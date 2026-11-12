# 잠금 파일 만들기(개발자용) — requirements/*.txt 를 pip 로 풀어서 '정확한 판 + 받을 주소 + sha256' 목록(locks/*.json)을 만든다.
#   설치 프로그램은 이 목록대로만 받고(해시 확인), pip 에는 받은 파일만 주고 인터넷을 쓰지 않게 한다(--no-index).
#
#   <python> make_lock.py <requirements.txt> <locks/이름.json> [--torch cu128|cpu] [-c 제약.txt]
#     <python> = 설치 때와 같은 판의 파이썬(3.11.9 embeddable 에 pip·setuptools 를 넣은 것). pip install --dry-run --report 를 씀.
#     --torch  = torch·torchaudio 를 PyTorch 공식 저장소(download.pytorch.org/whl/<판>)에서, 나머지는 PyPI 에서.
#   만든 목록은 그 파이썬의 판·윈도우 64비트 기준(markers 가 그 PC 기준으로 풀림).
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("requirements")
    ap.add_argument("out")
    ap.add_argument("--torch", default="")
    ap.add_argument("-c", "--constraint", default="")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as td:
        rep = os.path.join(td, "report.json")
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--no-build-isolation", "--quiet",
               "--report", rep, "-r", a.requirements]
        if a.constraint:
            cmd += ["-c", a.constraint]
        if a.torch:
            cmd += ["--index-url", f"https://download.pytorch.org/whl/{a.torch}", "--extra-index-url", "https://pypi.org/simple"]
        subprocess.run(cmd, check=True)
        with open(rep, encoding="utf-8") as f:
            r = json.load(f)
    pk = []
    for i in r["install"]:
        md, di = i["metadata"], i["download_info"]
        url = di["url"]
        hashes = (di.get("archive_info") or {}).get("hashes") or {}
        h = hashes.get("sha256") or str((di.get("archive_info") or {}).get("hash", "")).replace("sha256=", "")
        if not h or len(h) != 64:
            raise SystemExit(f"sha256 없음: {md['name']} {url}")
        pk.append({"name": md["name"], "version": md["version"], "file": url.rsplit("/", 1)[-1].replace("%2B", "+"),
                   "url": url, "sha256": h, "sdist": not url.endswith(".whl")})
    pk.sort(key=lambda x: x["name"].lower())
    env = r.get("environment") or {}
    out = {"schema": "kimbiseo-lock/1", "made": datetime.date.today().isoformat(),
           "requirements": os.path.relpath(os.path.abspath(a.requirements), os.path.dirname(HERE)).replace("\\", "/"),
           "python": env.get("python_full_version", ""), "platform": env.get("platform_machine", "") + "/" + env.get("sys_platform", ""),
           "torch_index": a.torch, "packages": pk}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{a.out}: 꾸러미 {len(pk)}개 (소스판 {sum(p['sdist'] for p in pk)}개)")


if __name__ == "__main__":
    main()
