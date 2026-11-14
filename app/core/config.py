# 본체 설정 읽기 — 기본 설정(app/config/default.json) 위에 사용자 설정을 깊게 덮어쓴다.
#   사용자 설정: --settings <파일> > 환경변수 KIMBISEO_SETTINGS > %APPDATA%\KimBiseo\settings.json
#   비밀값(두뇌 열쇠 등)은 여기에 두지 않는다 — core/secrets.py.
import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)
DEFAULT_FILE = os.path.join(APP, "config", "default.json")


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        j = json.load(f)
    if not isinstance(j, dict):
        raise ValueError(f"설정 파일이 객체가 아님: {path}")
    return j


def expand(p):
    return os.path.abspath(os.path.expandvars(str(p or "")))


def user_settings_path(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("KIMBISEO_SETTINGS"):
        return os.environ["KIMBISEO_SETTINGS"]
    base = _read(DEFAULT_FILE)["경로"]["자료"]
    return os.path.join(expand(base), "settings.json")


def _check_types(base, over, where, warn):
    """사용자 값의 형이 기본값과 다르면 경고하고 기본값을 씀(숫자끼리는 허용)."""
    out = {}
    for k, v in (over or {}).items():
        if k.startswith("_"):
            continue
        b = base.get(k) if isinstance(base, dict) else None
        if isinstance(b, dict) and isinstance(v, dict):
            out[k] = _check_types(b, v, f"{where}.{k}", warn)
            continue
        if b is not None and not isinstance(v, type(b)) and not (
                isinstance(b, (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool)):
            warn(f"[설정] {where}.{k} 형이 맞지 않아 기본값을 씀({type(v).__name__} → {type(b).__name__})")
            continue
        out[k] = v
    return out


# 끼어들기 감도(설정 대화.끼어들기_감도) — 값이 클수록 비서 말을 끊기 어렵게(시끄러운 곳). 0.3 = 기본값 그대로.
#   감도가 아래 다섯 값을 정한다. 다섯 값을 직접 바꾸려면 감도를 0(직접)으로 둔다.
BARGE_LEVELS = {
    0.3: {"엿듣기_초": 0.4, "첫소리_무시_초": 0.3, "큰소리_기준_dBFS": -18, "메아리_상관_기준": 0.9, "자기목소리_유사도": 0.6},
    0.4: {"엿듣기_초": 0.6, "첫소리_무시_초": 0.5, "큰소리_기준_dBFS": -15, "메아리_상관_기준": 0.8, "자기목소리_유사도": 0.5},
    0.5: {"엿듣기_초": 0.8, "첫소리_무시_초": 0.7, "큰소리_기준_dBFS": -12, "메아리_상관_기준": 0.7, "자기목소리_유사도": 0.45},
}


def barge_level(v):
    """0.3 · '0.4' · 0.5 → 그 값, 아니면 None."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return next((lv for lv in BARGE_LEVELS if abs(lv - x) < 0.026), None)


def apply_barge(cfg):
    dc = cfg.setdefault("대화", {})
    lv = barge_level(dc.get("끼어들기_감도", 0.3))
    if lv is not None:
        dc.update(BARGE_LEVELS[lv])
    return cfg


def load(settings_path=None, warn=print):
    cfg = _read(DEFAULT_FILE)
    p = user_settings_path(settings_path)
    user = None
    if os.path.isfile(p):
        try:
            user = _read(p)
            cfg = deep_merge(cfg, _check_types(cfg, user, "설정", warn))
        except (OSError, ValueError) as ex:
            warn(f"[설정] 사용자 설정을 못 읽음 → 기본값: {ex}")
    elif settings_path:
        warn("[설정] 사용자 설정 파일이 없음 → 기본값")
    apply_barge(cfg)
    # 목소리: 사용자 설정에 '목소리.목소리' 가 있으면 고정, 없으면 펫.성별(여/남)로 고른다.
    #   자산이 없어 대체된 경우 warn 으로 한 줄 남긴다(화면은 settings_api 경고로도 보여 줌).
    from .voice_choice import apply as apply_voice
    apply_voice(cfg, user or {}, log=warn)
    # 말투: 사용자 설정에 '비서.말투' 가 있으면 고정, 없으면 펫.성별(여: 존댓말, 남: 편한 존댓말)로 고른다.
    from .voice_choice import apply_tone
    apply_tone(cfg, user or {})
    cfg["_settings_file"] = p if os.path.isfile(p) else ""
    return cfg


def reload_into(cfg, settings_path=None, warn=print):
    """설정을 다시 읽어 같은 dict 를 채운다 — 대화·부품이 들고 있는 cfg 가 그대로 새 값을 보게."""
    new = load(settings_path, warn=warn)
    cfg.clear()
    cfg.update(new)
    return cfg


def read_user(settings_path=None):
    """사용자 설정 파일 그대로(없거나 못 읽으면 {})."""
    p = user_settings_path(settings_path)
    try:
        return _read(p) if os.path.isfile(p) else {}
    except (OSError, ValueError):
        return {}


def save_user(cfg, changes):
    """사용자 설정 파일에 바뀐 값만 덮어 저장(예: 말 빠르기). 실패해도 대화는 계속."""
    p = cfg.get("_settings_path") or cfg.get("_settings_file") or user_settings_path()
    try:
        cur = _read(p) if os.path.isfile(p) else {}
    except (OSError, ValueError):
        return False
    cur = deep_merge(cur, changes)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    cfg["_settings_file"] = p
    return True


def path(cfg, key):
    return expand(cfg["경로"][key])


def names(cfg):
    """(비서 이름, [별칭]) — 깨우는 이름 = 이름 + 별칭."""
    b = cfg.get("비서") or {}
    name = str(b.get("이름") or "김비서").strip() or "김비서"
    raw = list(b.get("별칭") or [])
    try:
        d = _read(DEFAULT_FILE).get("비서") or {}
        if name != d.get("이름") and raw == list(d.get("별칭") or []):
            raw = []   # 이름만 바꾸고 별칭은 안 건드렸으면 기본 이름의 별칭('김 비서' 등)은 버림 — 옛 이름으로 깨지 않게
    except (OSError, ValueError):
        pass
    al = [str(x).strip() for x in raw if str(x).strip() and str(x).strip() != name]
    return name, al


def honorific(cfg):
    return str((cfg.get("사용자") or {}).get("호칭") or "").strip()


def fill(cfg, text):
    """'{이름}'·'{호칭}'·'{기본장소}' 바꾸기. 호칭이 비면 '{호칭}' 자리를 '사용자'로."""
    name, _ = names(cfg)
    u = cfg.get("사용자") or {}
    return (str(text or "").replace("{이름}", name).replace("{호칭}", honorific(cfg) or "사용자")
            .replace("{기본장소}", str(u.get("기본장소") or "서울")))
