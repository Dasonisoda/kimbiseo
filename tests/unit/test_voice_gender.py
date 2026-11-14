# 성별 → 목소리 단위 시험 — 직접 고른 목소리 고정·자동 연결·자산 없음 대체·voices.json 보존.
#   python -m tests.unit.test_voice_gender
#
# 시험 자료는 임시 폴더와 가짜 registry 만 씁니다(실제 남성 참고음성이 나중에 들어와도 이 시험은 그대로 돕니다).
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import settings_api as S      # noqa: E402
from app.core import voice_choice as V      # noqa: E402


def fresh_cfg(user=None):
    """임시 사용자 설정으로 본체 설정을 읽는다(C.load 가 성별 자동 연결을 거는지도 같이 본다)."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    if user is not None:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(user, f, ensure_ascii=False)
    logs = []
    cfg = C.load(p, warn=logs.append)
    cfg["_settings_path"] = p
    return cfg, p, logs


def fake_registry(missing=False):
    """kimbiseo 는 실제 자산, kimbiseo_m 은 (원하면) 없는 임시 폴더인 registry."""
    real = V.load_registry()
    folder = os.path.join(tempfile.mkdtemp(), "kimbiseo_m_없음") if missing else (real["목록"]["kimbiseo_m"]["폴더"])
    return {"기본목소리": "kimbiseo", "성별_목소리": {"여": "kimbiseo", "남": "kimbiseo_m"},
            "목록": {"kimbiseo": {"폴더": real["목록"]["kimbiseo"]["폴더"]},
                     "kimbiseo_m": {"폴더": folder}}}


def test_gender_auto_selects_voice():
    """ㄱ) 사용자 설정에 목소리.목소리가 없으면 성별로 고른다 — 남 kimbiseo_m, 여 kimbiseo."""
    for sex, want in (("남", "kimbiseo_m"), ("여", "kimbiseo")):
        cfg, _p, _logs = fresh_cfg({"펫": {"성별": sex}})
        r = S.resolve_voice(cfg, registry=fake_registry())
        assert r["목소리"] == want, (sex, r)
        assert r["자동"] is True and r["고정"] is False, (sex, r)
        assert cfg["목소리"]["목소리"] == want, ("C.load 도 같은 값을 써야 함", sex, cfg["목소리"])


def test_explicit_voice_wins():
    """ㄴ) 목소리.목소리가 명시돼 있으면 성별 '남'이어도 그 값(고정)이 이긴다."""
    cfg, _p, _logs = fresh_cfg({"펫": {"성별": "남"}, "목소리": {"목소리": "kimbiseo"}})
    r = S.resolve_voice(cfg, registry=fake_registry())
    assert r["목소리"] == "kimbiseo" and r["실제"] == "kimbiseo", r
    assert r["자동"] is False and r["고정"] is True, r
    assert cfg["목소리"]["목소리"] == "kimbiseo", cfg["목소리"]


def test_missing_asset_falls_back_with_log():
    """ㄷ) kimbiseo_m 자산 폴더가 없으면 기본 kimbiseo 로 대체되고 이유 한 줄이 생긴다."""
    cfg, _p, _logs = fresh_cfg({"펫": {"성별": "남"}})
    logs = []
    r = S.resolve_voice(cfg, registry=fake_registry(missing=True), log=logs.append)
    assert r["목소리"] == "kimbiseo_m" and r["실제"] == "kimbiseo", r
    assert r["대체"] is True, r
    assert "참고음성 없음" in r["이유"] and "기본 kimbiseo 사용" in r["이유"], r
    assert logs and logs[-1] == r["이유"], logs


def test_save_gender_reloads_voice():
    """성별 저장 → 다시 읽기(C.reload_into)에서 목소리 해석이 새로 정해진다(끼어든 대화도 같은 cfg 를 봄)."""
    cfg, p, logs = fresh_cfg({"펫": {"성별": "여"}})
    clean, err, _warns = S.validate({"펫": {"성별": "남"}}, cfg)
    assert not err, err
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    assert cfg["목소리"]["목소리"] == "kimbiseo_m", cfg["목소리"]
    assert S.view(cfg)["목소리"]["해석"]["자동"] is True, S.view(cfg)["목소리"]["해석"]

    # 직접 고정한 목소리는 성별을 바꿔도 그대로(고정 존중)
    cfg, p, logs = fresh_cfg({"펫": {"성별": "남"}, "목소리": {"목소리": "kimbiseo"}})
    clean, err, _warns = S.validate({"펫": {"성별": "여"}}, cfg)
    assert not err, err
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    assert cfg["목소리"]["목소리"] == "kimbiseo", cfg["목소리"]
    assert S.view(cfg)["목소리"]["해석"]["고정"] is True, S.view(cfg)["목소리"]["해석"]


def test_settings_warning_shows_reason():
    """설정 저장 경고에도 같은 이유가 보인다(조용히 넘어가지 않음)."""
    cfg, _p, _logs = fresh_cfg()
    real = V.asset_problem
    V.asset_problem = lambda name, registry=None: "목소리 kimbiseo_m 참고음성 없음" if name == "kimbiseo_m" else ""
    try:
        _clean, err, warns = S.validate({"펫": {"성별": "남"}}, cfg)
    finally:
        V.asset_problem = real
    assert not err, err
    assert any("kimbiseo_m" in w and "기본 kimbiseo 사용" in w for w in warns), warns


def test_server_ensure_voice_falls_back_without_asset():
    """목소리 서버도 자산 없는 목소리를 요청받으면 기본 목소리로 대체하고 한 줄 남긴다."""
    spec = importlib.util.spec_from_file_location("kimbiseo_tts_server_test", os.path.join(ROOT, "voice", "tts_server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class FakeEngine:
        voices = {}

    logs = []
    mod.STATE.update(engine=FakeEngine(), engine_name="qwen", default_voice="kimbiseo",
                     voices={"kimbiseo_m": {"폴더": os.path.join(tempfile.mkdtemp(), "없음")}},
                     cfg={"목소리": {"참고음성_폴더": ""}}, voice_load={}, log=logs.append,
                     voice_fallback=None)
    assert mod.ensure_voice("kimbiseo_m") is None
    assert logs and "목소리 kimbiseo_m 참고음성 없음" in logs[-1] and "기본 kimbiseo 사용" in logs[-1], logs
    assert mod.STATE["voice_fallback"] and mod.STATE["voice_fallback"]["fallback"] == "kimbiseo"


def test_voices_json_intact():
    """ㄹ) voices.json 형식이 깨지지 않았고 기본목소리는 여전히 kimbiseo 다."""
    with open(os.path.join(ROOT, "voice", "voices.json"), encoding="utf-8-sig") as f:
        j = json.load(f)
    assert isinstance(j, dict) and isinstance(j.get("목록"), dict), j
    assert j["기본목소리"] == "kimbiseo", j["기본목소리"]
    assert j["성별_목소리"] == {"여": "kimbiseo", "남": "kimbiseo_m"}, j.get("성별_목소리")
    assert "kimbiseo" in j["목록"] and "kimbiseo_m" in j["목록"], j["목록"]
    assert j["목록"]["kimbiseo_m"]["이름"] == "김비서(남)", j["목록"]["kimbiseo_m"]
    assert j["목록"]["kimbiseo_m"]["폴더"] == "assets/voice/kimbiseo_m", j["목록"]["kimbiseo_m"]
    for name, item in j["목록"].items():
        assert isinstance(item.get("폴더"), str) and item["폴더"], (name, item)


def test_choices_offer_both_voices():
    """ㄱ) 설정 화면 목록(S.choices)에 김비서(여)·김비서(남) 둘 다 '준비: true' 로 나오고 저장도 된다."""
    ch = S.choices()
    voices = {x["id"]: x for x in ch["목소리"]}
    assert voices["kimbiseo"]["이름"] == "김비서(여)", voices["kimbiseo"]
    assert voices["kimbiseo_m"]["이름"] == "김비서(남)", voices["kimbiseo_m"]
    assert voices["kimbiseo"]["준비"] is True and voices["kimbiseo_m"]["준비"] is True, voices
    assert [x["id"] for x in ch["목소리"] if x["준비"]] == ["kimbiseo", "kimbiseo_m"], ch["목소리"]

    for name, sex in (("kimbiseo", "남"), ("kimbiseo_m", "여")):
        cfg, p, logs = fresh_cfg({"펫": {"성별": sex}})
        clean, err, _warns = S.validate({"목소리.목소리": name}, cfg)
        assert not err, (name, err)
        assert clean["목소리.목소리"] == name, (name, clean)
        assert C.save_user(cfg, S.nest(clean)) is True
        C.reload_into(cfg, p, warn=logs.append)
        assert cfg["목소리"]["목소리"] == name, ("직접 고른 목소리가 성별 자동 선택을 이겨야 함", name, cfg["목소리"])


def test_tone_auto_selects_by_gender():
    """ㄴ) 사용자 설정에 비서.말투가 없으면 남 → 편한 존댓말, 여 → 존댓말."""
    for sex, want in (("남", "편한 존댓말"), ("여", "존댓말")):
        cfg, _p, _logs = fresh_cfg({"펫": {"성별": sex}})
        assert cfg["비서"]["말투"] == want, (sex, cfg["비서"])
        r = S.resolve_tone(cfg)
        assert r["말투"] == want, (sex, r)
        assert r["자동"] is True and r["고정"] is False, (sex, r)


def test_explicit_tone_wins():
    """ㄷ) 비서.말투가 명시돼 있으면 성별 '남'이어도 그 값(고정)이 유지된다."""
    cfg, _p, _logs = fresh_cfg({"펫": {"성별": "남"}, "비서": {"말투": "존댓말"}})
    assert cfg["비서"]["말투"] == "존댓말", cfg["비서"]
    r = S.resolve_tone(cfg)
    assert r["말투"] == "존댓말" and r["고정"] is True and r["자동"] is False, r


def test_switch_gender_changes_voice_and_tone():
    """ㄹ) 성별을 '여'에서 '남'으로 저장하면 목소리(kimbiseo_m)와 말투(편한 존댓말)가 함께 바뀐다."""
    cfg, p, logs = fresh_cfg({"펫": {"성별": "여"}})
    assert cfg["목소리"]["목소리"] == "kimbiseo" and cfg["비서"]["말투"] == "존댓말"
    clean, err, _warns = S.validate({"펫": {"성별": "남"}}, cfg)
    assert not err, err
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    assert cfg["목소리"]["목소리"] == "kimbiseo_m", cfg["목소리"]
    assert cfg["비서"]["말투"] == "편한 존댓말", cfg["비서"]
    assert S.resolve_tone(cfg)["자동"] is True, S.resolve_tone(cfg)

    # 다시 여 로 바꾸면 둘 다 여 기본값으로 돌아온다.
    clean, err, _warns = S.validate({"펫": {"성별": "여"}}, cfg)
    assert not err, err
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    assert cfg["목소리"]["목소리"] == "kimbiseo", cfg["목소리"]
    assert cfg["비서"]["말투"] == "존댓말", cfg["비서"]


def main():
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("됨  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                print("안 됨", k, ex.__class__.__name__, ex)
    print("실패", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())