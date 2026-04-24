from __future__ import annotations

import gzip
import io
import json
from functools import lru_cache
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .catalog import (
    ANNOTATIONS_DIR,
    annotation_path,
    concept_detail,
    get_case,
    get_concept,
    get_patch,
    list_cases,
    list_concepts,
)
from .tiles import load_slide


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Histo Viewer 2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


VERSIONED_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _dzi_path(image_path: Path) -> Path:
    return image_path.with_suffix(".dzi")


def _dzi_files_dir(image_path: Path) -> Path:
    return image_path.with_suffix("").parent / f"{image_path.stem}_files"


def _tile_path(image_path: Path, level: int, col: int, row: int, fmt: str) -> Path:
    return _dzi_files_dir(image_path) / str(level) / f"{col}_{row}.{fmt}"


def _file_response(path: Path, media_type: str, headers: dict[str, str]) -> FileResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Missing precomputed file: {path}")
    return FileResponse(path, media_type=media_type, headers=headers)


def _dzi_response(image_path: Path, headers: dict[str, str]) -> FileResponse:
    return _file_response(_dzi_path(image_path), "application/xml", headers)


def _tile_response(image_path: Path, level: int, col: int, row: int, fmt: str, headers: dict[str, str]) -> FileResponse:
    media_type = "image/jpeg" if fmt in {"jpeg", "jpg"} else "image/png"
    return _file_response(_tile_path(image_path, level, col, row, fmt), media_type, headers)


def _json_response(payload: object, request: Request) -> Response:
    content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Vary": "Accept-Encoding"}
    if len(content) >= 1024 and "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        content = gzip.compress(content)
    return Response(content=content, media_type="application/json", headers=headers)


def _patch_thumbnail_path(patches_path: Path, rank: int, size: int) -> Path:
    return patches_path.parent / "patch_thumbnails" / str(size) / f"{rank}.png"


@lru_cache(maxsize=4096)
def _render_patch_thumbnail(
    case_id: str,
    concept_id: str,
    rank: int,
    output_size: int,
    slide_revision: str,
    patches_revision: str,
) -> bytes:
    case = get_case(case_id)
    patch = get_patch(case_id, concept_id, rank)

    scale_x = case.viewer_width / case.source_width
    scale_y = case.viewer_height / case.source_height
    crop_left = int(round(patch.source_x * scale_x))
    crop_top = int(round(patch.source_y * scale_y))
    crop_width = max(1, int(round(case.patch_size * scale_x)))
    crop_height = max(1, int(round(case.patch_size * scale_y)))

    slide = load_slide(str(case.slide_path), "RGB", slide_revision)
    crop_box = (
        max(0, crop_left),
        max(0, crop_top),
        min(slide.dimensions[0], crop_left + crop_width),
        min(slide.dimensions[1], crop_top + crop_height),
    )
    if crop_box[0] >= crop_box[2] or crop_box[1] >= crop_box[3]:
        raise HTTPException(status_code=404, detail="Patch crop is outside the slide bounds")

    crop = slide.read_region(
        (crop_box[0], crop_box[1]),
        (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]),
    ).convert("RGB")
    crop = crop.resize((output_size, output_size), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    crop.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/cases")
def api_cases() -> list[dict]:
    return list_cases()


@app.get("/api/cases/{case_id}/info")
def api_case_info(case_id: str) -> dict:
    case = get_case(case_id)
    return {
        "id": case.id,
        "label": case.label,
        "viewer_width": case.viewer_width,
        "viewer_height": case.viewer_height,
        "source_width": case.source_width,
        "source_height": case.source_height,
        "patch_size": case.patch_size,
        "default_concept_id": case.default_concept_id,
        "concept_count": len(case.concepts),
        "base_dzi_url": f"/api/cases/{case.id}/{case.slide_revision}.dzi",
    }


@app.get("/api/cases/{case_id}/concepts")
def api_concepts(case_id: str) -> list[dict]:
    return list_concepts(case_id)


@app.get("/api/cases/{case_id}.dzi")
def api_case_dzi(case_id: str) -> FileResponse:
    case = get_case(case_id)
    return _dzi_response(case.slide_path, NO_STORE_HEADERS)


@app.get("/api/cases/{case_id}/{revision}.dzi")
def api_case_dzi_versioned(case_id: str, revision: str) -> FileResponse:
    case = get_case(case_id)
    return _dzi_response(case.slide_path, VERSIONED_CACHE_HEADERS)


@app.get("/api/cases/{case_id}_files/{level:int}/{col:int}_{row:int}.{fmt}")
def api_case_tile(case_id: str, level: int, col: int, row: int, fmt: str) -> FileResponse:
    case = get_case(case_id)
    return _tile_response(case.slide_path, level, col, row, fmt, NO_STORE_HEADERS)


@app.get("/api/cases/{case_id}/{revision}_files/{level:int}/{col:int}_{row:int}.{fmt}")
def api_case_tile_versioned(case_id: str, revision: str, level: int, col: int, row: int, fmt: str) -> FileResponse:
    case = get_case(case_id)
    return _tile_response(case.slide_path, level, col, row, fmt, VERSIONED_CACHE_HEADERS)


@app.get("/api/cases/{case_id}/concepts/{concept_id}.dzi")
def api_concept_dzi(case_id: str, concept_id: str) -> FileResponse:
    get_case(case_id)
    concept = get_concept(case_id, concept_id)
    return _dzi_response(concept.overlay_path, NO_STORE_HEADERS)


@app.get("/api/cases/{case_id}/concepts/{concept_id}/{revision}.dzi")
def api_concept_dzi_versioned(case_id: str, concept_id: str, revision: str) -> FileResponse:
    get_case(case_id)
    concept = get_concept(case_id, concept_id)
    return _dzi_response(concept.overlay_path, VERSIONED_CACHE_HEADERS)


@app.get("/api/cases/{case_id}/concepts/{concept_id}")
def api_concept_detail(case_id: str, concept_id: str, request: Request) -> Response:
    return _json_response(concept_detail(case_id, concept_id), request)


@app.get("/api/cases/{case_id}/concepts/{concept_id}_files/{level:int}/{col:int}_{row:int}.{fmt}")
def api_concept_tile(case_id: str, concept_id: str, level: int, col: int, row: int, fmt: str) -> FileResponse:
    concept = get_concept(case_id, concept_id)
    return _tile_response(concept.overlay_path, level, col, row, fmt, NO_STORE_HEADERS)


@app.get("/api/cases/{case_id}/concepts/{concept_id}/{revision}_files/{level:int}/{col:int}_{row:int}.{fmt}")
def api_concept_tile_versioned(
    case_id: str,
    concept_id: str,
    revision: str,
    level: int,
    col: int,
    row: int,
    fmt: str,
) -> FileResponse:
    concept = get_concept(case_id, concept_id)
    return _tile_response(concept.overlay_path, level, col, row, fmt, VERSIONED_CACHE_HEADERS)


@app.get("/api/cases/{case_id}/concepts/{concept_id}/patches/{rank:int}.png")
def api_patch_thumbnail(case_id: str, concept_id: str, rank: int, size: int = 128) -> Response:
    case = get_case(case_id)
    concept = get_concept(case_id, concept_id)
    patch = get_patch(case_id, concept_id, rank)
    output_size = max(48, min(size, 256))

    thumbnail_path = _patch_thumbnail_path(concept.patches_path, patch.rank, output_size)
    if thumbnail_path.exists() and thumbnail_path.is_file():
        return FileResponse(thumbnail_path, media_type="image/png", headers=VERSIONED_CACHE_HEADERS)

    content = _render_patch_thumbnail(
        case.id,
        concept.id,
        patch.rank,
        output_size,
        case.slide_revision,
        concept.patches_revision,
    )
    return Response(
        content=content,
        media_type="image/png",
        headers=VERSIONED_CACHE_HEADERS,
    )


@app.get("/api/cases/{case_id}/annotations")
def api_get_annotations(case_id: str) -> JSONResponse:
    get_case(case_id)
    path = annotation_path(case_id)
    if not path.exists():
        return JSONResponse([])
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.put("/api/cases/{case_id}/annotations")
def api_save_annotations(case_id: str, annotations: list = Body(...)) -> dict:
    get_case(case_id)
    annotation_path(case_id).write_text(json.dumps(annotations, indent=2), encoding="utf-8")
    return {"saved": len(annotations)}


@app.get("/api/cases/{case_id}/annotations/export")
def api_export_annotations(case_id: str) -> FileResponse:
    get_case(case_id)
    path = annotation_path(case_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No annotations found")
    return FileResponse(path, media_type="application/json", filename=f"{case_id}.annotations.json")


@app.post("/api/cases/{case_id}/annotations/import")
def api_import_annotations(case_id: str, file: UploadFile = File(...)) -> dict:
    get_case(case_id)
    raw_content = file.file.read()
    try:
        annotations = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid annotation file: {exc}") from exc
    if not isinstance(annotations, list):
        raise HTTPException(status_code=400, detail="Invalid annotation file: expected a JSON array")
    annotation_path(case_id).write_text(json.dumps(annotations, indent=2), encoding="utf-8")
    return {"imported": len(annotations)}
