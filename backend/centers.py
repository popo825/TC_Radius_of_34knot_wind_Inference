"""Align reported TC positions with an image timestamp on the WGS84 ellipsoid."""
from datetime import datetime, timezone
import math
from pyproj import Geod

GEOD = Geod(ellps='WGS84')
MAX_EXTRAPOLATION_HOURS = 6


class CenterUnavailable(ValueError):
    pass


def timestamp(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if t.tzinfo is None:
        raise ValueError('Position and image timestamps must include a timezone.')
    return t.astimezone(timezone.utc)


def valid_motion(motion):
    try:
        return (math.isfinite(motion['bearing_deg']) and 0 <= motion['bearing_deg'] <= 360
                and math.isfinite(motion['speed_kmh']) and 0 <= motion['speed_kmh'] <= 200)
    except (TypeError, KeyError):
        return False


def center_at(storm, image_time):
    target = timestamp(image_time)
    fixes = storm.get('position_fixes') or [{'lat': storm['lat'], 'lon': storm['lon'],
        'at': storm['observed_at'], 'source': storm.get('position_source', storm.get('source', 'reported')),
        'source_url': storm.get('position_source_url', storm.get('source_url', '')), 'motion': storm.get('motion')}]
    fixes = sorted(fixes, key=lambda p: timestamp(p['at']))
    before = [p for p in fixes if timestamp(p['at']) <= target]
    after = [p for p in fixes if timestamp(p['at']) >= target]
    if not before:
        raise CenterUnavailable('影像早於所有可用定位，無法可靠對中；不使用未驗證的反向外推。')
    base = before[-1]
    hours = (target - timestamp(base['at'])).total_seconds() / 3600
    refs, method, bearing, speed = [base], 'reported', None, None
    lat, lon = base['lat'], base['lon']
    if hours > 1e-7:
        if after and 0 < (timestamp(after[0]['at'])-timestamp(base['at'])).total_seconds() <= 6*3600:
            end = after[0]
            interval = (timestamp(end['at'])-timestamp(base['at'])).total_seconds() / 3600
            bearing, _, distance = GEOD.inv(lon, lat, end['lon'], end['lat'])
            speed = distance / 1000 / interval
            if speed > 200:
                raise CenterUnavailable('兩筆定位推算的移動速度不合理，已停止對中。')
            lon, lat, _ = GEOD.fwd(lon, lat, bearing, distance * hours / interval)
            refs, method = [base, end], 'interpolated_track'
        else:
            if hours > MAX_EXTRAPOLATION_HOURS:
                raise CenterUnavailable('影像超過基準定位 6 小時，已停止線性外推。')
            motion = base.get('motion')
            if valid_motion(motion):
                bearing, speed = motion['bearing_deg'], motion['speed_kmh']
                method = 'extrapolated_motion'
            elif len(before) >= 2:
                previous = before[-2]
                interval = (timestamp(base['at'])-timestamp(previous['at'])).total_seconds()/3600
                if not .25 <= interval <= 12:
                    raise CenterUnavailable('缺少可靠移動向量或相鄰歷史定位，無法外推。')
                _, back_azimuth, distance = GEOD.inv(previous['lon'], previous['lat'], lon, lat)
                bearing, speed = (back_azimuth + 180) % 360, distance / 1000 / interval
                if speed > 200:
                    raise CenterUnavailable('歷史定位推算的移動速度不合理，已停止外推。')
                refs, method = [previous, base], 'extrapolated_history'
            else:
                raise CenterUnavailable('缺少移動方向、速度與歷史定位，無法估計影像時刻的中心。')
            lon, lat, _ = GEOD.fwd(lon, lat, bearing, speed * hours * 1000)
    _, _, displacement = GEOD.inv(base['lon'], base['lat'], lon, lat)
    return {'lat': float(lat), 'lon': float((lon+180)%360-180), 'method': method,
        'valid_at': target.isoformat(), 'reference_at': base['at'], 'reference_lat': base['lat'],
        'reference_lon': base['lon'], 'reference_source': base['source'],
        'reference_source_url': base.get('source_url', ''), 'elapsed_hours': hours,
        'displacement_km': displacement/1000, 'bearing_deg': None if bearing is None else bearing%360,
        'speed_kmh': speed, 'reference_fixes': [{k:v for k,v in p.items() if k!='rank'} for p in refs],
        'is_estimated': method!='reported'}
