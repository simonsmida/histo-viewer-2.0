#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def dzi_descriptor(width: int, height: int, tile_size: int, overlap: int, fmt: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
        f'TileSize="{tile_size}" Overlap="{overlap}" Format="{fmt}">\n'
        f'  <Size Width="{width}" Height="{height}"/>\n'
        '</Image>\n'
    )


def level_count(width: int, height: int) -> int:
    return int(math.ceil(math.log2(max(width, height)))) + 1


def level_dimensions(width: int, height: int, level: int, max_level: int) -> tuple[int, int]:
    scale = 2 ** (max_level - level)
    return (
        max(1, int(math.ceil(width / scale))),
        max(1, int(math.ceil(height / scale))),
    )


def save_tile(
    image: Image.Image,
    output_path: Path,
    fmt: str,
    jpeg_quality: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt in {"jpg", "jpeg"}:
        image = image.convert("RGB")
        image.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)
    elif fmt == "png":
        image.save(output_path, format="PNG", optimize=True)
    else:
        raise ValueError(f"Unsupported tile format: {fmt}")


def precompute_dzi(
    input_path: Path,
    output_dzi_path: Path,
    output_files_dir: Path,
    *,
    tile_size: int,
    overlap: int,
    fmt: str,
    jpeg_quality: int,
) -> None:
    print(f"[tiles] {input_path}")

    with Image.open(input_path) as original:
        original.load()

        width, height = original.size
        max_level = level_count(width, height) - 1

        output_dzi_path.parent.mkdir(parents=True, exist_ok=True)
        output_dzi_path.write_text(
            dzi_descriptor(width, height, tile_size, overlap, fmt),
            encoding="utf-8",
        )

        for level in range(max_level + 1):
            level_w, level_h = level_dimensions(width, height, level, max_level)

            if (level_w, level_h) == (width, height):
                level_image = original.copy()
            else:
                level_image = original.resize((level_w, level_h), Image.Resampling.LANCZOS)

            cols = int(math.ceil(level_w / tile_size))
            rows = int(math.ceil(level_h / tile_size))

            for row in range(rows):
                for col in range(cols):
                    left = col * tile_size
                    top = row * tile_size
                    right = min(left + tile_size, level_w)
                    bottom = min(top + tile_size, level_h)

                    tile = level_image.crop((left, top, right, bottom))
                    tile_path = output_files_dir / str(level) / f"{col}_{row}.{fmt}"
                    save_tile(tile, tile_path, fmt, jpeg_quality)

            print(f"  level {level:02d}: {level_w}x{level_h}, {cols * rows} tiles")

    print(f"  wrote {output_dzi_path}")
    print(f"  wrote {output_files_dir}")


def looks_like_base_image(path: Path) -> bool:
    name = path.name.lower()
    if not path.is_file():
        return False
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return False
    if "overlay" in name or "heatmap" in name:
        return False
    return True


def looks_like_overlay(path: Path) -> bool:
    name = path.name.lower()
    if not path.is_file():
        return False
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return False
    return "overlay" in name or "heatmap" in name


def process_tree(
    input_root: Path,
    *,
    tile_size: int,
    overlap: int,
    jpeg_quality: int,
) -> None:
    image_paths = sorted(
        p for p in input_root.rglob("*")
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    )

    if not image_paths:
        raise SystemExit(f"No images found under {input_root}")

    for image_path in image_paths:
        if looks_like_overlay(image_path):
            fmt = "png"
        else:
            fmt = "jpg"

        dzi_path = image_path.with_suffix(".dzi")
        files_dir = image_path.with_suffix("").parent / f"{image_path.stem}_files"

        if dzi_path.exists() and files_dir.exists():
            print(f"[skip] {image_path} already has tiles")
            continue

        precompute_dzi(
            image_path,
            dzi_path,
            files_dir,
            tile_size=tile_size,
            overlap=overlap,
            fmt=fmt,
            jpeg_quality=jpeg_quality,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Image file or directory containing case images/overlays.",
    )
    parser.add_argument("--tile-size", type=int, default=256)
    parser.add_argument("--overlap", type=int, default=0)
    parser.add_argument("--jpeg-quality", type=int, default=85)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if .dzi and *_files already exist.",
    )
    args = parser.parse_args()

    input_path = args.input

    if not input_path.exists():
        raise SystemExit(f"Input does not exist: {input_path}")

    if input_path.is_file():
        stem = input_path.with_suffix("")
        fmt = "png" if looks_like_overlay(input_path) else "jpg"

        precompute_dzi(
            input_path,
            input_path.with_suffix(".dzi"),
            stem.parent / f"{stem.name}_files",
            tile_size=args.tile_size,
            overlap=args.overlap,
            fmt=fmt,
            jpeg_quality=args.jpeg_quality,
        )
    else:
        process_tree(
            input_path,
            tile_size=args.tile_size,
            overlap=args.overlap,
            jpeg_quality=args.jpeg_quality,
        )


if __name__ == "__main__":
    main()