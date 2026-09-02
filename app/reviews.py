"""Append-only expert review snapshots for the experimental review branch."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .catalog import BASE_DIR, Case, get_case, get_concept, load_patches

router = APIRouter()
REVIEWS_DIR = BASE_DIR / 'review-data' / 'reviews'


class ReviewInput(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    assessment: Literal['consistent', 'mixed', 'artifact', 'uncertain']
    interpretation: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=5000)
    supporting_patches: list[int] = Field(default_factory=list, max_length=100)
    contradicting_patches: list[int] = Field(default_factory=list, max_length=100)
    annotations: list[dict] = Field(default_factory=list, max_length=500)


def source_regions(case: Case, annotations: list[dict]) -> list[dict]:
    sx, sy = case.source_width / case.viewer_width, case.source_height / case.viewer_height
    result = []
    def number(value):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise HTTPException(422, 'Annotation coordinates must be finite numbers')
        return value
    def point(p):
        x, y = number(p['x']), number(p['y'])
        if not (0 <= x <= case.viewer_width and 0 <= y <= case.viewer_height):
            raise HTTPException(422, 'Annotation extends outside the image')
        return {'x': x * sx, 'y': y * sy}
    for annotation in annotations:
        record = {'name': str(annotation.get('name', 'Region'))[:200], 'type': annotation.get('type')}
        try:
            if record['type'] == 'bbox':
                r = annotation['rect']; start = point(r)
                w, h = number(r['w']), number(r['h'])
                if w <= 0 or h <= 0:
                    raise HTTPException(422, 'Annotation must have positive size')
                point({'x': r['x'] + w, 'y': r['y'] + h})
                record['rect'] = dict(start, w=w * sx, h=h * sy)
            elif record['type'] == 'freehand':
                points = annotation['points']
                if not isinstance(points, list) or not 3 <= len(points) <= 10000:
                    raise HTTPException(422, 'Freehand annotation needs 3 to 10000 points')
                record['points'] = [point(p) for p in points]
            else:
                raise HTTPException(422, 'Unsupported annotation shape')
        except (KeyError, TypeError):
            raise HTTPException(422, 'Invalid annotation geometry') from None
        result.append(record)
    return result


def save_review(case_id: str, concept_id: str, review: ReviewInput) -> dict:
    case = get_case(case_id)
    concept = get_concept(case_id, concept_id)
    reviewer = review.reviewer.strip()
    if not reviewer:
        raise HTTPException(422, 'Enter a reviewer name or initials')
    support = set(review.supporting_patches)
    contradict = set(review.contradicting_patches)
    if support & contradict:
        raise HTTPException(422, 'A patch cannot both support and contradict this review')
    patches = {p.patch_index: p for p in load_patches(case_id, concept_id)}
    if not (support | contradict) <= patches.keys():
        raise HTTPException(422, 'Example patch is not in this group')
    def examples(indices):
        return [{'patch_index': i, 'rank_at_review': patches[i].rank,
                 'x': patches[i].source_x, 'y': patches[i].source_y,
                 'width': case.patch_size, 'height': case.patch_size} for i in sorted(indices)]
    metadata = json.loads((case.slide_path.parent / 'case.json').read_text())
    record = {
        'schema_version': 1, 'id': uuid4().hex,
        'created_at': datetime.now(timezone.utc).isoformat(), 'reviewer': reviewer,
        'case_id': case.id, 'case_label': case.label, 'group_id': concept.id,
        'sae_type': metadata.get('sae_type'), 'patch_table_revision': concept.patches_revision,
        'coordinate_space': 'source_image_pixels',
        'image_width': case.source_width, 'image_height': case.source_height,
        'assessment': review.assessment, 'interpretation': review.interpretation.strip(),
        'notes': review.notes.strip(), 'supporting_patches': examples(support),
        'contradicting_patches': examples(contradict),
        'regions': source_regions(case, review.annotations),
    }
    folder = REVIEWS_DIR / case.id / concept.id
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / f".{record['id']}.tmp"
    destination = folder / f"{record['id']}.json"
    try:
        with temp.open('x', encoding='utf-8') as handle:
            json.dump(record, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return record


@router.post('/api/cases/{case_id}/concepts/{concept_id}/reviews')
def api_save_review(case_id: str, concept_id: str, review: ReviewInput) -> dict:
    return save_review(case_id, concept_id, review)


@router.get('/api/cases/{case_id}/concepts/{concept_id}/reviews')
def api_reviews(case_id: str, concept_id: str) -> list[dict]:
    case = get_case(case_id)
    concept = get_concept(case_id, concept_id)
    folder = REVIEWS_DIR / case.id / concept.id
    records = [json.loads(p.read_text()) for p in folder.glob('*.json')]
    return sorted(records, key=lambda r: r['created_at'], reverse=True)
