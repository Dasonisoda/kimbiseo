# 설치가 '멈춘 것처럼' 보이지 않게 하는 부분의 단위 시험 — 지난 시간 · 진전 없던 시간(조용_초) · 살아 있음 표시 ·
#   큰 부품을 디스크에 푸는 동안의 진행 표시 · 실패 까닭 한 줄.   python -B -m tests.unit.test_install_progress
#
# 진짜 설치·진짜 pip 없이 돈다: 임시 폴더(한글·빈칸 든 경로)와 가짜 pip(천천히 파일을 쓰는 작은 스크립트)만 쓴다.
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))

import get_models as GM  # noqa: E402
import setup_core as SC  # noqa: E402

OK = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


def read(path):
    for _ in range(20):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            time.sleep(0.05)
    return {}


def test_words():
    check("지난 시간 글: 초 · 분 초 · 시간 분", (SC.took(45), SC.took(200), SC.took(3900)) == ("45초", "3분 20초", "1시간 5분"), (SC.took(45), SC.took(200), SC.took(3900)))
    check("까닭 한 줄: 받기 원인은 받기 부품의 말 그대로", SC.short_why("blocked") == GM.WHY["blocked"] and SC.short_why("tls") == GM.WHY["tls"])
    check("까닭 한 줄: 파일이 원본과 다름 · 디스크 모자람", "원본과 달라요" in SC.short_why("hash") and "디스크" in SC.short_why("disk"))
    check("까닭 한 줄: 원인을 모르면 이유의 첫 문장만", SC.short_why(None, "첫 문장이에요. 둘째 문장이에요.") == "첫 문장이에요.", SC.short_why(None, "첫 문장이에요. 둘째 문장이에요."))
    hard = [k for k, v in GM.WHY.items() if any(w in v for w in ("Electron", "TLS", "DNS", "HTTP", "프록시", "서버", "호스트"))]
    check("받기 실패 까닭 글에 어려운 낱말(TLS·DNS·프록시·서버 등)이 없음", not hard, hard)


def test_sizes():
    with tempfile.TemporaryDirectory(prefix="김비서 진행 시험 ") as td:
        a, b = os.path.join(td, "a.whl"), os.path.join(td, "b.whl")
        with zipfile.ZipFile(a, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("pkg/x.bin", b"\0" * 300000)
            z.writestr("pkg/y.py", b"print(1)\n" * 100)
        with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("q/z.bin", b"\1" * 50000)
        open(os.path.join(td, "깨진.whl"), "wb").write(b"not a zip " * 10)
        n = SC.unpacked_size([a, b])
        check("받은 부품이 디스크에 풀리면 차지할 크기를 압축 목록에서 셈", n == 300000 + 900 + 50000 and os.path.getsize(a) < 5000, n)
        bad = os.path.join(td, "깨진.whl")
        check("못 읽는 부품은 받은 크기의 2배로 어림 · 없는 파일은 0", SC.unpacked_size([bad, os.path.join(td, "없음.whl")]) == os.path.getsize(bad) * 2)
        os.makedirs(os.path.join(td, "폴더", "안 쪽"))
        open(os.path.join(td, "폴더", "1"), "wb").write(b"x" * 1000)
        open(os.path.join(td, "폴더", "안 쪽", "2"), "wb").write(b"y" * 234)
        check("폴더 크기 재기(하위 폴더 포함) · 없는 폴더는 0", SC.tree_size(os.path.join(td, "폴더")) == 1234 and SC.tree_size(os.path.join(td, "없는 폴더")) == 0)


def test_status_quiet_and_heartbeat():
    with tempfile.TemporaryDirectory(prefix="김비서 진행 시험 ") as td:
        st = SC.Status(os.path.join(td, "status.json"), os.path.join(td, "logs", "install.log"))
        st.begin("packages")
        st.progress(0.1, "부품 받는 중")
        st.alive_t -= 100                      # 100초 동안 진전이 없었다고 침
        st.progress(0.1, "부품 받는 중 · 1분 40초째", alive=False)      # 글만 고침(지난 시간) — 진전 아님
        st.write(force=True)
        d = read(st.path)
        check("진전 없이 글만 바뀌면 '조용_초'가 그대로 늘어남(설치 창이 '진전이 없어요'를 띄울 수 있음)", 100 <= d.get("조용_초", 0) <= 103 and "1분 40초째" in d["글"], d.get("조용_초"))
        st.progress(0.2, "부품 받는 중 2MB")
        st.write(force=True)
        d = read(st.path)
        check("진짜 진전(받은 양이 늚)이 있으면 '조용_초'가 0 으로 돌아감", d.get("조용_초") == 0 and d.get("경과_초") is not None and "단계_경과_초" in d, d)

        # 살아 있음 표시: 일하는 줄이 아무것도 안 해도 2초마다 상태 파일을 새로 씀
        st.alive_t -= 50
        st.heartbeat()
        m0 = os.path.getmtime(st.path)
        time.sleep(4.6)
        d = read(st.path)
        check("살아 있음 표시가 2초마다 상태 파일을 새로 쓰고, 그 사이 '조용_초'는 늘어남", os.path.getmtime(st.path) > m0 and d.get("조용_초", 0) >= 52, (d.get("조용_초"), d.get("시각")))

        # 일하는 줄과 살아 있음 표시가 동시에 써도 상태 파일이 깨지지 않음
        stop, bad = threading.Event(), []

        def spam():
            i = 0
            while not stop.is_set():
                i += 1
                st.progress((i % 100) / 100, f"받는 중 {i}")
                st.write(force=True)

        def peek():
            while not stop.is_set():
                try:
                    with open(st.path, encoding="utf-8") as f:
                        json.load(f)
                except OSError:
                    pass
                except ValueError as ex:
                    bad.append(str(ex))
                time.sleep(0.003)
        ts = [threading.Thread(target=spam), threading.Thread(target=peek)]
        for t in ts:
            t.start()
        time.sleep(3.0)
        stop.set()
        for t in ts:
            t.join()
        check("두 줄이 동시에 상태를 써도 읽는 쪽이 깨진 파일을 보지 않음", not bad, bad[:2])
        st.d["끝"] = True
        st.heartbeat(False)
        st.write(force=True)
        check("끝나면 '조용_초'는 0", read(st.path).get("조용_초") == 0)


FAKE_PIP = r'''
import os, sys, time
site = os.environ["KB_FAKE_SITE"]
mode = os.environ.get("KB_FAKE_MODE", "ok")
print("Looking in links: wheels", flush=True)
print("Processing ./wheels/big-1.0-py3-none-any.whl", flush=True)
if mode == "disk":
    print("ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device", flush=True)
    sys.exit(1)
if mode == "locked":
    print("ERROR: Could not install packages due to an OSError: [WinError 5] Access is denied: 'x.pyd'", flush=True)
    sys.exit(1)
print("Installing collected packages: big", flush=True)
os.makedirs(os.path.join(site, "big"), exist_ok=True)
for i in range(14):                 # 7초 동안 0.5초마다 1MB — 큰 부품을 디스크에 푸는 흉내(그동안 아무 말도 안 함)
    with open(os.path.join(site, "big", f"{i}.bin"), "wb") as f:
        f.write(b"\0" * (1024 * 1024))
    time.sleep(0.5)
time.sleep(float(os.environ.get("KB_FAKE_QUIET", "0")))      # 아무것도 안 늘어나는 시간(멈춘 흉내)
print("Successfully installed big-1.0", flush=True)
'''


def _installer(td):
    a = argparse.Namespace(prefix=os.path.join(td, "프로그램 폴더"), data=os.path.join(td, "자료 폴더"), status=os.path.join(td, "status.json"), source="",
                           local_brain=False, gemma=None, desktop_dir="", startmenu_dir="", reg_key="KimBiseoUnitTest", display_name="김비서",
                           packs_catalog="", no_shortcuts=True, no_register=True, dry_run=False, file="")
    inst = SC.Installer(a)
    os.makedirs(os.path.join(a.prefix, "install"), exist_ok=True)
    with open(os.path.join(a.prefix, "install", "pip.py"), "w", encoding="utf-8") as f:      # python -m pip 가 이 가짜를 집음(작업 폴더가 먼저)
        f.write(FAKE_PIP)
    return inst


def test_pip_shows_life_while_installing():
    with tempfile.TemporaryDirectory(prefix="김비서 진행 시험 ") as td:
        inst = _installer(td)
        site = os.path.join(td, "가짜 site-packages")
        os.makedirs(site)
        os.environ.update({"KB_FAKE_SITE": site, "KB_FAKE_MODE": "ok", "KB_FAKE_QUIET": "7"})
        inst.st.begin("packages")
        seen, stop = [], threading.Event()

        def watch():
            while not stop.is_set():
                d = read(inst.st.path)
                if d.get("글") and (not seen or seen[-1][0] != d["글"]):
                    seen.append((d["글"], d.get("진행"), d.get("조용_초")))
                time.sleep(0.25)
        t = threading.Thread(target=watch)
        t.start()
        t0 = time.time()
        try:
            inst.pip(sys.executable, ["install", "big"], "음성 부품 설치", (0.5, 1.0), 1, expect=14 * 1024 * 1024, site=site)
            err = None
        except SC.Fail as ex:
            err = ex
        took = time.time() - t0
        stop.set()
        t.join()
        texts = [x[0] for x in seen]
        unp = [x for x in seen if "디스크에 푸는 중" in x[0]]
        check("가짜 pip 가 끝까지 돎", err is None and took >= 13, (err, took))
        check("pip 가 말이 없는 동안에도 화면 글이 바뀜: '디스크에 푸는 중 · 풀린 양 / 예상 양 · 지난 시간'", len(unp) >= 3 and "약 14.0MB" in unp[0][0] and "째" in unp[0][0], texts)
        check("그 글에 '멈춘 것이 아니에요'라고 알려 줌", unp and "멈춘 것이 아니에요" in unp[0][0], texts[-3:])
        check("풀린 양에 따라 진행 막대가 나아감(뒤로 가지 않음)", len(unp) >= 2 and unp[-1][1] > unp[0][1] and all(b[1] >= a[1] for a, b in zip(unp, unp[1:])), [x[1] for x in unp])
        check("풀린 양이 더 안 늘면 '조용_초'가 늘어남(진짜 멈춤을 가릴 수 있음)", unp and max(x[2] or 0 for x in unp) >= 3, [x[2] for x in unp])
        log = open(inst.st.log_path, encoding="utf-8").read()
        check("기록에 pip 가 끝난 것과 걸린 시간을 남김", "pip 끝(코드 0)" in log and "Successfully installed big-1.0" in log)

        for mode, word, kind in (("disk", "디스크 공간이 모자라요", "disk"), ("locked", "백신 알림", "file")):
            os.environ["KB_FAKE_MODE"] = mode
            try:
                inst.pip(sys.executable, ["install", "big"], "음성 부품 설치", site=site)
                got = None
            except SC.Fail as ex:
                got = ex
            check(f"pip 실패 까닭을 가려 말함({mode})", got is not None and word in got.why and got.info.get("원인") == kind, got and got.why)
        for k in ("KB_FAKE_SITE", "KB_FAKE_MODE", "KB_FAKE_QUIET"):
            os.environ.pop(k, None)


def test_import_check_shows_elapsed():
    with tempfile.TemporaryDirectory(prefix="김비서 진행 시험 ") as td:
        inst = _installer(td)
        inst.st.begin("packages")
        rc, err = inst.try_import(sys.executable, "import time; time.sleep(7)", "음성 부품이 잘 깔렸는지 불러와 보는 중")
        inst.st.write(force=True)
        d = read(inst.st.path)
        check("깔린 부품을 불러와 보는 동안(오래 걸림) 지난 시간을 보여 줌", rc == 0 and "불러와 보는 중 · " in d.get("글", "") and "초째" in d["글"] and d.get("조용_초", 99) <= 4, d.get("글"))
        rc, err = inst.try_import(sys.executable, "import no_such_module_kimbiseo_test", "확인하는 중")
        check("불러오지 못하면 오류 글을 돌려줌", rc != 0 and "ModuleNotFoundError" in err, err[-200:])


def main():
    test_words()
    test_sizes()
    test_status_quiet_and_heartbeat()
    test_pip_shows_life_while_installing()
    test_import_check_shows_elapsed()
    bad = [n for n, ok in OK if not ok]
    print(f"\n설치 진행 표시 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
