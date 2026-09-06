const id = new URLSearchParams(location.search).get("id");
const $ = value => document.getElementById(value);
let study;
let index = 0;
let saving = false;
let pendingChoice = null;

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
  $("contextImage").src = item.context_url;
  $("contextImage").dataset.contextBox = JSON.stringify(item.context_box);
  $("patchNumber").textContent = `Patch ${index + 1} of ${study.total}`;
  $("progressText").textContent = `${study.completed} of ${study.total} completed`;
  $("progressFill").style.width = `${100 * study.completed / study.total}%`;
  document.querySelectorAll(".answer").forEach(button => {
    button.classList.toggle("selected", button.dataset.value === pendingChoice);
    button.disabled = saving;
  });
  $("choiceReminder").textContent = pendingChoice ? "Answer selected." : "Select one answer to continue.";
  $("previous").disabled = index === 0 || saving;
  $("next").disabled = !pendingChoice || saving;
  $("next").textContent = index === study.total - 1 ? "Save and view results" : "Save and next";
  requestAnimationFrame(updateContextLinks);
}

function updateContextLinks() {
  const pane = document.querySelector(".patch-pane");
  const context = $("contextImage");
  const patch = $("patchImage");
  const svg = $("contextLinks");
  if (!pane || !context || !patch || !svg || !context.getBoundingClientRect().width) return;
  const details = document.querySelector(".context-details");
  if (details && !details.open) { svg.style.display = "none"; return; }
  svg.style.display = "block";
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

function choose(value) {
  if (saving) return;
  pendingChoice = value;
  document.querySelectorAll(".answer").forEach(button => button.classList.toggle("selected", button.dataset.value === value));
  $("choiceReminder").textContent = "Answer selected.";
  $("next").disabled = false;
  $("next").focus();
}

async function saveAndContinue() {
  if (!pendingChoice || saving) return;
  saving = true;
  $("saveState").textContent = "Saving…";
  render();
  try {
    study = await request(`/api/studies/${id}/judgments/${index + 1}`, {
      method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({judgment: pendingChoice}),
    });
    $("saveState").textContent = "Saved";
    if (index < study.total - 1) { index += 1; render(); }
    else location.href = `/study/results?id=${encodeURIComponent(id)}`;
  } catch (error) {
    $("saveState").textContent = "Could not save. Please try again.";
  } finally {
    saving = false;
    if (index < study.total) render();
  }
}

document.querySelectorAll(".answer").forEach(button => button.addEventListener("click", () => choose(button.dataset.value)));
$("previous").addEventListener("click", () => { if (index > 0 && !saving) { index -= 1; $("saveState").textContent = ""; render(); } });
$("next").addEventListener("click", saveAndContinue);
addEventListener("keydown", event => {
  if (["1", "2", "3", "4"].includes(event.key)) choose(["present", "absent", "uncertain", "cannot_assess"][Number(event.key) - 1]);
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
