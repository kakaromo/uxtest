#!/bin/bash
# trace job 의 상위 프로세스·파일을 빠르게 본다:  scenarios/peek.sh <traceJobId> [dim=comm] [topN=8]
J=$1; DIM=${2:-comm}; N=${3:-8}
curl -s -XPOST 127.0.0.1:50051/api/agent/trace/attribution -H 'Content-Type: application/json' \
  -d "{\"jobIds\":[\"$J\"],\"dims\":[\"$DIM\"],\"sortBy\":\"bytes\",\"topN\":$N}" |
python3 -c '
import json,sys
d=json.load(sys.stdin); print("events", d.get("totalEvents"))
for g in d.get("groups",[]):
  for e in g["entries"]:
    print(f"  {e["key"][:40]:40s} R {e["readBytes"]/2**20:8.1f}MB  W {e["writeBytes"]/2**20:8.1f}MB  n={e["count"]}")'
