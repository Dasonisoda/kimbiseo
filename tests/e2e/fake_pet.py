# 시험용 가짜 펫 — 본체가 펫에 보내는 /expr /mouth /bubble /motion /talk /emotion 을 받아 기록만 한다.
#   python fake_pet.py --port 17961 --log 펫기록.jsonl      (이 PC 127.0.0.1 에서만 듣는다)
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

A = None
LOCK = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _ok(self, obj=None):
        b = json.dumps(obj or {"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._ok({"ok": True, "pet": "fake"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {"_raw": raw[:200].decode("utf-8", "replace")}
        with LOCK, open(A.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "path": self.path, "body": body}, ensure_ascii=False) + "\n")
        self._ok()


def main():
    global A
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17961)
    ap.add_argument("--log", required=True)
    A = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", A.port), H)
    print(f"가짜 펫 127.0.0.1:{A.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
