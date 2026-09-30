#!/usr/bin/env python3
"""In-sandbox TCP -> UNIX-socket relay.

The sandbox has its own empty network namespace (loopback only). This relay
listens on 127.0.0.1:<port> inside it and pipes each connection to the host's
model gate through a bind-mounted UNIX socket. It is the only way out, and the
gate on the other end only speaks to the model API.

    python3 sandbox_relay.py 8080 /run/llm/llm.sock
"""
import socket
import sys
import threading


def pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve(port: int, path: str) -> None:
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", port))
    ls.listen(64)
    while True:
        c, _ = ls.accept()
        u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            u.connect(path)
        except OSError:
            c.close()
            continue
        threading.Thread(target=pipe, args=(c, u), daemon=True).start()
        threading.Thread(target=pipe, args=(u, c), daemon=True).start()


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2])
