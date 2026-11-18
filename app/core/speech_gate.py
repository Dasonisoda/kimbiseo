# 말소리 문 — 귀(위스퍼)에 넘기기 전·뒤에 '사람 말이 맞는지' 한 번 더 본다(무음·잡음 헛받아쓰기 막기, 0.1.17).
#   실제 폰 시험(2026-11-18): 아무 말 안 했는데 1.6초 조각이 '고맙습니다.'·'안녕' 으로 받아써져 두뇌로 감.
#   pipecat 의 VAD 조각 = 말 앞 최대 1초 + 말 + 끝 무음(trailing) 이라 조각 길이로는 판단이 안 됨 → 실레로를 조각 전체에 다시 돌려
#   '말소리 길이(확률 0.5 이상 칸 합)'·'가장 높은 확률'·'말소리 칸의 소리 크기(dBFS)'를 잰다.
#   - 위스퍼 전: 말소리가 너무 짧거나(최소_말초) 확실한 말소리 칸이 없거나(최소_최대확률) 너무 작으면(최소_dB) 버림.
#   - 위스퍼 뒤: 말소리가 짧고(짧은단독_초) 약하거나 흐릿한데(짧은단독_dB·짧은단독_평균확률) 받아쓴 글이 인사·감사 같은 짧은 말 하나뿐이면
#     버림(위스퍼가 조용한 소리에 잘 지어내는 말). 또렷한 진짜 '안녕'은 통과(시험: 처음 기준은 진짜 '안녕'까지 버렸음).
#     '네·예·응' 은 확인 대답일 수 있어 소리가 약할 때(약할때_dB 아래)만 버림.
#   - 저장_폴더(시험용, 기본 빈칸=안 씀): 위스퍼에 넘긴 조각을 wav 로 남김(실제 소리 확인용 — 시험 뒤 지울 것).
import math
import os
import threading
import time
import wave

import numpy as np
from loguru import logger

from .state import norm_text

FRAME = 512            # 실레로 16kHz 한 칸 = 512 표본(32ms)
FRAME_S = FRAME / 16000

DEFAULTS = {
    "켜기": True,
    "최소_말초": 0.2,
    "최소_최대확률": 0.7,
    "최소_dB": -50.0,
    "짧은단독_초": 1.0,
    "짧은단독_dB": -35.0,          # 또렷한 진짜 '안녕'(시험: 말소리 0.58초 · -25dB · 확률 0.98)은 살림 — 약하거나 흐릿할 때만 버림
    "짧은단독_평균확률": 0.9,
    "짧은단독_문구": ["안녕", "안녕하세요", "고맙습니다", "감사합니다", "감사해요", "고마워요", "고마워", "수고하셨습니다",
                   "시청해주셔서감사합니다", "구독과좋아요부탁드립니다", "아", "음", "어", "으", "흠"],
    "약할때_문구": ["네", "예", "응", "어", "네네", "예예"],
    "약할때_dB": -38.0,
    "저장_폴더": "",
}


def conf(cfg):
    c = dict(DEFAULTS)
    c.update(((cfg.get("귀") or {}).get("말소리_문") or {}))
    return c


class SpeechGate:
    def __init__(self, cfg):
        self.cfg = cfg
        self._vad = None
        self._lock = threading.Lock()
        self._n = 0

    def _model(self):
        if self._vad is None:
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            v = SileroVADAnalyzer(sample_rate=16000)
            v.set_sample_rate(16000)     # 파이프라인 밖에서 쓰므로 직접(안 하면 표본 빈도 0 으로 모든 칸 오류)
            self._vad = v
        return self._vad

    def measure(self, audio: bytes, tail_s: float = 0.0) -> dict:
        """조각(16kHz 16비트 모노) → {전체초, 말초, 최대확률, 평균확률(말소리 칸), dB(말소리 칸, 없으면 전체)}. 끝 무음(tail_s)은 뺌."""
        a = np.frombuffer(audio, dtype=np.int16)
        if tail_s > 0:
            a = a[: max(0, len(a) - int(16000 * tail_s))]
        out = {"전체초": round(len(a) / 16000, 2), "말초": 0.0, "최대확률": 0.0, "평균확률": 0.0, "dB": -120.0}
        if len(a) < FRAME:
            return out
        with self._lock:
            v = self._model()
            try:
                v._model.reset_states()
            except Exception:  # noqa: BLE001
                pass
            probs, levels = [], []
            for i in range(0, len(a) - FRAME + 1, FRAME):
                ch = a[i:i + FRAME]
                probs.append(float(np.asarray(v.voice_confidence(ch.tobytes())).reshape(-1)[0]))
                levels.append(float(np.mean(ch.astype(np.float64) ** 2)))
        p = np.array(probs)
        sp = p >= 0.5
        out["말초"] = round(float(sp.sum()) * FRAME_S, 2)
        out["최대확률"] = round(float(p.max()), 2)
        out["평균확률"] = round(float(p[sp].mean()), 2) if sp.any() else 0.0
        lv = np.array(levels)
        ms = float(lv[sp].mean()) if sp.any() else float(lv.mean())
        out["dB"] = round(10 * math.log10(ms / (32768.0 ** 2)) if ms > 0 else -120.0, 1)
        return out

    def before(self, m: dict) -> str:
        """위스퍼 전 판정 — 버릴 까닭(빈 글 = 통과)."""
        c = conf(self.cfg)
        if not c.get("켜기", True):
            return ""
        if m["말초"] < float(c["최소_말초"]):
            return f"말소리 짧음({m['말초']}초)"
        if m["최대확률"] < float(c["최소_최대확률"]):
            return f"말소리 확률 낮음({m['최대확률']})"
        if m["dB"] < float(c["최소_dB"]):
            return f"소리 작음({m['dB']}dB)"
        return ""

    def after(self, text: str, m: dict) -> str:
        """위스퍼 뒤 판정 — 짧은 조각의 인사·감사 단독 / 약한 소리의 '네' 단독."""
        c = conf(self.cfg)
        if not c.get("켜기", True):
            return ""
        n = norm_text(text)
        if not n:
            return ""
        weak = m["dB"] < float(c["짧은단독_dB"]) or m["평균확률"] < float(c["짧은단독_평균확률"])
        if m["말초"] < float(c["짧은단독_초"]) and weak and n in {norm_text(x) for x in c.get("짧은단독_문구") or []}:
            return f"짧고 약한 조각의 단독 '{text.strip()[:12]}'(말소리 {m['말초']}초 · {m['dB']}dB · 확률 {m['평균확률']})"
        if n in {norm_text(x) for x in c.get("약할때_문구") or []} and m["dB"] < float(c["약할때_dB"]):
            return f"약한 소리의 단독 '{text.strip()[:12]}'({m['dB']}dB)"
        return ""

    def save(self, audio: bytes, m: dict, tag: str = "") -> str:
        """시험용: 설정 '귀.말소리_문.저장_폴더' 가 있을 때만 조각을 wav 로(파일 이름에 잰 값)."""
        d = str(conf(self.cfg).get("저장_폴더") or "").strip()
        if not d:
            return ""
        try:
            os.makedirs(d, exist_ok=True)
            self._n += 1
            name = time.strftime("%H%M%S") + f"_{self._n:03d}_말{m['말초']}_최대{m['최대확률']}_{m['dB']}dB{('_' + tag) if tag else ''}.wav"
            p = os.path.join(d, name)
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(audio)
            return p
        except Exception as ex:  # noqa: BLE001
            logger.debug(f"조각 저장 못 함: {ex}")
            return ""
