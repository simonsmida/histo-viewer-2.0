# Histo Viewer 2.0

A FastAPI/OpenSeadragon viewer for histology images, SAE concept overlays, top-activating patches, and annotations. Based on [Heatmap.Viewer](https://github.com/0Kozlik0/Heatmap.Viewer).

## Code and data

Git contains application code, preprocessing scripts, and setup instructions. Runtime data is stored separately in `data/` and is ignored by Git and Docker builds.

```text
app/          FastAPI routes, case discovery, and image loading for thumbnails
static/       HTML, JavaScript, and CSS
scripts/      Overlay, tile, and thumbnail preprocessing
tests/        Preprocessing regression tests
data/         Local runtime data (not committed)
  cases/      Case JSON, source images, overlays, CSVs, DZI descriptors and tiles
  annotations/  Saved user annotations
```

## Run locally

Use Python 3.11 or later. Run commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Populate `data/` from the production server before opening the viewer. On a Mac connected to FIT VPN, with the deployment SSH key available:

```bash
mkdir -p data
rsync -a --partial --no-owner --no-group --timeout=180 \
  --exclude='*_files/**/**_files/' \
  --exclude='*_files/**/*.dzi' \
  -e "ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519_histo -o ServerAliveInterval=15 -o ServerAliveCountMax=3" \
  root@histoviewer.ksi.in.fit.cvut.cz:/opt/histo-viewer-2.0/data/ \
  ./data/
```

This updates local data, including annotations. It excludes redundant pyramids generated inside other tile pyramids. On macOS, if the built-in openrsync stalls, install Homebrew rsync and use `/opt/homebrew/bin/rsync` instead.

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://localhost:8000. `python run.py` is an alternative that listens on all network interfaces, port 8000.

## Run with Docker

Data is mounted at runtime, not baked into the image:

```bash
docker build -t histo-viewer-2 .
docker run --rm -p 8000:8000 -v "$PWD/data:/app/data" histo-viewer-2
```

The data mount must be writable to save annotations.

## Preprocessing

Ordinary code updates do not require regenerating data. After adding source images or changing overlays, generate their Deep Zoom pyramids:

```bash
python scripts/precompute_tiles.py --inputdata/cases --tile-size 256 --overlap 0 --jpeg-quality 85
python scripts/precompute_patch_thumbnails.py --size 128
```

Tile preprocessing skips `*_files` and `patch_thumbnails` directories. Existing pyramids are skipped unless `--force` is supplied; use it after changing source images. Use `--force` for thumbnails after changing slides or patch CSVs. The app serves precomputed tiles and renders missing patch thumbnails on demand.

To rebuild shared SAE overlays and patch CSVs, supply the research dataset directory explicitly:

```bash
python scripts/sync_shared_sae_neurons.py \
  --source-root /path/to/mego-ctc \
  --sae-type batchtopk_latent2048_l048_seed0 \
  --neurons 31 44 51 107 152 162 167 207 252 444 551 580 751 1151 1575
```

The source directory must contain `visualizations/by_image/`, `outputs/conch_embeddings/`, and `outputs/sae_activations/`. The image paths in its metadata must be accessible. This script rebuilds overlays and CSVs, updates case metadata, and removes concepts outside the requested neuron list. Regenerate tiles and thumbnails with `--force` afterward.

To add an image, create `data/cases/<case-id>/slide.png` and a `case.json` following an existing case, including `source_image_slug`, then generate its concepts and tiles.

## Verification

```bash
python -m unittest discover -s tests
```

## Deployment and the one-time data migration

Local changes are tested, committed, pushed, then fast-forwarded into the server checkout at `/opt/histo-viewer-2.0`. Restart `histo-viewer` after application changes. Script-only changes do not need a service restart. The server needs GitHub credentials for `git pull`; SSH access alone does not provide them.

**Before first deploying the commit that removes data from Git tracking:** back up the complete server `data/` directory outside the checkout and verify the backup. Stop the service for this migration to avoid losing new annotations. Pull the code, restore the data into `data/`, verify it, and restart the service. Git may delete formerly tracked data during this first pull; `.gitignore` does not prevent that. Do not delete the backup until the viewer has been verified.

Subsequent deployments transport code through Git and data through rsync. Never commit `.venv/`, runtime data, or credentials. Removing data from the current Git index does not shrink existing Git history; rewriting history is a separate operation.

## Pathologist demonstration controls

The image slider blends the original interpolated Turbo heatmap over the histology image. Both use precomputed Deep Zoom tiles in the same OpenSeadragon viewport, so pan and zoom stay synchronized. The legend runs from weaker to stronger pattern response. The export normalizes each image/group separately; the colors are not comparable across images.

Click a patch to make a gentle, animated move to a broad surrounding tissue region and highlight its location without opening a dialog. Choose **View patch details** to explicitly inspect its original-resolution crop and surrounding tissue. Without an original, the dialog explicitly identifies the reduced preview fallback.

To enable original-resolution crops, place an original image inside its case directory and add `source_image_path` (a path relative to that directory) to `case.json`. Its dimensions must match `source_width` and `source_height`. Add `microns_per_pixel_x` and `microns_per_pixel_y` only when physical calibration is known. A scale bar and patch measurements appear only with valid calibration. Image dimensions alone are not a physical calibration.

The local demonstration has matching original TIFFs for Samples 2 and 3. Sample 2's ImageJ TIFF records micrometre units and 1.371211 pixels per micrometre (0.7292823643 µm/pixel); Sample 3 has no usable physical calibration. Sample 1 currently uses the preview fallback. These files and case metadata remain under ignored `data/` and must be transferred separately for any deployment.

Future research work: evaluate feature consistency beyond top-ranked patches, including intermediate/random active examples and controls from held-out slides. This is not part of the current demonstration UI.
