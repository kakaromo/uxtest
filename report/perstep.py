import json,glob,sys,duckdb
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; AR=Path.home()/'.agent-standalone/archive/jobs'
for sid in sys.argv[1:]:
    run=sorted(f for f in glob.glob(str(ROOT/'runs'/sid/'*.json')) if not f.endswith('-dry.json'))[-1]
    r=json.load(open(run))['results'][0]
    for tj in r['traceJobs']:
        pq=glob.glob(str(AR/'*'/'trace'/tj['traceJobId']/'result_fsio_ufs.parquet'))[0]
        bs=[b for b in r['stepBoundaries'] if b['repeatIndex']==tj['repeatIndex'] and 'cold start' in b['label']]
        out=[]
        for b in bs:
            t0=b['startedMono']; t1=t0+ (b['finishedAt']-b['startedAt'])/1000
            mb=duckdb.sql(f"select sum(size)/1e6 from read_parquet('{pq}') where action='send_req' and opcode in (40,136) and time>={t0} and time<{t1}").fetchone()[0] or 0
            out.append(f"{b['label'].replace(' cold start','')}:{mb:.0f}")
        print(sid, tj['repeatIndex'], ' '.join(out))
