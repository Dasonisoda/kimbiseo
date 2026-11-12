# 김비서 귀 서버 — ear.py(whisper-large-v3-turbo)를 이 PC 안(127.0.0.1) TCP 로 내놓는다.
#
# 규약(한 줄 JSON + 이어서 소리 바이트)
#   요청 {"op":"asr","id":N,"n":바이트수, "max_tokens":선택, "quiet":선택}\n + int16 16kHz 모노 PCM
#        max_tokens = 받아쓰기 길이 상한(이름 부르기 확인처럼 짧은 조각에서 반복 환각이 귀를 오래 붙잡지 않게)
#        quiet      = 대기 중 이름 확인용 조각 — 로그에 글을 남기지 않음
#   응답 {"id":N,"text":"...","sec":계산초,"rms_db":소리크기,"audio_sec":소리초}\n
#   {"op":"ping"}\n   → {"type":"pong","engine":"whisper"}
#   {"op":"status"}\n → {"type":"status", 장치·모델 이름·그래픽 메모리 …}
#
# 실행: python ear_server.py [--settings 설정.json] [--port 8872] [--device auto|cuda|cpu] [--parent_pid N]
import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

GPU_LOCK = threading.Lock()
HOT = {"ids": None, "text": ""}
STATE = {"ear": None, "cfg": None, "log": print, "served": 0, "started": time.time(), "model": "", "device": ""}


def recv_exact(f, n):
    buf = f.read(n)
    if buf is None or len(buf) < n:
        raise OSError("연결 끊김")
    return buf


def hot_transcribe(ear, x):
    """설정 '귀.핫워드' 를 whisper 앞글로 줘서 그 낱말을 더 잘 알아듣게.
    앞글이 결과에 그대로 새어 나오면(조용한 소리 등) 앞글 없이 다시."""
    words = [w for w in (STATE["cfg"]["귀"].get("핫워드") or []) if w]
    if not words or len(x) < 16000 * 0.4:
        return ear.transcribe(x)
    if HOT["ids"] is None:
        HOT["text"] = ", ".join(words)
        HOT["ids"] = ear.prompt_ids(HOT["text"])
    t = ear.transcribe(x, prompt_ids=HOT["ids"])
    if HOT["text"] in t or t.replace(" ", "") in HOT["text"].replace(" ", ""):
        return ear.transcribe(x)
    return t


def status():
    import torch
    ear = STATE["ear"]
    vram = None
    if ear is not None and ear.cuda:
        mb = 1024 * 1024
        vram = dict(allocated_mib=round(torch.cuda.memory_allocated() / mb, 1), reserved_mib=round(torch.cuda.memory_reserved() / mb, 1),
                    max_allocated_mib=round(torch.cuda.max_memory_allocated() / mb, 1))
    return {"type": "status", "ok": ear is not None, "engine": "whisper", "device": STATE["device"],
            "model": os.path.basename(STATE["model"].rstrip("\\/")), "served": STATE["served"],
            "uptime_sec": round(time.time() - STATE["started"]), "pid": os.getpid(), "vram": vram}


def handle(conn, ear):
    log, cfg = STATE["log"], STATE["cfg"]
    max_bytes = int(float(cfg["귀"].get("최대_초") or 60) * 16000 * 2)
    show_text = bool(cfg["귀"].get("로그_글_남기기"))
    f = conn.makefile("rb")
    wlock = threading.Lock()

    def send(obj):
        with wlock:
            conn.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    try:
        import numpy as np
        import torch
        while True:
            line = f.readline(64 * 1024)
            if not line:
                return
            try:
                msg = json.loads(line.decode("utf-8"))
                assert isinstance(msg, dict)
            except Exception:  # noqa: BLE001
                send({"error": "JSON 오류"})
                return
            op = msg.get("op")
            if op == "ping":
                send({"type": "pong", "engine": ear.backend})
                continue
            if op == "status":
                send(status())
                continue
            if op != "asr":
                continue
            try:
                n = int(msg.get("n") or 0)
            except (TypeError, ValueError):
                n = -1
            if n < 0 or n > max_bytes or n % 2:
                send({"id": msg.get("id"), "error": f"소리 길이 오류(0~{max_bytes}바이트, 짝수)"})
                return
            pcm = np.frombuffer(recv_exact(f, n), dtype=np.int16) if n else np.zeros(0, np.int16)
            t0 = time.perf_counter()
            x = pcm.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
            text = ""
            if len(x) >= 1600:  # 0.1초 미만은 버림
                try:
                    with GPU_LOCK, torch.inference_mode():
                        mt = int(msg.get("max_tokens") or 0)
                        text = ear.transcribe(x, max_new_tokens=mt) if mt > 0 else hot_transcribe(ear, x)
                except Exception as ex:  # noqa: BLE001
                    log("받아쓰기 오류:", ex)
                    traceback.print_exc()
            sec = time.perf_counter() - t0
            STATE["served"] += 1
            send({"id": msg.get("id"), "text": text, "sec": sec,
                  "rms_db": 20 * np.log10(max(rms, 1e-9)), "audio_sec": len(x) / 16000})
            shown = f"[{text[:40]}]" if (show_text and not msg.get("quiet")) else f"(글 {len(text)}자)"
            log(f"#{msg.get('id')} {len(x) / 16000:.2f}초 → {sec * 1000:.0f}ms {shown}")
    except OSError:
        return
    finally:
        try:
            conn.close()
        except OSError:
            pass


def watch_parent(pid, log):
    """부모(실행 관리)가 끝나면 이 서버도 끝냄(윈도우)."""
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        log(f"부모 PID {pid} 못 찾음 — 감시 안 함")
        return
    k.WaitForSingleObject(h, 0xFFFFFFFF)
    log(f"부모 PID {pid} 끝남 → 귀 서버도 끝냄")
    os._exit(0)


def main():
    ap = argparse.ArgumentParser(description="김비서 귀 서버")
    ap.add_argument("--settings", default=None, help="사용자 설정 JSON(기본 %%APPDATA%%/KimBiseo/settings.json)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--device", default=None, help="auto | cuda | cpu (설정 '귀.장치' 보다 우선)")
    ap.add_argument("--threads", type=int, default=None, help="CPU 로 돌 때 스레드 수(설정 '귀.CPU_스레드')")
    ap.add_argument("--parent_pid", type=int, default=0)
    a = ap.parse_args()

    cfg = C.load(a.settings)
    log = C.Logger("ear.log", C.path(cfg, "로그"), "[귀 서버]")
    STATE.update(cfg=cfg, log=log)
    C.apply_hf_env(cfg)
    engine = cfg["귀"].get("엔진", "whisper")
    if engine != "whisper":
        log(f"귀.엔진 '{engine}' 은 지원하지 않음 → whisper")
    model = C.model_path(cfg, cfg["귀"].get("모델"))
    if not model or not os.path.isdir(model):
        log(f"귀 모델 폴더 없음: {model} — installer/get_models.py 로 받으세요")
        sys.exit(2)
    port = a.port or int(cfg["포트"]["귀"])
    # 포트를 먼저 잡아 둠 — 이미 쓰이면 모델을 올리기 전에 끝냄
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    if a.parent_pid:
        threading.Thread(target=watch_parent, args=(a.parent_pid, log), daemon=True).start()

    from ear import Ear
    device = C.pick_device(a.device or cfg["귀"].get("장치"), float(cfg["귀"].get("그래픽메모리_필요_GB") or 2.2), log)
    if not device.startswith("cuda"):
        import torch
        torch.set_num_threads(int(a.threads or cfg["귀"].get("CPU_스레드") or 8))
    log(f"귀 불러오는 중: whisper ({os.path.basename(model.rstrip(chr(92) + '/'))}) {device}")
    ear = Ear(model=model, device=device, language=cfg["귀"].get("언어") or "korean", log=log)
    STATE.update(ear=ear, model=model, device=device)
    log(f"준비 완료 127.0.0.1:{port} (PID {os.getpid()})")
    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(conn, ear), daemon=True).start()


if __name__ == "__main__":
    main()
