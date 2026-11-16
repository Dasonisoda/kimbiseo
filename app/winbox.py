# 김비서 창의 옮기기·크기 조절·자리 기억 — 모니터마다 배율(100%·125%·150%)이 달라도 좌표가 틀어지지 않게 '진짜 픽셀'로만 계산한다.
#
# 왜 따로 만들었나(0.1.13 — 사용자 피드백 '다른 모니터로 옮기면 좌표가 틀어진다')
#   0.1.11 까지는 창 틀(pywebview)의 끌기를 썼다. 그 끌기는 화면(웹)이 알려 주는 좌표(ev.screenX — 배율로 나눈 값)에 '창이 있는 곳의 배율'
#   하나를 곱해 창을 옮기는데, 프로그램이 '시스템 배율만 아는' 방식(System DPI aware)으로 떠서 그 배율은 늘 주 모니터 값이었다.
#   → 주 모니터와 배율이 다른 모니터로 넘어가면 창이 커서에서 점점 멀어지고(배율 차이 × 거리), 윈도우가 창 그림을 늘리거나 줄여 보여 줘서
#     글자가 흐려지고 누르는 자리도 어긋났다. 음수 좌표(왼쪽·위 모니터)에서는 소수점을 0 쪽으로 버려 1픽셀씩 밀렸다.
#   고친 방법
#     ① 창 프로그램을 '모니터별 배율을 아는' 방식(Per-Monitor V2)으로 띄운다 → 윈도우가 좌표·그림을 바꿔 주지 않는다(set_dpi_awareness).
#     ② 끌기·크기 조절은 화면이 '시작/끝'만 알리고, 계산은 여기서 커서의 진짜 픽셀 좌표(GetCursorPos)와 창의 진짜 픽셀 사각형으로 한다.
#     ③ 창 크기는 '논리 크기(배율 100% 기준)'로 기억하고, 창이 놓인 모니터의 배율을 곱해 픽셀 크기를 정한다 → 어느 모니터에서도 같은 크기로 보인다.
#     ④ 자리 기억: 논리 크기 + 모니터 이름·그 모니터 안에서의 자리. 다음에 켤 때 그 모니터가 없거나 자리가 화면 밖이면 보이는 곳으로 옮긴다.
#   되돌리기: 설정 '화면.배율_방식' 을 "시스템" 으로 두면 ①을 건너뛴다(예전 방식 — 문제가 생긴 PC 에서 바로 되돌릴 수 있게).
#
# 계산 부분(아래 '순수 계산')은 윈도우 없이 돈다 — tests/unit/test_winbox.py 가 가짜 모니터 구성(배율 섞임·음수 좌표·세로 모니터·사라진 모니터)으로 시험한다.
import json
import os
import threading
import time

EDGES = ("n", "s", "e", "w", "ne", "nw", "se", "sw")
GRAB_STRIP = 48          # 창 위쪽 끌기 줄 높이(논리 픽셀) — 이 줄이 화면 안에 보여야 창을 다시 잡을 수 있음
KEEP_VISIBLE = 120       # 끌기 줄이 가로로 이만큼(논리 픽셀)은 화면 안에 보이게


# ================================================================ 순수 계산(윈도우 호출 없음)
def scale_of(dpi):
    return (dpi or 96) / 96.0


def _area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def _dist2(rect, pt):
    dx = max(rect[0] - pt[0], 0, pt[0] - (rect[2] - 1))
    dy = max(rect[1] - pt[1], 0, pt[1] - (rect[3] - 1))
    return dx * dx + dy * dy


def monitor_at(pt, monitors):
    """그 점이 있는 모니터(없으면 가장 가까운 모니터)."""
    return min(monitors, key=lambda m: _dist2(m["rect"], pt))


def monitor_for_rect(rect, monitors):
    """그 사각형이 가장 많이 걸친 모니터(하나도 안 걸치면 가운데 점에서 가장 가까운 모니터)."""
    best = max(monitors, key=lambda m: _area(rect, m["rect"]))
    if _area(rect, best["rect"]) > 0:
        return best
    return monitor_at(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2), monitors)


def primary(monitors):
    return next((m for m in monitors if m.get("primary")), monitors[0])


def fit_rect(rect, monitors, min_logical=(340, 480)):
    """창 사각형(픽셀)을 '다시 잡을 수 있는 자리'로: 가장 많이 걸친 모니터의 작업 영역보다 크면 줄이고,
    위쪽 끌기 줄이 화면 안에 보이게(위로 벗어나지 않게 · 가로로 KEEP_VISIBLE 만큼은 보이게) 옮긴다. → (l, t, r, b)"""
    m = monitor_for_rect(rect, monitors)
    wl, wt, wr, wb = m["work"]
    k = scale_of(m["dpi"])
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    w = max(min(w, wr - wl), min(int(round(min_logical[0] * k)), wr - wl))
    h = max(min(h, wb - wt), min(int(round(min_logical[1] * k)), wb - wt))
    keep = min(w, int(round(KEEP_VISIBLE * k)))
    strip = int(round(GRAB_STRIP * k))
    left = min(max(rect[0], wl - (w - keep)), wr - keep)
    top = min(max(rect[1], wt), max(wt, wb - strip))
    return (int(left), int(top), int(left + w), int(top + h))


def center_rect(size_logical, mon):
    """그 모니터 작업 영역 가운데에 놓은 사각형(픽셀)."""
    k = scale_of(mon["dpi"])
    wl, wt, wr, wb = mon["work"]
    w = min(int(round(size_logical[0] * k)), wr - wl)
    h = min(int(round(size_logical[1] * k)), wb - wt)
    left = wl + (wr - wl - w) // 2
    top = wt + (wb - wt - h) // 2
    return (left, top, left + w, top + h)


def remembered(rect, monitors):
    """지금 창 사각형(픽셀) → 기억할 값: 논리 크기 + 모니터 이름·사각형·배율 + 그 모니터 왼쪽 위에서의 논리 거리."""
    m = monitor_for_rect(rect, monitors)
    k = scale_of(m["dpi"])
    return {"v": 1, "w": round((rect[2] - rect[0]) / k), "h": round((rect[3] - rect[1]) / k),
            "ox": round((rect[0] - m["rect"][0]) / k), "oy": round((rect[1] - m["rect"][1]) / k),
            "mon": {"name": m.get("name", ""), "rect": list(m["rect"]), "dpi": int(m["dpi"])}}


def restore_rect(saved, monitors, default_logical=(400, 680), min_logical=(340, 480), max_logical=(4000, 4000)):
    """기억한 값 → 이번에 창을 놓을 사각형(픽셀) 과 이유. 기억이 없거나 못 쓰면 주 모니터 가운데(기본 크기).
    같은 이름의 모니터가 있으면 그 모니터 안 같은 자리(배율이 바뀌었어도 논리 크기 그대로),
    이름은 없지만 같은 사각형의 모니터가 있으면 그곳, 둘 다 없으면(모니터를 뺐음) 주 모니터 가운데."""
    try:
        w, h = int(saved["w"]), int(saved["h"])
        ox, oy = int(saved["ox"]), int(saved["oy"])
        sm = saved.get("mon") or {}
        if not (min_logical[0] <= w <= max_logical[0] and min_logical[1] <= h <= max_logical[1]):
            raise ValueError("크기")
    except (KeyError, TypeError, ValueError):
        return fit_rect(center_rect(default_logical, primary(monitors)), monitors, min_logical), "기억 없음 → 주 모니터 가운데"
    m = next((x for x in monitors if x.get("name") and x.get("name") == sm.get("name")), None)
    why = "기억한 모니터 그대로"
    if m is None:
        m = next((x for x in monitors if list(x["rect"]) == list(sm.get("rect") or [])), None)
        why = "이름은 다르지만 같은 자리의 모니터"
    if m is None:
        return fit_rect(center_rect((w, h), primary(monitors)), monitors, min_logical), "기억한 모니터가 없음 → 주 모니터 가운데"
    k = scale_of(m["dpi"])
    left = m["rect"][0] + int(round(ox * k))
    top = m["rect"][1] + int(round(oy * k))
    rect = (left, top, left + int(round(w * k)), top + int(round(h * k)))
    fitted = fit_rect(rect, monitors, min_logical)
    if monitor_for_rect(fitted, monitors) is not m:        # 모니터 배치가 바뀌어 기억한 자리가 다른 모니터로 넘어감 → 그 모니터 가운데
        return fit_rect(center_rect((w, h), m), monitors, min_logical), "기억한 자리가 화면 밖 → 그 모니터 가운데"
    return fitted, why + ("" if fitted == rect else " · 화면 안으로 조금 옮김")


def drag_rect(grab_logical, size_logical, cursor, monitors):
    """끌기: 커서가 창의 같은 곳(grab — 창 왼쪽 위에서의 논리 거리)을 계속 잡고 있게 한 사각형(픽셀).
    커서가 있는 모니터의 배율로 창 크기와 잡은 곳을 계산한다 → 배율이 다른 모니터로 넘어가도 커서와 창이 떨어지지 않는다."""
    m = monitor_at(cursor, monitors)
    k = scale_of(m["dpi"])
    w, h = int(round(size_logical[0] * k)), int(round(size_logical[1] * k))
    left = cursor[0] - int(round(grab_logical[0] * k))
    top = cursor[1] - int(round(grab_logical[1] * k))
    # 끌기 줄이 작업 영역 위로 숨지 않게(작업 표시줄 아래로는 내려가도 끌기 줄은 남게)
    work = m["work"]
    top = min(max(top, work[1]), max(work[1], work[3] - int(round(GRAB_STRIP * k))))
    return (left, top, left + w, top + h), m


def resize_rect(start, start_cursor, cursor, edge, min_px, work=None):
    """크기 조절: 잡은 가장자리(edge = n·s·e·w·ne·nw·se·sw)만 커서를 따라 움직인 사각형(픽셀). 최소 크기 아래로는 안 줄어듦.
    work(작업 영역)를 주면 위쪽 가장자리가 그 위로 나가지 않는다."""
    l, t, r, b = start
    dx, dy = cursor[0] - start_cursor[0], cursor[1] - start_cursor[1]
    if "e" in edge:
        r = max(r + dx, l + min_px[0])
    if "w" in edge:
        l = min(l + dx, r - min_px[0])
    if "s" in edge:
        b = max(b + dy, t + min_px[1])
    if "n" in edge:
        t = min(t + dy, b - min_px[1])
        if work is not None:
            t = max(t, work[1])
    return (int(l), int(t), int(r), int(b))


# ================================================================ 윈도우 쪽(ctypes)
def set_dpi_awareness(mode="모니터별"):
    """창을 만들기 전에(첫 창이 생기기 전 한 번만 정해짐) 부른다. → 실제로 정해진 방식 글.
    "모니터별": Per-Monitor V2 → 안 되면 Per-Monitor → 안 되면 System. "시스템": 건드리지 않음(창 틀이 System 으로 정함)."""
    if os.name != "nt" or str(mode) == "시스템":
        return "시스템(예전 방식)"
    import ctypes
    try:
        f = ctypes.windll.user32.SetProcessDpiAwarenessContext
        f.argtypes = [ctypes.c_void_p]
        f.restype = ctypes.c_int
        if f(ctypes.c_void_p(-4)):          # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return "모니터별(V2)"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:      # PROCESS_PER_MONITOR_DPI_AWARE
            return "모니터별"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass
    return "시스템"


def test_monitors():
    """시험 전용: 환경변수 KIMBISEO_TEST_WINDOW=1 이고 KIMBISEO_TEST_MONITORS 가 JSON 파일을 가리키면 그 가짜 모니터 구성을 쓴다(부를 때마다 다시 읽음).
    진짜 창으로 '배율이 섞인 여러 모니터·음수 좌표·모니터 빼기'를 시험하고, 시험 창을 사용자 화면 밖에 두려고 둔 것. 보통 실행에서는 None."""
    if os.environ.get("KIMBISEO_TEST_WINDOW") != "1" or not os.environ.get("KIMBISEO_TEST_MONITORS"):
        return None
    try:
        with open(os.environ["KIMBISEO_TEST_MONITORS"], encoding="utf-8") as f:
            raw = json.load(f)
        out = [{"name": str(m.get("name", "")), "rect": tuple(int(v) for v in m["rect"]), "work": tuple(int(v) for v in m.get("work") or m["rect"]),
                "dpi": int(m.get("dpi", 96)), "primary": bool(m.get("primary"))} for m in raw]
        return out if out and all(len(m["rect"]) == 4 and len(m["work"]) == 4 for m in out) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


class Win32Env:
    """진짜 윈도우에서 읽고 쓰는 것 — 시험에서는 같은 모양의 가짜(FakeEnv)로 바꿔 끼운다. 좌표는 모두 진짜 픽셀."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c, self.wt = ctypes, wintypes
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.u32.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.u32.GetDpiForWindow.restype = wintypes.UINT
        self.u32.IsIconic.argtypes = [wintypes.HWND]
        self.u32.IsZoomed.argtypes = [wintypes.HWND]
        self.u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.u32.GetAsyncKeyState.restype = ctypes.c_short

    def cursor(self):
        p = self.wt.POINT()
        self.u32.GetCursorPos(self.c.byref(p))
        return (p.x, p.y)

    def button_down(self):
        vk = 0x02 if self.u32.GetSystemMetrics(23) else 0x01     # 왼손잡이 설정(SM_SWAPBUTTON)이면 오른쪽 단추가 '주 단추'
        return bool(self.u32.GetAsyncKeyState(vk) & 0x8000)

    def rect(self, hwnd):
        r = self.wt.RECT()
        if not self.u32.GetWindowRect(hwnd, self.c.byref(r)):
            return None
        return (r.left, r.top, r.right, r.bottom)

    def set_rect(self, hwnd, rect):
        SWP = 0x0004 | 0x0010 | 0x0200       # NOZORDER | NOACTIVATE | NOOWNERZORDER
        return bool(self.u32.SetWindowPos(hwnd, None, int(rect[0]), int(rect[1]), int(rect[2] - rect[0]), int(rect[3] - rect[1]), SWP))

    def dpi(self, hwnd):
        try:
            return int(self.u32.GetDpiForWindow(hwnd)) or 96
        except (AttributeError, OSError):
            return 96

    def busy(self, hwnd):
        """내려 둔(최소화) 창·가득 채운(최대화) 창은 옮기거나 기억하지 않는다."""
        return bool(self.u32.IsIconic(hwnd) or self.u32.IsZoomed(hwnd))

    def monitors(self):
        fake = test_monitors()
        if fake:
            return fake
        c, wt = self.c, self.wt

        class MONITORINFOEXW(c.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]

        out = []
        proc_t = c.WINFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p, c.POINTER(wt.RECT), c.c_void_p)

        def cb(hmon, _hdc, _rc, _lp):
            mi = MONITORINFOEXW()
            mi.cbSize = c.sizeof(MONITORINFOEXW)
            if self.u32.GetMonitorInfoW(c.c_void_p(hmon), c.byref(mi)):
                dx, dy = wt.UINT(96), wt.UINT(96)
                try:
                    c.windll.shcore.GetDpiForMonitor(c.c_void_p(hmon), 0, c.byref(dx), c.byref(dy))     # MDT_EFFECTIVE_DPI
                except (AttributeError, OSError):
                    pass
                m, w = mi.rcMonitor, mi.rcWork
                out.append({"name": mi.szDevice, "rect": (m.left, m.top, m.right, m.bottom), "work": (w.left, w.top, w.right, w.bottom),
                            "dpi": int(dx.value) or 96, "primary": bool(mi.dwFlags & 1)})
            return 1
        self.u32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
        if not out:
            out.append({"name": "", "rect": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1040), "dpi": 96, "primary": True})
        return out


class WinBox:
    """창 하나의 옮기기·크기 조절·자리 기억. 화면(JS)은 drag_start/drag_end · resize_start(edge)/resize_end 만 부른다.
    env = Win32Env(진짜) 또는 시험용 가짜. hwnd 는 bind() 로 받는다(창이 만들어진 뒤)."""

    TICK = 0.008

    def __init__(self, store_path, default=(400, 680), minimum=(340, 480), remember=True, env=None, log=None):
        self.store = store_path
        self.default, self.minimum = tuple(default), tuple(minimum)
        self.remember = bool(remember)
        self.env = env
        self.log = log or (lambda *a: None)
        self.hwnd = None
        self.size = tuple(default)          # 논리 크기(배율 100% 기준) — 어느 모니터에서도 이 크기로 보이게
        self.dpi = 96
        self._job = None                    # (종류, 멈춤 표시)
        self._lock = threading.Lock()
        self.fake = None                    # 시험용 가짜 커서 {"pos": (x, y), "down": bool} — set_fake 로만
        self.moves = 0

    # ---- 기억
    def load(self):
        if not self.remember or not self.store:
            return None
        try:
            with open(self.store, encoding="utf-8") as f:
                j = json.load(f)
            return j if isinstance(j, dict) else None
        except (OSError, ValueError):
            return None

    def save(self):
        """지금 자리·크기를 기억 파일에. 내려 둔 창·기억 끔이면 안 적는다."""
        if not self.remember or not self.store or self.hwnd is None or self.env.busy(self.hwnd):
            return None
        rect = self.env.rect(self.hwnd)
        if not rect or rect[2] - rect[0] < 50:
            return None
        rec = remembered(rect, self.env.monitors())
        rec["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs(os.path.dirname(self.store), exist_ok=True)
            tmp = self.store + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.store)
        except OSError as ex:
            self.log("창 자리 기억 실패", ex.__class__.__name__)
            return None
        return rec

    # ---- 창에 붙이기
    def bind(self, hwnd):
        """창이 만들어진 뒤(보이기 전) 한 번: 기억한 자리·크기로 놓는다."""
        self.hwnd = hwnd
        mons = self.env.monitors()
        rect, why = restore_rect(self.load() or {}, mons, self.default, self.minimum)
        self.env.set_rect(hwnd, rect)
        self._adopt(rect, mons)
        self.log(f"창 자리: {why} · {rect[2] - rect[0]}x{rect[3] - rect[1]}px @({rect[0]},{rect[1]}) · 배율 {self.dpi / 96:.2f} · 모니터 {len(mons)}개")
        return rect

    def _adopt(self, rect, mons=None):
        m = monitor_for_rect(rect, mons or self.env.monitors())
        self.dpi = int(m["dpi"])
        k = scale_of(self.dpi)
        self.size = (round((rect[2] - rect[0]) / k), round((rect[3] - rect[1]) / k))

    def settle(self, save=True):
        """창이 우리 끌기 말고 다른 까닭(Win+Shift+화살표 · 모니터 빼기 · 배율 바꾸기)으로 옮겨졌을 때 맞춤:
        배율이 바뀌었으면 논리 크기에 맞게 픽셀 크기를 다시 정하고, 화면 밖이면 보이는 곳으로. → 바꿨으면 새 사각형."""
        if self.hwnd is None or self._job is not None or self.env.busy(self.hwnd):
            return None
        rect = self.env.rect(self.hwnd)
        if not rect:
            return None
        mons = self.env.monitors()
        want = rect
        for _ in range(3):                                  # 크기를 바꾸면 '가장 많이 걸친 모니터'가 바뀔 수 있어 몇 번만 다시 봄
            m = monitor_for_rect(want, mons)
            k = scale_of(m["dpi"])
            w, h = int(round(self.size[0] * k)), int(round(self.size[1] * k))
            nxt = fit_rect((want[0], want[1], want[0] + w, want[1] + h), mons, self.minimum)
            if nxt == want:
                break
            want = nxt
        self.dpi = int(monitor_for_rect(want, mons)["dpi"])
        if want != rect:
            self.env.set_rect(self.hwnd, want)
            self.log(f"창 맞춤: {rect} → {want} (배율 {self.dpi / 96:.2f})")
            if save:
                self.save()
            return want
        return None

    # ---- 끌기·크기 조절
    def _cursor(self):
        return tuple(self.fake["pos"]) if self.fake else self.env.cursor()

    def _down(self):
        return bool(self.fake["down"]) if self.fake else self.env.button_down()

    def set_fake(self, x, y, down=True):
        """시험용: 진짜 마우스 대신 이 커서를 쓴다(down=False 면 단추를 뗀 것). None 을 주면 진짜 마우스로."""
        self.fake = None if x is None else {"pos": (int(x), int(y)), "down": bool(down)}
        return True

    def start(self, kind, edge=""):
        if self.hwnd is None or self.env.busy(self.hwnd) or kind not in ("drag", "resize") or (kind == "resize" and edge not in EDGES):
            return False
        with self._lock:
            if self._job is not None:
                return False
            stop = threading.Event()
            self._job = (kind, stop)
        t = threading.Thread(target=self._run, args=(kind, edge, stop), name="win-" + kind, daemon=True)
        t.start()
        return True

    def stop(self):
        with self._lock:
            job = self._job
        if job:
            job[1].set()
        return True

    def step(self, kind, edge, st):
        """한 번 움직임(끌기 루프가 부름 · 시험은 직접 부름). st = begin() 이 만든 시작 상태. → 놓은 사각형."""
        cur = self._cursor()
        mons = st["mons"]
        if kind == "drag":
            rect, m = drag_rect(st["grab"], self.size, cur, mons)
            self.dpi = int(m["dpi"])
        else:
            k = scale_of(st["dpi"])
            min_px = (int(round(self.minimum[0] * k)), int(round(self.minimum[1] * k)))
            rect = resize_rect(st["rect"], st["cursor"], cur, edge, min_px, st["work"])
        if rect != st.get("last"):
            self.env.set_rect(self.hwnd, rect)
            st["last"] = rect
            self.moves += 1
        return rect

    def begin(self, kind):
        rect = self.env.rect(self.hwnd)
        mons = self.env.monitors()
        cur = self._cursor()
        m = monitor_for_rect(rect, mons)
        k = scale_of(m["dpi"])
        self._adopt(rect, mons)
        return {"rect": rect, "cursor": cur, "mons": mons, "dpi": int(m["dpi"]), "work": m["work"], "last": rect,
                "grab": ((cur[0] - rect[0]) / k, (cur[1] - rect[1]) / k)}

    def finish(self, kind):
        """끌기·크기 조절이 끝난 뒤: 크기 조절이면 새 논리 크기를 받아들이고, 화면 밖·배율 어긋남을 맞춘 뒤 자리 기억."""
        rect = self.env.rect(self.hwnd)
        if rect and kind == "resize":
            self._adopt(rect)
        with self._lock:
            self._job = None
        self.settle(save=False)
        return self.save()

    def _run(self, kind, edge, stop):
        try:
            st = self.begin(kind)
            t_end = time.time() + 600                       # 단추를 뗀 것을 놓쳐도 10분 뒤에는 끝남
            while not stop.is_set() and self._down() and time.time() < t_end:
                self.step(kind, edge, st)
                time.sleep(self.TICK)
            self.step(kind, edge, st)
        except Exception as ex:  # noqa: BLE001
            self.log("창 옮기기 오류", repr(ex))
        finally:
            try:
                self.finish(kind)
            except Exception as ex:  # noqa: BLE001
                self.log("창 자리 맞춤 오류", repr(ex))
                with self._lock:
                    self._job = None

    def info(self):
        rect = self.env.rect(self.hwnd) if self.hwnd is not None else None
        return {"rect": list(rect) if rect else None, "size": list(self.size), "dpi": self.dpi, "moving": self._job[0] if self._job else "",
                "moves": self.moves, "min": list(self.minimum), "remember": self.remember}
