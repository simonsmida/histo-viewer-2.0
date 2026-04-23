#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import pickle
import shutil
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from matplotlib import colormaps
from PIL import Image, ImageFilter

# python3 scripts/sync_shared_sae_neurons.py \
#   --sae-type batchtopk_latent2048_l048_seed0 \
#   --neurons 1 2 3


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "cases"
SOURCE_ROOT = Path("/Users/kailash/Desktop/PhD/Research/FoundationModels/CONCH/mego-ctc")
SOURCE_VIS_DIR = SOURCE_ROOT / "visualizations" / "by_image"

DEFAULT_SAE_TYPE = "batchtopk_latent2048_l048_seed0"
DEFAULT_NEURONS = [31, 44, 51, 107, 152, 162, 167, 207, 252, 444, 551, 580, 751, 1151, 1575]
DEFAULT_CASE_SOURCE_SLUGS = {
    "case-01": "1005137_0_poloha_537_1_0_EP_0_EMT_0_ANY_0",
    "case-02": "camelyon2",
}

DTYPES = {
    "BoolStorage": np.dtype("?"),
    "ByteStorage": np.dtype("u1"),
    "FloatStorage": np.dtype("<f4"),
    "IntStorage": np.dtype("<i4"),
    "LongStorage": np.dtype("<i8"),
}


@dataclass(frozen=True)
class PatchRecord:
    patch_index: int
    x: int
    y: int
    grid_row: int
    grid_col: int
    tissue_fraction: float


@dataclass(frozen=True)
class StorageRef:
    storage_type: str
    key: str
    location: str
    size: int


class TorchZipUnpickler(pickle.Unpickler):
    def __init__(self, handle, zip_file: zipfile.ZipFile, prefix: str) -> None:
        super().__init__(handle)
        self.zip_file = zip_file
        self.prefix = prefix

    def persistent_load(self, pid):
        kind, storage_type, key, location, size = pid
        if kind != "storage":
            raise pickle.UnpicklingError(f"Unsupported persistent kind: {kind}")
        return StorageRef(
            storage_type=str(storage_type),
            key=str(key),
            location=str(location),
            size=int(size),
        )

    def find_class(self, module: str, name: str):
        if module == "collections" and name == "OrderedDict":
            return OrderedDict
        if module == "torch._utils" and name == "_rebuild_tensor_v2":
            return self._rebuild_tensor_v2
        if module == "torch" and name.endswith("Storage"):
            return name
        raise pickle.UnpicklingError(f"Unsupported global: {module} {name}")

    def _rebuild_tensor_v2(self, storage_ref, storage_offset, size, stride, requires_grad, backward_hooks):
        dtype = DTYPES.get(storage_ref.storage_type)
        if dtype is None:
            raise ValueError(f"Unsupported storage type: {storage_ref.storage_type}")

        raw = self.zip_file.read(f"{self.prefix}/data/{storage_ref.key}")
        storage = np.frombuffer(raw, dtype=dtype, count=storage_ref.size)

        if isinstance(size, int):
            size = (size,)
        if isinstance(stride, int):
            stride = (stride,)

        if not size:
            return storage[int(storage_offset)]

        view = np.lib.stride_tricks.as_strided(
            storage[int(storage_offset):],
            shape=tuple(int(dim) for dim in size),
            strides=tuple(int(step) * dtype.itemsize for step in stride),
        )
        return np.array(view, copy=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync one shared SAE neuron list into every histology case."
    )
    parser.add_argument("--sae-type", default=DEFAULT_SAE_TYPE)
    parser.add_argument("--neurons", nargs="+", type=int, default=DEFAULT_NEURONS)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_torch_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as zip_file:
        prefix = path.stem
        with zip_file.open(f"{prefix}/data.pkl") as handle:
            return TorchZipUnpickler(handle, zip_file, prefix).load()


def patch_slug(patch_size: int, stride: int, min_tissue_fraction: float, white_threshold: float) -> str:
    return (
        f"patches_p{patch_size}"
        f"_s{stride}"
        f"_tf{int(round(min_tissue_fraction * 1000)):03d}"
        f"_w{int(round(white_threshold * 1000)):03d}"
        "_all"
    )


def grayscale_float(image_array: np.ndarray) -> np.ndarray:
    weights = np.asarray([0.299, 0.587, 0.114], dtype=np.float32)
    return np.tensordot(image_array.astype(np.float32), weights, axes=([-1], [0])) / 255.0


def grayscale_rgb(image_array: np.ndarray) -> np.ndarray:
    gray = np.clip(grayscale_float(image_array) * 255.0, 0, 255).astype(np.uint8)
    return np.repeat(gray[..., None], 3, axis=2)


def resize_array(
    image_array: np.ndarray,
    target_size: tuple[int, int],
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> np.ndarray:
    image = Image.fromarray(image_array)
    if image.size == target_size:
        return np.asarray(image)
    return np.asarray(image.resize(target_size, resample=resample))


def normalize_positive_scores(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return np.asarray([], dtype=np.float32)
    minimum = float(scores.min())
    maximum = float(scores.max())
    if maximum <= minimum:
        return np.ones(scores.shape[0], dtype=np.float32)
    return ((scores - minimum) / (maximum - minimum)).astype(np.float32)


def compute_tissue_fraction(patch_rgb: np.ndarray, white_threshold: float) -> float:
    return float((grayscale_float(patch_rgb) < white_threshold).mean())


def sliding_positions(length: int, patch_size: int, stride: int) -> list[int]:
    positions = list(range(0, length - patch_size + 1, stride))
    final_position = length - patch_size
    if positions[-1] != final_position:
        positions.append(final_position)
    return positions


def build_patch_records(
    image_array: np.ndarray,
    coordinates: np.ndarray,
    patch_size: int,
    stride: int,
    white_threshold: float,
) -> list[PatchRecord]:
    height, width = image_array.shape[:2]
    xs = sliding_positions(width, patch_size, stride)
    ys = sliding_positions(height, patch_size, stride)
    x_to_col = {x: col for col, x in enumerate(xs)}
    y_to_row = {y: row for row, y in enumerate(ys)}

    records: list[PatchRecord] = []
    for patch_index, coordinate in enumerate(coordinates):
        x, y = (int(coordinate[0]), int(coordinate[1]))
        patch = image_array[y:y + patch_size, x:x + patch_size]
        records.append(
            PatchRecord(
                patch_index=patch_index,
                x=x,
                y=y,
                grid_row=y_to_row[y],
                grid_col=x_to_col[x],
                tissue_fraction=compute_tissue_fraction(patch, white_threshold),
            )
        )
    return records


def build_interpolated_heatmap(
    image_shape: tuple[int, int],
    records: list[PatchRecord],
    patch_size: int,
    positive_indices: np.ndarray,
    normalized_scores: np.ndarray,
) -> np.ndarray:
    height, width = image_shape
    heatmap = np.zeros((height, width), dtype=np.float32)
    for patch_index, normalized_score in zip(positive_indices, normalized_scores, strict=True):
        record = records[int(patch_index)]
        region = heatmap[record.y:record.y + patch_size, record.x:record.x + patch_size]
        np.maximum(region, float(normalized_score), out=region)

    blurred = Image.fromarray(np.clip(heatmap * 255.0, 0, 255).astype(np.uint8), mode="L")
    blurred = blurred.filter(ImageFilter.GaussianBlur(radius=patch_size * 0.25))
    return np.asarray(blurred, dtype=np.float32) / 255.0


def build_clean_colormap_overlay(
    base_rgb: np.ndarray,
    heatmap: np.ndarray,
    target_size: tuple[int, int],
) -> np.ndarray:
    display_base = resize_array(
        base_rgb,
        target_size=target_size,
        resample=Image.Resampling.LANCZOS,
    ).astype(np.float32)
    display_heatmap = (
        resize_array(
            (heatmap * 255.0).astype(np.uint8),
            target_size=target_size,
            resample=Image.Resampling.BILINEAR,
        ).astype(np.float32)
        / 255.0
    )
    alpha = np.where(display_heatmap > 0.0, 0.10 + 0.85 * (display_heatmap ** 0.85), 0.0).astype(np.float32)
    colormap_rgb = (colormaps.get_cmap("turbo")(display_heatmap)[..., :3] * 255.0).astype(np.float32)
    overlay = display_base * (1.0 - alpha[..., None]) + colormap_rgb * alpha[..., None]
    return np.clip(overlay, 0, 255).astype(np.uint8)


def activated_patch_rows(
    records: list[PatchRecord],
    scores: np.ndarray,
    positive_indices: np.ndarray,
    normalized_scores: np.ndarray,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    order = np.argsort(-scores[positive_indices]) if positive_indices.size else np.asarray([], dtype=np.int64)
    for rank, order_index in enumerate(order, start=1):
        patch_index = int(positive_indices[int(order_index)])
        record = records[patch_index]
        rows.append(
            {
                "rank": rank,
                "patch_index": record.patch_index,
                "x": record.x,
                "y": record.y,
                "grid_row": record.grid_row,
                "grid_col": record.grid_col,
                "tissue_fraction": record.tissue_fraction,
                "activation": float(scores[patch_index]),
                "normalized_activation": float(normalized_scores[int(order_index)]),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def source_slug_for_case(case_id: str, case_payload: dict) -> str:
    source_slug = case_payload.get("source_image_slug")
    if source_slug:
        return str(source_slug)
    try:
        return DEFAULT_CASE_SOURCE_SLUGS[case_id]
    except KeyError as exc:
        raise KeyError(
            f"Missing source_image_slug for {case_id}. Add it to case.json before syncing."
        ) from exc


def load_source_bundle(source_slug: str, sae_type: str) -> tuple[dict, np.ndarray, list[PatchRecord], np.ndarray]:
    image_metadata = load_json(SOURCE_VIS_DIR / source_slug / "image_metadata.json")
    patch_key = patch_slug(
        patch_size=int(image_metadata["patch_size"]),
        stride=int(image_metadata["stride"]),
        min_tissue_fraction=float(image_metadata["min_tissue_fraction"]),
        white_threshold=float(image_metadata["white_threshold"]),
    )
    embedding_cache = SOURCE_ROOT / "outputs" / "conch_embeddings" / source_slug / patch_key / "conch_patch_embeddings.pt"
    activation_cache = SOURCE_ROOT / "outputs" / "sae_activations" / sae_type / source_slug / patch_key / "all_latent_activations.pt"

    if not embedding_cache.exists():
        raise FileNotFoundError(f"Missing embedding cache: {embedding_cache}")
    if not activation_cache.exists():
        raise FileNotFoundError(f"Missing activation cache: {activation_cache}")

    embedding_payload = load_torch_zip(embedding_cache)
    activation_payload = load_torch_zip(activation_cache)
    image_array = np.asarray(Image.open(image_metadata["image_path"]).convert("RGB"))
    records = build_patch_records(
        image_array=image_array,
        coordinates=np.asarray(embedding_payload["coordinates"]),
        patch_size=int(image_metadata["patch_size"]),
        stride=int(image_metadata["stride"]),
        white_threshold=float(image_metadata["white_threshold"]),
    )
    activations = np.asarray(activation_payload["activations"], dtype=np.float32)
    return image_metadata, image_array, records, activations


def concept_id_for(neuron: int) -> str:
    return f"concept-{neuron:04d}"


def sync_case(case_dir: Path, sae_type: str, neurons: list[int]) -> None:
    case_path = case_dir / "case.json"
    case_payload = load_json(case_path)
    case_id = str(case_payload["id"])
    source_slug = source_slug_for_case(case_id, case_payload)
    image_metadata, image_array, records, activations = load_source_bundle(source_slug, sae_type)

    slide_width, slide_height = Image.open(case_dir / "slide.png").size
    patch_size = int(image_metadata["patch_size"])
    concepts_dir = case_dir / "concepts"
    concepts_dir.mkdir(exist_ok=True)
    keep_ids = {concept_id_for(neuron) for neuron in neurons}

    for concept_dir in sorted(concepts_dir.iterdir()):
        if concept_dir.is_dir() and concept_dir.name.startswith("concept-") and concept_dir.name not in keep_ids:
            shutil.rmtree(concept_dir)

    concepts: list[dict[str, object]] = []
    latent_dim = int(activations.shape[1])
    grayscale_base = grayscale_rgb(image_array)
    for neuron in neurons:
        if neuron < 0 or neuron >= latent_dim:
            raise ValueError(f"Neuron {neuron} is outside [0, {latent_dim - 1}] for {sae_type}")

        concept_id = concept_id_for(neuron)
        concept_dir = concepts_dir / concept_id
        concept_dir.mkdir(parents=True, exist_ok=True)

        scores = activations[:, neuron].astype(np.float32)
        positive_indices = np.flatnonzero(scores > 0.0)
        positive_scores = scores[positive_indices]
        normalized_scores = normalize_positive_scores(positive_scores)

        heatmap = build_interpolated_heatmap(
            image_shape=image_array.shape[:2],
            records=records,
            patch_size=patch_size,
            positive_indices=positive_indices,
            normalized_scores=normalized_scores,
        )
        overlay = build_clean_colormap_overlay(
            base_rgb=grayscale_base,
            heatmap=heatmap,
            target_size=(slide_width, slide_height),
        )
        Image.fromarray(overlay).save(concept_dir / "overlay.png")

        write_csv(
            concept_dir / "patches.csv",
            rows=activated_patch_rows(
                records=records,
                scores=scores,
                positive_indices=positive_indices,
                normalized_scores=normalized_scores,
            ),
            fieldnames=[
                "rank",
                "patch_index",
                "x",
                "y",
                "grid_row",
                "grid_col",
                "tissue_fraction",
                "activation",
                "normalized_activation",
            ],
        )

        concepts.append(
            {
                "id": concept_id,
                "label": f"Potential concept {neuron}",
                "positive_patch_count": int(positive_indices.size),
                "max_score": float(positive_scores.max()) if positive_scores.size else 0.0,
                "overlay_path": f"concepts/{concept_id}/overlay.png",
                "patches_path": f"concepts/{concept_id}/patches.csv",
            }
        )

    case_payload["source_image_slug"] = source_slug
    case_payload["sae_type"] = sae_type
    case_payload["source_width"] = int(image_metadata["image_width"])
    case_payload["source_height"] = int(image_metadata["image_height"])
    case_payload["viewer_width"] = slide_width
    case_payload["viewer_height"] = slide_height
    case_payload["patch_size"] = patch_size
    case_payload["default_concept_id"] = concepts[0]["id"]
    case_payload["concepts"] = concepts
    write_json(case_path, case_payload)

    print(f"{case_id}: synced {len(neurons)} neurons from {sae_type}")


def main() -> None:
    args = parse_args()
    neurons = sorted(dict.fromkeys(args.neurons))
    for case_dir in sorted(path for path in CASES_DIR.iterdir() if path.is_dir()):
        sync_case(case_dir=case_dir, sae_type=args.sae_type, neurons=neurons)


if __name__ == "__main__":
    main()
