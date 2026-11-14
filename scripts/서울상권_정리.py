# -*- coding: utf-8 -*-
"""서울시 상권분석서비스 행정동 자료(PC에서 받은 원본)를 최신 분기 한 줄씩으로 줄여 저장.

python scripts/서울상권_정리.py <원본 폴더>   → analysis/서울/상권분석_행정동.csv
원본: 유동인구·상주인구·소득소비·집객시설·아파트_행정동_*.csv, 직장인구·상권변화지표·추정매출_행정동_전체.csv, 점포_행정동_{최신}.csv
행정동코드는 우리 경계(adm_cd2, 10자리)에 맞춰 8자리 뒤에 '00'을 붙인다.
"""
import csv, glob, os, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1])

def latest(pattern):
    files = sorted(glob.glob(str(SRC / pattern)))
    rows = list(csv.DictReader(open(files[-1], encoding="utf-8-sig")))
    q = max(r["STDR_YYQU_CD"] for r in rows)
    return q, [r for r in rows if r["STDR_YYQU_CD"] == q]

f = lambda r, k: float(r.get(k) or 0)
out = defaultdict(dict)
qs = {}

qs["유동"], rows = latest("유동인구_행정동_*.csv")
for r in rows:      # 요일 7개 칸의 합이 총계 → 일평균은 ÷7
    o = out[r["ADSTRD_CD"]]
    o["이름"] = r["ADSTRD_CD_NM"]
    o["유동"] = f(r, "TOT_FLPOP_CO") / 7
    for k in ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24"):
        o[f"유동_t{k}"] = f(r, f"TMZON_{k}_FLPOP_CO") / 7
    o["유동_주말"] = (f(r, "SAT_FLPOP_CO") + f(r, "SUN_FLPOP_CO")) / 7
    for a in ("10", "20", "30", "40", "50", "60_ABOVE"):
        o[f"유동_a{a[:2]}"] = f(r, f"AGRDE_{a}_FLPOP_CO") / 7

qs["상주"], rows = latest("상주인구_행정동_*.csv")
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["상주"] = f(r, "TOT_REPOP_CO"); o["가구"] = f(r, "TOT_HSHLD_CO"); o["아파트가구"] = f(r, "APT_HSHLD_CO")
    for a in ("10", "20", "30", "40", "50", "60_ABOVE"):
        o[f"상주_a{a[:2]}"] = f(r, f"AGRDE_{a}_REPOP_CO")

qs["직장"], rows = latest("직장인구_행정동_*.csv")
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["직장"] = f(r, "TOT_WRC_POPLTN_CO")
    for a in ("10", "20", "30", "40", "50", "60_ABOVE"):
        o[f"직장_a{a[:2]}"] = f(r, f"AGRDE_{a}_WRC_POPLTN_CO")

qs["지출"], rows = latest("소득소비_행정동_*.csv")
SP = {"식료품": "FDSTFFS", "의류": "CLTHS_FTWR", "생활용품": "LVSPL", "의료": "MCP", "교통": "TRNSPORT", "교육": "EDC",
      "유흥": "PLESR", "여가문화": "LSR_CLTUR", "기타": "ETC", "음식": "FD"}
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["지출"] = f(r, "EXPNDTR_TOTAMT")
    for k, c in SP.items():
        o[f"지출_{k}"] = f(r, f"{c}_EXPNDTR_TOTAMT")

qs["집객"], rows = latest("집객시설_행정동_*.csv")
FC = {"지하철역": ["SUBWAY_STATN_CO"], "버스정류장": ["BUS_STTN_CO"], "대학": ["UNIV_CO"], "초중고": ["ELESCH_CO", "MSKUL_CO", "HGSCHL_CO"],
      "병원": ["GEHSPT_CO", "GNRL_HSPTL_CO"], "관공서": ["PBLOFC_CO"], "은행": ["BANK_CO"], "백화점": ["DRTS_CO"], "슈퍼마켓": ["SUPMK_CO"],
      "극장": ["THEAT_CO"], "숙박시설": ["STAYNG_FCLTY_CO"]}
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["집객시설"] = f(r, "VIATR_FCLTY_CO")
    for k, cs in FC.items():
        o[f"집객_{k}"] = sum(f(r, c) for c in cs)

qs["아파트"], rows = latest("아파트_행정동_*.csv")
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["아파트단지"] = f(r, "APT_HSMP_CO")
    o["아파트세대"] = sum(f(r, c) for c in ("AE_66_SQMT_BELO_HSHLD_CO", "AE_66_SQMT_HSHLD_CO", "AE_99_SQMT_HSHLD_CO", "AE_132_SQMT_HSHLD_CO", "AE_165_SQMT_HSHLD_CO"))
    o["아파트시가"] = f(r, "AVRG_MKTC")

qs["변화"], rows = latest("상권변화지표_행정동_*.csv")
for r in rows:
    o = out[r["ADSTRD_CD"]]
    o["변화"] = r["TRDAR_CHNGE_IX_NM"]; o["운영개월"] = f(r, "OPR_SALE_MT_AVRG"); o["폐업개월"] = f(r, "CLS_SALE_MT_AVRG")

# 추정매출(용량이 커서 최신 분기만 흘려 읽음) + 같은 분기 점포 수
sales = defaultdict(lambda: defaultdict(float))
qmax = ""
with open(SRC / "추정매출_행정동_전체.csv", encoding="utf-8-sig") as fp:
    for r in csv.DictReader(fp):
        qmax = max(qmax, r["STDR_YYQU_CD"])
qs["매출"] = qmax
with open(SRC / "추정매출_행정동_전체.csv", encoding="utf-8-sig") as fp:
    for r in csv.DictReader(fp):
        if r["STDR_YYQU_CD"] != qmax:
            continue
        s = sales[r["ADSTRD_CD"]]
        s["매출"] += f(r, "THSMON_SELNG_AMT"); s["매출_주말"] += f(r, "WKEND_SELNG_AMT")
        s["매출_저녁"] += f(r, "TMZON_17_21_SELNG_AMT") + f(r, "TMZON_21_24_SELNG_AMT")
        s["업종:" + r["SVC_INDUTY_CD"]] = 1
stor_files = sorted(glob.glob(str(SRC / f"점포_행정동_{qmax}.csv"))) or sorted(glob.glob(str(SRC / "점포_행정동_*.csv")))
stores = defaultdict(float)
for r in csv.DictReader(open(stor_files[-1], encoding="utf-8-sig")):
    if ("업종:" + r["SVC_INDUTY_CD"]) in sales[r["ADSTRD_CD"]]:
        stores[r["ADSTRD_CD"]] += f(r, "STOR_CO")
for c, s in sales.items():
    o = out[c]
    o["매출"] = s["매출"]; o["매출_주말"] = s["매출_주말"]; o["매출_저녁"] = s["매출_저녁"]; o["매출점포"] = stores.get(c, 0)

cols = sorted({k for o in out.values() for k in o})
dst = ROOT / "analysis" / "서울" / "상권분석_행정동.csv"
with open(dst, "w", encoding="utf-8-sig", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["행정동코드"] + cols)
    for c in sorted(out):
        w.writerow([c + "00"] + [round(out[c][k], 1) if isinstance(out[c].get(k), float) else out[c].get(k, "") for k in cols])
print("분기:", qs, "행정동", len(out), "→", dst)
