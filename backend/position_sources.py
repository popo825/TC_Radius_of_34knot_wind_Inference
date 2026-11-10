"""Official position/motion enrichment, independent of satellite acquisition.

NHC JSON movementSpeed is mph; JTWC warnings use kt; NCEP TCVitals use 0.1 m/s.
Warning issue times are never substituted for the WARNING POSITION valid time.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import re
import requests
from .centers import GEOD, timestamp, valid_motion

NHC_URL = 'https://www.nhc.noaa.gov/CurrentStorms.json'
SID = re.compile(r'^\d{2}[LECWABSP]$')


def coordinate(value, tenths=False):
    number = float(value[:-1]) / (10 if tenths else 1)
    return number * (-1 if value[-1] in 'SW' else 1)


def fix(sid, lat, lon, at, source, url, rank, motion=None):
    if not SID.fullmatch(sid) or not math.isfinite(lat) or not math.isfinite(lon) or abs(lat)>90 or abs(lon)>180:
        raise ValueError('Invalid position fix.')
    return {'id': sid, 'lat':lat, 'lon':lon, 'at':timestamp(at).isoformat(), 'source':source,
        'source_url':url, 'rank':rank, 'motion':motion if valid_motion(motion) else None}


def parse_nhc(data):
    points=[]
    for s in data.get('activeStorms', []):
        try:
            suffix={'al':'L','ep':'E','cp':'C'}[s['id'][:2].lower()]
            sid=s['id'][2:4]+suffix
            motion={'bearing_deg':float(s['movementDir']), 'speed_kmh':float(s['movementSpeed'])*1.609344,
                    'source':'NHC/CPHC motion (mph converted to km/h)'} if s.get('movementDir') is not None and s.get('movementSpeed') is not None else None
            points.append(fix(sid,float(s['latitudeNumeric']),float(s['longitudeNumeric']),s['lastUpdate'],
                              'NOAA NHC/CPHC',NHC_URL,30,motion))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def parse_tcvitals(text, url=''):
    points=[]
    for line in text.splitlines():
        try:
            if len(line)<51 or line[:4].strip() not in ('NHC','JTWC'):
                continue
            sid=line[5:8]
            at=datetime.strptime(line[19:27]+line[28:32],'%Y%m%d%H%M').replace(tzinfo=timezone.utc)
            motion=None
            # Climatological movement is unsuitable for time-aligned centering.
            if line[43]!='C' and line[47]!='C':
                motion={'bearing_deg':float(line[44:47]),'speed_kmh':float(line[48:51])*.36,
                        'source':'NCEP TCVitals motion (0.1 m/s converted to km/h)',
                        'direction_flag':line[43].strip(), 'speed_flag':line[47].strip()}
            points.append(fix(sid,coordinate(line[33:37],True),coordinate(line[38:43],True),at,
                              f'NOAA NCEP TCVitals / {line[:4].strip()}',url,20,motion))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def day_time(value, reference):
    candidates=[]
    for offset in (-32,0,32):
        month=(reference.replace(day=15)+timedelta(days=offset)).replace(day=1)
        try:
            candidates.append(month.replace(day=int(value[:2]),hour=int(value[2:4]),minute=int(value[4:6]),second=0,microsecond=0))
        except ValueError:
            pass
    return min(candidates,key=lambda t:abs((t-reference).total_seconds()))


def parse_jtwc(text, sid, reference, url=''):
    identity=re.search(r'\b(\d{2}[WSPAB])\s+\(',text)
    position=re.search(r'WARNING POSITION:\s*(\d{6})Z\s*---\s*NEAR\s+([\d.]+[NS])\s+([\d.]+[EW])',text)
    if not identity or identity[1]!=sid or not position:
        return []
    motion_match=re.search(r'MOVEMENT PAST SIX HOURS\s*-\s*(\d+) DEGREES AT\s*([\d.]+) KTS',text)
    motion={'bearing_deg':float(motion_match[1]),'speed_kmh':float(motion_match[2])*1.852,
            'source':'JTWC past-six-hour motion (kt converted to km/h)'} if motion_match else None
    at=day_time(position[1],reference)
    return [fix(sid,coordinate(position[2]),coordinate(position[3]),at,'JTWC warning',url,30,motion)]


def get_text(url):
    response=requests.get(url,timeout=(5,15))
    response.raise_for_status()
    return response.text


def read_nhc():
    response=requests.get(NHC_URL,timeout=(5,15));response.raise_for_status()
    return parse_nhc(response.json())


def read_jtwc(storm):
    sid=storm['id'];prefix={'W':'wp','S':'sh','P':'sh','A':'io','B':'io'}.get(sid[-1])
    if not prefix:
        return []
    reference=timestamp(storm['observed_at'])
    season=reference.year+(1 if sid[-1] in 'SP' and reference.month>=7 else 0)
    for year in dict.fromkeys([season,reference.year]):
        url=f'https://www.metoc.navy.mil/jtwc/products/{prefix}{sid[:2]}{year%100:02d}web.txt'
        try:
            points=parse_jtwc(get_text(url),sid,reference,url)
            if points:return points
        except (requests.RequestException,ValueError):
            continue
    return []


def enrich_positions(storms, now, nhc_data=None):
    if not storms:
        return
    cycle=now.replace(hour=now.hour//6*6,minute=0,second=0,microsecond=0)
    tasks=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks.append(pool.submit(parse_nhc,nhc_data) if nhc_data is not None else pool.submit(read_nhc))
        for delta in (0,6):
            t=cycle-timedelta(hours=delta)
            url=f'https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{t:%Y%m%d}/{t:%H}/atmos/gfs.t{t:%H}z.syndata.tcvitals.tm00'
            def vitals(url=url):
                return parse_tcvitals(get_text(url),url)
            tasks.append(pool.submit(vitals))
        tasks.extend(pool.submit(read_jtwc,s) for s in storms if s['id'][-1] in 'WSPAB')
        points=[]
        for task in tasks:
            try:points.extend(task.result())
            except (requests.RequestException,TypeError,KeyError,ValueError):pass
    for storm in storms:
        base=fix(storm['id'],storm['lat'],storm['lon'],storm['observed_at'],storm['source'],storm['source_url'],10)
        candidates=[base]+[p for p in points if p['id']==storm['id'] and 0 <= (now-timestamp(p['at'])).total_seconds() <= 24*3600]
        selected={}
        for point in sorted(candidates,key=lambda p:p['rank']):
            previous=selected.get(point['at'])
            if previous and not point['motion'] and previous['motion']:
                _,_,distance=GEOD.inv(point['lon'],point['lat'],previous['lon'],previous['lat'])
                if distance<20000:point={**point,'motion':previous['motion']}
            selected[point['at']]=point
        history=sorted(selected.values(),key=lambda p:timestamp(p['at']))
        latest=history[-1]
        storm['intensity_at']=storm.get('intensity_at',storm['observed_at'])
        storm.update(lat=latest['lat'],lon=latest['lon'],observed_at=latest['at'],
                     position_source=latest['source'],position_source_url=latest['source_url'],
                     position_fixes=history,motion=latest['motion'])
