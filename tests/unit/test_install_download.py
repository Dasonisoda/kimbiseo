# 설치 때 받기 단위 시험 — 끊겨도 이어 받기 · 원인 가려내기 · 윈도우 내려받기로 대신 받기 · 깨진 파일 다시 받기 ·
#   '펫' 단계가 실패해도 설치를 끝내기 · 펫만 다시 설치 · 받아 둔 파일로 넣기.   python -B -m tests.unit.test_install_download
#
# 진짜 인터넷·진짜 설치 없이 돈다: 이 PC 안 임시 서버(일부러 끊고·거절하고·깨진 파일을 줌)와 임시 폴더(한글·빈칸 든 경로)만 쓴다.
import argparse
import hashlib
import io
import json
import os
import ssl
import sys
import tempfile
import threading
import urllib.error
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))

import get_models as GM  # noqa: E402
import setup_core as SC  # noqa: E402

OK = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


def make_zip():
    """가짜 '펫 실행 틀' 압축 파일(진짜 실행 파일 아님) — 3MB 쯤 되게 안 눌리는 내용으로."""
    bio = io.BytesIO()
    blob = b"".join(hashlib.sha512(str(i).encode()).digest() for i in range(46000))
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_STORED) as z:
        z.writestr("electron.exe", b"MZ fake for test")
        z.writestr("resources/default_app.asar", blob)
        z.writestr("locales/ko.pak", b"ko")
    return bio.getvalue()


GOOD = make_zip()
BAD = bytes([GOOD[0] ^ 0x5A]) + GOOD[1:]
SHA = hashlib.sha256(GOOD).hexdigest()
HITS = {}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        n = HITS[path] = HITS.get(path, 0) + 1
        code = {"/403": 403, "/404": 404}.get(path)
        if path == "/429-then-ok" and n <= 2:
            code = 429
        if code:
            self.send_response(code)
            self.send_header("Content-Length", "0")
            if code == 429:
                self.send_header("Retry-After", "0")
            self.end_headers()
            return
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng and path != "/norange-cut" else 0
        data = BAD if path == "/corrupt" or (path == "/corrupt-once" and n == 1) else GOOD
        body = data[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.end_headers()
        limit = {"/cut": 400 * 1024, "/norange-cut": 400 * 1024, "/cut-small": 20 * 1024}.get(path)
        try:
            if limit is None:
                self.wfile.write(body)
            else:
                self.wfile.write(body[:limit])
                self.wfile.flush()
                self.close_connection = True
                self.connection.close()
        except OSError:
            pass


class Net:
    """임시 서버 + 시험 동안만 '이 PC 안 http 주소'를 받아도 되는 곳으로(진짜 설치기는 https·정해 둔 곳만)."""

    def __enter__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.saved = (GM.host_ok, GM.TIMEOUT, GM.BACKOFF_MAX, GM.time.sleep)
        GM.host_ok = lambda url, hosts=None: True
        GM.TIMEOUT, GM.BACKOFF_MAX = 3, 0
        GM.time.sleep = lambda s: None
        HITS.clear()
        return self

    def __exit__(self, *a):
        GM.host_ok, GM.TIMEOUT, GM.BACKOFF_MAX, GM.time.sleep = self.saved
        self.srv.shutdown()
        self.srv.server_close()


def test_download_resume_and_reasons():
    with Net() as net, tempfile.TemporaryDirectory(prefix="김비서 받기 시험 ") as td:
        logs = []
        d = os.path.join(td, "한글 폴더", "a.zip")
        GM.download(net.base + "/cut", d, len(GOOD), say=logs.append)
        check("끊겨도 이어 받기: 400KB 마다 끊기는 회선에서 끝까지(5번 넘게 끊겨도) · 한글·빈칸 경로",
              hashlib.sha256(open(d, "rb").read()).hexdigest() == SHA and HITS["/cut"] >= 7 and not os.path.exists(d + ".part"), HITS)
        d = os.path.join(td, "b.zip")
        GM.download(net.base + "/429-then-ok", d, len(GOOD), say=logs.append)
        check("'잠시 뒤 다시'(429) 뒤에 받음", os.path.getsize(d) == len(GOOD))
        for path, kind, max_hits in (("/403", "http403", 3), ("/404", "http404", 1), ("/norange-cut", "short", 6), ("/cut-small", "short", 6)):
            HITS.clear()
            try:
                GM.download(net.base + path, os.path.join(td, "x" + path.strip("/") + ".zip"), len(GOOD), say=logs.append)
                check(f"받을 수 없는 조건 {path}: 실패로 알림", False)
            except GM.DownloadError as ex:
                check(f"받을 수 없는 조건 {path}: 원인 {kind} · 쉬운 말 · 끝없이 돌지 않음({HITS.get(path)}번)",
                      ex.kind == kind and ex.why == GM.WHY[kind] and HITS.get(path, 0) <= max_hits, f"{ex.kind} {HITS}")
        part = os.path.join(td, "xcut-small.zip.part")
        check("못 받았어도 받은 만큼(.part)은 남김(다음에 이어 받기)", os.path.isfile(part) and os.path.getsize(part) > 0)
    try:
        GM.download("http://github.com/x.zip", os.path.join(tempfile.gettempdir(), "kb_no.zip"), 1)
        check("https 가 아니거나 정해 둔 곳이 아니면 받지 않음", False)
    except GM.DownloadError as ex:
        check("https 가 아니거나 정해 둔 곳이 아니면 받지 않음", ex.kind == "redirect")


def test_classify():
    cases = [
        (urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate")), "tls"),
        (urllib.error.URLError(OSError(11001, "getaddrinfo failed")), "dns"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionResetError(10054, "원격 호스트에 의해 강제로 끊김"), "reset"),
        (urllib.error.URLError(ConnectionRefusedError(10061, "거부")), "blocked"),
        (urllib.error.URLError("허용하지 않은 주소로 넘김: evil.example"), "redirect"),
        (OSError("받은 크기가 모자람(1/2)"), "short"),
        (urllib.error.HTTPError("u", 503, "x", {}, None), "http5xx"),
    ]
    bad = [(type(e).__name__, GM.classify(e), want) for e, want in cases if GM.classify(e) != want]
    check("실패 원인 가려내기(인증서·주소·시간 초과·끊김·막힘·넘겨주기·덜 받음·서버 문제)", not bad, bad)
    check("원인마다 쉬운 말이 있음", all(GM.WHY.get(k) for k in ("tls", "dns", "timeout", "reset", "blocked", "http403", "http404", "http429", "http5xx", "redirect", "short", "file", "net")))


def test_native_fallback():
    """파이썬이 인증서를 못 믿으면(윈도우 저장소에 뿌리 인증서가 아직 없음) 바로 윈도우 내려받기로 넘어간다."""
    with tempfile.TemporaryDirectory() as td:
        saved = (GM._fetch_python, GM._fetch_curl, GM._fetch_powershell, os.name)
        calls = []

        def py_fail(*a, **k):
            calls.append("python")
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"))

        def curl_ok(url, part, size, say, progress):
            calls.append("curl")
            open(part, "wb").write(b"x" * size)
            return True, ""

        def curl_bad(url, part, size, say, progress):
            calls.append("curl")
            return False, "curl 종료 코드 60"

        def ps_ok(url, part, size, say, progress):
            calls.append("powershell")
            open(part, "wb").write(b"y" * size)
            return True, ""
        try:
            GM._fetch_python, GM._fetch_curl, GM._fetch_powershell = py_fail, curl_ok, ps_ok
            d = os.path.join(td, "a.bin")
            GM.download("https://github.com/x/a.bin", d, 10, say=lambda m: None, native=True)
            check("인증서 확인 실패 → 다시 시도 없이 바로 윈도우 내려받기(curl)로 받음", calls == ["python", "curl"] and open(d, "rb").read() == b"x" * 10, calls)
            calls.clear()
            GM._fetch_curl = curl_bad
            d = os.path.join(td, "b.bin")
            GM.download("https://github.com/x/b.bin", d, 10, say=lambda m: None, native=True)
            check("curl 도 안 되면 파워셸로 받음", calls == ["python", "curl", "powershell"] and open(d, "rb").read() == b"y" * 10, calls)
            calls.clear()
            try:
                GM.download("https://github.com/x/c.bin", os.path.join(td, "c.bin"), 10, say=lambda m: None, native=False)
                check("해시로 확인하지 않는 파일은 윈도우 내려받기를 쓰지 않음", False)
            except GM.DownloadError as ex:
                check("해시로 확인하지 않는 파일은 윈도우 내려받기를 쓰지 않음", calls == ["python"] and ex.kind == "tls", calls)
            calls.clear()
            os.environ[GM.NATIVE_ENV] = "powershell"
            GM.download("https://github.com/x/d.bin", os.path.join(td, "d.bin"), 10, say=lambda m: None, native=True)
            check("받는 방식 정하기(문제 해결용 환경변수): powershell 만", calls == ["powershell"], calls)
        finally:
            os.environ.pop(GM.NATIVE_ENV, None)
            GM._fetch_python, GM._fetch_curl, GM._fetch_powershell = saved[:3]


def test_rename_waits_for_antivirus():
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.part"), os.path.join(td, "a.bin")
        open(a, "wb").write(b"1")
        real, n = os.replace, {"n": 0}

        def flaky(src, dst):
            n["n"] += 1
            if n["n"] <= 3:
                raise PermissionError(13, "다른 프로세스가 파일을 사용 중")
            return real(src, dst)
        saved_sleep = GM.time.sleep
        try:
            os.replace, GM.time.sleep = flaky, lambda s: None
            GM._replace(a, b, say=lambda m: None)
        finally:
            os.replace, GM.time.sleep = real, saved_sleep
        check("다 받은 파일을 백신이 잠깐 잡고 있어도 기다렸다 이름을 바꿈", os.path.isfile(b) and n["n"] == 4, n)


class St:
    """설치 상태 파일 대신 쓰는 가짜."""

    def __init__(self):
        self.lines, self.text = [], ""

    def log(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    def progress(self, frac, text=""):
        self.text = text or self.text


def test_fetcher_hash_and_manual_file():
    with Net() as net, tempfile.TemporaryDirectory(prefix="김비서 받기 시험 ") as td:
        f = SC.Fetcher(St(), ("127.0.0.1",))
        d = f.get(net.base + "/corrupt-once", os.path.join(td, "a.zip"), SHA, len(GOOD), "시험 파일")
        check("받은 파일이 원본과 다르면 저절로 한 번 새로 받아 맞춤", hashlib.sha256(open(d, "rb").read()).hexdigest() == SHA and HITS["/corrupt-once"] == 2, HITS)
        try:
            f.get(net.base + "/corrupt", os.path.join(td, "b.zip"), SHA, len(GOOD), "시험 파일")
            check("두 번 다 원본과 다르면 멈추고 '받아 둔 파일로 넣기'를 안내", False)
        except SC.Fail as ex:
            check("두 번 다 원본과 다르면 멈추고 '받아 둔 파일로 넣기'를 안내",
                  ex.info.get("원인") == "hash" and "받아 둔 파일" in ex.why and not os.path.exists(os.path.join(td, "b.zip")) and ex.info.get("주소"), ex.why)
        try:
            f.get(net.base + "/403", os.path.join(td, "c.zip"), SHA, len(GOOD), "시험 파일")
            check("받기 실패 안내에 원인·직접 받을 주소·넣을 곳이 들어감", False)
        except SC.Fail as ex:
            check("받기 실패 안내에 원인·직접 받을 주소·넣을 곳이 들어감",
                  ex.info.get("원인") == "http403" and ex.info.get("주소", "").endswith("/403") and ex.info.get("넣을곳") == td and "거절" in ex.why, ex.info)
        real = SC.shutil.disk_usage
        try:
            SC.shutil.disk_usage = lambda p: argparse.Namespace(free=1024 * 1024, total=1, used=1)
            f.get(net.base + "/ok", os.path.join(td, "d.zip"), SHA, len(GOOD), "시험 파일")
            check("디스크가 모자라면 받기 전에 쉬운 말로 멈춤", False)
        except SC.Fail as ex:
            check("디스크가 모자라면 받기 전에 쉬운 말로 멈춤", ex.info.get("원인") == "disk" and "디스크 공간" in ex.why and HITS.get("/ok") is None, ex.why)
        finally:
            SC.shutil.disk_usage = real
        # 직접 받아 둔 파일
        mine = os.path.join(td, "내려받기", "받은 것 (1).zip")
        os.makedirs(os.path.dirname(mine))
        open(mine, "wb").write(GOOD)
        dest = os.path.join(td, "downloads", "pet.zip")
        check("받아 둔 파일: 크기·sha256 이 맞으면 받는 자리에 둠", f.take_file(mine, dest, SHA, len(GOOD), "펫") == dest and os.path.getsize(dest) == len(GOOD))
        for content, word in ((GOOD[:1000], "크기"), (BAD, "원본과 달라요")):
            open(mine, "wb").write(content)
            try:
                f.take_file(mine, os.path.join(td, "downloads", "pet2.zip"), SHA, len(GOOD), "펫")
                check(f"받아 둔 파일: 틀린 파일은 거절({word})", False)
            except SC.Fail as ex:
                check(f"받아 둔 파일: 틀린 파일은 거절({word})", word in ex.why and not os.path.exists(os.path.join(td, "downloads", "pet2.zip")), ex.why)


def _installer(td, **over):
    a = argparse.Namespace(prefix=os.path.join(td, "프로그램 폴더"), data=os.path.join(td, "자료 폴더"), status=os.path.join(td, "status.json"), source="",
                           local_brain=False, gemma=None, desktop_dir="", startmenu_dir="", reg_key="KimBiseoUnitTest", display_name="김비서",
                           packs_catalog="", no_shortcuts=True, no_register=True, dry_run=False, file="")
    for k, v in over.items():
        setattr(a, k, v)
    inst = SC.Installer(a)
    inst.do_plan = lambda: (inst.state.__setitem__("plan", {"구성": "시험", "torch": "cpu", "llama": "", "모델": [], "설정": {}}), "시험")[1]
    inst.do_files = inst.do_packages = inst.do_brain = inst.do_models = lambda: ("됨", "시험")
    os.makedirs(os.path.join(a.prefix, "install"), exist_ok=True)
    return inst


def test_pet_step_is_optional_and_repairable():
    with Net() as net, tempfile.TemporaryDirectory(prefix="김비서 설치 시험 ") as td:
        inst = _installer(td)
        inst.rt["electron"] = {"version": "9.9.9", "url": net.base + "/403", "sha256": SHA, "size": len(GOOD)}
        rc = inst.run()
        st = json.load(open(inst.st.path, encoding="utf-8"))
        note = (st.get("주의") or [{}])[0]
        check("'펫' 단계가 실패해도 설치는 끝남(성공) — 마무리 단계까지 함",
              rc == 0 and st["성공"] is True and [s["상태"] for s in st["단계"] if s["id"] in ("pet", "finish")] == ["실패", "됨"], st.get("오류"))
        check("무엇이 빠졌는지 '주의'에 남김: 단계·이유·직접 받을 주소·파일 이름·넣을 곳",
              note.get("id") == "pet" and note.get("원인") == "http403" and note.get("직접받기", {}).get("주소", "").endswith("/403")
              and note["직접받기"].get("파일") == "403" and note["직접받기"].get("넣을곳") == inst.dl, note)
        cfg = json.load(open(inst.settings_file(), encoding="utf-8"))
        check("설정은 써 둠(김비서는 켤 수 있음) · 받다 만 자리(downloads)는 남김 · 상태 기록에 빠진 단계",
              "실행" in cfg and os.path.isdir(inst.dl) and inst.state.get("skipped") == ["pet"], inst.state)
        check("기록에 진단 줄(윈도우·원인·써 본 방식·프록시 여부)", any("진단:" in ln and "http403" in ln for ln in inst.st.lines if isinstance(ln, str)) if hasattr(inst.st, "lines")
              else "진단:" in open(inst.st.log_path, encoding="utf-8").read())

        # 펫만 다시 설치 — 이번에는 받아짐(자주 끊기는 회선)
        inst2 = _installer(td, status=os.path.join(td, "pet_status.json"))
        inst2.rt["electron"] = {"version": "9.9.9", "url": net.base + "/cut", "sha256": SHA, "size": len(GOOD)}
        rc = inst2.run_pet()
        st = json.load(open(inst2.st.path, encoding="utf-8"))
        exe = os.path.join(inst2.P, "runtime", "electron", "electron.exe")
        cfg = json.load(open(inst2.settings_file(), encoding="utf-8"))
        check("펫만 다시 설치: 받아서 풀고 설정에 펫 경로를 적음", rc == 0 and st["성공"] and os.path.isfile(exe) and cfg["실행"]["펫_실행파일"] == exe
              and open(os.path.join(os.path.dirname(exe), "kimbiseo_electron.txt")).read() == "9.9.9" and inst2.state.get("skipped") == [], st.get("오류"))
        check("펫만 다시 설치: 받은 압축 파일은 치움", not os.path.exists(os.path.join(inst2.dl, "cut")))
        HITS.clear()
        check("이미 설치돼 있으면 다시 받지 않음", inst2.do_pet()[1].startswith("이미 설치됨") and not HITS)


def test_pet_from_manual_file():
    with Net() as net, tempfile.TemporaryDirectory(prefix="김비서 설치 시험 ") as td:
        mine = os.path.join(td, "받은 파일.zip")
        open(mine, "wb").write(GOOD)
        inst = _installer(td, status=os.path.join(td, "pet_status.json"), file=mine)
        inst.rt["electron"] = {"version": "9.9.9", "url": net.base + "/403", "sha256": SHA, "size": len(GOOD)}      # 인터넷으로는 못 받는 상황
        rc = inst.run_pet()
        check("받아 둔 파일로 넣기: 인터넷으로 못 받아도 직접 받은 파일로 설치됨(받으러 가지 않음)",
              rc == 0 and os.path.isfile(os.path.join(inst.P, "runtime", "electron", "electron.exe")) and "/403" not in HITS, HITS)
        open(mine, "wb").write(BAD)
        inst = _installer(os.path.join(td, "둘째"), status=os.path.join(td, "pet_status2.json"), file=mine)
        inst.rt["electron"] = {"version": "9.9.9", "url": net.base + "/403", "sha256": SHA, "size": len(GOOD)}
        rc = inst.run_pet()
        st = json.load(open(inst.st.path, encoding="utf-8"))
        check("받아 둔 파일로 넣기: 다른 파일이면 설치하지 않고 알림", rc == 1 and st["성공"] is False and "원본과 달라요" in st["오류"]["이유"]
              and not os.path.exists(os.path.join(inst.P, "runtime", "electron")), st.get("오류"))


def test_broken_zip_is_not_installed():
    with Net() as net, tempfile.TemporaryDirectory(prefix="김비서 설치 시험 ") as td:
        inst = _installer(td, status=os.path.join(td, "pet_status.json"))
        nozip = b"not a zip" * 100
        inst.rt["electron"] = {"version": "9.9.9", "url": net.base + "/ok", "sha256": hashlib.sha256(nozip).hexdigest(), "size": len(nozip)}
        os.makedirs(inst.dl, exist_ok=True)
        open(os.path.join(inst.dl, "ok"), "wb").write(nozip)        # 해시는 맞지만 풀 수 없는 파일(있을 수 없는 일의 대비)
        old = os.path.join(inst.P, "runtime", "electron")
        os.makedirs(old)
        open(os.path.join(old, "electron.exe"), "wb").write(b"old")
        rc = inst.run_pet()
        check("풀다가 실패하면 예전 펫 실행 틀을 지우지 않음(반쯤 풀린 폴더를 '설치됨'으로 두지 않음)",
              rc == 1 and open(os.path.join(old, "electron.exe"), "rb").read() == b"old" and not os.path.exists(old + ".새로"))


def main():
    test_download_resume_and_reasons()
    test_classify()
    test_native_fallback()
    test_rename_waits_for_antivirus()
    test_fetcher_hash_and_manual_file()
    test_pet_step_is_optional_and_repairable()
    test_pet_from_manual_file()
    test_broken_zip_is_not_installed()
    bad = [n for n, ok in OK if not ok]
    print(f"\n설치 받기 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
