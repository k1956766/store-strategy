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

_FR = {}
def is_franchise(name):
    """상호가 프랜차이즈 사전(직접 정리한 브랜드 + 공정위 가맹 브랜드)과 맞으면 True."""
    if name in _FR:
        return _FR[name]
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import 업종분류 as U
    low = (name or "").lower().replace(" ", "")
    hit = any(b.replace(" ", "") in low for b, _ in U.BRAND_INDEX) or bool(U.ftc_lookup(name or ""))
    _FR[name] = hit
    return hit

TLAB = {"00_06": "심야(0~6시)", "06_11": "아침(6~11시)", "11_14": "점심(11~14시)", "14_17": "오후(14~17시)", "17_21": "저녁(17~21시)", "21_24": "밤(21~24시)"}
ALAB = {"10": "10대", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대 이상"}
SPK = ["식료품", "의류", "생활용품", "의료", "교통", "교육", "유흥", "여가문화", "기타", "음식"]
FCK = ["지하철역", "버스정류장", "대학", "초중고", "병원", "관공서", "은행", "백화점", "슈퍼마켓", "극장", "숙박시설"]

def people(out_dong, g_dong):
    """서울시 상권분석서비스 행정동 자료(analysis/{SIDO}/상권분석_행정동.csv)를 동·구·서울 단위 사람·돈 지표로."""
    src = A / "상권분석_행정동.csv"
    if not src.exists():
        return None
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    num = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else 0.0
    shops = {x["행정동코드"]: x["가게수"] for x in out_dong}
    gshops = {x["행정동코드"]: x["가게수"] for x in g_dong}
    acc = {"dong": defaultdict(lambda: defaultdict(float)), "gu": defaultdict(lambda: defaultdict(float)), "서울": defaultdict(float)}
    chg = {"dong": {}, "gu": defaultdict(lambda: defaultdict(float))}
    for r in rows:
        c = r["행정동코드"]
        vals = {k: num(r, k) for k in r if k not in ("행정동코드", "이름", "변화")}
        vals["아파트시가x세대"] = vals.get("아파트시가", 0) * vals.get("아파트세대", 0)
        for tgt in (acc["dong"][c], acc["gu"][c[:5]], acc["서울"]):
            for k, v in vals.items():
                tgt[k] += v
        if r.get("변화"):
            chg["dong"][c] = r["변화"]
            chg["gu"][c[:5]][r["변화"]] += max(1.0, vals.get("매출점포", 0))

    def pack(a, shop):
        if not a:
            return None
        o = {"유동": a["유동"], "상주": a["상주"], "가구": a["가구"], "직장": a["직장"] or None, "지출": a["지출"] or None,
             "유동시간": {TLAB[k]: a[f"유동_t{k}"] for k in TLAB}, "유동연령": {ALAB[k]: a[f"유동_a{k}"] for k in ALAB},
             "상주연령": {ALAB[k]: a[f"상주_a{k}"] for k in ALAB}, "직장연령": {ALAB[k]: a[f"직장_a{k}"] for k in ALAB},
             "유동주말": a["유동_주말"] / a["유동"] if a["유동"] else None,
             "지출구성": {k: a[f"지출_{k}"] for k in SPK}, "집객": {k: a[f"집객_{k}"] for k in FCK}, "집객시설": a["집객시설"],
             "아파트단지": a["아파트단지"], "아파트세대": a["아파트세대"],
             "아파트시가": a["아파트시가x세대"] / a["아파트세대"] if a["아파트세대"] else None,
             "매출": a["매출"], "점포당매출": a["매출"] / a["매출점포"] if a["매출점포"] >= 5 else None,
             "매출주말": a["매출_주말"] / a["매출"] if a["매출"] else None, "매출저녁": a["매출_저녁"] / a["매출"] if a["매출"] else None,
             "가게": shop}
        return {k: (round(v, 4) if isinstance(v, float) else v) if not isinstance(v, dict) else {kk: round(vv, 1) for kk, vv in v.items()} for k, v in o.items()}

    res = {"dong": {}, "gu": {}}
    for c, a in acc["dong"].items():
        o = pack(a, shops.get(c))
        if o:
            o["변화"] = chg["dong"].get(c)
            res["dong"][c] = o
    for c, a in acc["gu"].items():
        o = pack(a, gshops.get(c))
        if o:
            m = chg["gu"].get(c)
            o["변화"] = max(m, key=m.get) if m else None
            res["gu"][c] = o
    S = pack(acc["서울"], sum(shops.values()))
    S["가게당유동"] = S["유동"] / S["가게"] if S["가게"] else None
    res["서울"] = S
    return res

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

def compute(level, rows, E, allm, first, R12, R6, P6, BEFORE, nxt, dong_code_of, dong_area):
    """level='행정동'이면 그대로, '시군구'면 행정동을 구로 묶어서 같은 지표를 낸다."""
    def unit(code, name):
        if level == "행정동":
            return code, name
        return code[:5], name.split(" ")[0]
    # (동, 업종, 월) → [월초, 개업, 폐업]
    cell = defaultdict(lambda: [0, 0, 0])
    names = {}
    for r in rows:
        u, un = unit(r["행정동코드"], r["행정동"])
        k = (u, r["업종"], r["월"])
        x = cell[k]
        x[0] += int(r["월초_영업"]); x[1] += int(r["개업"]); x[2] += int(r["폐업"])
        names[u] = un
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
        u = unit(r["행정동코드"], r["행정동"])[0]
        for key in ((u, r["업종"]), ("*", r["업종"]), (u, "*"), ("*", "*")):
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
                       "개업_최근6개월": v["o6"], "개업_기대": round(exp_up, 1) if exp_up is not None else None,
                       "폐업_기대": round(exp_cl, 1) if exp_cl is not None else None, "뜨는신호_z": round(z_up, 2) if z_up is not None else None,
                       "폐업경보_z": round(z_cl, 2) if z_cl is not None else None,
                       "1년생존율": sr, "생존표본": sn,
                       "_p_up": pois_sf(v["o6"], exp_up) if exp_up is not None else 1.0,
                       "_p_cl": pois_sf(v["c12"], exp_cl) if exp_cl is not None else 1.0})
    for key, col in (("_p_up", "뜨는신호_q"), ("_p_cl", "폐업경보_q")):
        qs = bh([x[key] for x in out_dg])
        for x, q in zip(out_dg, qs):
            x[col] = round(q, 4)
            del x[key]

    # ── 보조 자료(있으면): R-ONE 상권 임대료·공실률(상권 → 행정동 근사), 나이스 학원
    rent = {}
    rp, mp = A / "임대동향_상권.csv", ROOT / "scripts" / f"상권_행정동_{SIDO}.json"
    if rp.exists() and mp.exists():
        rr = list(csv.DictReader(open(rp, encoding="utf-8-sig")))
        mapping = {k: v for k, v in json.loads(mp.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        val = {(r["상가유형"], r["지표"], r["상권"], r["분기"]): float(r["값"]) for r in rr if r["값"] != ""}
        last = max(r["분기"] for r in rr)
        prev = f"{int(last[:4]) - 1}{last[4:]}"
        by_unit = defaultdict(list)                 # 단위 → [상권 ...]
        for area, dlist in mapping.items():
            for dn in dlist:
                u = unit(dong_code_of.get(dn, ""), dn)[0] if dn in dong_code_of else None
                if u and area not in by_unit[u]:
                    by_unit[u].append(area)
        for u, areas in by_unit.items():
            if level == "행정동":
                areas = areas[:1]                      # 동은 가장 가까운 상권 하나
            vals = [(val.get(("소규모", "임대료", a, last)), val.get(("소규모", "임대료", a, prev)), val.get(("소규모", "공실률", a, last))) for a in areas]
            vals = [v for v in vals if v[0]]
            if not vals:
                continue
            r_now = sum(v[0] for v in vals) / len(vals)
            r_prev = sum(v[1] for v in vals if v[1]) / max(1, sum(1 for v in vals if v[1]))
            vac = [v[2] for v in vals if v[2] is not None]
            rent[u] = {"임대상권": "·".join(areas), "임대료_소규모": round(r_now, 1),
                       "임대료_전년비": rate(r_now - r_prev, r_prev) if r_prev else None,
                       "공실률_소규모": round(sum(vac) / len(vac), 2) if vac else None, "임대분기": last}
    for x in out_dong:
        x.update(rent.get(x["행정동코드"], {"임대상권": "", "임대료_소규모": None, "임대료_전년비": None, "공실률_소규모": None, "임대분기": ""}))
    aca = defaultdict(lambda: [0, 0])
    ap = A / "학원_행정동.csv"
    if ap.exists():
        for r in csv.DictReader(open(ap, encoding="utf-8-sig")):
            u = unit(r["행정동코드"], r["행정동"])[0]
            aca[u][0] += int(r["개원"]); aca[u][1] += int(r["최근12개월_신규"])
    for x in out_dong:
        x["학원"], x["학원_최근12개월_신규"] = aca[x["행정동코드"]] if ap.exists() else (None, None)
    # 면적(㎢)·점포 밀도, 음식점 중 프랜차이즈 비중(지금 영업 중 가게 기준)
    area = defaultdict(float)
    for dc, a in dong_area.items():
        area[unit(dc, "")[0]] += a
    fr = defaultdict(lambda: [0, 0])
    for r in csv.DictReader(gzip.open(A / "가게.csv.gz", "rt", encoding="utf-8")):
        if r["제외"] or not r["행정동코드"] or r["CLSBIZ_YMD"] or r["자료"] not in ("휴게음식점", "일반음식점"):
            continue
        u = unit(r["행정동코드"], r["행정동"])[0]
        fr[u][0] += 1
        fr[u][1] += is_franchise(r["BPLC_NM"])
    for x in out_dong:
        a = area.get(x["행정동코드"])
        x["면적_km2"] = round(a, 3) if a else None
        x["점포밀도"] = round(x["가게수"] / a, 1) if a else None
        n, f = fr[x["행정동코드"]]
        x["프랜차이즈비중"] = round(f / n * 100, 1) if n >= 20 else None

    rising = [x for x in out_dg if x["뜨는신호_q"] < 0.1 and x["개업_최근6개월"] >= 3 and x["업종"] != "기타"]
    closing = [x for x in out_dg if x["폐업경보_q"] < 0.1 and x["폐업_12개월"] >= 5 and x["업종"] != "기타"]
    return out_cat, out_dong, out_dg, rising, closing, cty

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
    dong_code_of = {}
    for r in rows:
        dong_code_of[r["행정동"]] = r["행정동코드"]
    # 행정동 면적(㎢): 경계를 중부원점(EPSG:5186)으로 바꿔 계산
    dong_area = {}
    bp = ROOT / "data" / "boundary" / f"행정동_{SIDO}.geojson"
    if bp.exists():
        from shapely.geometry import shape
        from shapely.ops import transform  # noqa
        from pyproj import Transformer
        tf = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True).transform
        for f in json.loads(bp.read_text(encoding="utf-8"))["features"]:
            dong_area[f["properties"]["adm_cd2"]] = transform(tf, shape(f["geometry"])).area / 1e6
    args = (rows, E, allm, first, R12, R6, P6, BEFORE, nxt, dong_code_of, dong_area)
    out_cat, out_dong, out_dg, rising, closing, cty = compute("행정동", *args)
    _, g_dong, g_dg, g_rise, g_close, _ = compute("시군구", *args)

    def write(name, data):
        with open(A / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader(); w.writerows(data)
    write("지표_업종.csv", out_cat)
    write("지표_행정동.csv", out_dong)
    write("지표_행정동_업종.csv", sorted(out_dg, key=lambda x: (x["행정동코드"], -x["가게수"])))
    write("지표_시군구.csv", g_dong)
    write("지표_시군구_업종.csv", sorted(g_dg, key=lambda x: (x["행정동코드"], -x["가게수"])))

    # ── 홈페이지용 요약
    churn = sorted([x for x in out_dong if x["가게수"] >= 50], key=lambda x: -x["교체_z"])
    summary = {
        "시도": SIDO, "기준월": E, "최근12개월": [R12[0], R12[-1]], "최근6개월": [R6[0], R6[-1]],
        "업종": out_cat,
        "서울_전체": {"개업률": rate(cty["o12"], cty["avg"]), "폐업률": rate(cty["c12"], cty["avg"]),
                    "회전율": rate(cty["o12"] + cty["c12"], cty["avg"])},
        "뜨는_동네업종": sorted(rising, key=lambda x: -x["뜨는신호_z"])[:60],
        "폐업경보": sorted(closing, key=lambda x: -x["폐업경보_z"])[:60],
        "교체_빈발": churn[:30], "교체_적음": churn[-15:][::-1],
        "행정동": {x["행정동코드"]: x for x in out_dong},
        "행정동_업종": defaultdict(list),
        "시군구": {"지역": {x["행정동코드"]: x for x in g_dong}, "지역_업종": defaultdict(list),
                 "뜨는": sorted(g_rise, key=lambda x: -x["뜨는신호_z"])[:60],
                 "경보": sorted(g_close, key=lambda x: -x["폐업경보_z"])[:60],
                 "교체_빈발": sorted(g_dong, key=lambda x: -x["교체_z"])},
    }
    summary["인구"] = people(out_dong, g_dong)
    for x in sorted(g_dg, key=lambda x: -x["가게수"]):
        summary["시군구"]["지역_업종"][x["행정동코드"]].append(
            [x["업종"], x["가게수"], x["개업_12개월"], x["폐업_12개월"], x["특화도_LQ"], x["뜨는신호_z"], x["폐업경보_z"], x["1년생존율"]])
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
