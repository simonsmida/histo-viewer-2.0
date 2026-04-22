from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from PIL import Image

TILE_SIZE = 254
OVERLAP = 1
BASE_FORMAT = "jpeg"
OVERLAY_FORMAT = "png"


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


@lru_cache(maxsize=4)
def load_slide(path_value: str, mode: str) -> RasterSlide:
    return RasterSlide(Path(path_value), mode)


def deep_zoom_descriptor(width: int, height: int, image_format: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
        f'Format="{image_format}" Overlap="{OVERLAP}" TileSize="{TILE_SIZE}">'
        f'<Size Width="{width}" Height="{height}"/>'
        "</Image>"
    )


def render_tile(path: Path, mode: str, level: int, col: int, row: int, image_format: str) -> bytes:
    slide = load_slide(str(path), mode)
    width, height = slide.dimensions

    max_level = math.ceil(math.log2(max(width, height)))
    if level < 0 or level > max_level:
        raise HTTPException(status_code=404, detail="Tile level out of range")

    scale = 2 ** (max_level - level)
    scaled_width = math.ceil(width / scale)
    scaled_height = math.ceil(height / scale)

    x0 = col * TILE_SIZE
    y0 = row * TILE_SIZE

    overlap_left = OVERLAP if col > 0 else 0
    overlap_top = OVERLAP if row > 0 else 0
    overlap_right = OVERLAP if (col + 1) * TILE_SIZE < scaled_width else 0
    overlap_bottom = OVERLAP if (row + 1) * TILE_SIZE < scaled_height else 0

    tile_x = x0 - overlap_left
    tile_y = y0 - overlap_top
    tile_w = min(TILE_SIZE + overlap_left + overlap_right, scaled_width - tile_x)
    tile_h = min(TILE_SIZE + overlap_top + overlap_bottom, scaled_height - tile_y)
    if tile_w <= 0 or tile_h <= 0:
        raise HTTPException(status_code=404, detail="Tile out of range")

    read_x = int(tile_x * scale)
    read_y = int(tile_y * scale)
    read_w = int(math.ceil(tile_w * scale))
    read_h = int(math.ceil(tile_h * scale))

    tile = slide.read_region((read_x, read_y), (read_w, read_h))
    if tile.size != (tile_w, tile_h):
        tile = tile.resize((tile_w, tile_h), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    if image_format in {"jpeg", "jpg"}:
        tile.convert("RGB").save(buffer, format="JPEG", quality=85)
    else:
        tile.save(buffer, format="PNG")
    return buffer.getvalue()
