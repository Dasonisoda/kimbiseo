# 비밀값(두뇌 열쇠 등) — 설정 파일·저장소·로그에 값을 남기지 않는다.
#   찾는 순서: 환경변수 KIMBISEO_KEY_<이름> > %APPDATA%\KimBiseo\secrets\<이름>.bin
#   파일은 윈도우 계정 암호화(DPAPI)로 저장 — 같은 윈도우 계정만 풀 수 있음. 윈도우가 아니면 파일 권한만으로 저장.
#   값은 화면·기록에 내보내지 않는다(mask_key 로 앞 몇 글자만).
import ctypes
import os
import re
import sys

from . import config

_NAME = re.compile(r"^[a-z0-9_]{1,40}$")


def _dir(cfg=None):
    base = config.path(cfg, "자료") if cfg else config.expand("%APPDATA%/KimBiseo")
    return os.path.join(base, "secrets")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dst = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst))  # 0x1 = 화면에 묻지 않음
    if not ok:
        raise OSError("DPAPI 실패")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree(dst.pbData)


def get(name, cfg=None):
    """비밀값 하나(없으면 빈 글)."""
    if not name or not _NAME.match(name):
        return ""
    env = os.environ.get("KIMBISEO_KEY_" + name.upper())
    if env:
        return env.strip()
    p = os.path.join(_dir(cfg), name + ".bin")
    try:
        raw = open(p, "rb").read()
    except OSError:
        return ""
    try:
        if sys.platform == "win32":
            raw = _dpapi(raw, False)
        return raw.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def put(name, value, cfg=None):
    if not name or not _NAME.match(name):
        raise ValueError("비밀값 이름은 영어 소문자·숫자·_ 만")
    d = _dir(cfg)
    os.makedirs(d, exist_ok=True)
    data = str(value or "").strip().encode("utf-8")
    if sys.platform == "win32":
        data = _dpapi(data, True)
    p = os.path.join(d, name + ".bin")
    with open(p, "wb") as f:
        f.write(data)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return True


def mask_key(v):
    v = str(v or "")
    return "(없음)" if not v else (v[:3] + "…" + f"({len(v)}자)")
