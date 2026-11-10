"""Build a static website from one hourly inference batch.

Only frontend assets and small products are published. Model/raw files stay out.
A total feed failure raises before a replacement site can be published.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import uuid
import numpy as np
import requests
from .imagery import DataUnavailable, get_patch
from .model import ROOT, load_model, predict
from .rendering import render_ir_png
from .storms import fetch_storms

SID = re.compile(r'^\d{2}[LECWABSP]$')
PRODUCT = re.compile(r'^\d{2}[LECWABSP]\.(png|json|csv)$')


def now_utc():
    return datetime.now(timezone.utc)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def result_valid(result):
    try:
        probabilities = np.asarray(result['probabilities'], dtype=float)
        bins = np.asarray(result['bins_nmi'], dtype=float)
        return (probabilities.shape == (59,) and np.array_equal(bins, np.arange(10, 305, 5))
                and np.isfinite(probabilities).all() and (probabilities >= 0).all()
                and abs(float(probabilities.sum()) - 1) < 1e-5
                and np.isfinite(result['mean_nmi'])
                and abs(float(np.dot(probabilities, bins)) - result['mean_nmi']) < 1e-3)
    except (KeyError, TypeError, ValueError):
        return False


def previous_snapshot(site_url):
    if not site_url:
        return None
    if not site_url.startswith('https://'):
        raise ValueError('Previous site URL must use HTTPS.')
    try:
        response = requests.get(site_url.rstrip('/') + '/data/latest.json', timeout=(10, 25))
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            return None
        data = response.json()
        return data if data.get('schema_version') == 1 else None
    except (requests.RequestException, ValueError, AttributeError):
        return None


def reuse_previous(sid, previous, site_url, digest, now):
    """Retain a bounded, labeled last success if an individual storm fails."""
    try:
        record = previous['records'][sid]
        result = record['result']
        meta = result['metadata']
        image_time = datetime.fromisoformat(meta['observed_at'].replace('Z', '+00:00'))
        if (not result_valid(result) or result['model_sha256'] != digest
                or not 0 <= (now - image_time).total_seconds() <= 6 * 3600
                or meta['storm']['id'] != sid):
            return None
        image_path = f'data/products/{sid}.png'
        if record['image_url'] != image_path:
            return None
        response = requests.get(site_url.rstrip('/') + '/' + image_path, timeout=(10, 25))
        response.raise_for_status()
        content = response.content
        if len(content) > 5 * 1024 * 1024 or not content.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
        return result, content
    except (KeyError, TypeError, ValueError, requests.RequestException):
        return None


def write_product(directory, sid, result, png):
    (directory / f'{sid}.png').write_bytes(png)
    write_json(directory / f'{sid}.json', result)
    metadata = result['metadata']
    lines = ['bin_nmi,probability,mean_nmi,storm_id,image_time_utc,position_time_utc,satellite,channel,center_lat,center_lon,model_sha256']
    for radius, probability in zip(result['bins_nmi'], result['probabilities']):
        lines.append(','.join(str(v) for v in [radius, probability, result['mean_nmi'], sid,
            metadata['observed_at'], metadata['position_at'], metadata['satellite'], metadata['channel'],
            metadata['center_lat'], metadata['center_lon'], result['model_sha256']]))
    (directory / f'{sid}.csv').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build_site(output, previous_site=None):
    output = Path(output).resolve()
    frontend = (ROOT / 'frontend').resolve()
    if output == ROOT or output == frontend or output in frontend.parents or frontend in output.parents:
        raise ValueError('Build output must be separate from the frontend source directory.')
    _, _, digest = load_model()  # A broken checkpoint must fail the entire run.
    feed = fetch_storms()  # A total feed outage preserves the published site.
    if len(feed['storms']) > 100 or any(not SID.fullmatch(s.get('id', '')) for s in feed['storms']):
        raise ValueError('Invalid or unexpectedly large active-storm feed.')
    previous = previous_snapshot(previous_site)
    started = now_utc()
    records, products = {}, {}
    warnings = list(feed.get('warnings', []))
    for storm in feed['storms']:
        sid = storm['id']
        try:
            kelvin, metadata = get_patch(storm)
            metadata['storm'] = dict(storm)
            result = {**predict(kelvin), 'metadata': metadata, 'inferred_at': now_utc().isoformat(),
                      'experimental': True, 'out_of_basin': not storm['in_training_basin']}
            if not result_valid(result):
                raise ValueError('Model returned an invalid distribution.')
            png = render_ir_png(kelvin)
            status, message = 'ready', ''
        except Exception as exc:
            message = str(exc) if isinstance(exc, DataUnavailable) else '本次衛星下載、解碼或推論失敗，等待下次每小時更新。'
            print(f'{sid}: unavailable ({type(exc).__name__})', flush=True)
            old = reuse_previous(sid, previous, previous_site, digest, started) if previous and previous_site else None
            if old:
                result, png = old
                status = 'cached'
                message += ' 目前顯示上次成功結果，並非本次新推論。'
            else:
                records[sid] = {'status': 'unavailable', 'message': message}
                continue
        records[sid] = {'status': status, 'message': message, 'image_url': f'data/products/{sid}.png', 'result': result}
        products[sid] = (result, png)
        print(f'{sid}: {status}; mean={result["mean_nmi"]:.1f} n mi', flush=True)
    ready = sum(r['status'] == 'ready' for r in records.values())
    if records and not ready:
        warnings.append('本批次沒有新辨識結果；請查看各系統的原因與資料時間。')
    snapshot = {'schema_version': 1, 'mode': 'hourly', 'generation_id': uuid.uuid4().hex,
        'generated_at': now_utc().isoformat(), 'started_at': started.isoformat(),
        'fetched_at': feed['fetched_at'], 'scope': feed['scope'], 'warnings': warnings,
        'update_interval_seconds': 3600, 'stale_after_seconds': 7200,
        'model_sha256': digest, 'storms': feed['storms'], 'records': records,
        'summary': {'ready': ready, 'cached': sum(r['status'] == 'cached' for r in records.values()),
                    'unavailable': sum(r['status'] == 'unavailable' for r in records.values())}}
    shutil.copytree(frontend, output, dirs_exist_ok=True)
    directory = output / 'data' / 'products'
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.iterdir():
        if path.is_file() and PRODUCT.fullmatch(path.name) and path.stem not in products:
            path.unlink()
    for sid, (result, png) in products.items():
        write_product(directory, sid, result, png)
    write_json(output / 'data' / 'latest.json', snapshot)
    (output / '.nojekyll').touch()
    if any(path.suffix.lower() in ('.pth', '.pt', '.npy', '.npz', '.nc', '.bz2') for path in output.rglob('*')):
        raise ValueError('Build output contains a model or raw satellite file; publication stopped.')
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--previous-site', default=None)
    args = parser.parse_args()
    snapshot = build_site(args.output, args.previous_site)
    print(json.dumps(snapshot['summary']), flush=True)


if __name__ == '__main__':
    main()
