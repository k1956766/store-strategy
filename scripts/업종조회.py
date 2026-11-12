# -*- coding: utf-8 -*-
"""상호·주소로 카카오 로컬 → 네이버 지역 검색에 물어 업종을 받아 온다.

업종분류.classify()가 '기타'로 남긴 가게에만 쓴다.
lookup(상호, 도로명주소, 지번주소, 위도, 경도, keys) -> (업종, 근거, 찾은이름) 또는 None

인정 규칙(오판정 줄이기)
- 이름: 지점명·괄호·법인 표기를 뗀 상호가 2글자 이하면 이름이 완전히 같아야 한다.
        3글자 이상이면 앞 3글자가 상대 이름 안에 있어야 한다.
- 위치: 도로명+건물번호가 같거나, 두 좌표 거리가 150m 이내여야 한다.
"""
import json, math, re, time, urllib.parse, urllib.request

def _norm(t):
    return re.sub(r"[\s\(\)\[\],.&·'\-]", "", t or "").lower()

def core_name(name):
    n = re.sub(r"\(.*?\)|주식회사|\(주\)|\(유\)", "", name or "").strip()
    n2 = re.sub(r"\s*\S*(점|본점|직영점)$", "", n).strip()
    return n2 or n

def road_key(addr):
    m = re.search(r"(\S+[로길])\s*(?:지하\s*)?(\d+(?:-\d+)?)", addr or "")
    return (m.group(1), m.group(2)) if m else None

def dong_of(road_addr, lot_addr):
    m = re.search(r"\(([^),]*[동가])", road_addr or "")
    if m:
        return m.group(1)
    m = re.search(r"\s(\S+[동가])\s", lot_addr or "")
    return m.group(1) if m else ""

def _dist(lat1, lon1, lat2, lon2):
    return math.hypot((lat1 - lat2) * 111000, (lon1 - lon2) * 88800)

def name_ok(shop, place):
    c, p = _norm(core_name(shop)), _norm(place)
    if not c or not p:
        return False
    if len(c) <= 2:
        return _norm(core_name(place)) == c
    return c[:3] in p or (len(p) >= 3 and p[:3] in c)

def place_ok(road, lat, lon, p_road, p_lat, p_lon):
    if road_key(road) and road_key(road) == road_key(p_road):
        return True
    if lat and p_lat:
        return _dist(lat, lon, p_lat, p_lon) <= 150
    return False

# 카카오·네이버 분류 문자열 → 지도 업종 (위에서부터 먼저 맞는 것)
CAT_RULES = [
    ("편의점", r"편의점"),
    ("PC방·오락", r"PC방|게임방|오락|노래|당구|볼링|보드게임|만화카페|키즈카페"),
    ("술집", r"술집|주점|호프|와인|칵테일|바\(BAR\)|이자카야|포차|맥주|요리주점"),
    ("디저트·베이커리", r"베이커리|제과|케이크|도넛|아이스크림|빙수|와플|떡|디저트카페|간식"),
    ("카페·음료", r"카페|커피|차,?음료|생과일|주스"),
    ("치킨·버거·피자", r"치킨|피자|햄버거|버거|패스트푸드|샌드위치"),
    ("일식", r"일식|초밥|돈까스|일본|우동|라멘|참치|오마카세"),
    ("중식", r"중식|중국|양꼬치|마라|훠궈"),
    ("아시아 음식", r"아시아|베트남|태국|인도|쌀국수"),
    ("분식", r"분식|김밥|떡볶이|만두"),
    ("고기구이", r"고기|육류|돼지|소고기|갈비|족발|보쌈|곱창|삼겹|닭갈비"),
    ("해산물·횟집", r"해물|생선|회$|생선회|조개|장어|게,?대게|해산물"),
    ("양식", r"양식|이탈리|프랑스|스페인|스테이크|파스타|멕시코|남미|퓨전|뷔페|브런치|다이닝"),
    ("한식", r"한식|국밥|냉면|국수|칼국수|백반|찌개|죽"),
]
CAT_RULES = [(c, re.compile(p)) for c, p in CAT_RULES]

def map_category(cat):
    for c, pat in CAT_RULES:
        if pat.search(cat or ""):
            return c
    return "기타"   # 음식점이 아닌 곳(식품판매, 스튜디오 등)

def _get(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return json.loads(f.read())
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)

def kakao(query, key, lat=None, lon=None):
    p = {"query": query, "size": 5}
    if lat:
        p.update(x=lon, y=lat, radius=300, sort="distance")
    d = _get("https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(p),
             {"Authorization": "KakaoAK " + key})
    return d.get("documents", [])

def naver_local(query, key_id, key):
    d = _get("https://naverapihub.apigw.ntruss.com/search/v1/local?" +
             urllib.parse.urlencode({"query": query, "display": 5}),
             {"X-NCP-APIGW-API-KEY-ID": key_id, "X-NCP-APIGW-API-KEY": key})
    return d.get("items", [])

def _naver_xy(item):
    """네이버 지역 검색 mapx/mapy는 경위도×1e7 정수."""
    try:
        x, y = int(item["mapx"]) / 1e7, int(item["mapy"]) / 1e7
        return (y, x) if 33 < y < 39 and 124 < x < 132 else (None, None)
    except (KeyError, ValueError):
        return (None, None)

def lookup(shop, road, lot, lat, lon, keys, pause=0.1):
    """keys = {"KAKAO_REST_KEY":..., "NAVER_API_KEY_ID":..., "NAVER_API_KEY":...}"""
    dong = dong_of(road, lot)
    parts = (road or lot or "").split()
    area = dong or (parts[1] if len(parts) > 1 else "")
    name, core = re.sub(r"\(.*?\)|주식회사|\(주\)|\(유\)", "", shop).strip(), core_name(shop)

    if keys.get("KAKAO_REST_KEY"):
        tries = []
        if lat:
            tries += [(name, lat, lon), (core, lat, lon)]
        tries += [(f"{core} {area}".strip(), None, None)]
        for q, qy, qx in tries:
            try:
                docs = kakao(q, keys["KAKAO_REST_KEY"], qy, qx)
            except Exception:
                docs = []
            time.sleep(pause)
            for d in docs:
                p_lat, p_lon = float(d["y"]), float(d["x"])
                if name_ok(shop, d["place_name"]) and place_ok(road, lat, lon, d.get("road_address_name"), p_lat, p_lon):
                    return map_category(d["category_name"]), "카카오: " + d["category_name"], d["place_name"]

    if keys.get("NAVER_API_KEY_ID"):
        try:
            items = naver_local(f"{name} {area}".strip(), keys["NAVER_API_KEY_ID"], keys["NAVER_API_KEY"])
        except Exception:
            items = []
        time.sleep(pause)
        for it in items:
            title = re.sub(r"<.*?>", "", it.get("title", ""))
            p_lat, p_lon = _naver_xy(it)
            if name_ok(shop, title) and place_ok(road, lat, lon, it.get("roadAddress"), p_lat, p_lon):
                return map_category(it.get("category")), "네이버: " + it.get("category", ""), title
    return None
