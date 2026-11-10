"""Global storm metadata; imagery is fetched separately as calibrated Kelvin data."""
from datetime import datetime, timezone
from html import unescape
import re
import requests

TT = 'https://www.tropicaltidbits.com/storminfo/stormhtml.json'
NHC = 'https://www.nhc.noaa.gov/CurrentStorms.json'
BASINS = {'L': '北大西洋', 'E': '東北太平洋', 'C': '中太平洋', 'W': '西北太平洋',
          'A': '阿拉伯海', 'B': '孟加拉灣', 'S': '南印度洋', 'P': '南太平洋'}


def parse_tidbits(data):
    storms = []
    for sid, markup in data.items():
        if not re.fullmatch(r'\d{2}[LECWABSP]', sid):
            continue
        text = unescape(re.sub('<[^>]+>', ' ', markup))
        loc = re.search(r'Location:\s*([\d.]+)°([NS])\s+([\d.]+)°([EW])', text)
        date = re.search(r'As of (\d{2}:\d{2}) UTC ([A-Za-z]{3} \d{1,2}, \d{4})', text)
        name = re.search(r'class="storm-name">([^<]+)', markup)
        if not loc or not date or not name:
            continue
        lat, ns, lon, ew = loc.groups()
        observed = datetime.strptime(' '.join(date.groups()), '%H:%M %b %d, %Y').replace(tzinfo=timezone.utc)
        wind = re.search(r'Maximum Winds:\s*(\d+) kt', text)
        pressure = re.search(r'Minimum Central Pressure:\s*(\d+) mb', text)
        storms.append({'id': sid, 'name': unescape(name[1]).strip(),
            'lat': float(lat) * (-1 if ns == 'S' else 1),
            'lon': float(lon) * (-1 if ew == 'W' else 1), 'basin': BASINS[sid[-1]],
            'wind_kt': int(wind[1]) if wind else None, 'pressure_hpa': int(pressure[1]) if pressure else None,
            'observed_at': observed.isoformat(), 'in_training_basin': sid.endswith('L'),
            'source': 'Tropical Tidbits / ATCF', 'source_url': 'https://www.tropicaltidbits.com/storminfo/#' + sid})
    if data and not storms:
        raise ValueError('Global storm feed format has changed; no valid positions parsed.')
    return storms


def fetch_storms():
    warnings = []
    nhc_data = None
    try:
        response = requests.get(TT, timeout=(10, 30))
        response.raise_for_status()
        storms = parse_tidbits(response.json())
        scope = 'global'
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        warnings.append('全球清單暫時無法取得；目前僅顯示 NHC 管轄海盆，並非全球無其他系統。')
        response = requests.get(NHC, timeout=(10, 30))
        response.raise_for_status()
        storms = []
        nhc_data = response.json()
        for s in nhc_data['activeStorms']:
            suffix = {'al': 'L', 'ep': 'E', 'cp': 'C'}.get(s['id'][:2])
            if suffix is None:
                continue
            storms.append({'id': s['id'][2:4] + suffix, 'name': s['name'],
                'lat': float(s['latitudeNumeric']), 'lon': float(s['longitudeNumeric']),
                'basin': BASINS[suffix], 'observed_at': s['lastUpdate'],
                'wind_kt': int(s['intensity']), 'pressure_hpa': int(s['pressure']) if s.get('pressure') else None,
                'in_training_basin': suffix == 'L', 'source': 'NOAA NHC', 'source_url': NHC})
        scope = 'NHC-only'
    now = datetime.now(timezone.utc)
    from .position_sources import enrich_positions
    enrich_positions(storms, now, nhc_data)
    for s in storms:
        s['position_age_hours'] = round((now - datetime.fromisoformat(s['observed_at'].replace('Z', '+00:00'))).total_seconds()/3600, 2)
        s['stale'] = not 0 <= s['position_age_hours'] <= 12
    return {'storms': sorted(storms, key=lambda s: s['id']), 'scope': scope,
            'fetched_at': now.isoformat(), 'warnings': warnings}
