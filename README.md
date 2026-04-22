# Histo Viewer 2.0

NOTE: Histology viewer revibe-coded based on Patrik's originally vibe-coded [Heatmap.Viewer](https://github.com/0Kozlik0/Heatmap.Viewer) (thank you!).


## What Is Included

- 2 local histology images packaged inside the repo
- 6 curated potential concepts for each image
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

## Adding More Images Later

1. Create a new folder under `data/cases/`.
2. Add a `slide.png` preview image.
3. Add one `overlay.png` and one `patches.csv` for each potential concept.
4. Create a `case.json` matching the existing examples in `data/cases/case-01/` and `data/cases/case-02/`.

The backend auto-discovers every case folder that contains a valid `case.json`.
