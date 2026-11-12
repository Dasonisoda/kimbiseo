# 구독 두뇌 찾기 — 이 PC 에 클로드 코드(claude)·GPT(codex) 명령이 있는지, 사용자 본인이 로그인했는지 본다.
#   표준 라이브러리만 씀(설치 프로그램 plan.py 도 같이 씀). 열쇠·토큰은 읽지 않고, 그 프로그램에 '로그인 상태'만 묻는다.
#     claude : `claude auth status` (JSON loggedIn)        codex : `codex login status` (끝 코드 0 + 'Logged in')
#   시험용: KIMBISEO_FAKE_CLI="claude:on,codex:off"(on=로그인됨 · off=있지만 로그인 안 됨 · none=없음)  "none" = 둘 다 없음
import json
import os
import re
import shutil
import subprocess
import time

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KINDS = {"claude": "claude_cli", "codex": "codex_cli"}
NAMES = {"claude": "클로드 코드", "codex": "GPT(Codex)"}
SUBJ = {"claude": "클로드 코드가", "codex": "Codex 가"}
INSTALL = {
    "claude": "클로드 코드 설치: https://claude.com/claude-code 의 윈도우 설치 안내(PowerShell 한 줄)대로 설치한 뒤 이 화면에서 '다시 확인' → '로그인 창 열기'를 누르세요.",
    "codex": "Codex 설치: https://developers.openai.com/codex/cli 안내대로 설치한 뒤 이 화면에서 '다시 확인' → '로그인 창 열기'를 누르세요.",
}
LOGIN_CMD = {"claude": ["auth", "login"], "codex": ["login"]}
_CACHE = {}
CACHE_SEC = 60


def _candidates(name):
    home = os.path.expanduser("~")
    la = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    ra = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    if name == "claude":
        return [os.path.join(home, ".local", "bin", "claude.exe"), os.path.join(ra, "npm", "claude.cmd"),
                os.path.join(la, "Programs", "claude", "claude.exe")]
    return [os.path.join(la, "Programs", "OpenAI", "Codex", "bin", "codex.exe"), os.path.join(ra, "npm", "codex.cmd")]


def find(name):
    """실행 파일 경로(없으면 ''). .exe 먼저(PATH → 흔한 설치 자리), 그다음 npm 의 .cmd 같은 것."""
    p = shutil.which(name + ".exe")
    if p:
        return p
    cands = _candidates(name)
    for c in cands:
        if c.lower().endswith(".exe") and os.path.isfile(c):
            return c
    p = shutil.which(name)
    if p:
        return p
    for c in cands:
        if os.path.isfile(c):
            return c
    return ""


# .cmd/.bat 는 윈도우가 cmd.exe 로 돌려서, 경로·인자에 cmd 특수문자가 있으면 다른 명령으로 풀릴 수 있음(BatBadBut 류)
#   → npm 이 만든 .cmd 는 안에 적힌 node + 진짜 .js 를 찾아 cmd 없이 바로 돌리고, 그게 안 되면 특수문자 있는 경로·인자는 거절
CMD_SPECIAL = set('&^%!|<>"()')
_SHIM_JS = re.compile(r'"%dp0%\\([^"%]+?\.(?:js|mjs|cjs|exe))"', re.I)


class CliPathError(OSError):
    """구독 두뇌 프로그램을 안전하게 부를 수 없음(안내 글이 들어 있음)."""


def _shim_target(cmd_path):
    """npm .cmd 심 → (node 경로 또는 '', 진짜 파일 경로) | None"""
    try:
        txt = open(cmd_path, encoding="utf-8", errors="replace").read(20000)
    except OSError:
        return None
    found = [x for x in _SHIM_JS.findall(txt) if os.path.basename(x).lower() != "node.exe"]   # 마지막 줄이 진짜 부르는 곳
    if not found:
        return None
    base = os.path.dirname(os.path.abspath(cmd_path))
    target = os.path.normpath(os.path.join(base, found[-1]))
    if not os.path.isfile(target):
        return None
    if target.lower().endswith(".exe"):
        return "", target
    node = os.path.join(base, "node.exe")
    if not os.path.isfile(node):
        node = shutil.which("node.exe") or ""
    if not node:
        return None
    return node, target


def command(name, args, exe=None):
    """구독 두뇌 프로그램을 부를 명령 줄(목록). .exe 는 그대로, .cmd/.bat 는 node + 진짜 .js 로 바꿈.
    바꾸지 못한 .cmd 는 경로·인자에 cmd 특수문자가 없을 때만 그대로 — 있으면 CliPathError(안내)."""
    exe = exe or find(name)
    if not exe:
        raise FileNotFoundError(INSTALL[name])
    low = exe.lower()
    if not low.endswith((".cmd", ".bat")):
        return [exe, *args]
    t = _shim_target(exe)
    if t:
        node, target = t
        return ([target] if not node else [node, target]) + list(args)
    bad = [x for x in [exe, *args] if CMD_SPECIAL & set(str(x))]
    if bad:
        raise CliPathError(f"{NAMES[name]} 가 .cmd 로만 설치돼 있고 경로나 설정에 특수문자(& ^ % ! | < > 따옴표 괄호)가 있어 안전하게 부를 수 없어요. "
                           f"공식 설치 프로그램(.exe)으로 다시 설치하거나 특수문자가 없는 폴더에 설치해 주세요. ({bad[0][:80]})")
    return [exe, *args]


def _run(cmd, timeout):
    env = dict(os.environ)
    for k in list(env):
        if k.upper() in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT") or k.upper().startswith("KIMBISEO_KEY_"):
            env.pop(k)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env, creationflags=NO_WINDOW)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _fake(name):
    f = os.environ.get("KIMBISEO_FAKE_CLI")
    if f is None:
        return None
    f = f.strip().lower()
    if f == "none":
        return {"있음": False, "로그인": False, "경로": "", "판": "", "시험값": True}
    for part in f.split(","):
        k, _, v = part.partition(":")
        if k.strip() == name:
            v = v.strip()
            if v == "none":
                return {"있음": False, "로그인": False, "경로": "", "판": "", "시험값": True}
            return {"있음": True, "로그인": v == "on", "경로": "(시험)", "판": "시험", "시험값": True}
    return {"있음": False, "로그인": False, "경로": "", "판": "", "시험값": True}


def status(name, timeout=20, fresh=False):
    """→ {"있음", "로그인"(True|False|None=확인 못 함), "경로", "판", "안내"}"""
    now = time.time()
    if not fresh and name in _CACHE and now - _CACHE[name][0] < CACHE_SEC:
        return dict(_CACHE[name][1])
    out = _fake(name)
    if out is None:
        exe = find(name)
        out = {"있음": bool(exe), "로그인": False, "경로": exe, "판": ""}
        if exe:
            try:
                command(name, ["auth", "status"] if name == "claude" else ["login", "status"], exe)
            except CliPathError as ex:
                out["로그인"], out["막힘"], exe = None, str(ex), ""
        if exe:
            try:
                rc, so, _se = _run(command(name, ["--version"], exe), timeout)
                out["판"] = (so.strip().splitlines() or [""])[0][:60] if rc == 0 else ""
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                if name == "claude":
                    rc, so, _se = _run(command(name, ["auth", "status"], exe), timeout)
                    try:
                        out["로그인"] = bool(json.loads(so).get("loggedIn"))
                    except ValueError:
                        out["로그인"] = None if rc != 0 else ("logged in" in so.lower())
                else:
                    rc, so, se = _run(command(name, ["login", "status"], exe), timeout)
                    out["로그인"] = rc == 0 and "logged in" in (so + se).lower() and "not logged" not in (so + se).lower()
            except subprocess.TimeoutExpired:
                out["로그인"] = None
            except (OSError, subprocess.SubprocessError):
                out["로그인"] = None
    out["이름"] = NAMES[name]
    out["방식"] = KINDS[name]
    if out.get("막힘"):
        out["안내"] = out["막힘"]
    elif not out["있음"]:
        out["안내"] = INSTALL[name]
    elif out["로그인"] is False:
        out["안내"] = f"{SUBJ[name]} 설치돼 있지만 로그인이 안 돼 있어요. '로그인 창 열기'를 눌러 본인 계정으로 로그인해 주세요."
    elif out["로그인"] is None:
        out["안내"] = f"{NAMES[name]} 로그인 상태를 확인하지 못했어요. '연결 시험'을 눌러 보세요."
    else:
        out["안내"] = f"{NAMES[name]}에 로그인돼 있어요. 본인 구독으로 대답해요."
    _CACHE[name] = (now, dict(out))
    return out


def all_status(fresh=False):
    return {n: status(n, fresh=fresh) for n in ("claude", "codex")}


def suggest(st=None):
    """로그인된 구독 두뇌 중 기본으로 권할 것('claude_cli' | 'codex_cli' | ''). 둘 다면 클로드 먼저."""
    st = st or all_status()
    for n in ("claude", "codex"):
        if (st.get(n) or {}).get("로그인") is True:
            return KINDS[n]
    return ""


def open_login(name):
    """사용자가 직접 로그인하는 창(새 명령 창)을 연다 — 김비서는 계정·토큰을 보지 않음."""
    fk = _fake(name)
    if fk is not None:                     # 시험값일 때는 창을 띄우지 않음(진짜 로그인을 건드리지 않게)
        if not fk["있음"]:
            raise FileNotFoundError(INSTALL[name])
        _CACHE.pop(name, None)
        return True
    exe = find(name)
    if not exe:
        raise FileNotFoundError(INSTALL[name])
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    argv = command(name, LOGIN_CMD[name], exe)   # cmd /k 를 거치지 않음(경로의 특수문자가 명령으로 풀리지 않게) — 새 콘솔 창에서 바로 실행
    subprocess.Popen(argv, creationflags=flags, close_fds=True)
    _CACHE.pop(name, None)
    return True
