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
