"""A stand-in for the hub's upload routes, only to test web/app/static/upload.js in a real browser (127.0.0.1 only).

It follows the real server's rules (blocks, runs, progress, finish; a broken request keeps the whole blocks that
arrived) and can slow the line down, hang, or answer 502, so
the engine's retries, resume, cancel and request sizing can be watched. Not part of the product."""
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BLOCK = 262144
ROOT = Path(__file__).parent
LOCK = threading.Lock()
STATE = {}
MODE = {}


def reset():
    STATE.clear()
    STATE.update({"uploads": {}, "next": 1, "log": [], "deleted": [], "starts": 0, "finishes": 0, "concurrent": 0, "max_concurrent": 0})
    MODE.clear()
    MODE.update({"rate": 0, "fail_next": 0, "hang_next": 0, "hang_seconds": 4, "fail_all": False})


reset()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if path == "/__state":
            with LOCK:
                snapshot = {k: v for k, v in STATE.items() if k != "uploads"}
                snapshot["uploads"] = {str(k): {"size": u["size"], "blocks": "".join(map(str, u["blocks"])), "bytes": u["bytes"]}
                                       for k, u in STATE["uploads"].items()}
            return self.send_json(snapshot)
        if path.startswith("/files/") and path.endswith("/progress"):
            fid = int(path.split("/")[2])
            with LOCK:
                u = STATE["uploads"].get(fid)
            if u is None:
                return self.send_json({"ok": False}, 404)
            return self.send_json({"ok": True, "size": u["size"], "block": BLOCK, "parts": "".join("1" if b == 1 else "0" for b in u["blocks"])})
        name = "uptest.html" if path in ("/", "") else path.lstrip("/")
        target = ROOT / name
        if name == "upload.js":                                       # the engine under test, straight from the app
            target = ROOT.parent.parent / "app" / "static" / "upload.js"
        if not target.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if name.endswith(".html") else "application/javascript")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        if path == "/__reset":
            self.body()
            reset()
            return self.send_json({"ok": True})
        if path == "/__mode":
            MODE.update(json.loads(self.body() or b"{}"))
            return self.send_json({"ok": True, "mode": MODE})
        if path == "/projects/1/files/start":
            fields = urllib.parse.parse_qs(self.body().decode("latin-1")) if "urlencoded" in (self.headers.get("Content-Type") or "") else self.multipart()
            size = int(fields["size"])
            with LOCK:
                fid = STATE["next"]
                STATE["next"] += 1
                STATE["starts"] += 1
                STATE["uploads"][fid] = {"size": size, "blocks": [0] * -(-size // BLOCK), "bytes": 0, "name": fields["name"]}
            return self.send_json({"ok": True, "id": fid, "name": fields["name"], "category": "media", "size": size})
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "files":
            fid, action = int(parts[1]), parts[2]
            with LOCK:
                u = STATE["uploads"].get(fid)
            if action == "delete":
                self.body()
                with LOCK:
                    STATE["uploads"].pop(fid, None)
                    STATE["deleted"].append(fid)
                return self.send_json({"ok": True})
            if u is None:
                self.body()
                return self.send_json({"ok": False}, 404)
            if action == "finish":
                self.body()
                with LOCK:
                    if 0 in u["blocks"] or 2 in u["blocks"]:
                        return self.send_json({"ok": False, "message": "incomplete"}, 409)
                    STATE["finishes"] += 1
                return self.send_json({"ok": True, "id": fid, "name": u["name"], "category": "media", "size": u["size"]})
            if action == "chunk":
                return self.chunk(fid, u, int(query["offset"][0]))
        self.body()
        self.send_json({"ok": False}, 404)

    def multipart(self):
        raw = self.body().decode("latin-1")
        fields = {}
        for piece in raw.split("--")[1:-1]:
            head, _, value = piece.partition("\r\n\r\n")
            if 'name="' in head:
                fields[head.split('name="')[1].split('"')[0]] = value.rstrip("\r\n-")
        return fields

    def chunk(self, fid, u, offset):
        length = int(self.headers.get("Content-Length") or 0)
        with LOCK:
            STATE["concurrent"] += 1
            STATE["max_concurrent"] = max(STATE["max_concurrent"], STATE["concurrent"])
            hang = MODE["hang_next"] > 0
            if hang:
                MODE["hang_next"] -= 1
            failing = MODE["fail_all"] or MODE["fail_next"] > 0
            if failing and not MODE["fail_all"]:
                MODE["fail_next"] -= 1
        started = time.time()
        try:
            if hang:
                time.sleep(MODE["hang_seconds"])                     # reads nothing: the browser's upload stalls
            got, rate = 0, MODE["rate"]
            limit = int(length * 0.3) if failing else length          # a failing request breaks off early
            while got < limit:
                piece = self.rfile.read(min(16384, limit - got))
                if not piece:
                    return
                got += len(piece)
                if rate:
                    time.sleep(len(piece) / rate)
            if failing:
                self.rfile.read(length - got)
                with LOCK:                                            # like the hub: the front part that arrived is kept
                    first = offset // BLOCK
                    for i in range(first, first + got // BLOCK):
                        u["blocks"][i] = 1
                self.send_json({"ok": False}, 502)
                with LOCK:
                    STATE["log"].append({"id": fid, "offset": offset, "length": length, "status": 502, "seconds": round(time.time() - started, 2)})
                return
            ok = offset % BLOCK == 0 and offset < u["size"] and offset + length <= u["size"] and (offset + length == u["size"] or length % BLOCK == 0)
            if not ok:
                return self.send_json({"ok": False, "message": "bad_offset"}, 409)
            with LOCK:
                first = offset // BLOCK
                for i in range(first, first + -(-length // BLOCK)):
                    u["blocks"][i] = 1
                u["bytes"] += length
                STATE["log"].append({"id": fid, "offset": offset, "length": length, "status": 200, "seconds": round(time.time() - started, 2)})
            self.send_json({"ok": True})
        except (ConnectionError, OSError):
            with LOCK:
                STATE["log"].append({"id": fid, "offset": offset, "length": length, "status": "aborted", "seconds": round(time.time() - started, 2)})
        finally:
            with LOCK:
                STATE["concurrent"] -= 1


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
