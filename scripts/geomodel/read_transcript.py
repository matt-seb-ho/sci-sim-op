#!/usr/bin/env python3
"""Read a pi JSON-mode transcript (pi_events.jsonl) as a numbered trace.

    python3 scripts/geomodel/read_transcript.py RUN_DIR [--full] [--stats]

Default: one line per tool call (turn, tool, command/path, result head). --full adds
assistant text and thinking. --stats prints counts: turns, tool calls by kind, files
touched per /site submission, and flags for network or out-of-bounds attempts.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

NET = re.compile(r"\b(curl|wget|pip3? install|pip install|urllib|requests\.get|http\.client|socket\.|nc |ssh |git clone|apt|npm i)", re.I)
URL = re.compile(r"https?://")
OOB = re.compile(r"(?<![\w/.])/(?!site\b|work\b|tmp\b|task\b|opt\b|usr\b|dev\b|proc\b|bin\b|etc\b|home/agent\b|lib)[A-Za-z_][\w.-]*")


def events(run: Path):
    with open(run / "pi_events.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def arg_text(args: dict) -> str:
    if "command" in args:
        return args["command"]
    return " ".join(f"{k}={str(v)[:120]}" for k, v in args.items() if k != "content")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--width", type=int, default=220)
    a = ap.parse_args()
    run = Path(a.run)
    turn = 0
    pending = {}
    kinds = collections.Counter()
    subs = collections.Counter()
    flags = []
    errors = 0
    W = a.width
    for e in events(run):
        t = e.get("type")
        if t == "turn_start":
            turn += 1
        elif t == "message_end" and e["message"].get("role") == "assistant" and a.full and not a.stats:
            for c in e["message"].get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    print(f"      [say] {c['text'][:W * 3]}")
                if c.get("type") == "thinking" and c.get("thinking", "").strip():
                    print(f"      [think] {c['thinking'][:W * 2]}")
        elif t == "tool_execution_start":
            pending[e["toolCallId"]] = (turn, e["toolName"], e.get("args", {}))
        elif t == "tool_execution_end":
            tr, name, args = pending.pop(e["toolCallId"], (turn, e.get("toolName"), {}))
            txt = arg_text(args)
            kinds[name] += 1
            for m in re.findall(r"/site/(gdr_\d+|grid)", txt):
                subs[m] += 1
            res = e.get("result", {})
            out = ""
            for c in res.get("content", []) if isinstance(res, dict) else []:
                if c.get("type") == "text":
                    out += c["text"]
            if e.get("isError"):
                errors += 1
            if NET.search(txt) or URL.search(txt):
                flags.append((tr, "network?", txt[:200]))
            for m in OOB.findall(txt):
                if m not in ("/dev/null",):
                    flags.append((tr, "path outside sandbox dirs?", m + "  <- " + txt[:160]))
                    break
            if not a.stats:
                one = txt.replace("\n", " ⏎ ")
                o = out.strip().replace("\n", " ⏎ ")
                print(f"{tr:4d} {name:5s} {'ERR ' if e.get('isError') else ''}{one[:W]}")
                print(f"           -> {o[:W]}")
    print(f"\n# turns={turn} tool_calls={sum(kinds.values())} errors={errors} by_tool={dict(kinds)}")
    print("# /site touches:", dict(subs.most_common()))
    for f in flags:
        print("# FLAG", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
