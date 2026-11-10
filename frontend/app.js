'use strict';
const $ = id => document.getElementById(id);
const state = { storms: [], selected: null, generation: 0, patch: null, result: null, markers: [], snapshot: null, feedRequest: 0 };
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText = value => new Date(value).toISOString().replace('T', ' ').slice(0,16) + ' UTC';
const position = s => `${Math.abs(s.lat).toFixed(1)}°${s.lat>=0?'N':'S'}  ${Math.abs(s.lon).toFixed(1)}°${s.lon>=0?'E':'W'}`;
const shortName = s => s.name.replace(/^(Tropical (Cyclone|Storm|Depression)|Hurricane|Typhoon|Super Typhoon)\s+/i, '');
let map;
function initMap() {
  if (!window.L) { $('map').textContent = '地圖元件無法載入，仍可從左側清單選取氣旋。'; return; }
  map = L.map('map', {zoomControl:true, attributionControl:true, minZoom:0, maxZoom:8, zoomSnap:.25, worldCopyJump:true}).setView([12,70],2);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com/">Leaflet</a>');
  map.attributionControl.addAttribution('Natural Earth');
  // Bundled coastline geometry keeps the overview available without a tile service.
  fetch('data/world.geojson').then(r => r.json()).then(data => {
    for (const shift of [-360, 0, 360]) {
      const shifted = JSON.parse(JSON.stringify(data));
      const move = coords => typeof coords[0] === 'number' ? [coords[0] + shift, coords[1]] : coords.map(move);
      shifted.features.forEach(f => f.geometry.coordinates = move(f.geometry.coordinates));
      L.geoJSON(shifted,{style:{color:'#37505c',weight:.8,fillColor:'#1b303c',fillOpacity:1},interactive:false}).addTo(map);
    }
  }).catch(() => { $('feed-warning').hidden=false; $('feed-warning').textContent='海岸線無法載入，氣旋定位與清單仍可使用。'; });
  const gridStyle = {color:'#263c4a',weight:.6,opacity:.7,interactive:false};
  for(let lon=-540;lon<=540;lon+=30) L.polyline([[-70,lon],[75,lon]],gridStyle).addTo(map);
  for(let lat=-60;lat<=60;lat+=30) L.polyline([[lat,-540],[lat,540]],{...gridStyle, dashArray:lat===0?'4 5':null,opacity:lat===0?.9:.5}).addTo(map);
  resetMap();
}
function resetMap() { if(map) map.fitBounds([[-47,-180],[57,180]],{padding:[35,20],animate:false}); }
function filteredStorms() {
  const filter=$('basin-filter').value;
  return state.storms.filter(s=>filter==='all'||filter.includes(s.id.slice(-1)));
}
function renderStorms() {
  const storms=filteredStorms();
  $('storm-count').textContent=storms.length;
  $('storm-list').innerHTML=storms.length ? storms.map(s=>`<button class="storm-card ${state.selected?.id===s.id?'selected':''}" data-storm="${esc(s.id)}" aria-pressed="${state.selected?.id===s.id}"><div class="storm-card-top"><span class="storm-code">${esc(s.id)}</span><span class="storm-card-wind">${s.wind_kt??'—'} <small>kt</small></span></div><div class="storm-card-name">${esc(shortName(s))}</div><div class="storm-card-meta"><i class="dot ${s.stale?'gray':s.in_training_basin?'mint':'amber'}"></i>${esc(s.basin)} · ${s.stale?'定位過期':s.in_training_basin?'訓練海盆':'跨域實驗'}</div><div class="storm-card-position">${esc(position(s))}</div></button>`).join('') : '<p class="list-message">此海盆目前沒有來源列出的活躍系統。</p>';
  $('storm-list').querySelectorAll('[data-storm]').forEach(button=>button.addEventListener('click',()=>selectStorm(button.dataset.storm)));
  if(!map) return;
  state.markers.forEach(m=>m.remove());state.markers=[];
  storms.forEach(s=>{
    const icon=L.divIcon({className:'storm-marker',iconSize:[28,28],iconAnchor:[14,14],html:`<span class="marker-core ${s.in_training_basin?'in-basin':''} ${s.stale?'stale-marker':''}">◎</span><span class="marker-label">${esc(shortName(s))}<small>${esc(s.id)} · ${s.wind_kt??'—'} kt</small></span>`});
    // Repeat markers alongside repeated coastline geometry across the dateline.
    for(const shift of [-360,0,360]) {
      const marker=L.marker([s.lat,s.lon+shift],{icon,title:`${s.id} ${shortName(s)}`,keyboard:true}).addTo(map);
      marker.on('click',()=>selectStorm(s.id));state.markers.push(marker);
    }
  });
}
async function refreshStorms(forceSelection=false) {
  const request=++state.feedRequest;
  $('refresh').disabled=true;
  try {
    const response=await fetch('data/latest.json',{cache:'no-store'});
    if(!response.ok) throw new Error('無法讀取最新批次資料。');
    const data=R34Data.validateSnapshot(await response.json());
    if(request!==state.feedRequest)return;
    const changed=state.snapshot?.generation_id!==data.generation_id;
    state.snapshot=data;
    const warnings=[...data.warnings];
    const age=R34Data.ageHours(data.generated_at);
    if(data.status==='awaiting_first_run') {
      clearSelection();state.storms=[];renderStorms();
      $('storm-list').innerHTML='<div class="list-message">等待第一次每小時辨識結果。</div>';
      $('feed-status').textContent='尚未完成首批推論';$('feed-time').textContent='每小時自動更新';
    } else {
      if(age>2) warnings.push('最新批次已超過 2 小時未更新；目前顯示歷史資料，請留意觀測時間。');
      if(age<-.1) warnings.push('裝置時間與批次時間不一致，請確認電腦時鐘。');
      state.storms=data.storms.map(s=>({...s,stale:age>2 || R34Data.ageHours(s.observed_at)>12 || R34Data.ageHours(s.observed_at)<0}));
      $('feed-status').textContent=data.scope==='global'?'全球清單 · 每小時批次':'NHC 海盆 · 每小時批次';
      $('feed-time').textContent='批次 '+dateText(data.generated_at);
    }
    $('feed-warning').hidden=!warnings.length;
    $('feed-warning').textContent=warnings.join(' ');
    if(state.selected) {
      const updated=state.storms.find(s=>s.id===state.selected.id);
      if(!updated) clearSelection();
      else if(changed || forceSelection) selectStorm(updated.id,false);
    }
    if(data.status!=='awaiting_first_run') renderStorms();
  } catch(error) {
    if(request!==state.feedRequest)return;
    $('feed-warning').hidden=false;
    $('feed-warning').textContent=error.message+' 如有上次結果，僅供歷史資料參考。';
    $('feed-status').textContent='批次資料讀取失敗';
    if(!state.storms.length) $('storm-list').innerHTML='<div class="list-message">暫時無法讀取每小時結果。請按 ↻ 重試。</div>';
  } finally { if(request===state.feedRequest)$('refresh').disabled=false; }
}
function clearSelection() {
  state.generation++;state.selected=null;state.patch=null;state.result=null;
  $('selection').hidden=true;$('empty-selection').hidden=false;
}
function imageError(message) {
  $('image-state').hidden=false;$('image-state').classList.add('error');
  $('image-state').innerHTML=`<span class="loader"></span><p>${esc(message)}</p><small>每小時更新；只使用校準的 Kelvin 亮溫</small>`;
  $('ir-image').hidden=true;$('image-crosshair').hidden=true;
  $('retry-image').hidden=false;$('infer').disabled=true;
  $('image-meta').textContent='本批次尚無可顯示的辨識影像。';
}
function selectStorm(id, focus=true) {
  const storm=state.storms.find(s=>s.id===id);if(!storm)return;
  const generation=++state.generation;
  state.selected=storm;state.patch=null;state.result=null;
  $('selection').hidden=false;$('empty-selection').hidden=true;$('result').hidden=true;
  $('selected-name').textContent=shortName(storm);$('selected-id').textContent=storm.id;
  $('selected-basin').textContent=storm.basin+' / STORM DETAIL';
  $('domain-tag').textContent=storm.in_training_basin?'● 北大西洋 · 訓練海盆':'● 跨海盆實驗 · 尚未驗證準確度';
  $('domain-tag').classList.toggle('in-basin',storm.in_training_basin);
  $('selected-position').textContent=position(storm);$('selected-wind').textContent=`${storm.wind_kt??'—'} kt / ${storm.pressure_hpa??'—'} hPa`;
  $('position-time').textContent='清單定位 '+dateText(storm.observed_at)+(storm.stale?' · 資料過期':'');
  $('image-meta').textContent='讀取本批次 11.2 µm 觀測…';
  $('prediction-status').textContent='';
  $('channel-label').textContent='11.2 µm';$('infer').disabled=true;
  $('infer').innerHTML='<span>✧</span> 查看 R34 辨識結果 <span>→</span>';
  $('retry-image').hidden=true;$('ir-image').hidden=true;$('image-crosshair').hidden=true;
  $('image-state').hidden=false;$('image-state').classList.remove('error');
  $('image-state').innerHTML='<span class="loader"></span><p>載入批次 IR 影像…</p><small>顯示最近一次每小時辨識結果</small>';
  renderStorms();
  if(focus&&map) map.setView([storm.lat,storm.lon],3,{animate:false});
  try {
    const record=state.snapshot.records[id];
    if(!record || record.status==='unavailable') throw new Error(record?.message||'本批次未產生此系統的辨識結果。');
    state.patch=record.result.metadata;state.result=record.result;
    const img=$('ir-image');
    img.onload=()=>{if(generation!==state.generation)return;$('image-state').hidden=true;img.hidden=false;$('image-crosshair').hidden=false;$('infer').disabled=false;};
    img.onerror=()=>{if(generation===state.generation)imageError('批次影像載入失敗，請重新讀取。');};
    img.src=record.image_url+'?v='+encodeURIComponent(state.snapshot.generation_id);
    const m=record.result.metadata;
    $('channel-label').textContent=m.channel+' · '+m.wavelength_um+' µm';
    $('image-meta').innerHTML=`${esc(m.satellite)} · 影像 ${esc(dateText(m.observed_at))}<br>156 × 156 · 8 km/pixel · ${m.resampling==='nearest'?'最近鄰':'雙線性'}重採樣<br>裁切中心 ${esc(position({lat:m.center_lat,lon:m.center_lon}))}<br>中心定位 ${esc(dateText(m.position_at))} · 相差 ${m.position_image_offset_hours.toFixed(1)} 小時<br><a href="${esc(m.source_urls[0])}" target="_blank" rel="noreferrer">原始觀測 ↗</a>`;
    const old=R34Data.ageHours(m.observed_at)>2;
    $('prediction-status').textContent=record.message || (old?'此影像已超過 2 小時，僅供歷史參考。':'已於批次作業完成推論，點下方按鈕查看。');
    if(record.status==='cached') $('infer').innerHTML='<span>◷</span> 查看上次成功結果 <span>→</span>';
    $('retry-image').hidden=false;$('retry-image').textContent='重新讀取批次結果';
  }catch(error){if(generation===state.generation)imageError(error.message);}
}
function showResult() {
  const result=state.result;if(!result)return;
  $('result').hidden=false;
  $('mean-value').textContent=result.mean_nmi.toFixed(1);
  $('mean-km').textContent='≈ '+(result.mean_nmi*1.852).toFixed(1)+' km';
  $('result-time').textContent='推論 '+dateText(result.inferred_at)+' · 批次 '+dateText(state.snapshot.generated_at)+' · 權重 '+result.model_sha256.slice(0,10);
  renderChart(result);
  $('infer').innerHTML='<span>✓</span> 已顯示辨識結果 <span>↓</span>';
}
function renderChart(result) {
  const W=340,H=210,pad={l:38,r:12,t:17,b:34},cw=W-pad.l-pad.r,ch=H-pad.t-pad.b;
  const max=Math.max(...result.probabilities)*1.18;
  const x=v=>pad.l+(v-10)/290*cw,y=v=>pad.t+ch-v/max*ch;
  let contents='';
  for(let i=0;i<=4;i++){
    const val=max*i/4,yp=y(val);
    contents+=`<line x1="${pad.l}" y1="${yp}" x2="${W-pad.r}" y2="${yp}" stroke="#2a3c49" stroke-dasharray="3 4"/><text x="${pad.l-7}" y="${yp+3}" text-anchor="end" fill="#839eac" font-size="8">${val.toFixed(2)}</text>`;
  }
  for(const val of [10,50,100,150,200,250,300]) contents+=`<text x="${x(val)}" y="${H-19}" text-anchor="middle" fill="#839eac" font-size="8">${val}</text>`;
  const points=result.bins_nmi.map((b,i)=>`${x(b)},${y(result.probabilities[i])}`).join(' ');
  contents+=`<polygon points="${x(10)},${y(0)} ${points} ${x(300)},${y(0)}" fill="#ef789112"/><polyline points="${points}" stroke="#ef7891" stroke-width="2" fill="none" stroke-linejoin="round"/>`;
  const mx=x(result.mean_nmi);
  contents+=`<line x1="${mx}" y1="${pad.t-5}" x2="${mx}" y2="${y(0)}" stroke="#8ee5c5" stroke-dasharray="3 4"/><text x="${Math.min(W-32,Math.max(65,mx+5))}" y="10" fill="#8ee5c5" font-size="8">mean ${result.mean_nmi.toFixed(1)}</text>`;
  result.bins_nmi.forEach((b,i)=>contents+=`<circle cx="${x(b)}" cy="${y(result.probabilities[i])}" r="2" fill="#ef7891"><title>${b} n mi：${(result.probabilities[i]*100).toFixed(3)}%</title></circle>`);
  contents+=`<text x="${W/2}" y="${H-2}" text-anchor="middle" fill="#839eac" font-size="8">Wind radius (n mi)</text><text x="0" y="8" fill="#839eac" font-size="8">Probability</text>`;
  $('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="59 個 R34 bin 的模型預測機率，mean ${result.mean_nmi.toFixed(1)} 海浬"><title>R34 機率分布</title>${contents}</svg>`;
}
function downloadResult() {
  const r=state.result;if(!r)return;
  const m=r.metadata;
  const header='bin_nmi,probability,mean_nmi,storm_id,image_time_utc,position_time_utc,satellite,channel,center_lat,center_lon,model_sha256';
  const csv=[header,...r.bins_nmi.map((b,i)=>[b,r.probabilities[i],r.mean_nmi,m.storm.id,m.observed_at,m.position_at,m.satellite,m.channel,m.center_lat,m.center_lon,r.model_sha256].join(','))].join('\r\n');
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`R34-${m.storm.id}-${m.observed_at.replace(/[:+]/g,'-')}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function clockTick() {$('clock').textContent=new Date().toISOString().replace('T',' ').slice(0,19)+' UTC';}
$('refresh').addEventListener('click',()=>refreshStorms(true));
$('basin-filter').addEventListener('change',renderStorms);
$('reset-map').addEventListener('click',resetMap);
$('retry-image').addEventListener('click',()=>refreshStorms(true));
$('infer').addEventListener('click',showResult);
$('download-result').addEventListener('click',downloadResult);
['about-button','notice-about'].forEach(id=>$(id).addEventListener('click',()=>$('about-dialog').showModal()));
$('close-about').addEventListener('click',()=>$('about-dialog').close());
$('about-dialog').addEventListener('click',event=>{if(event.target===$('about-dialog'))$('about-dialog').close();});
clockTick();setInterval(clockTick,1000);initMap();refreshStorms();setInterval(()=>refreshStorms(),300000);
