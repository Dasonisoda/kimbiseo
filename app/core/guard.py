# 요청 검사 — 다른 웹페이지가 대신 보내는 요청(CSRF)·DNS 리바인딩 막기(표준 라이브러리만).
#   ① Host 헤더: 허용된 이름(127.0.0.1·localhost·::1) + 듣는 포트만. 아니면 403.
#   ② 상태를 바꾸는 요청(POST·PUT·PATCH·DELETE): Origin 이 있으면 같은 원점만, Sec-Fetch-Site 는 same-origin·none 만,
#      Content-Type 은 JSON(정해 둔 이진 형식 주소만 예외). 브라우저가 사전 확인 없이 보낼 수 있는 형식은 거절.
#   ③ 끄기 비밀값: /api/shutdown 은 이 PC 안 프로그램만 아는 값이 머리글에 있어야 함(값은 화면·기록에 안 나감).
import hmac
import os
import secrets
import socket
import threading
import time

STATE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOP_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
SHUTDOWN_HEADER = "X-KimBiseo-Shutdown"
SHUTDOWN_FILE = "shutdown_secret.txt"


def split_host(host_header):
    """'127.0.0.1:8770' → ('127.0.0.1', 8770), '[::1]:8770' → ('::1', 8770). 이상하면 ('', None)."""
    h = str(host_header or "").strip().lower()
    if not h or any(c in h for c in " /\\@?#"):
        return "", None
    if h.startswith("["):
        end = h.find("]")
        if end < 0:
            return "", None
        name, rest = h[1:end], h[end + 1:]
        if rest and not rest.startswith(":"):
            return "", None
        port = rest[1:]
    else:
        if h.count(":") > 1:
            return "", None
        name, _, port = h.partition(":")
    if port and not port.isdigit():
        return "", None
    return name.rstrip("."), (int(port) if port else None)


def ctype_main(ctype):
    return str(ctype or "").split(";")[0].strip().lower()


def _is_json(ct):
    return ct == "application/json" or (ct.startswith("application/") and ct.endswith("+json"))


def check(method, path, headers, allowed_names, port, binary_types=None):
    """요청 하나 검사 → None(통과) 또는 (상태코드, 이유). headers = 소문자 이름으로 get 되는 것(dict·Starlette Headers·http.server 메시지).
    allowed_names = 허용 Host 이름(소문자), port = 이 서버가 듣는 포트, binary_types = {경로: (허용 이진 형식…)}(끝이 '/' 면 그 종류 전부)."""
    host = headers.get("host")
    name, hport = split_host(host)
    if not name or name not in allowed_names or hport != int(port):
        return 403, f"허용 안 된 Host({str(host or '')[:80]!r})"
    m = str(method or "").upper()
    if m not in STATE_METHODS:
        return None
    origin = headers.get("origin")
    if origin is not None and str(origin).strip().lower() != "http://" + str(host).strip().lower():
        return 403, f"다른 원점에서 온 요청(Origin {str(origin)[:80]!r})"
    sfs = str(headers.get("sec-fetch-site") or "").strip().lower()
    if sfs and sfs not in ("same-origin", "none"):
        return 403, f"다른 사이트에서 온 요청(Sec-Fetch-Site {sfs})"
    ct = ctype_main(headers.get("content-type"))
    if _is_json(ct):
        return None
    for want in (binary_types or {}).get(path, ()):
        if ct == want or (want.endswith("/") and ct.startswith(want) and len(ct) > len(want)):
            return None
    return 415, f"받지 않는 형식(Content-Type {ct or '없음'!r})"


class LocalNames:
    """이 PC 의 이름·주소 + 설정의 허용 호스트 — Host 검사용. 모르는 Host 면 다시 읽음(10초에 한 번까지)."""

    def __init__(self, extra=()):
        self.extra = {str(x).strip().lower().rstrip(".") for x in extra if str(x).strip()}
        self.names, self.t = set(), 0.0
        self.lock = threading.Lock()
        self.refresh(force=True)

    def refresh(self, force=False):
        with self.lock:
            if not force and time.time() - self.t < 10:
                return
            self.t = time.time()
            s = set(LOOP_NAMES) | self.extra
            try:
                hn = socket.gethostname()
                s |= {hn.lower(), socket.getfqdn().lower()}
                for a in socket.getaddrinfo(hn, None):
                    s.add(str(a[4][0]).split("%")[0].lower())
            except OSError:
                pass
            self.names = s

    def allowed(self, host_header):
        name, _ = split_host(host_header)
        if name and name not in self.names:
            self.refresh()
        return self.names


def shutdown_secret(secret_dir):
    """끄기 비밀값(자료 폴더 secrets 안 shutdown_secret.txt) — 없으면 만든다. 값은 화면·기록에 내보내지 않는다."""
    d = secret_dir
    path = os.path.join(d, SHUTDOWN_FILE)
    try:
        v = open(path, encoding="utf-8").read().strip()
        if len(v) >= 24:
            return v
    except OSError:
        pass
    os.makedirs(d, exist_ok=True)
    v = secrets.token_urlsafe(32)
    try:
        with open(path, "x", encoding="utf-8") as f:  # 동시에 두 곳이 만들면 먼저 만든 것을 씀
            f.write(v)
    except FileExistsError:
        return open(path, encoding="utf-8").read().strip()
    return v


def same_secret(got, want):
    return bool(want) and hmac.compare_digest(str(got or "").encode("utf-8", "replace"), str(want).encode("utf-8"))
