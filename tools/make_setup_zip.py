# 설치 파일(zip 하나) 만들기 — 개발자 도구(설치 파일 안에는 안 들어감)
#   python tools/make_setup_zip.py --out <폴더> [--guide 설치방법.txt]
#   허용 목록(tools/allowlist.json)에 적힌 파일 중 설치에 필요한 것만, sha256 이 목록과 맞을 때만 넣음.
#   tests·tools·android·docs 는 넣지 않음. 모델·파이썬·펫 옷은 설치할 때 받으므로 넣지 않음.
#   같은 파일이면 같은 zip(시각·순서 고정) → sha256 이 매번 같음.
import argparse
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "installer"))
from setup_core import COPY_ITEMS, VERSION  # noqa: E402

TOP_FILES = ["설치.bat"]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--guide", default="", help="zip 맨 위에 같이 넣을 설치 안내 글(.txt)")
    a = ap.parse_args()
    al = json.load(open(os.path.join(ROOT, "tools", "allowlist.json"), encoding="utf-8"))
    pick = []
    for e in al["files"]:
        p = e["path"]
        if e.get("self"):
            continue
        if p in TOP_FILES or p.split("/")[0] in COPY_ITEMS:
            full = os.path.join(ROOT, *p.split("/"))
            got = sha256(full)
            if got != e["sha256"]:
                print(f"멈춤: sha256 이 허용 목록과 다름 — {p}")
                return 1
            pick.append((p, full))
    pick.sort()
    top = f"KimBiseo-setup-{VERSION}"
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{top}.zip")
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        items = list(pick)
        if a.guide:
            items.insert(0, (os.path.basename(a.guide), os.path.abspath(a.guide)))
        for rel, full in items:
            zi = zipfile.ZipInfo(f"{top}/{rel}", FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(zi, f.read())
    os.replace(tmp, out)
    print(f"만듦: {out}  파일 {len(items)}개  {os.path.getsize(out)} 바이트  sha256 {sha256(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
