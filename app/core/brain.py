# 두뇌 — OpenAI 호환 주소(기본: 이 PC 의 llama-server, Gemma 4 E4B Q4_K_M)·GPT·클로드.
#   방식(설정 두뇌.방식): local = 이 PC llama-server(두뇌.주소) / url = 다른 OpenAI 호환 주소 / openai = GPT(열쇠) / claude = 클로드(열쇠)
#                         / claude_cli·codex_cli = 구독 두뇌(같은 PC 의 claude·codex 명령, core/cli_brain.py).
#   열쇠는 core/keystore(사용자 PC 의 DPAPI 파일·환경변수)에서만 읽는다 — 설정·로그·저장소에 쓰지 않음.
#   모드(두뇌.모드): '빠른' = 생각 끔(기본, 첫마디 빠름) / '꼼꼼' = 생각 켬(chat_template_kwargs.enable_thinking).
#   글로 쓴 도구 호출 건지기(두뇌.글로쓴호출_건지기): 작은 모델이 도구 호출 표시 없이 `get_weather{day:...}` 처럼 글로 쓰면
#     brain/tool_text_rescue.rescue 로 진짜 도구 호출로 바꾼다. 답 글이 도구 호출일 수 있는 동안은 글을 내보내지 않고 잡아 둔다.
#   글 거르기: <think> 블록·중국어 낱말(filters.py).
#   캐시(같은 앞부분은 다시 읽지 않게):
#     · 지시문+도구 정의+기억 블록이 맨 앞에 고정(prompt.py), 지금 시각은 사용자 말 끝 꼬리표로 한 번만 붙여 대화에 그대로 둔다.
#     · local/url: cache_prompt + id_slot(대화마다 같은 칸) + timings_per_token. GPT: prompt_cache_key. 클로드: cache_control.
#     · 캐시 오염 가드(local): 응답 첫 조각의 timings.cache_n(캐시로 다시 쓴 토큰 수)이 '이번 요청과 지금까지 보낸 요청들의
#       공통 앞부분 토큰 수'(/apply-template 로 그린 글의 공통 앞부분을 /tokenize)보다 크면, 다른 대화 내용을 이어 쓴 것으로 보고
#       그 응답을 버린 뒤 경고를 남기고 cache_prompt 를 끈 채 다시 묻는다(이 대화는 그 뒤로 캐시 끔). 글은 가드 판정 뒤에야 내보냄.
import asyncio
import collections
import json
import os
import re
import time
import uuid

import httpx
from loguru import logger
from pipecat.frames.frames import FunctionCallFromLLM, LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService

from . import config as C
from . import keystore
from .filters import HanziFilter, ThinkFilter
from .memory import TIME_TAG
from .prompt import now_tag


def _load_rescue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kimbiseo_tool_text_rescue",
                                                  os.path.join(C.REPO, "brain", "tool_text_rescue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.rescue



rescue = _load_rescue()

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
GUARD_SLACK = 16   # 토큰 경계·BOS 차이 허용


class CacheGuard:
    """한 두뇌 서버(llama-server)에 보낸 요청 글(그린 프롬프트 + 받은 답)을 기억해, 캐시 재사용이 맞는지 본다.
    본체 하나가 그 서버를 혼자 쓴다고 본다(다른 프로그램이 같은 서버를 쓰면 가드가 지나치게 조심할 수 있음 — 그때는 캐시를 끔)."""

    def __init__(self, base_url, keep=8):
        root = re.sub(r"/v1/?$", "", base_url.rstrip("/"))
        self.root = root
        self.hist = collections.deque(maxlen=keep)   # 그린 프롬프트 + 그 답 글
        self.ok = True                               # /apply-template·/tokenize 가 없으면 False(가드 못 함)
        self.trips = 0
        self.checks = 0
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))

    async def render(self, params):
        body = {"messages": params.get("messages") or []}
        if params.get("tools"):
            body["tools"] = params["tools"]
        eb = params.get("extra_body") or {}
        if eb.get("chat_template_kwargs"):
            body["chat_template_kwargs"] = eb["chat_template_kwargs"]
        r = await self.http.post(self.root + "/apply-template", json=body)
        r.raise_for_status()
        return r.json()["prompt"]

    async def n_tokens(self, text):
        if not text:
            return 0
        r = await self.http.post(self.root + "/tokenize", json={"content": text})
        r.raise_for_status()
        return len(r.json().get("tokens") or [])

    async def allowed(self, rendered):
        """캐시로 다시 써도 되는 최대 토큰 수.
        ① 지금까지 보낸 요청(+받은 답 글)과의 가장 긴 공통 앞부분.
        ② 이번 요청이 앞 요청 P 를 통째로 이어 쓴 것이면(같은 대화의 다음 차례) 서버 칸에는 P 와 그때 두뇌가 만든 토큰 G 가
           있으므로 |P| + |G| 까지(도구 호출은 답 글이 없어 ①만으로는 모자람 — 시험에서 21토큰 차이로 헛걸림)."""
        best, ext, ext_gen = "", "", 0
        for prompt, full, gen in self.hist:
            p = os.path.commonprefix([full, rendered])
            if len(p) > len(best):
                best = p
            if gen and len(prompt) > len(ext) and rendered.startswith(prompt):
                ext, ext_gen = prompt, gen
        n = await self.n_tokens(best)
        if ext:
            n = max(n, await self.n_tokens(ext) + int(ext_gen))
        return n

    def remember(self, rendered, reply_text="", gen_tokens=0):
        if rendered:
            self.hist.append((rendered, rendered + (reply_text or ""), int(gen_tokens or 0)))


def _plain_assistant(m):
    return (isinstance(m, dict) and m.get("role") == "assistant" and not m.get("tool_calls")
            and isinstance(m.get("content"), str))


def tidy_messages(msgs):
    """두뇌에 보내는 사본만 다듬는다(대화 문맥 자체는 그대로).
    ① 끝에 붙은 비서 글(도구 앞 한마디 '잠깐 날씨 볼게요' 등)은 뺀다 — llama-server 는 끝이 비서 말이면 그 말을 '이어 쓰기'로 받는다.
    ② 이어진 비서 글 두 개(앞 한마디 + 답)는 하나로 합친다 — 차례가 번갈아야 하는 채팅 틀이 있음."""
    out = []
    for m in msgs:
        if out and _plain_assistant(m) and _plain_assistant(out[-1]):
            out[-1] = {**out[-1], "content": (out[-1]["content"].rstrip() + " " + m["content"].lstrip()).strip()}
            continue
        out.append(m)
    while len(out) > 1 and _plain_assistant(out[-1]) and any(isinstance(x, dict) and x.get("role") in ("user", "tool") for x in out):
        out.pop()
    return out


def _timings(chunk):
    ex = getattr(chunk, "model_extra", None) or {}
    t = ex.get("timings") if isinstance(ex, dict) else None
    return t if isinstance(t, dict) and "cache_n" in t else None


class BrainLLM(OpenAILLMService):
    """OpenAI 호환 두뇌 + 글로 쓴 도구 호출 건지기 + 글 거르기 + 캐시 가드."""

    supports_developer_role = False

    def __init__(self, state, cfg, tool_names=(), guard=None, slot=0, cache_key="", **kw):
        super().__init__(**kw)
        self.state = state
        self.cfg = cfg
        b = cfg["두뇌"]
        self.kind = str(b.get("방식") or "local")
        self.mode = str(b.get("모드") or "빠른")
        self.tool_names = list(tool_names)
        self.do_rescue = bool(b.get("글로쓴호출_건지기", True))
        self.guard = guard
        self.slot = int(slot)
        self.cache_key = cache_key or uuid.uuid4().hex[:12]
        self.cache_off = not bool(b.get("캐시", True))
        self.last_timing = None      # 마지막 응답의 {cache_n, prompt_n, ttft_ms}
        self.timing_log = []
        self.cur_user_key = None
        self.rescued = 0
        self._think = ThinkFilter()
        self._hanzi = HanziFilter()
        self._hold = None
        self._pushed = False

    # ---------------- 요청 만들기
    def build_chat_completion_params(self, params_from_context):
        params = super().build_chat_completion_params(params_from_context)
        if isinstance(params.get("messages"), list):
            params["messages"] = tidy_messages(params["messages"])
        b = self.cfg["두뇌"]
        eb = dict(b.get("추가") or {})
        st = self.state
        if params.get("tools") and (getattr(st, "stop_now", False)
                                    or (st.no_tools_key is not None and st.no_tools_key == self.cur_user_key)):
            params["tool_choice"] = "none"   # '그만' 뒤·도구 폭주로 멈춘 그 질문: 도구 없이 답하게(서버에서 강제)
        if self.kind in ("local", "url"):
            ctk = dict(eb.get("chat_template_kwargs") or {})
            ctk["enable_thinking"] = self.mode == "꼼꼼"
            eb["chat_template_kwargs"] = ctk
            eb.setdefault("cache_prompt", not self.cache_off)
            if not self.cache_off:
                eb.setdefault("id_slot", self.slot)
            eb.setdefault("timings_per_token", True)
        elif self.kind == "openai" and not self.cache_off:
            eb.setdefault("prompt_cache_key", "kimbiseo-" + self.cache_key)
        if self._no_cache_once:
            eb["cache_prompt"] = False
            eb.pop("id_slot", None)
        params["extra_body"] = {**(params.get("extra_body") or {}), **eb}
        for k in ("frequency_penalty", "presence_penalty", "seed", "top_p", "max_completion_tokens", "service_tier"):
            if params.get(k) is None or type(params.get(k)).__name__ == "NotGiven":
                params.pop(k, None)
        return params

    _no_cache_once = False

    async def get_chat_completions(self, context):
        if self.kind != "local" or self.guard is None or not self.guard.ok:
            return await super().get_chat_completions(context)
        return self._guarded_stream(context)

    async def _guarded_stream(self, context):
        """첫 timings 조각에서 캐시 재사용이 맞는지 확인한 뒤에야 조각을 내보낸다(어긋나면 버리고 캐시 끄고 다시)."""
        adapter = self.get_llm_adapter()
        for attempt in range(2):
            pfc = await adapter.get_llm_invocation_params(context, system_instruction=self._settings.system_instruction,
                                                          convert_developer_to_user=not self.supports_developer_role)
            params = self.build_chat_completion_params(pfc)
            cache_on = bool((params.get("extra_body") or {}).get("cache_prompt"))
            t0 = time.perf_counter()
            render_task = asyncio.ensure_future(self.guard.render(params)) if self.guard.ok else None
            stream = await self._client.chat.completions.create(**params)
            held, checked, reply, last_tm = [], False, [], None
            rendered = None
            redo = False
            try:
                async for chunk in stream:
                    if not checked:
                        tm = _timings(chunk)
                        if tm is None and not (chunk.choices and chunk.choices[0].delta
                                               and (chunk.choices[0].delta.content or chunk.choices[0].delta.tool_calls)):
                            held.append(chunk)
                            continue
                        checked = True
                        ttft = (time.perf_counter() - t0) * 1000
                        info = {"cache_n": (tm or {}).get("cache_n"), "prompt_n": (tm or {}).get("prompt_n"),
                                "ttft_ms": round(ttft), "cache": cache_on}
                        try:
                            rendered = await render_task if render_task else None
                            if cache_on and rendered is not None and tm is not None:
                                allow = await self.guard.allowed(rendered)
                                info["allowed"] = allow
                                self.guard.checks += 1
                                if int(tm.get("cache_n") or 0) > allow + GUARD_SLACK:
                                    self.guard.trips += 1
                                    logger.warning(f"두뇌 캐시 오염 의심: 다시 쓴 토큰 {tm.get('cache_n')} > 공통 앞부분 {allow} "
                                                   f"→ 이 답 버리고 캐시 끈 채 다시 묻기(이 대화는 캐시 끔)")
                                    self.state.event("cache_guard", cache_n=tm.get("cache_n"), allowed=allow)
                                    self.cache_off = True
                                    redo = True
                        except Exception as ex:  # noqa: BLE001
                            logger.info(f"캐시 가드를 쓸 수 없음(두뇌 서버가 apply-template·tokenize 를 모름) → 가드 끔: {ex.__class__.__name__}")
                            self.guard.ok = False
                        self.last_timing = info
                        self.timing_log.append(info)
                        if redo:
                            break
                        for h in held:
                            yield h
                        held = []
                    tl = _timings(chunk)
                    if tl is not None:
                        last_tm = tl
                    d = chunk.choices[0].delta if chunk.choices else None
                    if d is not None and d.content:
                        reply.append(d.content)
                    yield chunk
            finally:
                try:
                    await stream.close()
                except Exception:  # noqa: BLE001
                    pass
                if render_task is not None and not render_task.done():
                    render_task.cancel()
                if rendered is not None and not redo:
                    self.guard.remember(rendered, "".join(reply), int((last_tm or {}).get("predicted_n") or 0) + 1)
            if not redo:
                return

    # ---------------- 응답 처리
    def _maybe_tool(self, buf):
        """글이 도구 호출 꼴일 수 있나 → 'maybe' | 'no'."""
        s = buf.lstrip()
        if not s:
            return "maybe"
        if s.startswith(("<|tool_call>", "<|", "call:")) or "<|tool_call>".startswith(s) or "call:".startswith(s):
            return "maybe"
        m = _IDENT.match(s)
        if not m:
            return "no"
        ident = m.group(0)
        if m.end() == len(s):
            return "maybe" if any(n.startswith(ident) for n in self.tool_names) else "no"
        return "maybe" if ident in self.tool_names else "no"

    async def _emit(self, text):
        if text:
            self._pushed = True
            await super()._push_llm_text(text)

    async def _push_llm_text(self, text):
        t = self._think.feed(text)
        if t:
            t = self._hanzi.feed(t)
        if not t:
            return
        if self._hold is not None:
            self._hold += t
            if self._maybe_tool(self._hold) == "maybe":
                return
            t, self._hold = self._hold, None
        await self._emit(t)

    def _tag_time(self, context):
        """마지막 사용자 말에 지금 시각 꼬리표를 한 번 붙여 대화에 그대로 둔다(앞부분이 다음 차례에도 같게)."""
        msgs = context.messages
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str) and not TIME_TAG.search(c):
                    m["content"] = c + "\n" + now_tag()
                self.cur_user_key = id(m)
                return m
        return None

    async def _slow_note(self, key):
        b = self.cfg["두뇌"]
        sec = float(b.get("생각_먼저할말_초", 6) or 0)
        words = list(b.get("생각_먼저할말") or [])
        if sec <= 0 or not words:
            return
        await asyncio.sleep(sec)
        if not self._pushed and self.cur_user_key == key and self.state.pre_key != key:
            self.state.pre_key = key
            await self.push_frame(TTSSpeakFrame(words[int(time.time()) % len(words)]))

    async def _process_context(self, context):
        self._think = ThinkFilter()
        self._hanzi = HanziFilter()
        self._hold = "" if (self.do_rescue and self.tool_names) else None
        self._pushed = False
        um = self._tag_time(context)
        st = self.state
        st.stop_now = bool(um and st.is_stop(um.get("content")))
        note = asyncio.ensure_future(self._slow_note(self.cur_user_key))
        try:
            await super()._process_context(context)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"두뇌 응답 실패: {ex.__class__.__name__} {str(ex)[:160]}")
            st.event("brain_error", reason=ex.__class__.__name__)
            await self.push_frame(TTSSpeakFrame("두뇌에 연결이 안 돼요. 설정에서 두뇌 주소를 확인해 주세요."))
            return
        finally:
            note.cancel()
        rest = self._think.flush()
        rest = self._hanzi.feed(rest) + self._hanzi.flush() if rest else self._hanzi.flush()
        if self._hold is not None:
            buf = self._hold + (rest or "")
            self._hold = None
            calls = rescue(buf, self.tool_names) if buf.strip() else None
            if calls:
                self.rescued += 1
                logger.info(f"글로 쓴 도구 호출 건짐: {[c[0] for c in calls]}")
                st.event("tool_rescue", names=[c[0] for c in calls])
                await self.run_function_calls([
                    FunctionCallFromLLM(context=context, tool_call_id="rescue_" + uuid.uuid4().hex[:10],
                                        function_name=n, arguments=a) for n, a in calls])
                return
            await self._emit(buf)
        elif rest:
            await self._emit(rest)


def make_llm(state, cfg, tool_names=(), guards=None, session_key=""):
    """설정 두뇌.방식에 맞는 두뇌 부품을 만든다. guards: {주소: CacheGuard} (본체 전체에서 같은 서버면 같은 가드를 씀)."""
    b = cfg["두뇌"]
    kind = str(b.get("방식") or "local")
    if kind in ("claude_cli", "codex_cli"):   # 구독 두뇌(같은 PC 의 claude·codex 명령) — core/cli_brain
        from .cli_brain import CliBrain
        return CliBrain(state, cfg, kind)
    temp = float(b.get("온도", 0.6))
    mt = int(b.get("최대토큰", 400))
    if kind == "claude":
        cls = _claude_class()
        key = keystore.get(b.get("열쇠_이름") or "claude", cfg)
        if not key:
            raise RuntimeError("클로드 열쇠가 없어요. 설정 화면에서 열쇠를 넣어 주세요.")
        llm = cls(state, cfg, api_key=key, settings=cls.Settings(
            model=b.get("claude_모델") or "claude-opus-5-5", temperature=temp, max_tokens=mt,
            enable_prompt_caching=bool(b.get("캐시", True))))
        return llm
    if kind == "openai":
        base = b.get("openai_주소") or "https://api.openai.com/v1"
        model = b.get("openai_모델") or ""
        key = keystore.get(b.get("열쇠_이름") or "openai", cfg)
        if not model or not key:
            raise RuntimeError("GPT 를 쓰려면 설정에 모델 이름과 열쇠가 있어야 해요.")
    else:
        base = b.get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1"
        model = b.get("모델") or "local"
        key = keystore.get(b.get("열쇠_이름"), cfg) if b.get("열쇠_이름") else "none"
    guard = None
    if kind == "local" and guards is not None:
        guard = guards.get(base)
        if guard is None:
            guard = guards[base] = CacheGuard(base)
    llm = BrainLLM(state, cfg, tool_names=tool_names, guard=guard, slot=int(b.get("슬롯", 0) or 0), cache_key=session_key,
                   api_key=key or "none", base_url=base,
                   settings=BrainLLM.Settings(model=model, temperature=temp, max_tokens=mt, system_instruction=""),
                   retry_timeout_secs=float(b.get("첫응답_제한_초", 30)), retry_on_timeout=False)
    llm.kind = kind
    return llm


def _claude_class():
    """클로드 두뇌 — pipecat AnthropicLLMService + 본체가 쓰는 것(시각 꼬리표·멈춤말·기록 칸).
    캐시: enable_prompt_caching 이면 pipecat 이 지시문과 마지막 차례에 cache_control 을 붙인다(앞부분 고정 순서 그대로).
    pipecat 의 클로드 쪽은 tool_choice 를 넘기지 않으므로 '그만'·폭주 멈춤은 도구 겉싸개(거부 + run_llm=False)로만 막는다
    (도구 목록을 빼면 캐시 앞부분이 바뀌므로 빼지 않음)."""
    try:
        from pipecat.services.anthropic.llm import AnthropicLLMService
    except Exception as ex:  # noqa: BLE001
        raise RuntimeError("클로드를 쓰려면 anthropic 꾸러미가 필요해요(설치.bat 의 '클로드 쓰기' 선택).") from ex

    class ClaudeLLM(AnthropicLLMService):
        def __init__(self, state, cfg, **kw):
            super().__init__(**kw)
            self.state, self.cfg = state, cfg
            self.kind = "claude"
            self.guard = None
            self.timing_log = []
            self.last_timing = None
            self.rescued = 0
            self.cur_user_key = None

        async def _process_context(self, context):
            um = BrainLLM._tag_time(self, context)
            st = self.state
            st.stop_now = bool(um and st.is_stop(um.get("content")))
            try:
                await super()._process_context(context)
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"두뇌(클로드) 응답 실패: {ex.__class__.__name__}")
                st.event("brain_error", reason=ex.__class__.__name__)
                await self.push_frame(TTSSpeakFrame("두뇌에 연결이 안 돼요. 설정에서 열쇠와 인터넷 연결을 확인해 주세요."))

    return ClaudeLLM


class NoBrain(FrameProcessor):
    """두뇌를 못 만들었을 때(열쇠 없음·꾸러미 없음) 대신 들어가 사용자 말마다 이유를 말해 준다 — 본체가 꺼지지 않게."""

    def __init__(self, reason):
        super().__init__()
        self.reason = str(reason)[:200]
        self.kind = "none"
        self.guard = None
        self.timing_log = []
        self.last_timing = None
        self.rescued = 0
        self.cur_user_key = None
        self._said = 0.0

    def register_function(self, *a, **k):
        return None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            if time.time() - self._said > 3:
                self._said = time.time()
                await self.push_frame(TTSSpeakFrame(self.reason))
            return
        await self.push_frame(frame, direction)


async def simple_text(cfg, messages, max_tokens=300, temperature=0.3, timeout=60.0):
    """대화 밖 한 번 묻기(일기 요약·자동 기억). 생각 끔, 캐시 안 씀(대화 칸을 흐트리지 않게). 실패하면 ''."""
    b = cfg["두뇌"]
    kind = str(b.get("방식") or "local")
    if kind in ("claude_cli", "codex_cli"):
        if not (cfg.get("기억") or {}).get("구독두뇌_정리", True):
            return ""
        from .cli_brain import one_shot
        return await one_shot(cfg, messages, max_chars=max_tokens * 4, timeout=timeout)
    if kind == "claude":
        return ""   # 클로드는 대화 밖 요청을 하지 않음(열쇠 요금) — 일기·자동 기억은 로컬·OpenAI 호환에서만
    if kind == "openai":
        base, model = b.get("openai_주소") or "https://api.openai.com/v1", b.get("openai_모델") or ""
        key = keystore.get(b.get("열쇠_이름") or "openai", cfg)
    else:
        base, model = b.get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1", b.get("모델") or "local"
        key = keystore.get(b.get("열쇠_이름"), cfg) if b.get("열쇠_이름") else "none"
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": False}
    if kind in ("local", "url"):
        body["chat_template_kwargs"] = {"enable_thinking": False}
        body["cache_prompt"] = False
        body["id_slot"] = -1
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as cl:
            r = await cl.post(base.rstrip("/") + "/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {key or 'none'}"})
            r.raise_for_status()
            j = r.json()
        return str(((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception as ex:  # noqa: BLE001
        logger.warning(f"두뇌 한 번 묻기 실패: {ex.__class__.__name__}")
        return ""


def warm_body(params_messages, tools, cfg):
    """대화 시작 때 앞부분(지시문·도구·이어 온 차례)을 미리 읽혀 두는 요청 본문(답 1토큰, 캐시 칸 고정)."""
    b = cfg["두뇌"]
    body = {"model": b.get("모델") or "local", "messages": tidy_messages(list(params_messages)), "max_tokens": 1, "temperature": 0,
            "stream": False, "cache_prompt": True, "id_slot": int(b.get("슬롯", 0) or 0),
            "chat_template_kwargs": {"enable_thinking": str(b.get("모드")) == "꼼꼼"}}
    if tools:
        body["tools"] = tools
    return json.loads(json.dumps(body, ensure_ascii=False))
