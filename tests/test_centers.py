from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from backend.centers import GEOD, CenterUnavailable, center_at
from backend.position_sources import parse_nhc, parse_jtwc, parse_tcvitals, enrich_positions, day_time
from backend import imagery

T0=datetime(2026,11,10,tzinfo=timezone.utc)
VITALS='NHC  04C PENA      20261110 0000 117N 1621W 275 062 1004 1009 0222 18 130 0167 -999 -999 -999 M\nJTWC 31W CEMPAKA   20261110 0000 250N 1380E 070 052 0964 1012 0306 48 027 0148 0148 0148 0148 D'
WARNING='''WTPN31 PGTW 100300
SUBJ/TYPHOON 31W (CEMPAKA) WARNING NR 016//
WARNING POSITION:
100000Z --- NEAR 25.0N 138.0E
MOVEMENT PAST SIX HOURS - 075 DEGREES AT 13 KTS
REMARKS:
100300Z POSITION NEAR 25.3N 139.0E.
'''


def point(lat=20.,lon=135.,hours=0,motion=None):
    return {'lat':lat,'lon':lon,'at':(T0+timedelta(hours=hours)).isoformat(),'source':'Test analysis',
            'source_url':'https://example.com/fix','motion':motion}


def storm(points=None):
    fixes=points or [point(motion={'bearing_deg':90.,'speed_kmh':20.})]
    latest=fixes[-1]
    return {'id':'31W','lat':latest['lat'],'lon':latest['lon'],'observed_at':latest['at'],
            'position_fixes':fixes,'source':'Tropical Tidbits / ATCF','source_url':'https://example.com'}


class CenterMathTests(unittest.TestCase):
    def test_three_hour_extrapolation_is_60km_toward_east(self):
        center=center_at(storm(),T0+timedelta(hours=3))
        az,_,distance=GEOD.inv(135,20,center['lon'],center['lat'])
        self.assertAlmostEqual(distance,60000,places=5)
        self.assertAlmostEqual(az,90,places=6)
        self.assertEqual(center['method'],'extrapolated_motion')
        self.assertEqual(center['valid_at'],(T0+timedelta(hours=3)).isoformat())

    def test_reported_center_at_exact_time_does_not_need_motion(self):
        center=center_at(storm([point()]),T0)
        self.assertEqual(center['method'],'reported')
        self.assertFalse(center['is_estimated'])
        self.assertEqual(center['displacement_km'],0)

    def test_bracketing_fixes_interpolate_not_extrapolate(self):
        lon,lat,_=GEOD.fwd(135,20,90,120000)
        center=center_at(storm([point(),point(lat,lon,6)]),T0+timedelta(hours=3))
        self.assertEqual(center['method'],'interpolated_track')
        _,_,distance=GEOD.inv(135,20,center['lon'],center['lat'])
        self.assertAlmostEqual(distance,60000,places=5)

    def test_history_velocity_can_supply_missing_motion(self):
        lon,lat,_=GEOD.fwd(135,20,270,120000)
        center=center_at(storm([point(lat,lon,-6),point()]),T0+timedelta(hours=3))
        self.assertEqual(center['method'],'extrapolated_history')
        self.assertAlmostEqual(center['speed_kmh'],20,places=5)
        self.assertAlmostEqual(center['displacement_km'],60,places=5)

    def test_no_long_or_unsupported_extrapolation(self):
        for s,t in [(storm(),T0+timedelta(hours=6,seconds=1)),(storm([point()]),T0+timedelta(hours=1)),(storm(),T0-timedelta(hours=1))]:
            with self.assertRaises(CenterUnavailable):center_at(s,t)

    def test_dateline_and_zero_speed(self):
        center=center_at(storm([point(lon=179.9,motion={'bearing_deg':90.,'speed_kmh':30.})]),T0+timedelta(hours=3))
        self.assertLess(center['lon'],-179)
        center=center_at(storm([point(motion={'bearing_deg':0.,'speed_kmh':0.})]),T0+timedelta(hours=3))
        self.assertAlmostEqual(center['lat'],20)
        self.assertAlmostEqual(center['lon'],135)


class PositionSourceTests(unittest.TestCase):
    def test_warning_timestamp_handles_month_and_year_rollover(self):
        reference=datetime(2027,1,1,tzinfo=timezone.utc)
        self.assertEqual(day_time('312100',reference),datetime(2026,12,31,21,tzinfo=timezone.utc))

    def test_nhc_motion_is_mph_not_knots(self):
        data={'activeStorms':[{'id':'cp042026','latitudeNumeric':11.7,'longitudeNumeric':-162.7,
            'lastUpdate':(T0+timedelta(hours=3)).isoformat(),'movementDir':275,'movementSpeed':14}]}
        position=parse_nhc(data)[0]
        self.assertAlmostEqual(position['motion']['speed_kmh'],22.530816)
        self.assertEqual(position['id'],'04C')

    def test_jtwc_uses_analysis_valid_time_not_issue_or_remark_time(self):
        position=parse_jtwc(WARNING,'31W',T0)[0]
        self.assertEqual(position['at'],T0.isoformat())
        self.assertEqual((position['lat'],position['lon']),(25.,138.))
        self.assertAlmostEqual(position['motion']['speed_kmh'],24.076)
        self.assertEqual(parse_jtwc(WARNING,'32W',T0),[])

    def test_tcvitals_units_and_climatology_flags(self):
        positions=parse_tcvitals(VITALS)
        self.assertEqual(len(positions),2)
        self.assertAlmostEqual(positions[1]['motion']['speed_kmh'],18.72)
        self.assertEqual(positions[0]['lon'],-162.1)
        line=list(VITALS.splitlines()[1]);line[43]='C'
        self.assertIsNone(parse_tcvitals(''.join(line))[0]['motion'])

    def test_enrichment_prefers_new_nhc_position_and_preserves_history(self):
        s={'id':'04C','lat':11.7,'lon':-162.1,'observed_at':T0.isoformat(),
           'source':'Tropical Tidbits / ATCF','source_url':'https://example.com'}
        nhc={'activeStorms':[{'id':'cp042026','latitudeNumeric':11.7,'longitudeNumeric':-162.7,
             'lastUpdate':(T0+timedelta(hours=3)).isoformat(),'movementDir':275,'movementSpeed':14}]}
        with patch('backend.position_sources.get_text',return_value=VITALS):
            enrich_positions([s],T0+timedelta(hours=5),nhc)
        self.assertEqual(s['observed_at'],(T0+timedelta(hours=3)).isoformat())
        self.assertEqual(s['lon'],-162.7)
        self.assertEqual(s['intensity_at'],T0.isoformat())
        self.assertEqual(len(s['position_fixes']),2)
        self.assertEqual(s['position_source'],'NOAA NHC/CPHC')


class ImageryCenterTests(unittest.TestCase):
    def test_actual_sampling_uses_estimated_center_and_cache_changes_with_motion(self):
        s=storm();image_time=T0+timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory, patch('backend.imagery.CACHE',Path(directory)), patch('backend.imagery.datetime') as clock, patch('backend.imagery.latest_himawari',return_value=('test',['test.dat.bz2'],image_time)), patch('backend.imagery.download',return_value=Path('test.dat.bz2')), patch('backend.imagery.sample_himawari',return_value=np.full((156,156),236.5)) as sample:
            clock.now.return_value=image_time+timedelta(minutes=10)
            clock.fromisoformat.side_effect=datetime.fromisoformat
            _,meta=imagery.get_patch(s)
            args=sample.call_args.args
            self.assertAlmostEqual(args[1],meta['center_lat'])
            self.assertAlmostEqual(args[2],meta['center_lon'])
            self.assertNotEqual(meta['center_lon'],s['lon'])
            self.assertAlmostEqual(meta['center_estimation']['displacement_km'],60,places=5)
            s['position_fixes'][0]['motion']['speed_kmh']=40
            _,second=imagery.get_patch(s)
            self.assertNotEqual(meta['id'],second['id'])
            self.assertEqual(sample.call_count,2)
