"""두뇌가 도구 호출을 '글'로 써 버렸을 때 건져 내기.

작은 모델(예: Gemma 4 E4B, 생각 끔)은 도구 호출 시작 표시를 빼먹고 답 글에
`get_weather{day:<|"|>tomorrow<|"|>}` · `standby()` · `forget(what='매운 음식')` ·
`get_weather(day=tomorrow, place=서울)`(따옴표 없는 값) · `calc(32000+14000)`(이름 없는 인자) 처럼 쓰고,
가끔은 ```tool_code … ``` 나 `…` 로 감쌉니다.
서버(llama-server)는 이것을 도구 호출로 못 알아채므로 본체가 건져 진짜 도구 호출로 바꿉니다.

    calls = rescue(content, ["get_weather", "standby"])                 # 글 '전체'가 호출일 때만 → [(이름, 인자 dict)] 또는 None
    calls, end = parse_calls(text, names, first={"calc": "expression"})  # 글 '앞부분'의 호출들과 끝난 자리(못 읽으면 None, 0)
    looks_like_call(text, names)                                         # 알려진 도구 이름 + ( / { 로 시작하는가(못 건져도 소리로 읽지 않게)
first = {도구: 이름 없이 준 인자 하나를 넣을 칸}(없으면 아래 FIRST 기본값). 글 중간에 도구 이름이 섞인 보통 문장은 건드리지 않습니다.
"""
from __future__ import annotations

import ast
import re

_Q = '<|"|>'
_HEAD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*")
# 이름 없이 인자 하나만 쓴 경우(예: calc(32000+14000)) 넣을 칸 — 기본 도구 묶음. 다른 묶음은 본체가 도구 정의에서 첫 칸을 알려 줌
MAX_BODY = 4600   # 인자 칸 글자 수 상한(이보다 길면 호출로 보지 않음 — type_text 4000자가 들어가게)
FIRST = {"calc": "expression", "web_search": "query", "remember": "content", "recall": "query", "forget": "what",
         "get_weather": "place", "read_page": "url", "speech_speed": "speed", "type_text": "text"}


def _bare(v: str):
    v = v.strip()
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v.strip("'\"")


def _gemma_args(body: str) -> dict | None:
    """{key:<|"|>값<|"|>,key2:123} → dict. 꼴이 어긋나면 None."""
    s = body.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    s = s[1:-1]
    out, i, n = {}, 0, len(s)
    while i < n:
        while i < n and s[i] in " ,\n\t":
            i += 1
        if i >= n:
            break
        m = re.match(r"[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s*:\s*", s[i:])
        if not m:
            return None
        key = m.group(1)
        i += m.end()
        if s.startswith(_Q, i):
            j = s.find(_Q, i + len(_Q))
            if j < 0:
                return None
            out[key] = s[i + len(_Q):j]
            i = j + len(_Q)
        elif i < n and s[i] in "\"'":
            q = s[i]
            j = s.find(q, i + 1)
            if j < 0:
                return None
            out[key] = s[i + 1:j]
            i = j + 1
        else:
            j = i
            while j < n and s[j] != ",":
                j += 1
            out[key] = _bare(s[i:j])
            i = j
    return out


def _value(src: str, node):
    """인자 값: 글자 그대로의 값(문자·숫자·참거짓) → 그 값 / 따옴표 없는 낱말(tomorrow·서울) → 그 글 / 식(32000+14000) → 식 글."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
        pass
    if isinstance(node, ast.Name):
        return node.id
    seg = ast.get_source_segment(src, node)
    if seg is None or not seg.strip() or len(seg) > 400:
        raise ValueError("값을 읽을 수 없음")
    return seg.strip()


def _py_args(body: str, first_key: str | None) -> dict | None:
    """(key='값', key2=1) · (key=낱말) · (식 하나) → dict."""
    src = "f" + body.strip()
    if len(src) > MAX_BODY:
        return None
    try:
        node = ast.parse(src, mode="eval").body
    except SyntaxError:
        return _kv_args(body)
    except (RecursionError, MemoryError, ValueError):
        return None
    if not isinstance(node, ast.Call):
        return None
    out = {}
    try:
        if node.args:
            if len(node.args) != 1 or not first_key or isinstance(node.args[0], ast.Starred):
                return None
            out[first_key] = _value(src, node.args[0])
        for kw in node.keywords:
            if kw.arg is None:
                return None
            out[kw.arg] = _value(src, kw.value)
    except (ValueError, RecursionError, MemoryError):
        return None
    return out


_KV = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^,]*)\s*(?:,|$)")


def _kv_args(body: str) -> dict | None:
    """파이썬 꼴이 아닌 (key=띄어 쓴 낱말들, key2=값) → dict(값에 쉼표·괄호가 없을 때만)."""
    s = body.strip()
    if not (s.startswith("(") and s.endswith(")")):
        return None
    s = s[1:-1].strip()
    if not s or "(" in s or ")" in s:
        return None
    out, i = {}, 0
    while i < len(s):
        m = _KV.match(s, i)
        if not m or m.end() == i:
            return None
        out[m.group(1)] = _bare(m.group(2))
        i = m.end()
    return out or None


_PRE = re.compile(r"```[A-Za-z_]*|`|<\|tool_call>|call:")
_POST = ("```", "`", "<tool_call|>")


def _clean(content: str) -> str:
    """앞뒤의 ``` · ` · <|tool_call> · call: · <tool_call|> 를 떼어 냄(정규식 되풀이 없이 — 긴 공백에도 바로 끝남)."""
    t = str(content or "").strip()
    for _ in range(6):
        m = _PRE.match(t)
        if not m:
            break
        t = t[m.end():].lstrip()
    for _ in range(6):
        hit = next((x for x in _POST if t.endswith(x)), None)
        if not hit:
            break
        t = t[: -len(hit)].rstrip()
    return t


def parse_calls(text: str | None, tool_names, first=None, start=0):
    """text[start:] 앞부분의 도구 호출들 → ([(이름, 인자)], 끝난 자리). 첫 호출부터 못 읽으면 (None, start)."""
    if not text:
        return None, start
    names = set(tool_names)
    fk = {**FIRST, **(first or {})}
    s = text
    calls, i = [], start
    end = start
    while i < len(s):
        k = i
        while k < len(s) and s[k] in " \n\t;,`":
            k += 1
        if k >= len(s):
            break
        m = _HEAD.match(s, k)
        if not m or m.group(1) not in names:
            break
        name, j0 = m.group(1), m.end()
        if j0 >= len(s) or s[j0] not in "{(":
            # 이름만 쓴 경우는 글 전체가 이름 하나일 때만(인자 없는 도구)
            if not calls and not s[j0:].strip(" \n\t.`"):
                calls.append((name, {}))
                end = len(s)
            break
        opener = s[j0]
        closer = "}" if opener == "{" else ")"
        depth, j, in_q, qch = 0, j0, False, ""
        while j < len(s):
            if s.startswith(_Q, j):
                in_q = not in_q
                j += len(_Q)
                continue
            ch = s[j]
            if qch:
                if ch == qch:
                    qch = ""
            elif not in_q:
                if ch in "\"'":
                    qch = ch
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        if depth != 0:
            break
        body = s[j0:j + 1]
        if len(body) > MAX_BODY:
            break
        args = _gemma_args(body) if opener == "{" else _py_args(body, fk.get(name))
        if args is None:
            break
        calls.append((name, args))
        i = end = j + 1
    return (calls or None), (end if calls else start)


def rescue(content: str | None, tool_names, first=None) -> list[tuple[str, dict]] | None:
    """글 '전체'가 알려진 도구 호출(하나 이상)일 때만 → [(이름, 인자)]. 아니면 None."""
    if not content:
        return None
    s = _clean(content)
    calls, end = parse_calls(s, tool_names, first)
    if not calls or s[end:].strip(" \n\t;,.`"):
        return None
    return calls


_LOOK = re.compile(r"^\s*(?:```[A-Za-z_]*\s*)?`?\s*(?:<\|tool_call>\s*)?(?:call:\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*[({]")


def looks_like_call(text: str | None, tool_names) -> bool:
    """알려진 도구 이름 바로 뒤에 ( 나 { 가 오는 글인가(건지지 못했더라도 이런 글은 화면·소리로 내보내지 않음)."""
    m = _LOOK.match(str(text or ""))
    return bool(m and m.group(1) in set(tool_names))


# ---------------------------------------------------------------- 약속만 한 답(도구는 안 부르고 '열어 드릴게요'로 끝남)
#   작은 두뇌가 이렇게 답하면 본체가 한 번 더(tool_choice=required — 도구를 꼭 부르게) 묻고, 그래도 말뿐이면 그 차례를 다음 요청의
#   대화 기록에서 뺀다(한 번 말만 하면 그 대화 내내 말만 하는 버릇이 생겨서).
_PROMISE = re.compile(r"(드릴게요|드릴께요|드리겠습니다|드릴까요|볼게요|볼께요|할게요|할께요|하겠습니다|할까요|열게요|켤게요|적을게요|"
                      r"찾을게요|둘게요|시작할게요|기다려\s*주세요|잠시만요)[.!~…?\s]*$")
_ACTION = re.compile(r"(켜|켤|열어|열게|열 어|띄워|검색|찾아|찾을|알려|적어|적을|써\s*줘|써줘|정리|계산|기억|날씨|가격|조사|틀어|읽어|요약|메모|"
                     r"얼마|더하기|빼기|곱하기|나누기|퍼센트)")
_BODY = re.compile(r"(춤|춰|앉아|앉을|누워|눕|일어나|하트|브이|윙크|박수|엄지|기지개|손\s*흔들|손 들어|인사해|점프|뛰어)")


def is_promise(text: str | None) -> bool:
    """도구 없이 '해 드릴게요'·'알려 드릴까요?' 같은 약속(또는 되묻기)만 한 짧은 답인가."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return bool(t) and len(t) <= 120 and bool(_PROMISE.search(t))


MEMO_WANT = re.compile(r"(메모장에|메모에|메모해|적어|적을|받아\s*적|써\s*줘|써줘|기록해)")


_STRONG = re.compile(r"(켜|켤|열어|띄워|검색|찾아|조사|적어|메모장에|메모해|기억해|계산|더하기|빼기|곱하기|나누기|퍼센트|날씨|가격|시세|틀어|"
                     r"\d\s*[+\-*/x×]\s*\d)")


def wants_action(user_text: str | None) -> bool:
    """사용자 말이 도구가 필요한 부탁(켜·열어·검색·찾아·알려·적어·정리·계산·기억 등)인가. 몸동작 부탁(춤·앉아…)은 아님."""
    t = str(user_text or "")
    return bool(_ACTION.search(t)) and not _BODY.search(t)


def names_in(text: str | None, tool_names) -> bool:
    t = str(text or "")
    return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])", t) for n in tool_names)


def strong_action(user_text) -> bool:
    """도구 없이 말로만 답해도(약속이 아니어도) 다시 물을 부탁인가 — '메모장 열어줘'·'3+4 계산해'·'부산 날씨'."""
    return wants_action(user_text) and bool(_STRONG.search(str(user_text or "")))


def need_retry(user_text, said, raw, tool_names, dropped=False, after_tool=False, called=()) -> bool:
    """도구를 꼭 부르게(tool_choice=required) 한 번 더 물을까.
    · 사용자 말이 도구가 필요한 부탁이어야 함(잡담·몸동작은 아님)
    · 첫 답: 호출 꼴이 깨졌거나 / 약속만 했거나('열어 드릴게요') / 도구 이름을 글로 씀
    · 도구 결과 뒤: 메모장에 적어 달라는데 아직 type_text 를 안 불렀을 때만(같은 도구를 또 부르는 것을 막으려고)"""
    if not wants_action(user_text):
        return False
    named = names_in(raw, tool_names)
    if after_tool:
        return ("type_text" in tool_names and "type_text" not in set(called) and bool(MEMO_WANT.search(str(user_text or ""))))
    if dropped:
        return True
    if _STRONG.search(str(user_text or "")) and not called:
        return True     # 꼭 도구가 필요한 부탁인데 이 말에 아직 아무 도구도 안 부름(직접 계산·'켰어요' 같은 거짓 답 포함)
    return (is_promise(said) or named) and (wants_action(said) or named)


# ---------------------------------------------------------------- 흘러오는 글에서 호출 떼어 내기
_ANGLE = re.compile(r"<<\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*>>", re.S)
_START = re.compile(r"(?:```[A-Za-z_]*[ \t]*\n?\s*|`\s*)?(?:<\|tool_call>\s*)?(?:call:\s*)?(?<![A-Za-z0-9_/.\-])([A-Za-z_][A-Za-z0-9_]*)[({]")
_ANGLE_HEAD = re.compile(r"<<\s*([A-Za-z_][A-Za-z0-9_]*)")
# JSON 꼴: {"tool_name": "get_weather", "params": {...}} · {"name": "calc", "arguments": {...}} (```json 으로 감싸기도 함)
_JSON_HEAD = re.compile(r"(?:```[A-Za-z_]*[ \t]*\n?\s*)?\{\s*\"(?:tool_name|tool|name|function)\"\s*:\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")
_JSON_PART = re.compile(r"(?:```[A-Za-z_]*[ \t]*\n?\s*)?\{\s*(?:\"[a-z_]*(?:\"\s*(?::\s*(?:\"[A-Za-z0-9_]*)?)?)?)?")
# 소리로 읽힐 글에 섞인 도구 이름(예: 'calc를 불러서') → 쉬운 말
SAY = {"calc": "계산기", "get_weather": "날씨", "web_search": "검색", "read_page": "페이지 읽기", "remember": "기억",
       "recall": "기억 찾기", "forget": "잊기", "pc_action": "컴퓨터 조작", "type_text": "메모장 쓰기", "speech_speed": "말 빠르기", "standby": "대기"}


def _json_call(text: str, names):
    import json
    t = _clean(text)
    t = re.sub(r"^```[A-Za-z_]*\s*|\s*```$", "", t.strip())
    j = t.rfind("}")
    if not t.startswith("{") or j < 0:
        return None
    try:
        d = json.loads(t[:j + 1])
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    name = d.get("tool_name") or d.get("tool") or d.get("name") or d.get("function")
    if isinstance(name, dict):
        d = {**d, **name}
        name = name.get("name")
    if name not in set(names):
        return None
    a = d.get("params", d.get("parameters", d.get("arguments", {})))
    if isinstance(a, str):
        try:
            a = json.loads(a) if a.strip() else {}
        except ValueError:
            return None
    return [(name, a)] if isinstance(a, dict) else None


def _angle_args(body: str, first_key: str | None):
    b = body.strip()
    if not b:
        return {}
    if b.startswith("{"):
        try:
            import json
            v = json.loads(b)
            return v if isinstance(v, dict) else None
        except ValueError:
            return _gemma_args(b)
    if b.startswith("("):
        return _py_args(b, first_key)
    return {first_key: b.strip("'\"")} if first_key else None


def parse_angle(text: str, tool_names, first=None):
    """<<이름 {"인자": "값"}>> 이 하나 이상 → [(이름, 인자)] (모르는 이름·읽을 수 없는 인자는 뺌)."""
    import json
    names = set(tool_names)
    fk = {**FIRST, **(first or {})}
    out = []
    t = str(text or "")
    i = 0
    dec = json.JSONDecoder()
    while True:
        m = _ANGLE_HEAD.search(t, i)
        if not m:
            break
        name, j = m.group(1), m.end()
        while j < len(t) and t[j] in " \t":
            j += 1
        a, k = None, -1
        if j < len(t) and t[j] == "{":
            try:
                v, e = dec.raw_decode(t, j)
                rest = t[e:].lstrip()
                if isinstance(v, dict) and rest.startswith(">>"):
                    a, k = v, t.index(">>", e) + 2
            except ValueError:
                pass
        if k < 0:
            mm = _ANGLE.match(t, m.start())
            if not mm:
                i = m.end()
                continue
            a, k = _angle_args(mm.group(2), fk.get(name)), mm.end()
        if name in names and a is not None:
            out.append((name, a))
        i = k
    return out or None


class CallSplitter:
    """두뇌 글 조각을 받아 '지금 내보내도 되는 글'만 돌려주고, 도구 호출 꼴(글 중간이라도)은 떼어 잡아 둔다.
        s = CallSplitter(names); out = s.feed(조각) …; rest, calls, dropped = s.finish()
    calls = 건진 호출들(그 뒤 글은 버림) · dropped = 호출 꼴인데 못 읽어서 버림(화면·소리로 내보내지 않음).
    보통 한국어 글은 바로 흘려보내고, 끝이 도구 이름 앞부분·` · << 처럼 호출의 시작일 수 있을 때만 그 몇 글자를 잠깐 잡는다."""

    def __init__(self, tool_names, first=None, angle_only=False):
        self.names = list(tool_names)
        self.nameset = set(self.names)
        self.first = first or {}
        self.angle_only = angle_only     # 구독 두뇌: <<도구 {…}>> 꼴만, 답 맨 앞이나 줄 맨 앞에 있을 때만(옮겨 말한 글이 실행되지 않게)
        self.buf = ""
        self.cap = None
        self.emitted = False
        self.cap_mid = False             # 앞에 이미 내보낸 글이 있는 뒤에 잡았나

    def _line_start(self, s, k):
        """s[k] 앞이 답 맨 앞(아직 아무것도 안 내보냄)이거나 줄바꿈뿐인가."""
        pre = s[:k].rstrip(" \t")
        return (not pre and not self.emitted) or pre.endswith("\n")

    def _start(self, s):
        if self.angle_only:
            return next((m.start() for m in _ANGLE_HEAD.finditer(s) if m.group(1) in self.nameset and self._line_start(s, m.start())), None)
        i = next((m.start() for m in _ANGLE_HEAD.finditer(s) if m.group(1) in self.nameset), -1)
        best = None
        for m in _START.finditer(s):
            if m.group(1) in self.nameset:
                best = m.start()
                break
        j = s.find("<|tool_call>")
        js = next((m.start() for m in _JSON_HEAD.finditer(s) if m.group(1) in self.nameset), None)
        cands = [x for x in (i if i >= 0 else None, best, j if j >= 0 else None, js) if x is not None]
        return min(cands) if cands else None

    def _maybe_start(self, r):
        """r(글 끝 조각)이 호출의 시작일 수 있나."""
        if not r:
            return False
        if self.angle_only:
            a = re.fullmatch(r"<<?\s*([A-Za-z_][A-Za-z0-9_]*)?(\s*)", r)
            if not a:
                return False
            ident = a.group(1) or ""
            return not ident or (ident in self.nameset if a.group(2) else any(n.startswith(ident) for n in self.names))
        if "<|tool_call>".startswith(r) or r.startswith("<|tool_call>") or r in ("<", "<<"):
            return True
        if len(r) < 60 and _JSON_PART.fullmatch(r):
            return True
        a = re.fullmatch(r"<<\s*([A-Za-z_][A-Za-z0-9_]*)?(\s*)", r)
        if a:
            ident = a.group(1) or ""
            return not ident or (ident in self.nameset if a.group(2) else any(n.startswith(ident) for n in self.names))
        m = re.fullmatch(r"(?:```[A-Za-z_]*[ \t]*\n?\s*|`\s*)?(?:<\|tool_call>\s*)?(?:call:\s*)?([A-Za-z_][A-Za-z0-9_]*)?([\s.`]*)", r)
        if not m:
            return False
        ident, sp = m.group(1), m.group(2)
        if not ident:
            return r.lstrip().startswith("`")
        if sp:
            return ident in self.nameset
        return any(n.startswith(ident) for n in self.names)

    def _hold_from(self, s):
        lo = max(0, len(s) - 48)
        for k in range(lo, len(s)):
            if k > 0 and (s[k - 1].isascii() and (s[k - 1].isalnum() or s[k - 1] in "_/.-")):
                continue
            if self.angle_only and not self._line_start(s, k):
                continue
            if self._maybe_start(s[k:]):
                return k
        return len(s)

    def feed(self, text: str) -> str:
        if not text:
            return ""
        if self.cap is not None:
            self.cap += text
            return ""
        s = self.buf + text
        p = self._start(s)
        if p is not None:
            out, self.cap, self.buf = s[:p], s[p:], ""
            self.cap_mid = self.emitted or bool(out.strip())
        else:
            k = self._hold_from(s)
            out, self.buf = s[:k], s[k:]
        if out:
            self.emitted = True
        return self.plain(out)

    def plain(self, text):
        """소리로 나갈 글에 도구 이름이 낱말로 섞였으면 쉬운 말로(예: 'calc를' → '계산기를')."""
        if not text or not any(n in text for n in self.names):
            return text
        pairs = {"을": "을를", "를": "을를", "이": "이가", "가": "이가", "은": "은는", "는": "은는", "과": "과와", "와": "과와"}

        def word(m):
            w = SAY.get(m.group(1), "도구")
            j = m.group(2) or ""
            if j:
                last = w[-1]
                has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
                j = pairs[j][0] if has else pairs[j][1]
            return w + j
        return re.sub(r"(?<![A-Za-z0-9_/.\-])(" + "|".join(re.escape(n) for n in sorted(self.names, key=len, reverse=True))
                      + r")(?![A-Za-z0-9_])([을를이가은는과와](?![가-힣]))?", word, text)

    def finish(self):
        """→ (내보낼 남은 글, 호출들 또는 None, 버렸나)."""
        if self.cap is None:
            rest, self.buf = self.buf, ""
            # 잡아 둔 끝 조각이 도구 이름 하나(calc. 등) — 답 전체가 그것뿐일 때만 호출로(문장 끝 낱말 'standby' 로 대기에 들어가지 않게)
            calls = rescue(rest, self.names, self.first) if (rest.strip() and not self.emitted and not self.angle_only) else None
            if calls:
                return "", calls, False
            return self.plain(rest), None, False
        cap, self.cap = self.cap, None
        if self.angle_only:
            calls = parse_angle(cap, self.names, self.first)
            return ("", calls, False) if calls else ("", None, True)
        calls = parse_angle(cap, self.names, self.first) or _json_call(cap, self.names)
        tail = ""
        if not calls:
            c2 = _clean(cap)
            calls, end = parse_calls(c2, self.names, self.first)
            tail = c2[end:].strip(" \n\t;,.`") if calls else ""
        if calls and tail:
            # 호출 꼴 뒤에 말이 더 이어지면('remember(기억) 기능이 있어요') 호출이 아니라 설명 — 실행하지 않고, 호출 꼴만 빼고 나머지 말은 함
            return " " + self.plain(tail), None, True
        if calls:
            return "", calls, False
        return "", None, True
