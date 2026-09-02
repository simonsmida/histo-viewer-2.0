from __future__ import annotations

from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from PIL import Image


class RasterSlide:
    def __init__(self, path: Path, mode: str):
        self.path = path
        self.mode = mode
        with Image.open(path) as source:
            self._image = source.convert(mode)
        self.dimensions = self._image.size
        self._lock = Lock()

    def read_region(self, location: tuple[int, int], size: tuple[int, int]) -> Image.Image:
        x0, y0 = int(location[0]), int(location[1])
        read_w, read_h = int(size[0]), int(size[1])
        width, height = self.dimensions
        canvas = Image.new(self.mode, (read_w, read_h), (0, 0, 0, 0) if self.mode == "RGBA" else (255, 255, 255))
        left = max(0, x0)
        top = max(0, y0)
        right = min(width, x0 + read_w)
        bottom = min(height, y0 + read_h)
        if left >= right or top >= bottom:
            return canvas
        with self._lock:
            crop = self._image.crop((left, top, right, bottom))
        canvas.paste(crop, (left - x0, top - y0))
        return canvas


_slide_lock = Lock()


@lru_cache(maxsize=1)
def _load_slide(path_value: str, mode: str, revision: str) -> RasterSlide:
    return RasterSlide(Path(path_value), mode)


@contextmanager
def load_slide(path_value: str, mode: str, revision: str):
    # lru_cache alone permits duplicate concurrent cold loads. Hold the lock
    # through the crop so requests cannot retain many evicted full-size images.
    with _slide_lock:
        yield _load_slide(path_value, mode, revision)
