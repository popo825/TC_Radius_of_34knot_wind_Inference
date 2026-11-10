from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
from backend import batch
from backend.fetch_model import fetch_model
from backend.imagery import DataUnavailable
from backend.rendering import render_ir_png

NOW = datetime.now(timezone.utc)
DIGEST = 'a' * 64


def storm(sid='31W'):
    return {'id': sid, 'name': 'Test storm', 'lat': 24., 'lon': 135., 'basin': '西北太平洋',
            'observed_at': (NOW-timedelta(hours=2)).isoformat(), 'in_training_basin': False,
            'wind_kt': 50, 'pressure_hpa': 990, 'stale': False}


def metadata(s=None):
    s=s or storm()
    return {'id': 'sample', 'satellite': 'Himawari-9', 'channel': 'AHI B14', 'wavelength_um': 11.2,
        'observed_at': (NOW-timedelta(minutes=20)).isoformat(), 'position_at': s['observed_at'],
        'center_lat': s['lat'], 'center_lon': s['lon'], 'resampling': 'nearest',
        'position_image_offset_hours': 1.67, 'source_urls': ['https://example.com/raw'], 'storm': s}


def result():
    return {'bins_nmi': list(range(10,305,5)), 'probabilities': [1/59]*59, 'mean_nmi':155.,
        'model_sha256':DIGEST, 'metadata':metadata(), 'inferred_at':NOW.isoformat(), 'ground_truth':None}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'site'
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('backend.batch.load_model',return_value=(None,None,DIGEST)))
        self.stack.enter_context(patch('backend.batch.now_utc',return_value=NOW))
        self.stack.enter_context(patch('backend.batch.predict',return_value=result()))
        self.stack.enter_context(patch('backend.batch.get_patch',side_effect=lambda s:(np.full((156,156),236.5),metadata(s))))

    def feed(self, storms):
        return {'storms':storms,'warnings':[],'fetched_at':NOW.isoformat(),'scope':'global'}

    def test_partial_failure_keeps_other_storm_and_static_assets(self):
        with patch('backend.batch.fetch_storms',return_value=self.feed([storm(),storm('03S')])), patch('backend.batch.get_patch',side_effect=[(np.full((156,156),236.5),metadata()),DataUnavailable('No native coverage')]):
            data=batch.build_site(self.output)
        self.assertEqual(data['summary'],{'ready':1,'cached':0,'unavailable':1})
        self.assertEqual(data['records']['03S']['message'],'No native coverage')
        self.assertTrue((self.output/'index.html').is_file())
        self.assertTrue((self.output/'data/products/31W.png').read_bytes().startswith(b'\x89PNG'))
        rows=(self.output/'data/products/31W.csv').read_text().splitlines()
        self.assertEqual(len(rows),60)
        self.assertEqual(json.loads((self.output/'data/latest.json').read_text(encoding='utf-8'))['records']['31W']['result']['mean_nmi'],155)
        self.assertFalse(any(p.suffix in ('.pth','.npy','.nc','.bz2') for p in self.output.rglob('*')))

    def test_feed_outage_does_not_overwrite_last_build(self):
        self.output.mkdir();sentinel=self.output/'index.html';sentinel.write_text('last good build')
        with patch('backend.batch.fetch_storms',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):batch.build_site(self.output)
        self.assertEqual(sentinel.read_text(),'last good build')

    def test_empty_feed_is_a_successful_empty_snapshot(self):
        with patch('backend.batch.fetch_storms',return_value=self.feed([])):
            data=batch.build_site(self.output)
        self.assertEqual(data['storms'],[])
        self.assertEqual(data['records'],{})
        self.assertEqual(data['summary']['ready'],0)

    def test_cached_result_preserves_original_time_and_marks_it(self):
        old=result();old['metadata']['observed_at']=(NOW-timedelta(hours=3)).isoformat()
        prior={'schema_version':1,'records':{'31W':{'status':'ready','image_url':'data/products/31W.png','result':old}}}
        response=Mock();response.content=render_ir_png(np.full((156,156),236.5))
        with patch('backend.batch.fetch_storms',return_value=self.feed([storm()])), patch('backend.batch.get_patch',side_effect=RuntimeError('offline')), patch('backend.batch.previous_snapshot',return_value=prior), patch('backend.batch.requests.get',return_value=response):
            data=batch.build_site(self.output,'https://example.com/project/')
        row=data['records']['31W']
        self.assertEqual(row['status'],'cached')
        self.assertEqual(row['result']['metadata']['observed_at'],old['metadata']['observed_at'])
        self.assertIn('上次成功',row['message'])
        self.assertEqual(data['summary']['ready'],0)

    def test_old_or_different_model_results_are_not_reused(self):
        for changes in ['old','different-model','external-image']:
            old=result()
            row={'image_url':'data/products/31W.png','result':old}
            if changes=='old':old['metadata']['observed_at']=(NOW-timedelta(hours=7)).isoformat()
            if changes=='different-model':old['model_sha256']='b'*64
            if changes=='external-image':row['image_url']='https://other.example/image.png'
            with patch('backend.batch.requests.get') as get:
                cached=batch.reuse_previous('31W',{'records':{'31W':row}},'https://example.com/',DIGEST,NOW)
            self.assertIsNone(cached);get.assert_not_called()

    def test_invalid_distribution_and_source_output_are_rejected(self):
        invalid=result();invalid['probabilities'][0]=-1
        self.assertFalse(batch.result_valid(invalid))
        invalid=result();invalid['mean_nmi']=float('nan')
        self.assertFalse(batch.result_valid(invalid))
        with self.assertRaises(ValueError):batch.build_site(batch.ROOT/'frontend')

    def test_inactive_products_are_removed_from_next_build(self):
        with patch('backend.batch.fetch_storms',return_value=self.feed([storm()])):
            batch.build_site(self.output)
        with patch('backend.batch.fetch_storms',return_value=self.feed([])):
            batch.build_site(self.output)
        self.assertFalse((self.output/'data/products/31W.png').exists())


class CheckpointDownloadTests(unittest.TestCase):
    def test_download_hash_verification_and_cache_hit(self):
        payload=b'checkpoint-bytes'
        digest=hashlib.sha256(payload).hexdigest()
        response=Mock(url='https://example.com/model.pth')
        response.iter_content.return_value=iter([payload])
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/'model.pth'
            with patch('backend.fetch_model.requests.get',return_value=response):
                fetch_model('https://example.com/model.pth',digest,destination)
            self.assertEqual(destination.read_bytes(),payload)
            with patch('backend.fetch_model.requests.get') as get:
                fetch_model('https://example.com/model.pth',digest,destination)
                get.assert_not_called()

    def test_wrong_download_does_not_replace_existing_checkpoint(self):
        response=Mock(url='https://example.com/model.pth')
        response.iter_content.return_value=iter([b'wrong file'])
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/'model.pth';destination.write_bytes(b'existing')
            with patch('backend.fetch_model.requests.get',return_value=response):
                with self.assertRaises(ValueError):fetch_model('https://example.com/model.pth','a'*64,destination)
            self.assertEqual(destination.read_bytes(),b'existing')
            self.assertFalse(destination.with_suffix('.pth.part').exists())

    def test_insecure_model_url_is_rejected(self):
        with self.assertRaises(ValueError):fetch_model('http://example.com/model.pth','a'*64,Path('unused'))
