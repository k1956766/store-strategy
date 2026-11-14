# -*- coding: utf-8 -*-
"""'기타'로 남은 음식점의 업종을 카카오·네이버 지도 검색으로 채운다(상권 동향 분석 보강).

읽기: analysis/{SIDO}/가게.csv.gz (집계 결과)  → 업종이 '기타'이고 걸러지지 않은 음식점
저장: data/업종보강_캐시.json  {관리번호: {업종, 근거, 찾은이름, 마지막}}  — 집계.py가 읽는다.
매일 갱신용 업종조회_캐시.json과 따로 둬서 동시에 돌아도 부딪히지 않게 한다.
환경변수: HIST_SIDO(기본 서울), KAKAO_REST_KEY, NAVER_API_KEY_ID, NAVER_API_KEY, ENRICH_BUDGET_MIN(기본 300), ENRICH_MAX(기본 30000)
"""
import csv, gzip, json, os, sys, time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import 업종분류, 업종조회

SIDO = os.environ.get("HIST_SIDO", "서울")
BUDGET = float(os.environ.get("ENRICH_BUDGET_MIN", 300))
MAX = int(os.environ.get("ENRICH_MAX", 30000))
CACHE = ROOT / "data" / "업종보강_캐시.json"
keys = {k: os.environ.get(k, "").strip() for k in ("KAKAO_REST_KEY", "NAVER_API_KEY_ID", "NAVER_API_KEY")}

def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    daily = ROOT / "data" / "업종조회_캐시.json"        # 매일 갱신에서 이미 찾아본 가게는 건너뜀
    tried = set(json.loads(daily.read_text(encoding="utf-8"))) if daily.exists() else set()
    src = ROOT / "analysis" / SIDO / "가게.csv.gz"
    todo = []
    for r in csv.DictReader(gzip.open(src, "rt", encoding="utf-8")):
        if r["자료"] not in ("휴게음식점", "일반음식점") or r["제외"] or r["MNG_NO"] in cache or r["MNG_NO"] in tried:
            continue
        if 업종분류.classify(r["BZSTAT_SE_NM"], r["BPLC_NM"])[0] != "기타":   # 키워드 보강으로 이미 풀린 것
            continue
        if r["업종"] != "기타" and r["업종근거"] not in ("미분류",):
            continue
        todo.append(r)
    print(f"{SIDO}: 조회할 가게 {len(todo):,}곳 (캐시 {len(cache):,})", flush=True)
    t0, found, n = time.time(), 0, 0
    for r in todo[:MAX]:
        if (time.time() - t0) / 60 > BUDGET:
            break
        lat = float(r["위도"]) if r["위도"] else None
        lon = float(r["경도"]) if r["경도"] else None
        try:
            got = 업종조회.lookup(r["BPLC_NM"], r["ROAD_NM_ADDR"], "", lat, lon, keys, pause=0.05)
        except Exception as e:
            print("  오류", r["BPLC_NM"], e)
            got = None
        cache[r["MNG_NO"]] = {"업종": got[0] if got else None, "근거": got[1] if got else None,
                             "찾은이름": got[2] if got else None, "마지막": date.today().isoformat()}
        n += 1
        found += bool(got and got[0] != "기타")
        if n % 500 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  {n:,}곳 조회, 업종 찾음 {found:,} ({(time.time() - t0) / 60:.0f}분)", flush=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"이번 실행 {n:,}곳 조회, 업종 찾음 {found:,}, 남은 곳 {max(0, len(todo) - n):,}")

if __name__ == "__main__":
    main()
