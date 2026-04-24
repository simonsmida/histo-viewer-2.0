from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

BASE_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = BASE_DIR / "data" / "cases"
ANNOTATIONS_DIR = BASE_DIR / "data" / "annotations"


@dataclass(frozen=True, slots=True)
class Concept:
    id: str
    label: str
    positive_patch_count: int
    max_score: float
    overlay_path: Path
    patches_path: Path
    overlay_revision: str
    patches_revision: str


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    label: str
    slide_path: Path
    viewer_width: int
    viewer_height: int
    source_width: int
    source_height: int
    patch_size: int
    default_concept_id: str
    slide_revision: str
    concepts: tuple[Concept, ...]


@dataclass(frozen=True, slots=True)
class Patch:
    rank: int
    patch_index: int
    source_x: int
    source_y: int
    viewer_x: float
    viewer_y: float
    viewer_w: float
    viewer_h: float
    score: float
    relative_score: float
    tissue_fraction: float


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing required file: {path}") from exc


def _path_revision(path: Path) -> str:
    return str(path.stat().st_mtime_ns)


def _dzi_revision(image_path: Path) -> str:
    dzi_path = image_path.with_suffix(".dzi")
    if dzi_path.exists():
        return _path_revision(dzi_path)
    return _path_revision(image_path)


def _load_case(case_dir: Path) -> Case:
    payload = _read_json(case_dir / "case.json")
    slide_path = case_dir / payload["slide_path"]
    concepts = tuple(
        Concept(
            id=entry["id"],
            label=entry["label"],
            positive_patch_count=int(entry["positive_patch_count"]),
            max_score=float(entry["max_score"]),
            overlay_path=(case_dir / entry["overlay_path"]),
            patches_path=(case_dir / entry["patches_path"]),
            overlay_revision=_dzi_revision(case_dir / entry["overlay_path"]),
            patches_revision=_path_revision(case_dir / entry["patches_path"]),
        )
        for entry in payload["concepts"]
    )
    return Case(
        id=payload["id"],
        label=payload["label"],
        slide_path=slide_path,
        viewer_width=int(payload["viewer_width"]),
        viewer_height=int(payload["viewer_height"]),
        source_width=int(payload["source_width"]),
        source_height=int(payload["source_height"]),
        patch_size=int(payload["patch_size"]),
        default_concept_id=payload["default_concept_id"],
        slide_revision=_dzi_revision(slide_path),
        concepts=concepts,
    )


def load_cases() -> dict[str, Case]:
    cases: dict[str, Case] = {}
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        case = _load_case(case_dir)
        cases[case.id] = case
    return cases


def list_cases() -> list[dict]:
    return [
        {
            "id": case.id,
            "label": case.label,
            "source_width": case.source_width,
            "source_height": case.source_height,
            "viewer_width": case.viewer_width,
            "viewer_height": case.viewer_height,
            "patch_size": case.patch_size,
            "concept_count": len(case.concepts),
            "default_concept_id": case.default_concept_id,
            "base_dzi_url": f"/api/cases/{case.id}/{case.slide_revision}.dzi",
        }
        for case in load_cases().values()
    ]


def get_case(case_id: str) -> Case:
    try:
        return load_cases()[case_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown histology image: {case_id}") from exc


def get_concept(case_id: str, concept_id: str) -> Concept:
    case = get_case(case_id)
    for concept in case.concepts:
        if concept.id == concept_id:
            return concept
    raise HTTPException(status_code=404, detail=f"Unknown concept: {concept_id}")


def list_concepts(case_id: str) -> list[dict]:
    case = get_case(case_id)
    return [
        {
            "id": concept.id,
            "label": concept.label,
            "positive_patch_count": concept.positive_patch_count,
        }
        for concept in case.concepts
    ]


def load_patches(case_id: str, concept_id: str) -> tuple[Patch, ...]:
    case = get_case(case_id)
    concept = get_concept(case_id, concept_id)
    scale_x = case.viewer_width / case.source_width
    scale_y = case.viewer_height / case.source_height

    patches: list[Patch] = []
    with concept.patches_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_x = int(float(row["x"]))
            source_y = int(float(row["y"]))
            patches.append(
                Patch(
                    rank=int(float(row["rank"])),
                    patch_index=int(float(row["patch_index"])),
                    source_x=source_x,
                    source_y=source_y,
                    viewer_x=source_x * scale_x,
                    viewer_y=source_y * scale_y,
                    viewer_w=case.patch_size * scale_x,
                    viewer_h=case.patch_size * scale_y,
                    score=float(row["activation"]),
                    relative_score=float(row["normalized_activation"]),
                    tissue_fraction=float(row["tissue_fraction"]),
                )
            )
    return tuple(patches)


def get_patch(case_id: str, concept_id: str, rank: int) -> Patch:
    for patch in load_patches(case_id, concept_id):
        if patch.rank == rank:
            return patch
    raise HTTPException(status_code=404, detail=f"Unknown patch rank: {rank}")


def concept_detail(case_id: str, concept_id: str) -> dict:
    case = get_case(case_id)
    concept = get_concept(case_id, concept_id)
    patches = load_patches(case_id, concept_id)
    return {
        "id": concept.id,
        "label": concept.label,
        "positive_patch_count": concept.positive_patch_count,
        "max_score": concept.max_score,
        "overlay_dzi_url": f"/api/cases/{case.id}/concepts/{concept.id}/{concept.overlay_revision}.dzi",
        "patches": [
            {
                "rank": patch.rank,
                "patch_index": patch.patch_index,
                "source_x": patch.source_x,
                "source_y": patch.source_y,
                "viewer_x": patch.viewer_x,
                "viewer_y": patch.viewer_y,
                "viewer_w": patch.viewer_w,
                "viewer_h": patch.viewer_h,
                "score": patch.score,
                "relative_score": patch.relative_score,
                "tissue_fraction": patch.tissue_fraction,
                "thumbnail_url": (
                    f"/api/cases/{case.id}/concepts/{concept.id}/patches/{patch.rank}.png?rev={concept.patches_revision}"
                ),
            }
            for patch in patches
        ],
    }


def annotation_path(case_id: str) -> Path:
    return ANNOTATIONS_DIR / f"{case_id}.annotations.json"
