# 김비서 창 옮기기·크기 조절·자리 기억 단위 시험 — 가짜 모니터 구성으로(윈도우 호출 없음).   python -B -m tests.unit.test_winbox
#   배율이 섞인 모니터(100%·125%·150%) · 음수 좌표(왼쪽·위 모니터) · 세로 모니터 · 기억한 모니터가 사라짐 · 최소 크기 · 화면 밖 되찾기.
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from app import winbox as W  # noqa: E402

OK = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


def mon(name, x, y, w, h, dpi=96, primary=False, taskbar=40):
    k = dpi / 96
    return {"name": name, "rect": (x, y, x + w, y + h), "work": (x, y, x + w, y + h - int(taskbar * k)), "dpi": dpi, "primary": primary}


# 주 모니터(100%) 오른쪽에 150% 모니터, 왼쪽에 세로 125% 모니터(음수 좌표 · 위로 300 올라가 있음), 위에 100% 모니터(음수 y)
MAIN = mon(r"\\.\DISPLAY1", 0, 0, 1920, 1080, 96, True)
RIGHT = mon(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 144)
LEFT = mon(r"\\.\DISPLAY3", -1080, -300, 1080, 1920, 120)
TOP = mon(r"\\.\DISPLAY4", 200, -1080, 1920, 1080, 96)
ALL = [MAIN, RIGHT, LEFT, TOP]


class FakeEnv:
    """Win32Env 와 같은 모양의 가짜 — 창 사각형·커서·모니터를 기억만 한다."""

    def __init__(self, monitors, rect=(100, 100, 500, 780)):
        self.mons, self.r, self.cur, self.down, self.is_busy, self.sets = list(monitors), tuple(rect), (0, 0), True, False, []

    def monitors(self):
        return list(self.mons)

    def rect(self, hwnd):
        return self.r

    def set_rect(self, hwnd, rect):
        self.r = tuple(int(v) for v in rect)
        self.sets.append(self.r)
        return True

    def cursor(self):
        return self.cur

    def button_down(self):
        return self.down

    def busy(self, hwnd):
        return self.is_busy

    def dpi(self, hwnd):
        return W.monitor_for_rect(self.r, self.mons)["dpi"]


def size(r):
    return (r[2] - r[0], r[3] - r[1])


def test_pick_monitor():
    check("점이 있는 모니터를 고름(음수 좌표 포함)", W.monitor_at((-500, 500), ALL) is LEFT and W.monitor_at((2500, 700), ALL) is RIGHT and W.monitor_at((900, -500), ALL) is TOP
          and W.monitor_at((10, 10), ALL) is MAIN)
    check("어느 모니터에도 없는 점은 가장 가까운 모니터", W.monitor_at((9000, 500), ALL) is RIGHT and W.monitor_at((-5000, 0), ALL) is LEFT)
    check("두 모니터에 걸친 창은 더 많이 걸친 쪽", W.monitor_for_rect((1700, 100, 2100, 780), ALL) is MAIN and W.monitor_for_rect((1800, 100, 2200, 780), ALL) is RIGHT)


def test_drag_across_scales():
    """0.1.11 의 문제: 배율이 다른 모니터로 넘어가면 창이 커서에서 멀어짐. 고친 뒤: 커서가 잡은 곳이 그대로."""
    env = FakeEnv(ALL, rect=(100, 100, 500, 780))            # 주 모니터(100%)에 400x680 창
    box = W.WinBox("", (400, 680), (340, 480), remember=False, env=env)
    box.hwnd = 1
    env.cur = (300, 120)                                     # 창 왼쪽 위에서 (200, 20) 을 잡음
    st = box.begin("drag")
    worst = 0
    for cx, cy in [(600, 300), (1900, 300), (1921, 300), (2500, 600), (4400, 1300), (1921, 300), (500, 500), (-10, 500), (-900, 1500), (-500, -200),
                   (900, -500), (300, 120)]:
        env.cur = (cx, cy)
        r = box.step("drag", "", st)
        m = W.monitor_at((cx, cy), ALL)
        k = m["dpi"] / 96
        worst = max(worst, abs((cx - r[0]) - 200 * k))        # 잡은 곳의 가로 어긋남(픽셀)
        ok_size = size(r) == (round(400 * k), round(680 * k))
        if not ok_size:
            check(f"끌기: 커서가 있는 모니터 배율로 크기({m['name'][-1]})", False, (size(r), k))
    check("끌기: 배율 100%→150%→125%(세로·음수 좌표)→위 모니터를 오가도 커서가 창의 같은 곳을 잡고 있음(어긋남 1픽셀 이하)", worst <= 1, worst)
    check("끌기: 제자리로 돌아오면 처음 사각형 그대로(밀림 없음)", env.r == (100, 100, 500, 780), env.r)
    env.cur = (2500, 600)
    r = box.step("drag", "", st)
    check("끌기: 150% 모니터에서는 창이 600x1020 픽셀(보이는 크기는 같음)", size(r) == (600, 1020) and box.dpi == 144, (size(r), box.dpi))
    env.cur = (-500, 100)
    r = box.step("drag", "", st)
    check("끌기: 왼쪽 세로 모니터(음수 좌표 · 125%)에서 500x850 픽셀, 왼쪽 위 = 커서 − 잡은 곳×1.25", size(r) == (500, 850) and r[0] == -500 - 250 and r[1] == 100 - 25, r)
    env.cur = (800, -2000)
    r = box.step("drag", "", st)
    check("끌기: 화면 위로 끌어도 위쪽 끌기 줄은 작업 영역 안에 남음", r[1] >= TOP["work"][1], r)
    env.cur = (800, 1079)
    r = box.step("drag", "", st)
    check("끌기: 작업 표시줄 아래로 끌어도 끌기 줄은 남음", r[1] <= MAIN["work"][3] - W.GRAB_STRIP, r)


def test_resize():
    env = FakeEnv(ALL, rect=(100, 100, 500, 780))
    box = W.WinBox("", (400, 680), (340, 480), remember=False, env=env)
    box.hwnd = 1
    env.cur = (500, 780)
    st = box.begin("resize")
    env.cur = (700, 900)
    check("크기 조절: 오른쪽 아래 귀퉁이를 끌면 그쪽만 늘어남", box.step("resize", "se", st) == (100, 100, 700, 900))
    env.cur = (0, 0)
    check("크기 조절: 최소 크기(340x480)보다 작게는 안 줄어듦", box.step("resize", "se", st) == (100, 100, 440, 580))
    env.cur = (500, 780)
    box.step("resize", "se", st)
    st = box.begin("resize")
    env.cur = (480, 60)
    env.cur = (480 - 0, 780 - 800)
    r = box.step("resize", "n", st)
    check("크기 조절: 위쪽을 화면 위로 끌어도 작업 영역 위로 안 나감", r[1] >= MAIN["work"][1] and r[3] == 780, r)
    box.env.r = (100, 100, 620, 900)
    box.finish("resize")
    check("크기 조절이 끝나면 새 논리 크기를 받아들임", box.size == (520, 800), box.size)
    # 150% 모니터에서의 최소 크기 = 510x720 픽셀
    env2 = FakeEnv(ALL, rect=(2000, 100, 2600, 1120))
    b2 = W.WinBox("", (400, 680), (340, 480), remember=False, env=env2)
    b2.hwnd = 1
    env2.cur = (2600, 1120)
    st = b2.begin("resize")
    env2.cur = (2000, 100)
    check("크기 조절: 150% 모니터에서는 최소 크기가 510x720 픽셀", size(b2.step("resize", "se", st)) == (510, 720))
    check("모르는 방향·내려 둔 창에서는 시작하지 않음", b2.start("resize", "x") is False and (setattr(env2, "is_busy", True) or b2.start("drag") is False))


def test_remember_and_restore():
    with tempfile.TemporaryDirectory(prefix="김비서 창 시험 ") as td:
        store = os.path.join(td, "자료 폴더", "window.json")
        env = FakeEnv(ALL, rect=(2400, 300, 3150, 1500))           # 150% 모니터에 500x800(논리) 창
        box = W.WinBox(store, (400, 680), (340, 480), env=env)
        box.hwnd = 1
        rec = box.save()
        check("기억: 논리 크기 500x800 · 모니터 이름 · 그 모니터 안 자리(논리 320,200)", rec and (rec["w"], rec["h"], rec["ox"], rec["oy"]) == (500, 800, 320, 200)
              and rec["mon"]["name"].endswith("DISPLAY2") and os.path.isfile(store), rec)

        def reopen(monitors):
            e = FakeEnv(monitors, rect=(0, 0, 400, 680))
            b = W.WinBox(store, (400, 680), (340, 480), env=e, log=lambda *a: logs.append(" ".join(str(x) for x in a)))
            return b.bind(1), b

        logs = []
        r, b = reopen(ALL)
        check("다시 켜면 같은 모니터 같은 자리·같은 크기", r == (2400, 300, 3150, 1500) and b.size == (500, 800), r)
        # 그 모니터의 배율을 150% → 100% 로 바꿨을 때: 보이는 크기는 같게(픽셀은 500x800)
        r, b = reopen([MAIN, mon(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 96), LEFT, TOP])
        check("그 모니터 배율이 바뀌어도 논리 크기 그대로(픽셀 500x800) · 같은 논리 자리", size(r) == (500, 800) and r[:2] == (1920 + 320, 200), r)
        # 그 모니터를 뺐을 때 → 주 모니터 가운데(크기는 유지)
        r, b = reopen([MAIN, LEFT, TOP])
        check("기억한 모니터가 사라지면 주 모니터 가운데로(크기 유지) — 화면 밖에 남지 않음", W.monitor_for_rect(r, [MAIN, LEFT, TOP]) is MAIN and size(r) == (500, 800)
              and r[0] >= 0 and r[2] <= 1920 and r[1] >= 0 and "주 모니터 가운데" in logs[-1], (r, logs[-1]))
        # 모니터가 하나뿐이고 작을 때 → 작업 영역에 맞게 줄임
        small = mon(r"\\.\DISPLAY1", 0, 0, 1024, 600, 96, True)
        r, b = reopen([small])
        check("작은 화면 하나만 남으면 작업 영역 안으로 줄임", r[0] >= 0 and r[2] <= 1024 and r[1] >= 0 and r[3] <= small["work"][3], r)
        # 같은 이름의 모니터가 다른 자리로 옮겨졌을 때(배치를 바꿈) → 그 모니터 안 같은 자리
        moved = mon(r"\\.\DISPLAY2", -2560, 0, 2560, 1440, 144)
        r, b = reopen([MAIN, moved])
        check("모니터 배치를 바꿔도(오른쪽 → 왼쪽, 음수 좌표) 그 모니터 안 같은 자리", r == (-2560 + 480, 300, -2560 + 480 + 750, 1500), r)
        # 기억 파일이 깨졌거나 값이 이상할 때
        for bad in ("{", json.dumps({"w": 5, "h": 5, "ox": 0, "oy": 0}), json.dumps({"w": "x"}), json.dumps([1, 2])):
            open(store, "w", encoding="utf-8").write(bad)
            r, b = reopen(ALL)
            if not (size(r) == (400, 680) and W.monitor_for_rect(r, ALL) is MAIN):
                check("기억 파일이 깨졌으면 기본 크기로 주 모니터 가운데", False, (bad, r))
        check("기억 파일이 깨졌거나 값이 이상하면 기본 크기(400x680)로 주 모니터 가운데", True)
        # 기억 끔
        os.remove(store)
        b = W.WinBox(store, (400, 680), (340, 480), remember=False, env=FakeEnv(ALL))
        b.hwnd = 1
        check("설정에서 기억을 끄면 파일을 쓰지 않음", b.save() is None and not os.path.exists(store))
        # 내려 둔 창은 기억하지 않음
        e = FakeEnv(ALL, rect=(-32000, -32000, -31840, -31972))
        e.is_busy = True
        b = W.WinBox(store, env=e)
        b.hwnd = 1
        check("내려 둔(최소화) 창의 자리는 기억하지 않음", b.save() is None and not os.path.exists(store))


def test_settle():
    """우리 끌기 말고 다른 까닭(Win+Shift+화살표 · 모니터 빼기 · 배율 바꾸기)으로 창이 옮겨졌을 때."""
    env = FakeEnv(ALL, rect=(100, 100, 500, 780))
    box = W.WinBox("", (400, 680), (340, 480), remember=False, env=env)
    box.bind(1)
    env.r = (2100, 100, 2500, 780)                  # 윈도우가 150% 모니터로 옮김(픽셀 크기 그대로 400x680 → 작게 보임)
    r = box.settle()
    check("다른 까닭으로 배율이 다른 모니터에 가면 논리 크기에 맞게 픽셀 크기를 다시 정함(600x1020)", r and size(r) == (600, 1020) and box.dpi == 144, r)
    env.mons = [MAIN, LEFT, TOP]                    # 그 모니터를 뺌 — 창은 이제 어느 모니터에도 없음
    r = box.settle()
    check("모니터를 빼서 창이 화면 밖에 남으면 가까운 모니터 안으로(끌기 줄이 보이게)", r and W._area(r, MAIN["rect"]) > 0 and r[1] >= 0
          and min(r[2], MAIN["work"][2]) - max(r[0], MAIN["work"][0]) >= W.KEEP_VISIBLE, r)
    check("이미 맞으면 건드리지 않음", box.settle() is None)


def test_fake_monitor_file():
    saved = {k: os.environ.get(k) for k in ("KIMBISEO_TEST_WINDOW", "KIMBISEO_TEST_MONITORS")}
    with tempfile.TemporaryDirectory(prefix="김비서 창 시험 ") as td:
        p = os.path.join(td, "모니터.json")
        json.dump([{"name": "가", "rect": [0, 0, 100, 100], "dpi": 120, "primary": True}], open(p, "w", encoding="utf-8"))
        try:
            os.environ["KIMBISEO_TEST_MONITORS"] = p
            os.environ.pop("KIMBISEO_TEST_WINDOW", None)
            a = W.test_monitors()
            os.environ["KIMBISEO_TEST_WINDOW"] = "1"
            b = W.test_monitors()
            check("가짜 모니터 구성은 시험 환경변수가 둘 다 있을 때만 읽음(보통 실행에서는 무시)", a is None and b and b[0]["dpi"] == 120 and b[0]["work"] == (0, 0, 100, 100), (a, b))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def main():
    test_pick_monitor()
    test_drag_across_scales()
    test_resize()
    test_remember_and_restore()
    test_settle()
    test_fake_monitor_file()
    bad = [n for n, ok in OK if not ok]
    print(f"\n창 옮기기·크기·자리 기억 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
