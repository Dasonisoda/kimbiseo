# 내 목소리 등록 단위 시험 — 특징 계산(꼴·고정 값)·문(등록한 목소리만 명령 받기)·통역 중 켜기·끄기는 등록 목소리만·
#   등록(문장 3개 이상·섞인 목소리 거절·저장하는 것은 숫자 192개 평균뿐)·설정 값 검사.
#   진짜 모델 시험(선택): 환경변수 KIMBISEO_TITANET = nemo_en_titanet_small.onnx 경로,
#                         KIMBISEO_VOICE_WAVS = 16kHz 모노 wav 폴더(a_1.wav… = 한 사람 4개 이상, b_1.wav… = 다른 사람들). 없으면 그 시험만 건너뜀.
#   (실제 사람 목소리로 시험할 것 — 합성 음성(TTS)끼리는 다른 목소리여도 0.45~0.5 로 닮게 나옴)
#   python tests/unit/test_voiceprint.py
import asyncio
import glob
import json
import os
import shutil
import sys
import tempfile
import wave

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import interp                 # noqa: E402
from app.core import settings_api as S      # noqa: E402
from app.core import voiceprint as V        # noqa: E402

SKIPPED = []


def fresh_cfg(user=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    u = {"경로": {"자료": os.path.join(d, "data"), "모델": os.path.join(d, "models"), "캐시": os.path.join(d, "cache"),
                 "로그": os.path.join(d, "logs")}}
    u.update(user or {})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(u, f, ensure_ascii=False)
    cfg = C.load(p, warn=lambda m: None)
    cfg["_settings_path"] = p
    return cfg


def tone(sec, f0=140.0, sr=16000, seed=0):
    """말소리 비슷한 신호(기본음 + 배음 + 떨림) — 모델 없는 시험용."""
    t = np.arange(int(sec * sr)) / sr
    rng = np.random.default_rng(seed)
    x = sum(np.sin(2 * np.pi * f0 * k * t * (1 + 0.01 * np.sin(2 * np.pi * 3 * t))) / k for k in range(1, 8))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 2.5 * t) ** 2
    return (0.2 * x * env + 0.005 * rng.standard_normal(len(t))).astype(np.float32)


def pcm(x):
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------- 특징
def test_features_shape():
    x = tone(2.0)
    f = V.features(x)
    assert f.shape[1] == V.NMEL and abs(f.shape[0] - (len(x) - V.WIN) // V.HOP - 1) <= 1
    n = V.normalize(f)
    assert np.allclose(n.mean(0), 0, atol=1e-4) and np.allclose(n.std(0, ddof=1), 1, atol=1e-2)
    assert V.features(np.zeros(100, np.float32)).shape == (0, V.NMEL)
    mb = V.mel_bank(fmax=V.FMAX)
    assert mb.shape == (V.NMEL, V.NFFT // 2 + 1) and (mb >= 0).all()


def test_speech_part_trims_silence():
    x = np.concatenate([np.zeros(16000, np.float32), tone(1.5), np.zeros(16000, np.float32)])
    y = V.speech_part(x)
    assert 1.3 * 16000 <= len(y) <= 1.8 * 16000
    assert len(V.speech_part(np.zeros(32000, np.float32))) == 0


def test_cosine():
    a = np.array([1, 0, 0], np.float32)
    assert V.cosine(a, a) == 1.0 and V.cosine(a, np.array([0, 1, 0], np.float32)) == 0.0
    assert V.cosine(a, np.zeros(3, np.float32)) == 0.0


# ---------------------------------------------------------------- 설정·문(모델 없이)
def test_defaults_and_settings():
    cfg = fresh_cfg()
    vp = V.VoicePrint(cfg)
    assert cfg["목소리등록"]["명령만"] is False and abs(vp.threshold() - 0.40) < 1e-9 and abs(vp.threshold(True) - 0.32) < 1e-9
    assert S.FIELDS["목소리등록.문턱"][0]["v"] == (0.35, 0.4, 0.48)
    assert vp.gate_on() is False                          # 기본 꺼짐
    assert vp.model_path().endswith(os.path.join("models", "titanet-small", "nemo_en_titanet_small.onnx"))
    clean, err, _ = S.validate({"목소리등록": {"명령만": True, "문턱": 0.48}}, cfg)
    assert not err and clean["목소리등록.명령만"] is True
    _c, err, _ = S.validate({"목소리등록": {"문턱": 0.1}}, cfg)
    assert err                                            # 정한 세 값만
    _c, err, _ = S.validate({"폰": {"켜기": True, "테일스케일_허용": False, "PC조작_허용": False}}, cfg)
    assert not err
    assert S.FIELDS["폰.켜기"][1] == "폰" and S.when_groups(["폰.켜기"])["폰"] == ["폰 연결 켜기"]


def test_gate_needs_registration_and_model():
    cfg = fresh_cfg({"목소리등록": {"명령만": True}})
    vp = V.VoicePrint(cfg)
    assert vp.gate_on() is False                          # 등록 없음 → 안 막음
    vp.me = {"emb": np.ones(192, np.float32), "n": 3}
    assert vp.gate_on() is False                          # 모델 파일 없음 → 안 막음(말로 아무것도 못 하게 잠기지 않게)
    os.makedirs(os.path.dirname(vp.model_path()), exist_ok=True)
    open(vp.model_path(), "wb").close()
    assert vp.gate_on() is True
    cfg["목소리등록"]["명령만"] = False
    assert vp.gate_on() is False
    assert vp.is_me({"점수": None}) is False and vp.is_me({"점수": 0.41, "짧음": False}) is True
    assert vp.is_me({"점수": 0.35, "짧음": False}) is False and vp.is_me({"점수": 0.35, "짧음": True}) is True


class FakeVP:
    def __init__(self, score, on=True):
        self.score, self.on = score, on
        self.calls = 0

    def gate_on(self):
        return self.on

    def score_pcm(self, _pcm):
        self.calls += 1
        return {"점수": self.score, "등록됨": True, "짧음": False, "초": 2.0, "ms": 1}

    def is_me(self, r):
        return r["점수"] is not None and r["점수"] >= 0.4


class FakeEar:
    def __init__(self, text, lang="ko"):
        self.text, self.lang = text, lang

    async def transcribe(self, audio, langs=None, **kw):
        return {"text": self.text, "sec": 0.05, "audio_sec": 2.0, "lang": self.lang, "lang_conf": 0.99}

    async def close(self):
        pass


def _stt(cfg, text, vp, lang="ko"):
    from app.core.state import SessionState
    from app.core.stt import EarSTT
    events = []
    st = SessionState(cfg, lambda ev: events.append(ev))
    s = EarSTT(st, 1, ear=FakeEar(text, lang), voiceprint=vp)

    async def nothing(*a, **k):
        return None
    s.start_processing_metrics = nothing
    s.stop_processing_metrics = nothing
    return s, st, events


async def _run(s, sec=2.0):
    out = []
    async for f in s.run_stt(pcm(tone(sec))):
        out.append(f)
    return out


def _kinds(frames):
    return [type(f).__name__ for f in frames]


def test_gate_normal_talk():
    cfg = fresh_cfg()
    for score, gate, want in ((0.2, True, False), (0.7, True, True), (0.2, False, True)):
        vp = FakeVP(score, on=gate)
        s, st, ev = _stt(cfg, "오늘 날씨 어때", vp)
        frames = asyncio.run(_run(s))
        got = "TranscriptionFrame" in _kinds(frames)
        assert got == want, (score, gate, _kinds(frames))
        gated = [e for e in ev if e.get("type") == "voice_gate"]
        assert bool(gated) == (not want), ev
        if gate:
            assert vp.calls == 1
        else:
            assert vp.calls == 0                          # 문이 꺼져 있으면 점수도 안 냄
    s, st, ev = _stt(cfg, "오늘 날씨 어때", None)
    assert "TranscriptionFrame" in _kinds(asyncio.run(_run(s)))   # 목소리 등록 부품이 없어도 그대로


def test_gate_interp_commands():
    """통역 중: 상대(등록 목소리 아님)의 '통역 그만'은 끄지 않고 번역만 · 등록 목소리면 끔."""
    cfg = fresh_cfg()
    calls = []

    async def fake_translate(cfg_, text, src, dst, hist):
        calls.append((text, src, dst))
        return "Stop interpreting", "가짜", 0.01
    real = interp.translate
    interp.translate = fake_translate
    try:
        interp.turn_on(cfg, "en")
        s, st, ev = _stt(cfg, "통역 그만", FakeVP(0.1))
        frames = asyncio.run(_run(s))
        assert interp.active(cfg), "등록 목소리가 아닌데 통역이 꺼짐"
        assert calls and calls[-1][0] == "통역 그만"            # 번역만 함
        assert any(e.get("type") == "voice_gate" and e.get("interp") for e in ev)
        assert "TranscriptionFrame" not in _kinds(frames)          # 두뇌 대화로 안 넘김
        s, st, ev = _stt(cfg, "통역 그만", FakeVP(0.8))
        asyncio.run(_run(s))
        assert not interp.active(cfg), "등록 목소리인데 안 꺼짐"
        # 문이 꺼져 있으면 누구 말이든 끔(지금까지와 같음)
        interp.turn_on(cfg, "en")
        s, st, ev = _stt(cfg, "통역 그만", FakeVP(0.1, on=False))
        asyncio.run(_run(s))
        assert not interp.active(cfg)
        # 상대 외국어 말은 점수와 상관없이 번역
        interp.turn_on(cfg, "en")
        calls.clear()
        s, st, ev = _stt(cfg, "Where is the station?", FakeVP(0.1), lang="en")
        asyncio.run(_run(s))
        assert calls and calls[-1][1] == "en" and interp.active(cfg)
    finally:
        interp.translate = real
        interp.turn_off("시험 끝")


def test_gate_on_command_normal_mode():
    """통역이 꺼져 있을 때 '통역해 줘'도 등록 목소리만(문이 켜져 있으면)."""
    cfg = fresh_cfg()
    interp.turn_off("시험")
    s, st, ev = _stt(cfg, "영어 통역해 줘", FakeVP(0.1))
    asyncio.run(_run(s))
    assert not interp.active(cfg)
    s, st, ev = _stt(cfg, "영어 통역해 줘", FakeVP(0.9))
    asyncio.run(_run(s))
    assert interp.active(cfg)
    interp.turn_off("시험 끝")


def test_enroll_rules_with_fake_model():
    """등록 규칙(모델 대신 정해진 임베딩) — 짧은 문장 빼기·3개 미만 거절·섞인 목소리 거절·저장 파일에는 평균뿐."""
    cfg = fresh_cfg()
    vp = V.VoicePrint(cfg)
    base = np.random.default_rng(1).standard_normal(192).astype(np.float32)
    other = np.random.default_rng(2).standard_normal(192).astype(np.float32)
    plan = []

    def fake_embed(w):
        sec = len(V.speech_part(w)) / V.SR
        if sec < V.MIN_SEC:
            return None, sec
        return plan.pop(0), sec
    vp.embed = fake_embed
    rng = np.random.default_rng(3)
    plan[:] = [base + 0.1 * rng.standard_normal(192).astype(np.float32) for _ in range(2)]
    ok, msg, _ = vp.enroll([pcm(tone(2.0)), pcm(tone(2.0)), pcm(tone(0.3))])
    assert not ok and "2개" in msg
    plan[:] = [base, base + 0.1, other, base]
    ok, msg, info = vp.enroll([pcm(tone(2.0))] * 4)
    assert not ok and "달라요" in msg
    plan[:] = [base + 0.1 * rng.standard_normal(192).astype(np.float32) for _ in range(4)]
    ok, msg, info = vp.enroll([pcm(tone(2.0, seed=i)) for i in range(4)])
    assert ok, msg
    d = json.load(open(vp.me_path(), encoding="utf-8"))
    assert set(d) == {"emb", "n", "등록", "점수", "모델", "말_초"} and len(d["emb"]) == 192 and d["n"] == 4
    assert not glob.glob(os.path.join(vp.folder(), "*.wav")) and not glob.glob(os.path.join(vp.folder(), "*.pcm"))   # 소리는 저장 안 함
    assert vp.view()["등록됨"] and vp.view()["문장"] == 4
    vp.forget()
    assert not os.path.exists(vp.me_path()) and vp.me is None


# ---------------------------------------------------------------- 진짜 모델(선택)
def _read_wav(p):
    with wave.open(p, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        return w.readframes(w.getnframes())


def test_real_model():
    onnx = os.environ.get("KIMBISEO_TITANET", "")
    wavs = os.environ.get("KIMBISEO_VOICE_WAVS", "")
    if not (os.path.isfile(onnx) and os.path.isdir(wavs)):
        SKIPPED.append("test_real_model(KIMBISEO_TITANET·KIMBISEO_VOICE_WAVS 없음)")
        return
    a = sorted(glob.glob(os.path.join(wavs, "a_*.wav")))
    b = sorted(glob.glob(os.path.join(wavs, "b_*.wav")))
    assert len(a) >= 4 and len(b) >= 2, (len(a), len(b))
    cfg = fresh_cfg({"목소리등록": {"명령만": True}})
    vp = V.VoicePrint(cfg)
    os.makedirs(os.path.dirname(vp.model_path()), exist_ok=True)
    shutil.copyfile(onnx, vp.model_path())
    assert vp.ready() and not vp.gate_on()
    ok, msg, info = vp.enroll([_read_wav(p) for p in a[:3]])
    assert ok, msg
    assert vp.gate_on()
    same = [vp.score_pcm(_read_wav(p)) for p in a[3:]]
    diff = [vp.score_pcm(_read_wav(p)) for p in b]
    print("    같은 사람", [r["점수"] for r in same], "다른 사람", [r["점수"] for r in diff], "ms", [r["ms"] for r in same + diff])
    assert all(vp.is_me(r) for r in same), same
    assert not any(vp.is_me(r) for r in diff), diff
    assert min(r["점수"] for r in same) - max(r["점수"] for r in diff) > 0.1
    assert max(r["ms"] for r in same + diff) < 1500


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("됨  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                import traceback
                print("안 됨", k, ex.__class__.__name__, ex)
                traceback.print_exc()
    for s in SKIPPED:
        print("건너뜀", s)
    print("실패", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
