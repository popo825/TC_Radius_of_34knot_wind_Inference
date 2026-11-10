from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import re
import threading
import time
import uuid
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .imagery import CACHE, DataUnavailable, get_patch
from .model import MODEL_PATH, ROOT, predict
from .storms import fetch_storms
from .rendering import render_ir_png

app = FastAPI(title='R34 Observatory', version='0.1.0')
log = logging.getLogger('r34')
pool = ThreadPoolExecutor(max_workers=1)
jobs, job_lock = {}, threading.Lock()
storm_cache, storm_lock = {}, threading.Lock()


def current_storms():
    with storm_lock:
        if time.monotonic() - storm_cache.get('at', -1e10) > 300:
            data = fetch_storms()
            storm_cache.update(data=data, at=time.monotonic())
        return storm_cache['data']


@app.get('/api/health')
def health():
    return {'status': 'ok', 'model_present': MODEL_PATH.is_file(), 'version': '0.1.0'}


@app.get('/api/storms')
def storms():
    try:
        return current_storms()
    except Exception:
        log.exception('Storm feed failed')
        raise HTTPException(503, '氣旋資料來源無法連線，請稍後再試。尚未取得全球清單。')


class JobRequest(BaseModel):
    storm_id: str = Field(pattern=r'^\d{2}[LECWABSP]$')


def prepare_job(job_id, storm):
    try:
        patch, metadata = get_patch(storm)
        metadata['storm'] = storm
        (CACHE / f'patch-{metadata["id"]}.json').write_text(json.dumps(metadata), encoding='utf-8')
        payload = {'status': 'complete', 'metadata': metadata, 'image_url': f'/api/patches/{metadata["id"]}/image'}
    except Exception as exc:
        log.exception('Imagery preparation failed')
        message = str(exc) if isinstance(exc, DataUnavailable) else '衛星資料擷取或解碼失敗，請稍後重試；詳細原因已記錄在後端。'
        payload = {'status': 'failed', 'message': message}
    with job_lock:
        jobs[job_id].update(payload)


@app.post('/api/imagery', status_code=202)
def imagery(body: JobRequest):
    try:
        storm = next((s for s in current_storms()['storms'] if s['id'] == body.storm_id), None)
    except Exception:
        raise HTTPException(503, '無法取得氣旋定位。')
    if storm is None:
        raise HTTPException(404, '此系統已不在目前活躍清單中，請重新整理。')
    with job_lock:
        for jid, job in jobs.items():
            if job['storm_id'] == storm['id'] and job['status'] == 'loading':
                return {'job_id': jid}
        if sum(j['status'] == 'loading' for j in jobs.values()) >= 4:
            raise HTTPException(429, '衛星擷取佇列已滿，請稍後重試。')
        if len(jobs) >= 200:
            for jid in list(jobs):
                if jobs[jid]['status'] != 'loading':
                    del jobs[jid]
                if len(jobs) < 150:
                    break
        jid = uuid.uuid4().hex
        jobs[jid] = {'status': 'loading', 'storm_id': storm['id']}
    pool.submit(prepare_job, jid, dict(storm))
    return {'job_id': jid}


@app.get('/api/jobs/{jid}')
def job_status(jid: str):
    with job_lock:
        if jid not in jobs:
            raise HTTPException(404, '找不到此擷取工作，請重新選取氣旋。')
        return dict(jobs[jid])


def read_patch(patch_id):
    if not re.fullmatch(r'[0-9a-f]{24}', patch_id):
        raise HTTPException(404, '找不到影像。')
    try:
        meta = json.loads((CACHE / f'patch-{patch_id}.json').read_text(encoding='utf-8'))
        patch = np.load(CACHE / f'patch-{patch_id}.npy', allow_pickle=False)
        return patch, meta
    except FileNotFoundError:
        raise HTTPException(404, '影像快取不存在，請重新擷取。')


@app.get('/api/patches/{patch_id}/image')
def patch_image(patch_id: str):
    patch, _ = read_patch(patch_id)
    return Response(render_ir_png(patch), media_type='image/png')


@app.post('/api/patches/{patch_id}/infer')
def inference(patch_id: str):
    patch, meta = read_patch(patch_id)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(meta['observed_at'])).total_seconds()
    if not 0 <= age <= 90 * 60:
        raise HTTPException(409, '影像已超過 90 分鐘，請重新擷取最新影像。')
    if not MODEL_PATH.is_file():
        raise HTTPException(503, '找不到模型，請設定 R34_MODEL_PATH。')
    try:
        result = predict(patch)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        log.exception('Model inference failed')
        raise HTTPException(503, '模型載入或推論失敗，請查看後端記錄。')
    return {**result, 'metadata': meta, 'inferred_at': datetime.now(timezone.utc).isoformat(),
            'experimental': True, 'out_of_basin': not meta['storm']['in_training_basin']}


app.mount('/', StaticFiles(directory=ROOT / 'frontend', html=True), name='frontend')
