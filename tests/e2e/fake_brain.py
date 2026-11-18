# 시험용 가짜 두뇌 — OpenAI 꼴 /v1/chat/completions(스트리밍·한 번에) + llama-server 꼴 /apply-template·/tokenize·/health.
#   진짜 모델 없이 본체의 길(도구 호출·글로 쓴 도구 호출 건지기·캐시 가드·두뇌 바꾸기)을 시험한다. 규칙으로만 답한다.
#   python fake_brain.py --port 18990 [--log 요청기록.jsonl] [--require-key 환경변수이름] [--trip N] [--text-tools]
#     --require-key : 머리글 Authorization 의 열쇠가 그 환경변수 값과 같아야 답함(바깥 두뇌 흉내). 열쇠 값은 기록하지 않음.
#     --trip N      : 캐시를 쓰는(cache_prompt 가 거짓이 아닌) 스트리밍 요청 처음 N번에 '말이 안 되게 큰' cache_n 을 돌려줌
#                     (= 다른 대화 내용으로 오염된 칸 흉내). 가드가 버리고 캐시 끈 채 다시 묻는지 본다.
#     --text-tools  : 도구를 진짜 tool_calls 대신 답 글(get_weather{...} 꼴)로 씀(작은 모델 버릇 흉내 → 건지기 시험).
#     --loop-tools  : 도구를 줄 때마다 calc 를 또 부름(도구 폭주 멈춤 시험). 도구를 안 주면(tool_choice none) 글로 답함.
#   이 PC 127.0.0.1 에서만 듣는다.
import argparse
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

A = None
LOCK = threading.Lock()
COUNT = {"stream": 0, "trip_left": 0, "all": 0}
SLOTS = {}   # 칸 번호 → 마지막으로 읽힌 글(캐시 흉내: 공통 앞부분만 다시 씀)
Q = '<|"|>'


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(x.get("text") or "") for x in c if isinstance(x, dict))
    return str(c or "")


def render(messages, tools=None):
    """llama-server /apply-template 흉내 — 같은 앞부분이면 같은 글."""
    out = []
    if tools:
        out.append("<tools>" + json.dumps(tools, ensure_ascii=False, sort_keys=True) + "</tools>")
    for m in messages or []:
        body = _text(m.get("content"))
        if m.get("tool_calls"):
            body += json.dumps(m["tool_calls"], ensure_ascii=False, sort_keys=True)
        out.append(f"<|turn>{m.get('role')}\n{body}<turn|>")
    return "\n".join(out) + "\n<|turn>model\n"


def tokens(s):
    return [ord(ch) for ch in s]   # 글자 하나 = 토큰 하나


def name_of(messages):
    sysm = next((_text(m.get("content")) for m in messages if m.get("role") == "system"), "")
    m = re.search(r"너는 '([^']+)'라는", sysm)
    return m.group(1) if m else "비서"


def facts_in(messages):
    sysm = next((_text(m.get("content")) for m in messages if m.get("role") == "system"), "")
    return sysm


def decide(messages, tools):
    """→ ("text", 글) 또는 ("tool", 이름, 인자)."""
    names = {((t.get("function") or t).get("name")) for t in (tools or [])}
    tail = [m for m in messages if m.get("role") != "assistant" or m.get("tool_calls")]
    last = tail[-1] if tail else {}          # 끝에 붙은 비서 말('날씨 확인해 볼게요' 같은 먼저 한마디)은 건너뜀
    if last.get("tool_calls"):
        last = {}
    nm = name_of(messages)
    if last.get("role") == "tool" and not (A is not None and A.loop_tools and "calc" in names):
        r = _text(last.get("content"))
        if "기온" in r or "날씨" in r or "temperature" in r.lower() or "최고" in r:
            m = re.search(r"최고[^0-9-]*(-?\d+)", r)
            return ("text", f"내일 서울은 낮 최고 {m.group(1) if m else '몇'}도쯤이에요. 외출하실 때 참고하세요.")
        if '"답"' in r:
            m = re.search(r'"답":\s*(-?[\d.]+)', r)
            return ("text", f"계산해 보니 {m.group(1) if m else '?'}이에요.")
        if "저장" in r or "이미있음" in r:
            return ("text", "네, 기억할게요.")
        if '"취소"' in r:
            return ("text", "네, 실행하지 않았어요.")
        if '"폰"' in r or "폰에서" in r:
            return ("text", "폰에서 열었어요." if '"됨": true' in r else "폰에서 열지 못했어요.")
        if '"열림"' in r or "검색" in r or '"시험"' in r:
            return ("text", "PC에서 열었어요.")
        if "찾음" in r or "지식" in r or "대화" in r:
            return ("text", "기억을 찾아봤어요. " + re.sub(r"[{}\[\]\"]", " ", r)[:80].strip())
        return ("text", "확인했어요.")
    u = _text(last.get("content"))
    u = re.sub(r"\n?\(지금 시각: [^)]*\)\s*$", "", u)
    if A is not None and A.loop_tools and "calc" in names:     # 도구 폭주 흉내: 도구를 줄 때마다 다른 계산을 또 부름
        n = sum(1 for m in messages if m.get("role") == "tool")
        return ("tool", "calc", {"expression": f"{n}+1"})
    if ("가는 길" in u or "길 안내" in u or "길안내" in u) and "phone_action" in names:     # 폰 대화에만 붙는 폰 도구
        dest = re.sub(r"\s*(까지|으로|로)?\s*(가는 길|길 ?안내).*$", "", u).strip() or "강남역"
        app = next((a for a in ("카카오맵", "네이버지도", "티맵", "구글지도", "카카오내비") if a in u), "")
        return ("tool", "phone_action", {"action": "navigate", "destination": dest[:30], "app": app})
    if "전화" in u and "phone_action" in names:
        num = re.sub(r"\D", "", u)
        return ("tool", "phone_action", {"action": "dial", **({"number": num} if len(num) >= 3 else {"contact": u.split()[0].rstrip("한테에게")})})
    if "폰에서" in u and "열어" in u and "phone_action" in names:
        return ("tool", "phone_action", {"action": "open_app", "app": re.sub(r"(폰에서|열어 ?줘?|\s)", "", u)[:20] or "유튜브"})
    if "검색" in u and "pc_action" in names:                      # 폰으로 말해도 PC 조작
        return ("tool", "pc_action", {"action": "search", "query": re.sub(r"\s*(검색해 ?줘?|검색)\s*", " ", u).strip()[:40]})
    if "전부 잊어" in u and "forget" in names:                   # 위험한 도구(전부 지우기) → 확인 단추
        return ("tool", "forget", {"what": u.replace("전부 잊어 줘", "").strip()[:40] or "시험", "all": True})
    if "잊어" in u and "forget" in names:                       # 불리언을 글자 'False' 로 보내는 버릇 흉내
        return ("tool", "forget", {"what": u.replace("잊어 줘", "").strip()[:40], "all": "False"})
    if "날씨" in u and "get_weather" in names:
        return ("tool", "get_weather", {"place": "서울", "day": "tomorrow" if "내일" in u else "today"})
    if ("곱하기" in u or "더하기" in u or re.search(r"\d+\s*[x×*+]\s*\d+", u)) and "calc" in names:
        nums = [int(x) for x in re.findall(r"\d+", u)] or [320, 15]
        if len(nums) < 2:
            nums = [320, 15]
        return ("tool", "calc", {"expression": f"{nums[0]}*{nums[1]}"})
    if "기억해" in u and "remember" in names:
        return ("tool", "remember", {"content": u.replace("기억해 줘", "").strip()[:80]})
    if ("뭐라고 했" in u or "지난주" in u) and "recall" in names:
        return ("tool", "recall", {"query": "", "day": "지난주" if "지난주" in u else None})
    if "이름" in u:
        return ("text", f"저는 {nm}예요. 무엇을 도와드릴까요?")
    if "길게" in u or "설명" in u:
        return ("text", "우주는 아주 넓어요. " * 3 + "별과 은하가 셀 수 없이 많고, 빛도 끝까지 가려면 아주 오래 걸려요. "
                        "가까운 별까지 가는 데도 빛의 속도로 몇 년이 걸리고, 은하 사이는 수백만 년이 걸리기도 해요. "
                        "그래서 우리가 보는 별빛은 아주 오래전에 떠난 빛이에요.")
    return ("text", "네, 알겠어요.")


def chunk(cid, delta, finish=None, timings=None):
    j = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": "fake",
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if timings is not None:
        j["timings"] = timings
    return "data: " + json.dumps(j, ensure_ascii=False) + "\n\n"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            return self._send(200, {"status": "ok"})
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "fake"}]})
        self._send(404, {})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _record(self, kind, body, extra=None):
        if not A.log:
            return
        rec = {"t": round(time.time(), 3), "kind": kind, "auth": bool(self.headers.get("Authorization")),
               "cache_prompt": body.get("cache_prompt"), "id_slot": body.get("id_slot"), "stream": body.get("stream"),
               "tools": len(body.get("tools") or []), "tool_choice": body.get("tool_choice"),
               "prompt_cache_key": bool(body.get("prompt_cache_key")),
               "thinking": (body.get("chat_template_kwargs") or {}).get("enable_thinking"),
               "last": _text((body.get("messages") or [{}])[-1].get("content"))[:120] if body.get("messages") else None,
               **(extra or {})}
        with LOCK, open(A.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def do_POST(self):
        body = self._body()
        p = self.path.split("?")[0]
        if p.endswith("/apply-template"):
            return self._send(200, {"prompt": render(body.get("messages"), body.get("tools"))})
        if p.endswith("/tokenize"):
            return self._send(200, {"tokens": tokens(str(body.get("content") or ""))})
        if not p.endswith("/chat/completions"):
            return self._send(404, {})
        if A.require_key:
            want = os.environ.get(A.require_key) or ""
            got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if not want or got != want:
                self._record("거절", body)
                return self._send(401, {"error": {"message": "bad key"}})
        msgs = body.get("messages") or []
        tools = body.get("tools") or []
        if body.get("tool_choice") == "none":
            tools = []
        d = decide(msgs, tools)
        prompt_n = len(tokens(render(msgs, body.get("tools"))))
        cache_on = body.get("cache_prompt") is not False
        with LOCK:
            COUNT["all"] += 1
            trip = False
            if body.get("stream") and cache_on and COUNT["trip_left"] > 0:
                COUNT["trip_left"] -= 1
                trip = True
        rendered = render(msgs, body.get("tools"))
        slot = body.get("id_slot") if isinstance(body.get("id_slot"), int) and body.get("id_slot") >= 0 else 0
        with LOCK:
            prev = SLOTS.get(slot, "")
            SLOTS[slot] = rendered        # 진짜 서버처럼 칸에는 이번 글이 남음(답 글은 생략)
        common = len(tokens(os.path.commonprefix([prev, rendered])))
        cache_n = (prompt_n + 5000) if trip else (max(0, min(common, prompt_n - 1)) if cache_on else 0)
        timings = {"cache_n": cache_n, "prompt_n": max(1, prompt_n - cache_n) if not trip else 7, "predicted_n": 5}
        reply_text = d[1] if d[0] == "text" else None
        if trip:
            reply_text = "다른 대화의 엉뚱한 답입니다."   # 가드가 막아야 하는 글
        self._record("대답", body, {"decide": d[0] if not trip else "오염흉내", "tool": d[1] if d[0] == "tool" else None,
                                   "cache_n": cache_n})
        cid = "fake-%d" % COUNT["all"]
        if not body.get("stream"):
            msg = {"role": "assistant", "content": reply_text or ""}
            if d[0] == "tool" and not trip:
                if A.text_tools:
                    msg["content"] = _as_text(d[1], d[2])
                else:
                    msg["content"] = None
                    msg["tool_calls"] = [{"id": "call_1", "type": "function",
                                          "function": {"name": d[1], "arguments": json.dumps(d[2], ensure_ascii=False)}}]
            return self._send(200, {"id": cid, "object": "chat.completion", "model": "fake",
                                    "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": prompt_n, "completion_tokens": 5}, "timings": timings})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        time.sleep(A.delay)
        out = [chunk(cid, {"role": "assistant", "content": ""}, timings=timings)]
        if d[0] == "tool" and not trip:
            if A.text_tools:
                s = _as_text(d[1], d[2])
                out += [chunk(cid, {"content": s[i:i + 6]}) for i in range(0, len(s), 6)]
                out.append(chunk(cid, {}, "stop"))
            else:
                out.append(chunk(cid, {"tool_calls": [{"index": 0, "id": "call_%d" % COUNT["all"], "type": "function",
                                                       "function": {"name": d[1], "arguments": ""}}]}))
                out.append(chunk(cid, {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(d[2], ensure_ascii=False)}}]}))
                out.append(chunk(cid, {}, "tool_calls"))
        else:
            s = reply_text or ""
            out += [chunk(cid, {"content": s[i:i + 8]}) for i in range(0, len(s), 8)]
            out.append(chunk(cid, {}, "stop"))
        out.append("data: [DONE]\n\n")
        try:
            for x in out:
                self.wfile.write(x.encode())
                self.wfile.flush()
                time.sleep(0.01)
        except OSError:
            pass
        self.close_connection = True


def _as_text(name, args):
    inner = ",".join(f"{k}:{Q}{v}{Q}" for k, v in args.items())
    return f"{name}{{{inner}}}"


def main():
    global A
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18990)
    ap.add_argument("--log", default="")
    ap.add_argument("--require-key", default="")
    ap.add_argument("--trip", type=int, default=0)
    ap.add_argument("--text-tools", action="store_true")
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--loop-tools", action="store_true", help="도구를 줄 때마다 계속 부름(폭주 멈춤 시험)")
    A = ap.parse_args()
    COUNT["trip_left"] = A.trip
    srv = ThreadingHTTPServer(("127.0.0.1", A.port), H)
    print(f"가짜 두뇌 127.0.0.1:{A.port} (trip={A.trip}, text_tools={A.text_tools}, key={'있음' if A.require_key else '없음'})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
