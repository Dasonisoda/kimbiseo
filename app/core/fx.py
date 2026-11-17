# 통역 환율 — 상대 말(외국어 → 한국어)에 나온 외국 돈 금액을 원화로 바꿔 번역 끝에 "(약 14,000원)"을 붙임. 내 말(한국어 → 외국어)에는 안 붙임.
#   환율: 키 없는 무료 공개 원천 — ① frankfurter(유럽중앙은행 기준환율) ② 거기 없는 통화(베트남 동·러시아 루블 등)는 open.er-api.com
#     ("Rates By Exchange Rate API" — 무료 이용 조건에 따라 설정 화면에 출처 표시). 하루 한 번 받아 자료 폴더 fx_rates.json 에 둠.
#     인터넷이 안 되면 마지막 값(기준일 표시). 요청에는 사용자 정보를 넣지 않음(주소만, 이름 없는 User-Agent).
#   통화 낱말·기호: 바트·บาท·฿ / 엔·円 / 동·đồng·₫ / 루피아·Rp / 리라·₺·TL / 유로·€ / 달러·$ / 위안·元 / 파운드·£ / 루블·₽ …
#   통화가 없는 숫자("350이에요")는 돈 이야기(얼마·가격·요금·합계… 또는 원문 ราคา·値段·giá…)일 때만 통역 상대 나라 통화로 '추정'.
#   설정 통역.환율_켜기(기본 켬).
import json
import os
import re
import threading
import time
import urllib.request

FILE = os.path.join(os.path.expandvars("%APPDATA%"), "KimBiseo", "fx_rates.json")   # 본체가 켜질 때 set_dir(자료 폴더)로 바꿈
UA = "KimBiseo/1"
SOURCES = ("https://api.frankfurter.dev/v1/latest?base=KRW", "https://open.er-api.com/v6/latest/KRW")

# 통화 코드 → (한국어 이름, 알아볼 낱말·기호). 낱말은 숫자 바로 뒤(또는 기호는 바로 앞)에 붙은 것만 봄('동네'·'동안' 같은 말은 숫자 뒤가 아니라 안 걸림)
CUR = {
    "THB": ("바트", ["바트", "บาท", "baht", "thb", "฿"]),
    "JPY": ("엔", ["엔", "円", "yen", "jpy", "￥"]),
    "CNY": ("위안", ["위안", "元", "块", "塊", "人民币", "yuan", "rmb", "cny", "콰이"]),
    "VND": ("동", ["동", "đồng", "dong", "vnd", "₫", "đ"]),
    "IDR": ("루피아", ["루피아", "rupiah", "idr", "rp"]),
    "TRY": ("리라", ["리라", "lira", "try", "tl", "₺"]),
    "EUR": ("유로", ["유로", "euro", "euros", "eur", "ευρώ", "евро", "€"]),
    "USD": ("달러", ["달러", "dollar", "dollars", "usd", "us$", "$"]),
    "GBP": ("파운드", ["파운드", "pound", "pounds", "gbp", "£"]),
    "RUB": ("루블", ["루블", "рубль", "рублей", "рубля", "rub", "₽"]),
}
# 통역 상대 언어 → 그 나라 통화(통화가 없는 숫자를 추정할 때)
LANG_CUR = {"th": "THB", "ja": "JPY", "zh": "CNY", "vi": "VND", "id": "IDR", "tr": "TRY", "ru": "RUB",
            "el": "EUR", "de": "EUR", "fr": "EUR", "es": "EUR", "it": "EUR", "en": "USD"}
_THOUSAND_DOT = {"VND", "IDR", "JPY", "RUB", "TRY", "EUR"}   # 1.500 = 1500 으로 읽는 통화(점이 천 단위로 흔함)

_DIG = str.maketrans("๐๑๒๓๔๕๖๗๘๙٠١٢٣٤٥٦٧٨٩０１２３４５６７８９", "0123456789" * 3)
_NUM = r"\d[\d,.\s]*\d|\d"
_KO = r"(?:\s*\d+(?:[.,]\d+)?\s*[억만천백])+(?:\s*\d+)?"  # 85만 · 1만 2천 · 3천 5백
_WORDS = sorted({w for _, ws in CUR.values() for w in ws}, key=len, reverse=True)
_WRX = "|".join(re.escape(w) for w in _WORDS)
_AFTER = re.compile(rf"(?P<n>{_KO}|{_NUM})\s*(?P<w>{_WRX})(?![a-z])", re.I)   # 350바트 · 3,000엔 · 85만 동 · 12,50 €
_BEFORE = re.compile(rf"(?P<w>[฿€$£₺₽₫￥]|rp\.?|us\$)\s*(?P<n>{_NUM})", re.I)        # ฿350 · €12,50 · Rp 50.000 · $20
_BARE = re.compile(rf"(?P<n>{_KO}|{_NUM})(?!\s*[%시분초층개명번일박살인호차장권병잔그킬미센키리]|\s*(?:km|kg|m\b|cm|분|시간))")
_MONEY_CUE = re.compile(r"얼마|가격|값|요금|비용|합계|총|전부|모두 해서|내(?:세요|시면|야)|지불|계산|거스름|깎|할인|팁|입장료|택시비|방값|숙박비")
# 상대 말(원문)의 돈 낱말 — 번역이 '300입니다'처럼 돈 말을 빼도 추정할 수 있게(태·일·중·베·인니·터·그·러·독·프·스·이·영)
_SRC_CUE = re.compile(r"ราคา|เท่าไหร่|ทั้งหมด|รวม|値段|価格|合計|お会計|いくら|价格|多少钱|一共|总共|giá|tổng|bao nhiêu|harga|berapa|total|fiyat|toplam|"
                      r"kaç para|τιμή|κοστίζει|σύνολο|πόσο|цена|стоит|итого|сколько|preis|kostet|insgesamt|prix|coûte|precio|cuesta|prezzo|costa|"
                      r"wie ?viel|combien|cuánto|cuanto|quanto|price|cost|how much", re.I)
_UNIT = {"억": 10 ** 8, "만": 10 ** 4, "천": 1000, "백": 100}

_LOCK = threading.Lock()
_STATE = {"tried": 0.0, "busy": False}


# ---------------------------------------------------------------- 환율 받기·읽기(하루 한 번)
def set_dir(folder):
    global FILE
    FILE = os.path.join(folder, "fx_rates.json")


def _get(url, timeout=8.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch():
    """두 원천에서 받아 합침 → {'KRW당': {통화: 1원당 그 통화}, '기준일', '받은때', '원천'}. 둘 다 실패하면 예외."""
    per, used, day, errs = {}, [], "", []
    for url in SOURCES:
        try:
            d = _get(url)
        except Exception as ex:  # noqa: BLE001
            errs.append(f"{url.split('/')[2]} {type(ex).__name__}")
            continue
        rates = d.get("rates") or {}
        got = {c: float(rates[c]) for c in CUR if isinstance(rates.get(c), (int, float)) and rates[c] > 0 and c not in per}
        if got:
            per.update(got)
            used.append(url.split("/")[2])
            day = day or str(d.get("date") or "")[:10] or time.strftime("%Y-%m-%d", time.gmtime(int(d.get("time_last_update_unix") or time.time())))
        if all(c in per for c in CUR):
            break
    if not per:
        raise RuntimeError("환율을 못 받음: " + ", ".join(errs))
    return {"KRW당": per, "기준일": day, "받은때": time.strftime("%Y-%m-%d %H:%M"), "원천": used}


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d.get("KRW당"), dict) else None
    except (OSError, ValueError):
        return None


def _save(d):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".쓰는중"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def refresh(force=False, log=None):
    """오늘 받은 것이 없으면 받음(실패하면 1시간 뒤에 다시 시도). 성공하면 저장한 dict."""
    d = load()
    if not force and d and str(d.get("받은때", ""))[:10] == time.strftime("%Y-%m-%d"):
        return d
    if not force and time.time() - _STATE["tried"] < 3600:
        return d
    _STATE["tried"] = time.time()
    try:
        new = fetch()
    except Exception as ex:  # noqa: BLE001
        if log:
            log(f"환율 받기 실패(마지막 값 씀): {ex}")
        return d
    _save(new)
    if log:
        log(f"환율 받음: 기준일 {new['기준일']} · {len(new['KRW당'])}개 통화 · {'+'.join(new['원천'])}")
    return new


def refresh_bg(log=None):
    """번역을 막지 않게 뒤에서 받음(하루 한 번)."""
    with _LOCK:
        if _STATE["busy"]:
            return
        d = load()
        if d and str(d.get("받은때", ""))[:10] == time.strftime("%Y-%m-%d"):
            return
        if time.time() - _STATE["tried"] < 3600:
            return
        _STATE["busy"] = True

    def run():
        try:
            refresh(log=log)
        finally:
            _STATE["busy"] = False
    threading.Thread(target=run, name="환율", daemon=True).start()


# ---------------------------------------------------------------- 금액 찾기
def _value(s, cur):
    s = s.translate(_DIG).strip()
    if re.search(r"[억만천백]", s):
        total = sec = 0.0
        for num, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*([억만천백]?)", s):
            n = float(num.replace(",", "."))
            if unit in ("억", "만"):
                total += (sec + n) * _UNIT[unit]
                sec = 0.0
            elif unit:
                sec += n * _UNIT[unit]
            else:
                sec += n
        return total + sec
    s = re.sub(r"\s+", "", s)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s) and (cur in _THOUSAND_DOT or s.count(".") > 1):
        return float(s.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        return float(s.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", s):        # 1.234,50
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d+,\d{1,2}", s):                           # 12,50
        return float(s.replace(",", "."))
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _code(word, lang=None):
    w = word.lower()
    if w in ("￥",) and lang == "zh":
        return "CNY"
    for c, (_, ws) in CUR.items():
        if w in [x.lower() for x in ws]:
            return c
    return None


def find(text, lang=None):
    """글 속 외국 돈 → [(금액, 통화, 추정?)]. 통화 낱말·기호가 붙은 것만(추정은 guess 에서)."""
    out, seen = [], set()
    t = str(text or "")
    for rx in (_BEFORE, _AFTER):
        for m in rx.finditer(t):
            cur = _code(m.group("w"), lang)
            if not cur:
                continue
            v = _value(m.group("n"), cur)
            if v and v > 0 and (v, cur) not in seen:
                seen.add((v, cur))
                out.append((v, cur, False))
    return out


def guess(ko_text, lang, src_text=""):
    """통화 없이 숫자만 + 돈 이야기 → 상대 나라 통화로 추정. 시간·층·사람 수 같은 숫자는 뺌."""
    cur = LANG_CUR.get(lang or "")
    if not cur or not (_MONEY_CUE.search(ko_text or "") or _SRC_CUE.search(src_text or "")):
        return []
    out = []
    for m in _BARE.finditer(ko_text):
        v = _value(m.group("n"), cur)
        if v and v >= 1:
            out.append((v, cur, True))
    return out[:2]


# ---------------------------------------------------------------- 원화로
def won(v):
    """보기 좋게 반올림: 1천 원 미만 10원 · 10만 원 미만 100원 · 100만 원 미만 1천 원 · 그 위 1만 원 단위."""
    step = 10 if v < 1000 else 100 if v < 100_000 else 1000 if v < 1_000_000 else 10_000
    return int(round(v / step) * step)


def note(src_text, ko_text, lang, rates=None):
    """→ (번역 끝에 붙일 말, 화면용 정보) 또는 ("", None). ko_text = 한국어 번역문."""
    d = rates or load()
    if not d:
        return "", None
    per = d.get("KRW당") or {}
    items = find(ko_text, lang) or find(src_text, lang) or guess(ko_text, lang, src_text)
    parts, shown = [], []
    for v, cur, guessed in items[:3]:
        r = per.get(cur)
        if not r:
            continue
        w = won(v / r)
        if w <= 0:
            continue
        name = CUR[cur][0]
        parts.append(f"{name}라면 약 {w:,}원" if guessed else f"약 {w:,}원")
        shown.append({"금액": v, "통화": cur, "원": w, "추정": guessed})
    if not parts:
        return "", None
    old = str(d.get("받은때", ""))[:10] != time.strftime("%Y-%m-%d")
    day = str(d.get("기준일") or "")[5:].replace("-", "/")
    info = {"항목": shown, "기준일": d.get("기준일"), "받은때": d.get("받은때"), "오래됨": old,
            "글": "≈ " + " · ".join((f"{x['원']:,}원" + (f" ({CUR[x['통화']][0]}로 추정)" if x["추정"] else "")) for x in shown)
                  + f"  (환율 {day}{' · 오래된 값' if old else ''})"}
    return " (" + ", ".join(parts) + ")", info
