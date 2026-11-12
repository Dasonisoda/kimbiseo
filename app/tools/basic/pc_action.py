# pc_action 도구의 허용목록 실행기(운영판 컴퓨터조작을 옮김, 표준 라이브러리만)
#   두뇌 인자 → from_llm() 으로 검사·정리 → {"action": "open_url"|"open_program", ...} → run_checked() 가 다시 검사한 뒤 실행.
#   할 수 있는 일: http/https 웹 주소 열기(크롬·엣지·기본 브라우저), 네이버·구글·유튜브 검색 결과 열기, 정해진 프로그램 켜기.
#   못 하는 일: 임의 명령·스크립트 실행, 파일 삭제/이동, 설치, file:/javascript: 같은 주소, 프로그램에 인자 넘기기.
#   시험용 환경변수 KIMBISEO_PC_TEST_PROFILE=<폴더> : 크롬·엣지를 그 폴더의 별도 프로필로 띄움.
#   시험용 KIMBISEO_PC_DRYRUN=1 (또는 설정 도구.컴퓨터조작.시험_실행안함) : 검사까지만 하고 실제로 열지 않음(무엇을 열었을지 돌려줌).
import glob
import os
import re
import subprocess
import time
import urllib.parse

try:
    import winreg
except ImportError:  # 윈도우가 아니면(시험) 레지스트리 찾기만 건너뜀
    winreg = None

ENGINES = {
    "naver": ("네이버", "https://search.naver.com/search.naver?query={q}"),
    "google": ("구글", "https://www.google.com/search?q={q}"),
    "youtube": ("유튜브", "https://www.youtube.com/results?search_query={q}"),
}
BROWSERS = {"chrome": "크롬", "edge": "엣지", "default": "기본 브라우저"}
_ENV = os.environ.get
_PF = _ENV("ProgramFiles", r"C:\Program Files")
_PF86 = _ENV("ProgramFiles(x86)", r"C:\Program Files (x86)")
_SYS = os.path.join(_ENV("SystemRoot", r"C:\Windows"), "System32")
_LAD = _ENV("LOCALAPPDATA", "")

# 켤 수 있는 프로그램(이 목록 밖은 못 켬). 찾기: App Paths 레지스트리 → 정해진 경로(glob) → 시작 메뉴 바로가기 이름
PROGRAMS = {
    "chrome": {"이름": "크롬", "apppath": "chrome.exe",
               "경로": [rf"{_PF}\Google\Chrome\Application\chrome.exe", rf"{_PF86}\Google\Chrome\Application\chrome.exe",
                       rf"{_LAD}\Google\Chrome\Application\chrome.exe"], "바로가기": ["Google Chrome"]},
    "edge": {"이름": "엣지", "apppath": "msedge.exe",
             "경로": [rf"{_PF86}\Microsoft\Edge\Application\msedge.exe", rf"{_PF}\Microsoft\Edge\Application\msedge.exe"],
             "바로가기": ["Microsoft Edge"]},
    "notepad": {"이름": "메모장", "경로": [rf"{_SYS}\notepad.exe"]},
    "calculator": {"이름": "계산기", "경로": [rf"{_SYS}\calc.exe"]},
    "explorer": {"이름": "파일 탐색기", "경로": [os.path.join(_ENV("SystemRoot", r"C:\Windows"), "explorer.exe")]},
    "paint": {"이름": "그림판", "경로": [rf"{_SYS}\mspaint.exe", rf"{_LAD}\Microsoft\WindowsApps\mspaint.exe"],
              "주소": "ms-paint:"},
    "photoshop": {"이름": "포토샵", "apppath": "Photoshop.exe",
                  "경로": [rf"{_PF}\Adobe\Adobe Photoshop*\Photoshop.exe"], "바로가기": ["Adobe Photoshop*"],
                  "제외": ["Elements", "Express"]},
    "premiere": {"이름": "프리미어 프로", "apppath": "Adobe Premiere Pro.exe",
                 "경로": [rf"{_PF}\Adobe\Adobe Premiere Pro*\Adobe Premiere Pro.exe"], "바로가기": ["Adobe Premiere Pro*"],
                 "제외": ["Elements", "Rush"]},
}
PROGRAM_ALIASES = {
    "크롬": "chrome", "구글크롬": "chrome", "googlechrome": "chrome",
    "엣지": "edge", "마이크로소프트엣지": "edge", "msedge": "edge", "microsoftedge": "edge",
    "메모장": "notepad", "노트패드": "notepad",
    "계산기": "calculator", "calc": "calculator",
    "파일탐색기": "explorer", "탐색기": "explorer", "내pc": "explorer", "내컴퓨터": "explorer", "fileexplorer": "explorer",
    "그림판": "paint", "mspaint": "paint",
    "포토샵": "photoshop", "어도비포토샵": "photoshop", "adobephotoshop": "photoshop",
    "프리미어": "premiere", "프리미어프로": "premiere", "어도비프리미어": "premiere", "어도비프리미어프로": "premiere",
    "premierepro": "premiere", "adobepremierepro": "premiere",
}

REFUSE = "그건 제가 할 수 없어요. 웹사이트 열기, 검색, 정해진 프로그램 켜기만 할 수 있어요."
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DOMAIN = re.compile(r"^(?:[a-z0-9가-힣](?:[a-z0-9가-힣-]{0,61}[a-z0-9가-힣])?\.)+[a-z가-힣]{2,24}(?::\d{1,5})?(?:[/?#].*)?$", re.I)


def _key(s):
    return re.sub(r"[\s._\-·'\"]+", "", str(s or "")).lower()


def _clean(s, n):
    return _CTRL.sub(" ", str(s or "")).strip()[:n]


def _has_batchim(word):
    """마지막 글자에 받침이 있나(ㄹ 받침은 '로') — 크롬으로 / 엣지로."""
    c = (word or " ")[-1]
    if not ("가" <= c <= "힣"):
        return False
    j = (ord(c) - 0xAC00) % 28
    return j not in (0, 8)


def fail(reason, say):
    return {"ok": False, "이유": reason, "말": say}


# ---------------------------------------------------------------- 주소 검사(본체·실행 기기 모두)
def check_url(url):
    """http/https 주소만 통과. 돌려주는 값: 깨끗한 주소 또는 None."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or len(u) > 2000 or _CTRL.search(u) or any(c in u for c in ' \\"<>^`{|}'):
        return None
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        return None
    return u


def resolve_site(site, sites, aliases=None):
    """'네이버' 같은 이름 → 주소(설정.json 사전), 'naver.com'·'https://…' → 주소. 모르면 None."""
    raw = _clean(site, 300)
    if not raw:
        return None, None
    if re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.I) and not raw.lower().startswith(("http://", "https://")):
        return None, "bad_scheme"  # file:, javascript:, data: …
    if raw.lower().startswith(("http://", "https://")):
        u = check_url(raw)
        return (u, None) if u else (None, "bad_url")
    table = {_key(k): (k, v) for k, v in (sites or {}).items()}
    for a, target in (aliases or {}).items():
        if _key(target) in table:
            table.setdefault(_key(a), table[_key(target)])
    k = _key(raw)
    for suffix in ("", "홈페이지", "사이트", "웹사이트", "홈", "닷컴", "페이지"):
        if suffix and not k.endswith(suffix):
            continue
        base = k[: len(k) - len(suffix)] if suffix else k
        if base in table:
            name, url = table[base]
            u = check_url(url)
            return (u, None) if u else (None, "bad_url")
    if _DOMAIN.match(raw.replace(" ", "")):
        u = check_url("https://" + raw.replace(" ", ""))
        return (u, None) if u else (None, "bad_url")
    return None, "unknown_site"


def program_key(name):
    k = _key(name)
    if k in PROGRAMS:
        return k
    return PROGRAM_ALIASES.get(k)


# ---------------------------------------------------------------- 두뇌 인자 → 정리된 행동(본체에서)
def from_llm(args, sites=None, aliases=None):
    """두뇌가 부른 pc_action 인자를 검사해 (행동 dict, None) 또는 (None, 실패 결과) 를 돌려준다."""
    if not isinstance(args, dict):
        return None, fail("잘못된 인자", REFUSE)
    if not args.get("action"):   # 작은 두뇌가 {"open_program": "calculator"} 처럼 동작 이름을 칸 이름으로 씀
        for k, field in (("open_program", "program"), ("open_website", "site"), ("search", "query")):
            if isinstance(args.get(k), str) and args.get(k).strip():
                args = dict(args, action=k, **{field: args.get(field) or args[k]})
                break
    act = _key(args.get("action"))
    if act in ("openwebsite", "openurl", "website", "url") and not (args.get("site") or args.get("url")):
        for k in ("engine", "query", "program"):   # open_website 인데 사이트 칸이 비고 engine·query 에 '유튜브'만 옴
            v = _clean(args.get(k), 40)
            if v and "." not in v and ":" not in v and resolve_site(v, sites, aliases)[0]:
                args = dict(args, site=v)
                break
    browser = _key(args.get("browser") or "default")
    browser = {"크롬": "chrome", "엣지": "edge", "기본": "default", "기본브라우저": "default"}.get(browser, browser)
    if browser not in BROWSERS:
        browser = program_key(browser) if program_key(browser) in ("chrome", "edge") else "default"
    prog = program_key(args.get("program") or "")
    site = args.get("site") or args.get("url") or ""
    # '크롬 켜서 네이버' 를 open_program(chrome)+site 로 부른 경우 → 크롬으로 사이트 열기
    if act in ("openprogram", "program") and prog in ("chrome", "edge") and (site or args.get("query")):
        browser = prog
        act = "search" if (args.get("query") and not site) else "openwebsite"
    # '유튜브 켜 줘' 를 open_program(youtube) 로 부른 경우 → 프로그램 목록에 없고 주소 사전에 있는 사이트면 사이트 열기
    p_raw = _clean(args.get("program"), 60)
    if act in ("openprogram", "program", "launch") and not prog and not site and p_raw             and "." not in p_raw and ":" not in p_raw:   # 사전에 있는 이름만(주소 꼴은 안 받음)
        if resolve_site(p_raw, sites, aliases)[0]:
            site, act = p_raw, "openwebsite"
    if act in ("openwebsite", "openurl", "website", "url"):
        url, why = resolve_site(site, sites, aliases)
        if not url:
            if why == "unknown_site":
                return None, fail("모르는 사이트 이름(주소 사전에 없음). 검색(search)으로 대신 열 수 있음",
                                  f"'{_clean(site, 40)}' 사이트 주소를 몰라요.")
            return None, fail("허용되지 않는 주소(http/https 만 됨)", "그 주소는 열 수 없어요. 웹 주소만 열 수 있어요.")
        label = _clean(site, 40)
        return {"action": "open_url", "url": url, "browser": browser, "label": label, "kind": "site"}, None
    if act in ("search", "websearch"):
        eng = _key(args.get("engine") or "naver")
        eng = {"네이버": "naver", "구글": "google", "유튜브": "youtube", "유투브": "youtube"}.get(eng, eng)
        if eng not in ENGINES:
            eng = "naver"
        q = _clean(args.get("query"), 200)
        if not q:
            return None, fail("검색어 없음", "무엇을 검색할지 말씀해 주세요.")
        name, tpl = ENGINES[eng]
        url = tpl.format(q=urllib.parse.quote_plus(q))
        return {"action": "open_url", "url": url, "browser": browser, "label": f"{name}에서 {q} 검색",
                "kind": "search"}, None
    if act in ("openprogram", "program", "launch"):
        if not prog:
            return None, fail("허용되지 않은 프로그램", REFUSE)
        return {"action": "open_program", "program": prog, "label": PROGRAMS[prog]["이름"]}, None
    return None, fail("허용되지 않은 동작", REFUSE)


# ---------------------------------------------------------------- 실행(실행하는 기기에서)
def _app_path(exe):
    if not winreg:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe, 0,
                                    winreg.KEY_READ | view) as k:
                    v = winreg.QueryValue(k, None)
            except OSError:
                continue
            v = os.path.expandvars((v or "").strip().strip('"'))
            if v and os.path.isfile(v):
                return v
    return None


def _start_menu_dirs():
    return [os.path.join(_ENV("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(_ENV("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]


def find_program(key):
    """(실행할 것, 종류) — 종류: 'exe' | 'lnk' | 'uri'. 없으면 (None, None)."""
    p = PROGRAMS[key]
    skip = [s.lower() for s in p.get("제외", [])]
    ok = lambda path: not any(s in os.path.basename(os.path.dirname(path)).lower() or s in os.path.basename(path).lower()  # noqa: E731
                             for s in skip)
    if p.get("apppath"):
        v = _app_path(p["apppath"])
        if v and ok(v):
            return v, "exe"
    for pat in p.get("경로", []):
        hits = sorted((h for h in glob.glob(pat) if os.path.isfile(h) and ok(h)), reverse=True)
        if hits:
            return hits[0], "exe"
    for pat in p.get("바로가기", []):
        hits = []
        for d in _start_menu_dirs():
            hits += [h for h in glob.glob(os.path.join(d, "**", pat + ".lnk"), recursive=True) if ok(h)]
        if hits:
            return sorted(hits, reverse=True)[0], "lnk"
    if p.get("주소"):
        return p["주소"], "uri"
    return None, None


def _allow_foreground():
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # 새로 뜨는 창이 앞으로 나올 수 있게
    except Exception:  # noqa: BLE001
        pass


def _spawn(argv):
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    p = subprocess.Popen(argv, cwd=os.path.dirname(argv[0]) or None, close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return p.pid


def _test_args(key):
    prof = os.environ.get("KIMBISEO_PC_TEST_PROFILE")
    if not prof:
        return []
    return [f"--user-data-dir={os.path.join(prof, key)}", "--no-first-run", "--no-default-browser-check", "--new-window"]


def _open_url(a):
    url, browser, label = a["url"], a.get("browser", "default"), a.get("label") or "사이트"
    if os.environ.get("KIMBISEO_PC_TEST_PROFILE") and browser == "default":
        browser = "edge"  # 시험: 사용자 브라우저를 건드리지 않게 별도 프로필 엣지로
    note = ""
    if browser in ("chrome", "edge"):
        exe, kind = find_program(browser)
        if exe and kind == "exe":
            pid = _spawn([exe] + _test_args(browser) + [url])
            b = BROWSERS[browser] + ("으로" if _has_batchim(BROWSERS[browser]) else "로")
            return {"ok": True, "pid": pid, "브라우저": BROWSERS[browser],
                    "말": f"{b} {label} 열었어요." if a.get("kind") == "site" else f"{label} 결과를 {b} 열었어요."}
        note = f"{BROWSERS[browser]}{'이' if _has_batchim(BROWSERS[browser]) else '가'} 이 컴퓨터에 없어서 기본 브라우저로 열었어요. "
    os.startfile(url)  # noqa: S606  (http/https 만 — 기본 브라우저)
    return {"ok": True, "pid": None, "브라우저": "기본 브라우저",
            "말": note + (f"{label} 열었어요." if a.get("kind") == "site" else f"{label} 결과를 열었어요.")}


def _open_program(a):
    key = a["program"]
    name = PROGRAMS[key]["이름"]
    target, kind = find_program(key)
    if not target:
        return {"ok": False, "이유": "not_installed", "말": f"{name}{'은' if _has_batchim(name) else '는'} 이 컴퓨터에 설치돼 있지 않아요."}
    if kind == "exe":
        pid = _spawn([target] + (_test_args(key) if key in ("chrome", "edge") else []))
    else:
        os.startfile(target)  # noqa: S606  (시작 메뉴 바로가기 / ms-paint: 같은 고정 주소)
        pid = None
    return {"ok": True, "pid": pid, "말": f"{name} 켰어요."}


def validate(a):
    """실행하는 기기 쪽 재검사 — 서버가 보낸 것을 그대로 믿지 않는다. (깨끗한 행동, None) 또는 (None, 실패)."""
    if not isinstance(a, dict):
        return None, fail("잘못된 명령", REFUSE)
    act = a.get("action")
    label = _clean(a.get("label"), 60)
    if act == "open_url":
        url = check_url(a.get("url"))
        browser = a.get("browser") if a.get("browser") in BROWSERS else "default"
        if not url:
            return None, fail("허용되지 않는 주소", "그 주소는 열 수 없어요.")
        return {"action": "open_url", "url": url, "browser": browser, "label": label,
                "kind": "search" if a.get("kind") == "search" else "site"}, None
    if act == "open_program":
        if a.get("program") not in PROGRAMS:
            return None, fail("허용되지 않은 프로그램", REFUSE)
        return {"action": "open_program", "program": a["program"], "label": PROGRAMS[a["program"]]["이름"]}, None
    return None, fail("허용되지 않은 동작", REFUSE)


def run_checked(a, dry_run=False):
    """검사 → 실행. 늘 dict 를 돌려준다(예외를 밖으로 던지지 않음)."""
    t0 = time.time()
    clean, err = validate(a)
    if err:
        return err
    if dry_run or os.environ.get("KIMBISEO_PC_DRYRUN") == "1":
        what = clean.get("url") or clean.get("program")
        return {"ok": True, "시험": True, "열었을것": what, "말": f"(시험이라 실제로 열지 않음) {clean.get('label') or what}",
                "초": round(time.time() - t0, 2)}
    _allow_foreground()
    try:
        r = _open_url(clean) if clean["action"] == "open_url" else _open_program(clean)
    except Exception as ex:  # noqa: BLE001
        r = {"ok": False, "이유": f"{type(ex).__name__}: {ex}"[:200], "말": "여는 데 실패했어요."}
    r["초"] = round(time.time() - t0, 2)
    return r
