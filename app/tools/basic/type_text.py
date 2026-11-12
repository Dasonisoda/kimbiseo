# type_text 도구·메모장 켜기 — '김비서 메모' 창(김비서 본체가 직접 띄우는 창)에만 글을 쓴다(표준 라이브러리 ctypes, 윈도우 전용).
#   왜 윈도우 메모장이 아닌가: 윈도우 11 메모장은 켤 때 지난 탭을 되살려 다른 파일 이름·내용이 화면에 보이고, 어느 경로의 notepad.exe 로
#     켜도 같은 앱으로 넘어간다. 그래서 김비서는 윈도우 메모장을 저절로 켜지 않는다(사용자가 창의 단추를 눌렀을 때만 연다).
#   김비서 메모 창: 큰 글 칸 하나 + 단추(저장 · 다른 이름으로 저장 · 윈도우 메모장에서 열기). Ctrl+S = 저장, Ctrl+A = 모두 선택.
#     저장 = 문서\김비서 메모\김비서메모_날짜_시각.txt (설정 도구.글쓰기.메모_폴더 로 바꿀 수 있음). 저장 전에는 파일을 만들지 않는다.
#     닫을 때 저장 안 한 글이 있으면 '저장할까요?'(예·아니요·취소).
#   쓰기: 이 프로세스가 만든 그 창의 글 칸에만 EM_REPLACESEL 로 붙인다 — 키보드·앞 창을 거치지 않아 다른 프로그램으로 새지 않는다.
#     창이 앞에 없어도 쓴다(사용자가 다른 창을 보고 있어도 그 창에는 아무것도 안 들어감). 한 번에 4000자까지.
#   창마다 자기 스레드(메시지 반복)를 가진다. 본체가 끝나면 창도 함께 닫힌다(저장 안 한 글은 남지 않음 — 안내에 적음).
#   시험용 KIMBISEO_PC_DRYRUN=1 (또는 설정 도구.컴퓨터조작.시험_실행안함) : 창을 띄우지 않고 검사까지만.
#   시험용 KIMBISEO_MEMO_DIR=<폴더> : 문서 폴더 대신 그 폴더에 저장.
import datetime
import os
import re
import subprocess
import sys
import threading
import time
import types

MAX_CHARS = 4000
MEMO_PREFIX = "김비서메모_"
APP_TITLE = "김비서 메모"
MAX_WINDOWS = 5
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")      # 탭(\t)·줄바꿈(\n)만 남김

# 본체가 켜져 있는 동안 연 메모 창 목록(도구 묶음은 대화마다 다시 읽혀도 이 목록은 그대로)
_S = sys.modules.get("kimbiseo_memo_state")
if _S is None:
    _S = types.ModuleType("kimbiseo_memo_state")
    _S.memos = []
    _S.lock = threading.Lock()
    _S.api = None
    sys.modules["kimbiseo_memo_state"] = _S


def fail(reason, say):
    return {"ok": False, "이유": reason, "말": say}


def clean_text(text, limit=MAX_CHARS):
    """→ (써 넣을 글, 잘렸나). 줄바꿈은 \\n 하나로, 제어문자는 뺌."""
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _CTRL.sub("", t).strip("\n")
    lim = max(1, int(limit or MAX_CHARS))
    if len(t) > lim:
        return t[:lim], True
    return t, False


def memo_dir(cfg_dir=""):
    d = os.environ.get("KIMBISEO_MEMO_DIR") or cfg_dir
    if d:
        return d
    return os.path.join(_documents(), "김비서 메모")


def _documents():
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        p = ctypes.c_wchar_p()
        sh = ctypes.WinDLL("shell32")
        sh.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        if sh.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(p)) == 0 and p.value:
            v = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
            return v
    except Exception:  # noqa: BLE001
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def dry_run(flag=False):
    return bool(flag) or os.environ.get("KIMBISEO_PC_DRYRUN") == "1"


def new_memo_name(d):
    base = MEMO_PREFIX + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem, n = base, 1
    taken = {os.path.basename(m.path) for m in _S.memos}
    while os.path.exists(os.path.join(d, stem + ".txt")) or (stem + ".txt") in taken:
        n += 1
        stem = f"{base}_{n}"
    return os.path.join(d, stem + ".txt")


def save_file(path, text):
    """메모 글 → 파일(UTF-8, 윈도우 줄바꿈). 같은 폴더의 임시 파일에 쓴 뒤 바꿔 넣음."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    body = str(text or "").replace("\r\n", "\n").replace("\n", "\r\n")
    tmp = path + ".kbtmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    os.replace(tmp, path)


# ================================================================ 윈도우 부분
def _api():
    """user32·gdi32·comdlg32 함수(인자 꼴까지 정해서 — 64비트 핸들이 잘리지 않게). 윈도우가 아니면 None."""
    if _S.api is not None:
        return _S.api
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes as W
    A = types.SimpleNamespace(ct=ctypes, W=W)
    u, g, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("gdi32"), ctypes.WinDLL("kernel32", use_last_error=True)
    A.u, A.g, A.k = u, g, k
    LRESULT = ctypes.c_ssize_t
    A.LRESULT = LRESULT
    A.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", W.UINT), ("style", W.UINT), ("lpfnWndProc", A.WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HANDLE),
                    ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR), ("hIconSm", W.HICON)]

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [("lStructSize", W.DWORD), ("hwndOwner", W.HWND), ("hInstance", W.HINSTANCE), ("lpstrFilter", ctypes.c_void_p),
                    ("lpstrCustomFilter", ctypes.c_void_p), ("nMaxCustFilter", W.DWORD), ("nFilterIndex", W.DWORD),
                    ("lpstrFile", ctypes.c_void_p), ("nMaxFile", W.DWORD), ("lpstrFileTitle", ctypes.c_void_p), ("nMaxFileTitle", W.DWORD),
                    ("lpstrInitialDir", ctypes.c_void_p), ("lpstrTitle", ctypes.c_void_p), ("Flags", W.DWORD), ("nFileOffset", W.WORD),
                    ("nFileExtension", W.WORD), ("lpstrDefExt", ctypes.c_void_p), ("lCustData", W.LPARAM), ("lpfnHook", ctypes.c_void_p),
                    ("lpTemplateName", ctypes.c_void_p), ("pvReserved", ctypes.c_void_p), ("dwReserved", W.DWORD), ("FlagsEx", W.DWORD)]

    class ACTCTXW(ctypes.Structure):
        _fields_ = [("cbSize", W.ULONG), ("dwFlags", W.DWORD), ("lpSource", W.LPCWSTR), ("wProcessorArchitecture", W.USHORT),
                    ("wLangId", W.USHORT), ("lpAssemblyDirectory", W.LPCWSTR), ("lpResourceName", ctypes.c_void_p),
                    ("lpApplicationName", W.LPCWSTR), ("hModule", W.HMODULE)]
    A.WNDCLASSEXW, A.OPENFILENAMEW, A.ACTCTXW = WNDCLASSEXW, OPENFILENAMEW, ACTCTXW

    def sig(f, res, *args):
        f.restype, f.argtypes = res, list(args)
    sig(u.RegisterClassExW, W.ATOM, ctypes.POINTER(WNDCLASSEXW))
    sig(u.CreateWindowExW, W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
    sig(u.DefWindowProcW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    sig(u.GetMessageW, W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
    sig(u.TranslateMessage, W.BOOL, ctypes.POINTER(W.MSG))
    sig(u.DispatchMessageW, LRESULT, ctypes.POINTER(W.MSG))
    sig(u.PostQuitMessage, None, ctypes.c_int)
    sig(u.SendMessageW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    sig(u.SendMessageTimeoutW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t))
    sig(u.PostMessageW, W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    sig(u.SetWindowTextW, W.BOOL, W.HWND, W.LPCWSTR)
    sig(u.MoveWindow, W.BOOL, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.BOOL)
    sig(u.SetWindowPos, W.BOOL, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT)
    sig(u.ShowWindow, W.BOOL, W.HWND, ctypes.c_int)
    sig(u.IsWindow, W.BOOL, W.HWND)
    sig(u.IsIconic, W.BOOL, W.HWND)
    sig(u.DestroyWindow, W.BOOL, W.HWND)
    sig(u.SetFocus, W.HWND, W.HWND)
    sig(u.GetClientRect, W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
    sig(u.MessageBoxW, ctypes.c_int, W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT)
    sig(u.GetKeyState, ctypes.c_short, ctypes.c_int)
    sig(u.LoadCursorW, W.HANDLE, W.HINSTANCE, W.LPVOID)
    sig(u.LoadImageW, W.HANDLE, W.HINSTANCE, W.LPCWSTR, W.UINT, ctypes.c_int, ctypes.c_int, W.UINT)
    sig(u.GetForegroundWindow, W.HWND)
    sig(u.SetForegroundWindow, W.BOOL, W.HWND)
    sig(u.BringWindowToTop, W.BOOL, W.HWND)
    sig(u.GetWindowThreadProcessId, W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
    sig(u.AttachThreadInput, W.BOOL, W.DWORD, W.DWORD, W.BOOL)
    sig(k.GetCurrentThreadId, W.DWORD)
    sig(k.GetModuleHandleW, W.HMODULE, W.LPCWSTR)
    sig(k.CreateActCtxW, W.HANDLE, ctypes.POINTER(ACTCTXW))
    sig(k.ActivateActCtx, W.BOOL, W.HANDLE, ctypes.POINTER(ctypes.c_size_t))
    sig(g.CreateFontW, W.HFONT, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.DWORD, W.DWORD, W.DWORD,
        W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.LPCWSTR)
    sig(g.DeleteObject, W.BOOL, W.HGDIOBJ)
    try:
        sig(u.SetThreadDpiAwarenessContext, ctypes.c_void_p, ctypes.c_void_p)
        sig(u.GetDpiForWindow, W.UINT, W.HWND)
        A.dpi_ok = True
    except AttributeError:
        A.dpi_ok = False
    try:
        cd = ctypes.WinDLL("comdlg32")
        sig(cd.GetSaveFileNameW, W.BOOL, ctypes.POINTER(OPENFILENAMEW))
        A.cd = cd
    except OSError:
        A.cd = None
    A.hinst = k.GetModuleHandleW(None)
    A.cls = None
    A.proc = A.WNDPROC(_wndproc)          # 살려 둠(지워지면 창이 죽음)
    A.by_hwnd = {}
    _S.api = A
    return A


WM_DESTROY, WM_SIZE, WM_SETFOCUS, WM_CLOSE, WM_SETFONT, WM_GETTEXT, WM_GETTEXTLENGTH = 0x2, 0x5, 0x7, 0x10, 0x30, 0xD, 0xE
WM_KEYDOWN, WM_COMMAND, WM_DPICHANGED = 0x100, 0x111, 0x2E0
EM_SETSEL, EM_REPLACESEL, EM_SCROLLCARET, EM_SETLIMITTEXT, EM_SETMARGINS = 0xB1, 0xC2, 0xB7, 0xC5, 0xD3
EN_CHANGE = 0x300
ID_EDIT, ID_SAVE, ID_SAVEAS, ID_NOTEPAD = 1000, 1001, 1002, 1003
WM_APP_FRONT = 0x8000 + 1


def _wndproc(hwnd, msg, wp, lp):
    A = _S.api
    m = A.by_hwnd.get(hwnd) if A else None
    if m is not None:
        try:
            r = m.on_message(msg, wp, lp)
            if r is not None:
                return r
        except Exception:  # noqa: BLE001  (창 처리 오류가 본체를 죽이지 않게)
            pass
    return A.u.DefWindowProcW(hwnd, msg, wp, lp)


class Memo:
    """김비서 메모 창 하나(자기 스레드에서 돎)."""

    def __init__(self, d):
        self.dir = d
        self.path = new_memo_name(d)
        self.saved_once = False
        self.modified = False
        self.hwnd = None
        self.edit = None
        self.buttons = []
        self.fonts = []
        self.closed = False
        self.error = None
        self.dpi = 96
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="kimbiseo-memo", daemon=True)
        self.thread.start()

    # ---------------- 창 스레드
    def _run(self):
        A = _api()
        ct = A.ct
        try:
            try:   # 윈도우 기본 단추 모양(공용 컨트롤 6) — 안 되면 옛 모양으로
                sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
                ac = A.ACTCTXW(ct.sizeof(A.ACTCTXW), 0x4 | 0x8, os.path.join(sysdir, "shell32.dll"), 0, 0, sysdir, 124, None, None)
                h = A.k.CreateActCtxW(ct.byref(ac))
                if h and h != ct.c_void_p(-1).value:
                    cookie = ct.c_size_t(0)
                    A.k.ActivateActCtx(h, ct.byref(cookie))
                    ct.WinDLL("comctl32")
            except Exception:  # noqa: BLE001
                pass
            if A.dpi_ok:
                try:
                    A.u.SetThreadDpiAwarenessContext(ct.c_void_p(-4))   # 모니터마다 선명하게
                except Exception:  # noqa: BLE001
                    pass
            try:
                ct.windll.ole32.CoInitializeEx(None, 2)            # '다른 이름으로 저장' 창
            except Exception:  # noqa: BLE001
                pass
            with _S.lock:
                if A.cls is None:
                    wc = A.WNDCLASSEXW()
                    wc.cbSize = ct.sizeof(A.WNDCLASSEXW)
                    wc.style = 0x3
                    wc.lpfnWndProc = A.proc
                    wc.hInstance = A.hinst
                    wc.hCursor = A.u.LoadCursorW(None, ct.c_void_p(32512))
                    wc.hbrBackground = 16                         # COLOR_BTNFACE + 1
                    wc.lpszClassName = "KimBiseoMemoWindow"
                    ico = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                                        "pet", "renderer", "img", "icon.ico"))
                    if os.path.exists(ico):
                        wc.hIcon = A.u.LoadImageW(None, ico, 1, 0, 0, 0x10 | 0x40)
                        wc.hIconSm = A.u.LoadImageW(None, ico, 1, 16, 16, 0x10)
                    if not A.u.RegisterClassExW(ct.byref(wc)):
                        raise OSError("창 종류 등록 실패")
                    A.cls = "KimBiseoMemoWindow"
            hwnd = A.u.CreateWindowExW(0, A.cls, self._title(), 0x00CF0000, -2147483648, -2147483648, 680, 560,
                                       None, None, A.hinst, None)
            if not hwnd:
                raise OSError("창을 만들지 못함")
            self.hwnd = hwnd
            A.by_hwnd[hwnd] = self
            self.dpi = A.u.GetDpiForWindow(hwnd) if A.dpi_ok else 96
            child = 0x40000000 | 0x10000000 | 0x00010000        # WS_CHILD | WS_VISIBLE | WS_TABSTOP
            for bid, label in ((ID_SAVE, "저장 (Ctrl+S)"), (ID_SAVEAS, "다른 이름으로 저장"), (ID_NOTEPAD, "윈도우 메모장에서 열기")):
                b = A.u.CreateWindowExW(0, "BUTTON", label, child, 0, 0, 10, 10, hwnd, ct.c_void_p(bid), A.hinst, None)
                self.buttons.append(b)
            self.edit = A.u.CreateWindowExW(0x200, "EDIT", "", child | 0x00200000 | 0x4 | 0x40 | 0x1000 | 0x100,
                                            0, 0, 10, 10, hwnd, ct.c_void_p(ID_EDIT), A.hinst, None)
            if not self.edit:
                raise OSError("글 칸을 만들지 못함")
            A.u.SendMessageW(self.edit, EM_SETLIMITTEXT, 2_000_000, 0)
            self._fonts()
            if self.dpi != 96:
                A.u.SetWindowPos(hwnd, None, 0, 0, int(680 * self.dpi / 96), int(560 * self.dpi / 96), 0x2 | 0x4 | 0x10)
            self._layout()
            A.u.ShowWindow(hwnd, 5)
            A.u.ShowWindow(hwnd, 5)        # 숨김 시작 정보로 켜진 프로세스면 첫 번째는 무시될 수 있어 한 번 더
            self.front()
        except Exception as ex:  # noqa: BLE001
            self.error = f"{ex.__class__.__name__}: {ex}"
            self.closed = True
            self.ready.set()
            return
        self.ready.set()
        msg = A.W.MSG()
        while A.u.GetMessageW(ct.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_KEYDOWN and (A.u.GetKeyState(0x11) & 0x8000):
                if msg.wParam == 0x53:          # Ctrl+S
                    self.save()
                    continue
                if msg.wParam == 0x41 and msg.hWnd == self.edit:   # Ctrl+A
                    A.u.SendMessageW(self.edit, EM_SETSEL, 0, -1)
                    continue
            A.u.TranslateMessage(ct.byref(msg))
            A.u.DispatchMessageW(ct.byref(msg))
        self.closed = True
        A.by_hwnd.pop(self.hwnd, None)
        for f in self.fonts:
            A.g.DeleteObject(f)

    def _fonts(self):
        A = _api()
        for f in self.fonts:
            A.g.DeleteObject(f)
        px = lambda pt: -int(round(pt * self.dpi / 72))   # noqa: E731
        ui = A.g.CreateFontW(px(10), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "맑은 고딕")
        body = A.g.CreateFontW(px(12), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "맑은 고딕")
        self.fonts = [ui, body]
        for b in self.buttons:
            A.u.SendMessageW(b, WM_SETFONT, ui, 1)
        A.u.SendMessageW(self.edit, WM_SETFONT, body, 1)
        m = int(8 * self.dpi / 96)
        A.u.SendMessageW(self.edit, EM_SETMARGINS, 0x1 | 0x2, (m << 16) | m)

    def _layout(self):
        A = _api()
        r = A.W.RECT()
        A.u.GetClientRect(self.hwnd, A.ct.byref(r))
        s = self.dpi / 96
        pad, bh, gap = int(8 * s), int(34 * s), int(8 * s)
        widths = [int(118 * s), int(150 * s), int(186 * s)]
        x = pad
        for b, w in zip(self.buttons, widths):
            A.u.MoveWindow(b, x, pad, w, bh, 1)
            x += w + gap
        top = pad + bh + pad
        A.u.MoveWindow(self.edit, pad, top, max(10, r.right - 2 * pad), max(10, r.bottom - top - pad), 1)

    def _title(self):
        return ("* " if self.modified else "") + os.path.basename(self.path) + " - " + APP_TITLE

    def on_message(self, msg, wp, lp):
        A = _api()
        if msg == WM_SIZE and self.edit:
            self._layout()
            return 0
        if msg == WM_SETFOCUS and self.edit:
            A.u.SetFocus(self.edit)
            return 0
        if msg == WM_COMMAND:
            cid, code = wp & 0xFFFF, (wp >> 16) & 0xFFFF
            if cid == ID_EDIT and code == EN_CHANGE:
                if not self.modified:
                    self.modified = True
                    A.u.SetWindowTextW(self.hwnd, self._title())
                return 0
            if cid == ID_SAVE:
                self.save()
                return 0
            if cid == ID_SAVEAS:
                self.save_as()
                return 0
            if cid == ID_NOTEPAD:
                self.open_in_notepad()
                return 0
        if msg == WM_APP_FRONT:
            self.front()
            return 0
        if msg == WM_DPICHANGED:
            self.dpi = (wp >> 16) & 0xFFFF or 96
            rc = A.ct.cast(lp, A.ct.POINTER(A.W.RECT)).contents
            A.u.SetWindowPos(self.hwnd, None, rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top, 0x4 | 0x10)
            self._fonts()
            self._layout()
            return 0
        if msg == WM_CLOSE:
            if self.modified and self.text().strip():
                ans = A.u.MessageBoxW(self.hwnd, "적은 글을 저장할까요?\n" + self.path, APP_TITLE, 0x3 | 0x20)   # 예/아니요/취소
                if ans == 2:            # 취소
                    return 0
                if ans == 6 and not self.save():
                    return 0
            A.u.DestroyWindow(self.hwnd)
            return 0
        if msg == WM_DESTROY:
            A.u.PostQuitMessage(0)
            return 0
        return None

    # ---------------- 아무 스레드에서나
    def alive(self):
        A = _S.api
        return bool(A and self.hwnd and not self.closed and A.u.IsWindow(self.hwnd))

    def _send(self, hwnd, msg, wp, lp, ms=5000):
        A = _api()
        res = A.ct.c_size_t(0)
        ok = A.u.SendMessageTimeoutW(hwnd, msg, wp, lp, 0x0002, ms, A.ct.byref(res))   # SMTO_ABORTIFHUNG
        return res.value if ok else None

    def text(self):
        A = _api()
        n = self._send(self.edit, WM_GETTEXTLENGTH, 0, 0)
        if not n:
            return ""
        buf = A.ct.create_unicode_buffer(int(n) + 1)
        self._send(self.edit, WM_GETTEXT, int(n) + 1, A.ct.addressof(buf))
        return buf.value

    def append(self, body):
        """글 칸 끝에 붙임 → 늘어난 글자 수(실패 -1)."""
        A = _api()
        before = self._send(self.edit, WM_GETTEXTLENGTH, 0, 0)
        if before is None:
            return -1
        add = ("\r\n" if before else "") + body.replace("\n", "\r\n")
        buf = A.ct.create_unicode_buffer(add)
        self._send(self.edit, EM_SETSEL, before, before)
        self._send(self.edit, EM_REPLACESEL, 1, A.ct.addressof(buf), 8000)   # 되돌리기(Ctrl+Z) 가능
        self._send(self.edit, EM_SCROLLCARET, 0, 0)
        after = self._send(self.edit, WM_GETTEXTLENGTH, 0, 0)
        return -1 if after is None else int(after) - int(before)

    def save(self, path=None):
        A = _api()
        p = path or self.path
        try:
            save_file(p, self.text())
        except OSError as ex:
            if self.hwnd:
                A.u.MessageBoxW(self.hwnd, f"저장하지 못했어요({ex.__class__.__name__}).\n{p}", APP_TITLE, 0x10)
            return False
        self.path, self.saved_once, self.modified = p, True, False
        if self.hwnd:
            A.u.SetWindowTextW(self.hwnd, self._title())
        return True

    def save_as(self):
        A = _api()
        if A.cd is None:
            return False
        ct = A.ct
        flt = ct.create_unicode_buffer("텍스트 파일 (*.txt)\0*.txt\0모든 파일 (*.*)\0*.*\0\0")
        fbuf = ct.create_unicode_buffer(os.path.basename(self.path), 1024)
        init = ct.create_unicode_buffer(os.path.dirname(self.path))
        ttl = ct.create_unicode_buffer("다른 이름으로 저장")
        ext = ct.create_unicode_buffer("txt")
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            pass
        o = A.OPENFILENAMEW()
        o.lStructSize = ct.sizeof(A.OPENFILENAMEW)
        o.hwndOwner = self.hwnd
        o.lpstrFilter = ct.addressof(flt)
        o.nFilterIndex = 1
        o.lpstrFile = ct.addressof(fbuf)
        o.nMaxFile = 1024
        o.lpstrInitialDir = ct.addressof(init)
        o.lpstrTitle = ct.addressof(ttl)
        o.lpstrDefExt = ct.addressof(ext)
        o.Flags = 0x2 | 0x8 | 0x800 | 0x80000          # 덮어쓰기 물음 · 폴더 안 바꿈 · 경로 있어야 · 탐색기 모양
        if not A.cd.GetSaveFileNameW(ct.byref(o)):
            return False
        return self.save(fbuf.value)

    def open_in_notepad(self):
        """사용자가 단추를 눌렀을 때만 — 저장한 뒤 그 파일을 윈도우 메모장으로 연다."""
        if self.modified or not self.saved_once:
            if not self.save():
                return False
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
        try:
            subprocess.Popen([exe, self.path], close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def front(self):
        """창을 앞으로(이 창 스레드에서). 안 되면 작업 표시줄에서 깜빡이기만 함 — 쓰기에는 상관없음."""
        A = _api()
        if A.u.IsIconic(self.hwnd):
            A.u.ShowWindow(self.hwnd, 9)
        fg = A.u.GetForegroundWindow()
        me, other = A.k.GetCurrentThreadId(), A.u.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(other and other != me and A.u.AttachThreadInput(me, other, True))
        try:
            A.u.BringWindowToTop(self.hwnd)
            A.u.SetForegroundWindow(self.hwnd)
            if self.edit:
                A.u.SetFocus(self.edit)
        finally:
            if attached:
                A.u.AttachThreadInput(me, other, False)

    def ask_front(self):
        A = _api()
        A.u.PostMessageW(self.hwnd, WM_APP_FRONT, 0, 0)


# ================================================================ 도구가 쓰는 것(창 부분은 _new_window 로만 — 시험에서 바꿔 끼움)
def _new_window(d):
    return Memo(d)


def open_memo(d, wait=10.0):
    """새 김비서 메모 창 → (메모, None) 또는 (None, 실패 결과)."""
    if _api() is None:
        return None, fail("윈도우가 아님", "이 컴퓨터에서는 메모 창을 열 수 없어요.")
    with _S.lock:
        _S.memos[:] = [m for m in _S.memos if m.alive()]
        if len(_S.memos) >= MAX_WINDOWS:
            return None, fail("메모 창이 너무 많음", f"메모 창이 이미 {MAX_WINDOWS}개 열려 있어요. 하나를 닫고 다시 말씀해 주세요.")
    m = _new_window(d)
    if not m.ready.wait(wait) or not m.alive():
        return None, fail(f"메모 창을 못 띄움({m.error or '시간 초과'})", "메모 창이 열리지 않았어요.")
    with _S.lock:
        _S.memos.append(m)
    return m, None


def latest_memo():
    """아직 열려 있는 김비서 메모 창 가운데 가장 최근 것(없으면 None)."""
    with _S.lock:
        for m in reversed(_S.memos):
            if m.alive():
                return m
    return None


def open_result(d, dry=False):
    """'메모장 열어 줘' — 김비서 메모 창을 연다(열려 있는 빈 창이 있으면 그 창을 앞으로). 윈도우 메모장은 켜지 않음."""
    if dry_run(dry):
        return {"ok": True, "시험": True, "열었을것": "김비서 메모", "말": "(시험이라 실제로 열지 않음) 김비서 메모"}
    t0 = time.time()
    m = latest_memo()
    if m is not None and not m.text().strip():
        m.ask_front()
        return {"ok": True, "말": "김비서 메모장을 열었어요.", "새로_엶": False, "초": round(time.time() - t0, 2)}
    m, err = open_memo(d)
    if err:
        return err
    return {"ok": True, "말": "김비서 메모장을 열었어요.", "새로_엶": True, "초": round(time.time() - t0, 2),
            "안내": "메모장을 열었다고 한 문장으로 답한다. 저장은 Ctrl+S 또는 저장 단추."}


def type_memo(text, d, new=False, limit=MAX_CHARS, dry=False):
    """김비서 메모 창에 글을 써 넣는다(없으면 새 창). 늘 dict 를 돌려준다."""
    t0 = time.time()
    body, cut = clean_text(text, limit)
    if not body.strip():
        return fail("쓸 글 없음", "무엇을 적을지 말씀해 주세요.")
    if dry_run(dry):
        return {"ok": True, "시험": True, "쓸_글자": len(body), "잘림": cut, "말": "(시험이라 실제로 쓰지 않음) 김비서 메모에 적었을 것"}
    m = None if new else latest_memo()
    opened = False
    if m is None:
        m, err = open_memo(d)
        if err:
            return err
        opened = True
    n = m.append(body)
    if n <= 0:
        return fail("메모 창에 쓰지 못함", "메모 창에 적지 못했어요. 메모 창을 닫고 다시 말씀해 주세요.")
    if not opened:
        m.ask_front()
    r = {"ok": True, "글자": len(body), "방법": "김비서 메모 창", "새로_엶": opened, "메모": os.path.basename(m.path),
         "말": "메모장에 적었어요." + (" 너무 길어서 앞부분만 적었어요." if cut else ""),
         "안내": "메모장에 적었다고 한두 문장으로만 답한다(적은 글을 다시 읽어 주지 않는다). 저장은 사용자가 Ctrl+S 나 저장 단추로 한다.",
         "초": round(time.time() - t0, 2)}
    if cut:
        r["잘림"] = True
    return r
