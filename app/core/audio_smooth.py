# 소리 이음새 다듬기 — 목소리 서버가 조각조각 보내는 소리를 이을 때 '틱·지직'이 나지 않게.
#   1) 이음새: 앞 조각 끝과 다음 조각 첫 표본의 높이가 갑자기 뛰면(앞 기울기로 예상한 값과 차이가 문턱 넘음),
#      다음 조각 앞 '이음새_ms' 동안 그 차이를 줄여 가며 더해 계단을 없앤다(선형으로 0 까지).
#   2) 시작: 문장 흐름 첫 '시작_페이드_ms' 는 0 에서 키움.  3) 끝: 마지막 '끝_페이드_ms' 는 0 으로 줄임
#      (끝 부분을 그만큼 들고 있다가 end() 때 줄여서 내보냄 — 그래서 소리가 끝_페이드_ms 만큼 늦게 나감).
#   4) 소리 줄이기(덕): 크기를 한 번에 바꾸면 말소리 중간이 꺾여 틱 → 40ms 에 걸쳐 바꿈(Ducker).
#   int16 모노 바이트를 받고 돌려준다.
import numpy as np


class SeamSmoother:
    def __init__(self, sr=24000, seam_ms=3, fade_in_ms=4, fade_out_ms=12, jump=0.02):
        self.sr = sr
        self.n_seam = max(1, int(sr * seam_ms / 1000))
        self.n_in = int(sr * fade_in_ms / 1000)
        self.n_out = int(sr * fade_out_ms / 1000)
        self.jump = float(jump) * 32768
        self.fixed = 0          # 이음새를 고친 횟수(시험 기록용)
        self.start()

    def start(self):
        """새 문장 흐름 시작(끼어들기·새 말 뒤)."""
        self.tail = np.zeros(0, np.float32)
        self.prev2 = None       # 지금까지 내보낸(또는 들고 있는) 마지막 두 표본
        self.pos = 0            # 흐름 시작부터 지난 표본 수(시작 페이드용)

    def _seam(self, x):
        if self.prev2 is None or len(x) == 0:
            return x
        a, b = self.prev2
        expect = b + (b - a)
        d = expect - x[0]
        if abs(d) > self.jump:
            n = min(self.n_seam, len(x))
            x = x.copy()
            x[:n] += d * (1.0 - np.arange(n, dtype=np.float32) / n)
            self.fixed += 1
        return x

    def feed(self, pcm: bytes) -> bytes:
        x = np.frombuffer(pcm, np.int16).astype(np.float32)
        if len(x) == 0:
            return b""
        x = self._seam(x)
        if self.pos < self.n_in:
            k = min(self.n_in - self.pos, len(x))
            ramp = (np.arange(self.pos, self.pos + k, dtype=np.float32) + 1) / (self.n_in + 1)
            x = x.copy()
            x[:k] *= ramp
        self.pos += len(x)
        buf = np.concatenate([self.tail, x])
        self.prev2 = (float(buf[-2]) if len(buf) >= 2 else 0.0, float(buf[-1]))
        if len(buf) <= self.n_out:
            self.tail = buf
            return b""
        out, self.tail = buf[:-self.n_out], buf[-self.n_out:]
        return np.clip(out, -32768, 32767).astype(np.int16).tobytes()

    def end(self) -> bytes:
        """흐름 끝 — 들고 있던 끝 부분을 0 으로 줄여 내보냄."""
        t = self.tail
        self.start()
        if len(t) == 0:
            return b""
        t = t * np.linspace(1.0, 0.0, len(t), dtype=np.float32)
        return np.clip(t, -32768, 32767).astype(np.int16).tobytes()

    def drop(self):
        """끼어들기 — 들고 있던 끝 부분은 버림(곧 소리가 멈춤)."""
        self.start()


class Ducker:
    """내보내는 소리 크기 바꾸기(사람이 말하기 시작하면 줄이고, 메아리·잡음이면 되돌림) — 목표까지 ramp_ms 에 걸쳐."""

    def __init__(self, sr=24000, ramp_ms=40):
        self.sr = sr
        self.ramp_n = max(1, int(sr * ramp_ms / 1000))
        self.gain = 1.0
        self.target = 1.0

    def set(self, target):
        self.target = float(min(1.0, max(0.0, target)))

    def apply(self, pcm: bytes) -> bytes:
        if self.gain == self.target == 1.0:
            return pcm
        x = np.frombuffer(pcm, np.int16).astype(np.float32)
        if len(x) == 0:
            return pcm
        g = np.full(len(x), self.target, np.float32)
        if self.gain != self.target:
            step = (self.target - self.gain) / self.ramp_n
            n = min(len(x), int(abs((self.target - self.gain) / step)) if step else 0)
            g[:n] = self.gain + step * (np.arange(n, dtype=np.float32) + 1)
            self.gain = float(g[-1]) if n == len(x) else self.target
        return np.clip(x * g, -32768, 32767).astype(np.int16).tobytes()


def clicks(pcm: bytes, thresh=0.25):
    """시험용: 이웃 표본 차이가 크기의 thresh(전체 눈금 비율) 넘게 튀는 곳 수 — 이음새 계단 찾기."""
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    if len(x) < 3:
        return 0
    d2 = np.abs(np.diff(x, 2))
    return int((d2 > thresh).sum())
