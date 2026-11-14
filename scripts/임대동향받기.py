# -*- coding: utf-8 -*-
"""한국부동산원 R-ONE 상업용부동산 임대동향(상권별 임대료·공실률) 받기.

저장: analysis/{SIDO}/임대동향_상권.csv  (분기, 상가유형, 지표, 상권, 값, 단위)
환경변수: REB_KEY(필수), HIST_SIDO(기본 서울)
"""
import csv, json, os, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = os.environ.get("REB_KEY", "").strip()
SIDO = os.environ.get("HIST_SIDO", "서울")
TABLES = {   # (상가유형, 지표): [통계표 ID ...]  — 2024년 3분기~, 2026년 3분기~ 두 판을 이어 붙인다
    ("소규모", "임대료"): ["T248223134698125", "T269273143698159"],
    ("중대형", "임대료"): ["T244363134858603", "T269343143745470"],
    ("소규모", "공실률"): ["T241833134686576", "T262053143683833"],
    ("중대형", "공실률"): ["T249633134845544", "T267693143622612"],
}

def get(tid, page):
    q = urllib.parse.urlencode({"KEY": KEY, "Type": "json", "pIndex": page, "pSize": 1000, "STATBL_ID": tid, "DTACYCLE_CD": "QY"})
    with urllib.request.urlopen("https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do?" + q, timeout=60) as f:
        d = json.loads(f.read())
    if "SttsApiTblData" not in d:
        return 0, []
    head, body = d["SttsApiTblData"][0]["head"], d["SttsApiTblData"][1]["row"]
    return head[0]["list_total_count"], body

def main():
    if not KEY:
        raise SystemExit("REB_KEY가 없습니다.")
    out, seen = [], set()
    for (kind, item), ids in TABLES.items():
        for tid in ids:
            total, rows = get(tid, 1)
            page = 1
            while len(rows) < total:
                page += 1
                rows += get(tid, page)[1]
            for r in rows:
                full = r.get("CLS_FULLNM") or ""
                if not (full == SIDO or full.startswith(SIDO + ">") or full == "전국"):
                    continue
                key = (r["WRTTIME_IDTFR_ID"], kind, item, full)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"분기": r["WRTTIME_IDTFR_ID"], "분기설명": r["WRTTIME_DESC"], "상가유형": kind, "지표": item,
                            "상권": full.split(">")[-1], "상권전체": full, "값": round(float(r["DTA_VAL"]), 3) if r["DTA_VAL"] is not None else "",
                            "단위": r.get("UI_NM") or ""})
    out.sort(key=lambda x: (x["상가유형"], x["지표"], x["상권전체"], x["분기"]))
    p = ROOT / "analysis" / SIDO / "임대동향_상권.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"{SIDO} 임대동향 {len(out)}행, 상권 {len({x['상권전체'] for x in out})}곳, 분기 {sorted({x['분기'] for x in out})}")

if __name__ == "__main__":
    main()
