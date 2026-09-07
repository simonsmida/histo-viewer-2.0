"""Blinded, patch-level expert study prototype.

Study manifests keep the sampling strata and activations server-side.  The review
API deliberately exposes only randomized images and the expert's description.
"""
from __future__ import annotations

import io
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .catalog import BASE_DIR, get_case, get_concept, load_patches
from .patches import crop_patch

router = APIRouter()
STUDIES_DIR = BASE_DIR / "review-data" / "studies"
DISCOVERY_COUNT = 12
# Compact demo review: four randomly sampled patches from each of the five
# activation strata, for 20 evaluation patches in total.
PER_STRATUM = 4
STRATA = ("zero", "low", "medium", "high", "top")


class StudyCreate(BaseModel):
    case_id: str
    concept_id: str
    reviewer: str = Field(default="expert", min_length=1, max_length=120)
    assessment: Literal["clear", "partial", "no_pattern", "artifact", "unsure"]
    pattern: str = Field(default="", max_length=1000)
    confidence: Literal["low", "medium", "high"]


class JudgmentInput(BaseModel):
    judgment: Literal["present", "absent", "uncertain", "cannot_assess"]


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _session_path(study_id: str) -> Path:
    if not study_id.isalnum() or len(study_id) > 64:
        raise HTTPException(404, "Unknown study")
    return STUDIES_DIR / f"{study_id}.json"


def _load(study_id: str) -> dict:
    try:
        return json.loads(_session_path(study_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(404, "Unknown study") from exc


def discovery(case_id: str, concept_id: str) -> dict:
    case, concept = get_case(case_id), get_concept(case_id, concept_id)
    patches = list(load_patches(case_id, concept_id))[:DISCOVERY_COUNT]
    return {
        "case_id": case.id,
        "case_label": case.label,
        "concept_id": concept.id,
        "group_label": f"ID {concept.id.rsplit('-', 1)[-1].lstrip('0') or '0'}",
        "eligible": len(load_patches(case_id, concept_id)) >= DISCOVERY_COUNT + 8,
        "patch_count": len(load_patches(case_id, concept_id)),
        "patches": [{
            "rank": p.rank,
            "thumbnail_url": f"/api/cases/{case.id}/concepts/{concept.id}/patches/{p.rank}.png",
        } for p in patches],
    }


def _choose_evenly(values: list, count: int, rng: random.Random) -> list:
    if len(values) <= count:
        return list(values)
    # Random sampling within a frozen stratum; sorting makes the seed portable.
    return rng.sample(sorted(values, key=lambda p: p.patch_index), count)


def _zero_candidates(case_id: str, concept_id: str, positive_indices: set[int]) -> list:
    """Tissue-bearing patches absent from this feature but present for another."""
    case = get_case(case_id)
    candidates = {}
    for other in case.concepts:
        if other.id == concept_id or other.positive_patch_count == 0:
            continue
        for patch in load_patches(case_id, other.id):
            if patch.patch_index not in positive_indices:
                candidates.setdefault(patch.patch_index, patch)
    return list(candidates.values())


def create_study(data: StudyCreate) -> dict:
    reviewer, pattern = data.reviewer.strip(), data.pattern.strip()
    if not reviewer:
        raise HTTPException(422, "Enter your name or initials")
    if data.assessment in {"clear", "partial"} and not pattern:
        raise HTTPException(422, "Describe the pattern before validation")
    case, concept = get_case(data.case_id), get_concept(data.case_id, data.concept_id)
    positives = list(load_patches(case.id, concept.id))
    if len(positives) < DISCOVERY_COUNT + 8:
        raise HTTPException(422, "This group has too few patches for the prototype study")

    study_id = uuid4().hex
    seed = int(study_id[:12], 16)
    rng = random.Random(seed)
    remaining = positives[DISCOVERY_COUNT:]
    n = len(remaining)
    # Four disjoint rank ranges after the discovery examples.
    ranges = {
        "top": remaining[: max(1, n // 10)],
        "high": remaining[max(1, n // 10): max(2, n // 3)],
        "medium": remaining[max(2, n // 3): max(3, 2 * n // 3)],
        "low": remaining[max(3, 2 * n // 3):],
    }
    selected = []
    for name in ("top", "high", "medium", "low"):
        selected.extend((p, name, p.score) for p in _choose_evenly(ranges[name], PER_STRATUM, rng))
    zeros = _choose_evenly(_zero_candidates(case.id, concept.id, {p.patch_index for p in positives}), PER_STRATUM, rng)
    selected.extend((p, "zero", 0.0) for p in zeros)
    if not zeros:
        raise HTTPException(422, "No defensible zero-activation controls are available")
    rng.shuffle(selected)
    def context_box(p):
        left = max(0, p.source_x - 2 * case.patch_size)
        top = max(0, p.source_y - 2 * case.patch_size)
        right = min(case.source_width, p.source_x + 3 * case.patch_size)
        bottom = min(case.source_height, p.source_y + 3 * case.patch_size)
        return {"left": (p.source_x - left) / max(1, right - left),
                "top": (p.source_y - top) / max(1, bottom - top),
                "width": case.patch_size / max(1, right - left),
                "height": case.patch_size / max(1, bottom - top)}

    evaluation = [{
        "position": i + 1,
        "patch_index": p.patch_index,
        "source_x": p.source_x,
        "source_y": p.source_y,
        "score": score,
        "stratum": stratum,
        "context_box": context_box(p),
        "judgment": None,
    } for i, (p, stratum, score) in enumerate(selected)]
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": 1, "id": study_id, "created_at": now, "updated_at": now,
        "case_id": case.id, "case_label": case.label, "concept_id": concept.id,
        "patch_table_revision": concept.patches_revision, "seed": seed,
        "reviewer": reviewer, "assessment": data.assessment, "pattern": pattern,
        "confidence": data.confidence,
        "sampling": {
            "discovery": f"top {DISCOVERY_COUNT} activating patches",
            "evaluation": "random within frozen activation strata; discovery excluded",
            "zero": "tissue patch absent from this feature and active for another exported feature",
        },
        "evaluation": evaluation,
    }
    _atomic_json(_session_path(study_id), record)
    return public_study(record)


def public_study(record: dict) -> dict:
    items = record["evaluation"]
    return {
        "id": record["id"], "case_id": record["case_id"], "concept_id": record["concept_id"],
        "case_label": record["case_label"],
        "pattern": record["pattern"] or "No single pattern proposed",
        "assessment": record["assessment"], "confidence": record["confidence"],
        "total": len(items), "completed": sum(x["judgment"] is not None for x in items),
        "evaluation": [{
            "position": x["position"], "judgment": x["judgment"],
            "image_url": f"/api/studies/{record['id']}/patches/{x['position']}.png",
            "context_url": f"/api/studies/{record['id']}/patches/{x['position']}/context.png",
            "context_plain_url": f"/api/studies/{record['id']}/patches/{x['position']}/context-plain.png",
            "context_box": x.get("context_box", {"left": .4, "top": .4, "width": .2, "height": .2}),
        } for x in items],
    }


def average_precision(pairs: list[tuple[float, int]]) -> tuple[float | None, list[dict]]:
    if not pairs or not any(label for _, label in pairs):
        return None, []
    ordered = sorted(pairs, key=lambda x: x[0], reverse=True)
    positives = sum(label for _, label in ordered)
    tp = 0
    curve = [{"recall": 0.0, "precision": 1.0}]
    ap = 0.0
    for rank, (_, label) in enumerate(ordered, 1):
        tp += label
        precision, recall = tp / rank, tp / positives
        curve.append({"recall": recall, "precision": precision})
        if label:
            ap += precision / positives
    return ap, curve


def study_results(record: dict) -> dict:
    assessable = [x for x in record["evaluation"] if x["judgment"] in {"present", "absent"}]
    pairs = [(x["score"], int(x["judgment"] == "present")) for x in assessable]
    ap, curve = average_precision(pairs)
    top = sorted(assessable, key=lambda x: x["score"], reverse=True)[:20]
    top_high = [x for x in assessable if x["stratum"] in {"top", "high"}]
    ordered_pairs = sorted(pairs, key=lambda x: x[0], reverse=True)
    true_positive_count = 0
    auprc_precision_values = []
    for rank, (_, label) in enumerate(ordered_pairs, 1):
        true_positive_count += label
        if label:
            auprc_precision_values.append(true_positive_count / rank)
    counts = {name: {"present": 0, "absent": 0, "uncertain": 0, "cannot_assess": 0} for name in STRATA}
    all_counts = {key: 0 for key in ("present", "absent", "uncertain", "cannot_assess", "unreviewed")}
    for item in record["evaluation"]:
        judgment = item["judgment"] or "unreviewed"
        all_counts[judgment] += 1
        if item["judgment"]:
            counts[item["stratum"]][item["judgment"]] += 1
    activation = []
    for name in STRATA:
        c = counts[name]; n = c["present"] + c["absent"]
        activation.append({"stratum": name, "matching_fraction": c["present"] / n if n else None,
                           "assessable_n": n, "all_n": sum(c.values())})
    return {
        **public_study(record), "reviewer": record["reviewer"], "created_at": record["created_at"],
        "precision_at_20": sum(x["judgment"] == "present" for x in top) / len(top) if top else None,
        "precision_n": len(top),
        "precision_top_high": sum(x["judgment"] == "present" for x in top_high) / len(top_high) if top_high else None,
        "precision_top_high_n": len(top_high),
        "precision_top_high_present_n": sum(x["judgment"] == "present" for x in top_high),
        "auprc_precision_values": auprc_precision_values,
        "activation_order": [x["position"] for x in sorted(record["evaluation"], key=lambda x: x["score"], reverse=True)] if all(x["judgment"] for x in record["evaluation"]) else None,
        "auprc": ap, "prevalence": sum(y for _, y in pairs) / len(pairs) if pairs else None,
        "pr_curve": curve, "activation_curve": activation, "judgment_counts": all_counts,
        "sampling": record["sampling"],
    }


@router.get("/api/study/discovery/{case_id}/{concept_id}")
def api_discovery(case_id: str, concept_id: str) -> dict:
    return discovery(case_id, concept_id)


@router.post("/api/studies")
def api_create(data: StudyCreate) -> dict:
    return create_study(data)


@router.get("/api/studies/{study_id}")
def api_study(study_id: str) -> dict:
    return public_study(_load(study_id))


@router.put("/api/studies/{study_id}/judgments/{position}")
def api_judgment(study_id: str, position: int, data: JudgmentInput) -> dict:
    record = _load(study_id)
    if not 1 <= position <= len(record["evaluation"]):
        raise HTTPException(404, "Unknown evaluation patch")
    record["evaluation"][position - 1]["judgment"] = data.judgment
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(_session_path(study_id), record)
    return public_study(record)


@router.get("/api/studies/{study_id}/results")
def api_results(study_id: str) -> dict:
    return study_results(_load(study_id))


@router.get("/api/studies/{study_id}/patches/{position}.png")
def api_study_patch(study_id: str, position: int) -> Response:
    return _study_patch_response(study_id, position, context=1)


@router.get("/api/studies/{study_id}/patches/{position}/context.png")
def api_study_patch_context(study_id: str, position: int) -> Response:
    # Five patch widths provide useful architecture while keeping the marked
    # patch visibly proportional to the standalone 96-pixel patch.
    return _study_patch_response(study_id, position, context=5)


@router.get("/api/studies/{study_id}/patches/{position}/context-plain.png")
def api_study_patch_context_plain(study_id: str, position: int) -> Response:
    return _study_patch_response(study_id, position, context=5, outline=False)


def _study_patch_response(study_id: str, position: int, *, context: int, outline: bool = True) -> Response:
    record = _load(study_id)
    if not 1 <= position <= len(record["evaluation"]):
        raise HTTPException(404, "Unknown evaluation patch")
    item = record["evaluation"][position - 1]
    case = get_case(record["case_id"])
    patch = SimpleNamespace(source_x=item["source_x"], source_y=item["source_y"])
    image, _ = crop_patch(case, patch, context=context, original_resolution=True, outline=outline)
    buffer = io.BytesIO(); image.save(buffer, format="PNG", optimize=True)
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
