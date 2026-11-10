'use strict';
(function(root) {
  function validTime(value) { return typeof value==='string' && Number.isFinite(Date.parse(value)); }
  function validateResult(result) {
    if(!result || !Array.isArray(result.bins_nmi) || !Array.isArray(result.probabilities)
      || result.bins_nmi.length!==59 || result.probabilities.length!==59) throw new Error('辨識分布格式不正確。');
    let sum=0,mean=0;
    result.bins_nmi.forEach((bin,i)=>{
      const p=result.probabilities[i];
      if(bin!==10+i*5 || !Number.isFinite(p) || p<0) throw new Error('辨識分布包含無效數值。');
      sum+=p;mean+=bin*p;
    });
    if(Math.abs(sum-1)>1e-5 || !Number.isFinite(result.mean_nmi) || Math.abs(mean-result.mean_nmi)>1e-3)
      throw new Error('辨識機率或 mean 不正確。');
    const meta=result.metadata;
    if(!meta || !validTime(meta.observed_at) || !validTime(meta.position_at) || !validTime(result.inferred_at)
      || !Number.isFinite(meta.center_lat) || !Number.isFinite(meta.center_lon)
      || typeof meta.satellite!=='string' || typeof meta.channel!=='string' || !Number.isFinite(meta.wavelength_um)
      || !Number.isFinite(meta.position_image_offset_hours) || typeof meta.resampling!=='string'
      || !Array.isArray(meta.source_urls) || !meta.source_urls.length
      || !meta.source_urls.every(url=>typeof url==='string' && url.startsWith('https://'))
      || !/^[a-f0-9]{64}$/.test(result.model_sha256)) throw new Error('辨識來源或時間紀錄不完整。');
  }
  function validateSnapshot(data) {
    if(!data || data.schema_version!==1 || data.mode!=='hourly' || !Array.isArray(data.storms)
      || !data.records || !Array.isArray(data.warnings)) throw new Error('批次資料格式不正確，請稍後重新整理。');
    if(data.status==='awaiting_first_run') return data;
    if(!validTime(data.generated_at) || !validTime(data.fetched_at) || typeof data.generation_id!=='string')
      throw new Error('批次更新時間不完整。');
    const ids=new Set();
    for(const s of data.storms) {
      if(!/^\d{2}[LECWABSP]$/.test(s.id) || ids.has(s.id) || !validTime(s.observed_at)
        || !Number.isFinite(s.lat) || Math.abs(s.lat)>90 || !Number.isFinite(s.lon) || Math.abs(s.lon)>180)
        throw new Error('氣旋定位資料不正確。');
      ids.add(s.id);
      const record=data.records[s.id];
      if(!record || !['ready','cached','unavailable'].includes(record.status)) throw new Error('缺少氣旋的批次結果狀態。');
      if(record.status!=='unavailable') {
        validateResult(record.result);
        if(record.image_url!==`data/products/${s.id}.png` || record.result.metadata.storm?.id!==s.id)
          throw new Error('影像與氣旋結果不相符。');
      }
    }
    return data;
  }
  function ageHours(value, now=Date.now()) { return validTime(value) ? (now-Date.parse(value))/3600000 : Infinity; }
  const contract={validateSnapshot,validateResult,ageHours};
  root.R34Data=contract;
  if(typeof module!=='undefined' && module.exports) module.exports=contract;
})(globalThis);
