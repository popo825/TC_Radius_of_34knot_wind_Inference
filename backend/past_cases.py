"""Prepare the two published archive cases on demand: python -m backend.past_cases."""

from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import islice
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import time

import numpy as np
import requests

from .imagery import CACHE, DataUnavailable, sample_goes, s3_keys
from .model import ROOT, load_model, predict
from .rendering import render_ir_png


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


CASES = (
    ('isaias-2026', 'Hurricane Isaias', 'North Atlantic', 'al092026', 'GOES-19',
     '2026-10-08T00:00', '2026-10-09T18:00'),
    ('polo-2026', 'Hurricane Polo', 'Eastern North Pacific', 'ep172026', 'GOES-18',
     '2026-09-21T06:00', '2026-09-29T00:00'),
)
OUTPUT = ROOT / 'frontend' / 'data' / 'past'
ARCHIVE_CACHE = CACHE / 'past-storms'


def retry(operation):
    for attempt in range(3):
        try:
            return operation()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def response(url):
    result = requests.get(url, timeout=(10, 45))
    result.raise_for_status()
    return result


def read_track(url, storm_id):
    fixes = {}
    for line in retry(lambda: response(url)).text.splitlines():
        fields = [part.strip() for part in line.split(',')]
        if len(fields) < 8 or fields[4] != 'BEST':
            continue
        if ''.join((fields[0].lower(), fields[1], fields[2][:4])) != storm_id:
            raise ValueError(f'Unexpected storm ID in {url}')
        stamp = datetime.strptime(fields[2], '%Y%m%d%H').replace(tzinfo=timezone.utc)
        # ATCF BEST rows can supply a non-synoptic fix minute in column 4.
        stamp += timedelta(minutes=int(fields[3] or 0))
        lat, lon = (int(field[:-1]) / 10 * (-1 if field[-1] in 'SW' else 1)
                    for field in fields[6:8])
        if stamp in fixes and fixes[stamp] != (lat, lon):
            raise ValueError(f'Conflicting positions at {stamp.isoformat()}')
        fixes[stamp] = (lat, lon)
    if len(fixes) < 2:
        raise ValueError(f'Not enough NHC BEST positions in {url}')
    return dict(sorted(fixes.items()))


def position_at(track, stamp):
    times = list(track)
    index = bisect_left(times, stamp)
    if index < len(times) and times[index] == stamp:
        return (*track[stamp], 'reported', [stamp.isoformat()])
    if not 0 < index < len(times):
        raise DataUnavailable('No official fixes bracket the requested time.')
    left, right = times[index - 1:index + 1]
    a, b = track[left], track[right]
    fraction = (stamp - left) / (right - left)
    lat = a[0] + (b[0] - a[0]) * fraction
    lon_delta = (b[1] - a[1] + 180) % 360 - 180
    lon = (a[1] + lon_delta * fraction + 180) % 360 - 180
    return (lat, lon, 'interpolated', [left.isoformat(), right.isoformat()])


def closest_scan(slot, satellite):
    bucket = 'noaa-goes' + satellite.split('-')[1]
    scans = []
    for hour in (slot, slot - timedelta(hours=1)):
        keys = retry(lambda: s3_keys(bucket, f'ABI-L2-CMIPF/{hour:%Y/%j/%H}/'))
        for key in keys:
            match = re.search(r'_s(\d{13})', key)
            if 'C14_' not in key or not match:
                continue
            observed = datetime.strptime(match[1], '%Y%j%H%M%S').replace(tzinfo=timezone.utc)
            if -timedelta(minutes=30) <= observed - slot < timedelta(minutes=30):
                scans.append((observed, key))
        if scans and min(abs(t - slot) for t, _ in scans) < timedelta(minutes=1):
            break
    if scans:
        observed, key = min(scans, key=lambda scan: (abs(scan[0] - slot), scan[0], scan[1]))
        return observed, f'https://{bucket}.s3.amazonaws.com/{key}'
    return None


def prepare_frame(slot, satellite, track, scratch, case_cache):
    """Resolve and download one scan, or reuse the persisted Kelvin crop."""
    stamp = slot.strftime('%Y%m%d%H')
    cached_meta = case_cache / f'{stamp}.json'
    cached_crop = case_cache / f'{stamp}.npy'
    # Invalidate crops if NOAA revises the positions used to center them.
    satellites = ('GOES-18', 'GOES-19') if satellite == 'GOES-18' else (satellite,)
    if cached_meta.exists() and cached_crop.exists():
        meta = json.loads(cached_meta.read_text(encoding='utf-8'))
        if meta['satellite'] in satellites and meta['center'] == list(
            position_at(track, datetime.fromisoformat(meta['observed_at']))
        ):
            return meta, cached_crop
    for satellite in satellites:
        scan = closest_scan(slot, satellite)
        if scan is not None:
            break
    else:
        raise DataUnavailable('No archived ABI C14 scan within 30 minutes of this hour.')
    observed, url = scan
    center = position_at(track, observed)
    raw = scratch / f'{stamp}.nc'
    raw.write_bytes(retry(lambda: response(url)).content)
    return {'observed_at': observed.isoformat(), 'center': list(center), 'satellite': satellite,
            'source_url': url}, raw


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False),
                         encoding='utf-8')
    temporary.replace(path)


def build_case(case, digest, workers):
    slug, name, basin, storm_id, satellite, start, end = case
    start, end = utc(start), utc(end)
    url = f'https://ftp.nhc.noaa.gov/atcf/btk/b{storm_id}.dat'
    track = read_track(url, storm_id)
    slots = [start + timedelta(hours=i) for i in range(int((end - start).total_seconds() / 3600) + 1)]
    output = OUTPUT / slug
    output.mkdir(parents=True, exist_ok=True)
    case_cache = ARCHIVE_CACHE / slug
    case_cache.mkdir(parents=True, exist_ok=True)
    manifest = output / 'case.json'
    previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    if previous.get('model_sha256') == digest:
        old_frames = {f['time']: f for f in previous['frames']
                      if 'mean_nmi' in f and (output / f['image']).is_file()}
    else:
        old_frames = {}
    frames = []
    # Bound downloaded files to a batch. Decode NetCDF and run PyTorch serially.
    with TemporaryDirectory(dir=case_cache) as directory, ThreadPoolExecutor(max_workers=workers) as pool:
        scratch = Path(directory)
        remaining = iter(slot for slot in slots if slot.isoformat() not in old_frames)
        downloads = {slot: pool.submit(prepare_frame, slot, satellite, track, scratch, case_cache)
                     for slot in islice(remaining, workers * 2)}
        for slot in slots:
            if slot.isoformat() in old_frames:
                frames.append(old_frames[slot.isoformat()])
                continue
            download = downloads.pop(slot)
            next_slot = next(remaining, None)
            if next_slot is not None:
                downloads[next_slot] = pool.submit(prepare_frame, next_slot, satellite, track, scratch, case_cache)
            stamp = slot.strftime('%Y%m%d%H')
            lat, lon, method, fixes = position_at(track, slot)
            frame = {'time': slot.isoformat(), 'lat': lat, 'lon': lon, 'center_method': method,
                     'center_fixes': fixes}
            try:
                meta, file = download.result()
                lat, lon, method, fixes = meta['center']
                if file.suffix == '.npy':
                    kelvin = np.load(file, allow_pickle=False)
                else:
                    try:
                        kelvin = sample_goes(file, lat, lon)
                    finally:
                        file.unlink(missing_ok=True)
                    if np.isfinite(kelvin).mean() < .98:
                        raise DataUnavailable('The storm crop has more than 2% missing temperatures.')
                    np.save(case_cache / f'{stamp}.npy', kelvin)
                    write_json(case_cache / f'{stamp}.json', meta)
                result = predict(kelvin)
                image = f'{stamp}.png'
                if file.suffix != '.npy' or not (output / image).exists():
                    (output / image).write_bytes(render_ir_png(kelvin))
                frame.update(lat=lat, lon=lon, center_method=method, center_fixes=fixes,
                             observed_at=meta['observed_at'], source_url=meta['source_url'],
                             satellite=meta['satellite'],
                             image=image, mean_nmi=result['mean_nmi'], probabilities=result['probabilities'])
            except (DataUnavailable, requests.RequestException) as exc:
                frame['unavailable'] = (str(exc) if isinstance(exc, DataUnavailable)
                                        else 'The NOAA archive request failed. Retry archive preparation.')
            frames.append(frame)
            print(f'{slug} {len(frames)}/{len(slots)} {stamp}: '
                  f'{frame.get("unavailable", "ready")}', flush=True)
    route_times = sorted({start, end, *(t for t in track if start <= t <= end)})
    route = [{'time': t.isoformat(), 'lat': position_at(track, t)[0], 'lon': position_at(track, t)[1]}
             for t in route_times]
    _, bins, _ = load_model()
    write_json(manifest, {'schema_version': 1, 'id': slug, 'name': name, 'basin': basin,
                          'track_url': url, 'satellite': satellite, 'channel': 'ABI C14',
                          'model_sha256': digest, 'bins_nmi': bins.tolist(), 'track': route, 'frames': frames})
    return sum('mean_nmi' in frame for frame in frames), len(frames)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=range(1, 17), default=12)
    args = parser.parse_args()
    _, _, digest = load_model()
    for case in CASES:
        ready, total = build_case(case, digest, args.workers)
        print(f'{case[1]}: {ready}/{total} saved', flush=True)


if __name__ == '__main__':
    main()
