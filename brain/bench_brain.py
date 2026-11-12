"""두뇌 속도·한국어 답 재기 — OpenAI 호환 /v1/chat/completions 를 스트리밍으로 불러
첫 글자까지 시간(TTFT)과 생성 속도를 잽니다. 표준 라이브러리만 씁니다.

    python bench_brain.py --base-url http://127.0.0.1:8880/v1 --out 속도.json
    python bench_brain.py --long 6000 --out 긴문맥.json     # 앞에 약 6천 토큰 글을 붙여 긴 문맥 첫 글자 시간

llama-server 면 마지막 조각의 timings(prompt_n·prompt_ms·predicted_per_second)도 같이 적습니다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

SYSTEM = ("너는 '김비서'라는 한국어 음성 비서다. 답은 소리로 읽히니 기호·목록·이모지 없이 "
          "두세 문장으로 짧게 한국어로만 말한다. 모르면 모른다고 한다.")

PROMPTS = [
    "안녕, 오늘 기분 어때?",
    "아침에 일찍 일어나는 요령 세 가지만 알려 줘.",
    "비 오는 날 집에서 할 만한 일 추천해 줘.",
    "컴퓨터가 갑자기 느려졌을 때 먼저 뭘 확인하면 좋아?",
    "친구 생일 축하 문자 짧게 하나 써 줘.",
    "김치찌개 맛있게 끓이는 법 간단히 말해 줘.",
    "블랙홀이 뭔지 초등학생한테 설명하듯이 말해 줘.",
    "요즘 너무 피곤한데 어떻게 하면 좋을까?",
]

FILLER = ("옛날 어느 마을에 부지런한 농부가 살았습니다. 농부는 해가 뜨기 전에 일어나 밭을 갈고 "
          "저녁이 되면 마을 사람들과 이야기를 나누었습니다. ")


def stream_chat(url: str, body: dict, key: str | None, timeout: float) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    t0 = time.perf_counter()
    first = first_content = None
    text, reasoning, timings, usage, chunks = [], [], None, None, 0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("timings"):
                timings = ev["timings"]
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                c, rc = d.get("content"), d.get("reasoning_content")
                if (c or rc) and first is None:
                    first = time.perf_counter() - t0
                if c:
                    if first_content is None:
                        first_content = time.perf_counter() - t0
                    text.append(c)
                    chunks += 1
                if rc:
                    reasoning.append(rc)
    total = time.perf_counter() - t0
    return {"ttft_sec": first, "first_content_sec": first_content, "total_sec": total, "content": "".join(text),
            "reasoning_chars": len("".join(reasoning)), "content_chunks": chunks, "timings": timings, "usage": usage}


def main() -> int:
    ap = argparse.ArgumentParser(description="두뇌 속도·한국어 답 재기")
    ap.add_argument("--base-url", default="http://127.0.0.1:8880/v1")
    ap.add_argument("--model", default="local")
    ap.add_argument("--api-key-env", default="")
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--thinking", choices=["on", "off", "default"], default="off")
    ap.add_argument("--long", type=int, default=0, help="앞에 붙일 글의 대략 토큰 수(0 = 안 붙임)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    key = os.environ.get(a.api_key_env) if a.api_key_env else None
    url = a.base_url.rstrip("/") + "/chat/completions"

    prefix = ""
    if a.long:
        prefix = FILLER * max(1, a.long // 45) + "\n\n위 이야기는 참고만 하고, 아래 질문에 답해 줘.\n"
    runs = []
    for rep in range(a.repeat):
        for i, p in enumerate(PROMPTS if not a.long else PROMPTS[:3]):
            # 긴 문맥 시험은 질문마다 앞글을 조금 바꿔 앞부분 캐시 효과를 뺍니다.
            pre = (f"[{rep}-{i}] " + prefix) if a.long else ""
            body = {"model": a.model, "stream": True, "max_tokens": a.max_tokens, "temperature": 0.7,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": pre + p}]}
            if a.thinking != "default":
                body["chat_template_kwargs"] = {"enable_thinking": a.thinking == "on"}
            r = stream_chat(url, body, key, a.timeout)
            r.update({"rep": rep, "prompt": p, "long": a.long})
            tm = r.get("timings") or {}
            print(f"[{rep}] {i} ttft={r['ttft_sec']:.3f}s total={r['total_sec']:.2f}s "
                  f"prompt_n={tm.get('prompt_n')} pp/s={tm.get('prompt_per_second')} tg/s={tm.get('predicted_per_second')} "
                  f"| {r['content'][:80]!r}", flush=True)
            runs.append(r)

    def avg(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 3) if xs else None

    summary = {
        "runs": len(runs), "long": a.long, "thinking": a.thinking,
        "ttft_avg_sec": avg([r["ttft_sec"] for r in runs]),
        "ttft_max_sec": round(max((r["ttft_sec"] or 0) for r in runs), 3) if runs else None,
        "prompt_tokens_avg": avg([(r.get("timings") or {}).get("prompt_n") for r in runs]),
        "prompt_per_sec_avg": avg([(r.get("timings") or {}).get("prompt_per_second") for r in runs]),
        "gen_tokens_avg": avg([(r.get("timings") or {}).get("predicted_n") for r in runs]),
        "gen_per_sec_avg": avg([(r.get("timings") or {}).get("predicted_per_second") for r in runs]),
    }
    Path(a.out).write_text(json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
