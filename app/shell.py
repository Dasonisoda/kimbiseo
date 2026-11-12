# 김비서 창 — 본체 화면(http://127.0.0.1:<본체 포트>/)을 pywebview(엣지 WebView2) 창으로 연다.
#   python -m app.shell [--settings 설정.json] [--start-body] [--debug-port N] [--hidden]
#   - 마이크 권한: 이 창의 본체 화면(정확히 같은 출처)이 마이크를 물을 때만 묻지 않고 허용, 나머지 권한은 모두 거부.
#   - --start-body: 본체가 안 켜져 있으면 창 없이 켜고(PID 기록), 창을 닫으면 자기가 켠 본체만 끈다.
#   - 메아리 지우기(에코 제거)는 화면(audio.js)이 마이크를 열 때 켜고 getSettings() 로 확인해 화면·본체 기록에 남긴다.
#   - --debug-port: 시험용(DevTools 로 붙어 화면을 확인). --hidden: 시험용(창을 숨김).
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

from app.core import config as C  # noqa: E402

TITLE = "김비서"
WINDOW_SIZE = (400, 680)   # 테두리 없는 작은 검은 창(내리기·끄기 단추는 화면 위 줄). 테두리 없는 창은 크기를 못 바꿈
WINDOW_MIN = (340, 480)
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
    """화면 위 줄의 내리기·끄기 단추용(테두리 없는 창이라 윈도우 제목줄 단추가 없음)."""

    def __init__(self, win=None):
        self._win = win if win is not None else {}

    def minimize(self):
        if self._win.get("w") is not None:
            self._win["w"].minimize()
        return True

    def close(self):
        if self._win.get("w") is not None:
            self._win["w"].destroy()
        return True


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
    log("==== 창 시작", origin)

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
    win["w"] = webview.create_window(TITLE, origin + "/", js_api=WinApi(win), width=ww, height=wh,
                                     min_size=WINDOW_MIN, frameless=True, easy_drag=False, hidden=a.hidden,
                                     background_color="#0B0C0F", text_select=True)
    try:
        webview.start(private_mode=False, storage_path=os.path.join(C.path(cfg, "캐시"), "창"))
    finally:
        if mine is not None and mine.poll() is None:
            subprocess.run(["taskkill", "/PID", str(mine.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            log("내가 켠 본체 끔 PID", mine.pid)
        log("==== 창 닫힘")


if __name__ == "__main__":
    main()
