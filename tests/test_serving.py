import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import sleep
from unittest.mock import Mock, patch

from PIL import Image

from app import main, tiles
from app.patches import crop_patch


class ServingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tiles._load_slide.cache_clear()
        self.addCleanup(tiles._load_slide.cache_clear)

    def test_concurrent_cold_crops_decode_once(self):
        path = self.root / 'slide.png'
        Image.new('RGB', (96, 96), (20, 40, 60)).save(path)
        start = Barrier(16)
        constructor = tiles.RasterSlide

        def slow_decode(*args):
            sleep(.03)
            return constructor(*args)

        def crop(_):
            start.wait()
            with tiles.load_slide(str(path), 'RGB', '1') as slide:
                return slide.read_region((5, 5), (16, 16)).getpixel((0, 0))

        with patch.object(tiles, 'RasterSlide', side_effect=slow_decode) as decoder:
            with ThreadPoolExecutor(max_workers=16) as pool:
                pixels = list(pool.map(crop, range(16)))
        self.assertEqual(pixels, [(20, 40, 60)] * 16)
        self.assertEqual(decoder.call_count, 1)

    def test_slide_cache_evicts_and_honors_revision(self):
        path = self.root / 'slide.png'
        Image.new('RGB', (32, 32), 'red').save(path)
        with tiles.load_slide(str(path), 'RGB', 'old') as slide:
            self.assertEqual(slide.read_region((0, 0), (1, 1)).getpixel((0, 0)), (255, 0, 0))
        Image.new('RGB', (32, 32), 'blue').save(path)
        with tiles.load_slide(str(path), 'RGB', 'new') as slide:
            self.assertEqual(slide.read_region((0, 0), (1, 1)).getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(tiles._load_slide.cache_info().currsize, 1)

    def test_precomputed_thumbnail_never_opens_original(self):
        path = self.root / 'patch_thumbnails/128/1.png'
        path.parent.mkdir(parents=True)
        Image.new('RGB', (128, 128), 'red').save(path)
        case = Mock(source_image_path=self.root / 'large-original.tif')
        concept = Mock(patches_path=self.root / 'patches.csv')
        with patch.object(main, 'get_case', return_value=case), \
             patch.object(main, 'get_concept', return_value=concept), \
             patch.object(main, 'get_patch', return_value=Mock(rank=1)), \
             patch.object(main, '_render_patch_thumbnail', side_effect=AssertionError('must serve existing thumbnail')), \
             patch.object(main, 'patch_image_source', side_effect=AssertionError('must not open original')):
            response = main.api_patch_thumbnail('case', 'group', 1)
        self.assertEqual(response.path, path)

    def test_thumbnail_fallback_reads_preview_even_with_original_configured(self):
        preview = self.root / 'slide.png'
        Image.new('RGB', (48, 48), 'blue').save(preview)
        case = Mock(slide_path=preview, source_image_path=self.root / 'missing.tif',
                    source_width=96, source_height=96, patch_size=24)
        with patch('app.patches.patch_image_source', side_effect=AssertionError('must not inspect original')):
            image, original = crop_patch(case, Mock(source_x=24, source_y=24), original_resolution=False)
        self.assertFalse(original)
        self.assertEqual(image.size, (12, 12))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))

    def test_page_asset_urls_change_after_asset_update(self):
        (self.root / 'index.html').write_text('<link href="/static/styles.css"><script src="/static/app.js"></script>')
        (self.root / 'styles.css').write_text('body {color:red}')
        (self.root / 'app.js').write_text('console.log(1)')
        with patch.object(main, 'STATIC_DIR', self.root):
            first = main.index()
            (self.root / 'styles.css').write_text('body {color:blue}')
            second = main.index()
        self.assertNotEqual(first.body, second.body)
        self.assertIn(b'/static/styles.css?v=', second.body)
        self.assertIn(b'/static/app.js?v=', second.body)
        self.assertEqual(second.headers['cache-control'], 'no-store')
