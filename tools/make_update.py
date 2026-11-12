# 업데이트 꾸러미·목록 만들기 — 개발자 도구(설치 파일·업데이트 꾸러미 안에는 안 들어감). cryptography 가 있는 파이썬으로 돌린다.
#   python tools/make_update.py keygen --out <비밀키.pem>                 새 서명 열쇠(이미 있으면 멈춤). 공개키만 화면에 보임
#   python tools/make_update.py pubkey --key <비밀키.pem>                 공개키(app/core/update.py PUBKEYS 에 넣는 값)
#   python tools/make_update.py build  --key <비밀키.pem> --out <폴더> --base-url <꾸러미를 올릴 주소/>
#                                      [--notes "바뀐 점" ...] [--min-from 0.1.0] [--release-page 주소] [--setup-zip 설치파일.zip]
#                                      [--src 폴더 --no-allowlist]   (시험용: 허용 목록 없이 다른 폴더로)
#   python tools/make_update.py verify --manifest latest.json [--zip 꾸러미.zip]
# 만드는 것: KimBiseo-update-<판>.zip (src/… + kimbiseo-update.json 파일 목록) · latest.json (서명된 목록)
#   판 번호 = app/version.py. 같은 파일이면 같은 zip(시각·순서 고정). 비밀키 값은 어디에도 찍지 않는다.
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "installer"))
import updater as U  # noqa: E402
from setup_core import COPY_ITEMS  # noqa: E402

KEY_ID = "kimbiseo-update-1"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_key(path):
    from cryptography.hazmat.primitives import serialization
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def pub_b64(key):
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def cmd_keygen(a):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if os.path.exists(a.out):
        print("멈춤: 그 자리에 이미 열쇠가 있어요(덮어쓰지 않음).")
        return 1
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    print(json.dumps({"key_id": KEY_ID, "public": pub_b64(k), "sha256_of_pem_file": hashlib.sha256(pem).hexdigest()[:12] + "…"}))
    return 0


def cmd_pubkey(a):
    print(pub_b64(load_key(a.key)))
    return 0


def pick_files(src, use_allowlist):
    out = []
    if use_allowlist:
        al = json.load(open(os.path.join(ROOT, "tools", "allowlist.json"), encoding="utf-8"))
        for e in al["files"]:
            p = e["path"]
            if e.get("self") or p.split("/")[0] not in COPY_ITEMS:
                continue
            full = os.path.join(src, *p.split("/"))
            if U.sha256_file(full) != e["sha256"]:
                raise SystemExit(f"멈춤: sha256 이 허용 목록과 다름 — {p} (release_check 로 확인 뒤 다시)")
            out.append((p, full))
    else:
        for it in COPY_ITEMS:
            base = os.path.join(src, it)
            if os.path.isfile(base):
                out.append((it, base))
                continue
            for r, ds, fs in os.walk(base):
                ds[:] = sorted(d for d in ds if d not in ("__pycache__", "node_modules", ".git"))
                for f in sorted(fs):
                    if not f.endswith((".pyc", ".bak", ".part")):
                        full = os.path.join(r, f)
                        out.append((os.path.relpath(full, src).replace("\\", "/"), full))
    out.sort()
    return out


def cmd_build(a):
    src = os.path.abspath(a.src or ROOT)
    version = U.read_version_file(src)
    U.parse_version(version)
    files = pick_files(src, not a.no_allowlist)
    idx = {"format": "kimbiseo-update-files/1", "version": version,
           "files": {rel: {"sha256": U.sha256_file(full), "size": os.path.getsize(full)} for rel, full in files}}
    missing = [m for m in U.MUST_HAVE if m not in idx["files"]]
    if missing:
        raise SystemExit(f"멈춤: 꼭 있어야 할 파일이 없음 {missing}")
    os.makedirs(a.out, exist_ok=True)
    name = f"KimBiseo-update-{version}.zip"
    zp = os.path.join(a.out, name)
    with zipfile.ZipFile(zp + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        zi = zipfile.ZipInfo(U.PKG_INDEX, FIXED_TIME)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        z.writestr(zi, json.dumps(idx, ensure_ascii=False, indent=0, sort_keys=True))
        for rel, full in files:
            zi = zipfile.ZipInfo(U.PKG_ROOT + rel, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(zi, f.read())
    os.replace(zp + ".tmp", zp)
    key = load_key(a.key)
    base = a.base_url if a.base_url.endswith("/") else a.base_url + "/"
    signed = {"app": "kimbiseo", "version": version, "date": time.strftime("%Y-%m-%d"), "key_id": KEY_ID,
              "min_from": a.min_from, "notes": a.notes or [],
              "package": {"file": name, "url": base + name, "size": os.path.getsize(zp), "sha256": U.sha256_file(zp)},
              "deps": U.deps_of(src), "files_count": len(files), "release_page": a.release_page or ""}
    if a.setup_zip:
        signed["setup"] = {"file": os.path.basename(a.setup_zip), "url": base + os.path.basename(a.setup_zip),
                           "size": os.path.getsize(a.setup_zip), "sha256": U.sha256_file(a.setup_zip)}
    doc = {"format": "kimbiseo-update/1", "key_id": KEY_ID, "signed": signed,
           "sig": base64.b64encode(key.sign(canonical(signed))).decode()}
    mp = os.path.join(a.out, "latest.json")
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(json.dumps({"판": version, "꾸러미": zp, "크기": signed["package"]["size"], "sha256": signed["package"]["sha256"],
                      "파일": len(files), "목록": mp, "공개키": pub_b64(key)}, ensure_ascii=False, indent=1))
    return 0


def cmd_verify(a):
    sys.path.insert(0, ROOT)
    from app.core import update as UP
    doc = json.load(open(a.manifest, encoding="utf-8"))
    s = UP.verify_manifest(doc)
    print("서명 맞음:", s["version"], s["package"]["file"], s["package"]["size"])
    if a.zip:
        if os.path.getsize(a.zip) != s["package"]["size"] or U.sha256_file(a.zip) != s["package"]["sha256"]:
            print("꾸러미가 목록과 다름")
            return 1
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            idx = U.extract_package(a.zip, os.path.join(t, "x"))
            if U.deps_of(os.path.join(t, "x")) != s["deps"]:
                print("부품 정보가 목록과 다름")
                return 1
        print("꾸러미 맞음:", len(idx["files"]), "개")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    p = sub.add_parser("pubkey")
    p.add_argument("--key", required=True)
    b = sub.add_parser("build")
    b.add_argument("--key", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--base-url", required=True)
    b.add_argument("--notes", nargs="*")
    b.add_argument("--min-from", default="0.1.0")
    b.add_argument("--release-page", default="")
    b.add_argument("--setup-zip", default="")
    b.add_argument("--src", default="")
    b.add_argument("--no-allowlist", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--zip", default="")
    a = ap.parse_args()
    return {"keygen": cmd_keygen, "pubkey": cmd_pubkey, "build": cmd_build, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
