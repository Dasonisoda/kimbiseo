#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""옷 목록(packs.json) 만들기 — 김비서 공개판

꾸러미 파일들을 읽어 펫의 '옷 받기'가 보는 목록 파일을 만듭니다. 미리보기 그림은 꾸러미에서 꺼내 <꾸러미 이름>.preview.png 로 옆에 둡니다.
  python tools/make_catalog.py --out <폴더>/packs.json [--base-url https://.../] [--default <꾸러미 파일 이름>]
         [--soon '{"id":"kimbiseo_m","name":"김비서(남)","gender":"남성","body":""}'] [--note-file 파일=설명]... <꾸러미.hipcpet>...
  - url·preview 는 --base-url 이 없으면 목록 파일 기준 상대 주소(꾸러미를 목록 파일과 같은 곳에 올릴 때).
  - signed = 꾸러미 안에 signature.json 이 있는지(진짜 맞는지는 펫이 공개키로 확인). songs = 춤 노래가 들었는지.
  - soon = 아직 준비 중인 옷(받기 단추 없이 '준비 중'으로만 보임). 여러 번 줄 수 있음.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="옷 목록 packs.json 만들기")
    ap.add_argument("packs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--default", default="")
    ap.add_argument("--soon", action="append", default=[])
    ap.add_argument("--note-file", action="append", default=[], help="꾸러미파일이름=한 줄 설명")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    notes = dict(x.split("=", 1) for x in a.note_file if "=" in x)
    base = a.base_url
    if base and not base.endswith("/"):
        base += "/"
    items = []
    for p in map(Path, a.packs):
        z = zipfile.ZipFile(p)
        pj = json.loads(z.read("pack.json").decode("utf-8"))
        names = set(z.namelist())
        prev_name = p.stem + ".preview.png"
        (out.parent / prev_name).write_bytes(z.read(pj["preview"]))
        data = p.read_bytes()
        items.append({
            "id": pj["id"], "name": pj["name"], "version": pj.get("version", ""), "body": pj.get("body", ""), "gender": pj.get("gender", ""),
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "signed": "signature.json" in names,
            "url": base + p.name, "preview": base + prev_name, "default": p.name == a.default,
            "songs": bool(pj.get("music")), **({"note": notes[p.name]} if p.name in notes else {}),
        })
    for s in a.soon:
        d = json.loads(s)
        items.append({"id": d["id"], "name": d["name"], "version": "", "body": d.get("body", ""), "gender": d.get("gender", ""),
                      "size": 0, "sha256": "", "signed": True, "url": "", "preview": "", "default": False, "songs": False,
                      "soon": True, **({"note": d["note"]} if d.get("note") else {})})
    cat = {"format": "kimbiseo-packs/1", "packs": items}
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out}: 옷 {len(items)}개 (" + ", ".join(i['id'] + ('(준비 중)' if i.get('soon') else ' ' + i['version']) for i in items) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
