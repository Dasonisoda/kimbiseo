# 김비서 창 — 본체 화면(http://127.0.0.1:<본체 포트>/)을 pywebview(엣지 WebView2) 창으로 연다.
#   python -m app.shell [--settings 설정.json] [--start-body] [--debug-port N] [--hidden]
#   - 마이크 권한: 이 창의 본체 화면(정확히 같은 출처)이 마이크를 물을 때만 묻지 않고 허용, 나머지 권한은 모두 거부.
#   - --start-body: 본체가 안 켜져 있으면 창 없이 켜고(PID 기록), 창을 닫으면 자기가 켠 본체만 끈다.
#   - 메아리 지우기(에코 제거)는 화면(audio.js)이 마이크를 열 때 켜고 getSettings() 로 확인해 화면·본체 기록에 남긴다.
#   - --debug-port: 시험용(DevTools 로 붙어 화면을 확인). --hidden: 시험용(창을 숨김).
#   - 창 옮기기·크기 조절·자리 기억(0.1.13~): app/winbox.py — 모니터마다 배율이 달라도 진짜 픽셀로 계산해 좌표가 틀어지지 않게.
#     화면(start.js)은 위쪽 줄을 누르면 drag_start, 가장자리를 누르면 resize_start(방향)만 부르고, 놓으면 drag_end·resize_end.
#     크기·자리는 자료 폴더 window.json 에 기억(설정 화면.창_기억 false 면 기억 안 함).
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import winbox  # noqa: E402
from app.core import config as C  # noqa: E402

TITLE = "김비서"
WINDOW_SIZE = (400, 680)   # 처음 크기 — 테두리 없는 작은 검은 창(내리기·끄기 단추는 화면 위 줄). 가장자리를 끌면 크기가 바뀜(winbox)
WINDOW_MIN = (340, 480)    # 이보다 작게는 안 줄어듦
LOG = None


def window_size():
    """화면(작업 영역)이 작거나 배율이 커서 680 이 안 들어가면 높이를 줄인다 — 아래 입력줄이 화면 밖으로 나가지 않게."""
    w, hh = WINDOW_SIZE
    try:
        import ctypes
        from ctypes import wintypes
        rc = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0)    # SPI_GETWORKAREA(작업 표시줄 뺀 곳)
        dpi = ctypes.windll.user32.GetDpiForSystem() or 96
        avail_h = (rc.bottom - rc.top) * 96 / dpi                                    # 창 크기와 같은 논리 단위로
        avail_w = (rc.right - rc.left) * 96 / dpi
        if avail_h > 0:
            hh = int(max(WINDOW_MIN[1], min(hh, avail_h - 24)))
        if avail_w > 0:
            w = int(max(WINDOW_MIN[0], min(w, avail_w - 24)))
    except Exception:  # noqa: BLE001
        pass
    return w, hh


class WinApi:
    """화면 위 줄의 내리기·끄기 단추 + 창 옮기기·크기 조절(테두리 없는 창이라 윈도우 제목줄·테두리가 없음)."""

    def __init__(self, win=None, box=None):
        self._win = win if win is not None else {}
        self._box = box          # winbox.WinBox(없으면 옮기기·크기 조절 단추가 화면에 안 생김)

    def minimize(self):
        if self._win.get("w") is not None:
            self._win["w"].minimize()
        return True

    def close(self):
        if self._box is not None:
            self._box.save()
        if self._win.get("w") is not None:
            self._win["w"].destroy()
        return True

    # ---- 창 옮기기·크기 조절: 화면은 시작·끝만 알리고, 계산은 winbox 가 커서·창의 진짜 픽셀 좌표로 한다
    def drag_start(self):
        return bool(self._box and self._box.start("drag"))

    def drag_end(self):
        return bool(self._box and self._box.stop())

    def resize_start(self, edge):
        return bool(self._box and self._box.start("resize", str(edge or "")))

    def resize_end(self):
        return bool(self._box and self._box.stop())

    def win_info(self):
        """창 자리·크기·배율(시험·문제 해결용)."""
        return self._box.info() if self._box else None

    def win_test_cursor(self, x=None, y=None, down=True):
        """시험 전용(환경변수 KIMBISEO_TEST_WINDOW=1 일 때만): 진짜 마우스 대신 이 좌표를 커서로 쓴다. x 없이 부르면 진짜 마우스로."""
        if self._box is None or os.environ.get("KIMBISEO_TEST_WINDOW") != "1":
            return False
        return self._box.set_fake(x, y, down)

    def win_test_move(self, x, y):
        """시험 전용(KIMBISEO_TEST_WINDOW=1 일 때만): 윈도우가 창을 옮겨 놓은 것처럼(우리 끌기 말고) 창을 그 좌표로 옮긴다."""
        b = self._box
        if b is None or b.hwnd is None or os.environ.get("KIMBISEO_TEST_WINDOW") != "1":
            return False
        r = b.env.rect(b.hwnd)
        return bool(r and b.env.set_rect(b.hwnd, (int(x), int(y), int(x) + r[2] - r[0], int(y) + r[3] - r[1])))


def make_box(cfg, logf=None):
    """설정에서 창 기억 여부를 읽어 winbox.WinBox 를 만든다(윈도우가 아니면 None)."""
    if os.name != "nt":
        return None
    sc = cfg.get("화면") or {}
    return winbox.WinBox(os.path.join(C.path(cfg, "자료"), "window.json"), WINDOW_SIZE, WINDOW_MIN,
                         remember=sc.get("창_기억", True) is not False, env=winbox.Win32Env(), log=logf or log)


def attach_box(window, box):
    """창이 만들어진 뒤(보이기 전) 기억한 자리·크기로 놓고, 닫을 때·다른 까닭으로 옮겨졌을 때 맞춘다."""
    if box is None:
        return
    import threading
    timer = {"t": None}

    def before_show():
        try:
            from System.Drawing import Size
            window.native.MinimumSize = Size(1, 1)      # 최소 크기는 winbox 가 모니터 배율에 맞춰 지킴(창 틀의 값은 만든 모니터 배율로 굳어 있음)
            box.bind(int(window.native.Handle.ToInt64()))
        except Exception as ex:  # noqa: BLE001
            log("창 자리 놓기 실패", repr(ex))

    def later(*_a):
        if timer["t"] is not None:
            timer["t"].cancel()
        timer["t"] = threading.Timer(0.6, lambda: _quiet(box.settle))      # Win+Shift+화살표·모니터 빼기·배율 바꾸기 뒤
        timer["t"].daemon = True
        timer["t"].start()

    def _quiet(fn):
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            log("창 맞춤 실패", repr(ex))

    window.events.before_show += before_show
    window.events.moved += later
    window.events.resized += later
    window.events.restored += later
    window.events.closing += lambda: _quiet(box.save)


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except (OSError, TypeError):
        pass


def body_up(base):
    try:
        j = json.loads(urllib.request.urlopen(base + "/api/status", timeout=2).read())
        return bool(j.get("ok"))
    except Exception:  # noqa: BLE001
        return False


def start_body(settings):
    py = sys.executable.replace("pythonw.exe", "python.exe")
    args = [py, "-B", "-X", "utf8", "-m", "app.main", "serve"] + (["--settings", settings] if settings else [])
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    p = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, env={**os.environ, "PYTHONUTF8": "1"})
    log("본체 켬 PID", p.pid)
    return p


def patch_permissions(origin):
    """WebView2 권한 요청 — origin(예: http://127.0.0.1:8870) 화면의 마이크만 허용."""
    from webview.platforms import edgechromium as ec

    orig = ec.EdgeChrome.on_webview_ready

    def patched(self, sender, args):
        orig(self, sender, args)
        if not args.IsSuccess:
            return
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState

        def on_perm(_s, a):
            uri = str(a.Uri)
            ok = a.PermissionKind == CoreWebView2PermissionKind.Microphone and (uri == origin or uri.startswith(origin + "/"))
            a.State = CoreWebView2PermissionState.Allow if ok else CoreWebView2PermissionState.Deny
            log("권한 요청", a.PermissionKind, uri, "허용" if ok else "거부")

        sender.CoreWebView2.PermissionRequested += on_perm

    ec.EdgeChrome.on_webview_ready = patched


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=None)
    ap.add_argument("--start-body", action="store_true")
    ap.add_argument("--debug-port", type=int, default=0)
    ap.add_argument("--hidden", action="store_true")
    a = ap.parse_args()
    cfg = C.load(a.settings, warn=lambda m: None)
    port = int(cfg["포트"]["본체"])
    origin = f"http://127.0.0.1:{port}"
    LOG = os.path.join(C.path(cfg, "로그"), "창.log")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    dpi_mode = winbox.set_dpi_awareness((cfg.get("화면") or {}).get("배율_방식", "모니터별"))    # 창을 만들기 전에(창 틀을 불러오기 전에)
    log("==== 창 시작", origin, "· 배율 방식", dpi_mode)

    mine = None
    if not body_up(origin):
        if a.start_body:
            mine = start_body(a.settings)
            for _ in range(240):
                if body_up(origin):
                    break
                time.sleep(0.5)
        else:
            log("본체가 꺼져 있음 — 화면이 기다림 안내를 보여 줌")

    import webview
    patch_permissions(origin)
    if a.debug_port:
        webview.settings["REMOTE_DEBUGGING_PORT"] = a.debug_port
    win = {"w": None}
    ww, wh = window_size()
    box = make_box(cfg)
    win["w"] = webview.create_window(TITLE, origin + "/", js_api=WinApi(win, box), width=ww, height=wh,
                                     min_size=WINDOW_MIN, frameless=True, easy_drag=False, hidden=a.hidden,
                                     background_color="#0B0C0F", text_select=True)
    attach_box(win["w"], box)
    try:
        webview.start(private_mode=False, storage_path=os.path.join(C.path(cfg, "캐시"), "창"))
    finally:
        if mine is not None and mine.poll() is None:
            subprocess.run(["taskkill", "/PID", str(mine.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            log("내가 켠 본체 끔 PID", mine.pid)
        log("==== 창 닫힘")


if __name__ == "__main__":
    main()
