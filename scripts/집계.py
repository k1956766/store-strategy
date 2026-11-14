# -*- coding: utf-8 -*-
"""상권 동향 분석 2단계: 이력(history/)을 행정동 × 업종 × 월 집계표로.

1. history/{코드}/*.csv.gz를 모두 읽는다(영업 중 + 기준일 이후 폐업).
2. 업종: 업종분류.classify(업태·사전·키워드). 매일 갱신 때 카카오·네이버로 찾아 둔 결과(data/업종조회_캐시.json)가 있으면 그걸 쓴다.
3. 걸러내기
   - 임시 영업: 30일 안에 폐업, 상호에 '한시적', 푸드트럭, 규모 0인 행사장 주소(같은 건물 폐업 3건 이상)·행사 키워드
   - 행정 정리(직권 일괄 폐업): 같은 지자체·같은 날 폐업이 그 지자체 하루 폐업 중앙값의 5배 이상이면서 20건 이상이고,
     그날 폐업한 가게의 영업기간 중앙값이 3년 이상이면 그날 폐업은 실제 폐업이 아니라 서류 정리로 본다.
   걸러낸 가게는 개업·폐업·영업 중 가게 수 어디에도 넣지 않는다.
4. 좌표: 원자료(EPSG:5174) → 없으면 카카오 주소 검색(data/좌표_캐시.json 공유). 행정동은 경계 안에 드는지로 정한다.
5. 내보내기(analysis/{시도}/)
   가게.csv.gz          가게 단위 정리본(업종, 행정동, 걸러낸 이유)
   월별_행정동_업종.csv  월, 행정동코드, 행정동, 업종, 월초_영업, 개업, 폐업
   걸러낸_날.csv         행정 정리로 본 날짜(지자체, 날짜, 건수, 영업기간 중앙값)

환경변수: HIST_SIDO(기본 서울), HIST_START(기본 2025-01-01), KAKAO_REST_KEY(좌표 없는 가게용, 없으면 건너뜀)
"""
import csv, gzip, json, os, re, statistics, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import 업종분류  # noqa: E402

SIDO = os.environ.get("HIST_SIDO", "서울")
START = os.environ.get("HIST_START", "2025-01-01")
BOUNDARY = ROOT / "data" / "boundary" / f"행정동_{SIDO}.geojson"
OUT = ROOT / "analysis" / SIDO
KAKAO = os.environ.get("KAKAO_REST_KEY", "").strip()

KEYWORDS = re.compile(r"한시적|행사장|팝업|축제|페스티벌|박람|전시장|컨벤션|컨벤시아|메쎄|코엑스|COEX|SETEC|킨텍스|KINTEX|"
                      r"aT센터|DDP|디자인플라자|광장|일대|부스|로비|운동장|경기장|체육관|야구장")

FOOD = {"휴게음식점", "일반음식점"}
CVS = re.compile(r"씨유|CU|지에스25|GS25|GS\s*25|세븐일레븐|코리아세븐|이마트24|미니스톱|emart24|스토리웨이|위드미", re.I)

def extra_category(r):
    """음식점 밖 인허가 업종의 분석용 업종 이름."""
    lab, name = r["자료"], r["BPLC_NM"] or ""
    sub = (r.get("SNTTN_BZSTAT_NM") or r.get("BZSTAT_SE_NM") or "")
    if lab == "제과점영업": return "디저트·베이커리"
    if lab == "즉석판매제조가공업": return "반찬·즉석식품"
    if lab == "축산판매업": return "정육점"
    if lab == "식품판매업(기타)": return "식료품점"
    if lab == "건강기능식품일반판매업": return "건강기능식품"
    if lab in ("단란주점영업", "유흥주점영업"): return "유흥·단란주점"
    if lab == "관광식당": return "관광식당"
    if lab == "담배소매업": return "편의점(담배소매)" if CVS.search(name) else "슈퍼·담배가게"
    if lab == "안전상비의약품판매업소": return "상비약 판매점"
    if lab == "약국": return "약국"
    if lab == "의원":
        subj = r.get("MDEXM_SBJCT_CN_NM") or ""
        if "치과" in name or subj.startswith("치과"): return "치과의원"
        if "한의" in name or subj.startswith("한방") or "한의" in subj: return "한의원"
        if re.search(r"피부|성형", subj.split(",")[0] + name): return "피부·성형의원"
        return "의원"
    if lab == "병원": return "병원"
    if lab == "안경업": return "안경점"
    if lab == "의료기기판매(임대)업": return "의료기기점"
    if lab == "산후조리업": return "산후조리원"
    if lab == "미용업":
        if "네일" in sub or "네일" in name: return "네일샵"
        if "피부" in sub: return "피부관리실"
        if "화장" in sub or "메이크업" in sub: return "메이크업"
        return "미용실"
    if lab == "이용업": return "이발소·바버샵"
    if lab == "세탁업": return "코인빨래방" if re.search(r"빨래|코인|워시|런드리|laundry", name, re.I) else "세탁소"
    if lab == "목욕장업": return "목욕탕·찜질방"
    if lab == "체력단련장업": return "필라테스·요가" if re.search(r"필라테스|요가|pilates|yoga", name, re.I) else "헬스·PT"
    if lab == "체육도장업": return "체육도장"
    if lab == "골프연습장업": return "골프연습장"
    if lab in ("수영장업", "종합체육시설업"): return "대형 체육시설"
    if lab == "노래연습장업": return "코인노래방" if "코인" in name else "노래방"
    if lab == "인터넷컴퓨터게임시설제공업": return "PC방"
    if lab == "청소년게임제공업": return "인형뽑기·오락실"
    if lab == "일반게임제공업": return "성인게임장"
    if lab == "숙박업": return "숙박"
    if lab == "외국인관광도시민박업": return "외국인 민박"
    if lab == "관광숙박업": return "호텔"
    if lab == "동물병원": return "동물병원"
    if lab in ("동물미용업", "동물위탁관리업", "동물판매업", "동물약국"): return "반려동물 서비스"
    if lab == "대규모점포": return "대규모점포"
    return lab

def d(s):
    return date.fromisoformat(s[:10]) if s else None

def scale(r):
    try:
        return float((r.get("FCLT_TOTAL_SCL") or "0").replace(",", ""))
    except ValueError:
        return 0.0

def base_addr(r):
    return re.sub(r",.*", "", r.get("ROAD_NM_ADDR") or r.get("LOTNO_ADDR") or "").split(" (")[0].strip()

def load_rows():
    regions = json.loads((ROOT / "scripts" / "지자체_수도권.json").read_text(encoding="utf-8"))
    rows = {}
    for code, name in regions.items():
        if not name.startswith(SIDO):
            continue
        for f in sorted((ROOT / "history" / code).glob("*.csv.gz")) if (ROOT / "history" / code).exists() else []:
            label = f.name.split("_")[0]
            for r in csv.DictReader(gzip.open(f, "rt", encoding="utf-8")):
                r["자료"] = label
                r["지자체"] = name
                rows[(label, r["MNG_NO"])] = r
    return list(rows.values())

def mark_filters(rows):
    """임시 영업과 행정 정리 표시. 사유를 r['제외']에 넣는다."""
    closed_at = Counter(base_addr(r) for r in rows if r["CLSBIZ_YMD"])
    # 같은 주소에서 넉 달 안에 문 닫은 가게가 3곳 이상 → 장터·팝업 행사(규모가 있어도)
    def short(r):
        o, c = d(r["LCPMT_YMD"]), d(r["CLSBIZ_YMD"])
        return bool(o and c and (c - o).days < 120)
    short_at = Counter(base_addr(r) for r in rows if r["자료"] in FOOD and short(r))
    for r in rows:
        why = []
        o, c = d(r["LCPMT_YMD"]), d(r["CLSBIZ_YMD"])
        if c and o and (c - o).days < 30:
            why.append("30일 안 폐업")
        if "한시적" in r["BPLC_NM"]:
            why.append("한시적")
        if r["자료"] in FOOD and r["BZSTAT_SE_NM"] == "푸드트럭":
            why.append("푸드트럭")
        if r["자료"] in FOOD and scale(r) == 0 and (closed_at[base_addr(r)] >= 3 or KEYWORDS.search((r["ROAD_NM_ADDR"] or "") + r["BPLC_NM"])):
            why.append("행사장")
        elif r["자료"] in FOOD and short(r) and short_at[base_addr(r)] >= 3:
            why.append("행사장")
        r["제외"] = "·".join(why)

    # 행정 정리: 임시 영업이 아닌 폐업만 놓고 지자체·날짜별로 본다
    by_day = defaultdict(list)
    for r in rows:
        if r["CLSBIZ_YMD"] and not r["제외"]:
            by_day[(r["지자체"] + "|" + ("음식점" if r["자료"] in FOOD else r["자료"]), r["CLSBIZ_YMD"][:10])].append(r)
    per_region = defaultdict(list)
    for (reg, day), rs in by_day.items():
        per_region[reg].append(len(rs))
    flagged = []
    for (reg, day), rs in by_day.items():
        med = statistics.median(per_region[reg]) if per_region[reg] else 1
        life = statistics.median([(d(r["CLSBIZ_YMD"]) - d(r["LCPMT_YMD"])).days / 365 for r in rs if r["LCPMT_YMD"]])
        if len(rs) >= max(20, 5 * med) and life >= 3:
            flagged.append((reg.split("|")[0], day, len(rs), round(life, 1), reg.split("|")[1]))
            for r in rs:
                r["제외"] = "행정 정리"
    return flagged

_tf = None
def to_wgs(x, y):
    global _tf
    if _tf is None:
        from pyproj import Transformer
        _tf = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lon, lat = _tf.transform(float(x), float(y))
    return lat, lon

def kakao_addr(addr, cache):
    ck = "kakao|" + addr
    if ck in cache:
        return cache[ck]
    res = None
    if KAKAO and addr:
        try:
            req = urllib.request.Request("https://dapi.kakao.com/v2/local/search/address.json?" +
                                         urllib.parse.urlencode({"query": addr}), headers={"Authorization": "KakaoAK " + KAKAO})
            with urllib.request.urlopen(req, timeout=15) as f:
                docs = json.loads(f.read())["documents"]
            if docs:
                res = [round(float(docs[0]["y"]), 6), round(float(docs[0]["x"]), 6)]
        except Exception:
            pass
        time.sleep(0.05)
    cache[ck] = res
    return res

def main():
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    rows = load_rows()
    print(f"{SIDO}: 가게 {len(rows):,}곳 읽음")
    qcache = {}
    for cf in ("업종조회_캐시.json", "업종보강_캐시.json"):     # 매일 갱신 조회 + 분석용 보강 조회
        if (ROOT / "data" / cf).exists():
            qcache.update({k: v for k, v in json.loads((ROOT / "data" / cf).read_text(encoding="utf-8")).items() if v.get("업종")})
    for r in rows:
        if r["자료"] not in FOOD:
            r["업종"], r["업종근거"] = extra_category(r), "인허가 업종"
            continue
        cat, why = 업종분류.classify(r["BZSTAT_SE_NM"], r["BPLC_NM"])
        q = qcache.get(r["MNG_NO"]) or {}
        if cat == "기타" and q.get("업종"):
            cat, why = q["업종"], q["근거"]
        r["업종"], r["업종근거"] = cat, why
    flagged = mark_filters(rows)

    gpath = ROOT / "data" / "좌표_캐시.json"
    gcache = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    feats = json.loads(BOUNDARY.read_text(encoding="utf-8"))["features"]
    polys = [shape(f["geometry"]) for f in feats]
    tree = STRtree(polys)
    no_xy = 0
    for r in rows:
        r["위도"] = r["경도"] = r["행정동코드"] = r["행정동"] = ""
        if r["CRD_INFO_X"]:
            lat, lon = to_wgs(r["CRD_INFO_X"], r["CRD_INFO_Y"])
        else:
            road = re.sub(r",.*", "", r["ROAD_NM_ADDR"] or "").split(" (")[0].strip()
            m = re.match(r"(.*?[동리가]\s+(?:산\s*)?\d+(?:-\d+)?)", r["LOTNO_ADDR"] or "")
            lot = m.group(1) if m else (r["LOTNO_ADDR"] or "").strip()
            got = (kakao_addr(road, gcache) if road else None) or (kakao_addr(lot, gcache) if lot else None)
            if not got:
                no_xy += 1
                continue
            lat, lon = got
        r["위도"], r["경도"] = round(lat, 6), round(lon, 6)
        p = Point(lon, lat)
        for i in tree.query(p):
            if polys[i].contains(p):
                pr = feats[i]["properties"]
                r["행정동코드"], r["행정동"] = pr["adm_cd2"], pr["adm_nm"].split(" ", 1)[1]
                break
    gpath.write_text(json.dumps(gcache, ensure_ascii=False), encoding="utf-8")

    # 월별 집계
    today = date.today()
    months = []
    y, m = int(START[:4]), int(START[5:7])
    while (y, m) <= (today.year, today.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    use = [r for r in rows if not r["제외"] and r["행정동코드"]]
    agg = defaultdict(lambda: [0, 0, 0])   # (월, 동코드, 동, 업종) -> [월초_영업, 개업, 폐업]
    for r in use:
        o, c = r["LCPMT_YMD"][:10], (r["CLSBIZ_YMD"] or "")[:10]
        key = (r["행정동코드"], r["행정동"], r["업종"])
        for mo in months:
            first = mo + "-01"
            if o < first and (not c or c >= first):
                agg[(mo,) + key][0] += 1
            if o[:7] == mo:
                agg[(mo,) + key][1] += 1
            if c[:7] == mo:
                agg[(mo,) + key][2] += 1

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "월별_행정동_업종.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["월", "행정동코드", "행정동", "업종", "월초_영업", "개업", "폐업"])
        for k in sorted(agg):
            w.writerow(list(k) + agg[k])
    keep = ["MNG_NO", "BPLC_NM", "자료", "BZSTAT_SE_NM", "SNTTN_BZSTAT_NM", "업종", "업종근거", "LCPMT_YMD", "CLSBIZ_YMD", "SALS_STTS_NM",
            "지자체", "행정동코드", "행정동", "위도", "경도", "ROAD_NM_ADDR", "FCLT_TOTAL_SCL", "제외"]
    with gzip.open(OUT / "가게.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keep, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(OUT / "걸러낸_날.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["지자체", "날짜", "폐업건수", "영업기간_중앙값_년", "자료"])
        w.writerows(sorted(flagged))

    ex = Counter(r["제외"].split("·")[0] for r in rows if r["제외"])
    print(f"제외: {dict(ex)} / 좌표 못 구함 {no_xy} / 행정동 못 붙임 {sum(1 for r in rows if r['위도'] and not r['행정동코드'])}")
    print(f"분석에 쓰는 가게 {len(use):,}곳, 집계 행 {len(agg):,} → {OUT}")

if __name__ == "__main__":
    main()
