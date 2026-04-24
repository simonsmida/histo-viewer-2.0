# Histo Viewer 2.0

NOTE: Histology viewer revibe-coded based on Patrik's originally vibe-coded [Heatmap.Viewer](https://github.com/0Kozlik0/Heatmap.Viewer) (thank you!).


## What Is Included

- 2 local histology images packaged inside the repo
- shared SAE neuron overlays synced across every image
- heatmap overlay toggle with opacity control
- top activating patch browser for each concept
- annotation drawing, save, export, and import
- lightweight FastAPI backend with raster Deep Zoom tiles

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open [http://localhost:8000](http://localhost:8000)

## Run With Docker

```bash
docker build -t histo-viewer-2 .
docker run --rm -p 8000:8000 histo-viewer-2
```

## Project Layout

```text
histo-viewer-2.0/
|- app/
|  |- catalog.py        # local case/concept discovery
|  |- main.py           # FastAPI routes
|  `- tiles.py          # raster Deep Zoom tile rendering
|- data/
|  |- cases/            # packaged slides, overlays, and patch CSVs
|  `- annotations/      # saved annotations per histology image
|- static/
|  |- app.js            # frontend logic
|  |- index.html        # UI shell
|  `- styles.css        # viewer styles
|- Dockerfile
|- requirements.txt
`- run.py
```

## Syncing Shared SAE Neurons

Use the sync script whenever you want the same SAE neurons to be available for every case:

```bash
python3 scripts/sync_shared_sae_neurons.py \
  --sae-type batchtopk_latent2048_l048_seed0 \
  --neurons 31 44 51 107 152 162 167 207 252 444 551 580 751 1151 1575
```

The script:

- rebuilds `overlay.png` as the clean interpolated colormap heatmap plus `patches.csv` for every listed neuron in every case
- updates each `case.json` so all cases expose the same neuron list
- removes old concept folders that are no longer in the shared selection

Each case also stores a `source_image_slug` in `case.json`. If you add a new case later, set that field to the matching source image slug from `Research/FoundationModels/CONCH/mego-ctc/visualizations/by_image/`, then rerun the script.

## Performance Precomputes

The repository already stores Deep Zoom tiles for slides and concept overlays. After pulling fresh data on the server, you can also precompute the patch thumbnails used by the right-side patch browser:

```bash
python3 scripts/precompute_patch_thumbnails.py --size 128
```

The app can generate missing thumbnails on demand, but precomputing them makes the first concept selection smoother.

## Adding More Images Later

1. Create a new folder under `data/cases/`.
2. Add a `slide.png` preview image.
3. Create a `case.json` matching the existing examples in `data/cases/case-01/` and `data/cases/case-02/`.
4. Set `source_image_slug` in that `case.json`.
5. Run `scripts/sync_shared_sae_neurons.py` to populate the shared neuron overlays.

The backend auto-discovers every case folder that contains a valid `case.json`.
