const ANNOT_COLORS = [
  "#e94560",
  "#2563eb",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#65a30d",
];

const viewer = OpenSeadragon({
  id: "viewer",
  prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@4.1/build/openseadragon/images/",
  showNavigator: true,
  navigatorPosition: "BOTTOM_RIGHT",
  navigatorSizeRatio: 0.15,
  navigatorBackground: "#f5f6f8",
  navigatorBorderColor: "#dfe3e8",
  animationTime: 0.3,
  minZoomImageRatio: 0.5,
  maxZoomPixelRatio: 40,
  visibilityRatio: 0.5,
  crossOriginPolicy: "Anonymous",
  subPixelRoundingForTransparency: OpenSeadragon.SUBPIXEL_ROUNDING_OCCURRENCES.ONLY_AT_REST,
  gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
  showZoomControl: false,
  showHomeControl: false,
  showFullPageControl: false,
});

const elements = {
  annotCanvas: document.getElementById("annotCanvas"),
  annotCount: document.getElementById("annotCount"),
  annotExport: document.getElementById("annotExport"),
  annotImportInput: document.getElementById("annotImportInput"),
  annotList: document.getElementById("annotList"),
  annotSave: document.getElementById("annotSave"),
  annotToggleAll: document.getElementById("annotToggleAll"),
  caseSelect: document.getElementById("caseSelect"),
  conceptSelect: document.getElementById("conceptSelect"),
  coordBar: document.getElementById("coordBar"),
  headerStatus: document.getElementById("headerStatus"),
  heatmapToggle: document.getElementById("heatmapToggle"),
  noAnnotMsg: document.getElementById("noAnnotMsg"),
  opacityLabel: document.getElementById("opacityLabel"),
  opacitySlider: document.getElementById("opacitySlider"),
  patchEmptyState: document.getElementById("patchEmptyState"),
  patchGrid: document.getElementById("patchGrid"),
  rightPanel: document.getElementById("rightPanel"),
  statusCoords: document.getElementById("statusCoords"),
  statusDims: document.getElementById("statusDims"),
  statusTool: document.getElementById("statusTool"),
  statusZoom: document.getElementById("statusZoom"),
  toolPanel: document.getElementById("toolPanel"),
  viewerControls: document.getElementById("viewerControls"),
};

const annotCtx = elements.annotCanvas.getContext("2d");

const state = {
  activeTool: "pan",
  annotations: [],
  cases: [],
  currentCase: null,
  currentConcept: null,
  heatmapItem: null,
  heatmapVisible: true,
  isDrawing: false,
  drawStart: null,
  freehandPoints: [],
  nextColorIndex: 0,
  overlayRequestToken: 0,
  selectedPatchKey: null,
  selectedPatchOverlay: null,
};

function setStatus(message, isError = false) {
  elements.headerStatus.textContent = message;
  elements.headerStatus.classList.toggle("error", isError);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function getNextColor() {
  const color = ANNOT_COLORS[state.nextColorIndex % ANNOT_COLORS.length];
  state.nextColorIndex += 1;
  return color;
}

function resizeCanvas() {
  const rect = elements.annotCanvas.parentElement.getBoundingClientRect();
  const coordHeight = elements.coordBar.offsetHeight || 28;
  elements.annotCanvas.width = rect.width;
  elements.annotCanvas.height = rect.height - coordHeight;
}

function canvasToImage(canvasX, canvasY) {
  if (!viewer.isOpen()) {
    return null;
  }
  const viewportPoint = viewer.viewport.pointFromPixel(new OpenSeadragon.Point(canvasX, canvasY));
  const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
  return { x: imagePoint.x, y: imagePoint.y };
}

function imageToCanvas(imageX, imageY) {
  if (!viewer.isOpen()) {
    return null;
  }
  const viewportPoint = viewer.viewport.imageToViewportCoordinates(imageX, imageY);
  const pixelPoint = viewer.viewport.pixelFromPoint(viewportPoint);
  return { x: pixelPoint.x, y: pixelPoint.y };
}

function setActiveTool(tool) {
  state.activeTool = tool;
  document.querySelectorAll(".sidebar-tool[data-tool]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === tool);
  });
  elements.annotCanvas.classList.toggle("drawing", tool !== "pan");
  viewer.setMouseNavEnabled(tool === "pan");
  const label = { pan: "", bbox: "Bounding Box", freehand: "Freehand" }[tool];
  elements.statusTool.textContent = label ? `Tool: ${label}` : "";
}

function redrawAnnotations(currentMousePoint = null) {
  annotCtx.clearRect(0, 0, elements.annotCanvas.width, elements.annotCanvas.height);
  if (!viewer.isOpen()) {
    return;
  }

  for (const annotation of state.annotations) {
    if (!annotation.visible) {
      continue;
    }

    annotCtx.strokeStyle = annotation.color;
    annotCtx.lineWidth = 2.5;
    annotCtx.fillStyle = `${annotation.color}18`;

    if (annotation.type === "bbox") {
      const topLeft = imageToCanvas(annotation.rect.x, annotation.rect.y);
      const bottomRight = imageToCanvas(annotation.rect.x + annotation.rect.w, annotation.rect.y + annotation.rect.h);
      if (!topLeft || !bottomRight) {
        continue;
      }
      annotCtx.fillRect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
      annotCtx.strokeRect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
    }

    if (annotation.type === "freehand" && annotation.points.length > 1) {
      const firstPoint = imageToCanvas(annotation.points[0].x, annotation.points[0].y);
      if (!firstPoint) {
        continue;
      }
      annotCtx.beginPath();
      annotCtx.moveTo(firstPoint.x, firstPoint.y);
      for (let index = 1; index < annotation.points.length; index += 1) {
        const point = imageToCanvas(annotation.points[index].x, annotation.points[index].y);
        if (point) {
          annotCtx.lineTo(point.x, point.y);
        }
      }
      annotCtx.closePath();
      annotCtx.fill();
      annotCtx.stroke();
    }
  }

  if (!state.isDrawing || !currentMousePoint) {
    return;
  }

  annotCtx.strokeStyle = "#2563eb";
  annotCtx.lineWidth = 2;
  annotCtx.setLineDash([6, 4]);

  if (state.activeTool === "bbox" && state.drawStart) {
    const topLeft = imageToCanvas(
      Math.min(state.drawStart.x, currentMousePoint.x),
      Math.min(state.drawStart.y, currentMousePoint.y),
    );
    const bottomRight = imageToCanvas(
      Math.max(state.drawStart.x, currentMousePoint.x),
      Math.max(state.drawStart.y, currentMousePoint.y),
    );
    if (topLeft && bottomRight) {
      annotCtx.fillStyle = "rgba(37, 99, 235, 0.08)";
      annotCtx.fillRect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
      annotCtx.strokeRect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
    }
  }

  if (state.activeTool === "freehand" && state.freehandPoints.length > 1) {
    const firstPoint = imageToCanvas(state.freehandPoints[0].x, state.freehandPoints[0].y);
    if (firstPoint) {
      annotCtx.beginPath();
      annotCtx.moveTo(firstPoint.x, firstPoint.y);
      for (let index = 1; index < state.freehandPoints.length; index += 1) {
        const point = imageToCanvas(state.freehandPoints[index].x, state.freehandPoints[index].y);
        if (point) {
          annotCtx.lineTo(point.x, point.y);
        }
      }
      annotCtx.stroke();
    }
  }

  annotCtx.setLineDash([]);
}

function addAnnotation(annotation) {
  state.annotations.push(annotation);
  renderAnnotationList();
  redrawAnnotations();
}

function renameAnnotation(annotationId, nextName) {
  const annotation = state.annotations.find((entry) => entry.id === annotationId);
  if (annotation) {
    annotation.name = nextName;
  }
}

function toggleAnnotation(annotationId) {
  const annotation = state.annotations.find((entry) => entry.id === annotationId);
  if (annotation) {
    annotation.visible = !annotation.visible;
  }
  renderAnnotationList();
  redrawAnnotations();
}

function removeAnnotation(annotationId) {
  state.annotations = state.annotations.filter((entry) => entry.id !== annotationId);
  renderAnnotationList();
  redrawAnnotations();
}

function focusAnnotation(annotationId) {
  const annotation = state.annotations.find((entry) => entry.id === annotationId);
  if (!annotation || !state.currentCase) {
    return;
  }

  let centerX = 0;
  let centerY = 0;
  let focusWidth = 0;

  if (annotation.type === "bbox") {
    centerX = annotation.rect.x + annotation.rect.w / 2;
    centerY = annotation.rect.y + annotation.rect.h / 2;
    focusWidth = annotation.rect.w * 2;
  } else {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const point of annotation.points) {
      minX = Math.min(minX, point.x);
      minY = Math.min(minY, point.y);
      maxX = Math.max(maxX, point.x);
      maxY = Math.max(maxY, point.y);
    }
    centerX = (minX + maxX) / 2;
    centerY = (minY + maxY) / 2;
    focusWidth = (maxX - minX) * 2;
  }

  const viewportCenter = viewer.viewport.imageToViewportCoordinates(centerX, centerY);
  const viewportWidth = focusWidth / state.currentCase.viewer_width;
  const zoom = 1 / Math.max(viewportWidth, 0.05);
  viewer.viewport.panTo(viewportCenter);
  viewer.viewport.zoomTo(Math.max(zoom, viewer.viewport.getMinZoom()));
}

function renderAnnotationList() {
  elements.annotCount.textContent = state.annotations.length;
  elements.noAnnotMsg.style.display = state.annotations.length ? "none" : "";
  elements.annotList.innerHTML = "";

  for (const annotation of state.annotations) {
    const item = document.createElement("li");
    item.className = "annot-item";
    item.innerHTML = `
      <span class="annot-color-dot" style="background:${annotation.color};"></span>
      <div class="annot-item-label">
        <span class="annot-item-name" contenteditable="true" spellcheck="false" data-id="${annotation.id}">${annotation.name}</span>
        <div class="annot-item-type">${annotation.type === "bbox" ? "Bounding Box" : "Freehand"}</div>
      </div>
      <div class="annot-item-actions">
        <button class="annot-action-btn ${annotation.visible ? "" : "hidden"}" data-action="toggle" data-id="${annotation.id}" title="${annotation.visible ? "Hide" : "Show"}">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            ${annotation.visible
              ? '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>'
              : '<path d="M2 2l12 12"/><path d="M6.5 6.5a2 2 0 002.8 2.8"/><path d="M1.5 8s2.5-4.5 6.5-4.5c1 0 1.9.3 2.7.7"/><path d="M14.5 8s-.8 1.5-2.5 2.8"/>'}
          </svg>
        </button>
        <button class="annot-action-btn" data-action="focus" data-id="${annotation.id}" title="Go to annotation">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5"/><circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg>
        </button>
        <button class="annot-action-btn delete" data-action="delete" data-id="${annotation.id}" title="Delete annotation">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4h10M6 4V3a1 1 0 011-1h2a1 1 0 011 1v1M5 4v8a1 1 0 001 1h4a1 1 0 001-1V4"/></svg>
        </button>
      </div>
    `;
    elements.annotList.appendChild(item);
  }

  elements.annotList.querySelectorAll(".annot-action-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const { action, id } = button.dataset;
      if (action === "toggle") {
        toggleAnnotation(id);
      }
      if (action === "delete") {
        removeAnnotation(id);
      }
      if (action === "focus") {
        focusAnnotation(id);
      }
    });
  });

  elements.annotList.querySelectorAll(".annot-item-name").forEach((label) => {
    label.addEventListener("blur", () => {
      renameAnnotation(label.dataset.id, label.textContent.trim() || "Unnamed");
    });
    label.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        label.blur();
      }
    });
  });
}

function removeHeatmapOverlay() {
  state.overlayRequestToken += 1;
  if (!state.heatmapItem) {
    return;
  }
  const index = viewer.world.getIndexOfItem(state.heatmapItem);
  if (index >= 0) {
    viewer.world.removeItem(state.heatmapItem);
  }
  state.heatmapItem = null;
}

function setHeatmapOpacity(opacity) {
  if (state.heatmapItem) {
    state.heatmapItem.setOpacity(opacity);
  }
}

function applyHeatmapOverlay() {
  removeHeatmapOverlay();
  if (!state.currentCase || !state.currentConcept || !state.heatmapVisible) {
    return;
  }
  const requestToken = state.overlayRequestToken;
  const addOverlay = () => {
    viewer.addTiledImage({
      tileSource: state.currentConcept.overlay_dzi_url,
      opacity: Number(elements.opacitySlider.value) / 100,
      index: viewer.world.getItemCount(),
      success: ({ item }) => {
        if (requestToken !== state.overlayRequestToken) {
          viewer.world.removeItem(item);
          return;
        }
        state.heatmapItem = item;
        item.setOpacity(Number(elements.opacitySlider.value) / 100);
      },
    });
  };

  if (viewer.isOpen()) {
    addOverlay();
  } else {
    viewer.addOnceHandler("open", addOverlay);
  }
}

function removeSelectedPatchOverlay() {
  if (state.selectedPatchOverlay) {
    viewer.removeOverlay(state.selectedPatchOverlay);
    state.selectedPatchOverlay = null;
  }
}

function applySelectedPatchOverlay(patch) {
  removeSelectedPatchOverlay();
  const overlay = document.createElement("div");
  overlay.className = "selected-patch-bbox";
  overlay.title = `Patch #${patch.rank}`;
  overlay.innerHTML = `
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <rect class="selected-patch-fill" x="2" y="2" width="96" height="96" rx="1.5" ry="1.5"></rect>
      <rect class="selected-patch-stroke-back" x="2.5" y="2.5" width="95" height="95" rx="1.5" ry="1.5"></rect>
      <rect class="selected-patch-stroke-front" x="2.5" y="2.5" width="95" height="95" rx="1.5" ry="1.5"></rect>
    </svg>
  `;
  state.selectedPatchOverlay = overlay;
  viewer.addOverlay({
    element: overlay,
    location: new OpenSeadragon.Rect(
      patch.viewer_x / state.currentCase.viewer_width,
      patch.viewer_y / state.currentCase.viewer_width,
      patch.viewer_w / state.currentCase.viewer_width,
      patch.viewer_h / state.currentCase.viewer_width,
    ),
  });
}

function updateActivePatchCard() {
  elements.patchGrid.querySelectorAll(".patch-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.patchKey === state.selectedPatchKey);
  });
}

function renderPatchGrid() {
  if (!state.currentConcept) {
    elements.patchGrid.innerHTML = "";
    elements.patchEmptyState.style.display = "";
    return;
  }

  elements.patchEmptyState.style.display = "none";
  elements.patchGrid.innerHTML = "";
  const fragment = document.createDocumentFragment();

  for (const patch of state.currentConcept.patches) {
    const patchKey = `${patch.rank}-${patch.patch_index}`;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "patch-card";
    card.dataset.patchKey = patchKey;
    card.innerHTML = `<img class="patch-thumb" src="${patch.thumbnail_url}" loading="lazy" decoding="async" alt="Patch #${patch.rank}" />`;
    card.addEventListener("click", () => {
      if (state.selectedPatchKey === patchKey) {
        state.selectedPatchKey = null;
        removeSelectedPatchOverlay();
        updateActivePatchCard();
        return;
      }
      state.selectedPatchKey = patchKey;
      applySelectedPatchOverlay(patch);
      updateActivePatchCard();
    });
    fragment.appendChild(card);
  }

  elements.patchGrid.appendChild(fragment);
  updateActivePatchCard();
}

async function loadAnnotations() {
  if (!state.currentCase) {
    state.annotations = [];
    renderAnnotationList();
    redrawAnnotations();
    return;
  }
  state.annotations = await fetchJson(`/api/cases/${encodeURIComponent(state.currentCase.id)}/annotations`);
  state.nextColorIndex = state.annotations.length;
  renderAnnotationList();
  redrawAnnotations();
}

async function saveAnnotations() {
  if (!state.currentCase) {
    return;
  }
  await fetchJson(`/api/cases/${encodeURIComponent(state.currentCase.id)}/annotations`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.annotations),
  });
  setStatus("Annotations saved.");
}

async function loadConcept(conceptId) {
  if (!state.currentCase || !conceptId) {
    return;
  }

  elements.patchEmptyState.style.display = "";
  elements.patchEmptyState.querySelector("p").textContent = "Loading patches...";
  state.selectedPatchKey = null;
  removeSelectedPatchOverlay();

  state.currentConcept = await fetchJson(
    `/api/cases/${encodeURIComponent(state.currentCase.id)}/concepts/${encodeURIComponent(conceptId)}`,
  );

  if (state.heatmapVisible) {
    applyHeatmapOverlay();
  } else {
    removeHeatmapOverlay();
  }

  renderPatchGrid();
  activateTab("patches");
  setStatus(`${state.currentCase.label} loaded with ${state.currentConcept.label}.`);
}

async function loadCase(caseId) {
  state.currentConcept = null;
  state.selectedPatchKey = null;
  elements.patchGrid.innerHTML = "";
  elements.patchEmptyState.style.display = "";
  elements.patchEmptyState.querySelector("p").textContent = "Loading patches...";
  state.currentCase = await fetchJson(`/api/cases/${encodeURIComponent(caseId)}/info`);
  elements.statusDims.textContent =
    `Source ${state.currentCase.source_width.toLocaleString()} x ${state.currentCase.source_height.toLocaleString()} px · viewer ${state.currentCase.viewer_width.toLocaleString()} x ${state.currentCase.viewer_height.toLocaleString()} px`;
  elements.viewerControls.hidden = false;
  viewer.open(`/api/cases/${encodeURIComponent(caseId)}.dzi`);
  await loadAnnotations();
}

async function populateConcepts(caseId, selectedConceptId = null) {
  const concepts = await fetchJson(`/api/cases/${encodeURIComponent(caseId)}/concepts`);
  elements.conceptSelect.innerHTML = "";
  for (const concept of concepts) {
    const option = document.createElement("option");
    option.value = concept.id;
    option.textContent = `${concept.label} (${concept.positive_patch_count.toLocaleString()} patches)`;
    elements.conceptSelect.appendChild(option);
  }
  const nextConceptId = selectedConceptId || state.currentCase.default_concept_id || concepts[0]?.id;
  elements.conceptSelect.value = nextConceptId;
  await loadConcept(nextConceptId);
}

async function initializeCases() {
  state.cases = await fetchJson("/api/cases");
  elements.caseSelect.innerHTML = "";
  for (const item of state.cases) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label;
    elements.caseSelect.appendChild(option);
  }

  const firstCase = state.cases[0];
  if (!firstCase) {
    setStatus("No local histology images found.", true);
    return;
  }

  elements.caseSelect.value = firstCase.id;
  await loadCase(firstCase.id);
  await populateConcepts(firstCase.id, firstCase.default_concept_id);
}

function activateTab(tabName) {
  document.querySelectorAll(".panel-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".panel-section").forEach((section) => {
    section.classList.toggle("active", section.dataset.tab === tabName);
  });
}

function updateStatusZoom() {
  if (!viewer.isOpen()) {
    elements.statusZoom.textContent = "Zoom: --";
    return;
  }
  elements.statusZoom.textContent = `Zoom: ${viewer.viewport.getZoom(true).toFixed(2)}x`;
}

elements.annotCanvas.addEventListener("mousedown", (event) => {
  if (state.activeTool === "pan" || !viewer.isOpen()) {
    return;
  }
  state.isDrawing = true;
  const bounds = elements.annotCanvas.getBoundingClientRect();
  const imagePoint = canvasToImage(event.clientX - bounds.left, event.clientY - bounds.top);
  if (!imagePoint) {
    return;
  }
  if (state.activeTool === "bbox") {
    state.drawStart = imagePoint;
  }
  if (state.activeTool === "freehand") {
    state.freehandPoints = [imagePoint];
  }
});

elements.annotCanvas.addEventListener("mousemove", (event) => {
  if (!state.isDrawing || !viewer.isOpen()) {
    return;
  }
  const bounds = elements.annotCanvas.getBoundingClientRect();
  const imagePoint = canvasToImage(event.clientX - bounds.left, event.clientY - bounds.top);
  if (!imagePoint) {
    return;
  }
  if (state.activeTool === "freehand") {
    state.freehandPoints.push(imagePoint);
  }
  redrawAnnotations(imagePoint);
});

elements.annotCanvas.addEventListener("mouseup", (event) => {
  if (!state.isDrawing || !viewer.isOpen()) {
    return;
  }
  state.isDrawing = false;
  const bounds = elements.annotCanvas.getBoundingClientRect();
  const imagePoint = canvasToImage(event.clientX - bounds.left, event.clientY - bounds.top);

  if (state.activeTool === "bbox" && state.drawStart && imagePoint) {
    const x = Math.min(state.drawStart.x, imagePoint.x);
    const y = Math.min(state.drawStart.y, imagePoint.y);
    const w = Math.abs(imagePoint.x - state.drawStart.x);
    const h = Math.abs(imagePoint.y - state.drawStart.y);
    if (w > 5 && h > 5) {
      addAnnotation({
        id: `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        type: "bbox",
        color: getNextColor(),
        name: `Region ${state.annotations.length + 1}`,
        visible: true,
        rect: { x, y, w, h },
      });
    }
    state.drawStart = null;
  }

  if (state.activeTool === "freehand" && state.freehandPoints.length > 3) {
    addAnnotation({
      id: `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      type: "freehand",
      color: getNextColor(),
      name: `Region ${state.annotations.length + 1}`,
      visible: true,
      points: [...state.freehandPoints],
    });
    state.freehandPoints = [];
  }

  redrawAnnotations();
});

elements.annotCanvas.addEventListener("mouseleave", () => {
  if (state.isDrawing && state.activeTool === "freehand" && state.freehandPoints.length > 3) {
    addAnnotation({
      id: `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      type: "freehand",
      color: getNextColor(),
      name: `Region ${state.annotations.length + 1}`,
      visible: true,
      points: [...state.freehandPoints],
    });
  }
  state.isDrawing = false;
  state.drawStart = null;
  state.freehandPoints = [];
  redrawAnnotations();
});

elements.annotSave.addEventListener("click", async () => {
  try {
    await saveAnnotations();
  } catch (error) {
    setStatus("Failed to save annotations.", true);
  }
});

elements.annotExport.addEventListener("click", () => {
  if (!state.currentCase) {
    return;
  }
  const blob = new Blob([JSON.stringify(state.annotations, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${state.currentCase.id}.annotations.json`;
  link.click();
  URL.revokeObjectURL(url);
});

elements.annotImportInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file || !state.currentCase) {
    return;
  }
  try {
    const imported = JSON.parse(await file.text());
    if (!Array.isArray(imported)) {
      throw new Error("Expected a JSON array.");
    }
    state.annotations = imported;
    state.nextColorIndex = state.annotations.length;
    renderAnnotationList();
    redrawAnnotations();
    await saveAnnotations();
    setStatus("Annotations imported.");
  } catch (error) {
    setStatus("Invalid annotation file.", true);
  } finally {
    event.target.value = "";
  }
});

elements.annotToggleAll.addEventListener("click", () => {
  const allVisible = state.annotations.every((annotation) => annotation.visible);
  state.annotations.forEach((annotation) => {
    annotation.visible = !allVisible;
  });
  renderAnnotationList();
  redrawAnnotations();
});

elements.caseSelect.addEventListener("change", async () => {
  try {
    removeHeatmapOverlay();
    removeSelectedPatchOverlay();
    await loadCase(elements.caseSelect.value);
    await populateConcepts(elements.caseSelect.value);
  } catch (error) {
    console.error(error);
    setStatus("Failed to load histology image.", true);
  }
});

elements.conceptSelect.addEventListener("change", async () => {
  try {
    await loadConcept(elements.conceptSelect.value);
  } catch (error) {
    console.error(error);
    setStatus("Failed to load potential concept.", true);
  }
});

elements.heatmapToggle.addEventListener("click", () => {
  state.heatmapVisible = !state.heatmapVisible;
  elements.heatmapToggle.classList.toggle("active", state.heatmapVisible);
  if (state.heatmapVisible) {
    applyHeatmapOverlay();
  } else {
    removeHeatmapOverlay();
  }
});

elements.opacitySlider.addEventListener("input", () => {
  const value = Number(elements.opacitySlider.value);
  elements.opacityLabel.textContent = `${value}%`;
  setHeatmapOpacity(value / 100);
});

document.querySelectorAll(".panel-tab").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

document.getElementById("toolPan").addEventListener("click", () => setActiveTool("pan"));
document.getElementById("toolBbox").addEventListener("click", () => setActiveTool("bbox"));
document.getElementById("toolFreehand").addEventListener("click", () => setActiveTool("freehand"));
document.getElementById("toolZoomIn").addEventListener("click", () => {
  viewer.viewport.zoomBy(2);
  viewer.viewport.applyConstraints();
});
document.getElementById("toolZoomOut").addEventListener("click", () => {
  viewer.viewport.zoomBy(0.5);
  viewer.viewport.applyConstraints();
});
document.getElementById("toolFitScreen").addEventListener("click", () => {
  viewer.viewport.goHome();
});
elements.toolPanel.addEventListener("click", () => {
  elements.rightPanel.classList.toggle("collapsed");
  elements.toolPanel.classList.toggle("active");
});

viewer.addHandler("open", () => {
  resizeCanvas();
  redrawAnnotations();
  updateStatusZoom();
  applyHeatmapOverlay();
});

viewer.addHandler("animation", () => {
  redrawAnnotations();
  updateStatusZoom();
});

viewer.addHandler("resize", () => {
  resizeCanvas();
  redrawAnnotations();
});

window.addEventListener("resize", () => {
  resizeCanvas();
  redrawAnnotations();
});

new OpenSeadragon.MouseTracker({
  element: viewer.element,
  moveHandler: (event) => {
    if (!viewer.isOpen() || !state.currentCase) {
      return;
    }
    const viewportPoint = viewer.viewport.pointFromPixel(event.position);
    const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
    const sourceX = imagePoint.x * (state.currentCase.source_width / state.currentCase.viewer_width);
    const sourceY = imagePoint.y * (state.currentCase.source_height / state.currentCase.viewer_height);
    elements.statusCoords.textContent = `Position: (${Math.round(sourceX).toLocaleString()}, ${Math.round(sourceY).toLocaleString()})`;
  },
});

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT" || event.target.isContentEditable) {
    return;
  }
  if (event.key === "+" || event.key === "=") {
    viewer.viewport.zoomBy(1.5);
  }
  if (event.key === "-") {
    viewer.viewport.zoomBy(0.667);
  }
  if (event.key === "0") {
    viewer.viewport.goHome();
  }
  if (event.key === "h" || event.key === "H") {
    elements.heatmapToggle.click();
  }
  if (event.key === "v" || event.key === "V") {
    setActiveTool("pan");
  }
  if (event.key === "b" || event.key === "B") {
    setActiveTool("bbox");
  }
  if (event.key === "f" || event.key === "F") {
    setActiveTool("freehand");
  }
  if (event.key === "p" || event.key === "P") {
    elements.rightPanel.classList.toggle("collapsed");
    elements.toolPanel.classList.toggle("active");
  }
  if (event.key === "Escape") {
    setActiveTool("pan");
  }
});

async function init() {
  resizeCanvas();
  setActiveTool("pan");
  updateStatusZoom();
  try {
    await initializeCases();
  } catch (error) {
    console.error(error);
    setStatus("Failed to initialize the local viewer.", true);
  }
}

init();
