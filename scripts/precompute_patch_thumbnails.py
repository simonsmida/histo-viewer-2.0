#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from app.catalog import Concept, Case, Patch, load_cases, load_patches
from app.tiles import load_slide

Image.MAX_IMAGE_PIXELS = None


def thumbnail_path(concept: Concept, rank: int, size: int) -> Path:
    return concept.patches_path.parent / "patch_thumbnails" / str(size) / f"{rank}.png"


def render_thumbnail(case: Case, concept: Concept, patch: Patch, size: int, force: bool) -> bool:
    output_path = thumbnail_path(concept, patch.rank, size)
    if output_path.exists() and not force:
        return False

    scale_x = case.viewer_width / case.source_width
    scale_y = case.viewer_height / case.source_height
    crop_left = int(round(patch.source_x * scale_x))
    crop_top = int(round(patch.source_y * scale_y))
    crop_width = max(1, int(round(case.patch_size * scale_x)))
    crop_height = max(1, int(round(case.patch_size * scale_y)))

    slide = load_slide(str(case.slide_path), "RGB", case.slide_revision)
    crop_box = (
        max(0, crop_left),
        max(0, crop_top),
        min(slide.dimensions[0], crop_left + crop_width),
        min(slide.dimensions[1], crop_top + crop_height),
    )
    if crop_box[0] >= crop_box[2] or crop_box[1] >= crop_box[3]:
        return False

    crop = slide.read_region(
        (crop_box[0], crop_box[1]),
        (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]),
    ).convert("RGB")
    crop = crop.resize((size, size), Image.Resampling.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path, format="PNG", optimize=True)
    return True


def selected_cases(case_ids: list[str] | None) -> list[Case]:
    cases = load_cases()
    if not case_ids:
        return list(cases.values())
    missing = [case_id for case_id in case_ids if case_id not in cases]
    if missing:
        raise SystemExit(f"Unknown case id(s): {', '.join(missing)}")
    return [cases[case_id] for case_id in case_ids]


def selected_concepts(case: Case, concept_ids: list[str] | None) -> list[Concept]:
    if not concept_ids:
        return list(case.concepts)
    missing = [concept_id for concept_id in concept_ids if concept_id not in case.concepts_by_id]
    if missing:
        raise SystemExit(f"Unknown concept id(s) for {case.id}: {', '.join(missing)}")
    return [case.concepts_by_id[concept_id] for concept_id in concept_ids]


def main() -> None:
    parser = argparse.ArgumentParser(description="Precompute patch thumbnails used by the viewer.")
    parser.add_argument("--case", dest="case_ids", action="append", help="Case id to process. Repeat for more cases.")
    parser.add_argument(
        "--concept",
        dest="concept_ids",
        action="append",
        help="Concept id to process. Repeat for more concepts.",
    )
    parser.add_argument("--size", type=int, action="append", help="Thumbnail size in pixels.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing thumbnails.")
    parser.add_argument("--limit", type=int, help="Only render the first N patches per concept.")
    args = parser.parse_args()

    sizes = sorted({max(48, min(size, 256)) for size in (args.size or [128])})
    written = 0
    skipped = 0

    for case in selected_cases(args.case_ids):
        for concept in selected_concepts(case, args.concept_ids):
            patches = load_patches(case.id, concept.id)
            if args.limit:
                patches = patches[:args.limit]
            print(f"[thumbs] {case.id}/{concept.id}: {len(patches)} patches")
            for patch in patches:
                for size in sizes:
                    if render_thumbnail(case, concept, patch, size, args.force):
                        written += 1
                    else:
                        skipped += 1

    print(f"wrote {written} thumbnails, skipped {skipped}")


if __name__ == "__main__":
    main()
