# 두뇌 지시문 만들기 — 캐시가 깨지지 않게 '안 바뀌는 것'을 앞에, '바뀌는 것'을 뒤에 둔다.
#   system = [기본 지시문(이름·호칭·말투) + 도구 안내] (고정)  →  [기억 블록(아는 사실 + 지난 대화 요약)] (한 대화 동안 고정)
#   그 뒤 messages = 이어 온 지난 차례(고정) → 이번 대화 차례들. 지금 시각은 사용자 말 끝 꼬리표로(지시문에 넣지 않음).
#   지시문은 app/prompts/*.md 글을 읽어 {이름}·{호칭}·{말투} 를 바꿔 넣는다(사용자가 고칠 수 있게 파일로 둠).
import datetime
import os

from . import config as C

PROMPT_DIR = os.path.join(C.APP, "prompts")
_WEEK = "월화수목금토일"


def _read(name):
    with open(os.path.join(PROMPT_DIR, name), encoding="utf-8") as f:
        return f.read().strip()


def now_tag(t=None):
    d = datetime.datetime.fromtimestamp(t) if t else datetime.datetime.now()
    ap = "오전" if d.hour < 12 else "오후"
    h = d.hour % 12 or 12
    return f"(지금 시각: {d.year}년 {d.month}월 {d.day}일 {_WEEK[d.weekday()]}요일 {ap} {h}시 {d.minute}분)"


# 기본 도구 안내 글(지시문 {도구안내} 자리). 켜진 도구만 넣는다 — 꺼진 도구를 안내하면 작은 모델이 'recall(…)'처럼 글로 써 버림.
#   다른 도구 묶음은 tools.json 의 도구마다 "안내"(예: "환율은 exchange_rate")를 두면 그 글을 쓴다.
GUIDE = {
    "remember": "기억해 달라면 remember", "recall": "예전 얘기나 지난 대화를 물으면 recall", "forget": "잊으라면 forget",
    "get_weather": "날씨는 get_weather", "web_search": "지금 가격·뉴스·최신 소식은 web_search",
    "read_page": "주소를 읽으라면 read_page", "pc_action": "프로그램·사이트를 열라면 pc_action",
    "speech_speed": "말 빠르기는 speech_speed", "standby": "쉬라거나 그만하라면 standby", "calc": "숫자 계산은 calc",
}


def tool_guide(specs):
    """[도구 정의] → 지시문 한 줄. 도구가 없으면 도구 이름을 쓰지 말라는 말."""
    out = []
    for s in specs or []:
        f = s.get("function", s) if isinstance(s, dict) else {"name": str(s)}
        name = f.get("name")
        g = (s.get("안내") if isinstance(s, dict) else None) or GUIDE.get(name) or (f"{name} 도구" if name else "")
        if g:
            out.append(g)
    if not out:
        return "지금은 쓸 수 있는 도구가 없다. 도구 이름이나 함수 모양의 글을 쓰지 말고 아는 만큼 말로 답한다."
    return ", ".join(out) + ". 여기에 없는 도구 이름이나 함수 모양의 글은 쓰지 않는다."


def _iras(word):
    """'사장님'+'이라고' / '대표'+'라고' — 끝 글자 받침에 맞춤."""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return word + ("이라고" if (ord(ch) - 0xAC00) % 28 else "라고")
    return word + "(이)라고"


CLI_KINDS = ("claude_cli", "codex_cli")


def base_prompt(cfg, tool_specs=()):
    """고정 앞부분 — 같은 설정·같은 도구면 글자 하나 다르지 않게 만든다(캐시).
    구독 두뇌(클로드 코드·Codex)는 대화 전용 지시문(base.cli.md — 도구 없음)."""
    b = cfg.get("비서") or {}
    honor = C.honorific(cfg)
    style = str(b.get("말투") or "존댓말").strip()
    cli = str((cfg.get("두뇌") or {}).get("방식") or "") in CLI_KINDS
    text = C.fill(cfg, _read("base.cli.md" if cli else "base.small.md")).replace("{말투}", style)
    text = text.replace("{도구안내}", tool_guide(tool_specs))
    parts = [text]
    if honor:
        parts.append(f"사용자를 부를 때는 {_iras(honor)} 부른다.")
    persona = str(b.get("성격") or "").strip()
    if persona:
        parts.append("성격: " + persona[:300])
    return "\n".join(parts)


def memory_block(cfg, memory, summary=""):
    """한 대화 동안 고정되는 기억 부분(대화 시작 때 한 번 만듦). 비면 ''."""
    honor = C.honorific(cfg) or "사용자"
    out = []
    if memory is not None and (cfg.get("기억") or {}).get("켜기", True):
        fb = memory.prompt_block(honor)
        if fb:
            out.append(fb)
    if summary:
        out.append("[지난 대화 요약 — 앞서 나눈 대화. 이어서 물으면 이것을 참고]\n" + summary.strip()[:2500])
    return "\n\n".join(out)


def system_prompt(cfg, tool_specs=(), memory=None, summary=""):
    mb = memory_block(cfg, memory, summary)
    return base_prompt(cfg, tool_specs) + ("\n\n" + mb if mb else "")
