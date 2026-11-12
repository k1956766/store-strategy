# -*- coding: utf-8 -*-
"""최신업종 매일 갱신: 받기 → 임시 영업 판정 → 업종 분류 → 좌표 → 지도용 JSON.

실행(주피터): %run "G:\내 드라이브\개인연구\0. 연구원 생활\최신업종\3_스크립트\매일갱신.py"

- 처음 실행하면 최근 WINDOW_DAYS일 치를 전부 받고, 다음부터는 지난 실행 이후 바뀐 건만 받는다.
- 결과는 4_자료 폴더에 쌓인다.
    가게목록.json   관리번호별 원자료 + 판정 결과(누적)
    좌표_캐시.json  주소별 좌표
    업종조회_캐시.json  '기타' 가게의 카카오·네이버 조회 결과
    상태.json       지자체·자료별 마지막 실행일
    지도/{지자체코드}.json   지도에 올릴 최근 WINDOW_DAYS일 가게(임시 영업 제외)
- 키: 환경변수가 있으면 그것을, 없으면 api_key.txt에서 읽는다.
    DATA_GO_KR_KEY(필수), VWORLD_KEY, KAKAO_REST_KEY, NAVER_API_KEY_ID, NAVER_API_KEY
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

# ---- 설정 -------------------------------------------------------------
KEY_FILE = Path(os.environ.get("NEWSHOP_KEY_FILE", r"G:\내 드라이브\개인연구\api_key.txt"))
BASE = Path(os.environ.get("NEWSHOP_BASE", r"G:\내 드라이브\개인연구\0. 연구원 생활\최신업종"))
SIGUNGU = {"3220000": "서울 강남구", "3740000": "경기 수원시"}
DATASETS = {"휴게음식점": "rest_cafes", "일반음식점": "general_restaurants"}
WINDOW_DAYS = 90        # 지도에 올리는 기간
RETRY_DAYS = 14         # '기타'로 못 찾은 가게를 다시 묻는 간격
MAX_TRIES = 3           # 그 횟수까지만 다시 묻는다
# -----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import 업종분류                     # noqa: E402
import 업종조회                     # noqa: E402

DATA = Path(os.environ.get("NEWSHOP_DATA", BASE / "4_자료"))
MAP_DIR = os.environ.get("NEWSHOP_MAP_DIR", "지도")
TODAY = date.today()

# ---------- 공통 ----------
def read_keys():
    keys = {}
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    for k in ("DATA_GO_KR_KEY", "VWORLD_KEY", "KAKAO_REST_KEY", "NAVER_API_KEY_ID", "NAVER_API_KEY"):
        if os.environ.get(k):
            keys[k] = os.environ[k]
    if not keys.get("DATA_GO_KR_KEY"):
        raise SystemExit("DATA_GO_KR_KEY가 없습니다.")
    return keys

def load(name, default):
    f = DATA / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

def save(name, obj):
    f = DATA / name
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)

def ymd(d):
    return d.strftime("%Y%m%d")

# ---------- 1. 받기 ----------
def fetch(dataset, code, key, since_license, since_update=None):
    rows, page = [], 1
    while True:
        cond = {"serviceKey": key, "pageNo": page, "numOfRows": 100, "returnType": "json",
                "cond[OPN_ATMY_GRP_CD::EQ]": code, "cond[LCPMT_YMD::GTE]": since_license}
        if since_update:
            cond["cond[DAT_UPDT_PNT::GTE]"] = since_update      # yyyymmdd 형식만 먹힌다
        url = f"https://apis.data.go.kr/1741000/{dataset}/info?" + urllib.parse.urlencode(cond)
        for attempt in range(4):
            try:
                body = json.load(urllib.request.urlopen(url, timeout=150))["response"]["body"]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(5)
        items = body["items"]["item"] if body.get("items") else []
        if isinstance(items, dict):
            items = [items]
        rows += items
        if not items or len(rows) >= int(body.get("totalCount", 0)):
            return rows
        page += 1

# ---------- 2. 임시 영업 ----------
KEYWORDS = re.compile(r"한시적|행사장|팝업|축제|페스티벌|박람|전시장|컨벤션|메쎄|코엑스|SETEC|광장|일대|부스|로비")

def scale(r):
    try:
        return float((r.get("FCLT_TOTAL_SCL") or "0").replace(",", ""))
    except ValueError:
        return 0.0

def base_addr(r):
    return re.sub(r",.*", "", r.get("ROAD_NM_ADDR") or r.get("LOTNO_ADDR") or "").split(" (")[0].strip()

def find_event_addrs(rows, min_closed=3):
    n = {}
    for r in rows:
        if r["SALS_STTS_NM"] == "폐업":
            n[base_addr(r)] = n.get(base_addr(r), 0) + 1
    return {a for a, c in n.items() if c >= min_closed}

def temporary_reasons(r, event_addrs):
    why = []
    if r["SALS_STTS_NM"] == "폐업":
        why.append("폐업")
    if "한시적" in r["BPLC_NM"]:
        why.append("한시적 표기")
    if r["BZSTAT_SE_NM"] == "푸드트럭":
        why.append("푸드트럭")
    if scale(r) == 0:
        if base_addr(r) in event_addrs:
            why.append("행사장 주소")
        if KEYWORDS.search((r.get("ROAD_NM_ADDR") or "") + r["BPLC_NM"]):
            why.append("행사 키워드")
    return why

# ---------- 3. 좌표 ----------
_tf = None
def from_5174(x, y):
    global _tf
    if _tf is None:
        from pyproj import Transformer
        _tf = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lon, lat = _tf.transform(float(x), float(y))
    return round(lat, 6), round(lon, 6)

def short_road(a):
    return re.sub(r",.*", "", a or "").split(" (")[0].strip()

def short_lot(a):
    m = re.match(r"(.*?[동리가]\s+(?:산\s*)?\d+(?:-\d+)?)", a or "")
    return m.group(1) if m else (a or "").strip()

def vworld(addr, kind, key):
    q = urllib.parse.urlencode({"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
                                "type": kind, "address": addr, "format": "json", "key": key})
    try:
        with urllib.request.urlopen("https://api.vworld.kr/req/address?" + q, timeout=20) as f:
            d = json.loads(f.read())["response"]
        if d["status"] == "OK":
            return round(float(d["result"]["point"]["y"]), 6), round(float(d["result"]["point"]["x"]), 6)
    except Exception:
        pass
    return None

def kakao_addr(addr, key):
    try:
        req = urllib.request.Request("https://dapi.kakao.com/v2/local/search/address.json?" +
                                     urllib.parse.urlencode({"query": addr}), headers={"Authorization": "KakaoAK " + key})
        with urllib.request.urlopen(req, timeout=15) as f:
            d = json.loads(f.read())["documents"]
        if d:
            return round(float(d[0]["y"]), 6), round(float(d[0]["x"]), 6)
    except Exception:
        pass
    return None

def geocode(r, keys, cache):
    """원자료 좌표 → 브이월드(도로명, '지하' 주소는 지번 먼저) → 카카오 주소 검색."""
    if r.get("CRD_INFO_X"):
        return from_5174(r["CRD_INFO_X"], r["CRD_INFO_Y"]) + ("원자료",)
    road, lot = short_road(r.get("ROAD_NM_ADDR")), short_lot(r.get("LOTNO_ADDR"))
    order = [("parcel", lot, "지번"), ("road", road, "도로명")] if "지하" in (r.get("ROAD_NM_ADDR") or "") \
        else [("road", road, "도로명"), ("parcel", lot, "지번")]
    for kind, addr, label in order:
        if not addr:
            continue
        ck = kind + "|" + addr
        if ck not in cache and keys.get("VWORLD_KEY"):
            cache[ck] = vworld(addr, kind, keys["VWORLD_KEY"])
        if cache.get(ck):
            return tuple(cache[ck]) + ("브이월드 " + label,)
    if keys.get("KAKAO_REST_KEY") and road:
        ck = "kakao|" + road
        if ck not in cache:
            cache[ck] = kakao_addr(road, keys["KAKAO_REST_KEY"])
        if cache.get(ck):
            return tuple(cache[ck]) + ("카카오 주소",)
    return (None, None, "실패")

# ---------- 4. 업종 ----------
def classify(r, keys, lat, lon, qcache):
    cat, why = 업종분류.classify(r["BZSTAT_SE_NM"], r["BPLC_NM"])
    if cat != "기타":
        return cat, why
    if not (keys.get("KAKAO_REST_KEY") or keys.get("NAVER_API_KEY_ID")):
        return cat, why
    c = qcache.get(r["MNG_NO"])
    if c and c.get("업종"):
        return c["업종"], c["근거"]
    if c and (c["횟수"] >= MAX_TRIES or (TODAY - date.fromisoformat(c["마지막"])).days < RETRY_DAYS):
        return "기타", "미분류(조회 대기)"
    found = 업종조회.lookup(r["BPLC_NM"], r.get("ROAD_NM_ADDR"), r.get("LOTNO_ADDR"), lat, lon, keys)
    qcache[r["MNG_NO"]] = {"업종": found[0] if found else None, "근거": found[1] if found else None,
                           "찾은이름": found[2] if found else None, "마지막": TODAY.isoformat(),
                           "횟수": (c["횟수"] if c else 0) + 1}
    return (found[0], found[1]) if found else ("기타", "미분류")

# ---------- 5. 내보내기 ----------
FIELDS = ["BPLC_NM", "BZSTAT_SE_NM", "LCPMT_YMD", "SALS_STTS_NM", "CLSBIZ_YMD", "ROAD_NM_ADDR", "LOTNO_ADDR",
          "FCLT_TOTAL_SCL", "CRD_INFO_X", "CRD_INFO_Y", "MNG_NO", "OPN_ATMY_GRP_CD", "DAT_UPDT_PNT", "TELNO"]

def main():
    keys = read_keys()
    shops = load("가게목록.json", {})
    state = load("상태.json", {})
    gcache = load("좌표_캐시.json", {})
    qcache = load("업종조회_캐시.json", {})
    start = TODAY - timedelta(days=WINDOW_DAYS)
    t0 = time.time()

    # 1. 받기
    for code, place in SIGUNGU.items():
        for label, ds in DATASETS.items():
            sk = f"{code}|{ds}"
            last = state.get(sk)
            since_update = ymd(date.fromisoformat(last) - timedelta(days=1)) if last else None   # 하루 겹쳐 받기
            rows = fetch(ds, code, keys["DATA_GO_KR_KEY"], ymd(start), since_update)
            for r in rows:
                rec = {k: r.get(k) for k in FIELDS}
                rec["자료"] = label
                old = shops.get(r["MNG_NO"], {})
                for k in ("위도", "경도", "좌표출처"):        # 원자료 좌표가 새로 들어오면 아래에서 다시 계산
                    if k in old and not rec["CRD_INFO_X"]:
                        rec[k] = old[k]
                shops[r["MNG_NO"]] = rec
            state[sk] = TODAY.isoformat()
            print(f"  {place} {label}: {len(rows)}건 받음 ({'전체' if not last else '갱신분'})")

    # 기간 밖은 정리
    shops = {k: v for k, v in shops.items() if (v["LCPMT_YMD"] or "").replace("-", "") >= ymd(start)}

    # 2~4. 판정
    for code in SIGUNGU:
        rows = [v for v in shops.values() if v["OPN_ATMY_GRP_CD"] == code]
        event_addrs = find_event_addrs(rows)
        for r in rows:
            r["임시영업_사유"] = "·".join(temporary_reasons(r, event_addrs))
            if r["임시영업_사유"]:
                continue
            if r.get("CRD_INFO_X") or not r.get("위도"):
                r["위도"], r["경도"], r["좌표출처"] = geocode(r, keys, gcache)
            r["업종"], r["업종근거"] = classify(r, keys, r["위도"], r["경도"], qcache)
            found = (qcache.get(r["MNG_NO"]) or {}).get("찾은이름") or ""
            if "팝업" in found:                       # 지도에 '팝업'으로 등록된 매장
                r["임시영업_사유"] = "지도 등록명에 팝업"

    # 5. 지도용 파일
    out_dir = DATA / MAP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for code, place in SIGUNGU.items():
        items = [{"이름": v["BPLC_NM"], "업종": v["업종"], "업종근거": v["업종근거"], "원업태": v["BZSTAT_SE_NM"],
                  "인허가일": v["LCPMT_YMD"], "주소": short_road(v["ROAD_NM_ADDR"]) or v["LOTNO_ADDR"],
                  "위도": v["위도"], "경도": v["경도"], "좌표출처": v["좌표출처"], "관리번호": v["MNG_NO"]}
                 for v in shops.values() if v["OPN_ATMY_GRP_CD"] == code and not v["임시영업_사유"] and v.get("위도")]
        items.sort(key=lambda x: x["인허가일"], reverse=True)
        (out_dir / f"{code}.json").write_text(json.dumps(
            {"지역": place, "갱신일": TODAY.isoformat(), "기간_시작": start.isoformat(), "가게": items},
            ensure_ascii=False), encoding="utf-8")
        n_all = sum(1 for v in shops.values() if v["OPN_ATMY_GRP_CD"] == code)
        n_other = sum(1 for x in items if x["업종"] == "기타")
        summary.append(f"{place}: 받은 {n_all}건 → 지도 {len(items)}건 (기타 {n_other})")

    save("가게목록.json", shops)
    save("상태.json", state)
    save("좌표_캐시.json", gcache)
    save("업종조회_캐시.json", qcache)
    print("\n".join(summary))
    print(f"걸린 시간 {time.time() - t0:.0f}초 → {out_dir}")

if __name__ == "__main__":
    main()
