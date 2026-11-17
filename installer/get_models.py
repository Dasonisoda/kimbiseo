# 김비서 모델 받기·확인 — installer/models.json 의 주소·크기·해시대로 받는다(파이썬 표준 라이브러리만).
#
#   python get_models.py list                         받을 모델·크기 보기
#   python get_models.py get [이름...] [--all]         받기(이름 없으면 필수 모델만, --all 이면 선택 모델까지)
#   python get_models.py check <이름> [--dir 폴더]     이미 있는 폴더를 해시로 확인만(아무것도 쓰지 않음)
#   공통: --dest <모델 폴더>(기본 = 설정 '경로.모델', %LOCALAPPDATA%\KimBiseo\models) · --settings <설정.json> · --json
#
# - 이어 받기: 받는 중인 파일은 <파일>.part 로 두고, 끊기면 다음에 이어서 받음(서버가 Range 를 받으면).
# - 보안 연결: 윈도우 인증서 저장소 + 모질라 뿌리 인증서 묶음(certifi — 설치 때는 pip 에 든 것)을 둘 다 믿음(ssl_context()).
#   까닭: 파이썬은 윈도우 저장소에 '이미 들어 있는' 뿌리만 읽는데, 윈도우는 뿌리를 처음 쓸 때에야 받아 넣는다 → 새 PC·깨끗한 윈도우에서는
#   깃허브 쪽 뿌리가 아직 없어 "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate" 로 받기가 실패했다(0.1.11 실제 사용자 기록).
#   인증서 검증을 끄는 길은 없다. 어느 길로 받든 받은 뒤 sha256 으로 확인한다.
# - 다시 시도: 조금이라도 더 받아지는 동안은 계속 이어 받음(기다림 2·4·8…초). 파이썬으로 안 되면(인증서 확인 실패·프록시 자동 설정 등)
#   해시로 확인하는 파일에 한해 윈도우에 든 내려받기(curl.exe → 파워셸)로 대신 받음. 실패하면 원인 종류를 가려 쉬운 말로 알림(WHY).
# - 확인: 크기 + sha256(큰 파일) 또는 git_sha1(작은 파일, git blob 해시). 공식 해시가 빈 칸인 파일은
#         '설치 때 확인' — 크기만 보고 받은 뒤 계산한 sha256 을 보여 주고, --allow-unverified 없이는 받지 않음.
# - 받는 주소: https 만, 정해 둔 곳(huggingface.co·hf.co·github.com 과 그 내려받기 서버)만 따라감.
# - 확인 기록: sha256 이 맞은 파일은 그 폴더의 .verified.json 에 (크기·수정 시각·sha256)을 적어 두고, 다음 설치 때
#   크기·수정 시각이 같으면 다시 계산하지 않음(5GB 두뇌 모델을 매번 다 읽지 않게). check 명령은 늘 다시 계산.
# - 설치 프로그램(setup_core.py)은 ensure_model() 과 download() 를 부름(진행 표시 progress 를 받음).
# 종료 코드: 0 = 됨, 1 = 실패(어느 파일이 왜 실패했는지 한국어로 출력)
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "models.json")
UA = "KimBiseo-installer/1"
ALLOWED_HOSTS = ("huggingface.co", ".hf.co", "github.com", ".githubusercontent.com")
CHUNK = 1024 * 1024


def models_dir(args):
    if args.dest:
        return os.path.abspath(os.path.expandvars(args.dest))
    sys.path.insert(0, os.path.join(REPO, "voice"))
    import config as C  # 표준 라이브러리만 쓰는 설정 읽기
    return C.path(C.load(args.settings, warn=lambda *_: None), "모델")


def load_manifest(path=MANIFEST):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    if m.get("schema") != "kimbiseo-models/1":
        raise SystemExit("models.json 형식이 다릅니다")
    return {x["name"]: x for x in m["models"]}


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024


def host_ok(url, hosts=None):
    u = urllib.parse.urlsplit(url)
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == a.lstrip(".") or (a.startswith(".") and h.endswith(a)) for a in (hosts or ALLOWED_HOSTS))


def _redirect_for(hosts=None):
    class _Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            newurl = urllib.parse.urljoin(req.full_url, newurl)
            if not host_ok(newurl, hosts):
                raise urllib.error.URLError(f"허용하지 않은 주소로 넘김: {urllib.parse.urlsplit(newurl).hostname}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    return _Redirect


def ca_bundle():
    """모질라 뿌리 인증서 묶음(certifi 의 cacert.pem) 경로. 설치할 때는 막 넣은 pip 에 든 것, 설치 뒤에는 본체 부품의 것. 없으면 ''."""
    import importlib
    for mod in ("certifi", "pip._vendor.certifi"):
        try:
            path = importlib.import_module(mod).where()
            if path and os.path.isfile(path):
                return path
        except Exception:  # noqa: BLE001  (없거나 못 읽으면 다음 것)
            continue
    return ""


_TLS = {}


def ssl_context():
    """보안 연결 설정: 윈도우 인증서 저장소(회사·백신이 넣은 뿌리 포함) + 모질라 뿌리 묶음. 검증(인증서·이름 확인)은 끄지 않는다."""
    import ssl
    if "ctx" not in _TLS:
        ctx = ssl.create_default_context()
        bundle = ca_bundle()
        if bundle:
            try:
                ctx.load_verify_locations(cafile=bundle)
            except (OSError, ssl.SSLError):
                bundle = ""
        _TLS["ctx"], _TLS["bundle"] = ctx, bundle
    return _TLS["ctx"]


def tls_note():
    """기록용: 어떤 뿌리 인증서를 믿고 있는지(경로는 파일 이름만)."""
    ssl_context()
    return "윈도우 저장소 + 묶음(" + os.path.basename(os.path.dirname(_TLS["bundle"])) + ")" if _TLS.get("bundle") else "윈도우 저장소만(묶음 없음)"


def make_opener(hosts=None):
    """정해 둔 곳만 따라가고(넘겨주기 검사), 위 보안 연결 설정을 쓰는 여는 도구."""
    return urllib.request.build_opener(_redirect_for(hosts), urllib.request.HTTPSHandler(context=ssl_context()))


class _LazyOpener:
    """OPENER.open(...) — 처음 쓸 때 만든다(불러오기만 할 때는 인증서 묶음을 읽지 않게)."""

    def open(self, *a, **k):
        if "opener" not in _TLS:
            _TLS["opener"] = make_opener()
        return _TLS["opener"].open(*a, **k)


OPENER = _LazyOpener()


def file_hashes(path, want_git=False, progress=None, algo="sha256"):
    size = os.path.getsize(path)
    h256 = hashlib.new(algo)
    hg = hashlib.sha1(b"blob %d\0" % size) if want_git else None
    done, last = 0, 0
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK * 4)
            if not b:
                break
            h256.update(b)
            if hg:
                hg.update(b)
            done += len(b)
            if progress and time.time() - last > 0.5:
                last = time.time()
                progress(done, size)
    return h256.hexdigest(), (hg.hexdigest() if hg else None)


def _seen_file(path):
    return os.path.join(os.path.dirname(path), ".verified.json")


def _seen_get(path):
    try:
        with open(_seen_file(path), encoding="utf-8") as f:
            j = json.load(f)
        st = os.stat(path)
        v = j.get(os.path.basename(path))
        if v and v[0] == st.st_size and v[1] == st.st_mtime_ns:
            return v[2]
    except (OSError, ValueError, TypeError, IndexError, AttributeError):
        pass
    return None


def _seen_put(path, s256):
    f = _seen_file(path)
    try:
        try:
            with open(f, encoding="utf-8") as fh:
                j = json.load(fh)
            if not isinstance(j, dict):
                j = {}
        except (OSError, ValueError):
            j = {}
        st = os.stat(path)
        j[os.path.basename(path)] = [st.st_size, st.st_mtime_ns, s256]
        with open(f + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(j, fh, ensure_ascii=False, indent=0)
        os.replace(f + ".tmp", f)
    except OSError:
        pass


def verify(path, spec, progress=None, use_seen=False):
    """→ (됨?, 이유, 계산한 sha256). use_seen=True 면 .verified.json 기록(크기·수정 시각이 같을 때)을 믿음."""
    if not os.path.isfile(path):
        return False, "파일 없음", None
    size = os.path.getsize(path)
    if spec.get("size") is not None and size != spec["size"]:
        return False, f"크기 다름({size} ≠ {spec['size']})", None
    if use_seen and spec.get("sha256") and _seen_get(path) == spec["sha256"]:
        return True, "sha256 맞음(확인 기록)", spec["sha256"]
    s256, sg = file_hashes(path, want_git=bool(spec.get("git_sha1")), progress=progress)
    if spec.get("sha256"):
        if s256 == spec["sha256"]:
            _seen_put(path, s256)
        return (s256 == spec["sha256"], "sha256 맞음" if s256 == spec["sha256"] else "sha256 다름", s256)
    if spec.get("git_sha1"):
        return (sg == spec["git_sha1"], "git_sha1 맞음" if sg == spec["git_sha1"] else "git_sha1 다름", s256)
    return True, "크기만 맞음(공식 해시 없음 — 설치 때 확인)", s256


def base_url(m):
    """models.json 의 base_url 에 있는 {revision} 자리를 고정 판으로 채움(판이 바뀌면 받는 파일도 그 판)."""
    u = m["base_url"]
    if "{revision}" in u:
        if not m.get("revision"):
            raise ValueError(f"{m.get('name')}: base_url 에 {{revision}} 이 있는데 revision 이 비어 있음")
        u = u.replace("{revision}", m["revision"])
    return u


# ---------------------------------------------------------------- 받기(이어 받기·다시 시도·원인 가려내기·윈도우 내려받기로 대신 받기)
TIMEOUT = 60              # 한 번 읽기를 기다리는 초(그동안 아무것도 안 오면 끊고 이어서 다시)
NO_PROGRESS_TRIES = 5     # 거의 못 받은 시도가 이만큼 이어지면 그만둠(받아지는 동안은 계속 이어 받음)
MIN_GAIN = 128 * 1024     # 한 번 시도에 이만큼은 더 받아야 '받아지는 중'으로 봄(100KB 받고 멈추는 회선에서 끝없이 돌지 않게)
MAX_TRIES = 60            # 그래도 끝없이 돌지 않게 하는 상한
BACKOFF_MAX = 30          # 다시 시도 사이 기다림(2, 4, 8 … 초)의 상한
RENAME_TRIES = 40         # 다 받은 파일 이름 바꾸기 — 백신이 방금 받은 파일을 검사하느라 잠깐 잡고 있으면 0.5초씩 기다렸다 다시
NATIVE_ENV = "KIMBISEO_DOWNLOADER"    # 문제 해결용: python | curl | powershell 중 하나로 받는 방식을 정함(없으면 차례로)

# 원인 종류 → 사용자에게 보여 줄 쉬운 말(설치 창·기록에 그대로 나감)
WHY = {
    "tls": "보안 인증서를 확인하지 못했어요(백신이나 회사·학교 인터넷이 연결을 검사하거나, PC 날짜·시계가 틀렸을 수 있어요).",
    "clock": "PC 날짜·시계가 틀린 것 같아요. 윈도우 시계를 맞춘 뒤 다시 해 주세요.",
    "dns": "인터넷 연결이 안 돼요(받는 곳 주소를 찾지 못했어요).",
    "timeout": "받는 곳이 응답하지 않아요(인터넷이 느리거나 막혀 있어요).",
    "reset": "받는 도중에 자꾸 끊겨요.",
    "blocked": "인터넷에서 받는 길이 막혀 있어요(회사·학교 인터넷이나 백신 때문일 수 있어요).",
    "http403": "받는 곳에서 거절했어요(회사·학교 인터넷이 막았을 수 있어요).",
    "http404": "받을 파일을 찾지 못했어요. 새 설치 파일을 받아 주세요.",
    "http429": "받는 곳이 붐벼요. 조금 뒤에 다시 해 주세요.",
    "http5xx": "받는 곳에 잠깐 문제가 있어요. 조금 뒤에 다시 해 주세요.",
    "redirect": "회사 인터넷이나 보안 프로그램이 받는 주소를 바꿔서 멈췄어요.",
    "short": "받는 도중에 끊겼어요.",
    "file": "받은 파일을 저장하지 못했어요(백신이 막았을 수 있어요).",
    "net": "인터넷 연결에 문제가 있어요.",
}


class DownloadError(RuntimeError):
    """받기 실패 — kind(원인 종류) · why(쉬운 말) · detail(기술 내용) · tried(써 본 방식들)."""

    def __init__(self, kind, detail="", tried=()):
        self.kind = kind if kind in WHY else "net"
        self.why = WHY[self.kind]
        self.detail = str(detail)[:600]
        self.tried = list(tried)
        super().__init__(f"{self.why} — {self.detail}" + (f" (써 본 방식: {', '.join(self.tried)})" if self.tried else ""))


def classify(ex):
    """예외 → 원인 종류(WHY 의 열쇠)."""
    import socket
    import ssl
    reason = getattr(ex, "reason", None)
    text = f"{type(ex).__name__} {ex} {reason if reason is not None else ''}".lower()
    if isinstance(ex, urllib.error.HTTPError):
        c = ex.code
        return "http403" if c in (401, 403, 407) else "http404" if c in (404, 410) else "http429" if c == 429 else "http5xx" if c >= 500 else "net"
    if "certificate is not yet valid" in text or "certificate has expired" in text:
        return "clock"          # 인증서 날짜가 안 맞음 = 거의 언제나 PC 날짜·시계가 틀린 것
    for e in (ex, reason):
        if isinstance(e, ssl.SSLCertVerificationError):
            return "tls"
    if "certificate_verify_failed" in text or "certificate verify failed" in text:
        return "tls"
    if isinstance(ex, ssl.SSLError) or isinstance(reason, ssl.SSLError):
        return "tls" if "cert" in text else "reset"
    if "허용하지 않은 주소" in text:
        return "redirect"
    if isinstance(reason, socket.gaierror) or isinstance(ex, socket.gaierror) or "getaddrinfo" in text or "11001" in text:
        return "dns"
    if isinstance(ex, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in text:
        return "timeout"
    if isinstance(ex, (ConnectionResetError, ConnectionAbortedError)) or isinstance(reason, (ConnectionResetError, ConnectionAbortedError)) \
            or "10054" in text or "10053" in text or "incompleteread" in text or "connection broken" in text:
        return "reset"
    if isinstance(ex, ConnectionRefusedError) or isinstance(reason, ConnectionRefusedError) or any(c in text for c in ("10061", "10013", "10065", "10051", "10060")):
        return "blocked" if "10060" not in text else "timeout"
    if "받은 크기가 모자람" in text:
        return "short"
    return "net"


def _disk_full(ex):
    return isinstance(ex, OSError) and (getattr(ex, "errno", 0) == 28 or getattr(ex, "winerror", 0) in (39, 112))


def _replace(src, dst, say=print):
    """os.replace — 백신·색인이 방금 쓴 파일을 잠깐 잡고 있으면(권한 없음·다른 프로그램이 사용 중) 조금씩 기다렸다 다시."""
    for i in range(RENAME_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError as ex:
            if i == RENAME_TRIES - 1:
                raise
            if i in (0, 10):
                say(f"    {os.path.basename(dst)}: 파일이 잠깐 잡혀 있음({ex.__class__.__name__}) — 기다렸다 다시")
            time.sleep(0.5)


def _part_size(part):
    try:
        return os.path.getsize(part)
    except OSError:
        return 0


def _fetch_python(opener, url, part, size, say, progress, dest):
    """파이썬으로 한 번 받기(이어 받기). → (다 받았나, 알게 된 전체 크기). 실패는 예외."""
    have = _part_size(part)
    if size is not None and have > size:
        os.remove(part)
        have = 0
    if size is not None and have == size:
        return True, size
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})})
    with opener.open(req, timeout=TIMEOUT) as r:
        if have and r.status != 206:      # 이어 받기를 안 받는 서버 → 처음부터
            have = 0
        if size is None:
            cr = r.headers.get("Content-Range", "")
            tail = cr.rsplit("/", 1)[-1] if "/" in cr else ""
            if tail.isdigit():
                size = int(tail)
            elif r.headers.get("Content-Length", "").isdigit():
                size = int(r.headers["Content-Length"]) + have
        t0, last, got0 = time.time(), 0, have
        with open(part, "ab" if have else "wb") as f:
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                f.write(b)
                have += len(b)
                if time.time() - last > 1:
                    last = time.time()
                    rate = (have - got0) / max(1e-6, time.time() - t0)
                    if progress:
                        progress(have, size, rate)
                    else:
                        say(f"    {os.path.basename(dest)} {human(have)} / {human(size)} ({human(rate)}/초)")
    if size is None or have == size:
        return True, have
    raise OSError(f"받은 크기가 모자람({have}/{size})")


def _watch(proc, part, size, progress, t0, have0):
    """바깥 프로그램(curl·powershell)이 받는 동안 파일 크기로 진행을 알림. 끝나면 종료 코드."""
    last = 0
    while proc.poll() is None:
        time.sleep(0.5)
        if progress and time.time() - last > 1:
            last = time.time()
            have = _part_size(part)
            progress(have, size, (have - have0) / max(1e-6, time.time() - t0))
    return proc.returncode


def _fetch_curl(url, part, size, say, progress):
    """윈도우에 든 curl.exe(윈도우 인증서·보안 연결을 그대로 씀)로 이어 받기. → (다 받았나, 이유)."""
    import shutil
    import subprocess
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    if not os.path.isfile(exe):
        exe = shutil.which("curl.exe") or ""
    if not exe:
        return False, "curl.exe 없음"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    base = [exe, "--location", "--fail", "--silent", "--show-error", "--max-redirs", "5", "--proto", "=https", "--proto-redir", "=https",
            "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", str(TIMEOUT), "--user-agent", UA, "--output", part]
    extra = ["--ssl-revoke-best-effort"]            # 인증서 폐기 목록을 못 받아도(회사망·방화벽) 멈추지 않게 — 옛 curl 은 이 옵션을 모름
    why, stuck = "", 0
    for _round in range(8):
        have0 = _part_size(part)
        if size is not None and have0 == size:
            return True, ""
        if size is not None and have0 > size:
            os.remove(part)
            have0 = 0
        cmd = base + extra + (["--continue-at", "-"] if have0 else []) + [url]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        rc = _watch(p, part, size, progress, time.time(), have0)
        err = (p.stderr.read() or b"").decode("utf-8", "replace").strip()[-300:]
        have = _part_size(part)
        if rc == 0 and (size is None or have == size):
            return True, ""
        why = f"curl 종료 코드 {rc} {err}"
        say(f"    윈도우 내려받기(curl) {why[:200]} · 받은 것 {human(have)}")
        if rc == 2 and extra:                       # 모르는 옵션(옛 curl) → 옵션 빼고 다시
            extra = []
            continue
        if rc == 33:                                # 이어 받기를 안 받는 서버 → 처음부터
            try:
                os.remove(part)
            except OSError:
                pass
            continue
        if rc == 23:                                # 디스크에 못 씀
            raise OSError(28, "디스크에 쓰지 못함(curl 23)")
        if rc in (22, 60, 35, 77, 6, 7) and have <= have0:      # 거절·인증서·연결 자체가 안 됨 → 되풀이해도 같음
            return False, why
        stuck = 0 if have - have0 >= MIN_GAIN else stuck + 1
        if stuck >= 3:
            return False, why
        time.sleep(min(BACKOFF_MAX, 2 ** (stuck + 1)))
    return False, why


def _fetch_powershell(url, part, size, say, progress):
    """윈도우 파워셸의 Invoke-WebRequest(윈도우 인증서·프록시 자동 설정을 그대로 씀)로 받기 — 이어 받기는 안 됨. → (다 받았나, 이유)."""
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ps = ("$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';"
          "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
          "try{[Net.WebRequest]::DefaultWebProxy.Credentials=[Net.CredentialCache]::DefaultNetworkCredentials}catch{};"      # 회사망 프록시(윈도우 로그인으로 인증)
          "Invoke-WebRequest -UseBasicParsing -Uri $env:K_URL -OutFile $env:K_OUT -UserAgent $env:K_UA")
    why = ""
    for _round in range(2):
        try:
            os.remove(part)
        except OSError:
            pass
        try:
            p = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags,
                                 env={**os.environ, "K_URL": url, "K_OUT": part, "K_UA": UA})
        except OSError as ex:
            return False, f"powershell 을 못 켬({ex.__class__.__name__})"
        rc = _watch(p, part, size, progress, time.time(), 0)
        err = (p.stderr.read() or b"").decode("utf-8", "replace").strip()[-300:]
        have = _part_size(part)
        if rc == 0 and have and (size is None or have == size):
            return True, ""
        why = f"powershell 종료 코드 {rc} {err}"
        say(f"    윈도우 내려받기(파워셸) {why[:200]} · 받은 것 {human(have)}")
        time.sleep(3)
    return False, why


def download(url, dest, size=None, tries=None, say=print, progress=None, hosts=None, native=False):
    """url → dest. size 를 모르면 None(서버가 알려 준 길이로). 받는 중엔 dest.part, 끊기면 이어서 받음.
    progress(받은 바이트, 전체 바이트|None, 초당 바이트) · hosts = 허용 호스트 목록(기본 ALLOWED_HOSTS).
    다시 시도: 받아지는 동안(한 번에 MIN_GAIN 넘게)은 계속 이어 받고(기다림 2·4·8…초), 거의 못 받은 시도가 NO_PROGRESS_TRIES 번
              (tries 를 주면 그 수) 이어지면 그만둔다.
    native=True(받은 뒤 부르는 쪽이 sha256 으로 확인하는 파일만): 파이썬으로 안 되면 윈도우 내려받기(curl.exe → 파워셸)로 대신 받는다.
      - 인증서 확인 실패는 다시 해도 같으므로 바로 넘어간다. 파이썬은 윈도우 인증서 저장소에 '이미 있는' 뿌리 인증서만 읽는데,
        윈도우는 뿌리 인증서를 처음 쓸 때 받아 넣는다 → 깃허브 쪽 뿌리를 아직 받은 적 없는 PC 에서는 파이썬만 실패한다(0.1.11 까지의 '펫' 단계 멈춤).
      - 프록시 자동 설정(PAC)·보안 프로그램 때문에 파이썬 연결만 막힌 PC 도 이 길로 받는다.
    실패하면 DownloadError(원인 종류·쉬운 말·기술 내용). 디스크가 꽉 찼으면 OSError(28)."""
    if not host_ok(url, hosts):
        raise DownloadError("redirect", f"허용하지 않은 주소: {url}")
    opener = make_opener(hosts) if hosts else OPENER
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    forced = (os.environ.get(NATIVE_ENV) or "").strip().lower()
    limit = int(tries) if tries else NO_PROGRESS_TRIES
    tried, last_kind, last_err = [], "net", ""
    done = False
    if forced not in ("curl", "powershell"):
        tried.append("파이썬")
        stuck = attempt = 0
        while attempt < MAX_TRIES:
            attempt += 1
            have0 = _part_size(part)
            try:
                done, size = _fetch_python(opener, url, part, size, say, progress, dest)
                if done:
                    break
            except (urllib.error.URLError, OSError, TimeoutError) as ex:
                if _disk_full(ex):
                    raise
                if isinstance(ex, PermissionError):
                    raise DownloadError("file", f"{type(ex).__name__}: {ex}", tried) from None
                last_kind, last_err = classify(ex), f"{type(ex).__name__}: {ex}"
                have = _part_size(part)
                stuck = 0 if have - have0 >= MIN_GAIN else stuck + 1
                wait = min(BACKOFF_MAX, 2 ** min(stuck, 5)) if stuck else 2
                if last_kind == "http429":
                    try:
                        wait = max(wait, min(60, int(ex.headers.get("Retry-After") or 0)))
                    except (TypeError, ValueError, AttributeError):
                        pass
                say(f"    {attempt}번째 시도 실패({last_kind}): {ex} — 받은 것 {human(have)}")
                if last_kind in ("tls", "clock", "http404", "redirect") or (last_kind == "http403" and stuck >= 2) or stuck >= limit:
                    break
                say(f"    {wait}초 뒤 이어서 받음")
                time.sleep(wait)
    if not done and native and os.name == "nt" and last_kind != "http404" and forced != "python":
        for name, fn in (("curl", _fetch_curl), ("powershell", _fetch_powershell)):
            if forced in ("curl", "powershell") and forced != name:
                continue
            say(f"    윈도우 내려받기({name})로 대신 받아 봄 — 앞선 방식이 안 된 까닭: {WHY.get(last_kind, last_kind)}")
            tried.append("윈도우 " + name)
            ok, why = fn(url, part, size, say, progress)
            if ok:
                done = True
                size = _part_size(part)
                say(f"    윈도우 내려받기({name})로 받음 {human(size)}")
                break
            last_err = (last_err + " | " + why).strip(" |")
    if not done:
        raise DownloadError(last_kind, last_err, tried)
    if progress:
        progress(size, size, 0)
    try:
        _replace(part, dest, say)
    except PermissionError as ex:
        raise DownloadError("file", f"{type(ex).__name__}: {ex}", tried) from None


def file_url(m, f):
    """파일 하나의 받을 주소. 'asset' 이 있으면 그 이름(릴리스 첨부처럼 폴더 없는 곳), 없으면 path."""
    return base_url(m) + urllib.parse.quote(f.get("asset") or f["path"])


def load_manifests(*paths):
    """여러 모델 목록을 하나로(뒤가 앞을 덮음). 없는 파일은 건너뜀 — 라데온 판 목록(installer/radeon/models.json)을 더할 때."""
    out = {}
    for p in paths:
        if p and os.path.isfile(p):
            out.update(load_manifest(p))
    return out


def ensure_model(m, root, say=print, progress=None, allow_unverified=False):
    """모델 하나를 root\\<이름>\\ 에 받고 확인. 이미 맞는 파일은 건너뜀. → (됨?, [실패한 파일], 받은 바이트)
    progress(이 모델에서 끝난 바이트, 이 모델 전체 바이트, 초당 바이트, 지금 하는 일)"""
    folder = os.path.join(root, m["name"])
    total = sum(f["size"] for f in m["files"])
    finished, got, failed = 0, 0, []
    for f in m["files"]:
        dest = os.path.join(folder, *f["path"].split("/"))
        if not (f.get("sha256") or f.get("git_sha1")) and not allow_unverified:
            say(f"  건너뜀 {f['path']}: 공식 해시가 없음(설치 때 확인)")
            failed.append(f"{m['name']}/{f['path']}")
            continue
        pv = (lambda d, t, _base=finished: progress(_base + d * 0.999, total, 0, "확인")) if progress else None
        ok, why, _ = verify(dest, f, progress=pv, use_seen=True) if os.path.isfile(dest) else (False, "", None)
        if ok:
            say(f"  있음 {f['path']} ({why})")
            finished += f["size"]
            if progress:
                progress(finished, total, 0, "확인")
            continue
        say(f"  받는 중 {f['path']} ({human(f['size'])})")
        pd = (lambda d, t, r, _base=finished: progress(_base + (d or 0), total, r, "받기")) if progress else None
        try:
            download(file_url(m, f), dest, f["size"], say=say, progress=pd,
                     native=bool(f.get("sha256") or f.get("git_sha1")))      # 받은 뒤 해시로 확인하는 파일만 윈도우 내려받기로 대신 받음
        except RuntimeError as ex:
            say(f"  실패 {f['path']}: {ex}")
            failed.append(f"{m['name']}/{f['path']}")
            continue
        got += f["size"]
        pv = (lambda d, t, _base=finished: progress(_base + d * 0.999, total, 0, "확인")) if progress else None
        ok, why, s256 = verify(dest, f, progress=pv)
        if not ok:
            os.replace(dest, dest + ".bad")
            say(f"  실패 {f['path']}: {why} — 받은 파일을 .bad 로 옮김(다시 시도하면 새로 받음)")
            failed.append(f"{m['name']}/{f['path']}")
        else:
            say(f"  됨 {f['path']} ({why})" + ("" if (f.get('sha256') or f.get('git_sha1')) else f" sha256={s256}"))
        finished += f["size"]
    return (not failed), failed, got


def cmd_list(models, args):
    rows = []
    for m in models.values():
        rows.append({"name": m["name"], "role": m["role"], "required": m["required"], "size": m["size_total"], "license": m["license"],
                     "unverified": [f["path"] for f in m["files"] if not (f.get("sha256") or f.get("git_sha1"))]})
        if not args.json:
            print(f"{m['name']:<28} {human(m['size_total']):>9}  {'필수' if m['required'] else '선택'}  {m['role']}  [{m['license']}]"
                  + ("  ※공식 해시 없음 — 설치 때 확인" if rows[-1]["unverified"] else ""))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


def cmd_check(models, args):
    if not args.names:
        print("확인할 모델 이름을 적어 주세요")
        return 1
    bad = 0
    out = []
    for name in args.names:
        m = models.get(name)
        if not m:
            print(f"모르는 모델: {name}")
            return 1
        folder = os.path.abspath(args.dir) if args.dir else os.path.join(models_dir(args), name)
        for f in m["files"]:
            ok, why, s256 = verify(os.path.join(folder, *f["path"].split("/")), f)
            out.append({"model": name, "path": f["path"], "ok": ok, "why": why, "sha256": s256})
            bad += not ok
            if not args.json:
                print(f"  {'됨 ' if ok else '실패'} {name}/{f['path']} — {why}")
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"확인 끝: 파일 {len(out)}개 중 실패 {bad}개")
    return 0 if bad == 0 else 1


def cmd_get(models, args):
    names = args.names or [n for n, m in models.items() if m["required"] or args.all]
    root = models_dir(args)
    print(f"모델 폴더: {root}")
    failed = []
    for name in names:
        m = models.get(name)
        if not m:
            print(f"모르는 모델: {name}")
            return 1
        print(f"[{name}] {human(m['size_total'])} — {m['role']}")
        ok, bad, _ = ensure_model(m, root, allow_unverified=args.allow_unverified)
        failed += bad
    if failed:
        print("받지 못한 파일: " + ", ".join(failed))
        return 1
    print("모두 받음")
    return 0


def main():
    ap = argparse.ArgumentParser(description="김비서 모델 받기·확인")
    ap.add_argument("cmd", choices=["list", "get", "check"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true", help="선택 모델까지")
    ap.add_argument("--dest", default=None, help="모델 폴더(기본 = 설정 '경로.모델')")
    ap.add_argument("--dir", default=None, help="check: 이 폴더를 그 모델 폴더로 보고 확인")
    ap.add_argument("--settings", default=None)
    ap.add_argument("--allow-unverified", action="store_true", help="공식 해시가 없는 파일도 크기만 보고 받음")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    models = load_manifest()
    return {"list": cmd_list, "get": cmd_get, "check": cmd_check}[args.cmd](models, args)


if __name__ == "__main__":
    sys.exit(main())
