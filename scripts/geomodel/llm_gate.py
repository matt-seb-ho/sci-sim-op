#!/usr/bin/env python3
"""Host-side model gate for sandboxed agent runs.

Listens on a UNIX socket that is bind-mounted into the sandbox (the sandbox
has no network namespace access). Accepts only

    POST /api/v1/chat/completions   with "model" == the allowed model

and forwards it to OpenRouter over TLS, adding the API key on the host side.
The key never enters the sandbox. Before forwarding it:
  - rejects any other path, method or model (403);
  - strips request fields that would give the agent web access through the
    API (plugins, web_search_options, :online model suffixes);
  - asks OpenRouter to report usage/cost for the request;
  - refuses new requests once the run's spend reaches --cap-usd (402).

Every request is logged as one JSON line to --log (status, tokens, cost);
the key and the prompt text are never logged.

    python3 llm_gate.py --socket /path/llm.sock --model xiaomi/mimo-v2.6-flash \
        --cap-usd 3 --log usage.jsonl          # key read from $OPENROUTER_API_KEY
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

STRIP_FIELDS = ("plugins", "web_search_options", "tools_server", "search_parameters")


class Gate:
    def __init__(self, model: str, cap: float, log_path: str, base_url: str, key: str, seed=None):
        self.model = model
        self.seed = seed
        self.cap = cap
        self.log_path = log_path
        u = urlparse(base_url)
        assert u.scheme == "https", "upstream must be https"
        self.host = u.hostname
        self.port = u.port or 443
        self.prefix = u.path.rstrip("/")  # e.g. /api/v1
        self.key = key
        self.spent = 0.0
        self.n = 0
        self.lock = threading.Lock()
        self.ctx = ssl.create_default_context()

    def log(self, rec: dict) -> None:
        rec["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self.lock, open(self.log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    gate: Gate  # set on the class

    def log_message(self, *a):  # silence default stderr logging
        pass

    def _deny(self, code: int, msg: str) -> None:
        body = json.dumps({"error": {"message": msg, "code": code}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.gate.log({"status": code, "deny": msg, "path": self.path})

    def do_GET(self):
        self._deny(403, "only POST /api/v1/chat/completions is allowed")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_GET

    def do_POST(self):
        g = self.gate
        path = urlparse(self.path).path
        if path.rstrip("/") not in ("/api/v1/chat/completions", "/v1/chat/completions", "/chat/completions"):
            return self._deny(403, f"path not allowed: {path}")
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            req = json.loads(raw)
        except Exception:
            return self._deny(400, "body is not JSON")
        if req.get("model") != g.model:
            return self._deny(403, f"model not allowed: {req.get('model')!r}")
        with g.lock:
            if g.spent >= g.cap:
                over = True
            else:
                over = False
                g.n += 1
                rid = g.n
        if over:
            return self._deny(402, f"run budget exhausted (${g.spent:.4f} >= ${g.cap})")
        stripped = [k for k in STRIP_FIELDS if req.pop(k, None) is not None]
        req["usage"] = {"include": True}
        if g.seed is not None:
            req["seed"] = g.seed
        if req.get("stream"):
            so = req.setdefault("stream_options", {})
            so["include_usage"] = True
        body = json.dumps(req).encode()

        t0 = time.time()
        conn = http.client.HTTPSConnection(g.host, g.port, context=g.ctx, timeout=600)
        try:
            conn.request("POST", g.prefix + "/chat/completions", body=body, headers={
                "Authorization": f"Bearer {g.key}",
                "Content-Type": "application/json",
                "Accept": self.headers.get("Accept", "*/*"),
                "HTTP-Referer": "https://github.com/sci-sim-op",
                "X-Title": "forge-v0-sandbox",
            })
            resp = conn.getresponse()
        except Exception as e:  # upstream unreachable
            conn.close()
            return self._deny(502, f"upstream error: {type(e).__name__}")

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "content-length", "connection", "content-encoding",
                             "set-cookie", "strict-transport-security"):
                continue
            self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()

        usage = None
        tail = b""
        nbytes = 0
        try:
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                nbytes += len(chunk)
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
                tail = (tail + chunk)[-65536:]
                if b'"usage"' in chunk or b'"cost"' in chunk:
                    u = _find_usage(tail)
                    if u:
                        usage = u
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()
        if usage is None:
            usage = _find_usage(tail)
        cost = float((usage or {}).get("cost") or 0.0)
        if usage and not cost:
            # fallback: price the tokens (mimo-v2.6-flash list price)
            cost = (usage.get("prompt_tokens", 0) * 0.14 + usage.get("completion_tokens", 0) * 0.28) / 1e6
        with g.lock:
            g.spent += cost
            spent = g.spent
        g.log({"id": rid, "status": resp.status, "secs": round(time.time() - t0, 2), "bytes": nbytes,
               "prompt_tokens": (usage or {}).get("prompt_tokens"),
               "completion_tokens": (usage or {}).get("completion_tokens"),
               "cost": round(cost, 6), "spent": round(spent, 6), "stripped": stripped,
               "usage_seen": usage is not None})


def _find_usage(buf: bytes):
    """Return the last usage object in an SSE or JSON body, if any."""
    txt = buf.decode("utf-8", "replace")
    best = None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if '"usage"' not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        u = obj.get("usage")
        if isinstance(u, dict) and u:
            best = u
    return best


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        req, _ = super().get_request()
        return req, ("sandbox", 0)  # BaseHTTPRequestHandler wants an address tuple


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--seed", type=int, default=None, help="sampling seed added to every request")
    ap.add_argument("--base-url", default=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    a = ap.parse_args()
    key = os.environ.pop("OPENROUTER_API_KEY", "")
    if not key:
        print("llm_gate: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    if os.path.exists(a.socket):
        os.unlink(a.socket)
    Handler.gate = Gate(a.model, a.cap_usd, a.log, a.base_url, key, a.seed)
    srv = Server(a.socket, Handler)
    os.chmod(a.socket, 0o600)
    print(f"llm_gate: listening on {a.socket} for {a.model}, cap ${a.cap_usd}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        try:
            os.unlink(a.socket)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
