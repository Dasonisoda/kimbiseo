# 옷 → 목소리 단위 시험 — 펫이 입은 옷으로 목소리 고르기·'옷에 맞춤(자동)' 설정·모르는 목소리 안전 처리.
#   python -m tests.unit.test_voice_outfit
#
# 소리·모델·펫 프로그램 없이 돕니다(가짜 목소리 서버·가짜 펫은 이 PC 안 임시 포트).
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import settings_api as S      # noqa: E402
from app.core import voice_choice as V      # noqa: E402

F, M = {"id": "kimbiseo_f", "gender": "여성", "voice": ""}, {"id": "kimbiseo_m", "gender": "남성", "voice": ""}


def fresh_cfg(user=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    if user is not None:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(user, f, ensure_ascii=False)
    logs = []
    cfg = C.load(p, warn=logs.append)
    cfg["_settings_path"] = p
    return cfg, p, logs


def asset(ok=True):
    """참고음성이 있는(또는 없는) 임시 목소리 폴더."""
    d = tempfile.mkdtemp()
    if ok:
        with open(os.path.join(d, "참고목록.json"), "w", encoding="utf-8") as f:
            json.dump({"기본": {"wav": "default.wav", "text": "시험용"}}, f, ensure_ascii=False)
        with open(os.path.join(d, "default.wav"), "wb") as f:
            f.write(b"RIFF")
    return d


def registry(**more):
    reg = {"기본목소리": "kimbiseo", "성별_목소리": {"여": "kimbiseo", "남": "kimbiseo_m"},
           "옷목소리": {"성별": {"여성": "kimbiseo", "남성": "kimbiseo_m"}, "옷": {}},
           "목록": {"kimbiseo": {"폴더": asset()}, "kimbiseo_m": {"폴더": asset()}}}
    reg.update(more)
    return reg


def test_registry_has_outfit_table():
    """저장소 voices.json 에 옷→목소리 대응표가 있고, 가리키는 이름이 모두 목록에 있고 참고음성이 실제로 있다."""
    reg = V.load_registry()
    table = reg["옷목소리"]
    assert table["성별"] == {"여성": "kimbiseo", "남성": "kimbiseo_m"}, table
    assert isinstance(table["옷"], dict), table
    for name in list(table["성별"].values()) + list(table["옷"].values()) + list(reg["성별_목소리"].values()):
        assert name in reg["목록"], name
        assert V.asset_problem(name, reg) == "", (name, V.asset_problem(name, reg))


def test_outfit_gender_picks_voice():
    """남자 옷 → kimbiseo_m, 여자 옷 → kimbiseo. 성별 표기가 '남'·'남성' 어느 쪽이어도 된다. 옷을 모르면 None."""
    reg = registry()
    assert V.voice_for_outfit(M, reg) == "kimbiseo_m"
    assert V.voice_for_outfit(F, reg) == "kimbiseo"
    assert V.voice_for_outfit({"id": "x", "gender": "남", "voice": ""}, reg) == "kimbiseo_m"
    assert V.voice_for_outfit({"id": "x", "gender": "", "voice": ""}, reg) is None
    assert V.voice_for_outfit(None, reg) is None


def test_outfit_order_pack_then_id_then_gender():
    """순서 = 꾸러미 voice → 옷목소리.옷[id] → 옷목소리.성별[gender]."""
    reg = registry()
    reg["목록"]["special"] = {"폴더": asset()}
    reg["목록"]["byid"] = {"폴더": asset()}
    reg["옷목소리"]["옷"] = {"suit": "byid"}
    assert V.voice_for_outfit({"id": "suit", "gender": "남성", "voice": "special"}, reg) == "special"
    assert V.voice_for_outfit({"id": "suit", "gender": "남성", "voice": ""}, reg) == "byid"
    assert V.voice_for_outfit({"id": "other", "gender": "남성", "voice": ""}, reg) == "kimbiseo_m"


def test_outfit_skips_unknown_missing_and_rejected():
    """목록에 없는 이름·참고음성이 없는 이름·서버가 방금 거절한 이름은 건너뛰고 다음 후보로."""
    reg = registry()
    reg["목록"]["empty"] = {"폴더": asset(ok=False)}
    assert V.voice_for_outfit({"id": "x", "gender": "남성", "voice": "nobody"}, reg) == "kimbiseo_m"
    assert V.voice_for_outfit({"id": "x", "gender": "남성", "voice": "empty"}, reg) == "kimbiseo_m"
    assert V.voice_for_outfit(M, reg, skip={"kimbiseo_m"}) is None
    reg["목록"]["kimbiseo_m"] = {"폴더": asset(ok=False)}
    assert V.voice_for_outfit(M, reg) is None, "남자 목소리 자산이 없으면 옷으로는 못 고름(→ 성별 설정·기본으로)"


def test_voice_now_order():
    """직접 고른 목소리 > 입은 옷 > 펫 성별 설정."""
    reg = registry()
    cfg, _p, _l = fresh_cfg({"펫": {"성별": "여"}})
    assert V.voice_now(cfg, None, reg) == ("kimbiseo", "성별")
    assert V.voice_now(cfg, M, reg) == ("kimbiseo_m", "옷"), "설정 성별이 여여도 남자 옷을 입으면 남자 목소리"
    assert V.voice_now(cfg, F, reg) == ("kimbiseo", "옷")
    cfg, _p, _l = fresh_cfg({"펫": {"성별": "남"}})
    assert V.voice_now(cfg, None, reg) == ("kimbiseo_m", "성별")
    assert V.voice_now(cfg, F, reg) == ("kimbiseo", "옷"), "설정 성별이 남이어도 여자 옷을 입으면 여자 목소리"
    cfg, _p, _l = fresh_cfg({"펫": {"성별": "여"}, "목소리": {"목소리": "kimbiseo"}})
    assert V.voice_now(cfg, M, reg) == ("kimbiseo", "고정"), "직접 고른 목소리는 옷을 갈아입어도 그대로"


def test_auto_value_is_not_pinned():
    """설정의 '목소리.목소리' = "auto" 는 고르지 않은 것 — 본체 설정·목소리 서버 설정 둘 다."""
    cfg, _p, _l = fresh_cfg({"펫": {"성별": "남"}, "목소리": {"목소리": "auto"}})
    assert cfg["목소리"]["목소리"] == "kimbiseo_m", cfg["목소리"]
    assert cfg["_voice_choice"]["자동"] is True and cfg["_voice_choice"]["고정"] is False, cfg["_voice_choice"]
    assert S.view(cfg)["목소리"]["목소리"] == "auto", "화면에는 '옷에 맞춤(자동)'으로 보임"
    spec = importlib.util.spec_from_file_location("kimbiseo_voice_config_outfit", os.path.join(ROOT, "voice", "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for sex, want in (("남", "kimbiseo_m"), ("여", "kimbiseo")):
        c = {"펫": {"성별": sex}, "목소리": {"목소리": "auto"}}
        mod.resolve_voice(c, user={"목소리": {"목소리": "auto"}}, log=lambda _m: None)
        assert c["목소리"]["목소리"] == want, (sex, c)


def test_settings_auto_and_pin():
    """설정 화면: 자동 → 자동 은 안 바뀐 것, 자동일 때 같은 이름을 고르면 고정, 고정 → 자동 으로 되돌릴 수 있다."""
    cfg, p, logs = fresh_cfg({"펫": {"성별": "여"}})
    clean, err, _w = S.validate({"목소리": {"목소리": "auto"}}, cfg)
    assert not err and clean["목소리.목소리"] == "auto", (clean, err)
    assert S.changed_keys(cfg, clean) == [], "이미 자동이면 바뀐 것이 없음"
    clean, err, _w = S.validate({"목소리": {"목소리": "kimbiseo"}}, cfg)
    assert S.changed_keys(cfg, clean) == ["목소리.목소리"], "자동이 고른 것과 같은 이름이어도 직접 고르면 고정"
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    cfg["_settings_path"] = p
    assert cfg["_voice_choice"]["고정"] is True
    assert S.view(cfg)["목소리"]["목소리"] == "kimbiseo"
    clean, err, _w = S.validate({"목소리": {"목소리": "auto"}}, cfg)
    assert S.changed_keys(cfg, clean) == ["목소리.목소리"]
    assert C.save_user(cfg, S.nest(clean)) is True
    C.reload_into(cfg, p, warn=logs.append)
    assert cfg["_voice_choice"]["자동"] is True and cfg["목소리"]["목소리"] == "kimbiseo"
    _clean, err, _w = S.validate({"목소리": {"목소리": "nobody"}}, cfg)
    assert "모르는" in err["목소리.목소리"], err


def test_choices_male_ready():
    """처음 화면·설정에서 남자 펫과 남자 목소리를 고를 수 있다(준비 중 아님)."""
    ch = S.choices()
    pets = {x["id"]: x for x in ch["펫"]}
    assert pets["kimbiseo_m"]["준비"] is True and pets["kimbiseo_f"]["준비"] is True, pets
    assert ch["성별_추천"]["남"] == {"펫": "kimbiseo_m", "목소리": "kimbiseo_m"}, ch["성별_추천"]
    assert [x["id"] for x in ch["목소리"]] == ["auto", "kimbiseo", "kimbiseo_m"], ch["목소리"]


def test_server_unknown_voice_falls_back():
    """목소리 서버: 목록에 없는 voice 이름은 400 이 아니라 기본 목소리로 말하고 이유를 남긴다. 글자가 아니면 400."""
    spec = importlib.util.spec_from_file_location("kimbiseo_tts_server_outfit", os.path.join(ROOT, "voice", "tts_server.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class FakeEngine:
        prompts = {"기본": 1}
        voices = {}

    logs = []
    mod.STATE.update(engine=FakeEngine(), engine_name="qwen", default_voice="kimbiseo", voices={"kimbiseo": {"폴더": ""}},
                     cfg={"목소리": {"목소리": "kimbiseo", "참고음성_폴더": ""}}, log=logs.append, voice_fallback=None)
    mod.VOICES_FILE = os.path.join(tempfile.mkdtemp(), "없음.json")
    import types
    fake = types.ModuleType("tts_engine")      # 진짜 엔진 모듈은 torch 가 있어야 읽힘 — 감정 이름 함수만 흉내
    fake.emotion_name = lambda name: name
    old = sys.modules.get("tts_engine")
    sys.modules["tts_engine"] = fake
    try:
        body = {"text": "안녕하세요.", "voice": "nobody", "raw": True}
        mod.prepare(body)
        assert body["_voice"] is None, body
        assert mod.STATE["voice_fallback"]["fallback"] == "kimbiseo" and "nobody" in mod.STATE["voice_fallback"]["reason"], mod.STATE["voice_fallback"]
        assert any("목록에 없음" in x and "기본 kimbiseo 사용" in x for x in logs), logs
        body = {"text": "안녕하세요.", "voice": "kimbiseo", "raw": True}
        mod.prepare(body)
        assert body["_voice"] == "kimbiseo", body
        try:
            mod.prepare({"text": "안녕하세요.", "voice": 3, "raw": True})
            raise AssertionError("글자가 아닌 voice 는 거절해야 함")
        except ValueError:
            pass
    finally:
        if old is None:
            sys.modules.pop("tts_engine", None)
        else:
            sys.modules["tts_engine"] = old


def test_voice_link_retries_default_when_rejected():
    """목소리 서버가 voice 이름을 거절(400)하면 그 문장은 기본 목소리로 다시 말하고, 그 이름은 5분 쉰다."""
    from app.core import voice_link

    async def run():
        seen = []

        async def handle(reader, writer):
            n = 0
            while True:
                ln = await reader.readline()
                if ln in (b"\r\n", b"\n", b""):
                    break
                if ln.lower().startswith(b"content-length:"):
                    n = int(ln.split(b":")[1])
            req = json.loads((await reader.readexactly(n)).decode("utf-8"))
            seen.append(req.get("voice"))
            if req.get("voice"):
                body = json.dumps({"error": "voice 는 ['kimbiseo'] 중 하나"}, ensure_ascii=False).encode()
                writer.write(b"HTTP/1.1 400 X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            else:
                pcm = bytes(44) + b"\x01\x00" * 480
                writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"%x\r\n" % len(pcm) + pcm + b"\r\n0\r\n\r\n")
            await writer.drain()
            writer.close()

        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        c = C.deep_merge(C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None), {"포트": {"목소리": port}})
        link = voice_link.VoiceLink(c)
        link.voice = "kimbiseo_m"
        first = [ev async for ev, _ in link.speak("안녕하세요")]
        second = [ev async for ev, _ in link.speak("반갑습니다")]
        srv.close()
        return seen, first, second, link

    seen, first, second, link = asyncio.run(run())
    assert seen == ["kimbiseo_m", None, None], seen
    for evs in (first, second):
        assert [e["type"] for e in evs] == ["head", "audio", "end"] and not evs[-1].get("error"), evs
    assert link.bad_voices() == {"kimbiseo_m"}, link.bad_voices()


def test_pet_outfit_reads_extras():
    """본체가 펫에 '지금 입은 옷'을 묻는다(GET /extras). 펫이 꺼져 있거나 옷이 없으면 None, 잠깐 기억한다."""
    from app.pet_link import face

    state = {"body": {"ok": True, "skin": "kimbiseo_m", "gender": "남성", "packVoice": ""}, "hits": 0}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            state["hits"] += 1
            b = json.dumps(state["body"], ensure_ascii=False).encode("utf-8")
            self.send_response(200 if self.path == "/extras" else 404)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *_a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = {"포트": {"펫": srv.server_address[1]}}
    try:
        face.forget_outfit()
        assert face.pet_outfit(cfg) == {"id": "kimbiseo_m", "gender": "남성", "voice": ""}
        assert face.pet_outfit(cfg) == {"id": "kimbiseo_m", "gender": "남성", "voice": ""} and state["hits"] == 1, "0.5초 안에는 다시 묻지 않음"
        state["body"] = {"ok": True, "skin": "kimbiseo_f", "gender": "여성", "packVoice": "special"}
        face.forget_outfit()
        assert face.pet_outfit(cfg) == {"id": "kimbiseo_f", "gender": "여성", "voice": "special"}
        state["body"] = {"ok": True, "skin": None, "motions": []}
        face.forget_outfit()
        assert face.pet_outfit(cfg) is None, "옷이 없으면 None"
    finally:
        srv.shutdown()
        srv.server_close()
    face.forget_outfit()
    assert face.pet_outfit(cfg, timeout=0.3) is None, "펫이 꺼져 있으면 None"
    face.forget_outfit()


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
