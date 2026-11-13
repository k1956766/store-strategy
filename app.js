(() => {
  'use strict';
  // 업종 15개를 색 묶음 7개 + 기타로(색은 고정 순서, 필터로 바뀌지 않음)
  const GROUPS = [
    { key: 'g1', name: '한식', cats: ['한식', '고기구이', '해산물·횟집'] },
    { key: 'g2', name: '카페·디저트', cats: ['카페·음료', '디저트·베이커리'] },
    { key: 'g3', name: '일식·중식·아시아', cats: ['일식', '중식', '아시아 음식'] },
    { key: 'g4', name: '분식·치킨·버거', cats: ['분식', '치킨·버거·피자'] },
    { key: 'g5', name: '양식', cats: ['양식'] },
    { key: 'g6', name: '편의점·오락', cats: ['편의점', 'PC방·오락'] },
    { key: 'g7', name: '술집', cats: ['술집'] },
    { key: 'g0', name: '기타', cats: ['기타'] },
  ];
  const CAT2G = {};
  GROUPS.forEach((g) => g.cats.forEach((c) => (CAT2G[c] = g.key)));
  const groupOf = (cat) => CAT2G[cat] || 'g0';
  const SIDO = { seoul: '서울', gyeonggi: '경기', incheon: '인천' };
  const SIDO_KEY = { 서울: 'seoul', 경기: 'gyeonggi', 인천: 'incheon' };
  const PERIOD = { 14: '2주 안', 30: '1개월 안', 90: '3개월 안' };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

  const state = { region: 'all', days: 30, off: {}, showN: 30 };
  let index = null, current = [], markers = [], visible = [];
  const cache = {};

  // ---------- 지도 ----------
  const map = L.map('map', { zoomControl: false, minZoom: 8, maxZoom: 18 }).setView([37.5565, 126.99], 11);
  L.control.zoom({ position: 'topright' }).addTo(map);
  // 배경지도: 국토교통부 브이월드(키는 배포할 때 pages.yml이 넣음. 비어 있으면 OSM으로 대체)
  const VW_KEY = '';
  const hasVW = /^[0-9A-F-]{30,}$/i.test(VW_KEY);
  L.tileLayer(hasVW ? `https://api.vworld.kr/req/wmts/1.0.0/${VW_KEY}/Base/{z}/{y}/{x}.png` : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, className: 'basemap',
    attribution: hasVW ? '&copy; <a href="https://www.vworld.kr">국토교통부 브이월드</a>' : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 기여자',
  }).addTo(map);
  fetch('data/sigungu_base.json').then((r) => r.json()).then((g) => {
    L.geoJSON(g, { interactive: false, style: () => ({ color: '#5A6676', weight: 1, opacity: 0.45, fillOpacity: 0 }) }).addTo(map);
  }).catch(() => {});

  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 48, spiderfyOnMaxZoom: true, disableClusteringAtZoom: 17, chunkedLoading: true,
    iconCreateFunction: (c) => {
      const n = c.getChildCount(), s = n < 10 ? 30 : n < 100 ? 36 : n < 1000 ? 44 : 52;
      return L.divIcon({ html: `<div class="cl" style="width:${s}px;height:${s}px;font-size:${s < 40 ? 12 : 13}px">${n.toLocaleString()}</div>`, className: '', iconSize: [s, s] });
    },
  }).addTo(map);

  function popupHtml(s) {
    const g = groupOf(s.업종), q = encodeURIComponent(`${s.이름} ${s.주소}`);
    const orig = s.원업태 && s.원업태 !== s.업종 ? ` <span>신고 업태 ${esc(s.원업태)}</span>` : '';
    return `<div class="pp"><div class="pp-name">${esc(s.이름)}</div>
      <div class="pp-tag"><i style="background:var(--${g})"></i>${esc(s.업종)}${orig}</div>
      <dl><dt>인허가일</dt><dd>${esc(s.인허가일)}</dd><dt>주소</dt><dd>${esc(s.주소)}</dd><dt>업종 근거</dt><dd>${esc(s.업종근거)}</dd></dl>
      <div class="pp-links"><a href="https://map.naver.com/p/search/${q}" target="_blank" rel="noopener">네이버 지도</a><a href="https://map.kakao.com/?q=${q}" target="_blank" rel="noopener">카카오맵</a></div></div>`;
  }

  // ---------- 자료 ----------
  const loadRegion = (code) => (cache[code] ||= fetch(`data/map/${code}.json`).then((r) => r.json()).then((d) => d.가게));
  function codesFor(region) {
    if (region === 'all') return index.지역.map((r) => r.코드);
    if (region.startsWith('sido-')) return index.지역.filter((r) => r.시도 === SIDO[region.slice(5)]).map((r) => r.코드);
    return [region];
  }
  function regionName() {
    if (state.region === 'all') return '수도권';
    if (state.region.startsWith('sido-')) return SIDO[state.region.slice(5)];
    return (index.지역.find((r) => r.코드 === state.region) || {}).지역 || '';
  }
  function daysAgo(d) { const t = new Date(index.갱신일); t.setDate(t.getDate() - d); return t.toISOString().slice(0, 10); }

  async function load() {
    $('loading').hidden = false;
    try {
      const parts = await Promise.all(codesFor(state.region).map(loadRegion));
      current = parts.flat();
      $('loading').hidden = true;
      render(true);
    } catch (e) {
      $('loading').textContent = '자료를 불러오지 못했습니다. 새로고침해 주세요.';
    }
  }

  function renderLegend(rows) {
    const cnt = {};
    rows.forEach((s) => { const g = groupOf(s.업종); cnt[g] = (cnt[g] || 0) + 1; });
    $('chips').innerHTML = GROUPS.map((g) => `<button type="button" data-g="${g.key}" aria-pressed="${!state.off[g.key]}" title="${esc(g.cats.join(', '))}">
      <i style="background:var(--${g.key})"></i>${esc(g.name)}<b>${(cnt[g.key] || 0).toLocaleString()}</b></button>`).join('');
  }

  function render(fit) {
    const from = daysAgo(state.days);
    const rows = current.filter((s) => s.인허가일 >= from);
    renderLegend(rows);
    const shown = rows.filter((s) => !state.off[groupOf(s.업종)] && s.위도);
    cluster.clearLayers();
    markers = shown.map((s) => {
      const m = L.marker([s.위도, s.경도], {
        icon: L.divIcon({ className: '', html: `<div class="shop-dot" style="background:var(--${groupOf(s.업종)})"></div>`, iconSize: [12, 12] }),
        title: s.이름,
      });
      m.bindPopup(() => popupHtml(s), { maxWidth: 300 });
      m._shop = s;
      return m;
    });
    cluster.addLayers(markers);
    $('ro-k').textContent = `${regionName()} · ${PERIOD[state.days]}`;
    $('total').innerHTML = `${shown.length.toLocaleString()}<small>곳</small>`;
    if (fit && markers.length) {
      const mobile = window.innerWidth <= 720;
      map.fitBounds(L.latLngBounds(shown.map((s) => [s.위도, s.경도])), {
        maxZoom: 15,
        paddingTopLeft: mobile ? [20, 60] : [380, 30],
        paddingBottomRight: mobile ? [20, window.innerHeight * 0.52 + 70] : [330, 30],
      });
    }
    state.showN = 30;
    renderList();
  }

  function renderList() {
    const b = map.getBounds();
    visible = markers.filter((m) => b.contains(m.getLatLng())).map((m) => m._shop)
      .sort((a, c) => (a.인허가일 < c.인허가일 ? 1 : a.인허가일 > c.인허가일 ? -1 : 0));
    $('list-count').textContent = `${visible.length.toLocaleString()}곳 · 최신순`;
    if (!visible.length) {
      $('list').innerHTML = '<li class="none">이 화면에는 조건에 맞는 가게가 없습니다. 지도를 움직이거나 업종·기간을 바꿔 보세요.</li>';
      $('more').hidden = true;
      return;
    }
    $('list').innerHTML = visible.slice(0, state.showN).map((s, i) => `<li class="shop" tabindex="0" data-i="${i}">
      <i style="background:var(--${groupOf(s.업종)})"></i><span class="nm">${esc(s.이름)}</span>
      <span class="dt">${esc(s.인허가일.slice(5).replace('-', '.'))}</span>
      <span class="sub">${esc(s.업종)} · ${esc(s.주소)}</span></li>`).join('');
    $('more').hidden = visible.length <= state.showN;
  }

  function openShop(s) {
    const m = markers.find((x) => x._shop === s);
    if (m) cluster.zoomToShowLayer(m, () => m.openPopup());
  }

  // ---------- 조작 ----------
  $('chips').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-g]'); if (!b) return;
    const g = b.dataset.g; state.off[g] = !state.off[g]; render(false);
  });
  $('period').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-days]'); if (!b) return;
    state.days = +b.dataset.days;
    $('period').querySelectorAll('button').forEach((x) => x.setAttribute('aria-checked', x === b));
    render(false);
  });
  $('region').addEventListener('change', (e) => {
    state.region = e.target.value;
    try { history.replaceState(null, '', state.region === 'all' ? location.pathname : `#r-${state.region}`); } catch (_) {}
    load();
  });
  $('more').addEventListener('click', () => { state.showN += 30; renderList(); });
  const pick = (e) => { const li = e.target.closest('li[data-i]'); if (li) openShop(visible[+li.dataset.i]); };
  $('list').addEventListener('click', pick);
  $('list').addEventListener('keydown', (e) => { if (e.key === 'Enter') pick(e); });
  let t; map.on('moveend', () => { clearTimeout(t); t = setTimeout(() => { state.showN = 30; renderList(); }, 120); });

  // ---------- 시작 ----------
  fetch('data/map/index.json').then((r) => r.json()).then((d) => {
    index = d;
    $('asof').textContent = `${d.갱신일.replace(/-/g, '.')} 기준 · 서울·인천·경기 66개 시군구`;
    const opts = ['<option value="all">수도권 전체</option>'];
    ['서울', '경기', '인천'].forEach((sd) => {
      const rs = d.지역.filter((r) => r.시도 === sd).sort((a, b) => a.지역.localeCompare(b.지역, 'ko'));
      opts.push(`<optgroup label="${sd}"><option value="sido-${SIDO_KEY[sd]}">${sd} 전체</option>${rs.map((r) => `<option value="${r.코드}">${esc(r.지역)}</option>`).join('')}</optgroup>`);
    });
    $('region').innerHTML = opts.join('');
    const h = (location.hash || '').replace('#r-', '');
    if (h && ((h.startsWith('sido-') && SIDO[h.slice(5)]) || d.지역.some((r) => r.코드 === h))) state.region = h;
    $('region').value = state.region;
    load();
  }).catch(() => { $('loading').textContent = '자료를 불러오지 못했습니다. 새로고침해 주세요.'; });
})();
