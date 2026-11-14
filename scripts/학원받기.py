# -*- coding: utf-8 -*-
"""나이스 학원·교습소 정보 받기(인허가 API에 없는 학원 업종 보완).

저장: analysis/{SIDO}/학원.csv.gz          학원 단위(분야, 개설일, 상태, 행정동)
      analysis/{SIDO}/학원_행정동.csv      행정동 × 분야: 현재 개원 수, 최근 12개월 신규
환경변수: NEIS_KEY(필수), KAKAO_REST_KEY(주소 → 좌표), HIST_SIDO(기본 서울)
"""
import csv, gzip, json, os, re, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = os.environ.get("NEIS_KEY", "").strip()
KAKAO = os.environ.get("KAKAO_REST_KEY", "").strip()
SIDO = os.environ.get("HIST_SIDO", "서울")
OFFICE = {"서울": "B10", "인천": "E10", "경기": "J10"}[SIDO]

def page(i):
    q = urllib.parse.urlencode({"KEY": KEY, "Type": "json", "pIndex": i, "pSize": 1000, "ATPT_OFCDC_SC_CODE": OFFICE})
    for t in range(4):
        try:
            with urllib.request.urlopen("https://open.neis.go.kr/hub/acaInsTiInfo?" + q, timeout=60) as f:
                d = json.loads(f.read())
            if "acaInsTiInfo" not in d:
                return 0, []
            return d["acaInsTiInfo"][0]["head"][0]["list_total_count"], d["acaInsTiInfo"][1]["row"]
        except Exception:
            time.sleep(3 * (t + 1))
    raise RuntimeError(f"나이스 응답 실패 p{i}")

def kakao_addr(addr, cache):
    ck = "kakao|" + addr
    if ck in cache:
        return cache[ck]
    res = None
    if KAKAO:
        try:
            req = urllib.request.Request("https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode({"query": addr}),
                                         headers={"Authorization": "KakaoAK " + KAKAO})
            with urllib.request.urlopen(req, timeout=15) as f:
                docs = json.loads(f.read())["documents"]
            if docs:
                res = [round(float(docs[0]["y"]), 6), round(float(docs[0]["x"]), 6)]
        except Exception:
            pass
        time.sleep(0.03)
    cache[ck] = res
    return res

def main():
    if not KEY:
        raise SystemExit("NEIS_KEY가 없습니다.")
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree
    total, rows = page(1)
    i = 1
    while len(rows) < total:
        i += 1
        rows += page(i)[1]
    print(f"{SIDO} 학원·교습소 {len(rows):,}곳, 상태 {dict((s, sum(1 for r in rows if r['REG_STTUS_NM'] == s)) for s in {r['REG_STTUS_NM'] for r in rows})}", flush=True)

    gpath = ROOT / "data" / "좌표_캐시_학원.json"    # 매일 갱신 캐시와 따로(동시에 커밋해도 안 부딪히게)
    gcache = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    feats = json.loads((ROOT / "data" / "boundary" / f"행정동_{SIDO}.geojson").read_text(encoding="utf-8"))["features"]
    polys = [shape(f["geometry"]) for f in feats]
    tree = STRtree(polys)
    out = []
    for n, r in enumerate(rows, 1):
        addr = re.sub(r"\s+", " ", r.get("FA_RDNMA") or "").strip()
        got = kakao_addr(addr, gcache) if addr else None
        code = dong = ""
        if got:
            p = Point(got[1], got[0])
            for j in tree.query(p):
                if polys[j].contains(p):
                    code, dong = feats[j]["properties"]["adm_cd2"], feats[j]["properties"]["adm_nm"].split(" ", 1)[1]
                    break
        out.append({"학원번호": r["ACA_ASNUM"], "이름": r["ACA_NM"], "구분": r["ACA_INSTI_SC_NM"], "분야": r["REALM_SC_NM"],
                    "교습과정": r.get("LE_CRSE_NM") or "", "개설일": (r.get("ESTBL_YMD") or "").strip(), "등록일": (r.get("REG_YMD") or "").strip(),
                    "상태": r["REG_STTUS_NM"], "정원": r.get("TOFOR_SMTOT") or "", "주소": addr,
                    "위도": got[0] if got else "", "경도": got[1] if got else "", "행정동코드": code, "행정동": dong})
        if n % 2000 == 0:
            gpath.write_text(json.dumps(gcache, ensure_ascii=False), encoding="utf-8")
            print(f"  {n:,}곳 좌표 처리", flush=True)
    gpath.write_text(json.dumps(gcache, ensure_ascii=False), encoding="utf-8")

    A = ROOT / "analysis" / SIDO
    A.mkdir(parents=True, exist_ok=True)
    with gzip.open(A / "학원.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    t = date.today()
    since = f"{t.year - 1:04d}{t.month:02d}01"
    agg = defaultdict(lambda: [0, 0])
    for r in out:
        if not r["행정동코드"] or r["상태"] != "개원":
            continue
        k = (r["행정동코드"], r["행정동"], r["분야"] or "기타")
        agg[k][0] += 1
        agg[k][1] += (r["개설일"] or r["등록일"] or "") >= since
    with open(A / "학원_행정동.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["행정동코드", "행정동", "분야", "개원", "최근12개월_신규"])
        for k in sorted(agg):
            w.writerow(list(k) + agg[k])
    print(f"행정동 못 붙임 {sum(1 for r in out if not r['행정동코드']):,}곳 → {A}")

if __name__ == "__main__":
    main()
