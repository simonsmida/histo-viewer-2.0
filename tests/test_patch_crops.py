import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi import HTTPException
from PIL import Image

from app.patches import crop_patch, patch_image_source, physical_pixel_size


class PatchCropTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source.png'
        image = Image.new('RGB', (96, 96), 'white')
        for x in range(24, 48):
            for y in range(24, 48):
                image.putpixel((x, y), (x, y, 123))
        image.save(self.source)
        self.preview = root / 'slide.png'
        image.resize((48, 48)).save(self.preview)
        self.case = Mock(source_image_path=self.source, slide_path=self.preview,
                         source_width=96, source_height=96, patch_size=24,
                         microns_per_pixel_x=.5, microns_per_pixel_y=.75)
        self.patch = Mock(source_x=24, source_y=24)

    def test_original_crop_preserves_source_pixels(self):
        crop, original = crop_patch(self.case, self.patch)
        self.assertTrue(original)
        self.assertEqual(crop.size, (24, 24))
        self.assertEqual(crop.getpixel((0, 0)), (24, 24, 123))
        self.assertEqual(crop.getpixel((23, 23)), (47, 47, 123))

    def test_preview_fallback_is_identified(self):
        self.case.source_image_path = None
        crop, original = crop_patch(self.case, self.patch)
        self.assertFalse(original)
        self.assertEqual(crop.size, (12, 12))

    def test_mismatched_original_is_rejected(self):
        self.case.source_width = 100
        with self.assertRaises(HTTPException):
            patch_image_source(self.case)

    def test_context_clips_to_image_and_preserves_patch_location(self):
        crop, _ = crop_patch(self.case, self.patch, context=5)
        self.assertEqual(crop.size, (96, 96))
        self.assertEqual(crop.getpixel((24, 24)), (37, 99, 235))

    def test_scale_requires_valid_calibration(self):
        self.assertEqual(physical_pixel_size(self.case), (.5, .75))
        self.case.microns_per_pixel_x = float('nan')
        self.assertIsNone(physical_pixel_size(self.case))
        self.case.microns_per_pixel_x = None
        self.assertIsNone(physical_pixel_size(self.case))
