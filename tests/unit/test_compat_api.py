# 'OpenAI 호환 API' 두뇌(내 API 열쇠) 단위 시험 — 이 PC 안의 가짜 OpenAI 호환 서버로(진짜 서비스·진짜 열쇠 없음).   python -B -m tests.unit.test_compat_api
#   가짜 서버는 '엄격한 바깥 서비스'처럼 군다: 열쇠가 틀리면 401, 표준에 없는 값(llama.cpp 전용 cache_prompt·id_slot·chat_template_kwargs 등)이 오면 400.
#   확인: 값 검사(주소·모델 필수 · 주소에 계정·비밀번호 금지) · 열쇠는 암호화해 저장하고 화면 값·결과·기록에 안 나옴 · 연결 시험 · 모델 목록 ·
#         두뇌 부품이 표준 값만 보냄.
import asyncio
import io
import json
import logging
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import keystore               # noqa: E402
from app.core import settings_api as S      # noqa: E402

OK = []
KEY = "sk-unit-test-" + "0123456789abcdef" * 2          # 지어낸 값(어느 서비스의 열쇠도 아님)
WRONG = "sk-" + "wrong-key-" + "0" * 12                    # 지어낸 틀린 열쇠
STANDARD = {"model", "messages", "max_tokens", "max_completion_tokens", "temperature", "stream", "stream_options", "tools", "tool_choice", "top_p", "stop",
            "frequency_penalty", "presence_penalty", "seed", "n", "user", "response_format"}
SEEN = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        return self.headers.get("Authorization") == "Bearer " + KEY

    def do_GET(self):
        if not self._auth():
            return self._send(401, {"error": {"message": "Incorrect API key provided"}})
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": "가짜-작은모델", "object": "model"}, {"id": "fake-large", "object": "model"}]})
        return self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        SEEN.append({"path": self.path, "keys": sorted(body), "auth_ok": self._auth()})
        if not self._auth():
            return self._send(401, {"error": {"message": "Incorrect API key provided"}})
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        extra = sorted(set(body) - STANDARD)
        if extra:
            return self._send(400, {"error": {"message": "Unrecognized request argument supplied: " + ", ".join(extra)}})
        if body.get("model") not in ("가짜-작은모델", "fake-large"):
            return self._send(404, {"error": {"message": "model not found"}})
        if body.get("tools"):
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "calc", "arguments": json.dumps({"expr": "3+4"})}}]}
        else:
            msg = {"role": "assistant", "content": "안녕하세요"}
        return self._send(200, {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]})


def fresh_cfg(user=None):
    d = tempfile.mkdtemp(prefix="김비서 호환 시험 ")
    p = os.path.join(d, "settings.json")
    user = dict(user or {})
    user.setdefault("경로", {})["자료"] = d.replace("\\", "/")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(user, f, ensure_ascii=False)
    cfg = C.load(p, warn=lambda m: None)
    cfg["_settings_path"] = p
    return cfg, d


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    cfg, data = fresh_cfg()
    os.environ.pop("KIMBISEO_KEY_compat", None)

    # ---- 값 검사
    _c, err, _w = S.validate({"두뇌": {"방식": "compat"}}, cfg)
    check("주소·모델 없이 'OpenAI 호환 API'를 고르면 저장을 막고 무엇이 빠졌는지 알려 줌", "두뇌.호환_주소" in err and "두뇌.호환_모델" in err, err)
    _c, err, _w = S.validate({"두뇌": {"방식": "compat", "호환_주소": "https://" + "user:pw" + "@" + "api.example.com/v1", "호환_모델": "m"}}, cfg)
    check("주소에 계정·비밀번호(…@)를 넣으면 거절(주소는 설정 파일에 남으므로)", "두뇌.호환_주소" in err and "열쇠" in err["두뇌.호환_주소"], err)
    _c, err, _w = S.validate({"두뇌": {"방식": "compat", "호환_주소": "ftp://x/v1", "호환_모델": "m"}}, cfg)
    check("http·https 가 아닌 주소는 거절", "두뇌.호환_주소" in err, err)
    clean, err, _w = S.validate({"두뇌": {"방식": "compat", "호환_주소": base + "/", "호환_모델": "가짜-작은모델"}}, cfg)
    check("바른 값은 통과(끝의 / 는 뗌)", not err and clean["두뇌.호환_주소"] == base and clean["두뇌.호환_모델"] == "가짜-작은모델", err)
    over = {"방식": "compat", "호환_주소": base, "호환_모델": "가짜-작은모델"}

    # ---- 기록 잡기(열쇠가 새는지 보려고)
    logs = io.StringIO()
    hdl = logging.StreamHandler(logs)
    logging.getLogger().addHandler(hdl)
    logging.getLogger().setLevel(logging.DEBUG)
    sink_id = None
    try:
        from loguru import logger as lg
        sink_id = lg.add(logs, level="DEBUG")
    except Exception:  # noqa: BLE001
        pass

    # ---- 열쇠 없이 · 틀린 열쇠
    r = asyncio.run(S.brain_test(cfg, over))
    check("열쇠가 없으면 연결 시험이 '열쇠가 맞지 않아요'로 알려 줌", r["ok"] is False and "열쇠" in r.get("오류", ""), r)
    S.save_secret(cfg, "compat", WRONG)
    r = asyncio.run(S.brain_test(cfg, over))
    check("틀린 열쇠 → '열쇠가 맞지 않아요(거절됨)'", r["ok"] is False and "거절" in r.get("오류", ""), r)
    m = asyncio.run(S.brain_models(cfg, over))
    check("틀린 열쇠로는 모델 목록도 안 받아짐", m["ok"] is False and "열쇠" in m.get("오류", ""), m)

    # ---- 맞는 열쇠
    saved = S.save_secret(cfg, "compat", "  " + KEY + "\n")
    check("열쇠 저장: 돌려주는 것은 가린 글뿐(값 그대로는 없음)", saved.get("있음") is True and KEY not in json.dumps(saved, ensure_ascii=False) and "보기" in saved, saved)
    raw = open(os.path.join(data, "secrets", "compat.bin"), "rb").read()
    check("열쇠 파일은 암호화돼 있음(파일 안에 열쇠 글자가 그대로 없음) · 설정 파일에도 없음",
          KEY.encode() not in raw and KEY not in open(cfg["_settings_path"], encoding="utf-8").read() and keystore.get("compat", cfg) == KEY)
    view = S.view(cfg)
    check("설정 화면 값에는 '열쇠 있음' 표시만 감", view["열쇠"].get("compat") is True and KEY not in json.dumps(view, ensure_ascii=False))
    r = asyncio.run(S.brain_test(cfg, over))
    check("맞는 열쇠 → 연결됨 · 답 '안녕하세요' · 도구 부르기도 됨", r["ok"] is True and r.get("답") == "안녕하세요" and r.get("도구") is True, r)
    m = asyncio.run(S.brain_models(cfg, over))
    check("모델 목록 불러오기", m["ok"] is True and m["모델"] == ["fake-large", "가짜-작은모델"], m)
    r404 = asyncio.run(S.brain_test(cfg, {**over, "호환_모델": "없는모델"}))
    check("없는 모델 이름 → '주소나 모델 이름이 맞지 않아요'", r404["ok"] is False and "모델" in r404.get("오류", ""), r404)
    dead = asyncio.run(S.brain_test(cfg, {**over, "호환_주소": "http://127.0.0.1:9/v1"}))
    check("꺼진 주소 → 연결할 수 없다고 알려 줌", dead["ok"] is False and "연결" in dead.get("오류", ""), dead)
    sent = [x for x in SEEN if x["path"] == "/v1/chat/completions" and x["auth_ok"]]
    check("연결 시험이 보낸 값은 표준 값뿐(llama.cpp 전용 값 없음)", sent and all(set(x["keys"]) <= STANDARD for x in sent), [x["keys"] for x in sent])
    leak = [n for n, t in (("연결 시험 결과", json.dumps([r, m, r404, dead], ensure_ascii=False)), ("기록", logs.getvalue())) if KEY in t or WRONG in t]
    check("열쇠 값이 결과·기록 어디에도 안 나옴", not leak, leak)

    # ---- 진짜 두뇌 부품(대화에 쓰는 것)이 보내는 값
    try:
        from app.core import brain as B
        user = {"두뇌": over}
        cfg2, d2 = fresh_cfg(user)
        S.save_secret(cfg2, "compat", KEY)
        st = type("St", (), {"stop_now": False, "no_tools_key": None})()
        llm = B.make_llm(st, cfg2, tool_names=["calc"], session_key="t")
        base_url = str(getattr(getattr(llm, "_client", None), "base_url", ""))
        ctx = {"messages": [{"role": "user", "content": "안녕"}]}
        try:
            params = llm.build_chat_completion_params(dict(ctx))
        except Exception as ex:  # noqa: BLE001  (판에 따라 인자 모양이 다르면 건너뜀)
            params = None
            print("    (두뇌 부품의 요청 만들기는 이 판에서 직접 부를 수 없어 건너뜀: " + type(ex).__name__ + ")")
        check("대화용 두뇌 부품: 주소·모델이 설정 값 그대로", llm.kind == "compat" and base_url.rstrip("/") == base and llm.model_name == "가짜-작은모델" if hasattr(llm, "model_name") else llm.kind == "compat" and base_url.rstrip("/") == base,
              (llm.kind, base_url))
        if params is not None:
            eb = params.get("extra_body") or {}
            check("대화용 두뇌 부품: llama.cpp 전용 값(cache_prompt·id_slot·chat_template_kwargs)·OpenAI 전용 값(prompt_cache_key)을 붙이지 않음",
                  not ({"cache_prompt", "id_slot", "chat_template_kwargs", "timings_per_token", "prompt_cache_key"} & set(eb)), eb)
        cfg3, _ = fresh_cfg({"두뇌": {"방식": "compat"}})
        try:
            B.make_llm(st, cfg3)
            check("주소·모델이 없으면 두뇌를 만들지 않고 쉬운 말로 알림", False)
        except RuntimeError as ex:
            check("주소·모델이 없으면 두뇌를 만들지 않고 쉬운 말로 알림", "주소와 모델" in str(ex), str(ex))
    except ImportError as ex:
        print("건너뜀 대화용 두뇌 부품 시험(부품 없음: " + str(ex)[:60] + ")")
    finally:
        logging.getLogger().removeHandler(hdl)
        if sink_id is not None:
            from loguru import logger as lg
            lg.remove(sink_id)
        srv.shutdown()
    bad = [n for n, ok in OK if not ok]
    print(f"\nOpenAI 호환 API 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
