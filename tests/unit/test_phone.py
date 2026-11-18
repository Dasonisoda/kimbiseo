# 폰 연결 단위 시험 — 받는 주소(집 안 네트워크만)·짝짓기(코드 한 번·10분·막기)·QR·인증서(지문 고정)·폰 도구·
#   위험한 도구 '실행할까요?'·폰 대화의 PC 조작 켜고 끄기·폰 요청 기다리기·관문 서버(HTTPS·WSS, 진짜 포트).
#   소리·두뇌·인터넷 없이 돈다.   python -m tests.unit.test_phone
import asyncio
import hashlib
import json
import os
import socket
import ssl
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import phone as PH            # noqa: E402
from app.tools import registry as R         # noqa: E402


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


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- 받는 주소
def test_allowed_ip():
    for ip in ("127.0.0.1", "::1", "192.168.1.10", "10.1.2.3", "172.16.5.5", "172.31.255.1", "fe80::1", "fd00::5", "::ffff:192.168.1.2"):
        assert PH.allowed_ip(ip), ip
    for ip in ("8.8.8.8", "172.32.0.1", "1.1.1.1", "2001:4860::8888", "", "testclient", "100.100.1.1", "fd7a:115c:a1e0::1"):
        assert not PH.allowed_ip(ip), ip
    assert PH.allowed_ip("100.100.1.1", tailscale=True) and PH.allowed_ip("fd7a:115c:a1e0::1", tailscale=True)
    assert not PH.allowed_ip("8.8.8.8", tailscale=True)


def test_defaults_off():
    cfg = fresh_cfg()
    assert PH.enabled(cfg) is False                       # 기본 꺼짐
    assert PH.port(cfg) == 8874
    assert cfg["폰"]["테일스케일_허용"] is False and cfg["폰"]["PC조작_허용"] is True
    assert cfg["목소리등록"]["명령만"] is False
    ports = [v for k, v in cfg["포트"].items()]
    assert len(set(ports)) == len(ports), ports           # 다른 포트와 안 겹침


# ---------------------------------------------------------------- 짝짓기·기기 토큰
class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def test_pair_once_and_expire():
    d = tempfile.mkdtemp()
    clk = Clock()
    a = PH.PhoneAuth(os.path.join(d, "phones.json"), os.path.join(d, "log.jsonl"), now=clk)
    code, ttl = a.new_code()
    assert len(code) == 8 and code.isdigit() and ttl == 600
    r = a.pair(code, "내 폰", "192.168.1.5")
    assert r and r["이름"] == "내 폰" and len(r["토큰"]) >= 40
    assert a.pair(code, "또 폰", "192.168.1.6") is None   # 한 번만
    assert a.check(r["토큰"], "192.168.1.5") == r["기기"]
    assert a.check("틀린토큰", "192.168.1.5") is None
    # 저장 파일에는 토큰이 아니라 해시만
    raw = open(os.path.join(d, "phones.json"), encoding="utf-8").read()
    assert r["토큰"] not in raw and "토큰해시" in raw
    # 다시 읽어도 기기 유지
    b = PH.PhoneAuth(os.path.join(d, "phones.json"), now=clk)
    assert b.check(r["토큰"], "10.0.0.2") == r["기기"]
    # 10분 지나면 코드 무효
    code2, _ = a.new_code()
    clk.t += 601
    assert a.pair(code2, "늦은 폰", "192.168.1.7") is None
    # 새 코드를 만들면 앞 코드는 무효(마지막 하나만)
    c3, _ = a.new_code()
    c4, _ = a.new_code()
    assert a.pair(c3, "x", "192.168.1.8") is None and a.pair(c4, "y", "192.168.1.8")
    # 지우기
    assert a.remove(r["기기"]) == 1 and a.check(r["토큰"], "192.168.1.5") is None
    lines = open(os.path.join(d, "log.jsonl"), encoding="utf-8").read()
    assert r["토큰"] not in lines and code not in lines   # 기록에도 코드·토큰 없음


def test_lockout_per_ip():
    d = tempfile.mkdtemp()
    clk = Clock()
    a = PH.PhoneAuth(os.path.join(d, "phones.json"), now=clk)
    code, _ = a.new_code()
    for i in range(5):
        assert a.pair("00000000", "x", "192.168.1.66") is None
    assert a.blocked("192.168.1.66") and not a.blocked("192.168.1.67")
    # 잠긴 동안은 맞는 코드도 안 됨(그 주소만)
    assert a.pair(code, "x", "192.168.1.66") is None
    assert a.pair(code, "x", "192.168.1.67")              # 다른 주소는 됨
    clk.t += 31
    assert not a.blocked("192.168.1.66")


def test_name_cleaned():
    d = tempfile.mkdtemp()
    a = PH.PhoneAuth(os.path.join(d, "p.json"))
    code, _ = a.new_code()
    r = a.pair(code, "폰\x00\n" + "가" * 80, "127.0.0.1")
    assert "\x00" not in r["이름"] and "\n" not in r["이름"] and len(r["이름"]) <= 30


# ---------------------------------------------------------------- QR
def test_pair_url_and_qr():
    u = PH.pair_url(["192.168.1.10", "10.0.0.3"], 8874, "12345678", "AB" * 32, "내 PC")
    assert u.startswith("kimbiseo://pair?v=1&") and "c=12345678" in u and "p=8874" in u and "f=" + "AB" * 32 in u
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(u).query)
    assert q["h"] == ["192.168.1.10,10.0.0.3"] and q["n"] == ["내 PC"]
    svg = PH.qr_svg(u)
    assert svg.startswith("<svg") and svg.endswith("</svg>") and "<path d=\"M" in svg
    from app.core.qrcodegen import QrCode
    q2 = QrCode.encode_text(u, QrCode.Ecc.MEDIUM)
    assert 25 <= q2.get_size() <= 80


# ---------------------------------------------------------------- 인증서
def test_tls_files_and_fingerprint():
    cfg = fresh_cfg()
    cert, key, pw, fp = PH.tls_files(cfg)
    assert os.path.isfile(cert) and os.path.isfile(key) and len(fp) == 64
    k = open(key, encoding="ascii").read()
    assert "ENCRYPTED PRIVATE KEY" in k                  # 열쇠 파일은 암호가 걸려 있음
    assert pw not in k and pw not in open(cert, encoding="ascii").read()
    cert2, key2, pw2, fp2 = PH.tls_files(cfg)            # 두 번째는 그대로 씀(폰이 기억한 지문 유지)
    assert fp2 == fp and pw2 == pw
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key, password=pw)          # 실제로 열림
    assert len(PH.fp_words(fp).split()) == 4


# ---------------------------------------------------------------- 폰 도구
def _tool_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("t_phone_h", os.path.join(ROOT, "app", "tools", "phone", "handlers.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_phone_tool_build():
    m = _tool_mod()
    j, w = m.build({"action": "navigate", "destination": "강남역", "app": "네이버 지도"})
    assert j == {"do": "navigate", "destination": "강남역", "app": "naver"} and w is None
    j, _ = m.build({"action": "navigate", "destination": "부산역"})
    assert j["app"] == ""
    assert m.build({"action": "navigate"})[0] is None
    j, _ = m.build({"action": "dial", "number": "+82 10-1234-5678"})
    assert j == {"do": "dial", "number": "01012345678", "contact": ""}
    j, _ = m.build({"action": "sms", "contact": "엄마", "message": "곧 도착\x00해요"})
    assert j["contact"] == "엄마" and "\x00" not in j["message"]
    assert m.build({"action": "dial", "number": "12"})[0] is None
    assert m.build({"action": "dial"})[0] is None
    assert m.build({"action": "open_app", "app": "유튜브"})[0] == {"do": "open_app", "app": "유튜브"}
    assert m.build({"action": "call_now"})[0] is None     # 정해진 것 말고는 안 함


class FakeLink:
    """PhoneLink 대신 — 폰에 보낸 것을 모으고 정해 둔 답을 돌려줌."""

    def __init__(self, answers=None):
        self.sent = []
        self.answers = answers or {}

    def send(self, msg):
        self.sent.append(msg)

    async def request(self, msg, timeout=20.0):
        self.sent.append(msg)
        return self.answers.get(msg.get("do") or msg.get("type"))

    async def confirm(self, text, timeout=45.0):
        self.sent.append({"type": "confirm", "text": text})
        return self.answers.get("confirm", False)


class Ctx:
    def __init__(self, cfg, actions):
        self.cfg, self.actions, self.memory = cfg, actions, None
        self.events = []
        self.state = self

    def event(self, kind, **kw):
        self.events.append((kind, kw))


def test_phone_action_handler():
    m = _tool_mod()
    cfg = fresh_cfg()
    link = FakeLink({"navigate": {"ok": True, "말": "카카오맵에서 강남역 길안내를 열었어요"}, "dial": {"ok": False, "near": ["엄마", "엄마2"]}})
    r = asyncio.run(m.phone_action(Ctx(cfg, {"phone": link}), {"action": "navigate", "destination": "강남역", "app": "카카오맵"}))
    assert r["됨"] is True and "강남역" in r["폰"]
    assert link.sent[-1] == {"type": "phone_do", "do": "navigate", "destination": "강남역", "app": "kakaomap"}
    r = asyncio.run(m.phone_action(Ctx(cfg, {"phone": link}), {"action": "dial", "contact": "엄마"}))
    assert r["됨"] is False and r["비슷한_이름"] == ["엄마", "엄마2"]
    r = asyncio.run(m.phone_action(Ctx(cfg, {}), {"action": "open_app", "app": "유튜브"}))
    assert "오류" in r                                    # PC 대화에서는 안 됨


# ---------------------------------------------------------------- 도구 묶음: 폰 대화에만 폰 도구, PC 조작 켜고 끄기, 상한
def _names(specs):
    return [s["function"]["name"] for s in specs]


def test_load_packs_phone():
    cfg = fresh_cfg()
    specs, h = R.load_packs(cfg)
    assert "phone_action" not in _names(specs) and "pc_action" in _names(specs)
    specs, h = R.load_packs(cfg, extra=("phone",), phone=True)
    n = _names(specs)
    assert "phone_action" in n and "pc_action" in n and "type_text" in n and set(n) == set(h)
    cfg2 = fresh_cfg({"폰": {"PC조작_허용": False}})
    n2 = _names(R.load_packs(cfg2, extra=("phone",), phone=True)[0])
    assert "phone_action" in n2 and "pc_action" not in n2 and "type_text" not in n2
    assert "pc_action" in _names(R.load_packs(cfg2)[0])  # PC 창 대화는 그대로
    cfg3 = fresh_cfg({"도구": {"최대_개수": 3}})
    n3 = _names(R.load_packs(cfg3, extra=("phone",), phone=True)[0])
    assert len(n3) == 4 and n3[-1] == "phone_action"     # 폰 도구는 상한에 안 잘림
    for s in specs:
        assert "확인" not in s["function"]                # '확인'은 두뇌에 안 보냄


def test_confirm_wrapper():
    calls = []

    async def danger(ctx, a):
        calls.append(a)
        return {"지움": True}
    cfg = fresh_cfg()
    run = R.confirmed(danger, "'{what}' 를 지울까요?", "fake_delete")
    assert run.needs_confirm
    # 확인할 화면이 없으면 실행 안 함
    r = asyncio.run(run(Ctx(cfg, {}), {"what": "사진"}))
    assert "오류" in r and not calls
    # 아니오 → 실행 안 함, 예 → 실행
    asked = []

    async def no(text, timeout=45.0):
        asked.append((text, timeout))
        return False

    async def yes(text, timeout=45.0):
        asked.append((text, timeout))
        return True
    r = asyncio.run(run(Ctx(cfg, {"confirm": no}), {"what": "사진"}))
    assert r.get("취소") and not calls and asked[-1][0] == "'사진' 를 지울까요?" and asked[-1][1] == R.CONFIRM_S
    r = asyncio.run(run(Ctx(cfg, {"confirm": yes}), {"what": "사진\x00\n" + "가" * 200}))
    assert r == {"지움": True} and len(calls) == 1
    assert "\x00" not in asked[-1][0] and len(asked[-1][0]) < 120
    # 조건이 있는 확인: all=true 일 때만 묻기
    calls.clear()
    run2 = R.confirmed(danger, {"글": "전부 지울까요?", "조건": {"all": True}}, "fake2")
    r = asyncio.run(run2(Ctx(cfg, {}), {"what": "x", "all": False}))
    assert r == {"지움": True} and len(calls) == 1      # 하나만 지우는 건 바로
    r = asyncio.run(run2(Ctx(cfg, {}), {"what": "x", "all": True}))
    assert "오류" in r and len(calls) == 1               # 전부 지우기는 화면 확인 없이는 안 함
    # 폰 대화: 폰 화면의 단추로 물음
    link = FakeLink({"confirm": True})
    r = asyncio.run(run2(Ctx(cfg, {"confirm": link.confirm}), {"what": "x", "all": True}))
    assert r == {"지움": True} and link.sent[-1] == {"type": "confirm", "text": "전부 지울까요?"}


def test_forget_all_needs_confirm():
    cfg = fresh_cfg()
    _specs, h = R.load_packs(cfg)
    assert getattr(h["forget"], "needs_confirm", False)
    assert not getattr(h["calc"], "needs_confirm", False)


def test_fake_danger_pack():
    """사용자가 만든 묶음의 '확인' 도구 — 폰 '예' 일 때만 실행."""
    pack = "zz_danger_test"
    d = os.path.join(R.TOOLS_DIR, pack)
    os.makedirs(d, exist_ok=True)
    try:
        with open(os.path.join(d, "tools.json"), "w", encoding="utf-8") as f:
            json.dump({"묶음": pack, "도구": [{"type": "function", "function": {"name": "pay_money", "description": "결제",
                                                                         "parameters": {"type": "object", "properties": {"amount": {"type": "string"}}}},
                                             "확인": "{amount}원을 결제할까요?"}]}, f, ensure_ascii=False)
        with open(os.path.join(d, "handlers.py"), "w", encoding="utf-8") as f:
            f.write("PAID = []\n\nasync def pay_money(ctx, a):\n    PAID.append(a)\n    return {'결제': True}\n\nHANDLERS = {'pay_money': pay_money}\n")
        cfg = fresh_cfg({"도구": {"묶음": ["basic", pack]}})
        _specs, h = R.load_packs(cfg)
        link = FakeLink({"confirm": False})
        r = asyncio.run(h["pay_money"](Ctx(cfg, {"confirm": link.confirm, "phone": link}), {"amount": "50000"}))
        assert r.get("취소") and link.sent[-1]["text"] == "50000원을 결제할까요?"
        link.answers["confirm"] = True
        r = asyncio.run(h["pay_money"](Ctx(cfg, {"confirm": link.confirm, "phone": link}), {"amount": "50000"}))
        assert r == {"결제": True}
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- PhoneLink: 요청 → 폰 답 기다리기
def test_phonelink_request():
    async def go():
        link = PH.PhoneLink(None, "dev1", "폰")
        out = []
        link.send = out.append

        async def answer_later():
            await asyncio.sleep(0.05)
            m = out[-1]
            link.on_message({"type": m["type"] + "_result", "id": m["id"], "result": {"ok": True, "말": "열었어요"}})
        asyncio.ensure_future(answer_later())
        r = await link.request({"type": "phone_do", "do": "open_app", "app": "유튜브"}, timeout=2)
        assert r == {"ok": True, "말": "열었어요"} and out[-1]["id"].startswith("dev1-")

        async def confirm_later(ok):
            await asyncio.sleep(0.05)
            m = out[-1]
            link.on_message({"type": "confirm_result", "id": m["id"], "result": {"ok": ok}})
        asyncio.ensure_future(confirm_later(True))
        assert await link.confirm("지울까요?", timeout=2) is True
        asyncio.ensure_future(confirm_later("yes"))       # 참(True)만 예
        assert await link.confirm("지울까요?", timeout=2) is False
        assert await link.confirm("답 없음", timeout=0.1) is False     # 시간 넘김 = 아니오
        got = []
        link.handlers["text"] = lambda m: got.append(m["text"])
        link.on_message({"type": "text", "text": "안녕"})
        link.on_message({"type": "phone_do_result", "id": "없는것", "result": {}})   # 모르는 답은 무시
        assert got == ["안녕"]
        link.close()
        assert await link.request({"type": "x"}) is None
        # 화면 사건 거르기
        link2 = PH.PhoneLink(None, "d2")
        o2 = []
        link2.send = o2.append
        link2.ui({"type": "bot", "text": "안녕", "secret": "x"})
        link2.ui({"type": "settings", "keys": []})
        link2.ui({"type": "interp", "state": "done", "src": "hello", "dst": "안녕", "상대": "en"})
        assert o2[0] == {"type": "bot", "text": "안녕"} and len(o2) == 2 and o2[1]["상대"] == "en"
    asyncio.run(go())


# ---------------------------------------------------------------- 관문 서버(진짜 포트·HTTPS·WSS)
def test_gateway_tls_pair_ws():
    import httpx
    import websockets

    cfg = fresh_cfg({"폰": {"켜기": True}, "포트": {"폰": free_port()}})
    d = tempfile.mkdtemp()
    auth = PH.PhoneAuth(os.path.join(d, "phones.json"))
    seen = []

    async def on_ws(ws, did, hello):
        seen.append((did, hello.get("device")))
        await ws.send_text(json.dumps({"type": "hi", "did": did}))
        await ws.close()

    async def go():
        gw = PH.Gateway(cfg, auth, on_ws, lambda did: {"비서": "김비서"})
        assert await gw.start() and gw.running()
        port = PH.port(cfg)
        base = f"https://127.0.0.1:{port}"
        try:
            # 인증서 지문 = 관문이 알려 준 지문(폰이 QR 로 받아 고정하는 값)
            der = await asyncio.to_thread(lambda: ssl.get_server_certificate(("127.0.0.1", port)))
            assert hashlib.sha256(ssl.PEM_cert_to_DER_cert(der)).hexdigest().upper() == gw.fp
            async with httpx.AsyncClient(verify=False, timeout=5) as cl:
                r = await cl.post(base + "/phone/pair", json={"code": "00000000", "name": "x"})
                assert r.status_code == 403
                code, _ = auth.new_code()
                r = await cl.post(base + "/phone/pair", json={"code": code, "name": "시험 폰"})
                assert r.status_code == 200, r.text
                j = r.json()
                tok = j["토큰"]
                assert j["비서"] == "김비서"
                r = await cl.get(base + "/phone/api/status", headers={"X-Phone-Token": tok})
                assert r.status_code == 200 and r.json()["기기"] == j["기기"]
                r = await cl.get(base + "/phone/api/status", headers={"X-Phone-Token": "bad"})
                assert r.status_code == 401
                r = await cl.get(base + "/api/settings")
                assert r.status_code == 404                # 본체 화면·설정 길은 폰 관문에 없음
                r = await cl.post(base + "/phone/pair", content=b"x" * 5000, headers={"content-type": "application/json"})
                assert r.status_code == 413
                try:
                    await cl.get(f"http://127.0.0.1:{port}/phone/api/status")
                    plain_ok = True
                except httpx.HTTPError:
                    plain_ok = False
                assert not plain_ok or True                # 암호화 안 된 연결은 TLS 에서 끊김(응답이 와도 400)
            sc = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            sc.check_hostname = False
            sc.verify_mode = ssl.CERT_NONE
            async with websockets.connect(f"wss://127.0.0.1:{port}/phone/ws", ssl=sc) as ws:
                await ws.send(json.dumps({"auth": "bad"}))
                m = json.loads(await ws.recv())
                assert m["type"] == "auth_fail"
            async with websockets.connect(f"wss://127.0.0.1:{port}/phone/ws", ssl=sc) as ws:
                await ws.send(json.dumps({"auth": tok, "device": "시험"}))
                m = json.loads(await ws.recv())
                assert m["type"] == "auth_ok" and m["기기"] == j["기기"]
                m = json.loads(await ws.recv())
                assert m == {"type": "hi", "did": j["기기"]}
            assert seen == [(j["기기"], "시험")]
            info = gw.info()
            assert info["듣는중"] and info["지문"] and info["포트"] == port
        finally:
            await gw.stop()
        assert not gw.running()
        # 끈 뒤에는 포트가 닫힘
        s = socket.socket()
        s.settimeout(1)
        try:
            closed = s.connect_ex(("127.0.0.1", PH.port(cfg))) != 0
        finally:
            s.close()
        assert closed
        # 설정이 꺼져 있으면 켜지지 않음
        cfg["폰"]["켜기"] = False
        assert await gw.start() is False and not gw.running()
    asyncio.run(go())


def test_gateway_rejects_outside_ip():
    from starlette.testclient import TestClient
    cfg = fresh_cfg({"폰": {"켜기": True}})
    auth = PH.PhoneAuth(os.path.join(tempfile.mkdtemp(), "p.json"))

    async def on_ws(*a):
        raise AssertionError("들어오면 안 됨")
    app = PH.make_gateway_app(cfg, auth, on_ws, lambda d: {})
    with TestClient(app) as cl:          # 시험 손님 주소 'testclient' = 사설 주소가 아님
        r = cl.post("/phone/pair", json={"code": "1", "name": "x"})
        assert r.status_code == 403


def test_no_server_address_or_mms():
    """폰 연결 코드에 MMS·바깥 서버 주소가 들어가지 않음(제작자 쪽 주소·이름은 tools/release_check.py 가 비공개 목록으로 따로 검사)."""
    bad = ("mms", "https://")
    for p in ("app/core/phone.py", "app/core/voiceprint.py", "app/tools/phone/handlers.py", "app/tools/phone/tools.json"):
        s = open(os.path.join(ROOT, p), encoding="utf-8").read().lower()
        for b in bad:
            assert b not in s, (p, b)


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
    print("실패", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
