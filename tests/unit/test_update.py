# 업데이트 단위 시험(인터넷·설치 없이) — python -B -m tests.unit.test_update   (cryptography 가 있는 본체 파이썬으로)
#   판 번호 · 서명 확인(맞음·고침·다른 열쇠·모르는 열쇠) · 꾸러미 풀기(빠짐·더 있음·경로 탈출·내용 바뀜) · 주소 막기 · 부품 바뀜 → 새 설치
#   · 바꿔 끼우기(검사 통과 → 새 판·자료 그대로 / 검사 실패 → 예전 판으로 되돌림) · 다시 켠 뒤 실행기 오류 → 되돌림
import base64
import json
import os
import shutil
import sys
import tempfile
import types
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import updater as U  # noqa: E402
from app.core import update as UP  # noqa: E402
import make_update as MK  # noqa: E402

OK = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except U.UpdateError as ex:
        return str(ex) or True
    return False


def fake_src(root, version):
    for rel in U.MUST_HAVE + U.DEPS + ["app/config/default.json", "voice/ear.py"]:
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            if rel == "app/version.py":
                f.write(f'VERSION = "{version}"\n')
            elif rel.endswith(".json"):
                f.write('{"포트": {"본체": 18970}}' if rel.endswith("default.json") else "{}")
            else:
                f.write(f"# {rel} {version}\n")
    for top in ("LICENSE", "NOTICE"):
        open(os.path.join(root, top), "w").write(top)
    return root


def build(src, out, key, deps_from=None):
    a = types.SimpleNamespace(src=src, no_allowlist=True, out=out, key=key, base_url="http://127.0.0.1:1/x/", notes=["시험"],
                              min_from="0.1.0", release_page="", setup_zip="")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        MK.cmd_build(a)
    return json.load(open(os.path.join(out, "latest.json"), encoding="utf-8"))


def test_versions():
    check("판 번호 비교", U.newer("0.1.1", "0.1.0") and U.newer("0.2.0", "0.1.9") and U.newer("1.0.0", "0.99.99") and not U.newer("0.1.0", "0.1.0"))
    check("이상한 판 번호 막음", all(raises(U.parse_version, v) for v in ("", "0.1", "0.1.1a", "../0.1.1", "0.1.1 ", "0.1.1" + chr(10), "v0.1.1")))


def test_urls():
    check("https 깃허브 허용", UP.check_url("https://github.com/a/b/releases/latest/download/latest.json")
          and UP.check_url("https://release-assets.githubusercontent.com/x"))
    check("깃허브 밖 서버는 막음(사내 서버 없음)", raises(UP.check_url, "https://license.example.com/downloads/kimbiseo/latest.json"))
    check("이 PC http 허용(시험)", UP.check_url("http://127.0.0.1:18999/latest.json"))
    check("다른 곳·http 막음", all(raises(UP.check_url, u) for u in ("http://github.com/x", "https://evil.example/x", "https://github.com.evil.example/x",
                                                                   "ftp://127.0.0.1/x", "file:///C:/x", "https://notgithub.com/x")))


def test_sign(tmp):
    key = os.path.join(tmp, "k.pem")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        MK.cmd_keygen(types.SimpleNamespace(out=key))
    pub = MK.pub_b64(MK.load_key(key))
    keys = {"kimbiseo-update-1": pub}
    src = fake_src(os.path.join(tmp, "v011"), "0.1.1")
    doc = build(src, os.path.join(tmp, "out011"), key)
    s = UP.verify_manifest(doc, keys)
    check("서명 맞음 → 목록 읽힘", s["version"] == "0.1.1" and s["package"]["size"] > 0)
    bad = json.loads(json.dumps(doc))
    bad["signed"]["version"] = "9.9.9"
    check("목록을 고치면(판 번호) 서명 실패", raises(UP.verify_manifest, bad, keys))
    bad = json.loads(json.dumps(doc))
    bad["signed"]["package"]["sha256"] = "0" * 64
    check("목록을 고치면(sha256) 서명 실패", raises(UP.verify_manifest, bad, keys))
    other = os.path.join(tmp, "k2.pem")
    with contextlib.redirect_stdout(io.StringIO()):
        MK.cmd_keygen(types.SimpleNamespace(out=other))
    check("다른 열쇠로 확인하면 실패", raises(UP.verify_manifest, doc, {"kimbiseo-update-1": MK.pub_b64(MK.load_key(other))}))
    bad = json.loads(json.dumps(doc))
    bad["key_id"] = "kimbiseo-update-9"
    check("모르는 열쇠 이름 실패", raises(UP.verify_manifest, bad, keys))
    check("진짜 공개키 모양(32바이트)", len(base64.b64decode(UP.PUBKEYS["kimbiseo-update-1"])) == 32)
    check("진짜 공개키로는 시험 목록이 안 맞음", raises(UP.verify_manifest, doc))
    with contextlib.redirect_stdout(io.StringIO()):
        rc = MK.cmd_keygen(types.SimpleNamespace(out=key))
    check("keygen 은 있는 열쇠를 덮어쓰지 않음", rc == 1 and MK.pub_b64(MK.load_key(key)) == pub)
    return key, keys, doc, src


def test_package(tmp, doc):
    zp = os.path.join(tmp, "out011", doc["signed"]["package"]["file"])
    idx = U.extract_package(zp, os.path.join(tmp, "st"))
    check("꾸러미 풀기·파일 확인 됨", idx["version"] == "0.1.1" and len(idx["files"]) == doc["signed"]["files_count"])
    check("꾸러미의 부품 정보 = 목록", U.deps_of(os.path.join(tmp, "st")) == doc["signed"]["deps"])

    def remake(name, mutate):
        p = os.path.join(tmp, name + ".zip")
        with zipfile.ZipFile(zp) as zi, zipfile.ZipFile(p, "w") as zo:
            items = [(i, zi.read(i)) for i in zi.infolist()]
            for info, data in mutate(items):
                zo.writestr(info if isinstance(info, zipfile.ZipInfo) else zipfile.ZipInfo(info), data)
        return p
    p = remake("extra", lambda it: it + [("src/app/evil.py", b"x")])
    check("목록에 없는 파일 → 실패", raises(U.extract_package, p, os.path.join(tmp, "x1")))
    p = remake("slip", lambda it: it + [("src/../../evil.py", b"x")])
    check("경로 탈출 이름 → 실패", raises(U.extract_package, p, os.path.join(tmp, "x2")) and not os.path.exists(os.path.join(tmp, "evil.py")))
    p = remake("miss", lambda it: [x for x in it if x[0].filename != "src/app/main.py"])
    check("빠진 파일 → 실패", raises(U.extract_package, p, os.path.join(tmp, "x3")))
    p = remake("changed", lambda it: [(i, (d + b"\n# changed" if i.filename == "src/app/main.py" else d)) for i, d in it])
    check("내용 바뀐 파일(sha256) → 실패", raises(U.extract_package, p, os.path.join(tmp, "x4")))
    p = remake("outside", lambda it: it + [("readme_outside.txt", b"x")])
    check("src/ 밖 파일 → 실패", raises(U.extract_package, p, os.path.join(tmp, "x5")))
    st = os.path.join(tmp, "st")
    open(os.path.join(st, "app", "main.py"), "a").write("# 받은 뒤 바뀜\n")
    check("받아 둔 뒤 바뀐 파일 → 바꾸기 전 확인에서 실패", raises(U.verify_tree, st, idx))


def test_needs_setup(tmp, keys, doc):
    up = UP.Updater.__new__(UP.Updater)
    s = dict(doc["signed"])
    s["deps"] = {k: "0" * 64 for k in U.DEPS}
    check("부품 목록이 바뀐 판 → 새 설치 필요", up.needs_setup(s))
    s = dict(doc["signed"])
    s["deps"] = U.deps_of(UP.SRC)
    s["min_from"] = "9.0.0"
    check("지금 판이 너무 옛것 → 새 설치 필요", up.needs_setup(s))
    s["min_from"] = "0.1.0"
    check("부품 같음 → 코드만 업데이트", not up.needs_setup(s))


def fake_install(tmp, name, old="0.1.0"):
    prefix = os.path.join(tmp, name)
    fake_src(os.path.join(prefix, "src"), old)
    os.makedirs(os.path.join(prefix, "install"), exist_ok=True)
    U.write_json(os.path.join(prefix, "install", "state.json"), {"version": old})
    data = os.path.join(tmp, name + "_data")
    os.makedirs(os.path.join(data, "기억"), exist_ok=True)
    open(os.path.join(data, "기억", "지식.json"), "w", encoding="utf-8").write('["사용자는 커피를 좋아함"]')
    settings = os.path.join(data, "settings.json")
    U.write_json(settings, {"경로": {"자료": data}, "비서": {"이름": "현아"}})
    return prefix, data, settings


def stage(prefix, key, tmp, ver):
    src = fake_src(os.path.join(tmp, "src_" + ver), ver)
    out = os.path.join(tmp, "out_" + ver)
    doc = build(src, out, key)
    upd = os.path.join(prefix, "install", "update")
    idx = U.extract_package(os.path.join(out, doc["signed"]["package"]["file"]), os.path.join(upd, "staged"))
    U.write_json(os.path.join(upd, "staged_index.json"), idx)
    U.write_json(os.path.join(upd, "ready.json"), {"version": ver})


def run_updater(prefix, settings, ver, health_ok=True, relaunch_rc=None):
    saved = (U.stop_kimbiseo, U.health_check, U.relaunch, U.set_installed_version, U.time.sleep, U._http_ok)
    calls = {"health": 0, "relaunch": 0}

    def health(*_a, **_k):
        calls["health"] += 1
        if not health_ok:
            raise U.UpdateError("새 판 본체를 불러오지 못했어요: 시험")

    class P:
        pid = 1

        def poll(self):
            return relaunch_rc

    def rel(*_a, **_k):
        calls["relaunch"] += 1
        return P()
    U.stop_kimbiseo = lambda *a, **k: None
    U.health_check = health
    U.relaunch = rel
    U.time.sleep = lambda *_a: None
    U._http_ok = lambda *_a, **_k: relaunch_rc is None     # 다시 켠 새 본체가 준비됨(오류 시험에서는 준비 안 됨)
    real_siv = saved[3]
    U.set_installed_version = lambda p, v: real_siv(p, v)
    try:
        a = types.SimpleNamespace(prefix=prefix, settings=settings, version=ver, body_pid=0, no_relaunch=False)
        rc = U.do_run(a)
    finally:
        U.stop_kimbiseo, U.health_check, U.relaunch, U.set_installed_version, U.time.sleep, U._http_ok = saved
    return rc, calls


def test_swap(tmp, key):
    prefix, data, settings = fake_install(tmp, "inst_ok")
    stage(prefix, key, tmp, "0.1.1")
    rc, calls = run_updater(prefix, settings, "0.1.1")
    res = U.read_json(os.path.join(data, "update", "result.json"))
    check("업데이트 됨: src = 새 판", rc == 0 and U.read_version_file(os.path.join(prefix, "src")) == "0.1.1" and res["ok"] and res["from"] == "0.1.0")
    check("예전 판은 install/update/previous 에 남음", U.read_version_file(os.path.join(prefix, "install", "update", "previous")) == "0.1.0")
    check("자료(기억·설정) 그대로", open(os.path.join(data, "기억", "지식.json"), encoding="utf-8").read() == '["사용자는 커피를 좋아함"]'
          and U.read_json(settings)["비서"]["이름"] == "현아")
    check("설치 기록 판 번호 = 새 판", U.read_json(os.path.join(prefix, "install", "state.json"))["version"] == "0.1.1")
    check("다시 켬 1번", calls["relaunch"] == 1)

    prefix, data, settings = fake_install(tmp, "inst_bad")
    stage(prefix, key, tmp, "0.1.2")
    rc, calls = run_updater(prefix, settings, "0.1.2", health_ok=False)
    res = U.read_json(os.path.join(data, "update", "result.json"))
    check("새 판 검사 실패 → 예전 판으로 되돌림", rc == 1 and U.read_version_file(os.path.join(prefix, "src")) == "0.1.0" and res["rolled_back"] and not res["ok"])
    check("되돌린 뒤 설치 기록 판 번호 = 예전 판", U.read_json(os.path.join(prefix, "install", "state.json"))["version"] == "0.1.0")
    fails = [d for d in os.listdir(os.path.join(prefix, "install", "update")) if d.startswith("failed_0.1.2")]
    check("실패한 새 판은 failed_ 폴더로 따로", len(fails) == 1)
    check("되돌린 뒤에도 다시 켬(예전 판으로)", calls["relaunch"] == 1)

    prefix, data, settings = fake_install(tmp, "inst_crash")
    stage(prefix, key, tmp, "0.1.3")
    rc, calls = run_updater(prefix, settings, "0.1.3", relaunch_rc=1)
    res = U.read_json(os.path.join(data, "update", "result.json"))
    check("다시 켠 실행기가 오류로 꺼짐 → 예전 판으로 되돌리고 다시 켬", U.read_version_file(os.path.join(prefix, "src")) == "0.1.0"
          and res["rolled_back"] and calls["relaunch"] == 2)

    prefix, data, settings = fake_install(tmp, "inst_old", old="0.1.5")
    stage(prefix, key, tmp, "0.1.4")
    rc, _ = run_updater(prefix, settings, "0.1.4")
    check("더 옛 판으로는 안 바꿈(되돌리기 공격 막음)", rc == 1 and U.read_version_file(os.path.join(prefix, "src")) == "0.1.5")

    prefix, data, settings = fake_install(tmp, "inst_none")
    rc, _ = run_updater(prefix, settings, "0.1.1")
    check("받아 둔 판 없으면 아무것도 안 바꿈", rc == 1 and U.read_version_file(os.path.join(prefix, "src")) == "0.1.0")


def main():
    tmp = tempfile.mkdtemp(prefix="kimbiseo_update_test_")
    try:
        test_versions()
        test_urls()
        key, keys, doc, _src = test_sign(tmp)
        test_package(tmp, doc)
        test_needs_setup(tmp, keys, doc)
        test_swap(tmp, key)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok in OK if not ok]
    print(f"\n업데이트 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
