# 김비서 업데이트 바꾸기 일꾼 — 본체가 새 판을 받아 확인(서명·sha256)한 뒤 창 없이 띄운다. 직접 누르는 파일이 아님.
#   표준 라이브러리만. 본체가 이 파일을 <설치>\install\update\updater_run.py 로 복사해서 돌린다(바꾸는 동안 src 밖에서 돌게).
#
#   python updater_run.py spawn --prefix P --settings S --version V --body-pid N   본체가 부름: 아래 run 을 따로 띄우고 바로 끝남
#   python updater_run.py run   --prefix P --settings S --version V --body-pid N   실제 일(아래 차례)
#
# 차례: 김비서 끄기(실행 기록의 PID 만, 실행 파일·시작 시각 확인) → 받아 둔 새 판 파일 sha256 다시 확인 → src 를 통째로 바꿔 끼움
#       → 새 판 검사(문법·불러오기·본체가 실제로 켜지는지) → 실패하면 바로 예전 판으로 되돌림 → 김비서 다시 켜기
#       → 다시 켠 뒤 본체가 준비되기 전에 실행기가 오류로 꺼지면 그때도 예전 판으로 되돌리고 다시 켬.
# 바꾸는 것 = <설치>\src 하나(프로그램 코드). 그대로 두는 것 = 자료 폴더(설정·기억·열쇠·목소리·펫 옷), <설치>\models, <설치>\runtime.
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = 0x00000008
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
BREAKAWAY = 0x01000000
PKG_INDEX = "kimbiseo-update.json"       # 꾸러미 맨 위: {"format", "version", "files": {경로: {"sha256", "size"}}}
PKG_ROOT = "src/"                        # 꾸러미 안 프로그램 파일 자리
MUST_HAVE = ["app/main.py", "app/launcher.py", "app/version.py", "installer/setup_core.py", "installer/updater.py", "pet/main.js"]
DEPS = ["installer/locks/app.json", "installer/locks/voice-cuda.json", "installer/locks/voice-cpu.json", "installer/runtimes.json",
        "installer/models.json"]   # 이 파일이 바뀌는 판은 파이썬 부품·모델도 바뀜 → 코드만 바꾸는 업데이트로는 안 되고 새 설치 파일로
MAX_FILES = 3000
MAX_TOTAL = 200 * 1024 * 1024
VER_RE = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,6})$")
LOG = None


class UpdateError(Exception):
    """사용자에게 보여 줄 쉬운 이유가 있는 실패."""


# ---------------------------------------------------------------- 공통(본체 쪽 app/core/update.py · 만들기 도구도 씀)
def parse_version(v):
    m = VER_RE.fullmatch(str(v or ""))
    if not m:
        raise UpdateError(f"판 번호 모양이 이상해요: {str(v)[:20]}")
    return tuple(int(x) for x in m.groups())


def newer(a, b):
    """a 가 b 보다 새 판인지."""
    return parse_version(a) > parse_version(b)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_version_file(src):
    """<src>/app/version.py 의 VERSION = "x.y.z" (불러오지 않고 글로 읽음)."""
    try:
        with open(os.path.join(src, "app", "version.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([0-9.]+)"', f.read(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def _safe_rel(name):
    """꾸러미 안 이름 → 안전한 상대 경로(아니면 None): 절대 경로·..·드라이브·이상한 글자 막음."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name or "\x00" in name:
        return None
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts) or any(p.endswith((" ", ".")) for p in parts):
        return None
    return name


def extract_package(zpath, dest):
    """업데이트 꾸러미를 dest 에 푼다(src/ 아래만, 목록에 있는 파일만, 크기 한도). → 목록(dict)."""
    if os.path.exists(dest):
        rmtree(dest)
    os.makedirs(dest)
    with zipfile.ZipFile(zpath) as z:
        try:
            idx = json.loads(z.read(PKG_INDEX).decode("utf-8"))
        except (KeyError, ValueError) as ex:
            raise UpdateError("업데이트 꾸러미 안에 파일 목록이 없어요.") from ex
        files = idx.get("files") if isinstance(idx, dict) else None
        if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
            raise UpdateError("업데이트 꾸러미의 파일 목록이 이상해요.")
        total = 0
        seen = set()
        for info in z.infolist():
            n = info.filename
            if n == PKG_INDEX or n.endswith("/"):
                continue
            if info.flag_bits & 0x1:
                raise UpdateError("업데이트 꾸러미에 암호 걸린 파일이 있어요.")
            if not n.startswith(PKG_ROOT):
                raise UpdateError("업데이트 꾸러미에 이상한 파일이 있어요: " + n[:80])
            rel = _safe_rel(n[len(PKG_ROOT):])
            if rel is None or rel not in files:
                raise UpdateError("업데이트 꾸러미에 목록에 없는 파일이 있어요: " + n[:80])
            if rel in seen:
                raise UpdateError("업데이트 꾸러미에 같은 파일이 두 번 있어요: " + rel[:80])
            seen.add(rel)
            total += info.file_size
            if total > MAX_TOTAL:
                raise UpdateError("업데이트 꾸러미가 너무 커요.")
            out = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(info) as s, open(out, "wb") as f:
                shutil.copyfileobj(s, f, 1 << 20)
        if seen != set(files):
            raise UpdateError("업데이트 꾸러미에 빠진 파일이 있어요.")
    verify_tree(dest, idx)
    return idx


def verify_tree(root, idx):
    """root 안 파일이 목록과 정확히 같은지(빠짐·더 있음·sha256·크기). 판 번호·꼭 있어야 할 파일도."""
    files = idx["files"]
    found = set()
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d != "__pycache__"]
        for f in fs:
            rel = os.path.relpath(os.path.join(r, f), root).replace("\\", "/")
            if f.endswith(".pyc"):
                continue
            found.add(rel)
    if found != set(files):
        extra = sorted(found - set(files))[:3]
        miss = sorted(set(files) - found)[:3]
        raise UpdateError(f"새 판 파일이 목록과 달라요(더 있음 {extra} · 빠짐 {miss}).")
    for rel, meta in files.items():
        p = os.path.join(root, *rel.split("/"))
        if os.path.getsize(p) != int(meta.get("size", -1)) or sha256_file(p) != str(meta.get("sha256", "")):
            raise UpdateError("새 판 파일이 원본과 달라요: " + rel)
    for m in MUST_HAVE:
        if m not in files:
            raise UpdateError("새 판에 꼭 있어야 할 파일이 없어요: " + m)
    if read_version_file(root) != idx.get("version"):
        raise UpdateError("새 판의 판 번호가 목록과 달라요.")


def deps_of(src):
    out = {}
    for d in DEPS:
        p = os.path.join(src, *d.split("/"))
        out[d] = sha256_file(p) if os.path.isfile(p) else ""
    return out


def rmtree(path):
    if os.path.isdir(path):
        def onerr(f, p, _e):
            try:
                os.chmod(p, 0o666)
                f(p)
            except OSError:
                pass
        shutil.rmtree(path, onerror=onerr)


# ---------------------------------------------------------------- 기록·설정
def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    if LOG:
        try:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def data_dir(settings):
    s = read_json(settings, {}) or {}
    d = ((s.get("경로") or {}).get("자료")) if isinstance(s, dict) else None
    return os.path.abspath(os.path.expandvars(d)) if d else os.path.dirname(os.path.abspath(settings))


def body_port(src, settings):
    s = read_json(settings, {}) or {}
    p = ((s.get("포트") or {}).get("본체")) if isinstance(s, dict) else None
    if not p:
        p = ((read_json(os.path.join(src, "app", "config", "default.json"), {}) or {}).get("포트") or {}).get("본체")
    return int(p or 8870)


# ---------------------------------------------------------------- 프로세스(기록된 것만)
def _k32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def proc_info(pid):
    """→ (실행 파일, 시작 시각) 또는 None — app/launcher.py 의 proc_info 와 같은 값."""
    if sys.platform != "win32" or not pid:
        return None
    import ctypes
    from ctypes import wintypes
    k = _k32()
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        exe = buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
        ft = [wintypes.FILETIME() for _ in range(4)]
        ok = k.GetProcessTimes(h, *[ctypes.byref(x) for x in ft])
        return exe, ((ft[0].dwHighDateTime << 32 | ft[0].dwLowDateTime) if ok else 0)
    finally:
        k.CloseHandle(h)


def alive(pid):
    return proc_info(pid) is not None


def same_proc(rec):
    info = proc_info((rec or {}).get("pid"))
    return bool(info) and os.path.normcase(info[0]) == os.path.normcase(rec.get("exe", "")) and info[1] == rec.get("created")


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


def stop_kimbiseo(data, prefix, body_pid):
    """실행기 기록(<자료>/run/launcher.json)의 PID 만 끔(실행 파일·시작 시각이 같을 때만). 본체 PID 는 실행 파일이 설치 폴더 안일 때만."""
    run = read_json(os.path.join(data, "run", "launcher.json"), {}) or {}
    recs = [("실행기", run.get("launcher") or {})] + list((run.get("services") or {}).items())
    pids = []
    for name, rec in recs:
        if rec and same_proc(rec):
            log(f"끔: {name} PID {rec['pid']}")
            kill_tree(rec["pid"])
            pids.append(int(rec["pid"]))
    if body_pid and alive(body_pid):
        info = proc_info(body_pid)
        if info and os.path.normcase(os.path.abspath(info[0])).startswith(os.path.normcase(os.path.abspath(prefix)) + os.sep):
            log(f"끔: 본체 PID {body_pid}")
            kill_tree(body_pid)
            pids.append(int(body_pid))
    t0 = time.time()
    while time.time() - t0 < 30 and any(alive(p) for p in pids):
        time.sleep(0.5)
    left = [p for p in pids if alive(p)]
    if left:
        raise UpdateError(f"김비서가 꺼지지 않았어요(PID {left}). PC 를 다시 켠 뒤 다시 해 주세요.")
    try:
        os.remove(os.path.join(data, "run", "launcher.json"))
    except OSError:
        pass


# ---------------------------------------------------------------- 바꿔 끼우기·검사
def move_retry(a, b, tries=40):
    last = None
    for _ in range(tries):
        try:
            os.replace(a, b)
            return
        except OSError as ex:      # 방금 끈 프로그램이 아직 파일을 쥐고 있으면 잠깐 기다림
            last = ex
            time.sleep(0.75)
    raise UpdateError(f"폴더를 바꾸지 못했어요({type(last).__name__}). 다른 프로그램(백신 등)이 김비서 파일을 쓰고 있을 수 있어요.")


def env_for_child():
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    for k in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    return env


def health_check(prefix, src, settings, data, wait_s=180):
    """새 판 검사: ① 파이썬 파일 문법 ② 본체·실행기 불러오기 ③ 본체를 실제로 켜서 /api/status 200 → 끔. 실패하면 UpdateError."""
    py = os.path.join(prefix, "runtime", "python-app", "python.exe")
    if not os.path.isfile(py):
        raise UpdateError("본체 파이썬이 없어요.")
    bad = []
    for r, ds, fs in os.walk(src):
        ds[:] = [d for d in ds if d != "__pycache__"]
        for f in fs:
            if f.endswith(".py"):
                p = os.path.join(r, f)
                try:
                    with open(p, "rb") as fh:
                        compile(fh.read(), p, "exec", dont_inherit=True)
                except (SyntaxError, ValueError) as ex:
                    bad.append(f"{os.path.relpath(p, src)}: {ex}")
    if bad:
        raise UpdateError("새 판 파이썬 파일에 문법 오류가 있어요: " + bad[0][:200])
    log("검사 ① 문법 됨")
    r = subprocess.run([py, "-B", "-X", "utf8", "-c", "import app.version, app.core.update, app.launcher, app.main"], cwd=src,
                       capture_output=True, creationflags=NO_WINDOW, env=env_for_child(), timeout=180)
    if r.returncode != 0:
        raise UpdateError("새 판 본체를 불러오지 못했어요: " + r.stderr.decode("utf-8", "replace").strip().splitlines()[-1][:200]
                          if r.stderr.strip() else "새 판 본체를 불러오지 못했어요.")
    log("검사 ② 불러오기 됨")
    port = body_port(src, settings)
    t0 = time.time()
    while _port_busy(port) and time.time() - t0 < 30:
        time.sleep(0.5)
    if _port_busy(port):
        raise UpdateError(f"본체 자리(포트 {port})를 다른 프로그램이 쓰고 있어 새 판을 시험하지 못했어요.")
    out = open(os.path.join(data, "logs", "update_body_check.log"), "ab")
    p = subprocess.Popen([py, "-B", "-X", "utf8", "-m", "app.main", "serve", "--settings", settings, "--parent_pid", str(os.getpid())],
                         cwd=src, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env_for_child(),
                         creationflags=NO_WINDOW | NEW_GROUP)
    out.close()
    try:
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if p.poll() is not None:
                raise UpdateError(f"새 판 본체가 켜지다가 꺼졌어요(코드 {p.returncode}). 기록: logs/update_body_check.log")
            if _http_ok(f"http://127.0.0.1:{port}/api/status"):
                log(f"검사 ③ 새 판 본체가 켜짐({time.time() - t0:.1f}초)")
                return True
            time.sleep(0.5)
        raise UpdateError(f"새 판 본체가 {wait_s}초 안에 켜지지 않았어요.")
    finally:
        _shutdown_body(p, port, data)


def _port_busy(port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def _http_ok(url, timeout=2.0):
    try:
        req = urllib.request.Request(url, headers={"Host": url.split("/")[2]})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:  # noqa: BLE001
        return False


def _shutdown_body(p, port, data):
    if p.poll() is None:
        try:
            sec = open(os.path.join(data, "secrets", "shutdown_secret.txt"), encoding="utf-8").read().strip()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}", "X-KimBiseo-Shutdown": sec})
            urllib.request.urlopen(req, timeout=3).read()
            p.wait(timeout=8)
        except Exception:  # noqa: BLE001
            pass
    if p.poll() is None:
        kill_tree(p.pid)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def relaunch(prefix, src, settings):
    pyw = os.path.join(prefix, "runtime", "python-app", "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = os.path.join(prefix, "runtime", "python-app", "python.exe")
    p = _spawn([pyw, "-B", "-X", "utf8", "-m", "app.launcher", "--settings", settings], src)
    log(f"김비서 다시 켬: 실행기 PID {p.pid}")
    return p


def _spawn(cmd, cwd):
    flags = DETACHED | NEW_GROUP
    try:
        return subprocess.Popen(cmd, cwd=cwd, env=env_for_child(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=flags | BREAKAWAY, close_fds=True)
    except OSError:        # 작업 개체가 떼어 내기를 막으면 그냥
        return subprocess.Popen(cmd, cwd=cwd, env=env_for_child(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def set_installed_version(prefix, version):
    sp = os.path.join(prefix, "install", "state.json")
    st = read_json(sp, {}) or {}
    st["version"] = version
    st["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(sp, st)
    if st.get("reg_key") and sys.platform == "win32":
        try:
            import winreg
            key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{st['reg_key']}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
                loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                if os.path.normcase(os.path.abspath(loc)) == os.path.normcase(os.path.abspath(prefix)):
                    winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
        except OSError as ex:
            log("앱 목록 판 번호 못 고침:", ex)


# ---------------------------------------------------------------- 돌리기
def do_run(a):
    global LOG
    prefix = os.path.abspath(a.prefix)
    src = os.path.join(prefix, "src")
    upd = os.path.join(prefix, "install", "update")
    settings = os.path.abspath(a.settings)
    data = data_dir(settings)
    LOG = os.path.join(data, "logs", "update.log")
    result_p = os.path.join(data, "update", "result.json")
    time.sleep(1.5)      # 띄운 쪽(spawn)이 먼저 끝나게 — 그래야 본체를 끌 때 이 일꾼이 같이 꺼지지 않음
    ready = read_json(os.path.join(upd, "ready.json"), {}) or {}
    old_v = read_version_file(src) or "?"
    new_v = a.version
    staged = os.path.join(upd, "staged")
    prev = os.path.join(upd, "previous")
    res = {"ok": False, "from": old_v, "to": new_v, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "rolled_back": False, "why": ""}
    log(f"==== 업데이트 {old_v} → {new_v} (일꾼 PID {os.getpid()}) 설치 {prefix}")
    swapped = False
    try:
        if ready.get("version") != new_v or not os.path.isdir(staged):
            raise UpdateError("받아 둔 새 판이 없어요. '업데이트 확인'부터 다시 해 주세요.")
        if not newer(new_v, old_v):
            raise UpdateError(f"지금 판({old_v})보다 새 판이 아니에요.")
        idx = read_json(os.path.join(upd, "staged_index.json"))
        if not idx or idx.get("version") != new_v:
            raise UpdateError("받아 둔 새 판의 파일 목록이 없어요.")
        stop_kimbiseo(data, prefix, a.body_pid)
        log("김비서 끔")
        verify_tree(staged, idx)          # 바꾸기 바로 앞에서 한 번 더(받아 둔 뒤 바뀌지 않았는지)
        log("새 판 파일 다시 확인 됨", len(idx["files"]), "개")
        if os.path.exists(prev):
            rmtree(prev)
        move_retry(src, prev)
        try:
            move_retry(staged, src)
        except UpdateError:
            move_retry(prev, src)
            raise
        swapped = True
        log("src 바꿔 끼움(예전 판 = install/update/previous)")
        health_check(prefix, src, settings, data)
        set_installed_version(prefix, new_v)
        res.update({"ok": True, "why": ""})
        log(f"업데이트 됨: {new_v}")
    except Exception as ex:  # noqa: BLE001
        why = str(ex) if isinstance(ex, UpdateError) else f"생각하지 못한 문제({type(ex).__name__}: {ex})"
        res["why"] = why[:400]
        log("!!!! 실패:", why)
        if swapped:
            rollback(prefix, src, prev, upd, new_v)
            res["rolled_back"] = True
            log(f"예전 판({old_v})으로 되돌림")
    if swapped:      # 받아 둔 표시는 다 썼음(성공이면 src 로 들어갔고, 실패면 failed_ 로 감)
        for f in ("ready.json", "staged_index.json"):
            try:
                os.remove(os.path.join(upd, f))
            except OSError:
                pass
    write_json(result_p, res)
    if a.no_relaunch:
        return 0 if res["ok"] else 1
    p = relaunch(prefix, src, settings)
    if res["ok"]:
        watch_after(p, prefix, src, prev, upd, settings, data, res, result_p)
    log("==== 업데이트 일꾼 끝")
    return 0 if res["ok"] else 1


def rollback(prefix, src, prev, upd, new_v):
    failed = os.path.join(upd, f"failed_{new_v}_{time.strftime('%Y%m%d_%H%M%S')}")
    move_retry(src, failed)
    move_retry(prev, src)
    olds = sorted(d for d in os.listdir(upd) if d.startswith("failed_") and d != os.path.basename(failed))
    for d in olds:      # 실패한 판은 가장 최근 것 하나만 남김(살펴보기용)
        rmtree(os.path.join(upd, d))


def watch_after(p, prefix, src, prev, upd, settings, data, res, result_p, limit_s=900):
    """다시 켠 뒤: 본체가 준비되면 끝. 그 전에 실행기가 오류(코드 0 아님)로 꺼지면 예전 판으로 되돌리고 다시 켬."""
    port = body_port(src, settings)
    t0 = time.time()
    while time.time() - t0 < limit_s:
        if _http_ok(f"http://127.0.0.1:{port}/api/status"):
            log(f"다시 켠 새 판 본체 준비됨({time.time() - t0:.0f}초)")
            return
        rc = p.poll()
        if rc is not None:
            if rc == 0:
                log("실행기가 정상으로 끝남(창을 닫음) — 되돌리지 않음")
                return
            log(f"!!!! 다시 켠 실행기가 오류로 꺼짐(코드 {rc}) → 예전 판으로 되돌림")
            try:
                stop_kimbiseo(data, prefix, 0)
                rollback(prefix, src, prev, upd, res["to"])
                set_installed_version(prefix, res["from"])
                res.update({"ok": False, "rolled_back": True, "why": f"새 판을 켜자 김비서가 꺼졌어요(코드 {rc}). 예전 판으로 되돌렸어요."})
            except UpdateError as ex:
                res.update({"ok": False, "why": f"새 판이 켜지지 않았고 되돌리기도 못 했어요: {ex}"})
            write_json(result_p, res)
            relaunch(prefix, src, settings)
            return
        time.sleep(1.0)
    log("다시 켠 뒤 본체 준비를 기다리다 그만 봄(실행기는 켜져 있음)")


def do_spawn(a):
    me = os.path.abspath(sys.argv[0])
    cmd = [sys.executable, "-B", "-X", "utf8", me, "run", "--prefix", a.prefix, "--settings", a.settings, "--version", a.version,
           "--body-pid", str(a.body_pid)] + (["--no-relaunch"] if a.no_relaunch else [])
    p = _spawn(cmd, os.path.dirname(me))
    print(json.dumps({"ok": True, "pid": p.pid}), flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kimbiseo-updater")
    ap.add_argument("cmd", choices=["spawn", "run"])
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--settings", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--body-pid", type=int, default=0)
    ap.add_argument("--no-relaunch", action="store_true", help="시험용: 다시 켜지 않음")
    a = ap.parse_args(argv)
    parse_version(a.version)
    return do_spawn(a) if a.cmd == "spawn" else do_run(a)


if __name__ == "__main__":
    sys.exit(main())
