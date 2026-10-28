"""UFS trace 귀속 빈틈 점검: Read·Write 바이트를 (앱/커널) × (파일 있음/없음) × 파티션으로 나눈다.
python3 report/audit.py ~/.agent-standalone/archive/jobs/<시각>_<시나리오>/trace/*/result_fsio_ufs.parquet [...]
파티션 경계(PARTS)는 CPH2749 기준. 다른 기기는 /proc/partitions·by-name 으로 다시 잡는다."""
import collections
import re
import sys

import duckdb

PARTS = [("hybridswap", 123628, 385772), ("super", 385772, 4551404), ("userdata", 4551404, 124328955)]
KTHREAD = re.compile(r"^(kworker|f2fs_|kswapd|jbd2|loop\d|dm[-_]|kcompactd|ksoftirq|irq/|kverityd|erofs|swapper|z_erofs|kblockd|writeback|khugepaged|migration|rcu)")


def part(lun, lba):
    if lun != 0:
        return f"lun{lun}"
    for n, a, b in PARTS:
        if a <= lba < b:
            return n
    return "other"


def named(n):
    return bool(n) and n not in ("(unknown)",) and not n.startswith("ino:")


c = duckdb.connect()
for pq in sys.argv[1:]:
    rows = c.execute(f"""select opcode in (40,136) r, comm, coalesce(name,''), fs, lun, lba, size,
            coalesce(is_f2fs_node_write,false), coalesce(is_f2fs_meta_write,false), coalesce(is_checkpoint,false),
            coalesce(is_gc,false) or coalesce(is_f2fs_data_gc,false)
        from read_parquet('{pq}') where action='send_req' and opcode in (40,136,42,138)""").fetchall()
    print("==", pq.split("/jobs/")[1].split("/")[0] if "/jobs/" in pq else pq)
    for d in (True, False):
        R = [x for x in rows if x[0] == d]
        tot = sum(x[6] for x in R) or 1
        cat = collections.Counter()
        detail = collections.Counter()
        for _, comm, name, fs, lun, lba, sz, nd, mt, ck, gc in R:
            k = "kernel" if KTHREAD.match(comm or "") else "app"
            f = "file" if named(name) else "nofile"
            cat[(k, f)] += sz
            if not (k == "app" and f == "file"):
                tag = "node" if nd else "meta" if mt else "gc" if gc else ""
                detail[(k, f, part(lun, lba), fs or "-", tag, re.sub(r"[:/]\d+$", "", comm or "")[:16])] += sz
        print(f"  {'Read ' if d else 'Write'} {tot / 1e6:8.1f}MB  " + "  ".join(
            f"{k}+{f} {100 * v / tot:5.1f}%" for (k, f), v in sorted(cat.items())))
        for key, v in detail.most_common(7):
            if v / tot >= 0.005:
                print(f"      {100 * v / tot:5.1f}% {v / 1e6:7.1f}MB  {key}")
