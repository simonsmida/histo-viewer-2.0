import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.precompute_tiles import process_tree


class TilePreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.slide = self.root / 'slide.png'
        self.overlay = self.root / 'concepts/c1/overlay.png'
        for path in (self.slide, self.overlay, self.root / 'concepts/c1/patch_thumbnails/128/1.png'):
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (16, 16), 'red').save(path)

    def generate(self, force=False):
        with contextlib.redirect_stdout(io.StringIO()):
            process_tree(self.root, tile_size=8, overlap=0, jpeg_quality=85, force=force)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_rerun_does_not_tile_tiles_or_thumbnails(self):
        self.generate()
        before = self.snapshot()
        self.generate()
        self.assertEqual(before, self.snapshot())
        self.assertEqual({p.relative_to(self.root).as_posix() for p in self.root.rglob('*.dzi')},
                         {'slide.dzi', 'concepts/c1/overlay.dzi'})

    def test_force_updates_source_tiles_without_nested_pyramids(self):
        self.generate()
        tile = self.root / 'slide_files/4/0_0.jpg'
        before = tile.read_bytes()
        Image.new('RGB', (16, 16), 'blue').save(self.slide)
        self.generate()
        self.assertEqual(before, tile.read_bytes())
        self.generate(force=True)
        self.assertNotEqual(before, tile.read_bytes())
        self.assertEqual(len(list(self.root.rglob('*.dzi'))), 2)

    def test_single_file_respects_force(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/precompute_tiles.py'
        cmd = [sys.executable, str(script), '--input', str(self.slide), '--tile-size', '8']
        subprocess.run(cmd, check=True, capture_output=True)
        tile = self.root / 'slide_files/4/0_0.jpg'
        before = tile.read_bytes()
        Image.new('RGB', (16, 16), 'blue').save(self.slide)
        subprocess.run(cmd, check=True, capture_output=True)
        self.assertEqual(before, tile.read_bytes())
        subprocess.run(cmd + ['--force'], check=True, capture_output=True)
        self.assertNotEqual(before, tile.read_bytes())
