# 본체(app/) 단위 시험 — 소리·두뇌 없이 도는 것만. pytest 없이도 돈다:  python -m tests.unit.test_body
#   (pytest 가 있으면 pytest tests/unit 로도 됨)
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import prompt, safe_args, turns  # noqa: E402
from app.core.audio_smooth import SeamSmoother, clicks  # noqa: E402
from app.core.brain import CacheGuard        # noqa: E402
from app.core.memory import Memory           # noqa: E402
from app.core.state import SessionState      # noqa: E402
from app.core.wake import NameMatcher        # noqa: E402
from app.tools.basic.handlers import calc_expr  # noqa: E402
from app.tools.registry import Guard, load_packs  # noqa: E402


def cfg(**over):
    c = C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None)
    return C.deep_merge(c, over)


def test_bool_strings():
    a = {"all": "False", "x": "true", "y": 1}
    fixed = safe_args.불리언_정리(a, {"all", "x"})
    assert a["all"] is False and a["x"] is True and {k for k, _ in fixed} == {"all", "x"}


def test_names_and_rename():
    c = cfg()
    assert C.names(c)[0] == "김비서" and "김 비서" in C.names(c)[1]
    c2 = cfg(비서={"이름": "현아"})
    name, al = C.names(c2)
    assert name == "현아" and al == [], "이름만 바꾸면 옛 이름 별칭은 버려야 함"
    m = NameMatcher(name, al)
    assert m.only_name("현아") and m.only_name("현아야") and m.only_name("현아!")
    assert m.call("현아, 불 켜 줘") and not m.only_name("현아, 불 켜 줘")
    assert not m.call("김비서") and not m.call("표현아")
    k = NameMatcher("김비서", ["김 비서"])
    assert k.only_name("김비서요") and k.only_name("저기 김비서야") and not k.only_name("김비서 날씨")


def test_prompt_fixed_and_tools():
    c = cfg(사용자={"호칭": "대표"})
    specs, _ = load_packs(c)
    a, b = prompt.system_prompt(c, specs), prompt.system_prompt(c, specs)
    assert a == b, "고정 앞부분은 매번 같아야 캐시가 먹음"
    assert "지금 시각" not in a.split("\n")[-1] and "대표라고" in a
    assert "{" not in a and "김비서" in a
    c["도구"]["끄기"] = ["remember", "recall", "forget"]
    s2, _ = load_packs(c)
    g = prompt.tool_guide(s2)
    assert "recall" not in g and "remember" not in g and "calc" in g
    assert "도구가 없다" in prompt.tool_guide([])
    c3 = cfg(비서={"이름": "현아"})
    assert "'현아'라는" in prompt.system_prompt(c3, specs) and "김비서" not in prompt.system_prompt(c3, specs)


def test_korean_end():
    assert turns.looks_final("내일 서울 날씨 어때?") == 0.4
    assert turns.looks_final("내일 서울 날씨 어때") == 1.0
    assert turns.looks_final("그리고 내일") is None


def test_stop_words():
    st = SessionState(cfg())
    assert st.is_stop("그만 말해줘.\n(지금 시각: 2026년 1월 1일 목요일 오전 9시 0분)")
    assert not st.is_stop("그만두는 방법을 자세히 알려 주고 그다음에 내일 날씨도 찾아서 길게 설명해 줘 부탁해")


def test_news_signoff_hallucination():
    from app.core.state import is_hallucination
    c = cfg()
    assert is_hallucination("MBC 뉴스 박진주입니다.", c) and is_hallucination("MBC뉴스", c)
    assert not is_hallucination("MBC 뉴스 보여 줘", c) and not is_hallucination("뉴스 틀어 줘", c)


def test_standby_blocks_follow():
    st = SessionState(cfg(대화={"이름부르기": False}))
    st.bot_stopped_at = time.time()
    st.set_wake(True, why="대기 도구")
    assert st.wake and not st.in_follow(), "대기 대답 뒤 이어듣기가 열리면 주변 말에 답함"
    st.wake_until = time.time() + 8
    assert st.in_follow()


def test_calc_safe():
    assert calc_expr("320*15") == 4800 and calc_expr("(2400/3)*7") == 5600 and calc_expr("10%") == 0.1
    for bad in ("__import__('os')", "2**999999", "a+1"):
        try:
            calc_expr(bad)
            raise AssertionError("막아야 함: " + bad)
        except (ValueError, SyntaxError):
            pass


def test_memory_roundtrip():
    d = tempfile.mkdtemp()
    try:
        m = Memory(d)
        assert m.add("사용자는 김치찌개를 제일 좋아한다")["저장"]
        assert m.add("사장님은 김치찌개를 제일 좋아한다", source="자동").get("이미있음")
        assert m.add("사용자는 다음 주 목요일 치과 예약이 있다", source="자동")["저장"]
        card = " ".join(["4111"] * 4)   # 시험용 카드 번호 꼴(공개 검사가 글 그대로의 번호를 막으므로 조립)
        assert m.add(f"카드 번호는 {card} 이야").get("가림")
        fid = m.list_facts()[0]["id"]
        assert m.delete(fid) and len(m.list_facts()) == 2
        m.archive_append([{"role": "user", "content": "제주도 여행 가기로 했어"}, {"role": "assistant", "content": "좋네요"}], "s1")
        r = m.search_archive("제주도")
        assert r and "제주도" in json.dumps(r, ensure_ascii=False)
        assert m.day_range("지난주") and m.day_range("어제") and m.day_range("2026-11-04")
        msgs = [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "네, 안녕하세요."}]
        m.save_context(msgs, "요약 한 줄", 6)
        back, summ = Memory(d).load_context(6)
        assert back and back[0]["content"] == "안녕" and summ == "요약 한 줄"
        m.clear_all()
        assert not Memory(d).list_facts() and not Memory(d).load_context(6)[0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_seam_smoother():
    sr = 24000
    t = np.arange(sr // 2) / sr
    a = (np.sin(2 * np.pi * 220 * t) * 12000).astype(np.int16)
    b = (np.sin(2 * np.pi * 220 * t + 2.5) * 12000).astype(np.int16)   # 위상이 튀는 이음새
    raw = a.tobytes() + b.tobytes()
    sm = SeamSmoother(sr)
    sm.start()
    out = sm.feed(a.tobytes()) + sm.feed(b.tobytes()) + sm.end()
    assert clicks(raw) >= 1 and clicks(out) < clicks(raw)
    tail = np.frombuffer(out, np.int16)[-24:]
    assert abs(int(tail[-1])) < 200, "끝은 작게 사라져야 함"


def test_cache_guard_allowed():
    g = CacheGuard("http://127.0.0.1:1/v1")

    async def n_tokens(text):
        return len(text)
    g.n_tokens = n_tokens

    async def run():
        g.remember("SYS|A1|", "답A", gen_tokens=30)
        g.remember("SYS|B1|", "답B", gen_tokens=5)
        assert await g.allowed("SYS|A1|답A|A2|") == len("SYS|A1|") + 30     # 같은 대화 이어 쓰기 = 앞 요청 + 만든 토큰
        assert await g.allowed("SYS|C1|") == len("SYS|")                    # 처음 보는 대화 = 지시문까지만
    asyncio.run(run())


def test_tidy_messages():
    from app.core.brain import tidy_messages
    ms = [{"role": "system", "content": "S"}, {"role": "user", "content": "날씨"},
          {"role": "assistant", "tool_calls": [{"id": "1"}], "content": None},
          {"role": "tool", "tool_call_id": "1", "content": "{}"}, {"role": "assistant", "content": "잠깐 날씨 볼게요."}]
    t = tidy_messages(ms)
    assert t[-1]["role"] == "tool" and len(ms) == 5, "끝 비서 글은 사본에서만 뺌"
    ms.append({"role": "assistant", "content": "맑아요."})
    ms.append({"role": "user", "content": "고마워"})
    t = tidy_messages(ms)
    assert [m["role"] for m in t] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert t[4]["content"] == "잠깐 날씨 볼게요. 맑아요."


def test_tool_guard_caps():
    st = SessionState(cfg())
    g = Guard(st, cfg())

    class L:
        cur_user_key = 1
    for i in range(5):
        assert g.check(L, "web_search", {"query": f"q{i}"}) is None
    assert g.check(L, "web_search", {"query": "q9"})["중단"]
    g.reset(None)
    L.cur_user_key = 2
    assert g.check(L, "calc", {"expression": "1+1"}) is None and g.check(L, "calc", {"expression": "1+1"}) is None
    assert g.check(L, "calc", {"expression": "1+1"})["중단"], "같은 호출 3번째는 거부"
    st.stop_now = True
    assert g.check(L, "calc", {"expression": "2+2"})["멈춤"]


def test_read_page_cache_and_local_block():
    from app.tools.basic import handlers
    web = handlers.web
    u = "https://example.com/a"
    web.PAGE_CACHE[u] = {"t": time.time(), "주소": u, "제목": "제목", "본문": "가나다 " * 20}
    r = asyncio.run(web.read_page({}, u))
    assert r.get("이미읽음") is True, "같은 주소는 다시 받지 않음"
    r2 = asyncio.run(web.read_page({}, "http://127.0.0.1:8870/api/status"))
    assert r2.get("오류"), "이 PC 안 주소는 읽지 않음"
    web.PAGE_CACHE.pop(u, None)


def test_voice_waits_engine_loading():
    """목소리 서버가 떠 있어도 엔진을 읽는 중(503 '엔진 준비 중')이면 오류 대신 기다렸다 다시 — 앱 켜자마자 인사가 안 나오던 문제."""
    from app.core import voice_link

    async def run():
        hits = []

        async def handle(reader, writer):
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            hits.append(1)
            code, msg = (b"503", "엔진 준비 중") if len(hits) < 3 else (b"500", "다른 고장")
            body = json.dumps({"error": msg}, ensure_ascii=False).encode()
            writer.write(b"HTTP/1.1 " + code + b" X\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            await writer.drain()
            writer.close()

        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        c = cfg(포트={"목소리": port}, 목소리={"엔진_기다림_초": 10})
        link = voice_link.VoiceLink(c)
        evs = [ev async for ev, _ in link.speak("안녕하세요")]
        srv.close()
        return hits, evs, link

    hits, evs, link = asyncio.run(run())
    assert len(hits) == 3, hits
    assert len(evs) == 1 and "500" in evs[0]["error"], evs
    assert link._reset is False


def test_launcher_log_size_cap():
    """실행기 기록: 자식 출력(파이프)을 받아 쓰다 5MB(시험은 작게) 넘으면 .1 .2 로 나눔 · 3개까지만 남김."""
    import io
    from app import launcher as L
    d = tempfile.mkdtemp()
    p = os.path.join(d, "body.log")
    old = L.LOG_MAX
    L.LOG_MAX = 1000
    try:
        L.pump(io.BytesIO(b"".join(b"%05d %s\n" % (i, b"x" * 90) for i in range(100))), p, b"==== head\n")
        names = sorted(os.listdir(d))
        assert names == ["body.log", "body.log.1", "body.log.2"], names
        assert all(os.path.getsize(os.path.join(d, n)) <= 1000 + 100 for n in names)
        assert b"00099" in open(p, "rb").read(), "마지막 줄은 지금 파일에"
        open(os.path.join(d, "launcher.log"), "w").write("y" * 1500)
        assert L.rotate(os.path.join(d, "launcher.log")) and os.path.exists(os.path.join(d, "launcher.log.1"))
        assert not L.rotate(os.path.join(d, "없음.log"))
    finally:
        L.LOG_MAX = old


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
