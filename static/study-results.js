const id = new URLSearchParams(location.search).get("id");
const $ = value => document.getElementById(value);
const NS = "http://www.w3.org/2000/svg";

async function getResults() {
  const response = await fetch(`/api/studies/${id}/results`);
  if (!response.ok) throw new Error("Could not load results");
  return response.json();
}

const pct = value => value == null ? "—" : `${Math.round(value * 100)}%`;
const num = value => value == null ? "—" : value.toFixed(3);

function node(svg, name, attributes = {}, text = "") {
  const element = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  element.textContent = text;
  svg.append(element);
  return element;
}

function axes(svg, xlabel, ylabel) {
  svg.setAttribute("viewBox", "0 0 440 260");
  for (let i = 0; i <= 4; i++) {
    const y = 210 - i * 45;
    node(svg, "line", {x1: 48, y1: y, x2: 424, y2: y, class: "grid"});
    node(svg, "text", {x: 39, y: y + 4, "text-anchor": "end"}, `${i * 25}%`);
  }
  node(svg, "line", {x1: 48, y1: 30, x2: 48, y2: 210, class: "axis"});
  node(svg, "line", {x1: 48, y1: 210, x2: 424, y2: 210, class: "axis"});
  node(svg, "text", {x: 236, y: 258, "text-anchor": "middle"}, xlabel);
  node(svg, "text", {x: 4, y: 120, transform: "rotate(-90 4 120)", "text-anchor": "middle"}, ylabel);
}

function activation(svg, data, prevalence) {
  axes(svg, "Activation level", "Matching patches");
  const colors = {zero: "#e2e8f0", low: "#bfdbfe", medium: "#60a5fa", high: "#2563eb", top: "#1e3a8a"};
  const width = 52, gap = 22;
  data.forEach((item, index) => {
    const x = 67 + index * (width + gap);
    const value = item.matching_fraction;
    const height = value == null ? 0 : value * 180;
    node(svg, "rect", {x, y: 210 - height, width, height, rx: 3,
      fill: value == null ? "#e3e7ed" : (colors[item.stratum] || "#2563eb")});
    node(svg, "text", {x: x + width / 2, y: 228, "text-anchor": "middle"},
      item.stratum[0].toUpperCase() + item.stratum.slice(1));
    node(svg, "text", {x: x + width / 2, y: value == null ? 200 : Math.max(25, 202 - height), "text-anchor": "middle"},
      value == null ? "n/a" : pct(value));
    node(svg, "text", {x: x + width / 2, y: 241, "text-anchor": "middle"}, `n=${item.assessable_n}`);
  });
  if (prevalence != null) {
    const y = 210 - prevalence * 180;
    node(svg, "line", {x1: 48, y1: y, x2: 424, y2: y, class: "baseline"});
  }
}

function precisionRecall(svg, data, baseline) {
  axes(svg, "Recall", "Precision");
  for (let i = 0; i <= 4; i++) node(svg, "text", {x: 48 + i * 94, y: 228, "text-anchor": "middle"}, `${i * 25}%`);
  if (baseline != null) node(svg, "line", {x1: 48, y1: 210 - baseline * 180, x2: 424, y2: 210 - baseline * 180, class: "baseline"});
  if (data.length) node(svg, "polyline", {points: data.map(item => `${48 + item.recall * 376},${210 - item.precision * 180}`).join(" "), class: "data"});
}

try {
  const data = await getResults();
  $("title").textContent = `Pattern: ${data.pattern}`;
  $("subtitle").textContent = `${data.case_label} · ${data.reviewer}`;
  $("precision").textContent = pct(data.precision_at_20);
  $("precisionNote").textContent = `Based on ${data.precision_n} patches marked Present or Absent.`;
  $("auprc").textContent = num(data.auprc);
  $("baseline").textContent = `Chance reference (prevalence): ${pct(data.prevalence)}`;
  $("completed").textContent = `${data.completed}/${data.total}`;
  $("pattern").textContent = data.pattern;
  $("meta").textContent = `Discovery assessment: ${data.assessment.replace("_", " ")} · confidence: ${data.confidence}`;
  activation($("activation"), data.activation_curve, data.prevalence);
  $("activation").nextElementSibling.textContent = "Darker blue indicates higher activation. Dashed gray line shows overall validation prevalence.";
  precisionRecall($("pr"), data.pr_curve, data.prevalence);
  const colors = {present: "#087f5b", absent: "#c33b48", uncertain: "#d89016", cannot_assess: "#8993a5", unreviewed: "#dfe4ec"};
  for (const [key, color] of Object.entries(colors)) {
    const count = data.judgment_counts[key];
    if (!count) continue;
    const segment = document.createElement("span");
    segment.style.cssText = `width:${100 * count / data.total}%;background:${color}`;
    segment.title = `${key}: ${count}`;
    $("distribution").append(segment);
    $("distributionLegend").insertAdjacentHTML("beforeend", `<span><i class="dot" style="background:${color}"></i>${key.replace("_", " ")} · ${count}</span>`);
  }
} catch (error) {
  $("root").innerHTML = '<div class="card error">These results could not be loaded.</div>';
}
