# 김비서 설치 본체 — 설치 창(install.ps1)이 부른다. 파이썬 표준 라이브러리만(설치 때 막 받은 파이썬으로 돎).
#   python setup_core.py install --prefix <프로그램 폴더> --data <자료 폴더> --status <상태 파일> [--source <소스 폴더>]
#                                [--local-brain] [--desktop-dir 폴더] [--startmenu-dir 폴더] [--reg-key KimBiseo]
#                                [--display-name 김비서] [--packs-catalog 주소] [--no-shortcuts] [--no-register]
#   python setup_core.py plan [--prefix …] [--local-brain]      구성만 보기(JSON)
#   python setup_core.py gemma-install --prefix … --data … --status <상태 파일> [--gemma E4B|E2B]   설정 '두뇌 바꾸기 → Gemma 설치·다시 설치'
#       (두뇌 프로그램 llama.cpp + 고른 Gemma 4 무검열 판(E4B 기본 약 5.3GB · E2B 약 3.4GB)만 받음. 다 받으면 다른 Gemma 폴더는 지워 공간을 돌려줌)
#   install 에도 --gemma E2B 를 주면 이 PC 두뇌를 작은 판으로 받음(기본 E4B)
#   python setup_core.py gemma-remove --prefix … --data …     Gemma·두뇌 프로그램 지우기(지운 크기 JSON 으로)
# 0.1.4~ 두뇌: 이 PC 에 클로드 코드·Codex 로그인이 있으면 Gemma 를 받지 않음(plan.py). 업데이트(덮어 설치) 때
#   이미 있는 Gemma·두뇌 프로그램은 지우지 않고, 설정의 두뇌 경로는 디스크에 실제 있는 파일로 맞춘다.
#
# 차례(이미 된 것은 건너뜀 — '다시 하기'를 누르면 멈춘 곳부터):
#   python(설치 창이 먼저 함) → 사양 확인 → 프로그램 파일 → 파이썬 부품(본체·음성) → 두뇌 프로그램 → 모델 → 펫 → 바탕화면 아이콘·마무리
# 받는 것은 모두 공식 배포처(파이썬 = python.org, 부품 = PyPI·PyTorch, llama.cpp·Electron = GitHub 릴리스, 모델 = 허깅페이스)에서
# 사용자 PC 가 직접 받고, 판 고정 + sha256 으로 확인한다(runtimes.json · locks/*.json · models.json). 우리는 아무것도 다시 나눠 주지 않는다.
# 상태 파일(JSON)은 설치 창이 0.5초마다 읽어 화면에 보여 줌. 기록은 <자료>\logs\install.log.
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import get_models as GM  # noqa: E402
import plan as PLAN  # noqa: E402

def _read_version():
    import re
    try:
        with open(os.path.join(SRC_ROOT, "app", "version.py"), encoding="utf-8") as f:
            return re.search(r'^VERSION\s*=\s*"([0-9.]+)"', f.read(), re.M).group(1)
    except (OSError, AttributeError):
        return "0.0.0"


VERSION = _read_version()   # 판 번호는 app/version.py 한 곳
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STEPS = [("python", "파이썬 준비"), ("plan", "이 PC 사양 확인"), ("files", "프로그램 파일"), ("packages", "파이썬 부품"),
         ("brain", "두뇌 프로그램"), ("models", "모델(두뇌·귀·목소리)"), ("pet", "펫"), ("finish", "바탕화면 아이콘·마무리")]
WEIGHT = {"python": 2, "plan": 1, "files": 1, "packages": 30, "brain": 6, "models": 45, "pet": 8, "finish": 2}
COPY_ITEMS = ["app", "voice", "pet", "installer", "brain", "assets", "LICENSE", "NOTICE", "README.md", "ASSETS-LICENSE.md", "PRIVACY.md",
              "SECURITY.md", "THIRD_PARTY_LICENSES"]
SKIP_NAMES = {"__pycache__", ".git", "node_modules", ".pytest_cache"}


class Fail(Exception):
    """사용자에게 보여 줄 쉬운 이유가 있는 실패."""

    def __init__(self, why, detail=""):
        super().__init__(why)
        self.why = why
        self.detail = detail


# ---------------------------------------------------------------- 상태·기록
class Status:
    def __init__(self, path, log_path):
        self.path = path
        self.log_path = log_path
        self.d = None
        try:
            with open(path, encoding="utf-8-sig") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            pass
        if not isinstance(self.d, dict) or [s.get("id") for s in self.d.get("단계", [])] != [s[0] for s in STEPS]:
            self.d = {"단계": [{"id": i, "이름": n, "상태": "기다림", "글": ""} for i, n in STEPS]}
        self.d.update({"끝": False, "성공": False, "오류": None, "지금": "", "글": "", "진행": 0, "전체": 0})
        self.cur = None
        self._last = 0

    def log(self, *a):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass

    def step(self, sid):
        return next(s for s in self.d["단계"] if s["id"] == sid)

    def begin(self, sid):
        self.cur = sid
        st = self.step(sid)
        st["상태"], st["글"] = "하는 중", ""
        self.d["지금"] = sid
        self.d["진행"] = 0
        self.log(f"==== {st['이름']}")
        self.write(force=True)

    def end(self, sid, state="됨", text=""):
        st = self.step(sid)
        st["상태"], st["글"] = state, text
        self.d["진행"] = 100
        self.log(f"---- {st['이름']}: {state} {text}")
        self.write(force=True)

    def progress(self, frac, text=""):
        self.d["진행"] = max(0, min(100, round(frac * 100, 1)))
        if text:
            self.d["글"] = text
        self.write()

    def say(self, text):
        self.d["글"] = text
        self.log("  " + text)
        self.write()

    def total(self):
        done = sum(WEIGHT[s["id"]] for s in self.d["단계"] if s["상태"] in ("됨", "건너뜀"))
        cur = WEIGHT.get(self.cur, 0) * self.d.get("진행", 0) / 100 if self.cur and self.step(self.cur)["상태"] == "하는 중" else 0
        return round(100 * (done + cur) / sum(WEIGHT.values()), 1)

    def write(self, force=False):
        if not force and time.time() - self._last < 0.4:
            return
        self._last = time.time()
        self.d["전체"] = self.total()
        self.d["시각"] = time.strftime("%H:%M:%S")
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=0)
            for _ in range(20):   # 설치 창이 읽는 중이면 잠깐 기다렸다가
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    time.sleep(0.05)
        except OSError:
            pass


def human(n):
    return GM.human(n)


def sha256_of(path, progress=None):
    return GM.file_hashes(path, progress=progress)[0]


# ---------------------------------------------------------------- 받기 공통
def head(url, hosts):
    """시험(--dry-run): 받지 않고 크기만 물음(넘겨주기도 허용 호스트만). → (최종 주소, 크기|None)"""
    import urllib.request
    opener = urllib.request.build_opener(GM._redirect_for(hosts))
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": GM.UA})
    with opener.open(req, timeout=30) as r:
        n = r.headers.get("X-Linked-Size") or r.headers.get("Content-Length") or ""
        return r.geturl(), (int(n) if n.isdigit() else None)


class Fetcher:
    def __init__(self, st, hosts, dry=False):
        self.st = st
        self.hosts = tuple(hosts)
        self.dry = dry
        self.checked = []

    def get(self, url, dest, sha256, size=None, label="", frac=(0.0, 1.0)):
        """dest 가 이미 맞으면 건너뜀. 아니면 받고(이어 받기·다시 시도) sha256 확인. 틀리면 지우고 Fail."""
        a, b = frac
        name = label or os.path.basename(dest)
        if self.dry:
            if not GM.host_ok(url, self.hosts):
                raise Fail(f"{name}: 허용하지 않은 주소", url)
            if not (isinstance(sha256, str) and len(sha256) == 64):
                raise Fail(f"{name}: sha256 이 없어요", url)
            try:
                final, n = head(url, self.hosts)
            except Exception as ex:  # noqa: BLE001
                raise Fail(f"{name}: 주소 확인 실패", f"{url} {ex}") from None
            if size is not None and n is not None and n != size:
                raise Fail(f"{name}: 크기가 목록과 달라요({n} ≠ {size})", url)
            self.checked.append({"이름": name, "주소": url, "크기": n, "목록_크기": size})
            self.st.progress(b, f"[시험] {name} 주소 확인 {human(n or 0)}")
            return dest
        if os.path.isfile(dest) and (size is None or os.path.getsize(dest) == size):
            if sha256_of(dest) == sha256:
                self.st.progress(b, f"{name} — 있음(확인됨)")
                return dest
            os.remove(dest)

        def prog(done, total, rate):
            t = total or size or 0
            f = (done / t) if t else 0
            self.st.progress(a + (b - a) * f, f"{name} 받는 중 {human(done)} / {human(t)}" + (f" · {human(rate)}/초" if rate else ""))
        try:
            GM.download(url, dest, size, say=lambda m: self.st.log(m), progress=prog, hosts=self.hosts)
        except RuntimeError as ex:
            raise Fail(f"{name} 을(를) 받지 못했어요. 인터넷 연결을 확인하고 '다시 하기'를 눌러 주세요(받은 만큼은 이어서 받아요).", str(ex)) from None
        got = sha256_of(dest)
        if got != sha256:
            os.replace(dest, dest + ".bad")
            raise Fail(f"받은 {name} 이(가) 원본과 달라요(내려받다 깨졌을 수 있어요). '다시 하기'를 누르면 새로 받아요.",
                       f"sha256 {got} ≠ {sha256}")
        return dest


def extract_zip(zpath, dest, strip_single_root=False):
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        root = ""
        if strip_single_root:
            tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
            if len(tops) == 1 and all("/" in n for n in names if n.strip("/")):
                root = tops.pop() + "/"
        dest_abs = os.path.abspath(dest)
        for n in names:
            rel = n[len(root):] if root and n.startswith(root) else n
            if not rel or rel.endswith("/"):
                continue
            out = os.path.abspath(os.path.join(dest, *rel.split("/")))
            if not (out == dest_abs or out.startswith(dest_abs + os.sep)):
                raise Fail("압축 파일 안에 이상한 경로가 있어요.", n)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(n) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f, 1024 * 1024)


def dir_size(path):
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def rmtree(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=False, onerror=lambda f, p, e: (os.chmod(p, 0o666), f(p)))


# ---------------------------------------------------------------- 설치
class Installer:
    def __init__(self, a):
        self.a = a
        self.P = os.path.abspath(a.prefix)
        self.D = os.path.abspath(a.data)
        self.src = os.path.abspath(a.source or SRC_ROOT)
        self.st = Status(os.path.abspath(a.status), os.path.join(self.D, "logs", "install.log"))
        with open(os.path.join(HERE, "runtimes.json"), encoding="utf-8") as f:
            self.rt = json.load(f)
        self.dry = bool(getattr(a, "dry_run", False))
        self.fetch = Fetcher(self.st, self.rt["hosts"], self.dry)
        self.dl = os.path.join(self.P, "install", "downloads")
        self.wheels = os.path.join(self.P, "install", "wheels")
        self.state_path = os.path.join(self.P, "install", "state.json")
        self.state = self._load_state()
        self.plan = None
        self.bm = PLAN.brain_model(getattr(a, "gemma", None))   # 받을 Gemma 판(models.json 이름)

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(self.state_path + ".tmp", self.state_path)

    def path(self, *p):
        return os.path.join(self.P, *p)

    # ---- 1. 사양
    def current_settings(self):
        try:
            with open(self.settings_file(), encoding="utf-8-sig") as f:
                cur = json.load(f)
            return cur if isinstance(cur, dict) else {}
        except (OSError, ValueError):
            return {}

    def gemma_dirs(self):
        """설치 폴더 models 안의 Gemma 폴더 이름들(새 무검열 판 먼저)."""
        root = self.path("models")
        try:
            names = [n for n in os.listdir(root) if n.lower().startswith("gemma-") and os.path.isdir(os.path.join(root, n))]
        except OSError:
            return []
        return sorted(names, key=lambda n: (n != self.bm, n != PLAN.BRAIN_MODEL, n))

    def gemma_file(self):
        """디스크에 다 받아진 Gemma gguf 경로(없으면 '') — 무검열 판이 있으면 그것."""
        try:
            mf = GM.load_manifest(os.path.join(HERE, "models.json"))
        except (OSError, ValueError, SystemExit):
            mf = {}
        for n in self.gemma_dirs():
            m = mf.get(n)
            files = [f["path"] for f in (m or {}).get("files", []) if f["path"].endswith(".gguf")]
            for fp in files:
                full = os.path.join(self.path("models", n), *fp.split("/"))
                want = next((f["size"] for f in m["files"] if f["path"] == fp), None)
                if os.path.isfile(full) and (not want or os.path.getsize(full) == want):
                    return full
        return ""

    def do_plan(self):
        self.st.say("그래픽카드·메모리·디스크·구독 두뇌 로그인을 살펴보는 중이에요.")
        cur = self.current_settings()
        again = bool((cur.get("처음설정") or {}).get("끝"))
        uses_local = again and str((cur.get("두뇌") or {}).get("방식") or "local") == "local"
        # 이미 '내 PC(Gemma)'로 쓰는 사람의 업데이트는 두뇌를 바꾸지 않음(구독 로그인이 있어도) — 바꾸는 건 설정에서
        self.plan = PLAN.detect(self.P, self.a.local_brain or uses_local, cli=not uses_local, gemma=self.a.gemma)
        p = self.plan
        if uses_local:
            p["판별"].append("두뇌: 이미 '내 PC(Gemma)'로 쓰는 중 → 업데이트에서 바꾸지 않음")
            bm = p["두뇌_모델"]
            old = [n for n in self.gemma_dirs() if n != bm]
            if bm in p["모델"] and bm not in self.gemma_dirs() and old:
                p["모델"] = [old[0] if n == bm else n for n in p["모델"]]
                p["판별"].append(f"두뇌: 옛 Gemma({old[0]}) 그대로 씀 — 무검열 판은 설정 '두뇌 바꾸기 → Gemma 다시 설치'로(5GB 받기)")
        g = p.get("그래픽카드")
        self.st.log("사양:", json.dumps({k: p[k] for k in ("구성", "그래픽카드", "다른_그래픽카드", "램_GB", "디스크_여유_GB", "드라이버", "torch",
                                                     "llama", "모델", "필요_디스크_GB", "구독", "두뇌_제안")}, ensure_ascii=False))
        for line in p.get("판별") or []:
            self.st.log("판별:", line)
        self.st.d["구성"] = {"이름": p["구성"], "그래픽카드": (g or {}).get("이름") or "엔비디아 그래픽카드 없음",
                           "그래픽_GB": round((g or {}).get("전체_MiB", 0) / 1024, 1), "램_GB": p["램_GB"], "디스크_여유_GB": p["디스크_여유_GB"],
                           "필요_GB": p["필요_디스크_GB"], "안내": p["안내"], "경고": p["경고"], "모델": p["모델"],
                           "두뇌": {"claude_cli": "클로드 코드(구독)", "codex_cli": "GPT·Codex(구독)"}.get(p.get("두뇌_제안") or "")
                           or (f"이 PC(Gemma · {p['llama']})" if p["llama"] else "바깥 AI"), "판별": p.get("판별") or []}
        if p.get("디스크_모자람"):
            raise Fail(f"디스크 공간이 모자라요. 약 {p['필요_디스크_GB']}GB 가 필요한데 {p['디스크_여유_GB']}GB 남았어요. "
                       "공간을 비우거나 다른 드라이브에 설치해 주세요.")
        self.state["plan"] = {k: p[k] for k in ("구성", "torch", "llama", "모델", "설정")}
        return p["구성"] + (" · 두뇌 = " + self.st.d["구성"]["두뇌"])

    # ---- 2. 프로그램 파일
    def do_files(self):
        dst = self.path("src")
        if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(self.src):
            return "건너뜀", "설치 폴더에서 다시 실행 — 복사 안 함"
        os.makedirs(dst, exist_ok=True)
        items = [x for x in COPY_ITEMS if os.path.exists(os.path.join(self.src, x))]
        for i, it in enumerate(items):
            s, d = os.path.join(self.src, it), os.path.join(dst, it)
            self.st.progress(i / len(items), f"복사: {it}")
            if os.path.isdir(s):
                rmtree(d)
                shutil.copytree(s, d, ignore=lambda _d, names: [n for n in names if n in SKIP_NAMES or n.endswith((".pyc", ".bak", ".part"))])
            else:
                shutil.copy2(s, d)
        self.state["files"] = {"from": self.src, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        return "됨", f"{len(items)}개"

    # ---- 3. 파이썬 부품
    def make_python(self, folder):
        """공식 embeddable 파이썬을 folder 에 풀고 pip 를 넣는다(이미 있으면 그대로)."""
        py = os.path.join(folder, "python.exe")
        mark = os.path.join(folder, "kimbiseo_python.txt")
        ver = self.rt["python"]["version"] + "+pip" + self.rt["pip"]["version"]
        if os.path.isfile(py) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == ver:
            return py
        r = self.rt["python"]
        z = self.fetch.get(r["url"], os.path.join(self.dl, os.path.basename(r["url"])), r["sha256"], r["size"], "파이썬")
        if self.dry:
            self.fetch.get(self.rt["pip"]["url"], "pip", self.rt["pip"]["sha256"], self.rt["pip"]["size"], "pip")
            return py
        rmtree(folder)
        extract_zip(z, folder)
        self._write_pth(folder)
        pip = self.rt["pip"]
        w = self.fetch.get(pip["url"], os.path.join(self.dl, os.path.basename(pip["url"])), pip["sha256"], pip["size"], "pip")
        extract_zip(w, os.path.join(folder, "Lib", "site-packages"))
        with open(mark, "w", encoding="utf-8") as f:
            f.write(ver)
        return py

    def _write_pth(self, folder):
        with open(os.path.join(folder, self.rt["python"]["pth"]), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(chr(10).join(["python311.zip", ".", os.path.join("Lib", "site-packages"), os.path.join("..", "..", "src"),
                               "# 김비서: 위 줄 = 설치 폴더의 src(본체 코드). 환경변수·레지스트리는 보지 않음", "import site", ""]))

    def pip(self, py, args, label, frac=(0.0, 1.0), count=0):
        cmd = [py, "-m", "pip", *args, "--disable-pip-version-check", "--no-warn-script-location", "--progress-bar", "off"]
        self.st.log("  $ " + " ".join(cmd[:6]) + " …")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PIP_NO_INPUT": "1", "PIP_CONFIG_FILE": os.devnull,
               "PIP_CACHE_DIR": self.path("install", "pipcache")}
        for k in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PYTHONPATH", "PYTHONHOME"):
            env.pop(k, None)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                             creationflags=NO_WINDOW, cwd=self.path("install"))
        seen, tail = 0, []
        a, b = frac
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            self.st.log("    " + line[:300])
            tail = (tail + [line])[-15:]
            if line.startswith(("Processing ", "Building wheel", "Installing collected")):
                seen += 1
                nm = line.split()[1] if line.startswith("Processing") else line
                self.st.progress(a + (b - a) * min(0.95, seen / max(1, count + 2)), f"{label}: {os.path.basename(nm)[:60]}")
        rc = p.wait()
        if rc != 0:
            raise Fail(f"{label} 설치에 실패했어요. '다시 하기'를 눌러 주세요. 계속되면 기록 파일을 보내 주세요.", " / ".join(tail[-6:]))

    def env_ready(self, name, py, lock_path, probe):
        mark = os.path.join(os.path.dirname(py), f"kimbiseo_{name}_lock.txt")
        want = sha256_of(lock_path)
        if os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == want:
            r = subprocess.run([py, "-B", "-c", probe], capture_output=True, creationflags=NO_WINDOW)
            if r.returncode == 0:
                return True, mark, want
            self.st.log(f"  {name}: 기록은 있는데 불러오기 시험 실패 → 다시 설치", r.stderr.decode("utf-8", "replace")[-300:])
        return False, mark, want

    def install_env(self, name, folder, lock_name, probe, frac):
        a, b = frac
        py = self.make_python(folder)
        lock_path = os.path.join(HERE, "locks", lock_name)
        if self.dry:
            with open(lock_path, encoding="utf-8") as f:
                pk = json.load(f)["packages"]
            for i, x in enumerate(pk):
                self.fetch.get(x["url"], x["file"], x["sha256"], None, f"{name} 부품 {x['name']}=={x['version']}",
                               (a + (b - a) * i / len(pk), a + (b - a) * (i + 1) / len(pk)))
            if any(x["sdist"] for x in pk):
                s_ = self.rt["setuptools"]
                self.fetch.get(s_["url"], "setuptools", s_["sha256"], s_["size"], "setuptools")
            return f"[시험] {len(pk)}개 주소 확인"
        ok, mark, want = self.env_ready(name, py, lock_path, probe)
        if ok:
            self.st.progress(b, f"{name}: 이미 설치됨")
            return "있음"
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
        pk = lock["packages"]
        os.makedirs(self.wheels, exist_ok=True)
        mid = a + (b - a) * 0.6
        for i, x in enumerate(pk):
            self.fetch.get(x["url"], os.path.join(self.wheels, x["file"]), x["sha256"], None,
                           f"{name} 부품 {i + 1}/{len(pk)} {x['name']}", (a + (mid - a) * i / len(pk), a + (mid - a) * (i + 1) / len(pk)))
        if any(x["sdist"] for x in pk):   # 소스판만 있는 작은 꾸러미 → setuptools 먼저(빌드 격리 없이 만듦)
            s = self.rt["setuptools"]
            w = self.fetch.get(s["url"], os.path.join(self.wheels, os.path.basename(s["url"])), s["sha256"], s["size"], "setuptools")
            self.pip(py, ["install", "--no-index", "--no-deps", w], f"{name} 준비(setuptools)")
        req = os.path.join(self.path("install"), f"req_{name}.txt")
        with open(req, "w", encoding="utf-8") as f:
            for x in pk:
                f.write(f"{x['name']}=={x['version']} --hash=sha256:{x['sha256']}\n")
        self.pip(py, ["install", "--no-index", "--find-links", self.wheels, "--no-deps", "--require-hashes", "--no-build-isolation",
                      "-r", req], f"{name} 부품 설치", (mid, b), len(pk))
        r = subprocess.run([py, "-B", "-c", probe], capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise Fail(f"{name} 부품을 설치했지만 불러오지 못했어요.", r.stderr.decode("utf-8", "replace")[-400:])
        with open(mark, "w", encoding="utf-8") as f:
            f.write(want)
        return f"{len(pk)}개"

    def do_packages(self):
        p = self.state["plan"]
        voice_lock = "voice-cuda.json" if p["torch"] == "cu128" else "voice-cpu.json"
        r1 = self.install_env("본체", self.path("runtime", "python-app"), "app.json",
                              "import pipecat, fastapi, uvicorn, webview, aiortc, av, onnxruntime, anthropic, openai", (0.0, 0.3))
        r2 = self.install_env("음성", self.path("runtime", "python-voice"), voice_lock,
                              "import torch, torchaudio, transformers, qwen_tts, soundfile, librosa", (0.3, 1.0))
        return "됨", f"본체 {r1} · 음성 {r2}({'엔비디아' if p['torch'] == 'cu128' else 'CPU'} 판)"

    # ---- 4. 두뇌 프로그램
    def do_brain(self):
        v = self.state["plan"]["llama"]
        dest = self.path("runtime", "llama")
        if not v:   # 있던 두뇌 프로그램은 지우지 않음(설정에서 Gemma 로 돌아갈 수 있게 — 지우기는 'Gemma 삭제')
            return "건너뜀", "두뇌 = 구독·바깥 AI(Gemma 안 받음)" + (" · 있던 두뇌 프로그램은 그대로" if os.path.isdir(dest) else "")
        ll = self.rt["llama_cpp"]
        mark = os.path.join(dest, "kimbiseo_llama.txt")
        tag = f"{ll['version']} {v}"
        if os.path.isfile(os.path.join(dest, "llama-server.exe")) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == tag:
            return "됨", f"이미 설치됨({tag})"
        files = ll["variants"][v]
        if self.dry:
            for f in files:
                self.fetch.get(f["url"], f["file"], f["sha256"], f["size"], f["file"])
            return "됨", f"[시험] {tag} 주소 확인"
        zs = []
        for i, f in enumerate(files):
            zs.append(self.fetch.get(f["url"], os.path.join(self.dl, f["file"]), f["sha256"], f["size"], f["file"],
                                     (0.9 * i / len(files), 0.9 * (i + 1) / len(files))))
        self.st.progress(0.92, "푸는 중")
        rmtree(dest)
        for z in zs:
            extract_zip(z, dest, strip_single_root=True)
        if not os.path.isfile(os.path.join(dest, "llama-server.exe")):
            raise Fail("두뇌 프로그램을 풀었는데 llama-server.exe 가 없어요.", ", ".join(os.listdir(dest))[:300])
        with open(mark, "w", encoding="utf-8") as f:
            f.write(tag)
        return "됨", tag

    # ---- 5. 모델
    def do_models(self):
        names = self.state["plan"]["모델"]
        mf = GM.load_manifest(os.path.join(HERE, "models.json"))
        root = self.path("models")
        total = sum(mf[n]["size_total"] for n in names)
        base = 0
        got_all = 0
        if self.dry:
            for n in names:
                m = mf[n]
                for f in m["files"]:
                    url = GM.base_url(m) + __import__("urllib.parse").parse.quote(f["path"])
                    self.fetch.get(url, f["path"], f.get("sha256") or "0" * 64, f["size"], f"{n}/{f['path']}")
            return "됨", f"[시험] {len(names)}개 · {human(total)} 주소 확인"
        for n in names:
            m = mf[n]

            def prog(done, tot, rate, what, _b=base, _n=n):
                self.st.progress((_b + done) / total, f"{_n} {'받는 중' if what == '받기' else '확인 중'} {human(done)} / {human(tot)}"
                                 + (f" · {human(rate)}/초" if rate else ""))
            self.st.say(f"{n} ({human(m['size_total'])}) — {m['role']}")
            ok, failed, got = GM.ensure_model(m, root, say=lambda x: self.st.log(x), progress=prog)
            got_all += got
            if not ok:
                raise Fail(f"모델 {n} 을(를) 받지 못했어요. 인터넷 연결을 확인하고 '다시 하기'를 눌러 주세요(받은 만큼은 이어서 받아요).",
                           ", ".join(failed))
            base += m["size_total"]
        return "됨", f"{len(names)}개 · 새로 받음 {human(got_all)}"

    # ---- 6. 펫
    def do_pet(self):
        e = self.rt["electron"]
        dest = self.path("runtime", "electron")
        mark = os.path.join(dest, "kimbiseo_electron.txt")
        if os.path.isfile(os.path.join(dest, "electron.exe")) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == e["version"]:
            return "됨", f"이미 설치됨(Electron {e['version']})"
        z = self.fetch.get(e["url"], os.path.join(self.dl, os.path.basename(e["url"])), e["sha256"], e["size"], "펫 실행 틀(Electron)", (0, 0.85))
        if self.dry:
            return "됨", f"[시험] Electron {e['version']} 주소 확인"
        self.st.progress(0.9, "푸는 중")
        rmtree(dest)
        extract_zip(z, dest)
        if not os.path.isfile(os.path.join(dest, "electron.exe")):
            raise Fail("펫 실행 틀을 풀었는데 electron.exe 가 없어요.")
        with open(mark, "w", encoding="utf-8") as f:
            f.write(e["version"])
        return "됨", f"Electron {e['version']}"

    # ---- 7. 마무리
    def settings_file(self):
        return os.path.join(self.D, "settings.json")

    def write_settings(self):
        p = self.settings_file()
        os.makedirs(self.D, exist_ok=True)
        try:
            with open(p, encoding="utf-8-sig") as f:
                cur = json.load(f)
            if not isinstance(cur, dict):
                cur = {}
        except (OSError, ValueError):
            cur = {}
        plan = self.state["plan"]
        first = not (cur.get("처음설정") or {}).get("끝")
        for k, v in plan["설정"].items():          # 사양 추천은 처음 설치(처음 화면 전)이고 사용자가 정하지 않은 것만
            sec, key = k.split(".", 1)
            if sec == "실행":
                continue
            if first and key not in (cur.get(sec) or {}):
                cur.setdefault(sec, {})[key] = v
        cur.setdefault("경로", {}).update({"자료": self.D, "모델": self.path("models"), "캐시": self.path("cache"),
                                           "로그": os.path.join(self.D, "logs")})
        run = cur.setdefault("실행", {})
        llama_exe = self.path("runtime", "llama", "llama-server.exe")
        prev = os.path.expandvars(str(run.get("두뇌_모델") or ""))   # 사용자가 고른 Gemma 판(E4B·E2B)이 디스크에 있으면 그대로
        keep = (not getattr(self.a, "gemma", None) and prev and os.path.isfile(prev)
                and os.path.normcase(os.path.abspath(prev)).startswith(os.path.normcase(self.path("models")) + os.sep))
        run.update({"앱_파이썬": self.path("runtime", "python-app", "python.exe"),
                    "음성_파이썬": self.path("runtime", "python-voice", "python.exe"),
                    "두뇌_실행파일": llama_exe if os.path.isfile(llama_exe) else "",     # 디스크에 실제 있는 것으로
                    "두뇌_모델": prev if keep else self.gemma_file(),
                    "펫_실행파일": self.path("runtime", "electron", "electron.exe"),
                    "펫_폴더": self.path("src", "pet")})
        if "실행.두뇌_장치" in plan["설정"] and (first or "두뇌_장치" not in run):
            run["두뇌_장치"] = plan["설정"]["실행.두뇌_장치"]
        if self.a.packs_catalog is not None and (self.a.packs_catalog or not (cur.get("펫") or {}).get("옷목록_주소")):
            cur.setdefault("펫", {})["옷목록_주소"] = self.a.packs_catalog
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
        return p

    def known_dir(self, csidl):
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        return buf.value

    def make_shortcut(self, lnk, target, args, workdir, icon, desc):
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:K_LNK);$s.TargetPath=$env:K_TGT;$s.Arguments=$env:K_ARGS;"
              "$s.WorkingDirectory=$env:K_WD;$s.IconLocation=$env:K_ICON;$s.Description=$env:K_DESC;$s.WindowStyle=1;$s.Save()")
        env = {**os.environ, "K_LNK": lnk, "K_TGT": target, "K_ARGS": args, "K_WD": workdir, "K_ICON": icon, "K_DESC": desc}
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps], env=env,
                           capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(lnk):
            raise Fail("바탕화면 아이콘을 만들지 못했어요.", r.stderr.decode("utf-8", "replace")[-300:])

    def do_finish(self):
        sp = self.write_settings()
        self.st.say("설정 파일: " + sp)
        if self.dry:
            self.state["dry_checked"] = len(self.fetch.checked)
            return "됨", f"[시험] 설정만 씀 · 아이콘·앱 목록은 만들지 않음 · 주소 {len(self.fetch.checked)}개 확인"
        pyw = self.path("runtime", "python-app", "pythonw.exe")
        icon = self.path("src", "pet", "renderer", "img", "icon.ico") + ",0"
        launch_args = f'-B -X utf8 -m app.launcher --settings "{sp}"'
        un_ps1 = self.path("src", "installer", "uninstall.ps1")
        un_args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{un_ps1}" -Prefix "{self.P}"'
        links = []
        if not self.a.no_shortcuts:
            desk = self.a.desktop_dir or self.known_dir(0x10)            # CSIDL_DESKTOPDIRECTORY
            menu = self.a.startmenu_dir or os.path.join(self.known_dir(0x02), "김비서")   # CSIDL_PROGRAMS
            name = self.a.display_name
            for lnk, tgt, args, desc in [(os.path.join(desk, f"{name}.lnk"), pyw, launch_args, "김비서 켜기"),
                                         (os.path.join(menu, f"{name}.lnk"), pyw, launch_args, "김비서 켜기"),
                                         (os.path.join(menu, f"{name} 제거.lnk"), "powershell.exe", un_args, "김비서 지우기")]:
                self.make_shortcut(lnk, tgt, args, self.path("src"), icon, desc)
                links.append(lnk)
            self.state["menu_dir"] = menu
        self.state["shortcuts"] = links
        if not self.a.no_register:
            self.register(un_args, icon)
        # 받는 동안만 쓴 것 치우기(다시 받을 수 있음)
        for d in (self.dl, self.wheels, self.path("install", "pipcache")):
            rmtree(d)
        for f in os.listdir(self.path("install")):
            if f.startswith("req_"):
                os.remove(self.path("install", f))
        return "됨", f"아이콘 {len(links)}개"

    def register(self, un_args, icon):
        import winreg
        key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{self.a.reg_key}"
        size_kb = 0
        for r, _ds, fs in os.walk(self.P):
            for f in fs:
                try:
                    size_kb += os.path.getsize(os.path.join(r, f)) // 1024
                except OSError:
                    pass
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            for n, v in [("DisplayName", self.a.display_name), ("DisplayVersion", VERSION), ("Publisher", "김비서 프로젝트"),
                         ("InstallLocation", self.P), ("DisplayIcon", icon.rsplit(",", 1)[0]),
                         ("UninstallString", f"powershell.exe {un_args}"), ("QuietUninstallString", f"powershell.exe {un_args} -Quiet"),
                         ("InstallDate", datetime.date.today().strftime("%Y%m%d"))]:
                winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
            for n, v in [("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", min(size_kb, 0x7FFFFFFF))]:
                winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, v)
        self.state["reg_key"] = self.a.reg_key

    # ---- 돌리기
    def run(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.state.update({"version": VERSION, "prefix": self.P, "data": self.D, "settings": self.settings_file(),
                           "display_name": self.a.display_name})
        py_step = self.st.step("python")
        if py_step["상태"] != "됨":
            py_step["상태"] = "됨" if os.path.isfile(self.path("runtime", "python-app", "python.exe")) else py_step["상태"]
        for sid, fn in [("plan", self.do_plan), ("files", self.do_files), ("packages", self.do_packages), ("brain", self.do_brain),
                        ("models", self.do_models), ("pet", self.do_pet), ("finish", self.do_finish)]:
            self.st.begin(sid)
            t0 = time.time()
            try:
                r = fn()
            except Fail as ex:
                return self.fail(sid, ex.why, ex.detail)
            except OSError as ex:
                why = ("디스크 공간이 모자라요. 공간을 비우고 '다시 하기'를 눌러 주세요." if getattr(ex, "errno", 0) == 28 or getattr(ex, "winerror", 0) == 112
                       else "파일을 쓰거나 지우지 못했어요(백신 프로그램이 막았거나 김비서가 켜져 있을 수 있어요). 김비서를 끄고 '다시 하기'를 눌러 주세요."
                       if isinstance(ex, PermissionError) or getattr(ex, "winerror", 0) in (5, 32) else
                       "파일을 다루다 문제가 생겼어요. '다시 하기'를 눌러 주세요.")
                return self.fail(sid, why, f"{type(ex).__name__}: {ex}")
            except Exception as ex:  # noqa: BLE001
                return self.fail(sid, "생각하지 못한 문제가 생겼어요. '다시 하기'를 눌러 주세요. 계속되면 기록 파일을 보내 주세요.",
                                 traceback.format_exc()[-800:])
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
            self.save_state()
        self.state["installed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": "설치가 끝났어요.", "설정": self.settings_file(),
                          "실행": {"파이썬": self.path("runtime", "python-app", "pythonw.exe"), "작업폴더": self.path("src"),
                                 "인자": ["-B", "-X", "utf8", "-m", "app.launcher", "--settings", self.settings_file()]}})
        self.st.write(force=True)
        self.st.log("==== 설치 끝")
        return 0

    # ---- 설정 '두뇌 바꾸기' — Gemma 만 설치 / 지우기
    def run_gemma(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.log(f"==== Gemma 설치 시작 (김비서 {VERSION})")
        for sid in ("python", "files", "packages", "pet"):
            self.st.end(sid, "건너뜀", "Gemma 만 설치")
        steps = [("plan", None), ("brain", self.do_brain), ("models", self.do_models), ("finish", None)]
        for sid, fn in steps:
            self.st.begin(sid)
            t0 = time.time()
            try:
                if sid == "plan":
                    p = PLAN.detect(self.P, local_brain=True, cli=False, gemma=self.bm)
                    if not p["llama"]:   # 6GB 미만 그래픽카드 — 그래도 사용자가 원하면 그 카드(또는 CPU)로
                        p = PLAN.make_plan([], p["램_GB"], p["디스크_여유_GB"], others=p["다른_그래픽카드"], local_brain=True, gemma=self.bm)
                    self.state["plan"] = dict(self.state.get("plan") or {}, llama=p["llama"], 모델=[self.bm])
                    self.st.log("Gemma 설치 판별:", p["llama"], p["구성"])
                    need = (GM.load_manifest(os.path.join(HERE, "models.json"))[self.bm]["size_total"] / (1024 ** 3)) + 1.5
                    if p["디스크_여유_GB"] is not None and p["디스크_여유_GB"] < need:
                        raise Fail(f"디스크 공간이 모자라요. 약 {need:.1f}GB 가 필요한데 {p['디스크_여유_GB']}GB 남았어요.")
                    r = ("됨", f"두뇌 프로그램 {p['llama']} · {self.bm}")
                    self._gemma_dev = "gpu" if p["llama"] in ("cuda12", "cuda13", "vulkan") else "cpu"
                elif sid == "finish":
                    freed = 0
                    for n in self.gemma_dirs():
                        if n != self.bm:
                            freed += dir_size(self.path("models", n))
                            rmtree(self.path("models", n))
                    cur = self.current_settings()
                    run = cur.setdefault("실행", {})
                    run.update({"두뇌_실행파일": self.path("runtime", "llama", "llama-server.exe"), "두뇌_모델": self.gemma_file(),
                                "두뇌_장치": self._gemma_dev})
                    write_json(self.settings_file(), cur)
                    r = ("됨", "설정에 두뇌 경로를 적었어요" + (f" · 옛 Gemma 지움 {human(freed)}" if freed else ""))
                else:
                    r = fn()
            except Fail as ex:
                return self.fail(sid, ex.why, ex.detail)
            except Exception as ex:  # noqa: BLE001
                return self.fail(sid, "Gemma 를 설치하다 문제가 생겼어요. 인터넷을 확인하고 다시 눌러 주세요(받은 만큼은 이어서 받아요).",
                                 f"{type(ex).__name__}: {ex}")
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": "Gemma 설치가 끝났어요."})
        self.st.write(force=True)
        self.st.log("==== Gemma 설치 끝")
        return 0

    def remove_gemma(self):
        """Gemma 모델 폴더 전부 + 두뇌 프로그램(runtime\\llama) 지우기 → 돌려준 바이트. 켜져 있으면 실행 관리가 먼저 끔."""
        freed, gone, left = 0, [], []
        targets = [self.path("models", n) for n in self.gemma_dirs()] + [self.path("runtime", "llama")]
        for t in targets:
            if not os.path.isdir(t):
                continue
            n = dir_size(t)
            try:
                rmtree(t)
                freed += n
                gone.append(os.path.basename(t))
            except OSError as ex:
                left.append(f"{os.path.basename(t)}: {type(ex).__name__}")
        cur = self.current_settings()
        if cur:
            run = cur.setdefault("실행", {})
            run["두뇌_모델"] = self.gemma_file()
            llama_exe = self.path("runtime", "llama", "llama-server.exe")
            run["두뇌_실행파일"] = llama_exe if os.path.isfile(llama_exe) else ""
            write_json(self.settings_file(), cur)
        self.st.log(f"Gemma 지움: {', '.join(gone) or '없음'} · {human(freed)}" + (f" · 못 지움 {left}" if left else ""))
        return {"ok": not left, "지움": gone, "못지움": left, "돌려준_바이트": freed, "돌려준": human(freed)}

    def fail(self, sid, why, detail):
        self.st.end(sid, "실패", why)
        self.st.d.update({"끝": True, "성공": False, "오류": {"단계": dict(STEPS)[sid], "이유": why, "자세히": str(detail)[-800:],
                                                          "기록": self.st.log_path}})
        self.st.write(force=True)
        self.st.log("!!!! 실패:", sid, why, "|", detail)
        self.save_state()
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["install", "plan", "gemma-install", "gemma-remove"])
    ap.add_argument("--prefix", default=os.path.expandvars(r"%LOCALAPPDATA%\KimBiseo"))
    ap.add_argument("--data", default=os.path.expandvars(r"%APPDATA%\KimBiseo"))
    ap.add_argument("--status", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--local-brain", action="store_true")
    ap.add_argument("--gemma", default=None, help="이 PC 두뇌 판: E4B(기본, 약 5.3GB) | E2B(약 3.4GB)")
    ap.add_argument("--desktop-dir", default="")
    ap.add_argument("--startmenu-dir", default="")
    ap.add_argument("--reg-key", default="KimBiseo")
    ap.add_argument("--display-name", default="김비서")
    ap.add_argument("--packs-catalog", default=None)
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="시험: 받기·설치 없이 차례만(받을 주소는 크기만 물어 확인)")
    a = ap.parse_args()
    if a.packs_catalog is None:   # 옷 목록 주소 = install_config.json 한 줄(설치 창에서 따로 주지 않았을 때)
        try:
            with open(os.path.join(HERE, "install_config.json"), encoding="utf-8") as f:
                a.packs_catalog = str(json.load(f).get("packs_catalog") or "")
        except (OSError, ValueError):
            a.packs_catalog = None
    if a.cmd == "plan":
        print(json.dumps(PLAN.detect(a.prefix, a.local_brain, gemma=a.gemma), ensure_ascii=False, indent=1))
        return 0
    if not a.status:
        a.status = os.path.join(a.prefix, "install", "gemma_status.json" if a.cmd.startswith("gemma") else "status.json")
    os.makedirs(os.path.dirname(os.path.abspath(a.status)), exist_ok=True)
    if a.cmd == "gemma-remove":
        print(json.dumps(Installer(a).remove_gemma(), ensure_ascii=False))
        return 0
    if a.cmd == "gemma-install":
        if os.path.isfile(a.status):
            os.remove(a.status)
        return Installer(a).run_gemma()
    return Installer(a).run()


if __name__ == "__main__":
    sys.exit(main())
