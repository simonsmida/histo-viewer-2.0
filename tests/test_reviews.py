import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import reviews


class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'case.json').write_text(json.dumps({'sae_type': 'test-sae'}))
        self.case = SimpleNamespace(id='case-01', label='Sample 1', source_width=100, source_height=200,
                                    viewer_width=50, viewer_height=50, patch_size=10, slide_path=self.root/'slide.png')
        self.concept = SimpleNamespace(id='concept-0001', patches_revision='test-revision')
        self.patches = [SimpleNamespace(patch_index=7, rank=1, source_x=20, source_y=30)]
        for name, value in [('REVIEWS_DIR', self.root/'reviews')]:
            ctx = patch.object(reviews, name, value);ctx.start();self.addCleanup(ctx.stop)
        for name, value in [('get_case', self.case), ('get_concept', self.concept), ('load_patches', self.patches)]:
            ctx = patch.object(reviews, name, return_value=value);ctx.start();self.addCleanup(ctx.stop)

    def test_source_coordinate_snapshot(self):
        data = reviews.ReviewInput(reviewer='Expert', assessment='consistent', supporting_patches=[7],
            annotations=[{'type':'bbox', 'name':'Region', 'rect':{'x':5,'y':6,'w':10,'h':12}}])
        record = reviews.save_review('case-01','concept-0001',data)
        self.assertEqual(record['regions'][0]['rect'], {'x':10,'y':24,'w':20,'h':48})
        self.assertEqual(record['supporting_patches'][0]['patch_index'],7)
        self.assertEqual(record['sae_type'],'test-sae')
        stored = json.loads(next((self.root/'reviews').rglob('*.json')).read_text())
        self.assertEqual(record, stored)

    def test_simultaneous_saves_do_not_overwrite(self):
        data = reviews.ReviewInput(reviewer='Expert', assessment='uncertain')
        with ThreadPoolExecutor(max_workers=4) as pool:
            saved = list(pool.map(lambda _: reviews.save_review('case-01','concept-0001',data), range(4)))
        self.assertEqual(len({r['id'] for r in saved}),4)
        self.assertEqual(len(list((self.root/'reviews').rglob('*.json'))),4)
        self.assertEqual(len(reviews.api_reviews('case-01','concept-0001')),4)

    def test_invalid_evidence_rejected(self):
        for support, contra in [([99],[]),([7],[7])]:
            with self.assertRaises(HTTPException):
                reviews.save_review('case-01','concept-0001',reviews.ReviewInput(
                    reviewer='Expert',assessment='mixed',supporting_patches=support,contradicting_patches=contra))

    def test_invalid_regions_rejected(self):
        for rect in [{'x':-1,'y':0,'w':1,'h':1}, {'x':0,'y':0,'w':float('nan'),'h':1}, {'x':0,'y':0,'w':500,'h':1}]:
            with self.assertRaises(HTTPException):
                reviews.source_regions(self.case,[{'type':'bbox','rect':rect}])

    def test_whitespace_reviewer_rejected(self):
        with self.assertRaises(HTTPException):
            reviews.save_review('case-01','concept-0001',reviews.ReviewInput(reviewer='  ',assessment='uncertain'))
