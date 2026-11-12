# 목소리 부품 — 목소리 서버(8871)에 문장씩 보내 받은 소리를 이음새 다듬기(audio_smooth) 뒤 내보낸다.
#   - 글 정리(filters.tts_clean)는 여기서 한 번만 하고 서버에는 raw 로 보낸다.
#   - 첫 조각은 첫 쉼표에서 먼저 읽기(설정 목소리.첫쉼표_먼저읽기), 긴 문장(20글자+)은 쉼표에서 끊기(숫자 쉼표 제외).
#   - 영어 문장(생각 글이 새어 나온 것)은 외국어 모드가 아니면 읽지 않음. 답 대부분이 막히면 한마디 안내.
#   - 말 빠르기(목소리.말속도 1.0/1.2/1.4): 서버가 줄였으면(X-Speed-Applied 1) 그대로, 아니면 여기서 줄임(PyAV 있을 때).
import re

from loguru import logger
from pipecat.frames.frames import ErrorFrame, InterruptionFrame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.text.base_text_aggregator import Aggregation, TextType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

from .audio_smooth import SeamSmoother
from .filters import foreign_clean, lang_active, mostly_english, tts_clean
from .voice_link import VoiceLink, speech_rate, text_norm

SR = 24000


class FirstCommaAggregator(SimpleTextAggregator):
    def __init__(self, min_chars=1, long_chars=20, first_comma=True, **kw):
        super().__init__(**kw)
        self._first = True
        self._min = min_chars if first_comma else long_chars
        self._long = long_chars

    async def aggregate(self, text):
        if self._aggregation_type == TextType.TOKEN:
            async for a in super().aggregate(text):
                self._first = False
                yield a
            return
        for ch in text:
            if ch in ",，" and not self._text[-1:].isdigit() and \
                    len(re.sub(r"[^가-힣A-Za-z0-9]", "", self._text)) >= (self._min if self._first else self._long):
                out = (self._text + ch).strip(" ")
                self._text = ""
                self._first = False
                yield Aggregation(text=out, type=TextType.SENTENCE)
                continue
            async for a in super().aggregate(ch):
                self._first = False
                yield a

    async def flush(self):
        self._first = True
        return await super().flush()

    async def handle_interruption(self):
        self._first = True
        await super().handle_interruption()

    async def reset(self):
        self._first = True
        await super().reset()


class VoiceTTS(TTSService):
    def __init__(self, state, voice=None, **kw):
        async def _norm(text, _type):
            if text_norm.has_yawn(text):
                state.event("yawn", text=text[:60])
            if lang_active(state) and not re.search(r"[가-힣]", text):
                return foreign_clean(text)
            return tts_clean(text)

        vc = state.cfg.get("목소리") or {}
        # 첫 소리 기다림: 파이프캣 기본은 3초 안에 소리가 없으면 '소리 없음'으로 치고, 3번 이어지면 목소리를 못 쓰게 막는다.
        #   김비서 목소리가 그래픽 메모리 부족으로 CPU 로 돌면 첫 소리가 13~15초 걸려 대화 중 목소리가 끊겼음(0.1.3 실측)
        #   → 기다림을 늘리고(목소리.첫소리_기다림_초, 기본 20초) 막기는 끔. 느린 목소리는 목소리 서버가 윈도우 음성으로 바꿈.
        super().__init__(push_start_frame=True, push_stop_frames=True, sample_rate=SR,
                         stop_frame_timeout_s=float(vc.get("첫소리_기다림_초", 20) or 20), max_consecutive_zero_audio_contexts=0,
                         text_transforms=[("*", _norm)],
                         settings=TTSSettings(model=None, voice=str(vc.get("목소리") or "기본"), language=Language.KO), **kw)
        self.state = state
        self.mouth = voice or VoiceLink(state.cfg, on_yawn=lambda: state.event("yawn", text="(서버 표시)"))
        old = self._text_aggregator
        self._text_aggregator = FirstCommaAggregator(aggregation_type=old._aggregation_type, language=old.language,
                                                     first_comma=bool(vc.get("첫쉼표_먼저읽기", False)))
        self.smooth_on = bool(vc.get("이음새_다듬기", True))
        self.smoother = SeamSmoother(SR, seam_ms=float(vc.get("이음새_ms", 3)), fade_in_ms=float(vc.get("시작_페이드_ms", 4)),
                                     fade_out_ms=float(vc.get("끝_페이드_ms", 12)))
        self._turn_seen = None
        self._spoken_n = self._blocked_n = 0
        self._noticed = False

    @staticmethod
    def _hush(context_id):
        """읽지 않은 문장 자리의 아주 짧은 무음(10ms) — 소리 없이 끝난 문장이 다음 문장을 첫소리_기다림_초 만큼 붙잡지 않게."""
        return TTSAudioRawFrame(audio=bytes(2 * (SR // 100)), sample_rate=SR, num_channels=1, context_id=context_id)

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str):
        text = text.strip()
        if not re.search(r"[0-9A-Za-z가-힣]", text):
            yield self._hush(context_id)
            return
        st = self.state
        if self._turn_seen != st.turn_no:
            self._turn_seen, self._spoken_n, self._blocked_n, self._noticed = st.turn_no, 0, 0, False
        if mostly_english(text) and not lang_active(st):
            logger.warning(f"영어 문장이라 말하지 않음({len(text)}자)")
            self._blocked_n += 1
            if self._noticed or self._blocked_n < max(1, self._spoken_n):
                yield self._hush(context_id)
                return
            self._noticed = True
            text = "영어로 된 답이라 소리로는 읽지 않았어요. 화면을 봐 주세요."
        else:
            self._spoken_n += 1
        st.add_spoken(text)
        await self.start_tts_usage_metrics(text)
        speed = speech_rate.norm_speed(st.speed) or 1.0
        stretch = None
        sm = self.smoother if self.smooth_on else None
        if sm is not None:
            sm.start()
        first = True
        try:
            async for msg, pcm in self.mouth.speak(text, speed):
                kind = msg.get("type")
                if kind == "head":
                    if speed != 1.0 and not msg.get("speed_applied"):
                        try:
                            stretch = speech_rate.TimeStretch(speed, SR)
                            if not getattr(stretch, "ok", True):
                                stretch = None
                        except Exception as ex:  # noqa: BLE001
                            logger.warning(f"말 빠르기 처리기를 못 만들어 원래 속도로: {ex.__class__.__name__}")
                            stretch = None
                    continue
                if kind == "end":
                    if msg.get("error"):
                        yield ErrorFrame(error=msg["error"])
                        if first:
                            yield self._hush(context_id)
                    tail = stretch.flush() if stretch is not None else b""
                    if sm is not None:
                        tail = (sm.feed(tail) if tail else b"") + sm.end()
                    if tail:
                        yield TTSAudioRawFrame(audio=tail, sample_rate=SR, num_channels=1, context_id=context_id)
                    break
                if stretch is not None:
                    pcm = stretch.feed(pcm)
                if sm is not None and pcm:
                    pcm = sm.feed(pcm)
                if not pcm:
                    continue
                if first:
                    await self.stop_ttfb_metrics()
                    first = False
                yield TTSAudioRawFrame(audio=pcm, sample_rate=SR, num_channels=1, context_id=context_id)
        finally:
            await self.stop_ttfb_metrics()

    async def process_frame(self, frame, direction):
        if isinstance(frame, InterruptionFrame):
            await self.mouth.reset()
            self.smoother.drop()
        await super().process_frame(frame, direction)

    async def cleanup(self):
        await super().cleanup()
        await self.mouth.close()
