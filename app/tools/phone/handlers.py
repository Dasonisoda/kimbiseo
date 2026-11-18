# 폰 도구(폰 앱으로 대화할 때만 붙음) — 본체는 무엇을 할지 정리해 폰에 보내고, 폰이 그 앱 화면을 연다.
#   navigate : 길안내 앱(카카오맵·네이버지도·티맵·구글지도 = 목적지 검색·길안내 화면, 카카오내비 = 앱 열기 + 목적지 글 복사)
#   dial     : 전화 앱에 번호를 채워 열기(ACTION_DIAL) — 걸기 버튼은 사용자가 누름. 연락처 이름이면 폰이 연락처에서 찾음.
#   sms      : 문자 앱에 받는 사람·내용을 채워 열기(ACTION_SENDTO) — 보내기 버튼은 사용자가 누름.
#   open_app : 폰에 깔린 앱 이름으로 열기(앱 서랍에 보이는 앱만).
#   본체는 폰의 연락처·앱 목록을 받아 저장하지 않는다(폰이 그 자리에서 찾고 결과 한 줄만 돌려줌).
import re

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
NAV_APPS = {"카카오맵": "kakaomap", "카카오지도": "kakaomap", "kakaomap": "kakaomap", "네이버지도": "naver", "네이버맵": "naver",
            "네이버": "naver", "naver": "naver", "티맵": "tmap", "tmap": "tmap", "구글지도": "google", "구글맵": "google",
            "google": "google", "카카오내비": "kakaonavi", "kakaonavi": "kakaonavi"}


def _clean(s, n):
    return _CTRL.sub(" ", str(s or "")).strip()[:n]


def _digits(s):
    d = re.sub(r"[^\d+]", "", str(s or ""))
    if d.startswith("+82"):
        d = "0" + d[3:].lstrip("0")
    return re.sub(r"\D", "", d)


def _nav_app(name):
    k = re.sub(r"[\s·._-]+", "", str(name or "")).lower()
    return NAV_APPS.get(k, "")


def build(a):
    """두뇌 인자 → (폰에 보낼 일, None) 또는 (None, 안내 글)."""
    act = str(a.get("action") or "").strip()
    if act == "navigate":
        dest = _clean(a.get("destination"), 80)
        if not dest:
            return None, "어디로 안내할지 목적지를 여쭤보세요."
        return {"do": "navigate", "destination": dest, "app": _nav_app(a.get("app"))}, None
    if act in ("dial", "sms"):
        num = _digits(a.get("number"))
        who = _clean(a.get("contact"), 30)
        if num and not (3 <= len(num) <= 15):
            return None, "전화번호 모양이 아니에요. 번호를 다시 여쭤보세요."
        if not num and not who:
            return None, "누구에게 할지 이름이나 번호를 여쭤보세요."
        job = {"do": act, "number": num, "contact": "" if num else who}
        if act == "sms":
            job["message"] = _clean(a.get("message"), 500)
        return job, None
    if act == "open_app":
        app = _clean(a.get("app"), 40)
        if not app:
            return None, "어떤 앱을 열지 여쭤보세요."
        return {"do": "open_app", "app": app}, None
    return None, "폰에서는 길안내·전화 화면·문자 화면·앱 열기만 할 수 있어요."


async def phone_action(ctx, a):
    link = ctx.actions.get("phone")
    if link is None:
        return {"오류": "폰 앱으로 대화할 때만 폰에서 열 수 있어요.", "안내": "폰 앱으로 대화할 때만 된다고 짧게 말하세요."}
    job, why = build(a)
    if job is None:
        return {"안내": why}
    r = await link.request({"type": "phone_do", **job}, timeout=20.0)
    if r is None:
        return {"오류": "폰이 답하지 않았어요.", "안내": "폰에서 열지 못했다고 짧게 말하세요."}
    said = _clean(r.get("말"), 200)
    if r.get("ok"):
        return {"됨": True, "폰": said, "안내": (said or "폰에서 열었어요.") + " — 이 내용을 한 문장으로 말하세요. 걸기·보내기는 사용자가 폰에서 누른다."}
    if r.get("near"):
        return {"됨": False, "비슷한_이름": [_clean(x, 30) for x in (r.get("near") or [])][:3],
                "안내": "연락처에서 딱 맞는 이름을 못 찾았어요. 비슷한 이름을 읽어 드리고 누구인지 여쭤보세요."}
    return {"됨": False, "폰": said, "안내": (said or "폰에서 열지 못했어요.") + " — 이 내용을 짧게 말하세요."}


HANDLERS = {"phone_action": phone_action}
