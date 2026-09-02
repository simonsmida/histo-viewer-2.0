"""Source-resolution patch crops, with an explicit preview fallback."""
from __future__ import annotations

import math
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageDraw

from .catalog import Case, Patch
from .tiles import load_slide


def patch_image_source(case: Case) -> tuple[Path, bool]:
    original = case.source_image_path
    if original and original.is_file():
        with Image.open(original) as image:
            if image.size != (case.source_width, case.source_height):
                raise HTTPException(422, "Original image dimensions do not match the case coordinates")
        return original, True
    return case.slide_path, False


def physical_pixel_size(case: Case) -> tuple[float, float] | None:
    x, y = case.microns_per_pixel_x, case.microns_per_pixel_y
    if x is None or y is None:
        return None
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (x, y)):
        return None
    return float(x), float(y)


def crop_patch(case: Case, patch: Patch, *, context: int = 1) -> tuple[Image.Image, bool]:
    path, original = patch_image_source(case)
    revision = str(path.stat().st_mtime_ns)
    slide = load_slide(str(path), "RGB", revision)
    sx = slide.dimensions[0] / case.source_width
    sy = slide.dimensions[1] / case.source_height
    margin = case.patch_size * (context - 1) / 2
    left = max(0, round((patch.source_x - margin) * sx))
    top = max(0, round((patch.source_y - margin) * sy))
    right = min(slide.dimensions[0], round((patch.source_x + case.patch_size + margin) * sx))
    bottom = min(slide.dimensions[1], round((patch.source_y + case.patch_size + margin) * sy))
    if right <= left or bottom <= top:
        raise HTTPException(404, "Patch is outside the image")
    image = slide.read_region((left, top), (right - left, bottom - top)).convert("RGB")
    if context > 1:
        box = (round(patch.source_x * sx) - left, round(patch.source_y * sy) - top,
               round((patch.source_x + case.patch_size) * sx) - left - 1,
               round((patch.source_y + case.patch_size) * sy) - top - 1)
        ImageDraw.Draw(image).rectangle(box, outline="#2563eb", width=2)
    return image, original
