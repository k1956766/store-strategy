(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const fmt = (v, d = 1) => (v == null || v === '' || Number.isNaN(+v) ? '–' : (+v).toLocaleString('ko-KR', { maximumFractionDigits: d, minimumFractionDigits: d }));
  const int = (v) => (v == null || v === '' ? '–' : Math.round(+v).toLocaleString('ko-KR'));
  const sign = (v, d = 1) => (v == null || v === '' ? '–' : `${+v > 0 ? '+' : ''}${fmt(v, d)}`);
  // 색: 크기는 파랑 한 색 단계, 순증은 파랑(증가)–회색–빨강(감소)
  const SEQ = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];
  const DIV = ['#b42e2d', '#e66767', '#f0efec', '#6da7ec', '#1c5cab'];
  const NA = '#e3e6e4';
  const METRIC = {
    회전율: { name: '교체(회전율, %/년)', d: 0 }, 폐업률: { name: '폐업률(%/년)', d: 1 },
    개업률: { name: '개업률(%/년)', d: 1 }, 순증률: { name: '가게 수 순증률(%)', d: 1, div: true },
  };
  const FAMILY = [
    ['음식·음료', ['한식', '고기구이', '해산물·횟집', '분식', '중식', '일식', '아시아 음식', '양식', '치킨·버거·피자', '카페·음료', '디저트·베이커리', '술집', '유흥·단란주점', '관광식당', 'PC방·오락']],
    ['먹거리 가게', ['반찬·즉석식품', '정육점', '식료품점', '편의점', '슈퍼·담배가게', '대규모점포']],
    ['미용·생활', ['미용실', '네일샵', '피부관리실', '메이크업', '이발소·바버샵', '세탁소', '코인빨래방', '목욕탕·찜질방']],
    ['의료·건강', ['의원', '치과의원', '한의원', '피부·성형의원', '병원', '약국', '안경점', '산후조리원']],
    ['운동·여가', ['헬스·PT', '필라테스·요가', '체육도장', '골프연습장', '대형 체육시설', '노래방', '코인노래방', 'PC방', '인형뽑기·오락실', '성인게임장']],
    ['반려동물', ['동물병원', '반려동물 서비스']],
    ['숙박', ['숙박', '외국인 민박', '호텔']],
  ];
  const LODGING = new Set(['숙박', '외국인 민박', '호텔']);
  const state = { metric: '회전율', cat: '', tab: 'up', dong: null };
  let T = null, geo = null, layer = null;
  const layers = {};
  state.level = 'gu';
  // 단위별 자료(시군구 / 읍면동)
  const D = () => (state.level === 'gu'
    ? { 지역: T.시군구.지역, 지역_업종: T.시군구.지역_업종, 뜨는: T.시군구.뜨는, 경보: T.시군구.경보, 교체: T.시군구.교체_빈발, min: 0 }
    : { 지역: T.행정동, 지역_업종: T.행정동_업종, 뜨는: T.뜨는_동네업종, 경보: T.폐업경보, 교체: T.교체_빈발, min: 20 });
  const UNIT = () => (state.level === 'gu' ? '구' : '동네');

  const map = L.map('map', { zoomControl: false, minZoom: 9, maxZoom: 16 }).setView([37.5565, 126.99], 11);
  L.control.zoom({ position: 'topright' }).addTo(map);
  const VW_KEY = '';
  const hasVW = /^[0-9A-F-]{30,}$/i.test(VW_KEY);
  L.tileLayer(hasVW ? `https://api.vworld.kr/req/wmts/1.0.0/${VW_KEY}/Base/{z}/{y}/{x}.png` : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, className: 'basemap',
    attribution: hasVW ? '&copy; <a href="https://www.vworld.kr">국토교통부 브이월드</a>' : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 기여자',
  }).addTo(map);

  // ---------- 값 ----------
  function catRow(code, cat) {
    return (D().지역_업종[code] || []).find((r) => r[0] === cat);
  }
  function valueOf(code) {
    if (state.cat) {
      const r = catRow(code, state.cat);
      return r && r[1] >= 3 ? r[4] : null;           // 특화도(가게 3곳 이상만)
    }
    const d = D().지역[code];
    if (!d || d.가게수 < D().min) return null;            // 가게가 너무 적은 동은 비율이 흔들려 칠하지 않음
    return d[state.metric];
  }
  function bins() {
    if (state.cat) return { cuts: [0.5, 0.8, 1.25, 2], colors: SEQ, labels: ['0.5↓', '0.8', '1.25', '2', '2↑'] };
    const vals = Object.keys(D().지역).map(valueOf).filter((v) => v != null).sort((a, b) => a - b);
    const q = (p) => vals[Math.min(vals.length - 1, Math.floor(p * vals.length))];
    if (METRIC[state.metric].div) {
      const cuts = [-5, -1.5, 1.5, 5];
      return { cuts, colors: DIV, labels: ['−5↓', '−1.5', '±', '+1.5', '+5↑'] };
    }
    const cuts = [q(0.2), q(0.4), q(0.6), q(0.8)];
    const d = METRIC[state.metric].d;
    return { cuts, colors: SEQ, labels: [`~${fmt(cuts[0], d)}`, fmt(cuts[1], d), fmt(cuts[2], d), fmt(cuts[3], d), `${fmt(cuts[3], d)}~`] };
  }
  let B = null;
  const colorOf = (v) => {
    if (v == null) return NA;
    let i = 0;
    while (i < B.cuts.length && v >= B.cuts[i]) i++;
    return B.colors[i];
  };

  function paint() {
    B = bins();
    layer.setStyle((f) => {
      const sel = f.properties.c === state.dong;
      return { fillColor: colorOf(valueOf(f.properties.c)), fillOpacity: 0.72, color: sel ? '#FFD400' : '#111111', opacity: sel ? 1 : 0.75, weight: sel ? 3 : (state.level === 'gu' ? 0.9 : 0.6) };
    });
    if (state.dong) layer.eachLayer((l) => { if (l.feature.properties.c === state.dong) l.bringToFront(); });
    const title = state.cat ? `${esc(state.cat)} 특화도(서울 평균=1)` : METRIC[state.metric].name;
    $('legend').innerHTML = `<div class="lt">${title}</div><div class="bins">${B.colors.map((c) => `<i style="background:${c}"></i>`).join('')}</div>
      <div class="lab">${B.labels.map((l) => `<span>${l}</span>`).join('')}</div>
      <div class="na"><i></i>${state.cat ? '그 업종 가게 3곳 미만' : state.level === 'gu' ? '자료 없음' : '가게 20곳 미만'}</div>`;
  }

  function tip(f) {
    const c = f.properties.c, d = D().지역[c];
    if (!d) return `<b>${esc(f.properties.n)}</b><br>자료 없음`;
    if (state.cat) {
      const r = catRow(c, state.cat);
      return `<b>${esc(d.행정동)}</b><br>${esc(state.cat)} ${r ? int(r[1]) : 0}곳 · 특화도 ${r ? fmt(r[4], 2) : '–'}`;
    }
    return `<b>${esc(d.행정동)}</b><br>가게 ${int(d.가게수)}곳 · ${METRIC[state.metric].name.split('(')[0]} ${fmt(d[state.metric])}`;
  }

  // ---------- 업종 표(머리글을 눌러 정렬) ----------
  // 고르지 않은 칸 ▲▼, 고른 칸 내림차순 △▼(아래가 채워짐), 오름차순 ▲▽(위가 채워짐)
  const COLS = [['업종', '업종'], ['가게', '가게'], ['개업', '개업'], ['폐업', '폐업'], ['lq', '특화도']];
  state.sort = { key: 'lq', dir: 'desc' };
  let detailRows = null;
  function sortVal(r, k) { const v = r[k]; return v == null ? null : v; }
  function renderTable() {
    if (!detailRows) return;
    const { code, rows, hi, lo } = detailRows;
    const { key, dir } = state.sort;
    const sorted = [...rows].sort((a, b) => {
      const x = sortVal(a, key), y = sortVal(b, key);
      if (x == null && y == null) return 0;
      if (x == null) return 1;                       // 값 없는 칸은 늘 맨 아래
      if (y == null) return -1;
      const c = typeof x === 'string' ? x.localeCompare(y, 'ko') : x - y;
      return dir === 'desc' ? -c : c;
    });
    const head = COLS.map(([k, label]) => {
      const on = k === key;
      const up = on && dir === 'desc' ? '△' : '▲', dn = on && dir === 'asc' ? '▽' : '▼';
      const aria = on ? (dir === 'desc' ? '내림차순' : '오름차순') : '정렬 안 함';
      return `<th aria-sort="${on ? (dir === 'desc' ? 'descending' : 'ascending') : 'none'}"><button type="button" class="sort${on ? ' on' : ''}" data-k="${k}" aria-label="${label} ${aria}"><span class="arr"><i>${up}</i><i>${dn}</i></span>${label}</button></th>`;
    }).join('');
    const body = sorted.map((r) => {
      const tags = `${isRise(code, r.업종) ? '<span class="tag rise">뜸</span>' : ''}${isWarn(code, r.업종) ? '<span class="tag warn">경보</span>' : ''}${r.aca ? '<span class="tag src">나이스</span>' : ''}`;
      const cls = hi.has(r.업종) ? 'lq hi' : lo.has(r.업종) ? 'lq lo' : 'lq';
      return `<tr><td>${esc(r.업종)}${tags}</td><td>${int(r.가게)}</td><td>${int(r.개업)}</td><td>${r.폐업 == null ? '–' : int(r.폐업)}</td><td class="${cls}">${r.lq == null ? '–' : fmt(r.lq, 2)}</td></tr>`;
    }).join('');
    $('dtable').innerHTML = `<table class="t"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    $('dtable').querySelectorAll('button.sort').forEach((bt) => bt.addEventListener('click', () => {
      const k = bt.dataset.k;
      state.sort = state.sort.key === k ? { key: k, dir: state.sort.dir === 'desc' ? 'asc' : 'desc' } : { key: k, dir: 'desc' };
      renderTable();
    }));
  }

  // ---------- 동네 상세 ----------
  function openDong(code, zoom) {
    state.dong = code;
    const d = D().지역[code];
    if (!d) return;
    // 업종 표: 인허가 업종 + 학원·교습소(나이스, 폐원 기록이 없어 폐업은 '–')
    let rows = (D().지역_업종[code] || []).map((r) => ({ 업종: r[0], 가게: r[1], 개업: r[2], 폐업: r[3], lq: r[4] }));
    if (d.학원 != null && d.학원 > 0) {
      const all = Object.values(D().지역);
      const acaAll = all.reduce((a, x) => a + (x.학원 || 0), 0), shopAll = all.reduce((a, x) => a + x.가게수, 0);
      const lq = acaAll ? (d.학원 / (d.가게수 + d.학원)) / (acaAll / (shopAll + acaAll)) : null;
      rows.push({ 업종: '학원·교습소', 가게: d.학원, 개업: d.학원_최근12개월_신규, 폐업: null, lq, aca: true });
    }
    // 특화도 상위 3개는 빨강, 하위 3개는 파랑(가게 5곳 이상, '기타' 제외)
    const ranked = rows.filter((r) => r.lq != null && r.가게 >= 5 && r.업종 !== '기타').sort((a, b) => b.lq - a.lq);
    const hi = new Set(ranked.slice(0, 3).map((r) => r.업종));
    const lo = new Set(ranked.length > 6 ? ranked.slice(-3).map((r) => r.업종) : []);
    detailRows = { code, rows, hi, lo };
    $('detail').innerHTML = `<button class="close" type="button" id="close">닫기</button>
      <h2>${esc(d.행정동)}</h2><div class="sub">인허가 가게 ${int(d.가게수)}곳 · 최근 12개월</div>
      <div class="brief"><h3>이 ${UNIT() === '구' ? '구' : '동네'} 한눈에</h3>${describe(code, d)}</div>
      <div class="kpis">
        <div class="kpi"><b>${fmt(d.개업률)}%</b><span>개업률</span></div>
        <div class="kpi"><b>${fmt(d.폐업률)}%</b><span>폐업률</span></div>
        <div class="kpi"><b class="${d.순증률 > 0 ? 'up' : d.순증률 < 0 ? 'dn' : ''}">${sign(d.순증률)}%</b><span>순증률</span></div>
        <div class="kpi"><b>${fmt(d.회전율, 0)}%</b><span>교체(회전율)</span></div>
        <div class="kpi"><b>${fmt(d['1년생존율'])}%</b><span>1년 생존율</span></div>
        <div class="kpi"><b>${fmt(T.서울_전체.회전율, 0)}%</b><span>서울 평균 교체</span></div>
      </div>
      ${d.임대상권 ? `<p class="rent">소규모 상가 임대료 <b>${fmt(d.임대료_소규모)}천원/㎡</b>(월, 전년 대비 ${sign(d.임대료_전년비)}%) · 공실률 ${fmt(d.공실률_소규모)}%<br><span>한국부동산원 ${state.level === 'gu' ? `구 안 상권(${esc(d.임대상권)}) 평균` : `'${esc(d.임대상권)}' 상권 값을 가까운 동에 붙인 근사치`}, ${esc(String(d.임대분기).slice(0, 4))}년 ${esc(String(d.임대분기).slice(5))}분기</span></p>` : ''}
      <div id="dtable"></div>
      <p class="tab-note">특화도: 그 업종 비중이 서울 평균의 몇 배인지. <span class="lq hi">빨강</span>은 이 지역에서 가장 몰린 3개, <span class="lq lo">파랑</span>은 가장 적은 3개. 학원·교습소는 나이스 자료라 개업은 최근 12개월 새로 연 곳, 폐업 기록은 없습니다.</p>`;
    renderTable();
    $('detail').hidden = false;
    $('close').onclick = () => { state.dong = null; $('detail').hidden = true; paint(); };
    paint();
    if (zoom) {
      layer.eachLayer((l) => { if (l.feature.properties.c === code) map.fitBounds(l.getBounds(), { paddingTopLeft: [window.innerWidth > 720 ? document.querySelector('.panel').offsetWidth + 40 : 20, 20], maxZoom: state.level === 'gu' ? 13 : 14 }); });
    }
    $('detail').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  // ---------- 지역 한눈에(자동 해석) ----------
  // 숫자를 서울 기준과 비교해, 해당되는 것만 골라 '- ' 항목으로 쓴다. 인구 자료(T.인구)가 있으면 인구 해석도 붙인다.
  const pct = (arr, v) => (arr.length ? arr.filter((x) => x <= v).length / arr.length : 0.5);
  const josa = (w, a, b) => { const c = w.charCodeAt(w.length - 1); return w + ((c - 0xac00) % 28 && c >= 0xac00 ? a : b); };
  const GROUP_OF = {};
  FAMILY.forEach(([fam, list]) => list.forEach((c) => (GROUP_OF[c] = fam)));
  // 상권 성격을 가르는 업종 묶음
  const THEMES = [
    ['저녁·술자리', ['술집', '유흥·단란주점', '고기구이', '해산물·횟집', '노래방', '코인노래방']],
    ['카페·디저트', ['카페·음료', '디저트·베이커리']],
    ['외식(점심)', ['한식', '분식', '중식', '일식', '양식', '아시아 음식', '치킨·버거·피자']],
    ['주거 생활', ['반찬·즉석식품', '정육점', '식료품점', '슈퍼·담배가게', '세탁소', '코인빨래방', '미용실', '이발소·바버샵']],
    ['뷰티', ['네일샵', '피부관리실', '메이크업', '피부·성형의원']],
    ['의료', ['의원', '치과의원', '한의원', '병원', '약국', '안경점']],
    ['운동·여가', ['헬스·PT', '필라테스·요가', '체육도장', '골프연습장', 'PC방', 'PC방·오락', '인형뽑기·오락실']],
    ['반려동물', ['동물병원', '반려동물 서비스']],
    ['관광·숙박', ['숙박', '외국인 민박', '호텔']],
  ];
  function themeShares(code, lv) {
    const rows = (lv === 'gu' ? T.시군구.지역_업종 : T.행정동_업종)[code] || [];
    const tot = rows.reduce((a, r) => a + r[1], 0) || 1;
    const out = {};
    THEMES.forEach(([t, cats]) => { out[t] = rows.filter((r) => cats.includes(r[0])).reduce((a, r) => a + r[1], 0) / tot; });
    return out;
  }
  let CITY_THEME = null;
  function cityTheme() {
    if (CITY_THEME) return CITY_THEME;
    const tot = T.업종.reduce((a, r) => a + r.가게수, 0);
    CITY_THEME = {};
    THEMES.forEach(([t, cats]) => { CITY_THEME[t] = T.업종.filter((r) => cats.includes(r.업종)).reduce((a, r) => a + r.가게수, 0) / tot; });
    return CITY_THEME;
  }
  function entropy(rows) {      // 업종 다양성(0~1): 여러 업종이 고르게 섞일수록 1에 가깝다
    const xs = rows.filter((r) => r[0] !== '기타' && r[1] > 0), tot = xs.reduce((a, r) => a + r[1], 0);
    if (!tot || xs.length < 2) return 0;
    return -xs.reduce((a, r) => { const p = r[1] / tot; return a + p * Math.log(p); }, 0) / Math.log(xs.length);
  }
  const li = (s) => `<li>${s}</li>`;
  const sec = (title, items) => (items.length ? `<div class="bsec"><h4>${title}</h4><ul>${items.map(li).join('')}</ul></div>` : '');

  function describe(code, d) {
    if (state.cat) return describeCat(code, d, state.cat);
    const rows = (D().지역_업종[code] || []);
    const named = rows.filter((r) => r[0] !== '기타');
    const minN = state.level === 'gu' ? 30 : 8;
    const ct = cityTheme(), th = themeShares(code, state.level);
    // 상권 유형(서울 평균 대비 가장 두드러진 묶음 1~2개)
    const lifts = THEMES.map(([t]) => [t, ct[t] ? th[t] / ct[t] : 0, th[t]]).filter((x) => x[2] >= 0.03).sort((a, b) => b[1] - a[1]);
    const types = lifts.filter((x) => x[1] >= 1.2).slice(0, 2);
    const tag = types.length ? types.map((x) => `<span class="ttag">${x[0]} 상권</span>`).join('') : '<span class="ttag">고른 생활 상권</span>';

    const A = [];   // 업종 구성
    const spec = named.filter((r) => r[1] >= minN && r[4] >= 1.4 && !LODGING.has(r[0])).sort((a, b) => b[4] - a[4]).slice(0, 3);
    if (spec.length) A.push(`<b>${josa(spec.map((r) => r[0]).join('·'), '이', '가')}</b> 서울 평균보다 몰려 있습니다(${spec.map((r) => `${r[0]} ${fmt(r[4], 1)}배`).join(', ')}).`);
    const thin = named.filter((r) => r[1] >= 0 && r[4] != null && r[4] <= 0.6 && (T.업종.find((x) => x.업종 === r[0]) || {}).가게수 >= 2000).sort((a, b) => a[4] - b[4]).slice(0, 2);
    if (thin.length) A.push(`반대로 <b>${josa(thin.map((r) => r[0]).join('·'), '은', '는')}</b> 서울 평균의 ${thin.map((r) => `${fmt(r[4], 1)}배`).join('·')}로 드문 편입니다.`);
    const top = named[0];
    if (top) A.push(`가게 가운데 ${josa(top[0], '이', '가')} ${Math.round(top[1] / Math.max(1, d.가게수) * 100)}%로 가장 많습니다.`);
    types.forEach((x) => A.push(`${x[0]} 업종 비중이 ${Math.round(x[2] * 100)}%로 서울(${Math.round(ct[x[0]] * 100)}%)의 ${fmt(x[1], 1)}배입니다.`));
    const ent = entropy(rows), entAll = entropy(T.업종.map((r) => [r.업종, r.가게수]));
    if (ent && ent < entAll - 0.08) A.push(`업종이 몇 가지에 쏠려 있어 특색이 뚜렷한 편입니다.`);
    else if (ent > entAll + 0.03) A.push(`여러 업종이 고르게 섞인 편입니다.`);

    const B = [];   // 변화
    const turn = d.회전율 / T.서울_전체.회전율;
    B.push(turn >= 1.25 ? `가게가 <b>자주 바뀝니다</b> — 1년에 가게의 ${fmt(d.회전율, 0)}%가 새로 열거나 닫았습니다(서울 ${fmt(T.서울_전체.회전율, 0)}%).`
      : turn <= 0.8 ? `가게가 <b>오래 가는 안정된</b> 곳입니다 — 교체율 ${fmt(d.회전율, 0)}%(서울 ${fmt(T.서울_전체.회전율, 0)}%).`
      : `가게 교체 속도는 서울 평균 수준입니다(${fmt(d.회전율, 0)}%).`);
    if (Math.abs(d.순증률) >= 1) B.push(`가게 수는 1년 새 <b class="${d.순증률 > 0 ? 'up' : 'dn'}">${sign(d.순증률)}%</b> ${d.순증률 > 0 ? '늘었습니다' : '줄었습니다'}.`);
    const net = named.map((r) => [r[0], r[2] - r[3], r[2], r[3]]).filter((x) => Math.abs(x[1]) >= (state.level === 'gu' ? 5 : 2));
    const gain = net.filter((x) => x[1] > 0).sort((a, b) => b[1] - a[1]).slice(0, 3), loss = net.filter((x) => x[1] < 0).sort((a, b) => a[1] - b[1]).slice(0, 3);
    if (gain.length) B.push(`늘어난 업종: ${gain.map((x) => `${x[0]} +${x[1]}`).join(', ')}`);
    if (loss.length) B.push(`줄어든 업종: ${loss.map((x) => `${x[0]} ${x[1]}`).join(', ')}`);
    const ups = D().뜨는.filter((x) => x.행정동코드 === code);
    const upsN = ups.filter((x) => !LODGING.has(x.업종)).slice(0, 3), upsL = ups.filter((x) => LODGING.has(x.업종));
    if (upsN.length) B.push(`<b class="up">뜨는 업종</b>: ${upsN.map((x) => `${x.업종}(6개월 ${int(x.개업_최근6개월)}곳 개업, 서울 흐름대로면 ${fmt(x.개업_기대)}곳)`).join(', ')}`);
    if (upsL.length) B.push(`숙박·민박 개업도 크게 늘었는데, 관광 수요와 생활숙박시설 신고 정리가 함께 반영된 숫자입니다.`);

    const C = [];   // 위험·비용
    const ws = D().경보.filter((x) => x.행정동코드 === code).slice(0, 3);
    if (ws.length) C.push(`<b class="dn">폐업 경보</b>: ${ws.map((x) => `${x.업종}(폐업 ${int(x.폐업_12개월)}곳, 서울 폐업률대로면 ${fmt(x.폐업_기대)}곳)`).join(', ')}`);
    const sAll = T.업종.reduce((a, r) => a + (r['1년생존율'] || 0) * (r.생존표본 || 0), 0) / Math.max(1, T.업종.reduce((a, r) => a + (r.생존표본 || 0), 0));
    if (d['1년생존율'] != null && d.생존표본 >= 30) {
      const gap = d['1년생존율'] - sAll;
      C.push(`새로 연 가게의 1년 생존율 ${fmt(d['1년생존율'])}% — 서울(${fmt(sAll)}%)보다 ${Math.abs(gap) < 1.5 ? '비슷합니다' : gap > 0 ? '<b class="up">높습니다</b>' : '<b class="dn">낮습니다</b>'}.`);
    }
    if (d.임대료_소규모) {
      const p = pct(T._rent[state.level], d.임대료_소규모);
      const lv = p >= 0.8 ? '<b>비싼 편</b>' : p <= 0.2 ? '<b>싼 편</b>' : '중간 수준';
      C.push(`소규모 상가 임대료 ㎡당 월 ${fmt(d.임대료_소규모)}천원 — 서울 상권 가운데 ${lv}${d.임대료_전년비 != null ? `, 1년 새 ${sign(d.임대료_전년비)}%` : ''}. 공실률 ${fmt(d.공실률_소규모)}%${d.공실률_소규모 >= 10 ? '로 빈 가게가 많은 편' : ''}.`);
    }

    const P = [];   // 사람(인구·유동·직장·소득) — 자료가 있으면
    const pop = T.인구 && T.인구[state.level] && T.인구[state.level][code];
    if (pop) P.push(...popInsights(pop, th, ct));
    if (d.학원 != null && d.학원 > 0) {
      const p = pct(T._aca[state.level], d.학원 / Math.max(1, d.가게수));
      if (p >= 0.75) P.push(`학원·교습소 ${int(d.학원)}곳 — 가게 수에 비해 많은 <b>교육 수요</b> 지역입니다.`);
    }

    return `<div class="btype">${tag}</div>${sec('업종 구성', A)}${sec('변화', B)}${sec('사람', P)}${sec('위험·비용', C)}`;
  }

  // 업종을 고른 상태: 그 업종만의 한눈에
  function describeCat(code, d, cat) {
    const r = (D().지역_업종[code] || []).find((x) => x[0] === cat);
    const sc = T.업종.find((x) => x.업종 === cat) || {};
    const items = [], more = [];
    if (!r || !r[1]) return `<div class="btype"><span class="ttag">${esc(cat)}</span></div><ul><li>이 지역에는 ${esc(cat)} 가게가 없습니다.</li></ul>`;
    const all = Object.entries(D().지역_업종).map(([c, rs]) => [c, (rs.find((x) => x[0] === cat) || [])[4]]).filter((x) => x[1] != null);
    const rank = all.sort((a, b) => b[1] - a[1]).findIndex((x) => x[0] === code) + 1;
    items.push(`${esc(cat)} <b>${int(r[1])}곳</b> — 이 지역 가게의 ${fmt(r[1] / Math.max(1, d.가게수) * 100, 1)}%, 특화도 <b>${fmt(r[4], 2)}배</b>(서울 ${all.length}개 ${UNIT()} 중 ${rank}위).`);
    const or = r[1] ? r[2] / r[1] * 100 : null, cr = r[1] ? r[3] / r[1] * 100 : null;
    items.push(`최근 12개월 개업 ${int(r[2])}곳 · 폐업 ${int(r[3])}곳 — 개업률 약 ${fmt(or, 1)}%(서울 ${fmt(sc.개업률, 1)}%), 폐업률 약 ${fmt(cr, 1)}%(서울 ${fmt(sc.폐업률, 1)}%).`);
    const net = r[2] - r[3];
    items.push(net > 0 ? `1년 새 <b class="up">${net}곳 늘었습니다</b>.` : net < 0 ? `1년 새 <b class="dn">${-net}곳 줄었습니다</b>.` : `1년 새 가게 수는 그대로입니다.`);
    const up = D().뜨는.find((x) => x.행정동코드 === code && x.업종 === cat);
    if (up) items.push(`<b class="up">뜨는 신호</b> — 최근 6개월 ${int(up.개업_최근6개월)}곳 개업(서울 흐름대로면 ${fmt(up.개업_기대)}곳).`);
    const w = D().경보.find((x) => x.행정동코드 === code && x.업종 === cat);
    if (w) items.push(`<b class="dn">폐업 경보</b> — 최근 12개월 ${int(w.폐업_12개월)}곳 폐업(서울 폐업률대로면 ${fmt(w.폐업_기대)}곳).`);
    if (r[7] != null && sc['1년생존율'] != null) items.push(`1년 생존율 ${fmt(r[7])}%(서울 ${esc(cat)} ${fmt(sc['1년생존율'])}%).`);
    if (sc.개업_전년비 != null && sc.개업_1년전6개월 >= 20) more.push(`서울 전체로는 ${esc(cat)} 개업이 1년 전보다 ${fmt(Math.abs(sc.개업_전년비), 0)}% ${sc.개업_전년비 >= 0 ? '늘었습니다' : '줄었습니다'}.`);
    // 같은 업종이 많은 이웃(구 안의 동, 또는 다른 구)
    const peers = all.slice(0, 5).filter((x) => x[0] !== code).slice(0, 3).map((x) => D().지역[x[0]] && D().지역[x[0]].행정동).filter(Boolean);
    if (peers.length) more.push(`${esc(josa(cat, '이', '가'))} 가장 몰린 ${UNIT()}: ${peers.map(esc).join(', ')}.`);
    const pop = T.인구 && T.인구[state.level] && T.인구[state.level][code];
    if (pop) more.push(...catPop(cat, pop));
    return `<div class="btype"><span class="ttag">${esc(cat)}</span><span class="tsub">업종 전체를 보려면 위에서 '업종 전체'를 고르세요</span></div>${sec('이 지역의 ' + esc(cat), items)}${sec('함께 볼 것', more)}`;
  }

  // 인구 자료 해석(자료가 들어오면 쓰임)
  function popInsights(p, th, ct) {
    const out = [], S = T.인구.서울;
    const rel = (k) => (S[k] ? p[k] / S[k] : null);
    if (p.상주 != null) out.push(`상주인구 ${int(p.상주)}명, 가구 ${int(p.가구)}곳${p.가구 ? ` (가구당 ${fmt(p.상주 / p.가구, 1)}명)` : ''}.`);
    const ageTop = p.상주연령 && Object.entries(p.상주연령).map(([a, v]) => [a, v / Math.max(1, p.상주), S.상주연령[a] / Math.max(1, S.상주)]).sort((a, b) => b[1] / b[2] - a[1] / a[2])[0];
    if (ageTop && ageTop[1] / ageTop[2] >= 1.15) out.push(`주민 가운데 <b>${ageTop[0]}</b> 비중이 ${fmt(ageTop[1] * 100, 0)}%로 서울(${fmt(ageTop[2] * 100, 0)}%)보다 높습니다.`);
    if (p.직장 != null && p.상주) {
      const r = p.직장 / p.상주, rs = S.직장 / S.상주;
      out.push(r >= rs * 1.5 ? `직장인구가 상주인구의 ${fmt(r, 1)}배인 <b>업무 지역</b>입니다 — 점심·퇴근길 수요가 중심.`
        : r <= rs * 0.6 ? `직장인구가 적은 <b>주거 지역</b>입니다(직장인구/상주인구 ${fmt(r, 2)}).` : `직장인구와 상주인구가 섞인 지역입니다.`);
    }
    if (p.유동 != null) {
      const rr = rel('유동');
      out.push(`하루 유동인구는 서울 ${UNIT()} 평균의 ${fmt(rr, 1)}배${rr >= 1.5 ? '로 <b>사람이 많이 오가는</b> 곳' : rr <= 0.6 ? '로 한산한 편' : ''}입니다.`);
      if (p.유동시간) {
        const tb = Object.entries(p.유동시간).map(([t, v]) => [t, v / Math.max(1, p.유동), S.유동시간[t] / Math.max(1, S.유동)]).sort((a, b) => b[1] / b[2] - a[1] / a[2])[0];
        if (tb && tb[1] / tb[2] >= 1.1) out.push(`유동인구가 특히 <b>${tb[0]}</b>에 몰립니다(서울 대비 ${fmt(tb[1] / tb[2], 1)}배).`);
      }
      if (p.유동주말 != null && S.유동주말) {
        const w = p.유동주말 / S.유동주말;
        if (w >= 1.1) out.push(`주말 유동 비중이 서울보다 높은 <b>주말·나들이형</b> 상권입니다.`);
        else if (w <= 0.92) out.push(`평일 유동 비중이 높은 <b>평일형</b> 상권입니다.`);
      }
      if (p.유동연령) {
        const ya = Object.entries(p.유동연령).map(([a, v]) => [a, v / Math.max(1, p.유동), S.유동연령[a] / Math.max(1, S.유동)]).sort((a, b) => b[1] / b[2] - a[1] / a[2])[0];
        if (ya && ya[1] / ya[2] >= 1.12) out.push(`오가는 사람 중 <b>${ya[0]}</b>가 서울보다 많습니다(${fmt(ya[1] * 100, 0)}% vs ${fmt(ya[2] * 100, 0)}%).`);
      }
      if (p.유동 && d_shop(p)) out.push(`유동인구 1만 명당 가게 ${fmt(d_shop(p), 1)}곳(서울 ${fmt(S.가게당유동 ? 1e4 / S.가게당유동 : null, 1)}곳) — ${d_shop(p) * S.가게당유동 / 1e4 >= 1.3 ? '수요에 비해 가게가 많아 경쟁이 센 편' : d_shop(p) * S.가게당유동 / 1e4 <= 0.75 ? '수요에 비해 가게가 적은 편' : '서울 평균 수준'}.`);
    }
    if (p.소득 != null) {
      const r = rel('소득');
      out.push(`월평균 소득 ${fmt(p.소득 / 1e4, 0)}만원 — 서울 평균의 ${fmt(r, 2)}배${r >= 1.2 ? '로 <b>소득이 높은</b> 지역' : r <= 0.85 ? '로 소득이 낮은 편' : ''}.`);
    }
    if (p.지출 != null && p.지출구성) {
      const sp = Object.entries(p.지출구성).map(([k, v]) => [k, v / Math.max(1, p.지출), (S.지출구성[k] || 0) / Math.max(1, S.지출)]).sort((a, b) => b[1] / b[2] - a[1] / a[2])[0];
      if (sp && sp[1] / sp[2] >= 1.15) out.push(`지출 가운데 <b>${sp[0]}</b> 비중이 서울보다 높습니다.`);
    }
    if (p.집객 && Object.keys(p.집객).length) {
      const fs = Object.entries(p.집객).filter((x) => x[1] > 0).sort((a, b) => b[1] - a[1]).slice(0, 4);
      if (fs.length) out.push(`주변 집객시설: ${fs.map(([k, v]) => `${k} ${int(v)}`).join(', ')}.`);
    }
    if (p.아파트세대) out.push(`아파트 ${int(p.아파트단지)}개 단지·${int(p.아파트세대)}세대${p.아파트시가 ? `, 평균 시가 ${fmt(p.아파트시가 / 1e8, 1)}억원` : ''}.`);
    return out;
  }
  function d_shop(p) { return p.가게 && p.유동 ? p.가게 / p.유동 * 1e4 : null; }
  // 업종과 사람 자료 연결(자료가 들어오면 쓰임)
  const CAT_AGE = { '학원·교습소': '10대', '카페·음료': '20대', '디저트·베이커리': '20대', '술집': '30대', 'PC방': '10대', '코인노래방': '10대', '네일샵': '20대', '피부관리실': '30대', '반찬·즉석식품': '40대', '정육점': '50대', '한의원': '60대 이상', '의원': '60대 이상', '약국': '60대 이상', '필라테스·요가': '30대', '헬스·PT': '30대' };
  function catPop(cat, p) {
    const out = [], S = T.인구.서울, a = CAT_AGE[cat];
    if (a && p.유동연령 && S.유동연령[a]) {
      const r = (p.유동연령[a] / p.유동) / (S.유동연령[a] / S.유동);
      out.push(`${esc(cat)}의 주 고객층(${a}) 유동 비중이 서울의 ${fmt(r, 2)}배 — ${r >= 1.15 ? '수요층이 두터운 편' : r <= 0.85 ? '수요층이 얇은 편' : '서울 평균 수준'}.`);
    }
    if (['술집', '유흥·단란주점', '고기구이', '노래방'].includes(cat) && p.유동시간) {
      const k = Object.keys(p.유동시간).find((t) => /17|21/.test(t));
      if (k) out.push(`저녁 시간대 유동 비중이 서울의 ${fmt((p.유동시간[k] / p.유동) / (S.유동시간[k] / S.유동), 2)}배입니다.`);
    }
    if (['한식', '분식', '중식', '일식', '카페·음료'].includes(cat) && p.직장 && p.상주) out.push(`직장인구 ${int(p.직장)}명(상주인구의 ${fmt(p.직장 / p.상주, 1)}배) — 점심 수요의 크기.`);
    return out;
  }
  const riseSet = new Set(), warnSet = new Set();
  const isRise = (c, g) => riseSet.has(c + '|' + g);
  const isWarn = (c, g) => warnSet.has(c + '|' + g);

  // ---------- 탭 ----------
  function renderTab() {
    const body = $('tab-body'), note = $('tab-note');
    if (state.tab === 'up') {
      note.textContent = `최근 6개월(${T.최근6개월.join('~')}) 개업이 서울 업종 흐름보다 유독 몰린 ${UNIT()}·업종입니다. 숙박·민박·호텔은 관광·제도 영향이 커서 뒤에 모았습니다.`;
      body.innerHTML = list([...D().뜨는.filter((x) => !LODGING.has(x.업종)), ...D().뜨는.filter((x) => LODGING.has(x.업종))], (x) => `<span class="nm">${esc(x.행정동)}<small>${esc(x.업종)}</small></span><span class="v up">${int(x.개업_최근6개월)}곳 개업</span>
        <span class="s">서울 흐름대로라면 ${fmt(x.개업_기대)}곳 · 지금 ${int(x.가게수)}곳 · 특화도 ${fmt(x.특화도_LQ, 2)}${LODGING.has(x.업종) ? ' · 관광 수요·생활숙박시설 신고 영향 함께' : ''}</span>`);
    } else if (state.tab === 'cl') {
      note.textContent = '서울 같은 업종 폐업률로 기대되는 수보다 최근 12개월 폐업이 뚜렷이 많은 곳입니다.';
      body.innerHTML = list(D().경보, (x) => `<span class="nm">${esc(x.행정동)}<small>${esc(x.업종)}</small></span><span class="v dn">${int(x.폐업_12개월)}곳 폐업</span>
        <span class="s">서울 폐업률대로라면 ${fmt(x.폐업_기대)}곳 · 폐업률 ${fmt(x.폐업률)}% · 지금 ${int(x.가게수)}곳</span>`) || '<p class="tab-note">지금은 뚜렷한 경보가 없습니다.</p>';
    } else if (state.tab === 'ch') {
      note.textContent = state.level === 'gu' ? '25개 구를 서울 평균보다 가게가 자주 바뀐 순서로 늘어놓았습니다.' : '가게 50곳 이상 동네 가운데, 서울 평균 교체 속도보다 가게가 자주 바뀐 곳입니다.';
      body.innerHTML = list(D().교체, (x) => `<span class="nm">${esc(x.행정동)}</span><span class="v">${fmt(x.회전율, 0)}%</span>
        <span class="s">개업 ${fmt(x.개업률)}% · 폐업 ${fmt(x.폐업률)}% · 가게 ${int(x.가게수)}곳 · 순증 ${sign(x.순증률)}%</span>`);
      note.textContent += ` 서울 평균 교체는 ${fmt(T.서울_전체.회전율, 0)}%/년입니다.`;
    } else {
      note.textContent = `서울 전체 업종별 흐름(가게 200곳 이상 업종). 개업 전년비는 최근 6개월과 1년 전 같은 6개월 비교입니다.`;
      const rows = T.업종.filter((r) => r.업종 !== '기타' && r.가게수 >= 200 && (r.개업_1년전6개월 || 0) >= 20)
        .sort((a, b) => (b.개업_전년비 ?? -999) - (a.개업_전년비 ?? -999));
      body.innerHTML = `<table class="t"><thead><tr><th>업종</th><th>가게</th><th>순증</th><th>개업 증감</th><th>생존</th></tr></thead><tbody>${
        rows.map((r) => `<tr data-cat="${esc(r.업종)}" style="cursor:pointer"><td>${esc(r.업종)}</td><td>${int(r.가게수)}</td>
          <td class="${r.순증률 > 0 ? 'up' : r.순증률 < 0 ? 'dn' : ''}">${sign(r.순증률)}%</td>
          <td class="${r.개업_전년비 > 0 ? 'up' : r.개업_전년비 < 0 ? 'dn' : ''}">${sign(r.개업_전년비, 0)}%</td><td>${fmt(r['1년생존율'])}%</td></tr>`).join('')}</tbody></table>
        <p class="tab-note">줄을 누르면 그 업종이 몰린 동네를 지도에 칠합니다.</p>`;
      body.querySelectorAll('tr[data-cat]').forEach((tr) => tr.addEventListener('click', () => { state.cat = tr.dataset.cat; $('cat').value = state.cat; paint(); }));
      return;
    }
    body.querySelectorAll('li[data-c]').forEach((li) => li.addEventListener('click', () => {
      if (li.dataset.g) { state.cat = li.dataset.g; $('cat').value = state.cat; }
      openDong(li.dataset.c, true);
    }));
  }
  function list(arr, fn) {
    if (!arr || !arr.length) return '';
    return `<ol class="rank">${arr.slice(0, 60).map((x) => `<li data-c="${x.행정동코드}" ${x.업종 ? `data-g="${esc(x.업종)}"` : ''}>${fn(x)}</li>`).join('')}</ol>`;
  }

  // ---------- 시작 ----------
  Promise.all([fetch('data/trend/서울.json').then((r) => r.json()), fetch('data/boundary_web/행정동_서울.json').then((r) => r.json()),
    fetch('data/boundary_web/시군구_서울.json').then((r) => r.json())]).then(([t, g, gg]) => {
    T = t; geo = { dong: g, gu: gg };
    [...T.뜨는_동네업종, ...T.시군구.뜨는].forEach((x) => riseSet.add(x.행정동코드 + '|' + x.업종));
    [...T.폐업경보, ...T.시군구.경보].forEach((x) => warnSet.add(x.행정동코드 + '|' + x.업종));
    const rents = (o) => Object.values(o).map((x) => x.임대료_소규모).filter((v) => v).sort((a, b) => a - b);
    T._rent = { gu: rents(T.시군구.지역), dong: rents(T.행정동) };
    const acas = (o) => Object.values(o).map((x) => (x.학원 || 0) / Math.max(1, x.가게수)).sort((a, b) => a - b);
    T._aca = { gu: acas(T.시군구.지역), dong: acas(T.행정동) };
    $('asof').textContent = `기준: ${T.최근12개월[0]} ~ ${T.최근12개월[1]} (최근 12개월) · 인허가 자료`;
    const have = new Set(T.업종.filter((r) => r.업종 !== '기타').map((r) => r.업종));
    const used = new Set();
    let opts = '<option value="">업종 전체</option>';
    FAMILY.forEach(([fam, list]) => {
      const xs = list.filter((c) => have.has(c));
      xs.forEach((c) => used.add(c));
      if (xs.length) opts += `<optgroup label="${fam}">${xs.map((c) => `<option>${esc(c)}</option>`).join('')}</optgroup>`;
    });
    const rest = [...have].filter((c) => !used.has(c));
    if (rest.length) opts += `<optgroup label="그 밖">${rest.map((c) => `<option>${esc(c)}</option>`).join('')}</optgroup>`;
    $('cat').innerHTML = opts;
    ['gu', 'dong'].forEach((lv) => {
      layers[lv] = L.geoJSON(geo[lv], {
        onEachFeature: (f, l) => {
          l.bindTooltip(() => tip(f), { sticky: true, className: 'dong-tip' });
          l.on('click', () => openDong(f.properties.c, false));
        },
      });
    });
    layer = layers.gu.addTo(map);
    map.fitBounds(layer.getBounds(), { paddingTopLeft: [window.innerWidth > 720 ? document.querySelector('.panel').offsetWidth + 30 : 0, 10] });
    setLevelButton();
    paint(); renderTab();
    $('loading').hidden = true;
  }).catch(() => { $('loading').textContent = '자료를 불러오지 못했습니다. 새로고침해 주세요.'; });

  $('metric').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.metric = b.dataset.m; state.cat = ''; $('cat').value = '';
    $('metric').querySelectorAll('button').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
    paint();
  });
  function setLevelButton() {
    const b = $('level');
    b.innerHTML = state.level === 'gu' ? '<b>시군구</b><span>눌러서 읍면동으로</span>' : '<b>읍면동</b><span>눌러서 시군구로</span>';
    b.setAttribute('aria-label', `지역 단위 ${state.level === 'gu' ? '시군구' : '읍면동'}, 눌러서 바꾸기`);
  }
  $('level').addEventListener('click', () => {
    state.level = state.level === 'gu' ? 'dong' : 'gu';
    map.removeLayer(layer);
    layer = layers[state.level].addTo(map);
    state.dong = null; $('detail').hidden = true;
    setLevelButton(); paint(); renderTab();
  });
  $('cat').addEventListener('change', (e) => { state.cat = e.target.value; paint(); if (state.dong) openDong(state.dong, false); });
  $('tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.tab = b.dataset.t;
    $('tabs').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    renderTab();
  });
})();
