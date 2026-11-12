# 업데이트 — 우리 깃허브 릴리스의 최신 판 목록(latest.json)을 보고, 새 판이면 쉬운 말로 알리고, 누르면 받아서 바꾼다.
#   확인: 켤 때(하루 한 번까지) + 설정 '정보'의 '업데이트 확인' 단추.  받기: 서명(ed25519) 확인 → 꾸러미 sha256·크기 확인 → 풀어서 파일마다 sha256 확인.
#   바꾸기: installer/updater.py 를 설치 폴더 install\update 로 복사해 따로 띄움(김비서를 끄고 src 만 바꿔 끼우고, 검사해서 안 되면 되돌림).
#   그대로 두는 것: 자료 폴더(설정·기억·열쇠·목소리·펫 옷), 모델, 파이썬·두뇌·펫 실행 틀.
#   파이썬 부품·모델 목록(installer/locks·runtimes.json·models.json)이 바뀌는 판은 코드만 바꿔서는 안 되므로 '새 설치 파일로' 안내만 함.
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config as C
from .. import version as V

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.join(SRC, "installer") not in sys.path:
    sys.path.insert(0, os.path.join(SRC, "installer"))
import updater as U  # noqa: E402  (표준 라이브러리만 쓰는 공통 부분)

# 업데이트 서명 공개키(비밀키는 저장소 밖에만 있음). 열쇠를 바꿀 때는 새 줄을 더하고, 옛 열쇠는 한 판 동안 같이 둔다.
PUBKEYS = {
    "kimbiseo-update-1": "/NWEgQzO/BNNYDB40y8ppPkVyi6tR348/nDDsrLSTX0=",
}
FORMAT = "kimbiseo-update/1"
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")   # 깃허브 릴리스만(사내 서버 없음)
LOOP = ("127.0.0.1", "localhost")
UA = "KimBiseo-updater/1"
MANIFEST_MAX = 256 * 1024
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class UpdateError(U.UpdateError):
    pass


# ---------------------------------------------------------------- 받기(허용한 곳만)
def check_url(url):
    try:
        u = urllib.parse.urlsplit(str(url))
    except ValueError as ex:
        raise UpdateError("업데이트 주소가 이상해요.") from ex
    host = (u.hostname or "").lower()
    if host in LOOP and u.scheme in ("http", "https"):
        return u.geturl()
    if u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        return u.geturl()
    raise UpdateError("허용하지 않은 업데이트 주소예요: " + host[:60])


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, timeout=30):
    opener = urllib.request.build_opener(_Redirect())
    req = urllib.request.Request(check_url(url), headers={"User-Agent": UA, "Accept": "*/*"})
    return opener.open(req, timeout=timeout)


def fetch_bytes(url, limit):
    with _open(url) as r:
        b = r.read(limit + 1)
    if len(b) > limit:
        raise UpdateError("업데이트 목록이 너무 커요.")
    return b


def download(url, dest, size, sha256, progress=None):
    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    import hashlib
    h = hashlib.sha256()
    got = 0
    with _open(url, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 18)
            if not b:
                break
            got += len(b)
            if got > size:
                raise UpdateError("받은 꾸러미가 목록보다 커요.")
            h.update(b)
            f.write(b)
            if progress:
                progress(got, size)
    if got != size or h.hexdigest() != sha256:
        os.remove(tmp)
        raise UpdateError("받은 업데이트 꾸러미가 원본과 달라요(받다가 깨졌을 수 있어요). 다시 해 주세요.")
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------- 목록(latest.json) 확인
def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest(doc, pubkeys=None):
    """서명 확인 + 칸 확인 → signed(dict). 아니면 UpdateError."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    keys = PUBKEYS if pubkeys is None else pubkeys
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("signed"), dict):
        raise UpdateError("업데이트 목록 모양이 달라요.")
    kid = str(doc.get("key_id") or "")
    if kid not in keys or not keys[kid] or keys[kid].startswith("__"):
        raise UpdateError("모르는 서명 열쇠예요.")
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(keys[kid], validate=True))
        pub.verify(base64.b64decode(str(doc.get("sig") or ""), validate=True), canonical(doc["signed"]))
    except (InvalidSignature, ValueError) as ex:
        raise UpdateError("업데이트 목록의 서명이 맞지 않아요(가짜이거나 깨졌어요).") from ex
    s = doc["signed"]
    if s.get("app") != "kimbiseo" or s.get("key_id") != kid:
        raise UpdateError("김비서 업데이트 목록이 아니에요.")
    U.parse_version(s.get("version"))
    U.parse_version(s.get("min_from") or "0.0.0")
    pkg = s.get("package")
    if not isinstance(pkg, dict) or not isinstance(pkg.get("size"), int) or not (0 < pkg["size"] <= U.MAX_TOTAL):
        raise UpdateError("업데이트 꾸러미 정보가 이상해요.")
    if not (isinstance(pkg.get("sha256"), str) and len(pkg["sha256"]) == 64 and all(c in "0123456789abcdef" for c in pkg["sha256"])):
        raise UpdateError("업데이트 꾸러미 sha256 이 이상해요.")
    if not isinstance(s.get("deps"), dict):
        raise UpdateError("업데이트 목록에 부품 정보가 없어요.")
    return s


def notes_of(s):
    n = s.get("notes")
    return [str(x)[:200] for x in n][:20] if isinstance(n, list) else []


# ---------------------------------------------------------------- 상태
class Updater:
    def __init__(self, cfg, settings_path):
        self.cfg = cfg
        self.settings_path = settings_path
        self.prefix = os.path.dirname(SRC)
        self.installed = os.path.basename(SRC).lower() == "src" and os.path.isfile(os.path.join(self.prefix, "install", "state.json"))
        self.work = os.path.join(self.prefix, "install", "update")
        self.dir = os.path.join(C.path(cfg, "자료"), "update")
        self.state_p = os.path.join(self.dir, "state.json")
        self.lock = threading.Lock()
        self.st = U.read_json(self.state_p, {}) or {}
        self.busy = ""          # "확인 중" | "받는 중" | "바꾸는 중"
        self.progress = 0
        self.error = ""
        self.latest = None      # 확인한 signed 목록
        self.ready = None

    def conf(self):
        u = self.cfg.get("업데이트") or {}
        urls = u.get("주소") or []
        return {"켜기": u.get("켜기", True) is not False, "자동": u.get("자동_확인", True) is not False,
                "간격": float(u.get("간격_시간") or 24), "주소": [str(x) for x in urls if x][:4]}

    def save(self):
        try:
            U.write_json(self.state_p, self.st)
        except OSError:
            pass

    def view(self):
        s = self.latest
        new = None
        if s and U.newer(s["version"], V.VERSION):
            new = {"판": s["version"], "날짜": str(s.get("date") or "")[:20], "바뀐점": notes_of(s), "크기": s["package"]["size"],
                   "새설치필요": self.needs_setup(s), "안내주소": self._page(s)}
        res = U.read_json(os.path.join(self.dir, "result.json"))
        return {"ok": True, "지금_판": V.VERSION, "설치판": self.installed, "켜기": self.conf()["켜기"], "마지막_확인": self.st.get("last_check", ""),
                "하는중": self.busy, "진행": self.progress, "오류": self.error, "새판": new,
                "준비됨": bool(self.ready and new and self.ready.get("version") == new["판"]),
                "지난결과": res if (isinstance(res, dict) and not res.get("seen")) else None}

    def _page(self, s):
        p = str(s.get("release_page") or "")
        try:
            return check_url(p) if p else ""
        except UpdateError:
            return ""

    def needs_setup(self, s):
        """새 판에서 파이썬 부품·모델 목록이 바뀌는지, 또는 지금 판이 너무 옛것인지 → 새 설치 파일로."""
        if U.newer(s.get("min_from") or "0.0.0", V.VERSION):
            return True
        mine = U.deps_of(SRC)
        return any(mine.get(k, "") != v for k, v in (s.get("deps") or {}).items() if k in U.DEPS)

    def due(self):
        c = self.conf()
        if not (c["켜기"] and c["자동"] and c["주소"]):
            return False
        last = float(self.st.get("last_check_ts") or 0)
        return time.time() - last >= c["간격"] * 3600

    # ---- 확인
    def check(self):
        c = self.conf()
        if not c["켜기"]:
            raise UpdateError("업데이트가 꺼져 있어요(설정 업데이트.켜기).")
        if not c["주소"]:
            raise UpdateError("업데이트 주소가 없어요.")
        with self.lock:
            if self.busy:
                raise UpdateError("지금 " + self.busy + "이에요.")
            self.busy, self.error = "확인 중", ""
        ok = False
        try:
            last_ex = None
            for url in c["주소"]:
                try:
                    doc = json.loads(fetch_bytes(url, MANIFEST_MAX).decode("utf-8"))
                    s = verify_manifest(doc)
                    self.latest = s
                    self.st.update({"last_check": time.strftime("%Y-%m-%d %H:%M"), "last_check_ts": time.time(), "latest": s["version"],
                                    "manifest_url": url, "source": url.split("/")[2] if "//" in url else ""})
                    self.save()
                    self._load_ready()
                    ok = True
                    break
                except UpdateError as ex:
                    last_ex = ex
                except (urllib.error.URLError, OSError, ValueError) as ex:
                    last_ex = UpdateError("업데이트 정보를 받지 못했어요. 인터넷 연결을 확인해 주세요." +
                                          (f" ({getattr(ex, 'code', '')})" if getattr(ex, "code", None) else ""))
            if not ok:
                self.st.update({"last_check_ts": time.time(), "last_check": time.strftime("%Y-%m-%d %H:%M")})
                self.save()
                raise last_ex or UpdateError("업데이트 정보를 받지 못했어요.")
        finally:
            self.busy = ""
        return self.view()

    def _load_ready(self):
        r = U.read_json(os.path.join(self.work, "ready.json"))
        self.ready = r if (isinstance(r, dict) and os.path.isdir(os.path.join(self.work, "staged"))) else None

    # ---- 받기
    def download(self):
        s = self.latest
        if not self.installed:
            raise UpdateError("설치한 김비서에서만 업데이트할 수 있어요(지금은 소스에서 돌리는 중).")
        if not s or not U.newer(s["version"], V.VERSION):
            raise UpdateError("받을 새 판이 없어요. '업데이트 확인'을 먼저 눌러 주세요.")
        if self.needs_setup(s):
            raise UpdateError("이번 판은 부품이 바뀌어서 새 설치 파일로 설치해야 해요. 설치하면 대화 기억·설정은 그대로 남아요.")
        with self.lock:
            if self.busy:
                raise UpdateError("지금 " + self.busy + "이에요.")
            self.busy, self.error, self.progress = "받는 중", "", 0
        try:
            pkg = s["package"]
            url = pkg.get("url") or ""
            if not url.startswith(("http://", "https://")):     # 목록 주소 기준 상대 주소
                url = urllib.parse.urljoin(self.st.get("manifest_url") or self.conf()["주소"][0], url or pkg.get("file", ""))
            os.makedirs(self.work, exist_ok=True)
            for f in ("ready.json", "staged_index.json"):
                try:
                    os.remove(os.path.join(self.work, f))
                except OSError:
                    pass
            zp = os.path.join(self.work, f"update-{s['version']}.zip")
            download(url, zp, pkg["size"], pkg["sha256"], progress=lambda g, t: setattr(self, "progress", round(90 * g / max(1, t), 1)))
            idx = U.extract_package(zp, os.path.join(self.work, "staged"))
            if idx.get("version") != s["version"]:
                raise UpdateError("꾸러미 판 번호가 목록과 달라요.")
            if U.deps_of(os.path.join(self.work, "staged")) != {k: v for k, v in s["deps"].items() if k in U.DEPS}:
                raise UpdateError("꾸러미의 부품 정보가 목록과 달라요.")
            U.write_json(os.path.join(self.work, "staged_index.json"), idx)
            self.ready = {"version": s["version"], "at": time.strftime("%Y-%m-%d %H:%M:%S"), "sha256": pkg["sha256"]}
            U.write_json(os.path.join(self.work, "ready.json"), self.ready)
            try:
                os.remove(zp)
            except OSError:
                pass
            self.progress = 100
            return self.view()
        except UpdateError as ex:
            self.error = str(ex)
            raise
        except (urllib.error.URLError, OSError) as ex:
            self.error = "업데이트를 받지 못했어요. 인터넷 연결을 확인하고 다시 해 주세요."
            raise UpdateError(self.error) from ex
        finally:
            self.busy = ""

    # ---- 바꾸기(따로 띄운 일꾼이 김비서를 끄고 바꾼 뒤 다시 켬)
    def apply(self):
        self._load_ready()
        s = self.latest
        if not (self.ready and s and self.ready.get("version") == s["version"]):
            raise UpdateError("받아 둔 새 판이 없어요. '업데이트 하기'를 먼저 눌러 주세요.")
        with self.lock:
            if self.busy:
                raise UpdateError("지금 " + self.busy + "이에요.")
            self.busy = "바꾸는 중"
        try:
            run_copy = os.path.join(self.work, "updater_run.py")
            shutil.copyfile(os.path.join(SRC, "installer", "updater.py"), run_copy)
            py = sys.executable.replace("pythonw.exe", "python.exe")
            try:
                os.remove(os.path.join(self.dir, "result.json"))
            except OSError:
                pass
            r = subprocess.run([py, "-B", "-X", "utf8", run_copy, "spawn", "--prefix", self.prefix, "--settings", self.settings_path,
                                "--version", s["version"], "--body-pid", str(os.getpid())], cwd=self.work, capture_output=True,
                               creationflags=NO_WINDOW, timeout=30)
            if r.returncode != 0:
                raise UpdateError("업데이트 일꾼을 띄우지 못했어요.")
            return {"ok": True, "판": s["version"], "안내": "김비서를 잠깐 끄고 새 판으로 바꾼 뒤 다시 켜요. 1~3분 기다려 주세요."}
        except Exception:
            self.busy = ""
            raise

    def mark_seen(self):
        p = os.path.join(self.dir, "result.json")
        r = U.read_json(p)
        if isinstance(r, dict):
            r["seen"] = True
            U.write_json(p, r)
        return True
