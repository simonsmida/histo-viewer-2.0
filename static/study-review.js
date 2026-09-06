const id = new URLSearchParams(location.search).get("id");
const $ = value => document.getElementById(value);
let study;
let index = 0;
let saving = false;
let pendingChoice = null;
const ADVANCE_DELAY_MS = 650;

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function render() {
  const item = study.evaluation[index];
  // Keep a newly selected answer visible until it is persisted. Resetting this
  // from the server record here made Save and next appear to do nothing.
  if (!saving) pendingChoice = item.judgment;
  $("pattern").textContent = study.pattern;
  $("patchImage").src = item.image_url;
  const outlines = $("showGuides")?.checked !== false;
  $("contextImage").src = outlines ? item.context_url : (item.context_plain_url || item.context_url);
  $("patchImage").closest(".patch-frame")?.classList.toggle("without-outline", !outlines);
  $("contextImage").dataset.contextBox = JSON.stringify(item.context_box);
  $("patchNumber").textContent = `Patch ${index + 1} of ${study.total}`;
  $("progressText").textContent = `${study.completed} of ${study.total} completed`;
  $("progressFill").style.width = `${100 * study.completed / study.total}%`;
  document.querySelectorAll(".answer").forEach(button => {
    button.classList.toggle("selected", button.dataset.value === pendingChoice);
    button.disabled = saving;
  });
  $("choiceReminder").textContent = pendingChoice ? "Saved." : "Answers save automatically.";
  $("previous").disabled = index === 0 || saving;
  $("next").disabled = saving || index === study.total - 1;
  $("next").textContent = "Next →";
  $("viewResults").disabled = study.completed < study.total || saving;
  $("resultsHelp").textContent = study.completed < study.total ? "Complete all patches to view results." : "Study complete. Results are ready.";
  renderReviewGrid();
  requestAnimationFrame(updateContextLinks);
}

function renderReviewGrid() {
  const grid = $("reviewGrid");
  if (!grid || !study) return;
  grid.replaceChildren();
  study.evaluation.forEach((item, itemIndex) => {
    const tile = document.createElement("button");
    tile.type = "button";
    const selectedJudgment = itemIndex === index && pendingChoice ? pendingChoice : item.judgment;
    const judgmentClass = selectedJudgment || "unanswered";
    tile.className = `review-tile ${judgmentClass}${itemIndex === index ? " current" : ""}`;
    tile.setAttribute("aria-label", `Patch ${itemIndex + 1}: ${selectedJudgment || "not assessed"}`);
    if (itemIndex === index) tile.setAttribute("aria-current", "true");
    const image = document.createElement("img");
    image.src = item.image_url;
    image.alt = `Patch ${itemIndex + 1}`;
    const meta = document.createElement("span");
    meta.className = "review-tile-meta";
    const number = document.createElement("span");
    number.className = "review-tile-number";
    number.textContent = String(itemIndex + 1);
    const judgment = judgmentClass;
    const status = document.createElement("span");
    status.className = `review-tile-status ${judgment}`;
    status.textContent = selectedJudgment ? selectedJudgment[0].toUpperCase() + selectedJudgment.slice(1) : "Not assessed";
    meta.append(number, status);
    tile.append(image, meta);
    tile.addEventListener("click", () => {
      if (saving) return;
      index = itemIndex;
      $("saveState").textContent = "";
      render();
    });
    grid.append(tile);
  });
}

function updateContextLinks() {
  const pane = document.querySelector(".patch-pane");
  const context = $("contextImage");
  const patch = document.querySelector(".patch-frame");
  const svg = $("contextLinks");
  if (!pane || !context || !patch || !svg || !context.getBoundingClientRect().width) return;
  const details = document.querySelector(".context-details");
  if (details && !details.open) { svg.style.display = "none"; return; }
  svg.style.display = "block";
  if (!$("showGuides")?.checked) { svg.style.display = "none"; return; }
  const paneRect = pane.getBoundingClientRect();
  const c = context.getBoundingClientRect();
  const p = patch.getBoundingClientRect();
  let box;
  try { box = JSON.parse(context.dataset.contextBox); } catch { box = {left: .4, top: .4, width: .2, height: .2}; }
  const x = c.left - paneRect.left + box.left * c.width;
  const y = c.top - paneRect.top + box.top * c.height;
  const w = box.width * c.width;
  const h = box.height * c.height;
  const from = [[x, y], [x + w, y], [x, y + h], [x + w, y + h]];
  const to = [[p.left - paneRect.left, p.top - paneRect.top], [p.right - paneRect.left, p.top - paneRect.top], [p.left - paneRect.left, p.bottom - paneRect.top], [p.right - paneRect.left, p.bottom - paneRect.top]];
  svg.setAttribute("viewBox", `0 0 ${pane.clientWidth} ${pane.clientHeight}`);
  svg.setAttribute("width", pane.clientWidth); svg.setAttribute("height", pane.clientHeight);
  svg.innerHTML = from.map((point, i) => `<line x1="${point[0]}" y1="${point[1]}" x2="${to[i][0]}" y2="${to[i][1]}" />`).join("");
}

function updateStudyDisplay() {
  if (!study) return;
  const item = study.evaluation[index];
  const outlines = $("showGuides")?.checked !== false;
  $("contextImage").src = outlines ? item.context_url : item.context_plain_url;
  $("patchImage").closest(".patch-frame")?.classList.toggle("without-outline", !outlines);
  updateContextLinks();
}

async function choose(value) {
  if (saving || !study) return;
  pendingChoice = value;
  document.querySelectorAll(".answer").forEach(button => button.classList.toggle("selected", button.dataset.value === value));
  saving = true;
  $("choiceReminder").textContent = "Saving…";
  render();
  try {
    study = await request(`/api/studies/${id}/judgments/${index + 1}`, {
      method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({judgment: value}),
    });
    $("saveState").textContent = "Saved";
    // Leave the chosen answer visible briefly so the expert can register the
    // color-coded confirmation before the next patch is shown.
    if (index < study.total - 1) {
      await new Promise(resolve => setTimeout(resolve, ADVANCE_DELAY_MS));
      index += 1; pendingChoice = null;
    }
  } catch (error) {
    $("saveState").textContent = "Could not save. Please try again.";
  } finally {
    saving = false;
    render();
  }
}

document.querySelectorAll(".answer").forEach(button => button.addEventListener("click", () => choose(button.dataset.value)));
$("previous").addEventListener("click", () => { if (index > 0 && !saving) { index -= 1; $("saveState").textContent = ""; render(); } });
$("next").addEventListener("click", () => {
  if (saving) return;
  if (index < study.total - 1) { index += 1; render(); }
});
$("viewResults").addEventListener("click", () => {
  if (!study || saving || study.completed < study.total) return;
  location.href = `/study/results?id=${encodeURIComponent(id)}`;
});
$("toggleReviewGrid").addEventListener("click", () => {
  const grid = $("reviewGrid");
  const overview = $("reviewOverview");
  const button = $("toggleReviewGrid");
  const hidden = overview.hidden;
  overview.hidden = !hidden;
  button.textContent = hidden ? "Hide patches" : "Show patches";
  button.setAttribute("aria-expanded", String(hidden));
});
try {
  study = await request(`/api/studies/${id}`);
  const unfinished = study.evaluation.findIndex(item => !item.judgment);
  index = unfinished < 0 ? study.total - 1 : unfinished;
  render();
} catch (error) {
  document.querySelector("main").innerHTML = '<div class="card error">This study could not be loaded.</div>';
}

addEventListener("resize", updateContextLinks);
$("contextImage")?.addEventListener("load", updateContextLinks);
$("patchImage")?.addEventListener("load", updateContextLinks);
document.querySelector(".context-details")?.addEventListener("toggle", updateContextLinks);
$("showGuides")?.addEventListener("change", updateStudyDisplay);
