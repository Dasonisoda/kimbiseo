# 시험용 전송부 — 마이크 대신 정해 둔 소리 파일(wav)을 실제 시간대로 흘려 넣고, 내보낸 소리를 시간대 그대로 기록한다.
#   마이크(16kHz) = 조용한 바탕(아주 작은 잡음) + 대본 시각에 놓은 말 wav + (방 메아리 켜면) 비서가 낸 소리를 늦추고 줄여 섞은 것.
#   기록: 왼쪽 = 마이크에 들어간 소리, 오른쪽 = 비서가 낸 소리(16kHz 로 바꿔)인 2채널 wav + 비서 소리만 24kHz wav.
import asyncio
import time
import wave

import numpy as np
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, StartFrame
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams

IN_SR = 16000
OUT_SR = 24000
CH = 320   # 20ms @16k


def read_wav16(path):
    with wave.open(path, "rb") as w:
        sr, n, chn, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("16비트 wav 만")
    x = np.frombuffer(raw, np.int16).astype(np.float32)
    if chn > 1:
        x = x.reshape(-1, chn).mean(1)
    if sr != IN_SR:
        t = np.arange(int(len(x) * IN_SR / sr)) * (sr / IN_SR)
        x = np.interp(t, np.arange(len(x)), x)
    return x.astype(np.float32)


def resample(x, sr_from, sr_to):
    if sr_from == sr_to or len(x) == 0:
        return x
    t = np.arange(int(len(x) * sr_to / sr_from)) * (sr_from / sr_to)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


class Room:
    """마이크·스피커가 있는 가짜 방. 시각 0 = start()."""

    def __init__(self, length_sec, echo_gain=0.0, echo_delay=0.12, noise_db=-62.0, seed=1):
        self.n = int(length_sec * IN_SR)
        self.mic = np.zeros(self.n + IN_SR, np.float32)
        rng = np.random.default_rng(seed)
        self.mic += rng.normal(0, 32768 * 10 ** (noise_db / 20), len(self.mic)).astype(np.float32)
        self.bot16 = np.zeros(self.n + IN_SR, np.float32)
        self.bot24 = []
        self.echo_gain = float(echo_gain)
        self.echo_delay = float(echo_delay)
        self.t0 = None
        self.pos = 0
        self.out_pos = 0      # 비서 소리가 놓일 다음 자리(16k 표본)

    def place(self, t_sec, path, gain=1.0):
        x = read_wav16(path) * gain
        i = int(t_sec * IN_SR)
        j = min(len(self.mic), i + len(x))
        self.mic[i:j] += x[: j - i]
        return len(x) / IN_SR

    def start(self):
        self.t0 = time.monotonic()

    def now(self):
        return 0.0 if self.t0 is None else time.monotonic() - self.t0

    def bot_audio(self, pcm24: bytes):
        """비서가 낸 소리 — 지금 시각(재생이 밀려 있으면 그 뒤)에 놓고, 메아리를 마이크에 섞는다."""
        x24 = np.frombuffer(pcm24, np.int16).astype(np.float32)
        self.bot24.append(pcm24)
        x = resample(x24, OUT_SR, IN_SR)
        i = max(int(self.now() * IN_SR), self.out_pos)
        j = min(len(self.bot16), i + len(x))
        if j > i:
            self.bot16[i:j] += x[: j - i]
            if self.echo_gain > 0:
                k = i + int(self.echo_delay * IN_SR)
                kk = min(len(self.mic), k + (j - i))
                if kk > k:
                    self.mic[k:kk] += x[: kk - k] * self.echo_gain
        self.out_pos = i + len(x)
        return len(x) / IN_SR

    def save(self, stereo_path, bot_path):
        n = max(self.pos, self.out_pos)
        m = np.clip(self.mic[:n], -32768, 32767).astype(np.int16)
        b = np.clip(self.bot16[:n], -32768, 32767).astype(np.int16)
        with wave.open(stereo_path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(IN_SR)
            w.writeframes(np.stack([m, b], 1).tobytes())
        with wave.open(bot_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(OUT_SR)
            w.writeframes(b"".join(self.bot24))


class WavInput(BaseInputTransport):
    def __init__(self, room, params, **kw):
        super().__init__(params, **kw)
        self.room = room
        self._task = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self.set_transport_ready(frame)
        if self._task is None:
            self.room.start()
            self._task = self.create_task(self._feed())

    async def _feed(self):
        r = self.room
        while r.pos + CH <= r.n:
            target = r.pos / IN_SR
            wait = target - r.now()
            if wait > 0:
                await asyncio.sleep(wait)
            chunk = np.clip(r.mic[r.pos:r.pos + CH], -32768, 32767).astype(np.int16).tobytes()
            r.pos += CH
            await self.push_audio_frame(InputAudioRawFrame(audio=chunk, sample_rate=IN_SR, num_channels=1))

    async def cleanup(self):
        if self._task is not None:
            await self.cancel_task(self._task)
            self._task = None
        await super().cleanup()


class WavOutput(BaseOutputTransport):
    def __init__(self, room, params, ducker=None, **kw):
        super().__init__(params, **kw)
        self.room = room
        self.ducker = ducker
        self._clock = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        pcm = frame.audio
        if self.ducker is not None:
            pcm = self.ducker.apply(pcm)
        dur = len(pcm) / 2 / frame.sample_rate
        now = time.monotonic()
        if self._clock is None or self._clock < now:
            self._clock = now
        wait = self._clock - now - 0.04
        if wait > 0:
            await asyncio.sleep(wait)
        self.room.bot_audio(pcm)
        self._clock += dur
        return True


class WavTransport(BaseTransport):
    def __init__(self, room, ducker=None):
        super().__init__()
        p = TransportParams(audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=IN_SR,
                            audio_out_sample_rate=OUT_SR)
        self._in = WavInput(room, p)
        self._out = WavOutput(room, p, ducker=ducker)

    def input(self):
        return self._in

    def output(self):
        return self._out
