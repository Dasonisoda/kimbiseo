"""두뇌가 도구 호출을 '글'로 써 버렸을 때 건져 내기.

작은 모델(예: Gemma 4 E4B, 생각 끔)은 도구 호출 시작 표시를 빼먹고 답 글에
`get_weather{day:<|"|>tomorrow<|"|>}` · `standby()` · `forget(what='매운 음식')` 처럼 씁니다.
서버(llama-server)는 이것을 도구 호출로 못 알아채므로, 답 글 '전체'가 알려진 도구 호출 꼴일 때만
도구 호출로 바꿉니다. 글 중간에 도구 이름이 섞인 보통 문장은 건드리지 않습니다.

    calls = rescue(content, ["get_weather", "standby"])   # [(이름, 인자 dict)] 또는 None
"""
from __future__ import annotations

import ast
import re

_Q = '<|"|>'
_WRAP = re.compile(r"^\s*(?:<\|tool_call>)?\s*(?:call:)?\s*|\s*(?:<tool_call\|>)?\s*$")
_HEAD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*")


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
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*", s[i:])
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


def _py_args(body: str) -> dict | None:
    """(key='값', key2=1) → dict. 글자 그대로의 값만."""
    try:
        node = ast.parse("f" + body.strip(), mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call) or node.args:
        return None
    out = {}
    for kw in node.keywords:
        if kw.arg is None:
            return None
        try:
            out[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            return None
    return out


def rescue(content: str | None, tool_names) -> list[tuple[str, dict]] | None:
    if not content:
        return None
    names = set(tool_names)
    s = _WRAP.sub("", content.strip())
    calls, i = [], 0
    while i < len(s):
        while i < len(s) and s[i] in " \n\t;,":
            i += 1
        if i >= len(s):
            break
        m = _HEAD.match(s, i)
        if not m or m.group(1) not in names:
            return None
        name, i = m.group(1), m.end()
        if i >= len(s) or s[i] in " \n\t;,":
            # 이름만 쓴 경우는 글 전체가 이름 하나일 때만(인자 없는 도구)
            if calls or s[i:].strip():
                return None
            calls.append((name, {}))
            break
        opener = s[i]
        if opener not in "{(":
            return None
        closer = "}" if opener == "{" else ")"
        depth, j, in_q = 0, i, False
        while j < len(s):
            if s.startswith(_Q, j):
                in_q = not in_q
                j += len(_Q)
                continue
            ch = s[j]
            if not in_q:
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        if depth != 0:
            return None
        body = s[i:j + 1]
        args = _gemma_args(body) if opener == "{" else _py_args(body)
        if args is None:
            return None
        calls.append((name, args))
        i = j + 1
    return calls or None
