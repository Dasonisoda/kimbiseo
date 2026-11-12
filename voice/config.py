# 김비서 음성 쪽 설정 읽기 — 귀 서버(ear_server.py)·목소리 서버(tts_server.py)가 같이 쓴다.
#
# 순서(뒤가 앞을 덮음, 깊은 병합)
#   1) 이 파일의 DEFAULTS (음성 쪽 항목 전부 — 코드가 기본값 없이 꺼내 써도 KeyError 가 나지 않게)
#   2) 저장소의 app/config/default.json 이 있으면 그 안의 같은 항목
#   3) 사용자 설정: --settings <파일> > 환경변수 KIMBISEO_SETTINGS > %APPDATA%\KimBiseo\settings.json
# 경로 값의 %APPDATA%·%LOCALAPPDATA% 같은 환경변수는 읽을 때 풀어 준다.
# 모델 값이 절대 경로가 아니면 '경로.모델' 폴더 아래의 그 이름으로 본다(installer/get_models.py 가 받는 곳).
import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DEFAULTS = {
    "포트": {"목소리": 8871, "귀": 8872},
    "경로": {
        "자료": "%APPDATA%/KimBiseo",          # 읽을 때 abspath 가 윈도우 경로(\)로 바꿈
        "모델": "%LOCALAPPDATA%/KimBiseo/models",
        "캐시": "%LOCALAPPDATA%/KimBiseo/cache",
        "로그": "%APPDATA%/KimBiseo/logs",
    },
    "모델": {
        "오프라인": True,          # 모델은 설치 때 받아 두고, 켤 때는 인터넷에 묻지 않음(HF_HUB_OFFLINE=1)
        "hf_home": "",            # 비우면 '경로.캐시'\hf_home (라이브러리가 쓰는 작은 캐시 자리)
    },
    "귀": {
        "엔진": "whisper",
        "모델": "whisper-large-v3-turbo",
        "장치": "auto",            # auto | cuda | cpu
        "언어": "korean",
        "핫워드": [],              # 잘 못 알아듣는 낱말(예: 제품 이름)을 whisper 앞글로 줌
        "그래픽메모리_필요_GB": 2.2,   # auto 일 때 그래픽카드를 고르는 남은 메모리 기준
        "최대_초": 60,             # 한 번에 받는 소리 길이 상한
        "CPU_스레드": 8,           # 그래픽카드 없이 돌 때 쓰는 CPU 스레드 수
        "로그_글_남기기": False,     # True 면 받아쓴 글 앞부분을 로그에 남김(기본은 글자 수만)
    },
    "목소리": {
        "엔진": "qwen",            # qwen(김비서 목소리) | windows(윈도우 기본 음성)
        "예비": "windows",         # qwen 을 못 띄우면 이것으로(빈 값이면 예비 없음)
        "모델": "Qwen3-TTS-12Hz-0.6B-Base",
        "장치": "auto",            # auto | cuda | cpu
        "그래픽메모리_상한_GB": 1.8,
        "CPU_스레드": 8,
        "목소리": "kimbiseo",       # voices.json 의 이름
        "참고음성_폴더": "",         # 비우면 voices.json 의 폴더. 폴더 안에 참고목록.json + wav
        "윈도우_목소리": "",         # 윈도우 음성 이름 일부(비우면 한국어 음성 중 첫째)
        "발음사전": "",             # 사용자 발음 사전(tsv) — 저장소 기본 사전보다 먼저 적용
        "미리만들기": True,          # phrases.txt 의 말을 켤 때 미리 만들어 캐시에 둠
        "닮음검사": {"켜기": False, "모델": "", "도우미_파이썬": ""},
        "로그_글_남기기": False,
    },
}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        j = json.load(f)
    if not isinstance(j, dict):
        raise ValueError(f"설정 파일이 객체(JSON {{}})가 아님: {path}")
    return j


def user_settings_path(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("KIMBISEO_SETTINGS"):
        return os.environ["KIMBISEO_SETTINGS"]
    return os.path.abspath(os.path.join(os.path.expandvars(DEFAULTS["경로"]["자료"]), "settings.json"))


def load(settings_path=None, warn=print):
    cfg = copy.deepcopy(DEFAULTS)
    repo_default = os.path.join(REPO, "app", "config", "default.json")
    if os.path.isfile(repo_default):
        j = _read_json(repo_default)
        cfg = deep_merge(cfg, {k: j[k] for k in DEFAULTS if k in j})
    p = user_settings_path(settings_path)
    if os.path.isfile(p):
        try:
            cfg = deep_merge(cfg, _read_json(p))
        except (OSError, ValueError) as ex:
            warn(f"[설정] 사용자 설정을 못 읽음 → 기본값: {p} ({ex})")
    elif settings_path:
        warn(f"[설정] 사용자 설정 파일 없음 → 기본값: {p}")
    cfg["_settings_file"] = p if os.path.isfile(p) else ""
    return cfg


def path(cfg, key):
    """'경로' 항목 하나를 풀어 준다(폴더는 만들지 않음)."""
    return os.path.abspath(os.path.expandvars(str(cfg["경로"][key])))


def model_path(cfg, value):
    """모델 값(절대 경로 / 받은 모델 이름) → 폴더 경로."""
    v = os.path.expandvars(str(value or ""))
    if not v:
        return ""
    if os.path.isabs(v):
        return v
    return os.path.join(path(cfg, "모델"), v)


def apply_hf_env(cfg):
    """transformers·huggingface_hub 를 import 하기 전에 부른다."""
    if cfg["모델"].get("오프라인", True):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    hf_home = os.path.expandvars(str(cfg["모델"].get("hf_home") or "")) or os.path.join(path(cfg, "캐시"), "hf_home")
    os.environ.setdefault("HF_HOME", hf_home)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def gpu_free_mib():
    """(남은 MiB, 전체 MiB). nvidia-smi 가 없으면 (0, 0)."""
    import subprocess
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip().splitlines()[0]
        used, tot = [float(v) for v in out.split(",")]
        return tot - used, tot
    except Exception:  # noqa: BLE001
        return 0.0, 0.0


def pick_device(want, need_gb, log=print):
    """'auto' → 그래픽카드 남은 메모리가 need_gb 이상이고 CUDA 가 되면 cuda, 아니면 cpu."""
    want = str(want or "auto").lower()
    if want != "auto":
        return want
    import torch
    free, _ = gpu_free_mib()
    dev = "cuda" if (torch.cuda.is_available() and free >= need_gb * 1024) else "cpu"
    log(f"장치 자동 선택: 그래픽 메모리 남은 {free:.0f}MiB / 필요 {need_gb * 1024:.0f}MiB → {dev}")
    return dev


class Logger:
    """콘솔 + 파일(경로.로그 아래). 파일을 못 쓰면 콘솔만."""

    def __init__(self, name, log_dir=None, tag=""):
        self.tag = tag
        self.file = None
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
                self.file = os.path.join(log_dir, name)
            except OSError:
                self.file = None

    def __call__(self, *parts):
        import time
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + (self.tag + " " if self.tag else "") + " ".join(str(p) for p in parts)
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass
        if self.file:
            try:
                with open(self.file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
