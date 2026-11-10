'use strict';
const $ = id => document.getElementById(id);
const state = { storms: [], selected: null, generation: 0, patch: null, result: null, markers: [], requestController: null };
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText = value => new Date(value).toISOString().replace('T', ' ').slice(0,16) + ' UTC';
const position = s => `${Math.abs(s.lat).toFixed(1)}°${s.lat>=0?'N':'S'}  ${Math.abs(s.lon).toFixed(1)}°${s.lon>=0?'E':'W'}`;
const shortName = s => s.name.replace(/^(Tropical (Cyclone|Storm|Depression)|Hurricane|Typhoon|Super Typhoon)\s+/i, '');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `服務回應 ${response.status}`);
  return data;
}
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
async function refreshStorms() {
  $('refresh').disabled=true;
  try {
    const data=await api('/api/storms');
    state.storms=data.storms;
    $('feed-status').textContent=data.scope==='global'?'全球清單已連線':'NHC 海盆清單';
    $('feed-time').textContent='取得 '+dateText(data.fetched_at);
    $('feed-warning').hidden=!data.warnings.length;
    $('feed-warning').textContent=data.warnings.join(' ');
    if(state.selected) {
      const previous=state.selected, updated=state.storms.find(s=>s.id===previous.id);
      if(!updated) clearSelection();
      else if(updated.observed_at!==previous.observed_at || updated.lat!==previous.lat || updated.lon!==previous.lon) {
        selectStorm(updated.id,false);
      }
    }
    renderStorms();
  } catch(error) {
    $('feed-warning').hidden=false;
    $('feed-warning').textContent=error.message+' 如有上次清單，僅供定位參考。';
    $('feed-status').textContent='來源連線失敗';
    if(!state.storms.length) $('storm-list').innerHTML='<div class="list-message">暫時無法取得清單。請檢查網路後按 ↻ 重試。</div>';
  } finally { $('refresh').disabled=false; }
}
function clearSelection() {
  state.generation++;state.selected=null;state.patch=null;state.result=null;
  $('selection').hidden=true;$('empty-selection').hidden=false;
}
function imageError(message) {
  $('image-state').hidden=false;$('image-state').classList.add('error');
  $('image-state').innerHTML=`<span class="loader"></span><p>${esc(message)}</p><small>僅接受校準的原始 Kelvin 亮溫</small>`;
  $('ir-image').hidden=true;$('image-crosshair').hidden=true;
  $('retry-image').hidden=false;$('infer').disabled=true;
  $('image-meta').textContent='本次尚未取得可用的原始亮溫。';
}
async function selectStorm(id, focus=true) {
  const storm=state.storms.find(s=>s.id===id);if(!storm)return;
  const generation=++state.generation;
  state.selected=storm;state.patch=null;state.result=null;
  $('selection').hidden=false;$('empty-selection').hidden=true;$('result').hidden=true;
  $('selected-name').textContent=shortName(storm);$('selected-id').textContent=storm.id;
  $('selected-basin').textContent=storm.basin+' / STORM DETAIL';
  $('domain-tag').textContent=storm.in_training_basin?'● 北大西洋 · 訓練海盆':'● 跨海盆實驗 · 尚未驗證準確度';
  $('domain-tag').classList.toggle('in-basin',storm.in_training_basin);
  $('selected-position').textContent=position(storm);$('selected-wind').textContent=`${storm.wind_kt??'—'} kt / ${storm.pressure_hpa??'—'} hPa`;
  $('position-time').textContent='定位 '+dateText(storm.observed_at)+(storm.stale?' · 已過期':'');
  $('image-meta').textContent='正在尋找最近 90 分鐘內的 11.2 µm 觀測…';
  $('channel-label').textContent='11.2 µm';$('infer').disabled=true;
  $('infer').innerHTML='<span>✧</span> 開始 R34 辨識 <span>→</span>';
  $('retry-image').hidden=true;$('ir-image').hidden=true;$('image-crosshair').hidden=true;
  $('image-state').hidden=false;$('image-state').classList.remove('error');
  $('image-state').innerHTML='<span class="loader"></span><p>擷取衛星原始資料…</p><small>首次下載與校準約需 20–90 秒</small>';
  renderStorms();
  if(focus&&map) map.setView([storm.lat,storm.lon],3,{animate:false});
  try {
    if(storm.stale) throw new Error('定位資料超過 12 小時，無法可靠對中裁切。');
    const {job_id}=await api('/api/imagery',{method:'POST',body:JSON.stringify({storm_id:id})});
    const started=Date.now();let job;
    do {
      if(generation!==state.generation)return;
      if(Date.now()-started>300000)throw new Error('衛星資料擷取超時，請稍後重試。');
      job=await api('/api/jobs/'+job_id);
      if(job.status==='loading')await delay(1500);
    }while(job.status==='loading');
    if(generation!==state.generation)return;
    if(job.status==='failed')throw new Error(job.message);
    state.patch=job.metadata;
    const img=$('ir-image');
    img.onload=()=>{if(generation!==state.generation)return;$('image-state').hidden=true;img.hidden=false;$('image-crosshair').hidden=false;$('infer').disabled=false;};
    img.onerror=()=>{if(generation===state.generation)imageError('影像顯示失敗，請重新擷取。');};
    img.src=job.image_url;
    const m=job.metadata;
    $('channel-label').textContent=m.channel+' · '+m.wavelength_um+' µm';
    $('image-meta').innerHTML=`${esc(m.satellite)} · ${esc(dateText(m.observed_at))}<br>156 × 156 · 8 km/pixel · ${m.resampling==='nearest'?'最近鄰':'雙線性'}重採樣<br>影像與定位相差 ${m.position_image_offset_hours.toFixed(1)} 小時 · <a href="${esc(m.source_urls[0])}" target="_blank" rel="noreferrer">原始觀測 ↗</a>`;
    $('retry-image').hidden=false;$('retry-image').textContent='重新擷取最新影像';
  }catch(error){if(generation===state.generation)imageError(error.message);}
}
async function runInference() {
  if(!state.patch)return;
  const generation=state.generation;
  $('infer').disabled=true;$('infer').textContent='正在執行模型推論…';
  try {
    const result=await api(`/api/patches/${state.patch.id}/infer`,{method:'POST'});
    if(generation!==state.generation)return;
    state.result=result;$('result').hidden=false;
    $('mean-value').textContent=result.mean_nmi.toFixed(1);
    $('mean-km').textContent='≈ '+(result.mean_nmi*1.852).toFixed(1)+' km';
    $('result-time').textContent='辨識 '+dateText(result.inferred_at)+' · 權重 '+result.model_sha256.slice(0,10);
    renderChart(result);
    $('infer').innerHTML='<span>✓</span> 辨識完成 <span>↻</span>';
  }catch(error){
    if(generation!==state.generation)return;
    $('result').hidden=false;$('chart').textContent='';$('mean-value').textContent='—';$('mean-km').textContent='';
    $('result-time').textContent=error.message;$('infer').textContent='重新執行辨識';
  }finally{if(generation===state.generation)$('infer').disabled=false;}
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
$('refresh').addEventListener('click',refreshStorms);
$('basin-filter').addEventListener('change',renderStorms);
$('reset-map').addEventListener('click',resetMap);
$('retry-image').addEventListener('click',()=>state.selected&&selectStorm(state.selected.id,false));
$('infer').addEventListener('click',runInference);
$('download-result').addEventListener('click',downloadResult);
['about-button','notice-about'].forEach(id=>$(id).addEventListener('click',()=>$('about-dialog').showModal()));
$('close-about').addEventListener('click',()=>$('about-dialog').close());
$('about-dialog').addEventListener('click',event=>{if(event.target===$('about-dialog'))$('about-dialog').close();});
clockTick();setInterval(clockTick,1000);initMap();refreshStorms();setInterval(refreshStorms,300000);
