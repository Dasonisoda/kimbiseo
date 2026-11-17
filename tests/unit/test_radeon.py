# 라데온 판 단위 시험(받기·소리 없음) — 판 고르기·사양 추천·목소리 방식 고르기·한글 경로 대비·설치 zip 판 표시.
#   python -m tests.unit.test_radeon
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in (ROOT, os.path.join(ROOT, "installer"), os.path.join(ROOT, "voice")):
    if p not in sys.path:
        sys.path.insert(0, p)

import plan as PLAN  # noqa: E402
from app.core import sysinfo  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


def t_plan():
    amd = ["AMD Radeon RX 7600"]
    p = PLAN.make_plan([], 16, 200, others=amd, edition="radeon")
    check("라데온 판·엔비디아 없음 → GGUF 목소리", p["목소리_gguf"] and p["설정"]["목소리.엔진"] == "qwen" and p["설정"]["목소리.방식"] == "gguf")
    check("라데온 판 → GGUF 모델 받음·torch 모델은 안 받음", sysinfo.GGUF_VOICE_MODEL in p["모델"] and "Qwen3-TTS-12Hz-0.6B-Base" not in p["모델"])
    check("라데온 판 → torch CPU 판(귀용)", p["torch"] == "cpu")
    n = PLAN.make_plan([], 16, 200, others=amd, edition="nvidia")
    check("엔비디아 판(기본)은 예전과 같음 — 윈도우 음성", n["설정"]["목소리.엔진"] == "windows" and not n["목소리_gguf"]
          and "목소리.방식" not in n["설정"] and sysinfo.GGUF_VOICE_MODEL not in n["모델"])
    g = [{"이름": "NVIDIA GeForce RTX 4070", "전체_MiB": 12282}]
    r = PLAN.make_plan(g, 32, 200, driver=581.0, edition="radeon")
    check("라데온 판이어도 엔비디아가 있으면 엔비디아 구성", r["torch"] == "cu128" and not r["목소리_gguf"] and "Qwen3-TTS-12Hz-0.6B-Base" in r["모델"])
    check("라데온 판 디스크 계산에 GGUF 모델 포함", p["설치_크기_GB"] > n["설치_크기_GB"] + 1.0, f"{p['설치_크기_GB']} vs {n['설치_크기_GB']}")
    check("라데온 판을 엔비디아 PC 에 → 설치 창에 '엔비디아 판과 똑같이' 안내", r["안내"][0].startswith("라데온 판 설치 파일이지만 엔비디아"))
    check("엔비디아 판을 엔비디아 없는 PC 에 → 설치 창에 라데온 판 안내", any("-Radeon.zip" in x for x in n["안내"])
          and not any("-Radeon.zip" in x for x in p["안내"]))
    check("판 표시 없으면 nvidia", PLAN.edition_of(None) in ("nvidia", "radeon") and PLAN.edition_of("radeon") == "radeon")


def t_manifests():
    import get_models as GM
    mf = GM.load_manifests(GM.MANIFEST, PLAN.RADEON_MODELS)
    m = mf.get(sysinfo.GGUF_VOICE_MODEL)
    check("라데온 모델 목록 읽힘", m is not None)
    if m:
        check("모든 파일에 sha256·크기", all(len(f.get("sha256", "")) == 64 and f["size"] > 0 for f in m["files"]))
        check("크기 합 = size_total", sum(f["size"] for f in m["files"]) == m["size_total"])
        f = next(x for x in m["files"] if "/" in x["path"])
        u = GM.file_url(m, f)
        check("폴더 있는 파일은 첨부 이름(__)으로 받음", u.endswith(f["asset"]) and "__" in u and GM.host_ok(u))
    base = GM.load_manifest(GM.MANIFEST)
    check("엔비디아 models.json 은 그대로(GGUF 없음)", sysinfo.GGUF_VOICE_MODEL not in base)
    rt = json.load(open(os.path.join(ROOT, "installer", "radeon", "runtimes.json"), encoding="utf-8"))["llama_cpp_tts"]
    check("목소리 llama.cpp 판 = b10621(lib.py 구조체 판)", rt["version"] == "b10621" and len(rt["sha256"]) == 64 and GM.host_ok(rt["url"]))
    import updater
    deps = " ".join(getattr(updater, "DEPS", []))
    check("라데온 목록은 업데이트 '새 설치 필요' 검사 밖", "radeon" not in deps)


def t_recommend():
    r = sysinfo.recommend([], None, None, gguf_ready=True)
    check("GGUF 깔림 + 엔비디아 없음 → 처음 화면 추천 = 김비서 목소리", r["설정"]["목소리.엔진"] == "qwen" and r["설정"]["목소리.장치"] == "auto")
    r2 = sysinfo.recommend([], None, None)
    check("GGUF 없으면 예전 추천(윈도우 음성)", r2["설정"]["목소리.엔진"] == "windows")
    with tempfile.TemporaryDirectory() as d:
        md = os.path.join(d, "김비서 설치", "models")
        os.makedirs(os.path.join(md, sysinfo.GGUF_VOICE_MODEL))
        check("GGUF 파일 없으면 준비 안 됨", not sysinfo.gguf_voice_ready(md))
        open(os.path.join(md, sysinfo.GGUF_VOICE_MODEL, "qwen3_tts_talker.q5_k.gguf"), "wb").close()
        os.makedirs(os.path.join(d, "김비서 설치", "runtime", "llama-tts"))
        open(os.path.join(d, "김비서 설치", "runtime", "llama-tts", "llama.dll"), "wb").close()
        check("GGUF 모델 + llama.dll 있으면 준비됨(한글 폴더)", sysinfo.gguf_voice_ready(md))


def t_voice_method():
    import config as C
    import tts_server as S
    cfg = C.load(os.path.join(tempfile.gettempdir(), "없는_설정_라데온시험.json"), warn=lambda *_: None)
    cfg["목소리"]["방식"] = "gguf"
    check("방식 gguf 이면 gguf", S.voice_method(cfg) == "gguf")
    cfg["목소리"]["방식"] = "torch"
    check("방식 torch 이면 torch", S.voice_method(cfg) == "torch")
    cfg["목소리"]["방식"] = "auto"
    old = C.gpu_free_mib
    try:
        C.gpu_free_mib = lambda: (0.0, 0.0)
        cfg["목소리"]["GGUF_모델"] = os.path.join(tempfile.gettempdir(), "없는_GGUF")
        check("auto · 엔비디아 없음 · GGUF 없음 → torch(→ 예전 윈도우 음성 규칙)", S.voice_method(cfg) == "torch")
        C.gpu_free_mib = lambda: (8000.0, 8192.0)
        check("auto · 엔비디아 있음 → torch", S.voice_method(cfg) == "torch")
    finally:
        C.gpu_free_mib = old
    check("목소리 서버가 torch 를 먼저 안 불러옴", "torch" not in sys.modules)


def t_ascii_path():
    from gguf_tts import lib
    check("영문 경로는 그대로", lib.ascii_path(r"C:\models\a.gguf") == r"C:\models\a.gguf")
    if os.name == "nt":
        with tempfile.TemporaryDirectory() as d:
            k = os.path.join(d, "한글 폴더")
            os.makedirs(k)
            f = os.path.join(k, "모델.gguf")
            open(f, "wb").write(b"x")
            alt = lib.ascii_path(f, link_root=os.path.join(d, "links"))
            ok = os.path.isfile(alt) and (alt == f or all(ord(c) < 128 for c in alt.replace(os.path.basename(f), "")))
            check("한글 경로 → 짧은 경로/연결 폴더(그 파일이 열림)", ok, alt)


def t_edition_zip():
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "tools", "make_setup_zip.py"), "--out", d, "--edition", "radeon"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        zs = [f for f in os.listdir(d) if f.endswith("-radeon.zip")]
        check("라데온 판 설치 zip 만듦", r.returncode == 0 and len(zs) == 1, (r.stdout + r.stderr)[-300:])
        if zs:
            with zipfile.ZipFile(os.path.join(d, zs[0])) as z:
                names = z.namelist()
                ed = [n for n in names if n.endswith("/installer/edition.json")]
                check("zip 안에 installer/edition.json(radeon)", len(ed) == 1 and json.loads(z.read(ed[0]))["edition"] == "radeon")
                check("zip 안에 목소리 모델·DLL 은 없음(설치 때 받음)", not any(n.endswith((".gguf", ".onnx", ".dll", ".npy")) for n in names))


if __name__ == "__main__":
    for fn in (t_plan, t_manifests, t_recommend, t_voice_method, t_ascii_path, t_edition_zip):
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            check(fn.__name__, False, f"{type(ex).__name__}: {ex}")
    print(f"\n실패 {len(FAIL)}개" if FAIL else "\n모두 통과")
    sys.exit(1 if FAIL else 0)
