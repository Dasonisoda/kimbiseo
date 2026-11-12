# 구독 두뇌 — 같은 PC 의 클로드 코드(claude)·GPT(codex) 명령을 김비서가 직접 불러 답을 받는 '내장 중계'(따로 서버 없음).
#   사용자 본인이 그 프로그램에 로그인한 구독으로 대답한다. 김비서는 계정·토큰·열쇠를 읽지도 보내지도 않는다.
#   지연을 줄이려고(11-11 실측):
#     · 상시 세션 — 대화마다 한 번 띄워 두고 차례마다 한 줄씩 보냄(한 번씩 띄우는 'claude -p "…"'·'codex exec' 는 안 씀)
#         claude : claude -p --input-format stream-json --output-format stream-json --include-partial-messages (대화 하나 = 프로세스 하나)
#         codex  : codex app-server (JSON-RPC, 프로세스는 본체가 켜져 있는 동안 하나, 대화 하나 = 스레드 하나)
#     · 글 조각이 오는 대로 내보냄 → 목소리 쪽이 첫 문장이 끝나는 대로 바로 읽음
#     · 대화가 연결되면(인사하는 동안) 미리 띄움(warmup) · 빠른 모델 기본(클로드 haiku · codex 는 그 계정 기본 모델 + 가장 낮은 생각)
#     · 도구·파일 권한 끔(대화 전용): claude --tools "" --safe-mode(사용자 CLAUDE.md·플러그인·훅·MCP 안 읽음)
#                                    codex sandbox read-only + 승인 never + 훅·플러그인·앱·셸 도구 끔 + MCP 서버 비움
#   자식 프로세스 환경에서는 ANTHROPIC_API_KEY·OPENAI_API_KEY·KIMBISEO_KEY_* 를 뺀다(구독 로그인으로만, 종량제 열쇠가 끼어들지 않게).
#   끼어들기: claude = control_request interrupt · codex = turn/interrupt. 대화 글은 기록에 남기지 않는다(글자 수만).
import asyncio
import json
import os
import subprocess
import threading
import time
import uuid

from loguru import logger
from pipecat.frames.frames import (LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
                                   TTSSpeakFrame)
from pipecat.processors.frame_processor import FrameProcessor

from . import cli_detect as D
from . import config as C
from .filters import HanziFilter, ThinkFilter

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KINDS = ("claude_cli", "codex_cli")
LABEL = {"claude_cli": "클로드 코드", "codex_cli": "GPT(Codex)"}
CODEX_OFF = ["--disable", "hooks", "--disable", "plugins", "--disable", "apps", "--disable", "shell_tool", "--disable", "browser_use",
             "--disable", "computer_use", "--disable", "skill_search", "-c", "mcp_servers={}", "-c", 'web_search="disabled"',
             "-c", "project_doc_max_bytes=0"]


class CliError(RuntimeError):
    """사용자에게 소리로 알려 줄 쉬운 이유."""


def child_env(kind):
    env = dict(os.environ)
    for k in list(env):
        ku = k.upper()
        if ku.startswith("KIMBISEO_") or ku in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                                                 "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env.pop(k)
    env["NO_COLOR"] = "1"
    if kind == "claude_cli":
        env["MAX_THINKING_TOKENS"] = "0"            # 생각 끔(첫 글자 빠르게)
        env["DISABLE_AUTOUPDATER"] = "1"
    return env


def workdir(cfg):
    d = os.path.join(C.path(cfg, "자료"), "brain_cli")   # 빈 폴더(그 프로그램이 이 PC 의 다른 파일을 보지 않게)
    os.makedirs(d, exist_ok=True)
    return d


def explain(kind, text):
    """그 프로그램이 낸 오류 글 → 사용자에게 할 말(원문은 기록에 짧게만)."""
    t = str(text or "").lower()
    name = LABEL.get(kind, "구독 두뇌")
    if any(w in t for w in ("login", "log in", "logged", "unauthorized", "401", "auth", "credential", "/login")):
        return f"{name} 로그인이 풀린 것 같아요. 설정의 두뇌에서 '로그인 창 열기'를 눌러 다시 로그인해 주세요."
    if any(w in t for w in ("limit", "quota", "usage", "429", "rate")):
        return f"{name} 구독 사용 한도에 걸린 것 같아요. 잠시 뒤에 다시 말씀해 주시거나 설정에서 다른 두뇌로 바꿔 주세요."
    if any(w in t for w in ("model", "not found", "404")):
        return f"{name}에서 고른 모델을 쓸 수 없어요. 설정의 두뇌에서 모델을 기본으로 바꿔 주세요."
    return f"{name}에 연결이 안 돼요. 인터넷과 로그인을 확인해 주세요."


LIVE = set()   # 지금 켜져 있는 자식(본체가 os._exit 로 끝날 때도 남기지 않으려고 — kill_all_sync)


def kill_all_sync():
    """본체를 끝내기 직전: 내가 띄운 구독 두뇌 프로세스만(PID) 끔."""
    for p in list(LIVE):
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass


class _Proc:
    """자식 프로세스 하나 + 한 줄 JSON 읽기(스레드 → 이벤트 루프 큐). 이벤트 루프 종류와 상관없이 돎."""

    def __init__(self, cmd, cwd, env, name):
        self.name = name
        self.loop = asyncio.get_running_loop()
        self.q = asyncio.Queue()
        self.err_tail = ""
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=NO_WINDOW)
        self.on_line = None
        LIVE.add(self)
        threading.Thread(target=self._read, name=name + "-out", daemon=True).start()
        threading.Thread(target=self._read_err, name=name + "-err", daemon=True).start()

    def _put(self, obj):
        if self.on_line is not None:
            self.on_line(obj)
        else:
            self.q.put_nowait(obj)

    def _read(self):
        for raw in self.p.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            try:
                self.loop.call_soon_threadsafe(self._put, obj)
            except RuntimeError:
                return
        try:
            self.loop.call_soon_threadsafe(self._put, None)
        except RuntimeError:
            pass

    def _read_err(self):
        for raw in self.p.stderr:
            self.err_tail = (self.err_tail + raw.decode("utf-8", "replace"))[-1500:]

    def alive(self):
        return self.p.poll() is None

    def write(self, obj):
        try:
            self.p.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.p.stdin.flush()
        except (OSError, ValueError) as ex:
            raise CliError("구독 두뇌 프로그램이 꺼졌어요.") from ex

    def kill(self):
        LIVE.discard(self)
        if self.p.poll() is None:
            try:
                self.p.stdin.close()
            except OSError:
                pass
            subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def _history_text(history, n=8):
    lines = []
    for u, a in history[-n:]:
        lines.append("사용자: " + u.strip()[:600])
        if a:
            lines.append("비서: " + a.strip()[:600])
    return "\n".join(lines)


# ================================================================ 클로드 코드
class ClaudeCli:
    kind = "claude_cli"

    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.system = ""
        self.history = []
        self.open_turn = False
        self.turns = 0
        self.model = ""

    def _model(self):
        return str((self.cfg.get("두뇌") or {}).get("구독_클로드_모델") or "haiku")

    async def prepare(self, system_text, history=()):
        """이번 대화를 위한 프로세스를 띄워 둔다(이미 같은 지시문으로 떠 있고 아직 안 썼으면 그대로)."""
        self.system = system_text
        self.history = list(history or [])
        if self.proc is not None and self.proc.alive() and self.turns == 0 and getattr(self, "_sys_now", None) == self._sys_full():
            return
        await self.close()
        self._spawn()

    def _sys_full(self):
        s = self.system
        h = _history_text(self.history)
        if h:
            s += "\n\n[이 대화의 앞부분 — 이어서 대답]\n" + h
        return s

    def _spawn(self):
        exe = D.find("claude")
        if not exe:
            raise CliError("이 PC 에 클로드 코드가 없어요. 설정의 두뇌에서 설치 안내를 봐 주세요.")
        wd = workdir(self.cfg)
        sp = os.path.join(wd, "system_claude.txt")
        full = self._sys_full()
        with open(sp, "w", encoding="utf-8") as f:
            f.write(full)
        self._sys_now = full
        self.model = self._model()
        try:   # .exe 먼저 · npm .cmd 면 node + 진짜 .js 로(cmd.exe 를 거치지 않게) · 안 되면 특수문자 있는 경로는 거절
            cmd = D.command("claude", ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                                       "--model", self.model, "--tools", "", "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                                       "--setting-sources", "", "--permission-mode", "dontAsk", "--system-prompt-file", sp], exe)
        except OSError as ex:
            raise CliError(str(ex)) from None
        t0 = time.perf_counter()
        self.proc = _Proc(cmd, wd, child_env(self.kind), "claude-cli")
        self.turns = 0
        self.open_turn = False
        logger.info(f"구독 두뇌(클로드 코드) 띄움 PID {self.proc.p.pid} · 모델 {self.model} · 지시문 {len(full)}자 ({(time.perf_counter() - t0) * 1000:.0f}ms)")

    async def _drain(self, sec):
        end = time.monotonic() + sec
        while self.open_turn and time.monotonic() < end:
            try:
                ev = await asyncio.wait_for(self.proc.q.get(), max(0.05, end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            if ev is None or (isinstance(ev, dict) and ev.get("type") == "result"):
                self.open_turn = False
        return not self.open_turn

    async def ask(self, text, first_timeout=60.0):
        if self.proc is None or not self.proc.alive():
            self._spawn()
        if self.open_turn and not await self._drain(4.0):
            logger.info("구독 두뇌(클로드): 끊긴 답이 안 끝나 다시 띄움")
            await self.close()
            self._spawn()
        self.proc.write({"type": "user", "message": {"role": "user", "content": text}})
        self.open_turn = True
        self.turns += 1
        got, out = False, []
        while True:
            try:
                ev = await asyncio.wait_for(self.proc.q.get(), first_timeout if not got else 60.0)
            except asyncio.TimeoutError:
                raise CliError(f"클로드 코드가 {int(first_timeout)}초 안에 대답하지 않아요.") from None
            if ev is None:
                self.open_turn = False
                tail = self.proc.err_tail[-300:]
                logger.warning(f"구독 두뇌(클로드) 프로세스 끝남: {tail!r}")
                raise CliError(explain(self.kind, tail))
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event") or {}
                d = e.get("delta") or {}
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                    got = True
                    out.append(d["text"])
                    yield d["text"]
            elif t == "assistant" and not got:
                msg = ev.get("message") or {}
                txt = "".join(c.get("text", "") for c in msg.get("content") or [] if isinstance(c, dict) and c.get("type") == "text")
                if txt:
                    got = True
                    out.append(txt)
                    yield txt
            elif t == "result":
                self.open_turn = False
                if ev.get("is_error") and not got:
                    logger.warning(f"구독 두뇌(클로드) 오류 결과: {str(ev.get('result'))[:160]!r} {ev.get('subtype')}")
                    raise CliError(explain(self.kind, str(ev.get("result")) + " " + str(ev.get("subtype"))))
                self.history.append((text, "".join(out)))
                return

    async def interrupt(self):
        if self.proc is not None and self.proc.alive() and self.open_turn:
            try:
                self.proc.write({"type": "control_request", "request_id": "int-" + uuid.uuid4().hex[:8], "request": {"subtype": "interrupt"}})
            except CliError:
                pass

    def note_cut(self, user, said):
        """끼어들기로 끊긴 차례도 다시 띄울 때 이어지게 적어 둠."""
        self.history.append((user, said))

    async def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc = None


# ================================================================ GPT(Codex)
class CodexCli:
    kind = "codex_cli"

    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.pending = {}
        self.notes = None
        self.n = 0
        self.thread = None
        self.models = []
        self.model = ""
        self.effort = None
        self.system = ""
        self.history = []
        self.turn_id = None
        self.lock = asyncio.Lock()

    def _dispatch(self, obj):
        if obj is None:
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(CliError("Codex 프로그램이 꺼졌어요."))
            self.pending.clear()
            self.notes.put_nowait(None)
            return
        if "id" in obj and ("result" in obj or "error" in obj) and "method" not in obj:
            f = self.pending.pop(obj["id"], None)
            if f is not None and not f.done():
                f.set_result(obj)
            return
        if "method" in obj and "id" in obj:   # 그 프로그램이 묻는 것(명령 실행·파일 바꾸기 승인 등) → 모두 거절
            m = obj["method"]
            res = {"decision": "decline"} if "Approval" in m or "approval" in m else {}
            try:
                self.proc.write({"jsonrpc": "2.0", "id": obj["id"], **({"result": res} if res else
                                                                       {"error": {"code": -32601, "message": "not supported"}})})
            except CliError:
                pass
            return
        if "method" in obj:
            self.notes.put_nowait(obj)

    async def rpc(self, method, params=None, timeout=30.0):
        self.n += 1
        i = self.n
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        self.proc.write({"jsonrpc": "2.0", "id": i, "method": method, **({"params": params} if params is not None else {})})
        try:
            r = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.pending.pop(i, None)
            raise CliError(f"Codex 가 {int(timeout)}초 안에 대답하지 않아요({method}).") from None
        if "error" in r:
            msg = str((r.get("error") or {}).get("message") or "")
            logger.warning(f"구독 두뇌(Codex) {method} 오류: {msg[:160]!r}")
            raise CliError(explain(self.kind, msg))
        return r.get("result") or {}

    async def ensure(self):
        if self.proc is not None and self.proc.alive():
            return
        exe = D.find("codex")
        if not exe:
            raise CliError("이 PC 에 Codex 가 없어요. 설정의 두뇌에서 설치 안내를 봐 주세요.")
        t0 = time.perf_counter()
        self.notes = asyncio.Queue()
        self.pending = {}
        try:
            argv = D.command("codex", ["app-server", *CODEX_OFF], exe)
        except OSError as ex:
            raise CliError(str(ex)) from None
        self.proc = _Proc(argv, workdir(self.cfg), child_env(self.kind), "codex-cli")
        self.proc.on_line = self._dispatch
        from ..version import VERSION
        await self.rpc("initialize", {"clientInfo": {"name": "kimbiseo", "title": "KimBiseo", "version": VERSION}}, 30)
        self.proc.write({"jsonrpc": "2.0", "method": "initialized"})
        try:
            r = await self.rpc("model/list", {}, 30)
            self.models = list(r.get("data") or [])
        except CliError:
            self.models = []
        self.thread = None
        logger.info(f"구독 두뇌(Codex) app-server 띄움 PID {self.proc.p.pid} · 모델 {len(self.models)}개 ({(time.perf_counter() - t0) * 1000:.0f}ms)")

    def _pick(self):
        b = self.cfg.get("두뇌") or {}
        want = str(b.get("구독_GPT_모델") or "")
        ids = [m.get("id") or m.get("model") for m in self.models]
        if want and (want in ids or not ids):
            model = want
        else:
            dflt = next((m for m in self.models if m.get("isDefault")), self.models[0] if self.models else None)
            model = (dflt or {}).get("id") or (dflt or {}).get("model") or ""
        m = next((x for x in self.models if (x.get("id") or x.get("model")) == model), {})
        efforts = [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts") or [] if e.get("reasoningEffort")]
        want_e = str(b.get("구독_GPT_생각") or "")
        order = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
        if want_e and (want_e in efforts or not efforts):
            eff = want_e
        else:
            eff = next((e for e in order if e in efforts), efforts[0] if efforts else None)
        return model, eff

    async def prepare(self, system_text, history=()):
        async with self.lock:
            await self.ensure()
            self.system = system_text
            self.history = list(history or [])
            await self._new_thread()

    async def _new_thread(self):
        self.model, self.effort = self._pick()
        s = self.system
        h = _history_text(self.history)
        if h:
            s += "\n\n[이 대화의 앞부분 — 이어서 대답]\n" + h
        p = {"cwd": workdir(self.cfg), "sandbox": "read-only", "approvalPolicy": "never", "ephemeral": True, "baseInstructions": s}
        if self.model:
            p["model"] = self.model
        r = await self.rpc("thread/start", p, 30)
        self.thread = (r.get("thread") or {}).get("id")
        self.model = r.get("model") or self.model
        logger.info(f"구독 두뇌(Codex) 새 스레드 · 모델 {self.model} · 생각 {self.effort} · 지시문 {len(s)}자")

    async def ask(self, text, first_timeout=60.0):
        if self.proc is None or not self.proc.alive() or not self.thread:
            await self.prepare(self.system)
        while not self.notes.empty():      # 지난 차례 끝물(끊긴 답 조각 등) 버림
            if self.notes.get_nowait() is None:
                await self.prepare(self.system)
        p = {"threadId": self.thread, "input": [{"type": "text", "text": text}]}
        if self.effort:
            p["effort"] = self.effort
        r = await self.rpc("turn/start", p, 30)
        tid = (r.get("turn") or {}).get("id")
        self.turn_id = tid
        got, out = False, []
        try:
            while True:
                try:
                    m = await asyncio.wait_for(self.notes.get(), first_timeout if not got else 60.0)
                except asyncio.TimeoutError:
                    raise CliError(f"Codex 가 {int(first_timeout)}초 안에 대답하지 않아요.") from None
                if m is None:
                    raise CliError(explain(self.kind, self.proc.err_tail[-300:] if self.proc else ""))
                meth, pr = m.get("method"), m.get("params") or {}
                if pr.get("threadId") not in (None, self.thread):
                    continue
                if meth == "item/agentMessage/delta" and pr.get("turnId") == tid:
                    if pr.get("delta"):
                        got = True
                        out.append(pr["delta"])
                        yield pr["delta"]
                elif meth == "error" and pr.get("turnId") == tid and not pr.get("willRetry"):
                    msg = str((pr.get("error") or {}).get("message") or "")
                    logger.warning(f"구독 두뇌(Codex) 오류: {msg[:160]!r}")
                    if not got:
                        raise CliError(explain(self.kind, msg + " " + str((pr.get("error") or {}).get("codexErrorInfo"))))
                elif meth == "turn/completed" and (pr.get("turn") or {}).get("id") == tid:
                    t = pr.get("turn") or {}
                    if t.get("status") == "failed" and not got:
                        e = t.get("error") or {}
                        raise CliError(explain(self.kind, str(e.get("message")) + " " + str(e.get("codexErrorInfo"))))
                    self.history.append((text, "".join(out)))
                    return
        finally:
            self.turn_id = None

    async def interrupt(self):
        tid = self.turn_id
        if self.proc is not None and self.proc.alive() and tid and self.thread:
            try:
                await self.rpc("turn/interrupt", {"threadId": self.thread, "turnId": tid}, 5)
            except CliError:
                pass

    def note_cut(self, user, said):
        self.history.append((user, said))

    async def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc = None
        self.thread = None


# ================================================================ 본체 안 두뇌 칸
POOL = {}   # 종류 → 백엔드(본체가 켜져 있는 동안 하나 — codex 프로세스는 대화가 바뀌어도 그대로 데워져 있음)


def backend(kind, cfg):
    b = POOL.get(kind)
    if b is None:
        b = POOL[kind] = (ClaudeCli if kind == "claude_cli" else CodexCli)(cfg)
    b.cfg = cfg
    return b


async def prewarm(cfg):
    """본체가 켜질 때: codex 는 app-server 를 띄워 초기화까지(모델 호출 없음). 클로드는 대화가 연결될 때 띄움."""
    kind = str((cfg.get("두뇌") or {}).get("방식") or "")
    if kind == "codex_cli":
        try:
            await backend(kind, cfg).ensure()
        except Exception as ex:  # noqa: BLE001
            logger.info(f"구독 두뇌 미리 띄우기 못 함: {ex}")


async def shutdown_except(kind):
    """두뇌를 바꾸면 안 쓰는 구독 두뇌 프로세스는 끔."""
    for k in list(POOL):
        if k != kind:
            b = POOL.pop(k)
            try:
                await b.close()
            except Exception:  # noqa: BLE001
                pass


async def shutdown_all():
    for b in list(POOL.values()):
        try:
            await b.close()
        except Exception:  # noqa: BLE001
            pass
    POOL.clear()


class CliBrain(FrameProcessor):
    """파이프라인의 두뇌 자리. 마지막 사용자 말만 그 프로그램에 보내고(대화 기억은 그 프로그램 세션이 가짐) 글 조각을 바로 내보낸다."""

    def __init__(self, state, cfg, kind):
        super().__init__()
        self.state, self.cfg, self.kind = state, cfg, kind
        self.be = backend(kind, cfg)
        self.guard = None
        self.timing_log = []
        self.last_timing = None
        self.rescued = 0
        self.cur_user_key = None
        self.mode = "빠른"
        self.ready = None

    def register_function(self, *a, **k):
        return None

    async def prepare(self, system_text, history=()):
        t0 = time.perf_counter()
        try:
            await self.be.prepare(system_text, history)
            self.ready = True
        except CliError as ex:
            self.ready = str(ex)
            logger.warning(f"구독 두뇌 준비 못 함: {ex}")
        except Exception as ex:  # noqa: BLE001
            self.ready = explain(self.kind, str(ex))
            logger.warning(f"구독 두뇌 준비 오류: {ex.__class__.__name__} {ex}")
        return {"초": round(time.perf_counter() - t0, 2), "준비": self.ready is True}

    def _last_user(self, context):
        from .brain import BrainLLM
        m = BrainLLM._tag_time(self, context)
        return m

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return
        um = self._last_user(frame.context)
        st = self.state
        st.stop_now = bool(um and st.is_stop(um.get("content")))
        text = str((um or {}).get("content") or "").strip()
        if not text:
            return
        think, hanzi = ThinkFilter(), HanziFilter()
        said = []
        t0 = time.perf_counter()
        first = None
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            async for piece in self.be.ask(text):
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                t = think.feed(piece)
                t = hanzi.feed(t) if t else t
                if t:
                    said.append(t)
                    await self.push_frame(LLMTextFrame(t))
            rest = think.flush()
            rest = (hanzi.feed(rest) if rest else "") + hanzi.flush()
            if rest:
                said.append(rest)
                await self.push_frame(LLMTextFrame(rest))
        except asyncio.CancelledError:
            if said:
                self.be.note_cut(text, "".join(said) + " …(끊김)")
            asyncio.ensure_future(self.be.interrupt())
            raise
        except CliError as ex:
            st.event("brain_error", reason=str(ex)[:200])
            await self.push_frame(LLMFullResponseEndFrame())
            await self.push_frame(TTSSpeakFrame(str(ex)))
            return
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"구독 두뇌 응답 실패: {ex.__class__.__name__} {str(ex)[:160]}")
            st.event("brain_error", reason=ex.__class__.__name__)
            await self.push_frame(LLMFullResponseEndFrame())
            await self.push_frame(TTSSpeakFrame(explain(self.kind, str(ex))))
            return
        info = {"ttft_ms": round(first) if first is not None else None, "total_ms": round((time.perf_counter() - t0) * 1000),
                "글자": sum(len(x) for x in said), "두뇌": self.kind}
        self.last_timing = info
        self.timing_log.append(info)
        logger.info(f"구독 두뇌 답: 첫 글자 {info['ttft_ms']}ms · 끝 {info['total_ms']}ms · {info['글자']}자")
        await self.push_frame(LLMFullResponseEndFrame())


async def one_shot(cfg, messages, max_chars=1500, timeout=90.0):
    """대화 밖 한 번 묻기(일기·자동 기억) — 그 대화와 섞이지 않게 따로. 실패하면 ''."""
    kind = str((cfg.get("두뇌") or {}).get("방식") or "")
    sys_t = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    user_t = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") != "system")
    try:
        if kind == "claude_cli":
            be = ClaudeCli(cfg)
            await be.prepare(sys_t or "짧게 답한다.")
        else:
            main = backend(kind, cfg)
            await main.ensure()
            be = _SideThread(main)                 # 같은 app-server 에 따로 스레드
            await be.prepare(sys_t or "짧게 답한다.")
        out = []
        async for t in be.ask(user_t, first_timeout=timeout):
            out.append(t)
            if sum(len(x) for x in out) > max_chars:
                break
        if kind == "claude_cli":
            await be.close()
        return "".join(out).strip()
    except Exception as ex:  # noqa: BLE001
        logger.info(f"구독 두뇌 한 번 묻기 실패: {ex.__class__.__name__}")
        return ""


class _SideThread:
    """같은 codex app-server 에서 대화와 다른 스레드로 한 번 묻기(대화 스레드·차례는 그대로)."""

    def __init__(self, main):
        self.main = main
        self.thread = None

    async def prepare(self, system_text):
        m = self.main
        model, _eff = m._pick()
        p = {"cwd": workdir(m.cfg), "sandbox": "read-only", "approvalPolicy": "never", "ephemeral": True, "baseInstructions": system_text}
        if model:
            p["model"] = model
        r = await m.rpc("thread/start", p, 30)
        self.thread = (r.get("thread") or {}).get("id")

    async def ask(self, text, first_timeout=60.0):
        m = self.main
        saved = m.thread, m.history[:]
        m.thread = self.thread
        try:
            async for t in m.ask(text, first_timeout):
                yield t
        finally:
            m.thread, m.history = saved
