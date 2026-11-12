# 설치·실행기 단위 시험(받기·설치·서버 켜기 없음) — python -B -m tests.unit.test_installer
#   사양별 구성(가짜 사양) · 잠금 파일·실행 파일 목록의 주소·해시 모양 · 실행기가 만드는 명령(켜지 않음) · 압축 경로 막기 · 확인 기록
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "installer"))

import get_models as GM  # noqa: E402
import plan as PLAN  # noqa: E402
import setup_core as SC  # noqa: E402

OK = []


def check(name, cond, info=""):
    OK.append((name, bool(cond)))
    print(("됨  " if cond else "실패") + " " + name + (f" — {info}" if info and not cond else ""))


def g(name, mib):
    return [{"이름": name, "전체_MiB": mib, "남은_MiB": mib}]


def cli(claude=None, codex=None):
    """가짜 구독 두뇌 상태: None = 없음 · True = 로그인됨 · False = 있지만 로그인 안 됨"""
    def one(v):
        return {"있음": v is not None, "로그인": bool(v), "판": "시험"}
    return {"claude": one(claude), "codex": one(codex)}


BM = PLAN.BRAIN_MODEL


def test_plan():
    p = PLAN.make_plan(g("RTX 4070", 12282), 32, 500, 600.0)
    check("12GB·구독 없음: 전부 그래픽카드·김비서 목소리·Gemma 무검열 판", p["구성"] == "그래픽 메모리 넉넉함" and p["설정"]["목소리.엔진"] == "qwen"
          and p["llama"] == "cuda13" and p["torch"] == "cu128" and BM == "gemma-4-E4B-it-abliterated-Q4_K"
          and set(p["모델"]) == {BM, "whisper-large-v3-turbo", "Qwen3-TTS-12Hz-0.6B-Base"} and p["설정"]["두뇌.방식"] == "local")
    p = PLAN.make_plan(g("RTX 4060", 8188), 16, 500, 600.0)
    check("8GB·구독 없음: 김비서 목소리(Qwen)·두뇌·귀 그래픽카드(받아쓰기 CPU 규칙은 기본 끔)", p["구성"] == "그래픽 메모리 8GB 이하"
          and p["설정"]["목소리.엔진"] == "qwen" and p["설정"]["두뇌.방식"] == "local" and p["llama"] == "cuda13"
          and "Qwen3-TTS-12Hz-0.6B-Base" in p["모델"] and p["설정"]["귀.장치"] == "auto" and not PLAN.sysinfo.EAR_CPU_WITH_GEMMA
          and any("목소리" in x and "Qwen" in x for x in p["판별"]) and any("빠듯" in x for x in p["안내"]))
    PLAN.sysinfo.EAR_CPU_WITH_GEMMA = True    # 규칙을 켜기로 하면 이렇게 됨
    try:
        p = PLAN.make_plan(g("RTX 4060", 8188), 16, 500, 600.0)
        check("(규칙 켬) 8GB·구독 없음: 받아쓰기 CPU·근거 기록", p["설정"]["귀.장치"] == "cpu" and "whisper-large-v3-turbo" in p["모델"]
              and any("받아쓰기 CPU" in x for x in p["판별"]))
        p = PLAN.make_plan(g("RTX 4060", 6144), 16, 500, 600.0)
        check("(규칙 켬) 6GB·구독 없음: 받아쓰기 CPU", p["설정"]["귀.장치"] == "cpu" and p["llama"])
        p = PLAN.make_plan(g("RTX 4060", 8188), 16, 500, 600.0, cli=cli(claude=True))
        check("(규칙 켬) 8GB·구독 클로드: Gemma 없음 → 받아쓰기 자동", p["설정"]["귀.장치"] == "auto")
        p = PLAN.make_plan(g("RTX 4070", 12282), 16, 500, 600.0)
        check("(규칙 켬) 12GB·Gemma: 받아쓰기 자동", p["설정"]["귀.장치"] == "auto")
    finally:
        PLAN.sysinfo.EAR_CPU_WITH_GEMMA = False
    p = PLAN.make_plan(g("RTX 4060", 8188), 16, 500, 600.0, gemma="E2B")
    e2b = PLAN.BRAIN_MODELS["E2B"]
    check("--gemma E2B: 작은 판을 받음(기본 E4B 안 받음)", e2b in p["모델"] and BM not in p["모델"] and p["두뇌_모델"] == e2b
          and any("E2B" in x for x in p["판별"]))
    check("brain_model: e2b·E2B·이름·모름", PLAN.brain_model("e2b") == e2b and PLAN.brain_model("E4B") == BM
          and PLAN.brain_model(e2b) == e2b and PLAN.brain_model("x") == BM and PLAN.brain_model(None) == BM)
    mf = GM.load_manifest()
    check("models.json E2B: 원작자 저장소·판 고정·sha256·크기", e2b in mf and mf[e2b]["source"].startswith("https://huggingface.co/huihui-ai/")
          and len(mf[e2b]["revision"]) == 40 and all(len(f["sha256"]) == 64 for f in mf[e2b]["files"])
          and mf[e2b]["size_total"] == sum(f["size"] for f in mf[e2b]["files"]))
    p = PLAN.make_plan(g("RTX 4060", 6144), 16, 500, 600.0)
    check("6GB 딱: 김비서 목소리", p["설정"]["목소리.엔진"] == "qwen")
    p = PLAN.make_plan(g("GTX 1660", 6143), 16, 500, 600.0)
    check("6GB 미만: 윈도우 음성·근거 기록", p["설정"]["목소리.엔진"] == "windows" and "Qwen3-TTS-12Hz-0.6B-Base" not in p["모델"]
          and any("윈도우" in x for x in p["판별"]))
    p = PLAN.make_plan(g("RTX 4060", 8188), 16, 500, 600.0, cli=cli(claude=True))
    check("구독 클로드 로그인: 두뇌 = claude_cli · Gemma·llama 안 받음", p["설정"]["두뇌.방식"] == "claude_cli" and p["llama"] == ""
          and BM not in p["모델"] and p["두뇌_제안"] == "claude_cli" and any("Gemma 안 받음" in x for x in p["판별"]))
    p = PLAN.make_plan(g("RTX 4070", 12282), 16, 500, 600.0, cli=cli(claude=False, codex=True))
    check("클로드 로그인 안 됨 + Codex 로그인: 두뇌 = codex_cli", p["설정"]["두뇌.방식"] == "codex_cli" and p["llama"] == "")
    p = PLAN.make_plan(g("RTX 4070", 12282), 16, 500, 600.0, cli=cli(claude=True, codex=True))
    check("둘 다 로그인: 클로드 먼저", p["설정"]["두뇌.방식"] == "claude_cli")
    p = PLAN.make_plan(g("RTX 4070", 12282), 16, 500, 600.0, cli=cli(claude=False, codex=False))
    check("설치만 돼 있고 로그인 없음: Gemma 받음", p["설정"]["두뇌.방식"] == "local" and BM in p["모델"])
    p = PLAN.make_plan([], 16, 500, cli=cli(codex=True))
    check("그래픽카드 없음 + Codex 로그인: codex_cli", p["설정"]["두뇌.방식"] == "codex_cli" and p["llama"] == "")
    p = PLAN.make_plan(g("RTX 3060", 12288), 16, 500, 560.9)
    check("옛 드라이버(<580): llama CUDA 12 판", p["llama"] == "cuda12")
    p = PLAN.make_plan([], 16, 500)
    check("그래픽카드 없음: 바깥 두뇌·윈도우 음성·작은 귀·CPU torch·두뇌 안 받음",
          p["구성"] == "그래픽카드 없음" and p["설정"]["두뇌.방식"] == "url" and p["설정"]["목소리.엔진"] == "windows"
          and p["설정"]["귀.모델"] == "whisper-small" and p["설정"]["귀.장치"] == "cpu" and p["torch"] == "cpu" and p["llama"] == ""
          and p["모델"] == ["whisper-small"])
    p = PLAN.make_plan([], 16, 500, others=["AMD Radeon RX 7600"], local_brain=True)
    check("그래픽카드 없음 + 이 PC 두뇌(AMD): 불칸 판", p["llama"] == "vulkan" and BM in p["모델"] and p["설정"]["두뇌.방식"] == "local")
    p = PLAN.make_plan([], 16, 500, local_brain=True)
    check("그래픽카드 없음 + 이 PC 두뇌(없음): CPU 판", p["llama"] == "cpu" and p["설정"]["실행.두뇌_장치"] == "cpu")
    p = PLAN.make_plan(g("GTX 1650", 4096), 16, 500, 600.0)
    check("6GB 미만: 두뇌 바깥, 귀 그래픽카드", p["구성"] == "그래픽 메모리 6GB 미만" and p["llama"] == "" and p["설정"]["귀.장치"] == "auto")
    p = PLAN.make_plan(g("RTX 4070", 12282), 32, 10, 600.0)
    check("디스크 모자람 표시", p.get("디스크_모자람") and p["경고"])
    p = PLAN.make_plan(g("RTX 4070", 12282), 6, 500, 600.0)
    check("램 6GB 경고", any("램" in w for w in p["경고"]))
    os.environ["KIMBISEO_FAKE_GPU"] = "none"
    os.environ["KIMBISEO_FAKE_OTHER_GPU"] = ""
    os.environ["KIMBISEO_FAKE_CLI"] = "none"
    try:
        p = PLAN.detect(tempfile.gettempdir())
        check("가짜 사양 환경변수(none) → 그래픽카드 없음", p["구성"] == "그래픽카드 없음")
        os.environ["KIMBISEO_FAKE_GPU"] = "RTX 4070:12282"
        check("가짜 사양 환경변수(12GB)", PLAN.detect(tempfile.gettempdir())["구성"] == "그래픽 메모리 넉넉함")
        os.environ["KIMBISEO_FAKE_GPU"] = "RTX 4060:8188"
        check("가짜 사양 환경변수(8GB)", PLAN.detect(tempfile.gettempdir())["구성"] == "그래픽 메모리 8GB 이하")
        from app.core import cli_detect
        cli_detect._CACHE.clear()
        os.environ["KIMBISEO_FAKE_CLI"] = "claude:off,codex:on"
        p = PLAN.detect(tempfile.gettempdir())
        check("가짜 구독 환경변수(claude 로그인 안 됨·codex 됨) → codex_cli", p["설정"]["두뇌.방식"] == "codex_cli" and p["llama"] == "")
        p = PLAN.detect(tempfile.gettempdir(), local_brain=True, cli=False)
        check("Gemma 만 다시 설치(cli=False) → 구독 안 봄", p["설정"]["두뇌.방식"] == "local" and p["llama"])
    finally:
        os.environ.pop("KIMBISEO_FAKE_GPU", None)
        os.environ.pop("KIMBISEO_FAKE_OTHER_GPU", None)
        os.environ.pop("KIMBISEO_FAKE_CLI", None)


def test_manifests():
    rt = json.load(open(os.path.join(ROOT, "installer", "runtimes.json"), encoding="utf-8"))
    hosts = rt["hosts"]
    urls = [rt["python"], rt["pip"], rt["setuptools"], rt["electron"]] + [f for v in rt["llama_cpp"]["variants"].values() for f in v]
    check("실행 파일 목록: 전부 https·허용 호스트·sha256·크기", all(GM.host_ok(x["url"], hosts) and len(x["sha256"]) == 64 and x["size"] > 0 for x in urls))
    for name in ("app.json", "voice-cuda.json", "voice-cpu.json"):
        lk = json.load(open(os.path.join(ROOT, "installer", "locks", name), encoding="utf-8"))
        pk = lk["packages"]
        bad = [x["name"] for x in pk if not (GM.host_ok(x["url"], hosts) and len(x["sha256"]) == 64 and x["version"])]
        check(f"잠금 {name}: {len(pk)}개 모두 판·주소·sha256", not bad and lk["python"] == rt["python"]["version"], ",".join(bad))
    cu = {x["name"]: x for x in json.load(open(os.path.join(ROOT, "installer", "locks", "voice-cuda.json"), encoding="utf-8"))["packages"]}
    cp = {x["name"]: x for x in json.load(open(os.path.join(ROOT, "installer", "locks", "voice-cpu.json"), encoding="utf-8"))["packages"]}
    check("음성 잠금: torch 엔비디아 판 / CPU 판", cu["torch"]["version"].endswith("+cu128") and cp["torch"]["version"].endswith("+cpu"))
    check("음성 환경에 PyAV 없음(설치판에 안 넣음)", "av" not in cu and "av" not in cp)
    app = {x["name"]: x for x in json.load(open(os.path.join(ROOT, "installer", "locks", "app.json"), encoding="utf-8"))["packages"]}
    check("본체 잠금에 anthropic·pipecat-ai·pywebview", all(n in app for n in ("anthropic", "pipecat-ai", "pywebview")))
    mf = GM.load_manifest()
    check("모델 목록: 두뇌(무검열 판·옛 판)·작은 귀, 큰 파일 sha256", BM in mf and "gemma-4-E4B-it-Q4_K_M" in mf and "whisper-small" in mf
          and all(f.get("sha256") or f.get("git_sha1") for n in (BM, "gemma-4-E4B-it-Q4_K_M", "whisper-small", "whisper-large-v3-turbo",
                                                                 "Qwen3-TTS-12Hz-0.6B-Base") for f in mf[n]["files"]))
    gm = mf[BM]
    check("무검열 판: 원 출처(huihui-ai)·고정 판·Apache-2.0", "huggingface.co/huihui-ai/" in gm["source"] and len(gm.get("revision") or "") == 40
          and "{revision}" in gm["base_url"] and "Apache-2.0" in json.dumps(gm, ensure_ascii=False))
    ic = json.load(open(os.path.join(ROOT, "installer", "install_config.json"), encoding="utf-8"))
    pc = json.load(open(os.path.join(ROOT, "pet", "config.json"), encoding="utf-8"))
    host = ic["packs_catalog"].split("/")[2] if ic["packs_catalog"] else ""
    check("옷 목록 주소 = https 이고 펫 허용 호스트 안", (not host) or (ic["packs_catalog"].startswith("https://") and host in pc["allowed_hosts"]))
    check("옷 목록 = 옷 저장소 outfits.json · 예비 = 옛 packs.json(둘 다 허용 호스트)", ic["packs_catalog"] == pc["packs_catalog"]
          and ic["packs_catalog"].endswith("/kimbiseo-outfits/main/outfits.json") and pc["packs_catalog_backup"].endswith("/packs.json")
          and all(u.split("/")[2] in pc["allowed_hosts"] for u in (pc["packs_catalog"], pc["packs_catalog_backup"])))


def test_gemma_admin():
    """설정 '두뇌 바꾸기'의 Gemma 지우기·경로 고르기(실제 큰 파일 없이 작은 가짜로)."""
    P = tempfile.mkdtemp()
    D = tempfile.mkdtemp()
    mf = GM.load_manifest()
    ab = mf[BM]["files"][0]
    old = next(f for f in mf["gemma-4-E4B-it-Q4_K_M"]["files"] if f["path"].endswith(".gguf"))

    class A:
        prefix, data, status, source, local_brain, dry_run, packs_catalog = P, D, os.path.join(P, "st.json"), "", False, False, None
    ins = SC.Installer(A)
    check("Gemma 없음 → 경로 ''", ins.gemma_file() == "")
    od = os.path.join(P, "models", "gemma-4-E4B-it-Q4_K_M")
    os.makedirs(od)
    with open(os.path.join(od, old["path"]), "wb") as f:
        f.truncate(old["size"])          # 크기만 맞춘 빈 파일(희소)
    check("옛 Gemma 만 있으면 그 경로", ins.gemma_file().endswith(old["path"]))
    nd = os.path.join(P, "models", BM)
    os.makedirs(nd)
    with open(os.path.join(nd, ab["path"]), "wb") as f:
        f.truncate(ab["size"] - 1)       # 덜 받은 파일
    check("무검열 판을 덜 받았으면 옛 판", ins.gemma_file().endswith(old["path"]))
    with open(os.path.join(nd, ab["path"]), "wb") as f:
        f.truncate(ab["size"])
    check("무검열 판이 다 있으면 그것 먼저", ins.gemma_file().endswith(ab["path"]) and ins.gemma_dirs()[0] == BM)
    e2b = PLAN.BRAIN_MODELS["E2B"]
    sm = mf[e2b]["files"][0]
    sd = os.path.join(P, "models", e2b)
    os.makedirs(sd)
    with open(os.path.join(sd, sm["path"]), "wb") as f:
        f.truncate(sm["size"])

    class A2(A):
        gemma = "E2B"
    ins2 = SC.Installer(A2)
    check("--gemma E2B: E2B 폴더 먼저·그 경로", ins2.bm == e2b and ins2.gemma_dirs()[0] == e2b and ins2.gemma_file().endswith(sm["path"]))
    check("기본(E4B) 설치기는 그대로 E4B 먼저", ins.gemma_file().endswith(ab["path"]))
    import shutil as _sh
    _sh.rmtree(sd)
    os.makedirs(os.path.join(P, "runtime", "llama"))
    open(os.path.join(P, "runtime", "llama", "llama-server.exe"), "wb").close()
    with open(os.path.join(D, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"실행": {"두뇌_모델": "x", "두뇌_실행파일": "y", "앱_파이썬": "z"}}, f)
    r = ins.remove_gemma()
    cur = json.load(open(os.path.join(D, "settings.json"), encoding="utf-8"))
    check("Gemma 지우기: 모델 두 폴더·두뇌 프로그램 지움·설정 경로 비움·다른 설정 그대로",
          r["ok"] and set(r["지움"]) == {BM, "gemma-4-E4B-it-Q4_K_M", "llama"} and r["돌려준_바이트"] == ab["size"] + old["size"]
          and not os.path.isdir(od) and not os.path.isdir(nd) and cur["실행"]["두뇌_모델"] == "" and cur["실행"]["두뇌_실행파일"] == ""
          and cur["실행"]["앱_파이썬"] == "z", json.dumps(r, ensure_ascii=False))


def test_zip_guard():
    with tempfile.TemporaryDirectory() as td:
        z = os.path.join(td, "x.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("top/a.txt", "a")
            f.writestr("top/b/c.txt", "c")
        SC.extract_zip(z, os.path.join(td, "out"), strip_single_root=True)
        check("압축 풀기: 한 겹 뿌리 폴더 벗기기", os.path.isfile(os.path.join(td, "out", "b", "c.txt")))
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("../evil.txt", "x")
        try:
            SC.extract_zip(z, os.path.join(td, "out2"))
            check("압축 풀기: 바깥 경로 막기", False)
        except SC.Fail:
            check("압축 풀기: 바깥 경로 막기", not os.path.exists(os.path.join(td, "evil.txt")))


def test_verify_seen():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "m.bin")
        open(p, "wb").write(b"hello" * 1000)
        h = GM.file_hashes(p)[0]
        spec = {"size": 5000, "sha256": h}
        ok1 = GM.verify(p, spec)[0]
        why = GM.verify(p, spec, use_seen=True)[1]
        check("확인 기록: 두 번째는 다시 계산 안 함", ok1 and "확인 기록" in why)
        open(p, "r+b").write(b"J")
        os.utime(p, ns=(1, 1))
        check("확인 기록: 파일이 바뀌면 다시 계산해 틀림을 잡음", GM.verify(p, spec, use_seen=True)[0] is False)
        check("허용 안 된 주소 거절", not GM.host_ok("http://huggingface.co/x") and not GM.host_ok("https://evil.example/x"))


def test_launcher_spec():
    try:
        from app import launcher as L
    except Exception as ex:  # noqa: BLE001
        check("실행기 불러오기", False, repr(ex))
        return
    with tempfile.TemporaryDirectory() as td:
        exe = os.path.join(td, "llama", "llama-server.exe")
        model = os.path.join(td, "models", "g.gguf")
        pet = os.path.join(td, "electron", "electron.exe")
        for f in (exe, model, pet):
            os.makedirs(os.path.dirname(f), exist_ok=True)
            open(f, "wb").close()
        st = {"경로": {"자료": os.path.join(td, "자료"), "로그": os.path.join(td, "자료", "logs"), "모델": os.path.join(td, "models"),
                     "캐시": os.path.join(td, "cache")},
              "실행": {"두뇌_실행파일": exe, "두뇌_모델": model, "두뇌_장치": "cpu", "펫_실행파일": pet, "펫_폴더": os.path.join(ROOT, "pet")},
              "두뇌": {"방식": "local"}, "펫": {"옷_받기": True, "옷목록_주소": "https://example.org/x/packs.json"}}
        sp = os.path.join(td, "자료", "settings.json")
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        la = L.Launcher(sp)
        cmd, cwd, env, skip = la.spec("brain")
        check("실행기: 두뇌 CPU 명령(-ngl 0 -dev none, 127.0.0.1:8880)", skip is None and "-dev" in cmd and cmd[cmd.index("-ngl") + 1] == "0"
              and cmd[cmd.index("--port") + 1] == "8880" and cmd[cmd.index("--host") + 1] == "127.0.0.1" and env.get("CUDA_VISIBLE_DEVICES") == "-1")
        cmd, _, _, skip = la.spec("pet")
        check("실행기: 펫 명령(옷 받기 동의 → --auto-pack, 옷 목록 주소)", skip is None and "--auto-pack" in cmd
              and any(x.startswith("--pack-source=https://") for x in cmd) and any(x.startswith("--profile=") for x in cmd))
        st["펫"]["옷목록_주소"] = L.OLD_PACK_CATALOGS[0]
        json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        la.reload()
        cmd, _, _, _ = la.spec("pet")
        check("실행기: 0.1.8 까지의 옛 옷 목록 주소는 안 넘김(펫 기본 = 옷 저장소 outfits.json)", not any(x.startswith("--pack-source=") for x in cmd))
        st["펫"]["옷목록_주소"] = "https://example.org/x/packs.json"
        json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        la.reload()
        cmd, _, _, _ = la.spec("body")
        check("실행기: 본체에 --parent_pid", "--parent_pid" in cmd and str(os.getpid()) in cmd)
        cmd, _, _, _ = la.spec("tts")
        check("실행기: 목소리에 설정·부모 PID", cmd[-4:-2] == ["--parent_pid", str(os.getpid())] or "--parent_pid" in cmd)
        st["두뇌"]["방식"] = "url"
        json.dump(st, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        la.reload()
        check("실행기: 바깥 두뇌면 두뇌 안 켬", la.spec("brain")[3] is not None)
        check("실행기: 남의 PID 는 같은 프로세스로 안 봄", not L.same_proc({"pid": os.getpid(), "exe": "C:\\없는\\x.exe", "created": 1}))
        me = L.proc_info(os.getpid())
        check("실행기: 내 PID 확인(실행 파일·시작 시각)", me and L.same_proc({"pid": os.getpid(), "exe": me[0], "created": me[1]}))


def test_qwen_gpu_threshold():
    """목소리 서버 auto: 남은 그래픽 메모리 3,300MiB 미만이면 Qwen 대신 윈도우 음성(15단계 — 2,458 로는 켠 뒤 꽉 차 끊김)."""
    import types
    sys.path.insert(0, os.path.join(ROOT, "voice"))
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True, set_per_process_memory_fraction=lambda *a: None,
                                            mem_get_info=lambda: (0, 8 * 2**30))

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop()
    fake_engine = types.ModuleType("tts_engine")
    fake_engine.QwenVoice, fake_engine.load_refs = stop, stop
    saved = {k: sys.modules.get(k) for k in ("torch", "tts_engine")}
    sys.modules["torch"], sys.modules["tts_engine"] = fake_torch, fake_engine
    try:
        import tts_server as TS
        check("목소리: Qwen 그래픽카드 기준 3,300MiB", TS.QWEN_GPU_FREE_MIN_MIB == 3300)
        with tempfile.TemporaryDirectory() as td:
            model, refs = os.path.join(td, "m"), os.path.join(td, "r")
            os.makedirs(model)
            os.makedirs(refs)
            open(os.path.join(refs, "참고목록.json"), "w", encoding="utf-8").write("[]")
            cfg = {"목소리": {"모델": model, "참고음성_폴더": refs, "그래픽메모리_상한_GB": 1.8, "CPU면_윈도우": True}}
            TS.STATE["cfg"], TS.STATE["default_voice"] = cfg, "kimbiseo"
            orig_free, orig_log = TS.C.gpu_free_mib, TS.log
            TS.log = lambda m: None
            try:
                for free, want in ((2761, "windows"), (3299, "windows"), (3300, "cuda"), (5000, "cuda")):
                    TS.C.gpu_free_mib = lambda f=free: (float(f), 8151.0)
                    try:
                        TS.load_qwen(cfg, "auto", 4)
                        got = "?"
                    except TS.SlowVoice:
                        got = "windows"
                    except Stop:
                        got = "cuda"
                    check(f"목소리: 남은 {free}MiB → {want}", got == want, got)
            finally:
                TS.C.gpu_free_mib, TS.log = orig_free, orig_log
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("tts_server", None)


def main():
    test_plan()
    test_manifests()
    test_gemma_admin()
    test_zip_guard()
    test_verify_seen()
    test_launcher_spec()
    test_qwen_gpu_threshold()
    bad = [n for n, ok in OK if not ok]
    print(f"\n설치 단위 시험: {len(OK) - len(bad)}/{len(OK)} 됨" + (f" · 실패: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
