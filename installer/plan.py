# 사양 보고 설치 구성 고르기 — 그래픽카드 종류·그래픽 메모리·램·디스크 여유 → 무엇을 받고 어떻게 켤지.
#   python plan.py [--prefix 설치폴더] [--local-brain] [--json]      (시험: 환경변수로 가짜 사양)
#
# 규칙(3단계·2단계 실측: 두뇌 Q4_K_M 8K 약 3.5GB · 귀 약 2.1GB · 김비서 목소리 약 2.0GB · 화면 0.5GB)
#   목소리(0.1.4~, '되는 PC 는 전부 Qwen'): 엔비디아 그래픽 메모리 6GB 이상 → 김비서 목소리(Qwen)
#       6GB 미만·엔비디아 없음만 윈도우 기본 음성. 판별 근거(sysinfo.voice_rule 글)를 설치 기록에 남김.
#       켤 때·쓰는 중 그래픽 메모리가 모자라면 목소리 서버가 윈도우 음성으로 스스로 바꿈(끊지 않음).
#   두뇌(0.1.4~): 이 PC 에 클로드 코드(claude)·Codex(codex)가 로그인돼 있으면 그것을 기본으로(첫 화면에서 권함) — Gemma 는 안 받음.
#       구독이 없을 때만 Gemma 4 E4B 무검열 판(models.json 'gemma-4-E4B-it-abliterated-Q4_K', 원 출처에서 직접 받음)
#       --gemma E2B 면 작은 판(gemma-4-E2B-it-abliterated-Q4_K, 약 3.4GB) — 설정 '두뇌 바꾸기 → Gemma 설치'에서도 고름
#   귀(0.1.6~): sysinfo.EAR_CPU_WITH_GEMMA 가 켜져 있으면 엔비디아 9GB 미만 + 이 PC Gemma 일 때 받아쓰기 CPU(귀.장치 cpu).
#       14단계 실측에서 CPU 받아쓰기가 너무 느려(한 문장 2.6~8.4초) 기본은 끔 — 사용자는 설정 '목소리 → 받아쓰기 장치'에서 고름
#   엔비디아 그래픽 메모리 9GB 이상(12GB 이상 권장) → 두뇌·귀·김비서 목소리 모두 그래픽카드          = "그래픽 메모리 넉넉함"
#   엔비디아 6GB 이상 9GB 미만(8GB 급)             → 두뇌·귀·김비서 목소리 그래픽카드(빠듯 — 모자라면 목소리 자동 대체) = "그래픽 메모리 8GB 이하"
#   엔비디아 6GB 미만                              → 귀 그래픽카드, 목소리 = 윈도우 음성, 두뇌 = 바깥 AI 권장 = "그래픽 메모리 6GB 미만"
#   엔비디아 없음(AMD·인텔·없음)                   → 두뇌 = 바깥 AI(내 AI 주소·GPT·클로드) 안내, 목소리 = 윈도우 음성,
#                                                    귀 = CPU + 작은 귀(whisper-small), torch = CPU 판           = "그래픽카드 없음"
#   --local-brain : 그래픽카드가 모자라도 이 PC 에서 두뇌를 돌림(엔비디아가 아닌 그래픽카드면 불칸 판, 없으면 CPU 판 — 느림)
#
# 가짜 사양(시험): KIMBISEO_FAKE_GPU="이름:전체MiB" 또는 "none" · KIMBISEO_FAKE_OTHER_GPU="AMD Radeon RX 7600"(엔비디아 아닌 그래픽카드)
#                  KIMBISEO_FAKE_DRIVER="560.94"(엔비디아 드라이버 판) · KIMBISEO_FAKE_RAM_GB="16" · KIMBISEO_FAKE_DISK_GB="30"
#                  KIMBISEO_FAKE_CLI="claude:on,codex:off" | "none"(구독 두뇌 — core/cli_detect)
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from app.core import cli_detect  # noqa: E402  (표준 라이브러리만 씀)
from app.core import sysinfo  # noqa: E402  (표준 라이브러리만 씀)

BRAIN_MODELS = {"E4B": "gemma-4-E4B-it-abliterated-Q4_K", "E2B": "gemma-4-E2B-it-abliterated-Q4_K"}   # models.json 이름
BRAIN_MODEL = BRAIN_MODELS["E4B"]   # 0.1.4 기본 두뇌(무검열 판). 기본값을 바꾸는 것은 운영자 확인 뒤


def brain_model(gemma=None):
    """'E4B'·'E2B'(대소문자 무시) 또는 models.json 이름 → models.json 이름. 모르는 값이면 기본(E4B)."""
    g = str(gemma or "").strip()
    if g in BRAIN_MODELS.values():
        return g
    return BRAIN_MODELS.get(g.upper(), BRAIN_MODEL)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GB = 1024 ** 3

# 설치 뒤 크기(대략, 실측 + 여유) — 디스크 여유 검사용
SIZE_GB = {"python_app": 0.9, "python_voice_cuda": 5.6, "python_voice_cpu": 1.6, "llama_cuda": 1.3, "llama_vulkan": 0.1, "llama_cpu": 0.1,
           "electron": 0.35, "src": 0.05, "pet_pack": 0.2}
TEMP_GB = 4.5   # 받는 동안 잠깐 쓰는 자리(파이썬 부품 꾸러미·압축 파일 — 끝나면 지움)


def nvidia_driver():
    fake = os.environ.get("KIMBISEO_FAKE_DRIVER")
    if fake:
        try:
            return float(fake)
        except ValueError:
            return 0.0
    if os.environ.get("KIMBISEO_FAKE_GPU"):
        return 999.0
    exe = shutil.which("nvidia-smi")
    if not exe:
        return 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True,
                             timeout=10, creationflags=NO_WINDOW).stdout.strip().splitlines()
        return float(out[0].split(".")[0] + "." + (out[0].split(".") + ["0"])[1]) if out else 0.0
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0.0


def other_gpus():
    """엔비디아가 아닌 그래픽카드 이름(불칸 판 llama.cpp 를 고를 때만 씀). 기본 화면 장치(Microsoft Basic 등)는 뺌."""
    fake = os.environ.get("KIMBISEO_FAKE_OTHER_GPU")
    if fake is not None:
        return [x.strip() for x in fake.split(",") if x.strip()]
    if os.environ.get("KIMBISEO_FAKE_GPU"):
        return []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; (Get-CimInstance Win32_VideoController).Name"],
                             capture_output=True, timeout=30, creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    names = [x.strip() for x in out.splitlines() if x.strip()]
    return [n for n in names if "nvidia" not in n.lower() and not any(w in n.lower() for w in ("basic", "remote", "virtual", "parsec", "meta"))]


def make_plan(gpu_list, ram_gb, disk_gb, driver=0.0, others=(), local_brain=False, cli=None, gemma=None):
    """cli: core/cli_detect.all_status() 결과(None = 구독 두뇌 없음으로 봄) · gemma: 'E4B'(기본)·'E2B'."""
    bm = brain_model(gemma)
    g = max(gpu_list, key=lambda x: x["전체_MiB"]) if gpu_list else None
    mib = g["전체_MiB"] if g else 0
    sub = cli_detect.suggest(cli) if cli else ""
    plan = {"그래픽카드": g, "다른_그래픽카드": list(others), "램_GB": ram_gb, "디스크_여유_GB": disk_gb, "드라이버": driver,
            "안내": [], "경고": [], "설정": {}, "구독": {k: {x: v.get(x) for x in ("있음", "로그인", "판")} for k, v in (cli or {}).items()},
            "두뇌_제안": sub, "판별": [], "두뇌_모델": bm}
    st = plan["설정"]
    v_eng, v_why = sysinfo.voice_rule(g)
    plan["판별"].append("목소리: " + v_why)
    if g and mib >= sysinfo.SMALL_GPU_MIB:
        plan["구성"] = "그래픽 메모리 넉넉함"
        plan["torch"], brain, voice_model = "cu128", "gpu", True
        st.update({"목소리.엔진": "qwen", "목소리.장치": "auto", "귀.장치": "auto", "두뇌.방식": "local"})
        plan["안내"].append(f"{g['이름']} ({mib / 1024:.0f}GB): 두뇌·받아쓰기·김비서 목소리를 모두 그래픽카드로 해요.")
    elif g and mib >= sysinfo.QWEN_MIN_MIB:
        plan["구성"] = "그래픽 메모리 8GB 이하"
        plan["torch"], brain, voice_model = "cu128", "gpu", True
        st.update({"목소리.엔진": "qwen", "목소리.장치": "auto", "귀.장치": "auto", "두뇌.방식": "local"})
        plan["안내"].append(f"{g['이름']} ({mib / 1024:.0f}GB): 받아쓰기·김비서 목소리를 그래픽카드로 해요.")
    elif g:
        plan["구성"] = "그래픽 메모리 6GB 미만"
        plan["torch"], voice_model = "cu128", False
        brain = "gpu" if local_brain else ""
        st.update({"목소리.엔진": "windows", "목소리.장치": "cpu", "귀.장치": "auto", "두뇌.방식": "local" if local_brain else "url"})
        plan["안내"].append(f"{g['이름']} ({mib / 1024:.0f}GB): 받아쓰기는 그래픽카드로, 목소리는 윈도우 기본 음성으로 해요.")
        if not local_brain:
            plan["안내"].append("두뇌는 처음 화면에서 '내 AI 주소'·GPT·클로드 가운데 골라 주세요(이 PC 에서 돌리기엔 그래픽 메모리가 모자라요).")
    else:
        plan["구성"] = "그래픽카드 없음"
        plan["torch"], voice_model = "cpu", False
        brain = ("vulkan" if others else "cpu") if local_brain else ""
        st.update({"목소리.엔진": "windows", "목소리.장치": "cpu", "귀.장치": "cpu", "귀.모델": "whisper-small",
                   "두뇌.방식": "local" if local_brain else "url"})
        plan["안내"].append("엔비디아 그래픽카드가 보이지 않아요. 목소리는 윈도우 기본 음성, 받아쓰기는 작은 귀(whisper-small)를 CPU 로 해요.")
        if local_brain:
            plan["안내"].append("두뇌를 이 PC 에서 돌려요(" + ("불칸 — " + others[0] if others else "CPU") + "). 대답이 느릴 수 있어요.")
        else:
            plan["안내"].append("두뇌는 처음 화면에서 '내 AI 주소'·GPT·클로드 가운데 골라 주세요. 이 PC 에서 돌리면 아주 느려요.")
    if sub:   # 구독 두뇌가 로그인돼 있으면 Gemma·두뇌 프로그램은 받지 않음(설정에서 'Gemma 설치'로 나중에)
        brain = ""
        st["두뇌.방식"] = sub
        nm = "클로드 코드" if sub == "claude_cli" else "GPT(Codex)"
        plan["안내"].append(f"이 PC 에 {nm} 로그인이 있어 그것을 두뇌로 써요(본인 구독). Gemma 는 받지 않아요 — 설정에서 언제든 설치할 수 있어요.")
        plan["판별"].append(f"두뇌: {nm} 로그인됨 → 구독 두뇌, Gemma 안 받음")
    elif brain:
        plan["판별"].append(f"두뇌: {'구독 두뇌 로그인 없음' if cli is not None else '구독 두뇌는 보지 않음'} → Gemma 4 {'E2B' if 'E2B' in bm else 'E4B'} 무검열 판({bm})")
    else:
        plan["판별"].append("두뇌: 구독 두뇌 로그인 없음 · 이 PC 그래픽카드로는 Gemma 가 느림 → 처음 화면에서 고름(설정에서 Gemma 설치 가능)")
    # 두뇌(llama.cpp) 판 고르기
    if brain == "gpu":
        plan["llama"] = "cuda13" if driver >= 580.0 else "cuda12"
        st["실행.두뇌_장치"] = "gpu"
    elif brain in ("vulkan", "cpu"):
        plan["llama"] = brain
        st["실행.두뇌_장치"] = "gpu" if brain == "vulkan" else "cpu"
    else:
        plan["llama"] = ""
    # 귀: 9GB 미만 엔비디아에서 Gemma 를 그래픽카드로 돌리면 받아쓰기는 CPU(두뇌 + 귀 + 김비서 목소리를 다 올리면 넘침)
    if sysinfo.EAR_CPU_WITH_GEMMA and g and mib < sysinfo.SMALL_GPU_MIB and brain == "gpu":
        st["귀.장치"] = "cpu"
        plan["판별"].append(f"귀: 그래픽 메모리 {mib / 1024:.1f}GB < {sysinfo.SMALL_GPU_MIB / 1024:.0f}GB + 이 PC 두뇌(Gemma) → 받아쓰기 CPU")
        plan["안내"].append("이 PC 의 두뇌(Gemma)를 그래픽카드로 돌려서 받아쓰기는 CPU 로 해요(설정 '목소리'에서 바꿀 수 있어요). "
                          "그래도 모자라면 목소리가 저절로 윈도우 음성으로 바뀌어요.")
    elif g and mib < sysinfo.SMALL_GPU_MIB and brain == "gpu":
        plan["안내"].append("이 PC 의 두뇌(Gemma)까지 켜면 그래픽 메모리가 빠듯해요. 모자라면 두뇌는 CPU 로, 목소리는 윈도우 음성으로 저절로 바뀌어요.")
    models = ["whisper-small"] if plan["구성"] == "그래픽카드 없음" else ["whisper-large-v3-turbo"]
    if voice_model:
        models.append("Qwen3-TTS-12Hz-0.6B-Base")
    if plan["llama"]:
        models.insert(0, bm)
    plan["모델"] = models
    # 필요한 디스크
    try:
        sys.path.insert(0, HERE)
        import get_models as GM
        mf = GM.load_manifest()
        model_gb = sum(mf[n]["size_total"] for n in models if n in mf) / GB
    except Exception:  # noqa: BLE001
        model_gb = 0.0
    need = (SIZE_GB["python_app"] + SIZE_GB["python_voice_cuda" if plan["torch"] == "cu128" else "python_voice_cpu"] + SIZE_GB["electron"]
            + SIZE_GB["src"] + SIZE_GB["pet_pack"] + model_gb
            + (SIZE_GB["llama_cuda"] if plan["llama"].startswith("cuda") else SIZE_GB["llama_vulkan"] if plan["llama"] else 0))
    plan["설치_크기_GB"] = round(need, 1)
    plan["필요_디스크_GB"] = round(need + TEMP_GB, 1)
    if disk_gb is not None and disk_gb < plan["필요_디스크_GB"]:
        plan["경고"].append(f"디스크 여유가 모자라요: 필요 약 {plan['필요_디스크_GB']}GB, 남은 공간 {disk_gb}GB.")
        plan["디스크_모자람"] = True
    if ram_gb is not None:
        if ram_gb < 8:
            plan["경고"].append(f"메모리(램)가 {ram_gb}GB 예요. 16GB 이상을 권장해요 — 느리거나 멈출 수 있어요.")
        elif ram_gb < 16 and plan["llama"]:
            plan["경고"].append(f"메모리(램)가 {ram_gb}GB 예요. 두뇌를 이 PC 에서 돌리면 램 약 4GB 를 더 써요(16GB 이상 권장).")
    return plan


def detect(prefix, local_brain=False, cli=True, gemma=None):
    """cli=True 면 구독 두뇌(claude·codex) 로그인을 살핌. False 면 안 봄(Gemma 만 다시 설치할 때)."""
    gl = sysinfo.gpus()
    ram = sysinfo.ram_gb()
    if os.environ.get("KIMBISEO_FAKE_RAM_GB"):
        ram = float(os.environ["KIMBISEO_FAKE_RAM_GB"])
    disk = sysinfo.disk_free_gb(prefix)
    if os.environ.get("KIMBISEO_FAKE_DISK_GB"):
        disk = float(os.environ["KIMBISEO_FAKE_DISK_GB"])
    drv = nvidia_driver() if gl else 0.0
    others = other_gpus() if not gl else []
    st = cli_detect.all_status(fresh=True) if cli else None
    return make_plan(gl, ram, disk, drv, others, local_brain, st, gemma)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default=os.path.expandvars(r"%LOCALAPPDATA%\KimBiseo"))
    ap.add_argument("--local-brain", action="store_true")
    ap.add_argument("--gemma", default=None, help="E4B(기본) | E2B")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = detect(a.prefix, a.local_brain, gemma=a.gemma)
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=1))
    else:
        print(f"구성: {p['구성']} · torch {p['torch']} · 두뇌 프로그램 {p['llama'] or '(안 받음)'} · 모델 {', '.join(p['모델'])}")
        print(f"설치 크기 약 {p['설치_크기_GB']}GB · 필요 디스크 {p['필요_디스크_GB']}GB")
        for x in p["안내"] + p["경고"]:
            print(" -", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
