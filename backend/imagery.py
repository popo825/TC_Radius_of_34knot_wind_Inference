"""Native 11.2 µm observations, geolocated and resampled before normalization."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import os
import re
import threading
import xml.etree.ElementTree as ET
import numpy as np
import requests
from pyproj import CRS, Transformer
from scipy.ndimage import map_coordinates

CACHE = Path(os.getenv('R34_CACHE_DIR', str(Path(__file__).resolve().parents[1] / '.cache')))
MAX_IMAGE_MINUTES = 90
_io_lock = threading.Lock()


class DataUnavailable(RuntimeError):
    pass


def target_grid(lat, lon):
    """156 pixel centers spaced 8 km; outer edges span exactly 1248 km.

    A local azimuthal equidistant projection avoids a latitude-dependent width.
    North is up. The center lies between the four central pixels (even size).
    """
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m')
    axis = (np.arange(156) - 77.5) * 8000
    x, y = np.meshgrid(axis, -axis)
    lng, lats = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(x, y)
    return crs, lng, lats


def satellite_for(lon):
    distance = lambda origin: abs((lon - origin + 180) % 360 - 180)
    # Keep the entire 1248 km patch away from the limb. The adapter validates
    # coverage after resampling and refuses a patch with >2% missing data.
    candidates = [('GOES-19', -75.2), ('GOES-18', -137.2), ('Himawari-9', 140.7)]
    name, origin = min(candidates, key=lambda pair: distance(pair[1]))
    if distance(origin) > 65:
        raise DataUnavailable('此區需要 Meteosat／印度洋原始亮溫資料。公開 CPC 合成資料約延遲兩天，不能作為即時輸入；此版本不執行辨識。')
    return name


def s3_keys(bucket, prefix):
    keys, token = [], None
    while True:
        params = {'list-type': '2', 'prefix': prefix}
        if token:
            params['continuation-token'] = token
        r = requests.get(f'https://{bucket}.s3.amazonaws.com/', params=params, timeout=(10, 45))
        r.raise_for_status()
        root = ET.fromstring(r.content)
        keys.extend(x.text for x in root.findall('{*}Contents/{*}Key'))
        token = root.findtext('{*}NextContinuationToken')
        if not token:
            return keys


def download(bucket, key):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / key.rsplit('/', 1)[-1]
    if path.exists():
        return path
    r = requests.get(f'https://{bucket}.s3.amazonaws.com/{key}', timeout=(15, 180), stream=True)
    r.raise_for_status()
    part = path.with_suffix(path.suffix + '.part')
    try:
        with part.open('wb') as out:
            for chunk in r.iter_content(1024 * 1024):
                out.write(chunk)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    return path


def latest_goes(satellite, now):
    bucket = 'noaa-goes' + satellite.split('-')[1]
    for offset in range(3):
        t = now - timedelta(hours=offset)
        keys = [k for k in s3_keys(bucket, f'ABI-L2-CMIPF/{t:%Y/%j/%H}/') if 'C14_' in k]
        if keys:
            key = max(keys, key=lambda k: k.split('_s')[1])
            stamp = re.search(r'_s(\d{13})', key)[1]
            observed = datetime.strptime(stamp, '%Y%j%H%M%S').replace(tzinfo=timezone.utc)
            if (now - observed).total_seconds() > MAX_IMAGE_MINUTES * 60:
                break
            return bucket, [key], observed
    raise DataUnavailable('GOES C14 在最近 90 分鐘內沒有可用的完整觀測。')


def latest_himawari(now):
    bucket = 'noaa-himawari9'
    base = now.replace(minute=now.minute // 10 * 10, second=0, microsecond=0)
    for offset in range(10):
        t = base - timedelta(minutes=offset * 10)
        if (now - t).total_seconds() > MAX_IMAGE_MINUTES * 60:
            break
        keys = [k for k in s3_keys(bucket, f'AHI-L1b-FLDK/{t:%Y/%m/%d/%H%M}/') if '_B14_' in k and k.endswith('.bz2')]
        if len(keys) == 10:
            return bucket, sorted(keys), t
    raise DataUnavailable('Himawari B14 在最近 90 分鐘內沒有完整的 10 段全圓盤觀測。')


def sample_goes(path, lat, lon):
    # CMI for an IR band is already calibrated brightness temperature in Kelvin.
    # netCDF4 serial access: HDF5 libraries may not be thread-safe.
    from netCDF4 import Dataset
    # netCDF4/HDF5 on Windows can reject non-ASCII filesystem paths. Opening a
    # memory buffer keeps the project usable in Chinese-named directories.
    with Dataset('satellite.nc', memory=path.read_bytes()) as ds:
        cmi = ds.variables['CMI']
        if str(getattr(cmi, 'units', '')).lower() not in ('k', 'kelvin'):
            raise DataUnavailable('GOES CMI units are not Kelvin.')
        p = ds.variables['goes_imager_projection']
        crs = CRS.from_cf({k: p.getncattr(k) for k in p.ncattrs()})
        _, lng, lats = target_grid(lat, lon)
        xx, yy = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform(lng, lats)
        x, y = np.asarray(ds['x'][:]), np.asarray(ds['y'][:])
        h = float(p.perspective_point_height)
        cols = (xx / h - x[0]) / (x[1] - x[0])
        rows = (yy / h - y[0]) / (y[1] - y[0])
        valid = np.isfinite(cols) & np.isfinite(rows) & (cols >= 0) & (rows >= 0) & (cols <= len(x)-1) & (rows <= len(y)-1)
        if valid.mean() < .98:
            raise DataUnavailable('此系統的 1248 km 裁切超出衛星有效視野。')
        x0, x1 = max(0, int(np.floor(cols[valid].min()))-1), min(len(x), int(np.ceil(cols[valid].max()))+2)
        y0, y1 = max(0, int(np.floor(rows[valid].min()))-1), min(len(y), int(np.ceil(rows[valid].max()))+2)
        temp = np.ma.filled(cmi[y0:y1, x0:x1], np.nan).astype(np.float32)
        if 'DQF' in ds.variables:
            quality = np.ma.filled(ds['DQF'][y0:y1, x0:x1], 255)
            temp[quality > 1] = np.nan
        patch = map_coordinates(temp, [np.where(valid, rows-y0, -1), np.where(valid, cols-x0, -1)], order=1, mode='constant', cval=np.nan)
        patch[~valid] = np.nan
        return patch


def sample_himawari(paths, lat, lon):
    from satpy import Scene
    from pyresample.geometry import AreaDefinition
    crs, _, _ = target_grid(lat, lon)
    area = AreaDefinition('storm', '1248 km storm-centered square', 'aeqd', crs, 156, 156,
                          (-624000, -624000, 624000, 624000))
    scene = Scene(reader='ahi_hsd', filenames=[str(p) for p in paths])
    scene.load(['B14'], calibration='brightness_temperature')
    # Crop before resampling so no full-disk geographic lookup arrays are made.
    native = scene.crop(xy_bbox=None, ll_bbox=_bbox(lat, lon)) if abs(lon) < 170 else scene
    result = native.resample(area, resampler='nearest', radius_of_influence=12000)
    image = result['B14']
    if image.attrs.get('units') != 'K':
        raise DataUnavailable('Himawari decoder did not return Kelvin.')
    return np.asarray(image.compute().values, dtype=np.float32)


def _bbox(lat, lon):
    _, lng, lats = target_grid(lat, lon)
    return float(lng.min()), float(lats.min()), float(lng.max()), float(lats.max())


def get_patch(storm):
    now = datetime.now(timezone.utc)
    position_time = datetime.fromisoformat(storm['observed_at'].replace('Z', '+00:00'))
    if not 0 <= (now - position_time).total_seconds() <= 12*3600:
        raise DataUnavailable('定位資料超過 12 小時或時間不正確，請稍後重新整理。')
    satellite = satellite_for(storm['lon'])
    # Serialize providers to avoid duplicate files and non-thread-safe netCDF reads.
    with _io_lock:
        bucket, keys, observed = latest_himawari(now) if satellite.startswith('Himawari') else latest_goes(satellite, now)
        if abs((observed - position_time).total_seconds()) > 6 * 3600:
            raise DataUnavailable('影像與氣旋定位相差超過 6 小時，無法可靠對中裁切。')
        identity = hashlib.sha256((' '.join(keys) + f'/{storm["lat"]}/{storm["lon"]}/aeqd8km-v1').encode()).hexdigest()[:24]
        CACHE.mkdir(parents=True, exist_ok=True)
        patch_file = CACHE / f'patch-{identity}.npy'
        if patch_file.exists():
            patch = np.load(patch_file, allow_pickle=False)
        else:
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = list(pool.map(lambda k: download(bucket, k), keys))
            patch = sample_himawari(paths, storm['lat'], storm['lon']) if satellite.startswith('Himawari') else sample_goes(paths[0], storm['lat'], storm['lon'])
            if np.isfinite(patch).mean() < .98:
                raise DataUnavailable('裁切亮溫缺值超過 2%，已停止辨識。')
            np.save(patch_file, patch, allow_pickle=False)
        # Bound raw-file storage; storm patches are small and retained for provenance.
        raw = sorted([p for p in CACHE.iterdir() if p.suffix in ('.nc', '.bz2')], key=lambda p: p.stat().st_mtime, reverse=True)
        for old in raw[30:]:
            old.unlink(missing_ok=True)
    metadata = {'id': identity, 'satellite': satellite, 'channel': 'AHI B14' if satellite.startswith('Himawari') else 'ABI C14',
        'wavelength_um': 11.2, 'observed_at': observed.isoformat(), 'position_at': storm['observed_at'],
        'image_age_minutes': round((now - observed).total_seconds()/60, 1), 'position_image_offset_hours': round((observed-position_time).total_seconds()/3600, 2),
        'center_lat': storm['lat'], 'center_lon': storm['lon'], 'size_pixels': 156, 'pixel_km': 8, 'extent_km': 1248,
        'projection': 'WGS84 local azimuthal equidistant', 'units': 'K',
        'source_urls': [f'https://{bucket}.s3.amazonaws.com/{k}' for k in keys],
        'resampling': 'nearest' if satellite.startswith('Himawari') else 'bilinear',
        'missing_fraction': float(1 - np.isfinite(patch).mean())}
    return patch, metadata
