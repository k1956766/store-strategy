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
    return (T.행정동_업종[code] || []).find((r) => r[0] === cat);
  }
  function valueOf(code) {
    if (state.cat) {
      const r = catRow(code, state.cat);
      return r && r[1] >= 3 ? r[4] : null;           // 특화도(가게 3곳 이상만)
    }
    const d = T.행정동[code];
    if (!d || d.가게수 < 20) return null;            // 가게가 너무 적은 동은 비율이 흔들려 칠하지 않음
    return d[state.metric];
  }
  function bins() {
    if (state.cat) return { cuts: [0.5, 0.8, 1.25, 2], colors: SEQ, labels: ['0.5↓', '0.8', '1.25', '2', '2↑'] };
    const vals = Object.keys(T.행정동).map(valueOf).filter((v) => v != null).sort((a, b) => a - b);
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
      return { fillColor: colorOf(valueOf(f.properties.c)), fillOpacity: 0.72, color: sel ? '#1F2B3D' : '#ffffff', weight: sel ? 2.5 : 0.8 };
    });
    const title = state.cat ? `${esc(state.cat)} 특화도(서울 평균=1)` : METRIC[state.metric].name;
    $('legend').innerHTML = `<div class="lt">${title}</div><div class="bins">${B.colors.map((c) => `<i style="background:${c}"></i>`).join('')}</div>
      <div class="lab">${B.labels.map((l) => `<span>${l}</span>`).join('')}</div>
      <div class="na"><i></i>${state.cat ? '그 업종 가게 3곳 미만' : '가게 20곳 미만'}</div>`;
  }

  function tip(f) {
    const c = f.properties.c, d = T.행정동[c];
    if (!d) return `<b>${esc(f.properties.n)}</b><br>자료 없음`;
    if (state.cat) {
      const r = catRow(c, state.cat);
      return `<b>${esc(d.행정동)}</b><br>${esc(state.cat)} ${r ? int(r[1]) : 0}곳 · 특화도 ${r ? fmt(r[4], 2) : '–'}`;
    }
    return `<b>${esc(d.행정동)}</b><br>가게 ${int(d.가게수)}곳 · ${METRIC[state.metric].name.split('(')[0]} ${fmt(d[state.metric])}`;
  }

  // ---------- 동네 상세 ----------
  function openDong(code, zoom) {
    state.dong = code;
    const d = T.행정동[code];
    if (!d) return;
    const rows = (T.행정동_업종[code] || []).slice(0, 18);
    const tr = rows.map((r) => {
      const tags = `${r[5] != null && isRise(code, r[0]) ? '<span class="tag rise">뜸</span>' : ''}${isWarn(code, r[0]) ? '<span class="tag warn">경보</span>' : ''}`;
      return `<tr><td>${esc(r[0])}${tags}</td><td>${int(r[1])}</td><td>${int(r[2])}</td><td>${int(r[3])}</td><td>${r[4] == null ? '–' : fmt(r[4], 2)}</td></tr>`;
    }).join('');
    $('detail').innerHTML = `<button class="close" type="button" id="close">닫기</button>
      <h2>${esc(d.행정동)}</h2><div class="sub">인허가 가게 ${int(d.가게수)}곳 · 최근 12개월</div>
      <div class="kpis">
        <div class="kpi"><b>${fmt(d.개업률)}%</b><span>개업률</span></div>
        <div class="kpi"><b>${fmt(d.폐업률)}%</b><span>폐업률</span></div>
        <div class="kpi"><b class="${d.순증률 > 0 ? 'up' : d.순증률 < 0 ? 'dn' : ''}">${sign(d.순증률)}%</b><span>순증률</span></div>
        <div class="kpi"><b>${fmt(d.회전율, 0)}%</b><span>교체(회전율)</span></div>
        <div class="kpi"><b>${fmt(d['1년생존율'])}%</b><span>1년 생존율</span></div>
        <div class="kpi"><b>${fmt(T.서울_전체.회전율, 0)}%</b><span>서울 평균 교체</span></div>
      </div>
      ${d.임대상권 ? `<p class="rent">소규모 상가 임대료 <b>${fmt(d.임대료_소규모)}천원/㎡</b>(월, 전년 대비 ${sign(d.임대료_전년비)}%) · 공실률 ${fmt(d.공실률_소규모)}%<br><span>한국부동산원 '${esc(d.임대상권)}' 상권 값(${esc(String(d.임대분기).slice(0, 4))}년 ${esc(String(d.임대분기).slice(5))}분기)을 가까운 동에 붙인 근사치</span></p>` : ''}
      ${d.학원 != null ? `<p class="rent">학원·교습소 <b>${int(d.학원)}곳</b> · 최근 12개월 새로 연 곳 ${int(d.학원_최근12개월_신규)}곳 <span>(나이스)</span></p>` : ''}
      <table class="t"><thead><tr><th>업종</th><th>가게</th><th>개업</th><th>폐업</th><th>특화도</th></tr></thead><tbody>${tr}</tbody></table>`;
    $('detail').hidden = false;
    $('close').onclick = () => { state.dong = null; $('detail').hidden = true; paint(); };
    paint();
    if (zoom) {
      layer.eachLayer((l) => { if (l.feature.properties.c === code) map.fitBounds(l.getBounds(), { paddingTopLeft: [window.innerWidth > 720 ? 380 : 20, 20], maxZoom: 14 }); });
    }
    $('detail').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  const riseSet = new Set(), warnSet = new Set();
  const isRise = (c, g) => riseSet.has(c + '|' + g);
  const isWarn = (c, g) => warnSet.has(c + '|' + g);

  // ---------- 탭 ----------
  function renderTab() {
    const body = $('tab-body'), note = $('tab-note');
    if (state.tab === 'up') {
      note.textContent = `최근 6개월(${T.최근6개월.join('~')}) 개업이 서울 업종 흐름보다 유독 몰린 동네·업종입니다. 숙박·민박·호텔은 관광·제도 영향이 커서 뒤에 모았습니다.`;
      body.innerHTML = list([...T.뜨는_동네업종.filter((x) => !LODGING.has(x.업종)), ...T.뜨는_동네업종.filter((x) => LODGING.has(x.업종))], (x) => `<span class="nm">${esc(x.행정동)}<small>${esc(x.업종)}</small></span><span class="v up">${int(x.개업_최근6개월)}곳 개업</span>
        <span class="s">서울 흐름대로라면 ${fmt(x.개업_기대)}곳 · 지금 ${int(x.가게수)}곳 · 특화도 ${fmt(x.특화도_LQ, 2)}${LODGING.has(x.업종) ? ' · 관광 수요·생활숙박시설 신고 영향 함께' : ''}</span>`);
    } else if (state.tab === 'cl') {
      note.textContent = '서울 같은 업종 폐업률로 기대되는 수보다 최근 12개월 폐업이 뚜렷이 많은 곳입니다.';
      body.innerHTML = list(T.폐업경보, (x) => `<span class="nm">${esc(x.행정동)}<small>${esc(x.업종)}</small></span><span class="v dn">${int(x.폐업_12개월)}곳 폐업</span>
        <span class="s">서울 폐업률대로라면 ${fmt(x.폐업_기대)}곳 · 폐업률 ${fmt(x.폐업률)}% · 지금 ${int(x.가게수)}곳</span>`) || '<p class="tab-note">지금은 뚜렷한 경보가 없습니다.</p>';
    } else if (state.tab === 'ch') {
      note.textContent = '가게 50곳 이상 동네 가운데, 서울 평균 교체 속도보다 가게가 자주 바뀐 곳입니다.';
      body.innerHTML = list(T.교체_빈발, (x) => `<span class="nm">${esc(x.행정동)}</span><span class="v">${fmt(x.회전율, 0)}%</span>
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
  Promise.all([fetch('data/trend/서울.json').then((r) => r.json()), fetch('data/boundary_web/행정동_서울.json').then((r) => r.json())]).then(([t, g]) => {
    T = t; geo = g;
    T.뜨는_동네업종.forEach((x) => riseSet.add(x.행정동코드 + '|' + x.업종));
    T.폐업경보.forEach((x) => warnSet.add(x.행정동코드 + '|' + x.업종));
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
    layer = L.geoJSON(geo, {
      onEachFeature: (f, l) => {
        l.bindTooltip(() => tip(f), { sticky: true, className: 'dong-tip' });
        l.on('click', () => openDong(f.properties.c, false));
      },
    }).addTo(map);
    map.fitBounds(layer.getBounds(), { paddingTopLeft: [window.innerWidth > 720 ? 370 : 0, 10] });
    paint(); renderTab();
    $('loading').hidden = true;
  }).catch(() => { $('loading').textContent = '자료를 불러오지 못했습니다. 새로고침해 주세요.'; });

  $('metric').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.metric = b.dataset.m; state.cat = ''; $('cat').value = '';
    $('metric').querySelectorAll('button').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
    paint();
  });
  $('cat').addEventListener('change', (e) => { state.cat = e.target.value; paint(); });
  $('tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    state.tab = b.dataset.t;
    $('tabs').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    renderTab();
  });
})();
