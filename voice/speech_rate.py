# 말 빠르기 — 목소리 소리 조각을 음 높이는 그대로 두고 길이만 줄인다(ffmpeg atempo = WSOLA, PyAV 로 프로세스 안에서 조각마다 흘려 처리).
#   Qwen3-TTS 에는 빠르기 조절이 없어서 만든 소리를 줄인다. 1.0 이면 아무것도 하지 않는다(원래와 똑같은 소리).
#   조각을 40ms 단위로 잘라 넣으면 처음 소리가 늦어지는 것은 약 40~50ms 뿐(큰 조각을 통째로 넣으면 한 조각만큼 늦게 나옴).
#   PyAV(av) 가 없는 환경이면 ok=False 로 원래 속도 그대로 돌려준다(부르는 쪽이 대신 처리).
import fractions
import re

SPEEDS = (1.0, 1.2, 1.4)
SR = 24000
_PIECE = 960  # 40ms


def norm_speed(v):
    """'1.2', '1.2배', 1.2, '빠르게'(=1.2), '더 빠르게'(=1.4), '원래'(=1.0) → 고를 수 있는 값(1.0/1.2/1.4) 또는 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        s = str(v).strip()
        if re.search(r"원래|보통|기본|처음|1\s*배(?!\s*[.]\s*\d)|한\s*배", s) and not re.search(r"1\s*[.]\s*[24]", s):
            return 1.0
        if re.search(r"(?:제일|가장|더|많이|아주|최대).*빠르", s):
            return 1.4
        if re.search(r"빠르", s) and not re.search(r"\d", s):
            return 1.2
        m = re.search(r"(\d+(?:\s*[.]\s*\d+)?)", s)
        if not m:
            return None
        x = float(m.group(1).replace(" ", ""))
    for sp in SPEEDS:
        if abs(x - sp) < 0.051:
            return sp
    return None


class TimeStretch:
    """한 문장 동안 쓰는 흐름 처리기. feed(int16 bytes) → 줄인 int16 bytes, 끝에 flush()."""

    def __init__(self, speed, sr=SR):
        self.speed = float(speed)
        self.sr = sr
        self.ok = False
        self.err = None
        self.n_in = 0
        self.n_out = 0
        self._pts = 0
        if abs(self.speed - 1.0) < 1e-3:
            return
        try:
            import av  # noqa: F401
            from av.filter import Graph
            self._av = av
            self._tb = fractions.Fraction(1, sr)
            g = Graph()
            src = g.add_abuffer(sample_rate=sr, format="s16", layout="mono", time_base=self._tb)
            t = g.add("atempo", f"{self.speed:.3f}")
            sink = g.add("abuffersink")
            src.link_to(t)
            t.link_to(sink)
            g.configure()
            self._g = g
            self.ok = True
        except Exception as ex:  # noqa: BLE001
            self.err = repr(ex)

    def _pull(self, out):
        av = self._av
        while True:
            try:
                fr = self._g.pull()
            except (av.error.BlockingIOError, av.error.EOFError):
                return
            out.append(bytes(fr.to_ndarray().astype("<i2").tobytes()))

    def feed(self, pcm: bytes) -> bytes:
        if not pcm:
            return b""
        self.n_in += len(pcm) // 2
        if not self.ok:
            self.n_out += len(pcm) // 2
            return pcm
        import numpy as np
        av = self._av
        x = np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype="<i2")
        out = []
        try:
            for i in range(0, len(x), _PIECE):
                part = x[i:i + _PIECE]
                fr = av.AudioFrame.from_ndarray(part.reshape(1, -1), format="s16", layout="mono")
                fr.sample_rate = self.sr
                fr.pts = self._pts
                fr.time_base = self._tb
                self._pts += len(part)
                self._g.push(fr)
                self._pull(out)
        except Exception as ex:  # noqa: BLE001  (만에 하나 깨지면 그 문장 나머지는 원래 속도로)
            self.err = repr(ex)
            self.ok = False
            b = b"".join(out) + x[i:].tobytes()
            self.n_out += len(b) // 2
            return b
        b = b"".join(out)
        self.n_out += len(b) // 2
        return b

    def flush(self) -> bytes:
        if not self.ok:
            return b""
        out = []
        try:
            self._g.push(None)
            self._pull(out)
        except Exception as ex:  # noqa: BLE001
            self.err = repr(ex)
        self.ok = False
        b = b"".join(out)
        self.n_out += len(b) // 2
        return b
