#!/usr/bin/env bash
# usage: log.sh <logfile-basename> <source> <level> <event> <detail>
f="/home/matt/projects/sci-sim-op/.autoresearch/logs/$1.jsonl"
python3 -c '
import json,sys,datetime
ts=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")
print(json.dumps({"ts":ts,"source":sys.argv[1],"level":sys.argv[2],"event":sys.argv[3],"detail":sys.argv[4]}))
' "$2" "$3" "$4" "$5" >> "$f"
