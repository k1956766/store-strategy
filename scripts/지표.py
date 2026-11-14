# -*- coding: utf-8 -*-
"""상권 동향 지표 계산(상권 동향 분석 3단계).

읽기: analysis/{SIDO}/월별_행정동_업종.csv, analysis/{SIDO}/가게.csv.gz  (집계.py 결과)
쓰기: analysis/{SIDO}/지표_업종.csv        시도 전체 업종별 지표
      analysis/{SIDO}/지표_행정동.csv      행정동별(업종 전체) 지표
      analysis/{SIDO}/지표_행정동_업종.csv  행정동 × 업종 지표와 신호
      data/trend/{SIDO}.json              홈페이지용 요약

기간(마지막 완결 월 E 기준)
  최근 12개월 R12 = E-11 ~ E,  최근 6개월 R6 = E-5 ~ E,  1년 전 같은 6개월 P6 = E-17 ~ E-12

지표
  개업률·폐업률·회전율(%/년) = R12 개업·폐업·(개업+폐업) ÷ R12 평균 영업 가게 × 100
  순증률(%) = (E 월말 가게 − R12 첫 달 월초 가게) ÷ R12 첫 달 월초 가게 × 100
  1년 생존율 = 관찰 시작~(E−12) 사이 개업 가게 중 365일 넘게 영업한 비율.
               행정동 단위는 표본이 작아 시도 업종 생존율 쪽으로 당겨서(경험적 베이즈, k=10) 보정
  특화도 LQ = (동 안 업종 비중) ÷ (시도 안 업종 비중), E 월말 기준
  뜨는 신호 z = (R6 개업 − 기대) ÷ √(기대+1),  기대 = 시도 업종 R6 개업 × (동 업종 이전 개업 ÷ 시도 업종 이전 개업)
              → 같은 업종이 시도 전체에서 늘어난 몫과 계절은 빼고, 그 동네에서 유독 몰린 정도만 본다
  폐업 경보 z = (R12 폐업 − 기대) ÷ √(기대+1),  기대 = 동 업종 평균 가게 × 시도 업종 폐업률
  q값: 포아송 꼬리확률을 벤자미니-호흐베르크로 보정. 홈페이지에는 q < 0.1(거짓 신호 10% 이하)만 올린다
환경변수: HIST_SIDO(기본 서울)
"""
import csv, gzip, json, math, os
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDO = os.environ.get("HIST_SIDO", "서울")
A = ROOT / "analysis" / SIDO
K_SURV = 10

def months_back(m, n):
    y, mo = int(m[:4]), int(m[5:7])
    t = y * 12 + mo - 1 - n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"

def pois_sf(k, lam):
    """P(X >= k), X ~ 포아송(lam)."""
    if k <= 0:
        return 1.0
    term = math.exp(-lam); cdf = term
    for i in range(1, int(k)):
        term *= lam / i; cdf += term
    return max(0.0, 1.0 - cdf)

def bh(ps):
    """벤자미니-호흐베르크 q값(여러 동네·업종을 한꺼번에 볼 때 우연히 걸리는 것을 줄인다)."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    q, prev = [0.0] * len(ps), 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * len(ps) / rank)
        q[i] = prev
    return q

def rate(num, den):
    return round(num / den * 100, 2) if den else None

def main():
    rows = list(csv.DictReader(open(A / "월별_행정동_업종.csv", encoding="utf-8-sig")))
    today = date.today()
    E = months_back(f"{today.year:04d}-{today.month:02d}", 1)          # 마지막 완결 월
    allm = sorted({r["월"] for r in rows})
    first = allm[0]
    R12 = [months_back(E, i) for i in range(11, -1, -1)]
    R6, P6 = R12[6:], [months_back(m, 12) for m in R12[6:]]
    BEFORE = [m for m in allm if m < R6[0]]                            # 뜨는 신호의 비교 기간
    nxt = months_back(E, -1)

    # (동, 업종, 월) → [월초, 개업, 폐업]
    cell = defaultdict(lambda: [0, 0, 0])
    names = {}
    for r in rows:
        k = (r["행정동코드"], r["업종"], r["월"])
        cell[k] = [int(r["월초_영업"]), int(r["개업"]), int(r["폐업"])]
        names[r["행정동코드"]] = r["행정동"]
    dongs = sorted(names)
    cats = sorted({r["업종"] for r in rows})

    def stock_start(d, g, m):  return cell[(d, g, m)][0] if (d, g, m) in cell else 0
    def end_stock(d, g):       # E 월말 = 다음 달 월초. 없으면 E 월초 + 개업 − 폐업
        if (d, g, nxt) in cell:
            return cell[(d, g, nxt)][0]
        s, o, c = cell.get((d, g, E), (0, 0, 0))
        return s + o - c
    def sums(d, g, ms):
        o = c = st = 0
        for m in ms:
            s, oo, cc = cell.get((d, g, m), (0, 0, 0))
            o += oo; c += cc; st += s
        return o, c, st / len(ms)

    # 동 × 업종 기본 집계
    base = {}
    for d in dongs:
        for g in cats:
            o12, c12, avg = sums(d, g, R12)
            o6, _, _ = sums(d, g, R6)
            op6, _, _ = sums(d, g, P6) if P6[0] >= first else (None, 0, 0)
            ob, _, _ = sums(d, g, BEFORE) if BEFORE else (0, 0, 0)
            s0, s1 = stock_start(d, g, R12[0]), end_stock(d, g)
            if not (o12 or c12 or s0 or s1):
                continue
            base[(d, g)] = dict(o12=o12, c12=c12, avg=avg, o6=o6, op6=op6, ob=ob, s0=s0, s1=s1)

    # 시도 업종 합계
    city = defaultdict(lambda: defaultdict(float))
    for (d, g), v in base.items():
        for k, x in v.items():
            if x is not None:
                city[g][k] += x
    total_end = sum(v["s1"] for v in city.values())
    dong_end = defaultdict(float)
    for (d, g), v in base.items():
        dong_end[d] += v["s1"]

    # 1년 생존율(가게 단위)
    cut = date.fromisoformat(months_back(E, 12) + "-01")
    cut_end = date(cut.year + (cut.month == 12), cut.month % 12 + 1, 1)     # E−12 월말 다음날
    surv = defaultdict(lambda: [0, 0])          # (동, 업종) → [개업, 1년 생존]
    for r in csv.DictReader(gzip.open(A / "가게.csv.gz", "rt", encoding="utf-8")):
        if r["제외"] or not r["행정동코드"] or not r["LCPMT_YMD"]:
            continue
        o = date.fromisoformat(r["LCPMT_YMD"][:10])
        if not (date.fromisoformat(first + "-01") <= o < cut_end):
            continue
        c = date.fromisoformat(r["CLSBIZ_YMD"][:10]) if r["CLSBIZ_YMD"] else None
        alive = c is None or (c - o).days >= 365
        for key in ((r["행정동코드"], r["업종"]), ("*", r["업종"]), (r["행정동코드"], "*"), ("*", "*")):
            surv[key][0] += 1; surv[key][1] += alive

    def surv_rate(d, g):
        n, s = surv.get((d, g), (0, 0))
        n0, s0 = surv.get(("*", g), (0, 0))
        if not n0:
            return None, n
        p0 = s0 / n0
        if d == "*":
            return round(p0 * 100, 1), n
        return round((s + K_SURV * p0) / (n + K_SURV) * 100, 1), n

    # ── 시도 업종별
    out_cat = []
    for g in cats:
        v = city[g]
        yoy = rate(v["o6"] - v["op6"], v["op6"]) if v.get("op6") else None
        sr, sn = surv_rate("*", g)
        out_cat.append({"업종": g, "가게수": int(v["s1"]), "개업_12개월": int(v["o12"]), "폐업_12개월": int(v["c12"]),
                        "개업률": rate(v["o12"], v["avg"]), "폐업률": rate(v["c12"], v["avg"]),
                        "회전율": rate(v["o12"] + v["c12"], v["avg"]), "순증률": rate(v["s1"] - v["s0"], v["s0"]),
                        "개업_최근6개월": int(v["o6"]), "개업_1년전6개월": int(v["op6"]) if v.get("op6") else "",
                        "개업_전년비": yoy, "1년생존율": sr, "생존표본": sn})
    out_cat.sort(key=lambda x: -x["가게수"])

    # ── 행정동별(업종 전체)
    out_dong = []
    allc = defaultdict(lambda: defaultdict(float))
    for (d, g), v in base.items():
        for k in ("o12", "c12", "avg", "s0", "s1"):
            allc[d][k] += v[k]
    cty = {k: sum(allc[d][k] for d in allc) for k in ("o12", "c12", "avg")}
    city_turn = (cty["o12"] + cty["c12"]) / cty["avg"]
    for d in dongs:
        v = allc[d]
        if not v["avg"]:
            continue
        exp = v["avg"] * city_turn
        sr, sn = surv_rate(d, "*") if surv.get((d, "*")) else (None, 0)
        if surv.get((d, "*")):
            n, s = surv[(d, "*")]; n0, s0 = surv[("*", "*")]
            sr = round((s + K_SURV * s0 / n0) / (n + K_SURV) * 100, 1)
        out_dong.append({"행정동코드": d, "행정동": names[d], "가게수": int(v["s1"]),
                         "개업률": rate(v["o12"], v["avg"]), "폐업률": rate(v["c12"], v["avg"]),
                         "회전율": rate(v["o12"] + v["c12"], v["avg"]), "순증률": rate(v["s1"] - v["s0"], v["s0"]),
                         "교체_z": round((v["o12"] + v["c12"] - exp) / math.sqrt(exp + 1), 2),
                         "1년생존율": sr, "생존표본": sn})

    # ── 행정동 × 업종
    out_dg = []
    for (d, g), v in base.items():
        c = city[g]
        lq = (v["s1"] / dong_end[d]) / (c["s1"] / total_end) if dong_end[d] and c["s1"] else None
        exp_up = c["o6"] * ((v["ob"] + 0.5) / (c["ob"] + 0.5 * len(dongs))) if c["ob"] else None
        z_up = (v["o6"] - exp_up) / math.sqrt(exp_up + 1) if exp_up is not None else None
        exp_cl = v["avg"] * (c["c12"] / c["avg"]) if c["avg"] else None
        z_cl = (v["c12"] - exp_cl) / math.sqrt(exp_cl + 1) if exp_cl is not None else None
        sr, sn = surv_rate(d, g)
        out_dg.append({"행정동코드": d, "행정동": names[d], "업종": g, "가게수": v["s1"],
                       "개업_12개월": v["o12"], "폐업_12개월": v["c12"],
                       "개업률": rate(v["o12"], v["avg"]), "폐업률": rate(v["c12"], v["avg"]),
                       "순증": v["s1"] - v["s0"], "특화도_LQ": round(lq, 2) if lq else None,
                       "개업_최근6개월": v["o6"], "뜨는신호_z": round(z_up, 2) if z_up is not None else None,
                       "폐업경보_z": round(z_cl, 2) if z_cl is not None else None,
                       "1년생존율": sr, "생존표본": sn,
                       "_p_up": pois_sf(v["o6"], exp_up) if exp_up is not None else 1.0,
                       "_p_cl": pois_sf(v["c12"], exp_cl) if exp_cl is not None else 1.0})
    for key, col in (("_p_up", "뜨는신호_q"), ("_p_cl", "폐업경보_q")):
        qs = bh([x[key] for x in out_dg])
        for x, q in zip(out_dg, qs):
            x[col] = round(q, 4)
            del x[key]

    def write(name, data):
        with open(A / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader(); w.writerows(data)
    write("지표_업종.csv", out_cat)
    write("지표_행정동.csv", out_dong)
    write("지표_행정동_업종.csv", sorted(out_dg, key=lambda x: (x["행정동코드"], -x["가게수"])))

    # ── 홈페이지용 요약
    rising = [x for x in out_dg if x["뜨는신호_q"] < 0.1 and x["개업_최근6개월"] >= 3 and x["업종"] != "기타"]
    closing = [x for x in out_dg if x["폐업경보_q"] < 0.1 and x["폐업_12개월"] >= 5 and x["업종"] != "기타"]
    churn = sorted([x for x in out_dong if x["가게수"] >= 50], key=lambda x: -x["교체_z"])
    summary = {
        "시도": SIDO, "기준월": E, "최근12개월": [R12[0], R12[-1]], "최근6개월": [R6[0], R6[-1]],
        "업종": out_cat,
        "뜨는_동네업종": sorted(rising, key=lambda x: -x["뜨는신호_z"])[:60],
        "폐업경보": sorted(closing, key=lambda x: -x["폐업경보_z"])[:60],
        "교체_빈발": churn[:30], "교체_적음": churn[-15:][::-1],
        "행정동": {x["행정동코드"]: x for x in out_dong},
        "행정동_업종": defaultdict(list),
    }
    for x in sorted(out_dg, key=lambda x: -x["가게수"]):
        if x["가게수"] >= 1 or x["개업_12개월"]:
            summary["행정동_업종"][x["행정동코드"]].append(
                [x["업종"], x["가게수"], x["개업_12개월"], x["폐업_12개월"], x["특화도_LQ"], x["뜨는신호_z"], x["폐업경보_z"], x["1년생존율"]])
    (ROOT / "data" / "trend").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "trend" / f"{SIDO}.json").write_text(json.dumps(summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{SIDO} 기준월 {E}: 업종 {len(out_cat)}, 행정동 {len(out_dong)}, 동×업종 {len(out_dg)}, "
          f"뜨는 신호 {len(rising)}, 폐업 경보 {len(closing)}")

if __name__ == "__main__":
    main()
