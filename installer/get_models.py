# 김비서 모델 받기·확인 — installer/models.json 의 주소·크기·해시대로 받는다(파이썬 표준 라이브러리만).
#
#   python get_models.py list                         받을 모델·크기 보기
#   python get_models.py get [이름...] [--all]         받기(이름 없으면 필수 모델만, --all 이면 선택 모델까지)
#   python get_models.py check <이름> [--dir 폴더]     이미 있는 폴더를 해시로 확인만(아무것도 쓰지 않음)
#   공통: --dest <모델 폴더>(기본 = 설정 '경로.모델', %LOCALAPPDATA%\KimBiseo\models) · --settings <설정.json> · --json
#
# - 이어 받기: 받는 중인 파일은 <파일>.part 로 두고, 끊기면 다음에 이어서 받음(서버가 Range 를 받으면).
# - 확인: 크기 + sha256(큰 파일) 또는 git_sha1(작은 파일, git blob 해시). 공식 해시가 빈 칸인 파일은
#         '설치 때 확인' — 크기만 보고 받은 뒤 계산한 sha256 을 보여 주고, --allow-unverified 없이는 받지 않음.
# - 받는 주소: https 만, 정해 둔 곳(huggingface.co·hf.co·github.com 과 그 내려받기 서버)만 따라감.
# - 확인 기록: sha256 이 맞은 파일은 그 폴더의 .verified.json 에 (크기·수정 시각·sha256)을 적어 두고, 다음 설치 때
#   크기·수정 시각이 같으면 다시 계산하지 않음(5GB 두뇌 모델을 매번 다 읽지 않게). check 명령은 늘 다시 계산.
# - 설치 프로그램(setup_core.py)은 ensure_model() 과 download() 를 부름(진행 표시 progress 를 받음).
# 종료 코드: 0 = 됨, 1 = 실패(어느 파일이 왜 실패했는지 한국어로 출력)
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "models.json")
UA = "KimBiseo-installer/1"
ALLOWED_HOSTS = ("huggingface.co", ".hf.co", "github.com", ".githubusercontent.com")
CHUNK = 1024 * 1024


def models_dir(args):
    if args.dest:
        return os.path.abspath(os.path.expandvars(args.dest))
    sys.path.insert(0, os.path.join(REPO, "voice"))
    import config as C  # 표준 라이브러리만 쓰는 설정 읽기
    return C.path(C.load(args.settings, warn=lambda *_: None), "모델")


def load_manifest(path=MANIFEST):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    if m.get("schema") != "kimbiseo-models/1":
        raise SystemExit("models.json 형식이 다릅니다")
    return {x["name"]: x for x in m["models"]}


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024


def host_ok(url, hosts=None):
    u = urllib.parse.urlsplit(url)
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == a.lstrip(".") or (a.startswith(".") and h.endswith(a)) for a in (hosts or ALLOWED_HOSTS))


def _redirect_for(hosts=None):
    class _Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            newurl = urllib.parse.urljoin(req.full_url, newurl)
            if not host_ok(newurl, hosts):
                raise urllib.error.URLError(f"허용하지 않은 주소로 넘김: {urllib.parse.urlsplit(newurl).hostname}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    return _Redirect


OPENER = urllib.request.build_opener(_redirect_for())


def file_hashes(path, want_git=False, progress=None, algo="sha256"):
    size = os.path.getsize(path)
    h256 = hashlib.new(algo)
    hg = hashlib.sha1(b"blob %d\0" % size) if want_git else None
    done, last = 0, 0
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK * 4)
            if not b:
                break
            h256.update(b)
            if hg:
                hg.update(b)
            done += len(b)
            if progress and time.time() - last > 0.5:
                last = time.time()
                progress(done, size)
    return h256.hexdigest(), (hg.hexdigest() if hg else None)


def _seen_file(path):
    return os.path.join(os.path.dirname(path), ".verified.json")


def _seen_get(path):
    try:
        with open(_seen_file(path), encoding="utf-8") as f:
            j = json.load(f)
        st = os.stat(path)
        v = j.get(os.path.basename(path))
        if v and v[0] == st.st_size and v[1] == st.st_mtime_ns:
            return v[2]
    except (OSError, ValueError, TypeError, IndexError, AttributeError):
        pass
    return None


def _seen_put(path, s256):
    f = _seen_file(path)
    try:
        try:
            with open(f, encoding="utf-8") as fh:
                j = json.load(fh)
            if not isinstance(j, dict):
                j = {}
        except (OSError, ValueError):
            j = {}
        st = os.stat(path)
        j[os.path.basename(path)] = [st.st_size, st.st_mtime_ns, s256]
        with open(f + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(j, fh, ensure_ascii=False, indent=0)
        os.replace(f + ".tmp", f)
    except OSError:
        pass


def verify(path, spec, progress=None, use_seen=False):
    """→ (됨?, 이유, 계산한 sha256). use_seen=True 면 .verified.json 기록(크기·수정 시각이 같을 때)을 믿음."""
    if not os.path.isfile(path):
        return False, "파일 없음", None
    size = os.path.getsize(path)
    if spec.get("size") is not None and size != spec["size"]:
        return False, f"크기 다름({size} ≠ {spec['size']})", None
    if use_seen and spec.get("sha256") and _seen_get(path) == spec["sha256"]:
        return True, "sha256 맞음(확인 기록)", spec["sha256"]
    s256, sg = file_hashes(path, want_git=bool(spec.get("git_sha1")), progress=progress)
    if spec.get("sha256"):
        if s256 == spec["sha256"]:
            _seen_put(path, s256)
        return (s256 == spec["sha256"], "sha256 맞음" if s256 == spec["sha256"] else "sha256 다름", s256)
    if spec.get("git_sha1"):
        return (sg == spec["git_sha1"], "git_sha1 맞음" if sg == spec["git_sha1"] else "git_sha1 다름", s256)
    return True, "크기만 맞음(공식 해시 없음 — 설치 때 확인)", s256


def base_url(m):
    """models.json 의 base_url 에 있는 {revision} 자리를 고정 판으로 채움(판이 바뀌면 받는 파일도 그 판)."""
    u = m["base_url"]
    if "{revision}" in u:
        if not m.get("revision"):
            raise ValueError(f"{m.get('name')}: base_url 에 {{revision}} 이 있는데 revision 이 비어 있음")
        u = u.replace("{revision}", m["revision"])
    return u


def download(url, dest, size=None, tries=5, say=print, progress=None, hosts=None):
    """url → dest. size 를 모르면 None(서버가 알려 준 길이로). 받는 중엔 dest.part, 끊기면 이어서 받음.
    progress(받은 바이트, 전체 바이트|None, 초당 바이트) · hosts = 허용 호스트 목록(기본 ALLOWED_HOSTS)."""
    if not host_ok(url, hosts):
        raise RuntimeError(f"허용하지 않은 주소: {url}")
    opener = urllib.request.build_opener(_redirect_for(hosts)) if hosts else OPENER
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last_err = ""
    done = False
    for attempt in range(1, tries + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if size is not None and have > size:
            os.remove(part)
            have = 0
        if size is not None and have == size:
            done = True
            break
        req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with opener.open(req, timeout=60) as r:
                if have and r.status != 206:      # 이어 받기를 안 받는 서버 → 처음부터
                    have = 0
                if size is None:
                    cr = r.headers.get("Content-Range", "")
                    tail = cr.rsplit("/", 1)[-1] if "/" in cr else ""
                    if tail.isdigit():
                        size = int(tail)
                    elif r.headers.get("Content-Length", "").isdigit():
                        size = int(r.headers["Content-Length"]) + have
                mode = "ab" if have else "wb"
                t0, last, got0 = time.time(), 0, have
                with open(part, mode) as f:
                    while True:
                        b = r.read(CHUNK)
                        if not b:
                            break
                        f.write(b)
                        have += len(b)
                        if time.time() - last > 1:
                            last = time.time()
                            rate = (have - got0) / max(1e-6, time.time() - t0)
                            if progress:
                                progress(have, size, rate)
                            else:
                                say(f"    {os.path.basename(dest)} {human(have)} / {human(size)} ({human(rate)}/초)")
            if size is None or have == size:
                size = have
                done = True
                break
            raise OSError(f"받은 크기가 모자람({have}/{size})")
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            last_err = str(ex)
            say(f"    {attempt}번째 시도 실패: {ex} — 잠시 뒤 이어서 받음")
            if isinstance(ex, urllib.error.HTTPError) and ex.code in (401, 403, 404, 410):
                break
            time.sleep(min(30, 2 * attempt))
    if not done:
        raise RuntimeError(f"여러 번 시도했지만 받지 못함(인터넷 연결 확인 후 다시 시도) — {last_err}")
    if progress:
        progress(size, size, 0)
    os.replace(part, dest)


def ensure_model(m, root, say=print, progress=None, allow_unverified=False):
    """모델 하나를 root\\<이름>\\ 에 받고 확인. 이미 맞는 파일은 건너뜀. → (됨?, [실패한 파일], 받은 바이트)
    progress(이 모델에서 끝난 바이트, 이 모델 전체 바이트, 초당 바이트, 지금 하는 일)"""
    folder = os.path.join(root, m["name"])
    total = sum(f["size"] for f in m["files"])
    finished, got, failed = 0, 0, []
    for f in m["files"]:
        dest = os.path.join(folder, *f["path"].split("/"))
        if not (f.get("sha256") or f.get("git_sha1")) and not allow_unverified:
            say(f"  건너뜀 {f['path']}: 공식 해시가 없음(설치 때 확인)")
            failed.append(f"{m['name']}/{f['path']}")
            continue
        pv = (lambda d, t, _base=finished: progress(_base + d * 0.999, total, 0, "확인")) if progress else None
        ok, why, _ = verify(dest, f, progress=pv, use_seen=True) if os.path.isfile(dest) else (False, "", None)
        if ok:
            say(f"  있음 {f['path']} ({why})")
            finished += f["size"]
            if progress:
                progress(finished, total, 0, "확인")
            continue
        say(f"  받는 중 {f['path']} ({human(f['size'])})")
        pd = (lambda d, t, r, _base=finished: progress(_base + (d or 0), total, r, "받기")) if progress else None
        try:
            download(base_url(m) + urllib.parse.quote(f["path"]), dest, f["size"], say=say, progress=pd)
        except RuntimeError as ex:
            say(f"  실패 {f['path']}: {ex}")
            failed.append(f"{m['name']}/{f['path']}")
            continue
        got += f["size"]
        pv = (lambda d, t, _base=finished: progress(_base + d * 0.999, total, 0, "확인")) if progress else None
        ok, why, s256 = verify(dest, f, progress=pv)
        if not ok:
            os.replace(dest, dest + ".bad")
            say(f"  실패 {f['path']}: {why} — 받은 파일을 .bad 로 옮김(다시 시도하면 새로 받음)")
            failed.append(f"{m['name']}/{f['path']}")
        else:
            say(f"  됨 {f['path']} ({why})" + ("" if (f.get('sha256') or f.get('git_sha1')) else f" sha256={s256}"))
        finished += f["size"]
    return (not failed), failed, got


def cmd_list(models, args):
    rows = []
    for m in models.values():
        rows.append({"name": m["name"], "role": m["role"], "required": m["required"], "size": m["size_total"], "license": m["license"],
                     "unverified": [f["path"] for f in m["files"] if not (f.get("sha256") or f.get("git_sha1"))]})
        if not args.json:
            print(f"{m['name']:<28} {human(m['size_total']):>9}  {'필수' if m['required'] else '선택'}  {m['role']}  [{m['license']}]"
                  + ("  ※공식 해시 없음 — 설치 때 확인" if rows[-1]["unverified"] else ""))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


def cmd_check(models, args):
    if not args.names:
        print("확인할 모델 이름을 적어 주세요")
        return 1
    bad = 0
    out = []
    for name in args.names:
        m = models.get(name)
        if not m:
            print(f"모르는 모델: {name}")
            return 1
        folder = os.path.abspath(args.dir) if args.dir else os.path.join(models_dir(args), name)
        for f in m["files"]:
            ok, why, s256 = verify(os.path.join(folder, *f["path"].split("/")), f)
            out.append({"model": name, "path": f["path"], "ok": ok, "why": why, "sha256": s256})
            bad += not ok
            if not args.json:
                print(f"  {'됨 ' if ok else '실패'} {name}/{f['path']} — {why}")
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"확인 끝: 파일 {len(out)}개 중 실패 {bad}개")
    return 0 if bad == 0 else 1


def cmd_get(models, args):
    names = args.names or [n for n, m in models.items() if m["required"] or args.all]
    root = models_dir(args)
    print(f"모델 폴더: {root}")
    failed = []
    for name in names:
        m = models.get(name)
        if not m:
            print(f"모르는 모델: {name}")
            return 1
        print(f"[{name}] {human(m['size_total'])} — {m['role']}")
        ok, bad, _ = ensure_model(m, root, allow_unverified=args.allow_unverified)
        failed += bad
    if failed:
        print("받지 못한 파일: " + ", ".join(failed))
        return 1
    print("모두 받음")
    return 0


def main():
    ap = argparse.ArgumentParser(description="김비서 모델 받기·확인")
    ap.add_argument("cmd", choices=["list", "get", "check"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true", help="선택 모델까지")
    ap.add_argument("--dest", default=None, help="모델 폴더(기본 = 설정 '경로.모델')")
    ap.add_argument("--dir", default=None, help="check: 이 폴더를 그 모델 폴더로 보고 확인")
    ap.add_argument("--settings", default=None)
    ap.add_argument("--allow-unverified", action="store_true", help="공식 해시가 없는 파일도 크기만 보고 받음")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    models = load_manifest()
    return {"list": cmd_list, "get": cmd_get, "check": cmd_check}[args.cmd](models, args)


if __name__ == "__main__":
    sys.exit(main())
