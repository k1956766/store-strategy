# -*- coding: utf-8 -*-
"""최신업종 매일 갱신(수도권 66개 지자체): 받기 → 임시 영업 판정 → 업종 분류 → 좌표 → 지도용 JSON.

실행(주피터): %run "G:\내 드라이브\개인연구\0. 연구원 생활\최신업종\3_스크립트\매일갱신.py"
GitHub Actions에서는 .github/workflows/daily.yml이 매일 돌린다.

- 지자체 목록은 같은 폴더의 지자체_수도권.json(개방자치단체코드 → 이름).
- 처음 보는 지자체는 최근 WINDOW_DAYS일 치를 전부 받고, 다음부터는 지난 실행 이후 바뀐 건만 받는다.
  (전국을 한 번에 '바뀐 건'으로 물으면 API가 60초 제한에 걸려 실패해서 지자체마다 묻는다.)
- 한 번에 다 못 끝내도 괜찮게 만들었다: TIME_BUDGET_MIN을 넘기면 남은 지자체·업종 조회를 다음 실행으로 미루고
  그때까지 한 결과를 저장한다. 카카오·네이버 조회도 한 번에 MAX_LOOKUPS건까지만.
- 결과(DATA 폴더)
    shops/{코드}.json      관리번호별 원자료 + 판정 결과(누적)
    좌표_캐시.json, 업종조회_캐시.json, 상태.json
    {MAP_DIR}/{코드}.json  지도에 올릴 최근 WINDOW_DAYS일 가게(임시 영업 제외)
    {MAP_DIR}/index.json   지자체 목록과 건수
- 키: 환경변수가 있으면 그것을, 없으면 api_key.txt.
    DATA_GO_KR_KEY(필수), VWORLD_KEY, KAKAO_REST_KEY, NAVER_API_KEY_ID, NAVER_API_KEY
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

# ---- 설정 -------------------------------------------------------------
KEY_FILE = Path(os.environ.get("NEWSHOP_KEY_FILE", r"G:\내 드라이브\개인연구\api_key.txt"))
BASE = Path(os.environ.get("NEWSHOP_BASE", r"G:\내 드라이브\개인연구\0. 연구원 생활\최신업종"))
DATASETS = {"휴게음식점": "rest_cafes", "일반음식점": "general_restaurants"}
WINDOW_DAYS = 90         # 지도에 올리는 기간
RETRY_DAYS = 14          # '기타'로 못 찾은 가게를 다시 묻는 간격
MAX_TRIES = 3            # 그 횟수까지만 다시 묻는다
WORKERS = 4              # 인허가 API 동시 호출 수
MAX_LOOKUPS = int(os.environ.get("NEWSHOP_MAX_LOOKUPS", 800))            # 한 번 실행에 카카오·네이버 조회 상한
TIME_BUDGET_MIN = float(os.environ.get("NEWSHOP_TIME_BUDGET_MIN", 150))  # 이 시간이 지나면 남은 일은 다음 실행으로
# -----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import 업종분류                     # noqa: E402
import 업종조회                     # noqa: E402

SIGUNGU = json.loads((SCRIPT_DIR / "지자체_수도권.json").read_text(encoding="utf-8"))
DATA = Path(os.environ.get("NEWSHOP_DATA", BASE / "4_자료"))
MAP_DIR = os.environ.get("NEWSHOP_MAP_DIR", "지도")
TODAY = date.today()
T0 = time.time()

def over_budget():
    return (time.time() - T0) / 60 > TIME_BUDGET_MIN

# ---------- 공통 ----------
def read_keys():
    keys = {}
    if KEY_FILE.exists() and KEY_FILE.is_file():
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

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)

def ymd(d):
    return d.strftime("%Y%m%d")

# ---------- 1. 받기 ----------
def _call(url):
    """API는 60초 안에 못 끝내면 SERVICETIMEOUT을 돌려준다. 몇 번 다시 묻는다."""
    for attempt in range(5):
        try:
            b = json.load(urllib.request.urlopen(url, timeout=150))
            if "response" in b:
                return b["response"]["body"]
        except Exception:
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("API 응답 실패")

def fetch(dataset, code, key, since_license, since_update=None):
    rows, page = [], 1
    while True:
        cond = {"serviceKey": key, "pageNo": page, "numOfRows": 100, "returnType": "json",
                "cond[OPN_ATMY_GRP_CD::EQ]": code, "cond[LCPMT_YMD::GTE]": since_license}
        if since_update:
            cond["cond[DAT_UPDT_PNT::GTE]"] = since_update      # yyyymmdd 형식만 먹힌다
        body = _call(f"https://apis.data.go.kr/1741000/{dataset}/info?" + urllib.parse.urlencode(cond))
        items = body["items"]["item"] if body.get("items") else []
        if isinstance(items, dict):
            items = [items]
        rows += items
        if not items or len(rows) >= int(body.get("totalCount", 0)):
            return rows
        page += 1

# ---------- 2. 임시 영업 ----------
KEYWORDS = re.compile(r"한시적|행사장|팝업|축제|페스티벌|박람|전시장|컨벤션|컨벤시아|메쎄|코엑스|COEX|SETEC|킨텍스|KINTEX|"
                      r"aT센터|DDP|디자인플라자|광장|일대|부스|로비|운동장|경기장|체육관|야구장")

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

_vworld_down = False
def vworld(addr, kind, key):
    global _vworld_down
    if _vworld_down:
        return None
    q = urllib.parse.urlencode({"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326",
                                "type": kind, "address": addr, "format": "json", "key": key})
    try:
        with urllib.request.urlopen("https://api.vworld.kr/req/address?" + q, timeout=20) as f:
            d = json.loads(f.read())["response"]
        if d["status"] == "OK":
            return round(float(d["result"]["point"]["y"]), 6), round(float(d["result"]["point"]["x"]), 6)
        return None
    except Exception:
        _vworld_down = True          # 해외 서버 등에서 막히면 이번 실행에서는 카카오만 쓴다
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
        ck = kind + "|" + addr
        if addr and ck not in cache and keys.get("VWORLD_KEY") and not _vworld_down:
            cache[ck] = vworld(addr, kind, keys["VWORLD_KEY"])
        if addr and cache.get(ck):
            return tuple(cache[ck]) + ("브이월드 " + label,)
    if keys.get("KAKAO_REST_KEY") and road:
        ck = "kakao|" + road
        if ck not in cache:
            cache[ck] = kakao_addr(road, keys["KAKAO_REST_KEY"])
        if cache.get(ck):
            return tuple(cache[ck]) + ("카카오 주소",)
    return (None, None, "실패")

# ---------- 4. 업종 ----------
_lookups = 0
def classify(r, keys, lat, lon, qcache):
    global _lookups
    cat, why = 업종분류.classify(r["BZSTAT_SE_NM"], r["BPLC_NM"])
    if cat != "기타" or not (keys.get("KAKAO_REST_KEY") or keys.get("NAVER_API_KEY_ID")):
        return cat, why
    c = qcache.get(r["MNG_NO"])
    if c and c.get("업종"):
        return c["업종"], c["근거"]
    if c and (c["횟수"] >= MAX_TRIES or (TODAY - date.fromisoformat(c["마지막"])).days < RETRY_DAYS):
        return "기타", "미분류(조회 대기)"
    if _lookups >= MAX_LOOKUPS or over_budget():
        return "기타", "미분류(다음 실행에 조회)"
    _lookups += 1
    found = 업종조회.lookup(r["BPLC_NM"], r.get("ROAD_NM_ADDR"), r.get("LOTNO_ADDR"), lat, lon, keys)
    qcache[r["MNG_NO"]] = {"업종": found[0] if found else None, "근거": found[1] if found else None,
                           "찾은이름": found[2] if found else None, "마지막": TODAY.isoformat(),
                           "횟수": (c["횟수"] if c else 0) + 1}
    return (found[0], found[1]) if found else ("기타", "미분류")

# ---------- 5. 실행 ----------
FIELDS = ["BPLC_NM", "BZSTAT_SE_NM", "LCPMT_YMD", "SALS_STTS_NM", "CLSBIZ_YMD", "ROAD_NM_ADDR", "LOTNO_ADDR",
          "FCLT_TOTAL_SCL", "CRD_INFO_X", "CRD_INFO_Y", "MNG_NO", "OPN_ATMY_GRP_CD", "DAT_UPDT_PNT", "TELNO"]

def _fetch_job(args):
    if over_budget():
        return None
    return fetch(*args)

def main():
    keys = read_keys()
    state = load(DATA / "상태.json", {})
    gcache = load(DATA / "좌표_캐시.json", {})
    qcache = load(DATA / "업종조회_캐시.json", {})
    start = TODAY - timedelta(days=WINDOW_DAYS)
    shops = {code: load(DATA / "shops" / f"{code}.json", {}) for code in SIGUNGU}

    # 1. 받기 (지자체×자료마다, 동시에 WORKERS개)
    jobs = []
    for code in SIGUNGU:
        for label, ds in DATASETS.items():
            last = state.get(f"{code}|{ds}")
            since_update = ymd(date.fromisoformat(last) - timedelta(days=1)) if last else None   # 하루 겹쳐 받기
            jobs.append((code, label, ds, since_update))
    jobs.sort(key=lambda j: j[3] is not None)          # 처음 받는 지자체(오래 걸림)를 먼저
    got, failed, skipped = 0, [], 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(_fetch_job, (ds, code, keys["DATA_GO_KR_KEY"], ymd(start), su)): (code, label, ds)
                for code, label, ds, su in jobs}
        for f in as_completed(futs):
            code, label, ds = futs[f]
            try:
                rows = f.result()
            except Exception:
                failed.append(f"{SIGUNGU[code]} {label}")
                continue
            if rows is None:
                skipped += 1
                continue
            for r in rows:
                rec = {k: r.get(k) for k in FIELDS}
                rec["자료"] = label
                old = shops[code].get(r["MNG_NO"], {})
                for k in ("위도", "경도", "좌표출처"):
                    if k in old and not rec["CRD_INFO_X"]:
                        rec[k] = old[k]
                shops[code][r["MNG_NO"]] = rec
            state[f"{code}|{ds}"] = TODAY.isoformat()
            got += len(rows)
    print(f"받기: {got}건, 실패 {len(failed)}, 시간 부족으로 미룸 {skipped} ({(time.time()-T0)/60:.0f}분)")
    if failed:
        print("  실패(다음 실행에 다시):", ", ".join(failed))
    save(DATA / "상태.json", state)

    # 2~4. 판정 (지자체마다 저장해 두어 중간에 끊겨도 남는다)
    for code in SIGUNGU:
        shops[code] = {k: v for k, v in shops[code].items()
                       if (v["LCPMT_YMD"] or "").replace("-", "") >= ymd(start)}
        rows = list(shops[code].values())
        event_addrs = find_event_addrs(rows)
        for r in rows:
            r["임시영업_사유"] = "·".join(temporary_reasons(r, event_addrs))
            if r["임시영업_사유"]:
                continue
            if r.get("CRD_INFO_X") or not r.get("위도"):
                r["위도"], r["경도"], r["좌표출처"] = geocode(r, keys, gcache)
            r["업종"], r["업종근거"] = classify(r, keys, r["위도"], r["경도"], qcache)
            found = (qcache.get(r["MNG_NO"]) or {}).get("찾은이름") or ""
            if "팝업" in found:                         # 지도에 '팝업'으로 등록된 매장
                r["임시영업_사유"] = "지도 등록명에 팝업"
        save(DATA / "shops" / f"{code}.json", shops[code])
        save(DATA / "좌표_캐시.json", gcache)
        save(DATA / "업종조회_캐시.json", qcache)
    print(f"판정: 카카오·네이버 조회 {_lookups}건 ({(time.time()-T0)/60:.0f}분)")

    # 5. 지도용 파일
    out_dir = DATA / MAP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    index, total, total_other = [], 0, 0
    for code, place in SIGUNGU.items():
        items = [{"이름": v["BPLC_NM"], "업종": v["업종"], "업종근거": v["업종근거"], "원업태": v["BZSTAT_SE_NM"],
                  "인허가일": v["LCPMT_YMD"], "주소": short_road(v["ROAD_NM_ADDR"]) or v["LOTNO_ADDR"],
                  "위도": v["위도"], "경도": v["경도"], "좌표출처": v["좌표출처"], "관리번호": v["MNG_NO"]}
                 for v in shops[code].values() if not v.get("임시영업_사유") and v.get("위도")]
        items.sort(key=lambda x: x["인허가일"], reverse=True)
        save(out_dir / f"{code}.json", {"지역": place, "코드": code, "갱신일": TODAY.isoformat(),
                                        "기간_시작": start.isoformat(), "가게": items})
        n_other = sum(1 for x in items if x["업종"] == "기타")
        index.append({"코드": code, "지역": place, "시도": place.split()[0], "가게수": len(items), "기타": n_other,
                      "받은날": state.get(f"{code}|general_restaurants")})
        total += len(items)
        total_other += n_other
    save(out_dir / "index.json", {"갱신일": TODAY.isoformat(), "기간_시작": start.isoformat(), "지역": index})
    print(f"지도: {len(SIGUNGU)}개 지자체 {total}곳 (기타 {total_other}) → {out_dir}")
    print(f"걸린 시간 {(time.time() - T0) / 60:.0f}분")

if __name__ == "__main__":
    main()
