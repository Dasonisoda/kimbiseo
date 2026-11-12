# 두뇌가 보낸 도구 인자를 안전하게 읽기.
#   bool("False") 는 True 라서, 두뇌가 불리언을 문자열 'False'/'True' 로 보내면 '아니요'가 '예'로 읽힐 수 있다.
#   → 참(v): 진짜 참만 True. 'false'·'0'·'no'·'아니'·빈 값·모르는 값은 전부 False(안전한 쪽).
_TRUE = {"true", "1", "yes", "y", "예", "네", "응", "참", "on"}


def 참(v) -> bool:
    if v is True:
        return True
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v == 1
    if isinstance(v, str):
        return v.strip().lower() in _TRUE
    return False


def 불리언_정리(args, keys) -> list:
    """args(dict) 안의 keys 값 중 진짜 bool 이 아닌 것(None 제외)을 참()으로 바꾼다(제자리). 바꾼 (키, 원래값) 목록을 돌려줌."""
    out = []
    if not isinstance(args, dict) or not keys:
        return out
    for k in list(args):
        if k in keys:
            v = args[k]
            if v is not None and not isinstance(v, bool):
                args[k] = 참(v)
                out.append((k, v))
    return out


def 불리언_키(properties) -> set:
    """도구 정의(properties)에서 type 이 boolean 인 인자 이름."""
    out = set()
    for k, spec in (properties or {}).items():
        if isinstance(spec, dict) and spec.get("type") == "boolean":
            out.add(k)
    return out
