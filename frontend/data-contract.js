'use strict';
(function(root) {
  function validTime(value) { return typeof value==='string' && Number.isFinite(Date.parse(value)); }
  function validateResult(result) {
    if(!result || !Array.isArray(result.bins_nmi) || !Array.isArray(result.probabilities)
      || result.bins_nmi.length!==59 || result.probabilities.length!==59) throw new Error('The prediction distribution has an invalid format.');
    let sum=0,mean=0;
    result.bins_nmi.forEach((bin,i)=>{
      const p=result.probabilities[i];
      if(bin!==10+i*5 || !Number.isFinite(p) || p<0) throw new Error('The prediction contains invalid values.');
      sum+=p;mean+=bin*p;
    });
    if(Math.abs(sum-1)>1e-5 || !Number.isFinite(result.mean_nmi) || Math.abs(mean-result.mean_nmi)>1e-3)
      throw new Error('The prediction probabilities or mean are invalid.');
    const meta=result.metadata;
    if(!meta || !validTime(meta.observed_at) || !validTime(meta.position_at) || !validTime(result.inferred_at)
      || !Number.isFinite(meta.center_lat) || !Number.isFinite(meta.center_lon)
      || typeof meta.satellite!=='string' || typeof meta.channel!=='string' || !Number.isFinite(meta.wavelength_um)
      || !Number.isFinite(meta.position_image_offset_hours) || typeof meta.resampling!=='string'
      || !Array.isArray(meta.source_urls) || !meta.source_urls.length
      || !meta.source_urls.every(url=>typeof url==='string' && url.startsWith('https://'))
      || !/^[a-f0-9]{64}$/.test(result.model_sha256)) throw new Error('Observation metadata or timestamps are incomplete.');
    const e=meta.center_estimation;
    if(e && (!['reported','interpolated_track','extrapolated_motion','extrapolated_history'].includes(e.method)
      || !validTime(e.valid_at) || Math.abs(Date.parse(e.valid_at)-Date.parse(meta.observed_at))>1000
      || !Number.isFinite(e.lat) || !Number.isFinite(e.lon) || Math.abs(e.lat-meta.center_lat)>1e-5 || Math.abs(e.lon-meta.center_lon)>1e-5
      || !Number.isFinite(e.displacement_km) || e.displacement_km<0
      || (e.speed_kmh!=null && (!Number.isFinite(e.speed_kmh) || !Number.isFinite(e.bearing_deg)))))
      throw new Error('The crop center does not match the image timestamp.');
  }
  function validateSnapshot(data) {
    if(!data || data.schema_version!==1 || data.mode!=='hourly' || !Array.isArray(data.storms)
      || !data.records || !Array.isArray(data.warnings)) throw new Error('Published results have an invalid format. Please refresh later.');
    if(data.status==='awaiting_first_run') return data;
    if(!validTime(data.generated_at) || !validTime(data.fetched_at) || typeof data.generation_id!=='string')
      throw new Error('The batch update time is missing.');
    const ids=new Set();
    for(const s of data.storms) {
      if(!/^\d{2}[LECWABSP]$/.test(s.id) || ids.has(s.id) || !validTime(s.observed_at)
        || !Number.isFinite(s.lat) || Math.abs(s.lat)>90 || !Number.isFinite(s.lon) || Math.abs(s.lon)>180)
        throw new Error('Storm positions are invalid.');
      ids.add(s.id);
      const record=data.records[s.id];
      if(!record || !['ready','cached','unavailable'].includes(record.status)) throw new Error('A storm is missing its result status.');
      if(record.status!=='unavailable') {
        validateResult(record.result);
        if(record.image_url!==`data/products/${s.id}.png` || record.result.metadata.storm?.id!==s.id)
          throw new Error('The image does not match the selected storm.');
      }
    }
    return data;
  }
  function ageHours(value, now=Date.now()) { return validTime(value) ? (now-Date.parse(value))/3600000 : Infinity; }
  const contract={validateSnapshot,validateResult,ageHours};
  root.R34Data=contract;
  if(typeof module!=='undefined' && module.exports) module.exports=contract;
})(globalThis);
