'use strict';
const $=id=>document.getElementById(id);
const state={storms:[],selected:null,generation:0,patch:null,result:null,markers:[],snapshot:null,feedRequest:0,presenting:false,page:'monitor'};
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText=value=>new Date(value).toISOString().replace('T',' ').slice(0,16)+' UTC';
const position=s=>`${Math.abs(s.lat).toFixed(1)}°${s.lat>=0?'N':'S'}  ${Math.abs(s.lon).toFixed(1)}°${s.lon>=0?'E':'W'}`;
const shortName=s=>s.name.replace(/^(Tropical (Cyclone|Storm|Depression)|Hurricane|Typhoon|Super Typhoon)\s+/i,'');
const basinNames={L:'North Atlantic',E:'Eastern North Pacific',C:'Central North Pacific',W:'Western North Pacific',A:'Arabian Sea',B:'Bay of Bengal',S:'South Indian Ocean',P:'South Pacific'};
const basinName=s=>basinNames[s.id.slice(-1)]||'Other basin';
const methodNames={reported:'Reported position',interpolated_track:'Interpolated between analysis positions',extrapolated_motion:'Extrapolated using reported motion',extrapolated_history:'Extrapolated using recent track motion'};
let map;
function updateClock(){
  const now=new Date();
  $('live-clock').textContent=now.toISOString().replace('T',' ').slice(0,19)+' UTC';
  $('live-clock').setAttribute('datetime',now.toISOString());
}

function availabilityReason(record){
  const message=record?.message||'';
  if(message && !/[\u3400-\u9fff]/.test(message))return message;
  if(message.includes('Meteosat') || message.includes('視野') || message.includes('覆蓋'))return 'Infrared coverage is unavailable for this region.';
  if(message.includes('定位') || message.includes('對中') || message.includes('外推'))return 'A reliable storm center is unavailable for this observation.';
  if(message.includes('缺值'))return 'The infrared image did not pass the quality check.';
  if(record?.status==='cached')return 'The latest update failed. The last successful estimate is retained.';
  return 'No estimate is available in the latest update.';
}
function setPage(page){
  state.page=['monitor','tutorial','research'].includes(page)?page:'monitor';
  for(const name of ['monitor','tutorial','research'])$('view-'+name).hidden=name!==state.page;
  document.querySelectorAll('[data-page]').forEach(link=>{
    if(link.dataset.page===state.page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  document.title='R34 · '+({monitor:'Global Monitor',tutorial:'Tutorial',research:'Research'}[state.page]);
  if(state.page==='monitor' && map)map.invalidateSize();
}
function route(){
  const hash=(window.location?.hash||'#monitor').slice(1);
  const page=hash.startsWith('tutorial')?'tutorial':hash.startsWith('research')?'research':'monitor';
  setPage(page);if(hash!==page)$(hash)?.scrollIntoView?.({block:'start'});
}
function initMap(){
  if(!window.L){$('map').textContent='The map is unavailable. Select a storm from the list.';return;}
  map=L.map('map',{zoomControl:true,attributionControl:true,minZoom:0,maxZoom:8,zoomSnap:.25,worldCopyJump:true});
  map.attributionControl.setPrefix('<a href="https://leafletjs.com/">Leaflet</a>');map.attributionControl.addAttribution('Natural Earth');
  fetch('data/world.geojson').then(r=>r.json()).then(data=>{
    for(const shift of [-360,0,360]){
      const shifted=JSON.parse(JSON.stringify(data));
      const move=coords=>typeof coords[0]==='number'?[coords[0]+shift,coords[1]]:coords.map(move);
      shifted.features.forEach(f=>f.geometry.coordinates=move(f.geometry.coordinates));
      L.geoJSON(shifted,{style:{color:'#4c6679',weight:.7,fillColor:'#263e50',fillOpacity:1},interactive:false}).addTo(map);
    }
  }).catch(()=>{$('feed-warning').hidden=false;$('feed-warning').textContent='Coastlines could not be loaded. The storm list is still available.';});
  const grid={color:'#52697a',weight:.5,opacity:.35,interactive:false};
  for(let lon=-540;lon<=540;lon+=30)L.polyline([[-70,lon],[75,lon]],grid).addTo(map);
  for(let lat=-60;lat<=60;lat+=30)L.polyline([[lat,-540],[lat,540]],{...grid,dashArray:lat===0?'4 5':null}).addTo(map);
  resetMap();
}
function resetMap(){if(map)map.fitBounds([[-47,-180],[57,180]],{padding:[35,25],animate:false});}
function filteredStorms(){const filter=$('basin-filter').value;return state.storms.filter(s=>filter==='all'||filter.includes(s.id.slice(-1)));}
function markerMarkup(storm){return `<span class="marker-spin${storm.lat<0?' southern':''}"><img src="assets/cyclone.svg" alt=""></span><span class="marker-label">${esc(shortName(storm))}<small>${esc(storm.id)}</small></span>`;}
function clearRadius(){
  $('ir-radius').hidden=true;$('ir-radius').innerHTML='';$('radius-legend').hidden=true;
}
function showRadius(){
  const result=state.result;if(!result)return;
  // The projected infrared window spans 1,248 km at its outer pixel edges.
  const extent=result.metadata.extent_km||1248,radiusKm=result.mean_nmi*1.852;
  $('ir-radius').innerHTML=`<svg viewBox="0 0 ${extent} ${extent}" role="img" aria-label="Model mean R34: ${result.mean_nmi.toFixed(1)} nautical miles"><g class="radius-reveal"><circle class="radius-outline" cx="${extent/2}" cy="${extent/2}" r="${radiusKm}"/><circle class="radius-highlight" pathLength="1" cx="${extent/2}" cy="${extent/2}" r="${radiusKm}"/></g></svg>`;
  $('ir-radius').hidden=false;$('radius-legend').textContent=`Inference Result · Weighted Mean: ${result.mean_nmi.toFixed(1)} n mi`;$('radius-legend').hidden=false;
}
function renderStorms(){
  const storms=filteredStorms();$('storm-count').textContent=storms.length;
  $('storm-list').innerHTML=storms.length?storms.map(s=>`<button class="storm-card ${state.selected?.id===s.id?'selected':''}" data-storm="${esc(s.id)}" aria-pressed="${state.selected?.id===s.id}"><div class="storm-card-top"><span>${esc(s.id)}</span><span class="storm-card-wind">${s.wind_kt??'—'} kt</span></div><div class="storm-card-name">${esc(shortName(s))}</div><div class="storm-card-basin">${esc(basinName(s))}</div></button>`).join(''):'<p class="list-message">No active systems in this basin.</p>';
  $('storm-list').querySelectorAll('[data-storm]').forEach(button=>button.addEventListener('click',()=>selectStorm(button.dataset.storm)));
  if(!map)return;
  state.markers.forEach(m=>m.remove());state.markers=[];
  storms.forEach(s=>{
    const icon=L.divIcon({className:'storm-marker'+(state.selected?.id===s.id?' selected-marker':''),iconSize:[34,34],iconAnchor:[17,17],html:markerMarkup(s)});
    for(const shift of [-360,0,360]){
      const marker=L.marker([s.lat,s.lon+shift],{icon,title:`${s.id} ${shortName(s)}`,keyboard:true}).addTo(map);
      marker.on('click',()=>selectStorm(s.id));state.markers.push(marker);
    }
  });
}
async function refreshStorms(forceSelection=false){
  const request=++state.feedRequest;$('refresh').disabled=true;
  try{
    const response=await fetch('data/latest.json',{cache:'no-store'});
    if(!response.ok)throw new Error('Latest results could not be loaded.');
    const data=R34Data.validateSnapshot(await response.json());if(request!==state.feedRequest)return;
    const changed=state.snapshot?.generation_id!==data.generation_id;state.snapshot=data;
    $('feed-time').textContent=data.generated_at?'Updated '+dateText(data.generated_at):'Waiting for update';
    if(data.generated_at)$('feed-time').setAttribute('datetime',data.generated_at);else $('feed-time').removeAttribute('datetime');
    const warnings=[];if(data.scope==='NHC-only')warnings.push('Only NHC-covered basins are available in this update.');
    const age=R34Data.ageHours(data.generated_at);
    if(data.status==='awaiting_first_run'){
      clearSelection();state.storms=[];renderStorms();$('storm-list').innerHTML='<p class="list-message">Waiting for the first hourly update.</p>';
    }else{
      if(age>2)warnings.push('Results have not updated for over two hours. Check observation times in Research.');
      if(age<-.1)warnings.push('Please check your device clock.');
      state.storms=data.storms.map(s=>({...s,stale:age>2||R34Data.ageHours(s.observed_at)>12}));
    }
    $('feed-warning').hidden=!warnings.length;$('feed-warning').textContent=warnings.join(' ');
    if(state.selected){const updated=state.storms.find(s=>s.id===state.selected.id);if(!updated)clearSelection();else if(changed||forceSelection)selectStorm(updated.id,false);}
    if(data.status!=='awaiting_first_run')renderStorms();
  }catch(error){
    if(request!==state.feedRequest)return;
    $('feed-warning').hidden=false;$('feed-warning').textContent=error.message+' Previously loaded results may be out of date.';
    if(!state.storms.length)$('storm-list').innerHTML='<p class="list-message">Unable to load storms. Please refresh.</p>';
  }finally{if(request===state.feedRequest)$('refresh').disabled=false;}
}
function clearSelection(){
  clearRadius();$('image-time-row').hidden=true;
  state.generation++;state.selected=null;state.patch=null;state.result=null;state.presenting=false;
  $('selection').hidden=true;$('empty-selection').hidden=false;$('result').hidden=true;$('analysis-animation').hidden=true;renderRecord();
}
function imageError(message){
  clearRadius();
  state.result=null;state.presenting=false;$('analysis-animation').hidden=true;
  $('image-state').hidden=false;$('image-state').classList.add('error');$('image-state').innerHTML=`<span class="loader" aria-hidden="true"></span><p>${esc(message)}</p>`;
  $('ir-image').hidden=true;$('image-crosshair').hidden=true;$('infer').disabled=true;$('infer').setAttribute('aria-busy','false');$('retry-image').hidden=false;
}
function selectStorm(id,focus=true){
  const storm=state.storms.find(s=>s.id===id);if(!storm)return;
  clearRadius();$('image-time-row').hidden=true;
  const generation=++state.generation;state.selected=storm;state.patch=null;state.result=null;state.presenting=false;
  $('selection').hidden=false;$('empty-selection').hidden=true;$('result').hidden=true;$('analysis-animation').hidden=true;$('result-warning').hidden=true;
  $('selected-name').textContent=shortName(storm);$('selected-id').textContent=storm.id;$('selected-basin').textContent=basinName(storm);
  $('selected-position').textContent=position(storm);$('selected-wind').textContent=`${storm.wind_kt??'—'} kt`;
  $('infer').disabled=true;$('infer').setAttribute('aria-busy','false');$('infer').innerHTML='<span>Infer R34 Using Our Model</span><span aria-hidden="true">→</span>';
  $('retry-image').hidden=true;$('ir-image').hidden=true;$('image-crosshair').hidden=true;$('image-state').hidden=false;$('image-state').classList.remove('error');
  $('image-state').innerHTML='<span class="loader" aria-hidden="true"></span><p>Loading image…</p>';$('inference-status').textContent='';renderStorms();
  if(focus&&map)map.setView([storm.lat,storm.lon],3,{animate:false});
  const record=state.snapshot?.records[id];renderRecord();
  if(!record||record.status==='unavailable'){imageError(availabilityReason(record));return;}
  state.patch=record.result.metadata;state.result=record.result;
  $('image-time').textContent=dateText(state.patch.observed_at);$('image-time').setAttribute('datetime',state.patch.observed_at);$('image-time-row').hidden=false;
  const img=$('ir-image');
  img.onload=()=>{if(generation!==state.generation)return;$('image-state').hidden=true;img.hidden=false;$('image-crosshair').hidden=false;$('infer').disabled=false;};
  img.onerror=()=>{if(generation===state.generation)imageError('The infrared image could not be loaded. Please refresh.');};
  img.src=record.image_url+'?v='+encodeURIComponent(state.snapshot.generation_id);
}
async function runInferenceAnimation(){
  const result=state.result;if(!result||state.presenting)return;
  clearRadius();
  const generation=state.generation;state.presenting=true;$('result').hidden=true;$('analysis-animation').hidden=false;$('infer').disabled=true;
  $('infer').setAttribute('aria-busy','true');$('infer').innerHTML='<span>Preparing estimate…</span><span aria-hidden="true">↻</span>';$('inference-status').textContent='Preparing the latest hourly model output.';
  const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  await new Promise(resolve=>setTimeout(resolve,reduced?0:1100));
  if(generation!==state.generation||state.result!==result)return;
  state.presenting=false;$('analysis-animation').hidden=true;$('infer').disabled=false;$('infer').setAttribute('aria-busy','false');showResult();
}
function showResult(){
  const result=state.result;if(!result)return;
  $('mean-value').textContent=result.mean_nmi.toFixed(1);$('mean-km').textContent='≈ '+(result.mean_nmi*1.852).toFixed(1)+' km';renderChart(result);$('result').hidden=false;
  const messages=[],storm=state.selected,record=state.snapshot.records[storm.id];
  if(!storm.in_training_basin)messages.push(`${basinName(storm)} case: outside the model's Atlantic training basin.`);
  if(record.status==='cached')messages.push('Showing the last successful estimate.');
  if(R34Data.ageHours(result.metadata.observed_at)>2||R34Data.ageHours(state.snapshot.generated_at)>2)messages.push('Observation or update is over two hours old.');
  $('result-warning').textContent=messages.join(' ');$('result-warning').hidden=!messages.length;$('infer').innerHTML='<span>Infer R34 Using Our Model</span><span aria-hidden="true">↻</span>';
  showRadius();
  $('inference-status').textContent=`Estimated mean R34: ${result.mean_nmi.toFixed(1)} nautical miles.`;
}
function safeSource(url,label){return typeof url==='string'&&url.startsWith('https://')?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(label)} ↗</a>`:esc(label);}
function renderRecord(){
  const storm=state.selected,record=storm&&state.snapshot?.records[storm.id];$('record-empty').hidden=!!storm;$('record-content').hidden=!storm;if(!storm)return;
  $('record-name').textContent=`${shortName(storm)} · ${storm.id}`;
  const result=record?.result,m=result?.metadata,e=m?.center_estimation;
  const fields=[['Basin',esc(basinName(storm))],['Availability',esc(record?.status==='ready'?'Latest hourly estimate':record?.status==='cached'?'Last successful estimate':'No estimate available')],['Batch published',state.snapshot.generated_at?esc(dateText(state.snapshot.generated_at)):'Pending'],['Latest source position',esc(position(storm))],['Position valid at',esc(dateText(storm.observed_at))],['Position source',safeSource(storm.position_source_url||storm.source_url,storm.position_source||storm.source||'Source feed')]];
  if(m)fields.push(['Image time',esc(dateText(m.observed_at))],['Inference completed',esc(dateText(result.inferred_at))],['Satellite / channel',esc(`${m.satellite} · ${m.channel} · ${m.wavelength_um} µm`)],['Input grid','156 × 156 pixels · 8 km spacing · 1,248 km window'],['Resampling',esc(m.resampling==='nearest'?'Nearest neighbor':'Bilinear')],['Crop center',esc(position({lat:m.center_lat,lon:m.center_lon}))],['Center method',esc(e?methodNames[e.method]:'Unadjusted center from a legacy batch')],['Reference time',esc(dateText(m.position_at))],['Center target time',e?esc(dateText(e.valid_at)):'Not recorded'],['Motion',e?.speed_kmh!=null?`${e.speed_kmh.toFixed(1)} km/h toward ${e.bearing_deg.toFixed(0)}°`:'Not used'],['Center displacement',e?`${e.displacement_km.toFixed(1)} km`:'Not recorded'],['Normalization','<code>(Kelvin − 236.54854) / 26.703743</code>'],['Checkpoint SHA-256',`<code>${esc(result.model_sha256)}</code>`],['Raw infrared data',safeSource(m.source_urls[0],'Original observation')]);
  $('record-fields').innerHTML=fields.map(([name,value])=>`<div><dt>${name}</dt><dd>${value}</dd></div>`).join('');
  const messages=[];if(record?.status!=='ready')messages.push(availabilityReason(record));if(e?.is_estimated)messages.push('The crop center is a motion estimate, not an independent observed fix.');if(m&&R34Data.ageHours(m.observed_at)>2)messages.push('The image is over two hours old.');
  $('record-warning').textContent=messages.join(' ');$('record-warning').hidden=!messages.length;
}

function renderChart(result) {
  const W=340,H=210,pad={l:38,r:12,t:17,b:34},cw=W-pad.l-pad.r,ch=H-pad.t-pad.b;
  const max=Math.max(...result.probabilities)*1.18;
  const x=v=>pad.l+(v-10)/290*cw,y=v=>pad.t+ch-v/max*ch;
  let contents='';
  for(let i=0;i<=4;i++){
    const val=max*i/4,yp=y(val);
    contents+=`<line x1="${pad.l}" y1="${yp}" x2="${W-pad.r}" y2="${yp}" stroke="#dfe5e9" stroke-dasharray="3 4"/><text x="${pad.l-7}" y="${yp+3}" text-anchor="end" fill="#607585" font-size="10">${val.toFixed(2)}</text>`;
  }
  for(const val of [10,50,100,150,200,250,300]) contents+=`<text x="${x(val)}" y="${H-19}" text-anchor="middle" fill="#607585" font-size="10">${val}</text>`;
  const points=result.bins_nmi.map((b,i)=>`${x(b)},${y(result.probabilities[i])}`).join(' ');
  contents+=`<polygon points="${x(10)},${y(0)} ${points} ${x(300)},${y(0)}" fill="#bd526b10"/><polyline points="${points}" stroke="#b94762" stroke-width="2" fill="none" stroke-linejoin="round"/>`;
  const mx=x(result.mean_nmi);
  contents+=`<line x1="${mx}" y1="${pad.t-5}" x2="${mx}" y2="${y(0)}" stroke="#234e6d" stroke-dasharray="3 4"/><text x="${Math.min(W-32,Math.max(65,mx+5))}" y="10" fill="#234e6d" font-size="10">mean ${result.mean_nmi.toFixed(1)}</text>`;
  result.bins_nmi.forEach((b,i)=>contents+=`<circle cx="${x(b)}" cy="${y(result.probabilities[i])}" r="2" fill="#b94762"><title>${b} n mi：${(result.probabilities[i]*100).toFixed(3)}%</title></circle>`);
  contents+=`<text x="${W/2}" y="${H-2}" text-anchor="middle" fill="#607585" font-size="10">Wind radius (n mi)</text><text x="0" y="8" fill="#607585" font-size="10">Probability</text>`;
  $('chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="R34 prediction distribution, mean ${result.mean_nmi.toFixed(1)} nautical miles"><title>R34 probability distribution</title>${contents}</svg>`;
}
function downloadResult() {
  const r=state.result;if(!r)return;
  const m=r.metadata;
  const e=m.center_estimation||{};
  const header='bin_nmi,probability,mean_nmi,storm_id,image_time_utc,position_time_utc,satellite,channel,center_lat,center_lon,model_sha256,center_valid_at,center_method,position_source,motion_kmh,motion_bearing_deg';
  const csv=[header,...r.bins_nmi.map((b,i)=>[b,r.probabilities[i],r.mean_nmi,m.storm.id,m.observed_at,m.position_at,m.satellite,m.channel,m.center_lat,m.center_lon,r.model_sha256,e.valid_at||'',e.method||'reported_unadjusted',e.reference_source||'',e.speed_kmh??'',e.bearing_deg??''].join(','))].join('\r\n');
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`R34-${m.storm.id}-${m.observed_at.replace(/[:+]/g,'-')}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

$('refresh').addEventListener('click',()=>refreshStorms(true));
$('basin-filter').addEventListener('change',renderStorms);
$('reset-map').addEventListener('click',resetMap);
$('retry-image').addEventListener('click',()=>refreshStorms(true));
$('infer').addEventListener('click',runInferenceAnimation);
$('download-result').addEventListener('click',downloadResult);
window.addEventListener?.('hashchange',route);
updateClock();setInterval(updateClock,1000);
initMap();route();refreshStorms();setInterval(()=>refreshStorms(),300000);
