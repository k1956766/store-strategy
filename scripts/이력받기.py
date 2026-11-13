# -*- coding: utf-8 -*-
"""분석용 개업·폐업 이력 받기(상권 동향 분석 1단계).

지자체마다 두 묶음을 받는다.
  영업: 지금 영업 중인 가게 전부(SALS_STTS_CD=01) — 어느 날짜의 '영업 중 가게 수'(분모)를 되살리는 데 쓴다.
  폐업: 폐업일이 START 이후인 가게(CLSBIZ_YMD >= START). 폐업일 조건은 'YYYY-MM-DD' 형식이어야 맞게 걸린다.
두 묶음을 합치면 START 이후 개업한 가게와, START 이후 어느 날짜의 영업 중 가게를 모두 복원할 수 있다.

저장: history/{지자체코드}/{자료}_{영업|폐업}.csv.gz  (이미 있으면 건너뜀 → 끊겨도 다음 실행이 이어 받음)
환경변수: DATA_GO_KR_KEY(필수), HIST_SIDO(기본 서울), HIST_START(기본 2025-01-01), HIST_BUDGET_MIN(기본 300)
"""
import csv, gzip, json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
SIDO = os.environ.get("HIST_SIDO", "서울")
START = os.environ.get("HIST_START", "2025-01-01")
BUDGET = float(os.environ.get("HIST_BUDGET_MIN", 300))
WORKERS = 8
DATASETS = {"휴게음식점": "rest_cafes", "일반음식점": "general_restaurants"}
FIELDS = ["MNG_NO", "BPLC_NM", "BZSTAT_SE_NM", "LCPMT_YMD", "SALS_STTS_NM", "DTL_SALS_STTS_NM", "CLSBIZ_YMD",
          "ROAD_NM_ADDR", "LOTNO_ADDR", "CRD_INFO_X", "CRD_INFO_Y", "FCLT_TOTAL_SCL", "OPN_ATMY_GRP_CD",
          "LAST_MDFCN_PNT", "DAT_UPDT_PNT"]
T0 = time.time()

def over():
    return (time.time() - T0) / 60 > BUDGET

def call(ds, cond, page):
    p = {"serviceKey": KEY, "pageNo": page, "numOfRows": 100, "returnType": "json"}
    p.update(cond)
    url = f"https://apis.data.go.kr/1741000/{ds}/info?" + urllib.parse.urlencode(p)
    for attempt in range(6):
        try:
            b = json.load(urllib.request.urlopen(url, timeout=150))
            if "response" in b:
                body = b["response"]["body"]
                items = body["items"]["item"] if body.get("items") else []
                return int(body.get("totalCount", 0)), ([items] if isinstance(items, dict) else items)
        except Exception:
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"응답 실패 {ds} {cond} p{page}")

def fetch_all(ds, cond, pool):
    total, first = call(ds, cond, 1)
    pages = (total + 99) // 100
    rows = list(first)
    if pages > 1:
        for _, items in pool.map(lambda pg: call(ds, cond, pg), range(2, pages + 1)):
            rows += items
    # 같은 관리번호가 페이지 경계에서 겹칠 수 있어 정리
    uniq = {r["MNG_NO"]: r for r in rows}
    return total, list(uniq.values())

def main():
    if not KEY:
        raise SystemExit("DATA_GO_KR_KEY가 없습니다.")
    regions = json.loads((ROOT / "scripts" / "지자체_수도권.json").read_text(encoding="utf-8"))
    codes = [c for c, n in regions.items() if n.startswith(SIDO)]
    print(f"{SIDO} {len(codes)}개 지자체, 폐업 기준일 {START}")
    jobs = [(c, label, ds, kind) for c in codes for label, ds in DATASETS.items() for kind in ("폐업", "영업")]
    done = skipped = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for code, label, ds, kind in jobs:
            out = ROOT / "history" / code / f"{label}_{kind}.csv.gz"
            if out.exists():
                continue
            if over():
                skipped += 1
                continue
            cond = {"cond[OPN_ATMY_GRP_CD::EQ]": code}
            cond.update({"cond[SALS_STTS_CD::EQ]": "01"} if kind == "영업" else {"cond[CLSBIZ_YMD::GTE]": START})
            t = time.time()
            try:
                total, rows = fetch_all(ds, cond, pool)
            except Exception as e:
                print(f"  실패 {regions[code]} {label} {kind}: {e}")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            tmp.replace(out)
            done += 1
            print(f"  {regions[code]} {label} {kind}: {len(rows)}/{total}건 ({time.time() - t:.0f}초, 누적 {(time.time() - T0) / 60:.0f}분)", flush=True)
    left = sum(1 for c, l, d, k in jobs if not (ROOT / "history" / c / f"{l}_{k}.csv.gz").exists())
    print(f"이번 실행 {done}개 받음, 남은 묶음 {left}개 ({(time.time() - T0) / 60:.0f}분)")

if __name__ == "__main__":
    main()
