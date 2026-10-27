#!/usr/bin/env python3
"""사용 로그 데이터셋 → 사용자 행동 모델 (wl/.private/usage.json)

  python3 wl/usage.py            # 처음이면 JSON(530MB) → parquet 변환부터

데이터셋은 앱이 앞(FG)·뒤(BG)로 갈 때의 이벤트만 있다. 화면 켜짐/꺼짐 이벤트는 없어서,
앞에 있는 앱이 GAP 초 이상 없으면 화면이 꺼진 것으로 본다.
출처·라이선스가 불명이라 결과는 .private 에만 두고 커밋·공개하지 않는다.
"""
import json
import re
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
PRIV = HERE / ".private"
SRC = Path.home() / "project/스마트폰 앱,웹 사용 로그 데이터셋/스마트폰_로그_데이터셋2.json"
EVENTS = PRIV / "usage_events.parquet"
OUT = PRIV / "usage.json"
GAP = 60          # 이만큼 앞에 앱이 없으면 화면 꺼짐
MIN_FG = 2        # 이보다 짧은 FG 는 깜빡임
CAP = 2 * 3600    # FG 하나의 최대 길이 (BG 이벤트가 빠진 경우 대비)

con = duckdb.connect()


def q(sql, *a):
    return con.execute(sql, a).fetchall()


def convert():
    PRIV.mkdir(exist_ok=True)
    con.execute(f"""copy (select pid, timestamp::bigint ts, coalesce(nullif(utcoffset, 0), 9) utcoffset, package_name pkg,
                         name, is_system_app sys, type
                         from read_json('{SRC}', format='array', maximum_object_size=1000000))
                    to '{EVENTS}' (format parquet)""")


def categorize():
    cm = json.loads((HERE / "catmap.json").read_text())
    rules = [(re.compile(p), c) for p, c in cm["rules"]]
    pk = [r[0] for r in q(f"select distinct pkg from '{EVENTS}'")]

    def cat(p):
        if p in cm["ignore"]:
            return "ignore"
        if p in cm["packages"]:
            return cm["packages"][p]
        return next((c for rx, c in rules if rx.search(p)), "other")

    con.execute("create table cat(pkg varchar, cat varchar)")
    con.executemany("insert into cat values (?, ?)", [(p, cat(p)) for p in pk])


def main():
    if not EVENTS.exists():
        convert()
    categorize()
    # FG 구간: 다음 FG/BG 이벤트까지. 끝 = min(다음 이벤트, CAP)
    con.execute(f"""create table iv as select pid, pkg, cat, st, least(en, st + {CAP * 1000}) en, utcoffset from (
        select e.pid, e.pkg, c.cat, e.type, e.ts st, e.utcoffset,
               lead(e.ts) over (partition by e.pid order by e.ts, e.type desc) en
        from '{EVENTS}' e join cat c using (pkg)
        where e.type in ('MOVE_TO_FOREGROUND', 'MOVE_TO_BACKGROUND'))
        where type = 'MOVE_TO_FOREGROUND' and en is not null and en - st >= {MIN_FG * 1000} and cat <> 'ignore'""")
    # 화면 세션: 앞 구간 끝과 다음 시작 사이가 GAP 초 이상이면 새 세션
    con.execute(f"""create table iv2 as select *, sum(brk) over (partition by pid order by st) sess from (
        select *, case when st - lag(en) over (partition by pid order by st) < {GAP * 1000} then 0 else 1 end brk from iv)""")
    con.execute("""create table ss as select pid, sess, min(st) st, max(en) en, any_value(utcoffset) uo, count(*) n
                   from iv2 group by 1, 2""")
    # 사용자·날짜
    con.execute("create table ud as select pid, ((st + uo * 3600000) // 86400000) dd, sum(en - st) / 60000.0 onmin, count(*) sessions from ss group by 1, 2")

    days = q("select count(*), count(distinct pid) from ud")[0]
    onmin = q("select quantile_cont(onmin, [0.25, 0.5, 0.75]), quantile_cont(sessions, [0.25, 0.5, 0.75]) from ud")[0]

    # 카테고리 시간 비중: 사용자마다 비중을 구해 평균 (헤비 유저 한 명이 좌우하지 않게) + 전체 합 기준
    share_user = dict(q("""select cat, avg(s) from (
        select pid, cat, sum(en - st) / sum(sum(en - st)) over (partition by pid) s from iv group by 1, 2) group by 1"""))
    share_all = dict(q("select cat, sum(en - st) / sum(sum(en - st)) over () from iv group by 1"))
    # 카테고리 방문: 같은 세션 안 연속 같은 카테고리를 하나로
    con.execute("""create table vis as select pid, sess, cat, min(st) st, max(en) en from (
        select *, sum(chg) over (partition by pid, sess order by st) g from (
          select *, case when cat = lag(cat) over (partition by pid, sess order by st) then 0 else 1 end chg from iv2))
        group by pid, sess, g, cat""")
    visits = {c: {"n": n, "p": [round(x, 1) for x in p]} for c, n, p in
              q("select cat, count(*), quantile_cont((en - st) / 1000.0, [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]) from vis group by 1")}
    trans = {}
    for a, b, n in q("""select cat, nxt, count(*) from (
            select cat, lead(cat) over (partition by pid, sess order by st) nxt from vis) where nxt is not null group by 1, 2"""):
        trans.setdefault(a, {})[b] = n
    for a in trans:
        t = sum(trans[a].values())
        trans[a] = {b: round(n / t, 4) for b, n in sorted(trans[a].items(), key=lambda x: -x[1])}
    first = dict(q("""select cat, count(*) / sum(count(*)) over () from (
        select cat, row_number() over (partition by pid, sess order by st) r from vis) where r = 1 group by 1"""))
    # 세션 길이·세션 사이(화면 꺼짐) 분포
    sess_p = q("select quantile_cont((en - st) / 1000.0, [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]) from ss")[0][0]
    off_p = q("""select quantile_cont(g, [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]) from (
        select (st - lag(en) over (partition by pid order by st)) / 1000.0 g from ss) where g is not null and g < 86400""")[0][0]
    # 시간대별: 하루 평균 화면 켜짐 분(세션 시작 시각 기준), 세션 시작 수
    nd = days[0]
    hourly = {h: {"onMin": round(m / nd, 2), "sessions": round(n / nd, 3)} for h, m, n in q("""
        select (((st + uo * 3600000) // 3600000) % 24)::int h, sum(en - st) / 60000.0, count(*) from ss group by 1 order by 1""")}
    hour_cat = {}
    for h, c, s in q("""select h, cat, s from (select (((st + utcoffset * 3600000) // 3600000) % 24)::int h, cat,
                        sum(en - st) / sum(sum(en - st)) over (partition by (((st + utcoffset * 3600000) // 3600000) % 24)::int) s
                        from iv group by 1, 2) order by 1"""):
        hour_cat.setdefault(h, {})[c] = round(s, 4)

    out = {
        "_note": "사용 로그 데이터셋(33명, 2018-10)에서 뽑은 값. 출처·라이선스 불명 → 커밋·공개 금지",
        "params": {"gapSec": GAP, "minFgSec": MIN_FG, "capSec": CAP},
        "userDays": days[0], "users": days[1],
        "perDay": {"onMinQ": [round(x, 1) for x in onmin[0]], "sessionsQ": [round(x, 1) for x in onmin[1]]},
        "categoryShareUserAvg": {k: round(v, 4) for k, v in sorted(share_user.items(), key=lambda x: -x[1])},
        "categoryShareAll": {k: round(v, 4) for k, v in sorted(share_all.items(), key=lambda x: -x[1])},
        "firstCategory": {k: round(v, 4) for k, v in sorted(first.items(), key=lambda x: -x[1])},
        "visitSecQ": visits, "transition": trans,
        "sessionSecQ": [round(x, 1) for x in sess_p], "offSecQ": [round(x, 1) for x in off_p],
        "quantiles": [0.1, 0.25, 0.5, 0.75, 0.9, 0.99],
        "hourly": hourly, "hourCategory": hour_cat,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {OUT}: {days[1]}명 {days[0]}일, 하루 화면 켜짐 분(25/50/75%) {out['perDay']['onMinQ']}, 세션 수 {out['perDay']['sessionsQ']}")
    for k, v in out["categoryShareUserAvg"].items():
        print(f"  {k:13} {100 * v:5.1f}%  (전체 합 기준 {100 * share_all.get(k, 0):5.1f}%)  방문 중앙값 {visits.get(k, {}).get('p', [0] * 3)[2]}초")
    print("  세션 길이(초) 분위수", out["sessionSecQ"], "\n  화면 꺼짐(초) 분위수", out["offSecQ"])


if __name__ == "__main__":
    main()
