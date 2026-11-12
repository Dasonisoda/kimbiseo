"""두뇌 도구 고르기 시험 — OpenAI 호환 /v1/chat/completions 에 한국어 요청을 보내고 채점합니다.

표준 라이브러리만 씁니다. 도구는 실제로 실행하지 않고 '첫 번째 답에서 어떤 도구를 어떤 인자로 불렀는지'만 봅니다.

    python eval_tools.py --base-url http://127.0.0.1:8880/v1 --thinking off --out 결과.json
    python eval_tools.py --thinking on --repeat 2 --out 결과_생각켬.json

열쇠가 필요한 주소면 --api-key-env 로 열쇠가 든 환경변수 이름만 줍니다(값은 기록하지 않음).
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import operator
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "brain"))
from tool_text_rescue import rescue  # noqa: E402


def post_json(url: str, body: dict, key: str | None, timeout: float) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------- 계산식 채점(안전한 계산만) ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}


def _eval_node(n):
    if isinstance(n, ast.Expression):
        return _eval_node(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_eval_node(n.left), _eval_node(n.right))
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
        v = _eval_node(n.operand)
        return v if isinstance(n.op, ast.UAdd) else -v
    raise ValueError("허용 안 된 식")


def safe_calc(expr: str) -> float:
    s = str(expr).replace(",", "").replace("×", "*").replace("÷", "/").replace("＊", "*")
    s = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    if len(s) > 200:
        raise ValueError("식이 너무 김")
    return _eval_node(ast.parse(s.strip(), mode="eval"))


# ---------- 인자 채점 ----------
def check_rule(val, rule: dict) -> tuple[bool, str]:
    empty = val is None or (isinstance(val, str) and val.strip() == "")
    if "eq" in rule:
        return (str(val) == str(rule["eq"]), f"{val!r} == {rule['eq']!r}")
    if "in" in rule:
        return (str(val) in [str(x) for x in rule["in"]], f"{val!r} in {rule['in']!r}")
    if "contains_any" in rule:
        if empty:
            return False, "비어 있음"
        low = str(val).lower()
        return (any(str(x).lower() in low for x in rule["contains_any"]), f"{val!r} ⊃ {rule['contains_any']!r}")
    if "empty_or_in" in rule:
        if empty:
            return True, "비어 있음(맞음)"
        return (str(val) in [str(x) for x in rule["empty_or_in"]], f"{val!r} 비었거나 {rule['empty_or_in']!r}")
    if "calc_equals" in rule:
        if empty:
            return False, "식 없음"
        try:
            got = safe_calc(val)
        except Exception as e:  # noqa: BLE001
            return False, f"식 못 품: {val!r} ({e})"
        return (abs(got - float(rule["calc_equals"])) < 1e-6, f"{val!r} = {got} (정답 {rule['calc_equals']})")
    return False, "모르는 규칙"


def tool_as_text(content: str | None, names: list[str]) -> str | None:
    """도구 호출을 글로 써 버린 경우(서버가 도구 호출로 못 알아챔) 그 도구 이름."""
    c = content or ""
    for n in names:
        if re.search(r"(?<![A-Za-z_])" + re.escape(n) + r"\s*[({]", c):
            return n
    return None


def grade(case: dict, msg: dict, names: list[str] | None = None) -> dict:
    exp = case["expect"]
    calls = msg.get("tool_calls") or []
    want = exp.get("tool")
    out = {"id": case["id"], "expect_tool": want, "called": [], "pass": False, "fail_type": None, "notes": []}
    parsed = []
    for c in calls:
        fn = (c.get("function") or {})
        raw = fn.get("arguments")
        try:
            args = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
            if not isinstance(args, dict):
                raise ValueError("인자가 객체가 아님")
        except Exception as e:  # noqa: BLE001
            args = None
            out["notes"].append(f"인자 JSON 깨짐: {raw!r} ({e})")
        parsed.append((fn.get("name"), args))
        out["called"].append({"name": fn.get("name"), "arguments": args if args is not None else raw})
    if len(parsed) > 1:
        out["notes"].append(f"도구 {len(parsed)}개 동시 호출")
    if want is None:
        if not parsed and tool_as_text(msg.get("content"), names or []):
            out["fail_type"] = "도구를_글로_씀"
            return out
        if parsed:
            out["fail_type"] = "필요없는_도구"
        else:
            out["pass"] = bool((msg.get("content") or "").strip())
            if not out["pass"]:
                out["fail_type"] = "빈_답"
        return out
    if not parsed:
        leaked = tool_as_text(msg.get("content"), names or [])
        out["fail_type"] = "도구를_글로_씀" if leaked else "도구_안씀"
        return out
    name, args = parsed[0]
    if name != want:
        out["fail_type"] = "다른_도구"
        return out
    if args is None:
        out["fail_type"] = "인자_깨짐"
        return out
    ok_all = True
    for k, rule in (exp.get("args") or {}).items():
        ok, why = check_rule(args.get(k), rule)
        out["notes"].append(("맞음 " if ok else "틀림 ") + k + ": " + why)
        ok_all = ok_all and ok
    out["pass"] = ok_all
    if not ok_all:
        out["fail_type"] = "인자_틀림"
    return out


def grade_rescued(case: dict, msg: dict, names: list[str]) -> dict:
    """도구 호출을 글로 쓴 답을 brain/tool_text_rescue.py 로 건진 뒤 채점(본체가 할 일과 같음)."""
    if not msg.get("tool_calls"):
        calls = rescue(msg.get("content"), names)
        if calls:
            msg = {"content": "", "tool_calls": [
                {"type": "function", "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                for n, a in calls]}
            g = grade(case, msg, names)
            g["notes"].append("글에서 건짐")
            g["rescued"] = True
            return g
    g = grade(case, msg, names)
    g["rescued"] = False
    return g


def summarize(results: list[dict], key: str = "pass", ftkey: str = "fail_type") -> dict:
    n = len(results)
    tool_cases = [r for r in results if r["expect_tool"]]
    none_cases = [r for r in results if not r["expect_tool"]]
    fails: dict[str, int] = {}
    for r in results:
        if not r[key]:
            fails[r[ftkey]] = fails.get(r[ftkey], 0) + 1
    passed = sum(r[key] for r in results)
    return {"runs": n, "pass": passed, "pass_rate": round(passed / n, 4) if n else 0,
            "tool_needed_runs": len(tool_cases), "right_tool_and_args": sum(r[key] for r in tool_cases),
            "no_tool_runs": len(none_cases), "no_tool_correct": sum(r[key] for r in none_cases),
            "fail_types": fails}


def regrade(path: str, cases_path: str, tools_path: str) -> int:
    """저장된 결과 json 을 지금 채점 규칙(+건지기)으로 다시 채점. 결과 json 에 rescued 칸을 더해 덮어씀."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(Path(cases_path).read_text(encoding="utf-8"))["cases"]}
    names = [t["function"]["name"] for t in json.loads(Path(tools_path).read_text(encoding="utf-8"))["tools"]]
    for r in doc["results"]:
        if r.get("fail_type") == "요청_오류":
            r.update({"pass_rescued": False, "fail_type_rescued": "요청_오류"})
            continue
        msg = {"content": r.get("content"), "tool_calls": [
            {"type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)
                                              if isinstance(c["arguments"], dict) else c["arguments"]}}
            for c in r.get("called") or []]}
        case = cases[r["id"]]
        g0 = grade(case, msg, names)
        g1 = grade_rescued(case, msg, names)
        r.update({"pass": g0["pass"], "fail_type": g0["fail_type"],
                  "pass_rescued": g1["pass"], "fail_type_rescued": g1["fail_type"], "rescued": g1["rescued"]})
    doc["summary"]["regraded"] = summarize(doc["results"])
    doc["summary"]["rescued"] = summarize(doc["results"], "pass_rescued", "fail_type_rescued")
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(Path(path).name, json.dumps({"raw": doc["summary"]["regraded"]["pass"], "rescued": doc["summary"]["rescued"]["pass"],
                                       "runs": len(doc["results"]), "fails_rescued": doc["summary"]["rescued"]["fail_types"]},
                                      ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="두뇌 도구 고르기 시험")
    ap.add_argument("--base-url", default="http://127.0.0.1:8880/v1")
    ap.add_argument("--model", default="local")
    ap.add_argument("--api-key-env", default="", help="열쇠가 든 환경변수 이름(값이 아니라 이름)")
    ap.add_argument("--thinking", choices=["on", "off", "default"], default="off")
    ap.add_argument("--cases", default=str(HERE / "cases_ko.json"))
    ap.add_argument("--tools", default=str(HERE / "tools_basic.json"))
    ap.add_argument("--system-variant", default="", help="cases 의 system_variants 중 하나(비우면 기본 system)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=0, help="0 = 생각 끔 512 / 생각 켬 4096")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--only", default="", help="쉼표로 고른 id 만")
    ap.add_argument("--out", default="")
    ap.add_argument("--regrade", default="", help="저장된 결과 json 을 다시 채점(서버 안 부름)")
    a = ap.parse_args()
    if a.regrade:
        return regrade(a.regrade, a.cases, a.tools)
    if not a.out:
        ap.error("--out 이 필요합니다")

    key = os.environ.get(a.api_key_env) if a.api_key_env else None
    cases_doc = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    tools = json.loads(Path(a.tools).read_text(encoding="utf-8"))["tools"]
    now = _dt.datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분")
    base_system = cases_doc["system_variants"][a.system_variant] if a.system_variant else cases_doc["system"]
    system = base_system.replace("{now}", now)
    names = [t["function"]["name"] for t in tools]
    cases = cases_doc["cases"]
    if a.only:
        pick = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in pick]
    max_tokens = a.max_tokens or (4096 if a.thinking == "on" else 512)
    url = a.base_url.rstrip("/") + "/chat/completions"

    results = []
    for rep in range(a.repeat):
        for case in cases:
            msgs = [{"role": "system", "content": system}] + list(case.get("context") or []) + \
                   [{"role": "user", "content": case["user"]}]
            body = {"model": a.model, "messages": msgs, "tools": tools, "tool_choice": "auto",
                    "temperature": a.temperature, "max_tokens": max_tokens, "stream": False}
            if a.thinking != "default":
                body["chat_template_kwargs"] = {"enable_thinking": a.thinking == "on"}
            t0 = time.perf_counter()
            try:
                resp = post_json(url, body, key, a.timeout)
                err = None
            except urllib.error.HTTPError as e:
                resp, err = None, f"HTTP {e.code}: {e.read()[:300]!r}"
            except Exception as e:  # noqa: BLE001
                resp, err = None, f"{type(e).__name__}: {e}"
            sec = time.perf_counter() - t0
            if resp is None:
                g = {"id": case["id"], "expect_tool": case["expect"].get("tool"), "called": [], "pass": False,
                     "fail_type": "요청_오류", "notes": [err], "pass_rescued": False, "fail_type_rescued": "요청_오류"}
                msg, usage, finish = {}, {}, None
            else:
                ch = (resp.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                finish = ch.get("finish_reason")
                usage = resp.get("usage") or {}
                g = grade(case, msg, names)
                gr = grade_rescued(case, msg, names)
                g.update({"pass_rescued": gr["pass"], "fail_type_rescued": gr["fail_type"], "rescued": gr["rescued"]})
                if finish == "length":
                    g["notes"].append("길이 한도에서 잘림")
            g.update({"rep": rep, "user": case["user"], "sec": round(sec, 3), "finish": finish,
                      "content": msg.get("content"), "reasoning_chars": len(msg.get("reasoning_content") or ""),
                      "usage": usage, "timings": (resp or {}).get("timings")})
            results.append(g)
            mark = "통과" if g["pass"] else ("실패:" + str(g["fail_type"]))
            print(f"[{rep}] {case['id']:<4} {mark:<14} {sec:6.2f}s  {json.dumps(g['called'], ensure_ascii=False)[:160]}",
                  flush=True)

    n = len(results)
    passed = sum(r["pass"] for r in results)
    tool_cases = [r for r in results if r["expect_tool"]]
    none_cases = [r for r in results if not r["expect_tool"]]
    right_tool = sum(1 for r in tool_cases if r["called"] and r["called"][0]["name"] == r["expect_tool"])
    fails: dict[str, int] = {}
    for r in results:
        if not r["pass"]:
            fails[r["fail_type"]] = fails.get(r["fail_type"], 0) + 1
    summary = {
        "thinking": a.thinking, "system_variant": a.system_variant or "base", "repeat": a.repeat, "cases": len(cases), "runs": n,
        "pass": passed, "pass_rate": round(passed / n, 4) if n else 0,
        "tool_needed_runs": len(tool_cases),
        "right_tool": right_tool,
        "right_tool_and_args": sum(r["pass"] for r in tool_cases),
        "no_tool_runs": len(none_cases),
        "no_tool_correct": sum(r["pass"] for r in none_cases),
        "fail_types": fails,
        "rescued": summarize(results, "pass_rescued", "fail_type_rescued"),
        "avg_sec": round(sum(r["sec"] for r in results) / n, 3) if n else 0,
        "max_sec": round(max((r["sec"] for r in results), default=0), 3),
    }
    Path(a.out).write_text(json.dumps({"summary": summary, "system": system, "results": results},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
