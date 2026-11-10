"""Scientific/API invariants. No network calls and no synthetic results in the UI."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import torch
from fastapi.testclient import TestClient
from pyproj import Geod
from backend import app as api
from backend.imagery import DataUnavailable, satellite_for, target_grid
from backend.model import MODEL_PATH, MEAN_K, STD_K, predict
from backend.storms import parse_tidbits


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_square_footprint_and_orientation(self):
        for lat, lon in [(25, 135), (20, -75), (-15, 179.8)]:
            crs, lng, lats = target_grid(lat, lon)
            self.assertEqual(lng.shape, (156, 156))
            self.assertGreater(lats[0, 78], lats[-1, 78])
            # 155 intervals between pixel centers, plus two half pixels = 1248 km.
            _, _, dist = Geod(ellps='WGS84').inv(lng[77, 0], lats[77, 0], lng[77, -1], lats[77, -1])
            self.assertAlmostEqual(dist / 1000, 1240, delta=.1)

    def test_atcf_hemispheres_and_bins_not_scraped_from_jpg(self):
        sample = {'03S': '<span class="storm-name">Tropical Cyclone THREE</span> As of 12:00 UTC Nov 09, 2026: Location: 10.2&deg;S 48.7&deg;E Maximum Winds: 25 kt Minimum Central Pressure: 1011 mb'}
        s = parse_tidbits(sample)[0]
        self.assertEqual((s['lat'], s['lon']), (-10.2, 48.7))
        self.assertFalse(s['in_training_basin'])
        self.assertEqual(s['wind_kt'], 25)
        with self.assertRaises(ValueError):
            parse_tidbits({'31W': '<div>changed upstream format</div>'})
        self.assertEqual(parse_tidbits({}), [])

    def test_satellite_selection_and_uncovered_basin(self):
        self.assertEqual(satellite_for(-75), 'GOES-19')
        self.assertEqual(satellite_for(-159), 'GOES-18')
        self.assertEqual(satellite_for(135), 'Himawari-9')
        with self.assertRaises(DataUnavailable):
            satellite_for(49)

    def test_preprocessing_rejects_rgb_celsius_bad_coverage(self):
        for image in [np.zeros((156,156,3)), np.full((156,156), -40.), np.full((156,156), np.nan)]:
            with self.assertRaises(ValueError):
                predict(image)

    def test_exact_normalization_nan_fill_and_expected_mean(self):
        class Capture(torch.nn.Module):
            def forward(self, image):
                self.input = image
                return torch.zeros((1,59))
        model=Capture()
        image=np.full((156,156), MEAN_K, dtype=np.float32)
        image[0,0]=np.nan
        bins=np.arange(10,305,5,dtype=np.float32)
        with patch('backend.model.load_model', return_value=(model,bins,'test-only')):
            result=predict(image)
        self.assertEqual(tuple(model.input.shape),(1,1,156,156))
        self.assertAlmostEqual(float(model.input[0,0,0,0]),(245-MEAN_K)/STD_K,places=5)
        self.assertAlmostEqual(float(model.input[0,0,1,1]),0,places=5)
        self.assertEqual(len(result['probabilities']),59)
        self.assertAlmostEqual(sum(result['probabilities']),1,places=6)
        self.assertAlmostEqual(result['mean_nmi'],155,places=4)
        self.assertIsNone(result['ground_truth'])

    def test_api_validation_and_missing_storm(self):
        self.assertEqual(self.client.get('/api/health').status_code,200)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.post('/api/imagery',json={'storm_id':'../../'}).status_code,422)
        with patch('backend.app.current_storms',return_value={'storms':[]}):
            self.assertEqual(self.client.post('/api/imagery',json={'storm_id':'31W'}).status_code,404)
        self.assertEqual(self.client.get('/api/patches/invalid/image').status_code,404)

    def test_stale_inference_is_blocked(self):
        meta={'observed_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}
        with patch('backend.app.read_patch',return_value=(np.zeros((156,156)),meta)):
            response=self.client.post('/api/patches/'+'a'*24+'/infer')
        self.assertEqual(response.status_code,409)

    def test_feed_error_is_not_no_storms(self):
        with patch('backend.app.current_storms',side_effect=RuntimeError('offline')):
            response=self.client.get('/api/storms')
        self.assertEqual(response.status_code,503)

    @unittest.skipUnless(MODEL_PATH.is_file(), 'Local trained checkpoint not configured')
    def test_real_checkpoint(self):
        # This is a model shape/weights check, not a meteorological validation case.
        result=predict(np.full((156,156),236.5,dtype=np.float32))
        self.assertEqual(len(result['probabilities']),59)
        self.assertAlmostEqual(sum(result['probabilities']),1,places=6)
        self.assertGreaterEqual(result['mean_nmi'],10)
        self.assertLessEqual(result['mean_nmi'],300)
        self.assertEqual(len(result['model_sha256']),64)


if __name__=='__main__':
    unittest.main()
