# 옷·성별 → 목소리·말투 고르기 — 설정 화면(settings_api)과 본체 설정(config.load)·목소리 부품(tts)이 같이 쓴다.
#
# 규칙
#   1) 사용자 설정(settings.json)에 '목소리.목소리' 가 있으면 그 값이 고정값이다(자동 연결 무시).
#      저장소 기본값(app/config/default.json)의 '목소리.목소리' 는 고정으로 보지 않는다.
#      값이 "auto"(설정 화면의 '옷에 맞춤(자동)')이면 고르지 않은 것으로 본다.
#   2) 고정이 아니고 펫이 켜져 있으면, 펫이 지금 입은 옷으로 고른다(voice_for_outfit) —
#      옷 꾸러미 pack.json 의 voice(선택) → voices.json 옷목소리.옷[옷 id] → 옷목소리.성별[꾸러미 성별].
#      옷을 갈아입으면 다음 문장부터 그 옷의 목소리로 말한다(목소리 서버는 요청마다 "voice" 를 받음).
#   3) 펫이 꺼져 있거나 옷으로 못 고르면 펫.성별 로 고른다 — 여: kimbiseo, 남: kimbiseo_m.
#   4) 고른 목소리의 참고음성(참고목록.json + wav)이 없으면 기본목소리(kimbiseo)로 대체하고
#      "목소리 kimbiseo_m 참고음성 없음 → 기본 kimbiseo 사용" 같은 한 줄을 남긴다.
#
# 말투도 같은 규칙을 쓴다.
#   - 사용자 설정(settings.json)에 '비서.말투' 가 있으면 그 값이 고정값이다(자동 선택 무시) — 존댓말 · 편한 존댓말 · 반말.
#   - 없거나 "auto"(설정 화면의 '자동')면 펫.성별 로 고른다 — 여: 존댓말, 남: 편한 존댓말.
#
# 목소리 서버는 요청마다 "voice" 를 받으므로(tts_server.py 의 ensure_voice), 성별이 바뀌면
# 설정 저장 때 Session.apply_settings 가 VoiceLink.voice 만 바꿔 주면 서버를 다시 켜지 않아도 된다.
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOICES_FILE = os.path.join(REPO, "voice", "voices.json")
DEFAULT_VOICE = "kimbiseo"
AUTO = "auto"            # 설정 '목소리.목소리' 의 이 값 = 직접 고르지 않음(옷·성별에 맞춤)
GENDER_VOICES = {"여": "kimbiseo", "남": "kimbiseo_m"}
OUTFIT_GENDER_VOICES = {"여성": "kimbiseo", "남성": "kimbiseo_m"}   # voices.json 옷목소리.성별 을 못 읽을 때만
DEFAULT_TONE = "존댓말"
GENDER_TONES = {"여": "존댓말", "남": "편한 존댓말"}


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        j = json.load(f)
    if not isinstance(j, dict):
        raise ValueError(f"JSON 객체가 아님: {path}")
    return j


def load_registry(path=None):
    """voices.json → {"기본목소리": ..., "성별_목소리": {...}, "목록": {...}} (못 읽으면 기본값)."""
    try:
        j = _read_json(path or VOICES_FILE)
    except (OSError, ValueError):
        return {"기본목소리": DEFAULT_VOICE, "성별_목소리": dict(GENDER_VOICES), "목록": {}}
    if not isinstance(j.get("목록"), dict):
        j["목록"] = {}
    return j


def user_voice(user):
    """사용자 설정 dict 에 '목소리.목소리' 가 명시돼 있으면 그 값, 없으면(또는 "auto" 면) None."""
    if not isinstance(user, dict):
        return None
    v = (user.get("목소리") or {}).get("목소리")
    return v if isinstance(v, str) and v.strip() and v.strip() != AUTO else None


def user_tone(user):
    """사용자 설정 dict 에 '비서.말투' 가 명시돼 있으면 그 값, 없으면(또는 "auto" — 설정 화면의 '자동' — 면) None."""
    if not isinstance(user, dict):
        return None
    v = (user.get("비서") or {}).get("말투")
    return v if isinstance(v, str) and v.strip() and v.strip() != AUTO else None


def user_from_cfg(cfg):
    """cfg 가 들고 있는 사용자 설정 파일을 그대로 읽는다(고정 여부 판단용)."""
    p = (cfg or {}).get("_settings_path") or (cfg or {}).get("_settings_file")
    if p and os.path.isfile(p):
        try:
            return _read_json(p)
        except (OSError, ValueError):
            pass
    return {}


def voice_for_gender(gender, registry=None):
    reg = registry if isinstance(registry, dict) else load_registry()
    mapping = reg.get("성별_목소리") if isinstance(reg.get("성별_목소리"), dict) else GENDER_VOICES
    return str(mapping.get(str(gender or "여")) or reg.get("기본목소리") or DEFAULT_VOICE)


def _gender_keys(gender):
    """꾸러미 성별 표기('남성'·'남'·'male' …)를 대응표에서 찾을 열쇠 후보로."""
    g = str(gender or "").strip()
    if not g:
        return []
    alias = {"여": "여성", "남": "남성", "female": "여성", "male": "남성", "f": "여성", "m": "남성"}
    out = [g]
    if alias.get(g.lower()):
        out.append(alias[g.lower()])
    if g.endswith("성") and len(g) > 1:
        out.append(g[:-1])
    return out


def voice_for_outfit(outfit, registry=None, skip=()):
    """펫이 지금 입은 옷 → 목소리 이름(없으면 None).
    outfit = {"id": 옷 id, "gender": 꾸러미 성별, "voice": 꾸러미 pack.json 의 voice(선택)}.
    순서 = 꾸러미 voice → 옷목소리.옷[id] → 옷목소리.성별[gender]. 목록에 없거나 참고음성이 없는 이름,
    skip(목소리 서버가 방금 거절한 이름)에 든 이름은 건너뛴다."""
    if not isinstance(outfit, dict):
        return None
    reg = registry if isinstance(registry, dict) else load_registry()
    names = reg.get("목록") if isinstance(reg.get("목록"), dict) else {}
    table = reg.get("옷목소리") if isinstance(reg.get("옷목소리"), dict) else {}
    by_id = table.get("옷") if isinstance(table.get("옷"), dict) else {}
    by_gender = table.get("성별") if isinstance(table.get("성별"), dict) else OUTFIT_GENDER_VOICES
    cands = [outfit.get("voice"), by_id.get(str(outfit.get("id") or ""))]
    cands += [by_gender.get(k) for k in _gender_keys(outfit.get("gender"))]
    for name in cands:
        if not isinstance(name, str) or not name or name in skip or name not in names:
            continue
        if not asset_problem(name, reg):
            return name
    return None


def voice_now(cfg, outfit=None, registry=None, skip=()):
    """지금 이 문장을 말할 목소리 → (이름, 근거). 근거 = "고정"(직접 고름) | "옷"(입은 옷) | "성별"(펫.성별 설정).
    cfg['_voice_choice'] 는 config.load 가 apply() 로 넣어 둔 해석 결과."""
    choice = cfg.get("_voice_choice") if isinstance(cfg.get("_voice_choice"), dict) else {}
    base = str((cfg.get("목소리") or {}).get("목소리") or "") or None
    if choice.get("고정"):
        return base, "고정"
    name = voice_for_outfit(outfit, registry, skip) if outfit else None
    if name:
        return name, "옷"
    return base, "성별"


def tone_for_gender(gender):
    """성별 → 기본 말투(여: 존댓말, 남: 편한 존댓말). 모르는 성별은 존댓말."""
    return GENDER_TONES.get(str(gender or "여"), DEFAULT_TONE)


def resolve_tone(cfg, user=None):
    """지금 쓸 말투를 정한다(사용자 고정 > 펫.성별 자동).
    돌려줌: {"성별", "고정", "자동", "말투", "이유"}.
    """
    gender = str((cfg.get("펫") or {}).get("성별") or "여")
    if user is None:
        user = user_from_cfg(cfg)
    pinned = user_tone(user)
    tone = pinned or tone_for_gender(gender)
    reason = "" if pinned else f"펫 성별 {gender} → 말투 {tone} 자동 선택"
    return {"성별": gender, "고정": bool(pinned), "자동": not pinned, "말투": tone, "이유": reason}


def apply_tone(cfg, user=None):
    """config.load 가 부른다 — 정해진 말투를 cfg['비서']['말투'] 에 넣고 해석 결과를 남긴다."""
    result = resolve_tone(cfg, user=user)
    cfg.setdefault("비서", {})["말투"] = result["말투"]
    cfg["_tone_choice"] = dict(result)
    return result


def describe_tone(cfg, user=None):
    """화면에 보여 줄 말투 해석(로그를 남기지 않음)."""
    return resolve_tone(cfg, user=user)


def _folder(name, registry):
    entry = (registry.get("목록") or {}).get(name)
    if not isinstance(entry, dict):
        return "", f"목소리 {name} 정보 없음"
    folder = str(entry.get("폴더") or "").strip()
    if not folder:
        return "", f"목소리 {name} 폴더 정보 없음"
    folder = os.path.expandvars(folder)
    return (folder if os.path.isabs(folder) else os.path.normpath(os.path.join(REPO, folder))), ""


def asset_problem(name, registry=None):
    """목소리 참고음성 폴더가 쓸 수 있는지 → 문제 한 줄(없으면 "")."""
    reg = registry if isinstance(registry, dict) else load_registry()
    folder, problem = _folder(name, reg)
    if problem:
        return problem
    manifest = os.path.join(folder, "참고목록.json")
    if not os.path.isfile(manifest):
        return f"목소리 {name} 참고음성 없음"
    try:
        j = _read_json(manifest)
    except (OSError, ValueError):
        return f"목소리 {name} 참고목록.json 읽기 실패"
    base = j.get("기본") if isinstance(j.get("기본"), dict) else {}
    wav = str(base.get("wav") or "").strip()
    if not wav:
        return f"목소리 {name} 참고음성 없음"
    if not os.path.isfile(os.path.join(folder, wav)):
        return f"목소리 {name} 참고음성 파일 없음({wav})"
    return ""


def resolve(cfg, user=None, log=None, registry=None):
    """지금 쓸 목소리를 정한다.
    돌려줌: {"성별", "고정", "자동", "목소리"(고른 값), "실제"(자산이 없으면 대체된 값), "대체", "이유"}.
    """
    reg = registry if isinstance(registry, dict) else load_registry()
    default = str(reg.get("기본목소리") or DEFAULT_VOICE)
    gender = str((cfg.get("펫") or {}).get("성별") or "여")
    if user is None:
        user = user_from_cfg(cfg)
    pinned = user_voice(user)
    requested = pinned or voice_for_gender(gender, reg)
    problem = asset_problem(requested, reg)
    effective = default if problem else requested
    reason = f"{problem} → 기본 {default} 사용" if problem else ""
    if reason and log is not None:
        log(reason)
    return {"성별": gender, "고정": bool(pinned), "자동": not pinned, "목소리": requested,
            "실제": effective, "대체": bool(problem), "이유": reason}


def apply(cfg, user=None, log=None, registry=None):
    """config.load 가 부른다 — 고른 목소리를 cfg['목소리']['목소리'] 에 넣고 해석 결과를 남긴다.
    자산이 없어도 고른 값(kimbiseo_m)을 남겨 두고, 실제 대체는 목소리 서버(ensure_voice)가 한다.
    (그래야 나중에 참고음성이 들어오면 서버 재시작 없이 그 목소리로 바뀐다.)"""
    result = resolve(cfg, user=user, log=log, registry=registry)
    cfg.setdefault("목소리", {})["목소리"] = result["목소리"]
    cfg["_voice_choice"] = dict(result)
    return result


def describe(cfg, user=None, registry=None):
    """화면에 보여 줄 해석(로그는 남기지 않음)."""
    return resolve(cfg, user=user, registry=registry)