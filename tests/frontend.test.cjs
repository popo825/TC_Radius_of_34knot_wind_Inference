'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {validateSnapshot,ageHours}=require('../frontend/data-contract.js');
const fs=require('node:fs');
const vm=require('node:vm');
const now='2026-11-10T08:00:00Z';
function fixture() {
  const storm={id:'31W',name:'Test',lat:24,lon:135,observed_at:now};
  return {schema_version:1,mode:'hourly',generation_id:'batch-1',generated_at:now,fetched_at:now,warnings:[],storms:[storm],records:{'31W':{
    status:'ready',image_url:'data/products/31W.png',result:{bins_nmi:Array.from({length:59},(_,i)=>10+i*5),probabilities:Array(59).fill(1/59),mean_nmi:155,
      model_sha256:'a'.repeat(64),inferred_at:now,metadata:{observed_at:now,position_at:now,center_lat:24,center_lon:135,
        satellite:'Himawari-9',channel:'AHI B14',wavelength_um:11.2,resampling:'nearest',position_image_offset_hours:0,
        source_urls:['https://example.com/raw'],storm}}}}};
}
test('accepts complete 59-bin hourly data and cached data',()=>{
  const data=fixture();assert.equal(validateSnapshot(data),data);
  data.records['31W'].status='cached';assert.doesNotThrow(()=>validateSnapshot(data));
});
test('rejects invalid probabilities, mismatched mean and mismatched storm',()=>{
  for(const mutate of [d=>d.records['31W'].result.probabilities[0]=-1,d=>d.records['31W'].result.mean_nmi=200,d=>d.records['31W'].result.metadata.storm={id:'04C'}]){
    const data=fixture();mutate(data);assert.throws(()=>validateSnapshot(data));
  }
});
test('rejects external or absolute image paths on project Pages',()=>{
  for(const image_url of ['/api/image','https://example.com/image.png','../private.png']){
    const data=fixture();data.records['31W'].image_url=image_url;assert.throws(()=>validateSnapshot(data));
  }
});
test('distinguishes waiting, no storms and unavailable imagery',()=>{
  assert.doesNotThrow(()=>validateSnapshot(require('../frontend/data/latest.json')));
  const data=fixture();data.storms=[];data.records={};assert.doesNotThrow(()=>validateSnapshot(data));
  const missing=fixture();missing.records['31W']={status:'unavailable',message:'No coverage'};assert.doesNotThrow(()=>validateSnapshot(missing));
});
test('ages are based on observation time and invalid dates are never fresh',()=>{
  assert.equal(ageHours('2026-11-10T05:00:00Z',Date.parse(now)),3);
  assert.equal(ageHours(null,Date.parse(now)),Infinity);
});

test('selecting a storm and viewing results uses static data, and refresh replaces its distribution',async()=>{
  const elements=new Map(),requests=[];
  let snapshot=fixture();
  const get=id=>{
    if(!elements.has(id)) elements.set(id,{
      hidden:false,disabled:false,textContent:'',innerHTML:'',value:id==='basin-filter'?'all':'',events:{},
      classList:{add(){},remove(){},toggle(){}},querySelectorAll(){return[];},
      addEventListener(name,callback){this.events[name]=callback;},
      set src(value){this.currentSrc=value;if(this.onload)this.onload();}
    });
    return elements.get(id);
  };
  const context=vm.createContext({document:{getElementById:get},window:{},R34Data:{validateSnapshot,ageHours},
    Date,Set,URL,console,encodeURIComponent,setInterval(){},setTimeout(){},
    fetch:async path=>{requests.push(path);return {ok:true,json:async()=>structuredClone(snapshot)};}});
  // No browser API is used here; this tests application state and static requests.
  vm.runInContext(fs.readFileSync(require.resolve('../frontend/app.js'),'utf8'),context);
  await context.refreshStorms();
  context.selectStorm('31W');
  assert.equal(get('ir-image').hidden,false);
  assert.equal(get('infer').disabled,false);
  get('infer').events.click();
  assert.equal(get('mean-value').textContent,'155.0');
  assert.equal(get('result').hidden,false);
  assert.match(get('chart').innerHTML,/<svg/);
  snapshot=fixture();snapshot.generation_id='batch-2';
  snapshot.records['31W'].result.probabilities=Array(59).fill(0);
  snapshot.records['31W'].result.probabilities[38]=1;
  snapshot.records['31W'].result.mean_nmi=200;
  await context.refreshStorms();get('infer').events.click();
  assert.equal(get('mean-value').textContent,'200.0');
  assert.match(get('ir-image').currentSrc,/batch-2/);
  snapshot=fixture();snapshot.generation_id='batch-3';
  snapshot.records['31W']={status:'unavailable',message:'No native coverage'};
  await context.refreshStorms();
  assert.equal(get('infer').disabled,true);
  assert.equal(get('result').hidden,true);
  assert.match(get('image-state').innerHTML,/No native coverage/);
  assert.ok(requests.every(path=>path==='data/latest.json'));
});
