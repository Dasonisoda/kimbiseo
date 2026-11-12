# 민감정보 가림 — 기억·일기에 저장하기 전에 비밀번호·카드번호·토큰 같은 값을 가린다.
import re

_RULES = [
    # 열쇠=값 꼴(비밀번호·토큰·키)
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth|bearer|session[_-]?key|private[_-]?key)"
                r"(\s*[:=]\s*|\s+)([\"']?)[^\s\"',;]{4,}"), r"\1\2\3[가림]"),
    (re.compile(r"(비밀\s*번호|비번|암호|패스워드|토큰|인증\s*키|api\s*키|키값)(\s*(?:은|는|이|가|:|=)?\s*)([^\s,.;]{4,})"), r"\1\2[가림]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}"), "Bearer [가림]"),
    (re.compile(r"\b(sk|pk|rk|xox[abp]|ghp|gho|glpat|hf)[-_][A-Za-z0-9_\-]{12,}"), "[가림:키]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[가림:키]"),
    (re.compile(r"\b[MN][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}\b"), "[가림:디스코드토큰]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[가림:토큰]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[가림:개인키]"),
    # 카드번호(13~19자리, 띄어쓰기·하이픈 허용)
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), lambda m: "[가림:번호]" if _luhn(m.group(0)) or len(re.sub(r"\D", "", m.group(0))) == 16 else m.group(0)),
    # 주민등록번호
    (re.compile(r"\b\d{6}\s?-\s?[1-4]\d{6}\b"), "[가림:주민번호]"),
    # 계좌번호처럼 보이는 긴 하이픈 숫자
    (re.compile(r"\b(?!0\d{1,2}-\d{3,4}-\d{4}\b)\d{3,6}-\d{2,6}-\d{4,8}(?:-\d{1,4})?\b"), "[가림:번호]"),  # 전화번호(0으로 시작) 제외
    # 긴 무작위 문자열(32자 이상 영숫자)
    (re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b"), "[가림:긴값]"),
]


def _luhn(s):
    d = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    tot = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        tot += x
    return tot % 10 == 0


def mask(text):
    """비밀번호·토큰·카드번호·주민번호·긴 열쇠값을 [가림] 으로 바꾼 글."""
    if not text:
        return text
    t = str(text)
    for rx, rep in _RULES:
        t = rx.sub(rep, t)
    return t


def has_secret(text):
    return mask(text) != str(text or "")


# 주소 쿼리 속 열쇠 값(token=·key= 등)만 가리는 것(페이지 글은 그대로).
_URL_SECRET = re.compile(r"(?i)([?&#;]\s*(?:token|access_token|id_token|refresh_token|mcpRelayUrl|relayUrl|auth|key|api_key|apikey|secret|sig|signature)=)"
                         r"[^&\s\"'<>)\]#|`]+")
_ENV_TOKEN = re.compile(r"(?i)\b([A-Z][A-Z0-9_]*_TOKEN\s*[=:]\s*)[\"']?[^\s\"',;]+")


def mask_url_secrets(text):
    """주소 쿼리의 열쇠 값과 토큰 줄만 [가림] 으로. 글이 아니면 그대로."""
    if not isinstance(text, str) or not text:
        return text
    return _ENV_TOKEN.sub(r"\1[가림]", _URL_SECRET.sub(r"\1[가림]", text))


def mask_deep(obj, fn=mask_url_secrets, _depth=0):
    """dict·list 안의 글 전부에 fn 을 적용한 새 값(원본은 안 바꿈)."""
    if _depth > 12:
        return obj
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: mask_deep(v, fn, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_deep(v, fn, _depth + 1) for v in obj]
    return obj
