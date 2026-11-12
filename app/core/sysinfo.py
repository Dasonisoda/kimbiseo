# 이 PC 사양 보기(처음 화면 0번) — 그래픽카드·메모리·디스크 → 맞는 구성 추천.
#   그래픽카드: nvidia-smi 가 있으면 이름·전체/남은 메모리(MiB). 없으면 '엔비디아 그래픽카드 없음'.
#   추천(대략 실측: 두뇌 Q4_K_M 8K 약 3.5GB · 귀 약 2.1GB · 김비서 목소리 약 2.0GB(상한 1.8 + 여유 0.6) · 화면 0.5GB):
#     목소리(0.1.4~): 엔비디아 그래픽 메모리 6GB 이상이면 모두 김비서 목소리(Qwen). 6GB 미만·엔비디아 없음만 윈도우 기본 음성.
#       (켤 때·쓰는 중에 그래픽 메모리가 모자라면 목소리 서버가 스스로 윈도우 음성으로 바꿈 — voice/tts_server.py)
#     두뇌: 이 PC 에 구독 두뇌(클로드 코드·Codex)가 로그인돼 있으면 그것을 먼저 권함(core/cli_detect) → 없으면 Gemma(이 PC).
#     엔비디아 없음 → 귀 = CPU(느림), 두뇌 = 구독 두뇌·'내 AI 주소' 권장
#   시험용: 환경변수 KIMBISEO_FAKE_GPU="이름:전체MiB" 면 그 그래픽카드가 있는 것처럼, "none" 이면 없는 것처럼 본다.
import ctypes
import os
import shutil
import subprocess
import sys

VOICE_GB = 2.0
SMALL_GPU_MIB = 9 * 1024          # 이 밑이면 Gemma 까지 켤 때 빠듯(경고만)
QWEN_MIN_MIB = 6 * 1024           # 김비서 목소리(Qwen)를 쓰는 최소 그래픽 메모리(전체) — 귀 2.1 + 목소리 2.0 + 화면 0.5 + 여유
# 9GB 미만 + 이 PC 두뇌(Gemma) → 받아쓰기 CPU 로 정하기. 14단계 실측(RTX 5060 8GB·Ryzen 9 8940HX)에서 CPU 받아쓰기가
# 한 문장 7.5~8.4초(whisper-large-v3-turbo)·2.6~4.2초(whisper-small)로 그래픽카드(0.2~0.3초)보다 크게 느려 기본은 끔.
# 켜는 것은 운영자 확인 뒤(installer/plan.py 가 이 값을 같이 씀). 사용자는 설정 '목소리 → 받아쓰기 장치'에서 고름.
EAR_CPU_WITH_GEMMA = False


def gpus():
    fake = os.environ.get("KIMBISEO_FAKE_GPU")
    if fake:
        if fake.strip().lower() == "none":
            return []
        name, _, mib = fake.rpartition(":")
        try:
            total = int(mib)
        except ValueError:
            return []
        return [{"이름": name or "시험용 그래픽카드", "전체_MiB": total, "남은_MiB": total, "시험값": True}]
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    res = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 3:
            try:
                res.append({"이름": p[0], "전체_MiB": int(float(p[1])), "남은_MiB": int(float(p[2]))})
            except ValueError:
                pass
    return res


def ram_gb():
    if sys.platform != "win32":
        try:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30, 1)
        except (ValueError, OSError, AttributeError):
            return None

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return round(m.ullTotalPhys / 2 ** 30, 1)


def disk_free_gb(path):
    p = os.path.abspath(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return round(shutil.disk_usage(p).free / 2 ** 30, 1)
    except OSError:
        return None


def voice_rule(g):
    """→ (엔진, 판별 근거 글). 판별 근거는 설치 기록(install.log)·처음 화면에 그대로 보임."""
    if g is None:
        return "windows", "엔비디아 그래픽카드 없음 → 윈도우 기본 음성(김비서 목소리는 CPU 로 첫 소리 10초 넘음)"
    gb = g["전체_MiB"] / 1024
    if g["전체_MiB"] >= QWEN_MIN_MIB:
        return "qwen", f"{g['이름']} 그래픽 메모리 {gb:.1f}GB ≥ 기준 {QWEN_MIN_MIB / 1024:.0f}GB → 김비서 목소리(Qwen)"
    return "windows", f"{g['이름']} 그래픽 메모리 {gb:.1f}GB < 기준 {QWEN_MIN_MIB / 1024:.0f}GB → 윈도우 기본 음성"


def recommend(gpu_list, cli=None, gemma_ready=None):
    """→ {"구성": 이름, "설정": {경로: 값}, "안내": [글], "목소리_경고": 글|"", "판별": [글]}
    cli: core/cli_detect.all_status() 결과(없으면 구독 두뇌 안 봄) · gemma_ready: 이 PC 에 Gemma 가 설치돼 있는지(None = 모름)."""
    g = max(gpu_list, key=lambda x: x["전체_MiB"]) if gpu_list else None
    eng, why = voice_rule(g)
    sub = ""
    if cli:
        from . import cli_detect
        sub = cli_detect.suggest(cli)
    judge = [why]
    if sub:
        judge.append(f"구독 두뇌 로그인됨 → 두뇌 = {'클로드 코드' if sub == 'claude_cli' else 'GPT(Codex)'}(Gemma 는 안 받음)")
    if g is None:
        brain = sub or ("local" if gemma_ready else "url")
        return {"구성": "그래픽카드 없음",
                "설정": {"목소리.엔진": eng, "귀.장치": "cpu", "목소리.장치": "cpu", "두뇌.방식": brain},
                "안내": ["엔비디아 그래픽카드가 보이지 않아요.", "목소리는 윈도우 기본 음성, 받아쓰기는 CPU 로 해요(느릴 수 있어요).",
                         "두뇌는 구독 클로드·GPT 또는 '내 AI 주소'를 추천해요. 내 PC 에서도 되지만 아주 느려요." if not sub
                         else "두뇌는 이 PC 에 로그인된 구독을 써요."],
                "목소리_경고": "그래픽카드가 없으면 김비서 목소리는 한 문장에 10초 넘게 걸릴 수 있어요.", "판별": judge}
    gb = g["전체_MiB"] / 1024
    brain = sub or "local"
    if eng == "windows":
        return {"구성": "그래픽 메모리 6GB 미만",
                "설정": {"목소리.엔진": "windows", "귀.장치": "auto", "목소리.장치": "auto", "두뇌.방식": sub or ("local" if gemma_ready else "url")},
                "안내": [f"{g['이름']} ({gb:.0f}GB) 이 보여요.", "받아쓰기는 그래픽카드로, 목소리는 가벼운 윈도우 기본 음성으로 해요."],
                "목소리_경고": "그래픽 메모리가 6GB 보다 작아 김비서 목소리를 켜면 모자랄 수 있어요.", "판별": judge}
    small = g["전체_MiB"] < SMALL_GPU_MIB
    ear_cpu = EAR_CPU_WITH_GEMMA and small and brain == "local"   # installer/plan.py 와 같은 규칙
    if ear_cpu:
        judge.append(f"그래픽 메모리 {gb:.1f}GB < {SMALL_GPU_MIB / 1024:.0f}GB + 이 PC 두뇌(Gemma) → 받아쓰기 CPU")
    return {"구성": "그래픽 메모리 8GB 이하" if small else "그래픽 메모리 넉넉함",
            "설정": {"목소리.엔진": "qwen", "귀.장치": "cpu" if ear_cpu else "auto", "목소리.장치": "auto", "두뇌.방식": brain},
            "안내": [f"{g['이름']} ({gb:.0f}GB) 이 보여요.",
                     ("김비서 목소리는 그래픽카드로, 받아쓰기는 CPU 로 해요(그래픽 메모리를 이 PC 의 Gemma 에 남겨요)."
                      " 그래도 모자라면 목소리가 저절로 윈도우 음성으로 바뀌어요.") if ear_cpu else "받아쓰기·김비서 목소리를 그래픽카드로 해요."],
            "목소리_경고": "", "판별": judge}


def report(model_dir, cli=None, gemma_ready=None):
    gl = gpus()
    return {"그래픽카드": gl, "메모리_GB": ram_gb(), "디스크_여유_GB": disk_free_gb(model_dir),
            "추천": recommend(gl, cli, gemma_ready), "구독": cli}
