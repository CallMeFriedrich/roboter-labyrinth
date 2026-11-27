// Statistics page (iPad next to the exhibit): leaderboards, time by age, numbers of the day.
// Listens on the visitor WebSocket (state, live run) and reloads /api/stats whenever a run is added.
import { connect } from "/static/shared/ws.js";
import { el, formatTime, timeParts } from "/static/shared/format.js";
import { loadLogo } from "/static/shared/logo.js";
import { createPlayer, forgetMap, loadMap, loadReplay } from "/static/shared/replay.js";

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const NS = "http://www.w3.org/2000/svg";
const MODES = ["slow", "normal", "turbo"];
const MODE_LABEL = { slow: "Langsam", normal: "Normal", turbo: "Turbo" };
// Marker shapes (secondary encoding next to colour): triangle, circle, diamond, all ~10 px.
const SHAPE = {
  slow: "M0,-5.8 L5.2,3.6 L-5.2,3.6 Z",
  normal: "M5,0 A5,5 0 1,1 -5,0 A5,5 0 1,1 5,0 Z",
  turbo: "M0,-6 L6,0 L0,6 L-6,0 Z",
};
const AGE_GROUPS = [
  { label: "bis 12", min: 0, max: 12 }, { label: "13–15", min: 13, max: 15 },
  { label: "16–18", min: 16, max: 18 }, { label: "19–29", min: 19, max: 29 },
  { label: "30–49", min: 30, max: 49 }, { label: "50+", min: 50, max: 200 },
];

let stats = null;            // last /api/stats answer
let runsRev = null;
let labRev = null;
let liveBase = null;         // performance.now() when the live run was at 0 ms
let seenRuns = null;         // keys of runs already drawn (to mark new ones)
let newestKey = null;
let lastState = null;
// Shown top right while nobody plays: changes every few seconds.
const WAITING = [
  "Wer traut sich als Nächstes?",
  "Der Roboter wartet auf dich",
  "Freie Bahn für die nächste Bestzeit",
  "Bereit für eine neue Runde",
  "Schaffst du die Maschine?",
];
let waitingIndex = 0;
const RETURN_IDLE_MS = 45_000;     // overlays close by themselves: back to the statistics
const RETURN_AFTER_END_MS = 12_000;
const PLAY = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.8v8.4L10 6z"/></svg>';

// ------------------------------------------------------------------ scaling
function fit() {
  const scale = Math.min(window.innerWidth / 1180, window.innerHeight / 820);
  stage.style.transform = `scale(${scale})`;
}
window.addEventListener("resize", fit);
fit();

// ------------------------------------------------------------------- socket
connect("/ws/visitor", {
  onOpen() { $("pause").hidden = true; },
  onClose() { $("pause").hidden = false; },
  onMessage(message) {
    if (message.type !== "state") return;
    const display = message.display || {};
    document.documentElement.classList.toggle("theme-light", display.theme === "light");
    if (labRev !== message.labyrinth_rev) { labRev = message.labyrinth_rev; loadLogo($("logo")); forgetMap(); }
    const before = lastState;
    lastState = message;
    renderLive(message);
    // The requested replay starts on the robot: close everything, the live pill shows it.
    if (message.state === "AUTO_RUN" && before && before.state !== "AUTO_RUN") closeOverlays();
    if (!$("viewer").hidden) updateRealButton();
    if (message.runs_rev !== runsRev) { runsRev = message.runs_rev; refresh(); }
  },
});

async function refresh() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) return;
    stats = await response.json();
    render();
  } catch { /* next state message tries again */ }
}

// --------------------------------------------------------------------- live
function renderLive(state) {
  const live = $("live");
  const run = state.run;
  const driving = run && ["ARMED", "RUNNING", "COUNTDOWN", "MOVING_TO_START", "AUTO_RUN"].includes(state.state);
  live.classList.toggle("is-running", Boolean(driving));
  if (!driving) {
    $("live-text").textContent = idleText(state);
    $("live-time").textContent = "";
    liveBase = null;
    return;
  }
  const who = run.kind === "robot" ? "Der Roboter fährt"
    : run.kind === "replay" ? `Wiederholung: ${run.name}`
    : `${run.name} fährt · ${MODE_LABEL[state.speed_mode] || "Normal"}`;
  $("live-text").textContent = who;
  liveBase = run.running ? performance.now() - run.elapsed_ms : null;
  if (!run.running) $("live-time").textContent = formatTime(run.elapsed_ms);
}

function idleText(state) {
  if (state.state === "AUTO_REQUESTED") {
    return state.replay ? `Wiederholung von ${state.replay.name} wartet auf Freigabe` : "Der Roboter wartet auf Freigabe";
  }
  if (["DISCONNECTED", "ERROR"].includes(state.state)) return "Kurze Pause";
  if (state.show) return "Der Roboter vertreibt sich die Zeit";
  if (state.result) return `${state.result.name} ist im Ziel`;
  if (["RETURNING_HOME", "ABORTING", "FINISHED"].includes(state.state)) return "Gleich geht es weiter";
  return WAITING[waitingIndex % WAITING.length];
}
setInterval(() => {
  waitingIndex += 1;
  if (lastState && !$("live").classList.contains("is-running")) {
    const text = $("live-text");
    text.animate([{ opacity: 1 }, { opacity: 0 }, { opacity: 1 }], { duration: 600 });
    setTimeout(() => { text.textContent = idleText(lastState); }, 300);
  }
}, 7000);

function tick() {
  if (liveBase !== null) {
    const { main, fraction } = timeParts(performance.now() - liveBase);
    $("live-time").textContent = main + fraction;
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// ------------------------------------------------------------------- render
const ageOf = (run) => stats.year - run.birth_year;
const keyOf = (run) => `${run.at}|${run.name}|${run.time_ms}`;

function render() {
  const finished = stats.runs.filter((r) => r.status === "finished" && r.time_ms !== null);
  const keys = new Set(finished.map(keyOf));
  const fresh = seenRuns ? finished.filter((r) => !seenRuns.has(keyOf(r))) : [];
  if (fresh.length) newestKey = keyOf(fresh[fresh.length - 1]);
  seenRuns = keys;

  $("profile").textContent = `Profil „${stats.profile.name}“`;
  renderTiles(finished);
  renderLegend();
  renderScatter(finished);
  renderAges(finished);
  renderBoards(fresh);
}

function renderTiles(finished) {
  const aborted = stats.runs.filter((r) => r.status === "aborted").length;
  const total = finished.length + aborted;
  $("t-finished").textContent = finished.length;
  $("t-finished-sub").textContent = MODES.map((m) =>
    `${MODE_LABEL[m]} ${finished.filter((r) => r.mode === m).length}`).join(" · ");
  $("t-aborted").textContent = aborted;
  $("t-aborted-sub").textContent = total ? `${Math.round((finished.length / total) * 100)} % kommen ins Ziel` : "";
  const ages = stats.runs.map(ageOf).filter((a) => a > 0 && a < 120);
  if (ages.length) {
    const avg = ages.reduce((a, b) => a + b, 0) / ages.length;
    $("t-age").textContent = `${avg.toLocaleString("de-DE", { maximumFractionDigits: 1 })} Jahre`;
    $("t-age-sub").textContent = `Jüngste ${Math.min(...ages)} · Älteste ${Math.max(...ages)}`;
  } else {
    $("t-age").textContent = "–";
    $("t-age-sub").textContent = "";
  }
  $("t-robot").textContent = formatTime(stats.robot_best_ms);
  $("t-robot-sub").textContent = stats.robot_best_ms ? "Kürzester Weg, ganz allein" : "Noch nicht gefahren";
}

function renderLegend() {
  const legend = $("legend");
  if (legend.children.length) return;
  for (const mode of MODES) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "-6 -6 12 12");
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", SHAPE[mode]);
    path.setAttribute("fill", `var(--c-${mode})`);
    svg.append(path);
    legend.append(el("span", { class: "legend-item" }, svg, MODE_LABEL[mode]));
  }
}

// ------------------------------------------------------------ scatter chart
function niceStep(range, target) {
  const raw = range / target;
  const pow = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * pow >= raw) return m * pow;
  return 10 * pow;
}

const TIME_STEPS = [5, 10, 15, 20, 30, 60, 120, 300].map((s) => s * 1000);
function timeTick(ms) {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function svgNode(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function renderScatter(finished) {
  const box = $("scatter");
  const width = box.clientWidth, height = box.clientHeight;
  if (!width || !height) return;
  box.querySelector(".empty-note")?.remove();
  let svg = box.querySelector("svg");
  if (!svg) {
    svg = svgNode("svg");
    svg.append(svgNode("g", { class: "axis grid-layer" }), svgNode("g", { class: "dots" }),
               svgNode("g", { class: "labels" }));
    box.append(svg);
  }
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const [gridLayer, dotLayer, labelLayer] = svg.children;

  if (!finished.length) {
    gridLayer.replaceChildren();
    dotLayer.replaceChildren();
    labelLayer.replaceChildren();
    box.append(el("p", { class: "empty-note", text: "Noch keine Zeiten. Der erste Punkt gehört dir." }));
    return;
  }

  // Room for the time labels left and two label lines under the plot (ages, axis title).
  const m = { left: 50, right: 16, top: 12, bottom: 46 };
  const inset = 12;                         // the first age tick stands clear of the time labels
  const ages = finished.map(ageOf);
  let a0 = Math.max(0, Math.min(...ages) - 1), a1 = Math.max(...ages) + 1;
  if (a1 - a0 < 10) { const mid = (a0 + a1) / 2; a0 = Math.max(0, mid - 5); a1 = a0 + 10; }
  const aStep = niceStep(a1 - a0, 6);
  a0 = Math.floor(a0 / aStep) * aStep;
  a1 = Math.ceil(a1 / aStep) * aStep;
  const tMax = Math.max(...finished.map((r) => r.time_ms)) * 1.08;
  const tStep = TIME_STEPS.find((s) => tMax / s <= 5) || 600_000;
  const t1 = Math.ceil(tMax / tStep) * tStep;
  const x = (age) => m.left + inset + ((age - a0) / (a1 - a0)) * (width - m.left - m.right - inset);
  const y = (ms) => m.top + (ms / t1) * (height - m.top - m.bottom);   // 0 at the top: faster is higher up

  // Grid and axes: hairlines, recessive.
  const grid = [];
  for (let t = 0; t <= t1 + 1; t += tStep) {
    grid.push(svgNode("line", { class: "gridline", x1: m.left, x2: width - m.right, y1: y(t), y2: y(t) }));
    const label = svgNode("text", { x: m.left - 8, y: y(t) + 4, "text-anchor": "end" });
    label.textContent = timeTick(t);
    grid.push(label);
  }
  for (let a = a0; a <= a1 + 0.001; a += aStep) {
    const label = svgNode("text", { x: x(a), y: height - m.bottom + 20, "text-anchor": "middle" });
    label.textContent = a;
    grid.push(label);
  }
  grid.push(svgNode("line", { class: "baseline", x1: m.left, x2: width - m.right,
                              y1: height - m.bottom, y2: height - m.bottom }));
  const title = svgNode("text", { class: "axis-title", x: width - m.right, y: height - 4, "text-anchor": "end" });
  title.textContent = "Alter in Jahren";
  grid.push(title);
  gridLayer.replaceChildren(...grid);

  // Dots: keyed by run so existing ones glide to new places when the scale changes.
  const existing = new Map([...dotLayer.children].map((node) => [node.dataset.key, node]));
  const keep = new Set();
  // Draw the newest last so it sits on top.
  const order = [...finished].sort((p, q) => (keyOf(p) === newestKey) - (keyOf(q) === newestKey));
  for (const run of order) {
    const key = keyOf(run);
    keep.add(key);
    let node = existing.get(key);
    if (!node) {
      node = svgNode("g", { class: "dot" });
      node.dataset.key = key;
      node.append(svgNode("circle", { class: "dot-hit", r: 14 }),
                  svgNode("path", { d: SHAPE[run.mode] || SHAPE.normal, fill: `var(--c-${run.mode})` }));
      node.addEventListener("pointerdown", (event) => { event.stopPropagation(); showTip(run, node); });
      node.addEventListener("pointerenter", () => showTip(run, node));
      node.addEventListener("pointerleave", hideTip);
      dotLayer.append(node);
    }
    node.style.transform = `translate(${x(ageOf(run))}px, ${y(run.time_ms)}px)`;
    node.classList.toggle("is-new", key === newestKey);
    if (key === newestKey) dotLayer.append(node);
  }
  for (const [key, node] of existing) if (!keep.has(key)) node.remove();

  // One direct label: the newest run (the person who just played looks for their dot).
  labelLayer.replaceChildren();
  const newest = finished.find((r) => keyOf(r) === newestKey);
  if (newest) {
    const px = x(ageOf(newest)), py = y(newest.time_ms);
    const right = px < width - 140;
    const label = svgNode("text", { x: px + (right ? 12 : -12), y: py + 4, "text-anchor": right ? "start" : "end",
                                    class: "dot-label" });
    label.textContent = `${newest.name} · ${formatTime(newest.time_ms)}`;
    label.setAttribute("style", "font-size:12px;font-weight:600;fill:var(--label)");
    labelLayer.append(label);
  }
}

function showTip(run, node) {
  const tip = $("tip");
  tip.replaceChildren(el("strong", { text: run.name }),
    el("span", { text: `${ageOf(run)} Jahre · ${MODE_LABEL[run.mode]} · ` }),
    el("span", { class: "num", text: formatTime(run.time_ms) }));
  tip.hidden = false;
  const card = tip.parentElement.getBoundingClientRect();
  const dot = node.getBoundingClientRect();
  const scale = card.width / tip.parentElement.offsetWidth || 1;
  const left = (dot.left + dot.width / 2 - card.left) / scale;
  const top = (dot.top - card.top) / scale;
  tip.style.left = `${Math.min(left + 12, tip.parentElement.offsetWidth - tip.offsetWidth - 8)}px`;
  tip.style.top = `${Math.max(8, top - tip.offsetHeight - 6)}px`;
}
function hideTip() { $("tip").hidden = true; }
document.addEventListener("pointerdown", hideTip);

// ------------------------------------------------- age groups (small multiples)
function renderAges(finished) {
  const box = $("ages");
  const best = {};                        // best[mode][groupIndex] = run
  for (const mode of MODES) {
    best[mode] = AGE_GROUPS.map((g) => finished
      .filter((r) => r.mode === mode && ageOf(r) >= g.min && ageOf(r) <= g.max)
      .sort((p, q) => p.time_ms - q.time_ms)[0] || null);
  }
  const cells = [el("span", {})];
  for (const mode of MODES) {
    cells.push(el("span", { class: "ages-head" }, el("span", { class: "mark", dataset: { mode } }), MODE_LABEL[mode]));
  }
  // Own scale per column: the longest best time of that speed fills about two thirds.
  const scale = Object.fromEntries(MODES.map((mode) =>
    [mode, Math.max(1, ...best[mode].filter(Boolean).map((r) => r.time_ms))]));
  AGE_GROUPS.forEach((group, i) => {
    cells.push(el("span", { class: "ages-label", text: group.label }));
    for (const mode of MODES) {
      const run = best[mode][i];
      if (!run) { cells.push(el("span", { class: "ages-cell" }, el("span", { class: "bar-none", text: "–" }))); continue; }
      const bar = el("span", { class: "bar", dataset: { mode } });
      const pct = Math.max(4, (run.time_ms / scale[mode]) * 62);
      cells.push(el("span", { class: "ages-cell", title: `${run.name}, ${ageOf(run)} Jahre` },
        bar, el("span", { class: "bar-value", text: formatTime(run.time_ms) })));
      requestAnimationFrame(() => { bar.style.width = `${pct}%`; });
    }
  });
  // Keep old bar widths for a smooth transition: copy widths before replacing.
  const old = [...box.querySelectorAll(".bar")].map((b) => b.style.width);
  box.replaceChildren(...cells);
  [...box.querySelectorAll(".bar")].forEach((b, i) => { if (old[i]) b.style.width = old[i]; });
}

// ---------------------------------------------------------------- boards
function renderBoards(fresh) {
  const freshKeys = new Set(fresh.map(keyOf));
  for (const mode of MODES) {
    const list = document.querySelector(`[data-board="${mode}"]`);
    const entries = (stats.boards[mode] || []).slice(0, 5);
    if (!entries.length) {
      list.replaceChildren(el("li", { class: "board-empty", text: "Noch keine Zeiten." }));
      continue;
    }
    list.replaceChildren(...entries.map((e) => {
      const run = stats.runs.find((r) => r.name === e.name && r.time_ms === e.time_ms && r.mode === mode);
      const isNew = run && freshKeys.has(keyOf(run));
      const full = stats.runs.find((r) => r.id === e.run_id);
      const play = el("button", { type: "button", class: "row-play", "aria-label": `Lauf von ${e.name} abspielen`,
                                  disabled: !(full && full.replay), onclick: () => openViewer(e.run_id) });
      play.innerHTML = PLAY;
      return el("li", { class: `board-row${isNew ? " is-new" : ""}` },
        el("span", { class: "rank num", text: e.rank }),
        el("span", { class: "name", text: e.name }),
        el("span", { class: "age num", text: `${stats.year - e.birth_year} J.` }),
        el("span", { class: "time num", text: formatTime(e.time_ms) }), play);
    }));
  }
}

window.addEventListener("resize", () => { if (stats) render(); });

// =============================================================== overlays
// Everything returns to the statistics by itself: after 45 s without a touch,
// and 12 s after a replay has ended.
let returnTimer = 0;
function armReturn(ms = RETURN_IDLE_MS) {
  clearTimeout(returnTimer);
  returnTimer = setTimeout(closeOverlays, ms);
}
function closeOverlays() {
  clearTimeout(returnTimer);
  player?.stop();
  $("recent").hidden = true;
  $("viewer").hidden = true;
  viewing = null;
}
for (const button of document.querySelectorAll("[data-close]")) button.addEventListener("click", closeOverlays);
for (const id of ["recent", "viewer"]) {
  $(id).addEventListener("pointerdown", (event) => {
    if (event.target === $(id)) closeOverlays();         // tap next to the card
    else if (!(id === "viewer" && playing)) armReturn();
  });
}

const STATUS_TEXT = { wall: "Wand berührt", aborted: "Aufgegeben" };
function resultText(run) {
  if (run.status === "finished") return formatTime(run.time_ms);
  return STATUS_TEXT[run.end] || "Nicht im Ziel";
}
function since(iso) {
  const d = new Date(String(iso || "").replace(" ", "T"));   // Safari needs the T
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return "";
  if (minutes < 1) return "gerade eben";
  if (minutes < 60) return `vor ${minutes} min`;
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} Uhr`;
}

$("open-recent").addEventListener("click", () => {
  if (!stats) return;
  const recent = [...stats.runs].reverse().slice(0, 8);
  const list = $("recent-list");
  if (!recent.length) {
    list.replaceChildren(el("li", { class: "recent-empty", text: "Noch keine Versuche. Der erste kann gleich losgehen." }));
  } else {
    list.replaceChildren(...recent.map((run) => {
      const watch = el("button", { type: "button", class: "pill-btn", disabled: !run.replay,
                                   onclick: () => openViewer(run.id) });
      watch.innerHTML = PLAY + " Ansehen";
      const real = el("button", { type: "button", class: "pill-btn is-real", text: "Am Roboter",
                                  disabled: !run.replay || !canRequest(), onclick: () => requestReal(run.id, real) });
      return el("li", { class: "recent-row" },
        el("span", { class: "mark", dataset: { mode: run.mode } }),
        el("span", { class: "recent-name" }, run.name,
          el("small", { text: `${stats.year - run.birth_year} Jahre · ${MODE_LABEL[run.mode] || "Normal"}` })),
        el("span", { class: "recent-when", text: since(run.at) }),
        el("span", { class: `recent-result${run.status === "finished" ? "" : " is-out"}`, text: resultText(run) }),
        el("span", { class: "recent-actions" }, watch, real));
    }));
  }
  $("viewer").hidden = true;
  $("recent").hidden = false;
  armReturn();
});

// --------------------------------------------------------------- viewer
let player = null;
let viewing = null;          // replay data shown in the viewer
let playing = false;

function canRequest() {
  return Boolean(lastState && lastState.state === "IDLE" && lastState.can_start);
}
function updateRealButton() {
  const button = $("viewer-real");
  if (!viewing) return;
  button.disabled = !canRequest();
  if (lastState?.state === "AUTO_REQUESTED" && lastState.replay?.run_id === viewing.run_id) {
    $("viewer-note").textContent = "Angefragt. Ein Betreuer gibt den Roboter gleich frei.";
  }
}

async function requestReal(runId, button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/runs/${runId}/replay-request`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || "Das geht gerade nicht.");
    $("viewer-note").textContent = "Angefragt. Ein Betreuer gibt den Roboter gleich frei.";
    button.textContent = "Angefragt";
    armReturn(5000);                          // back to the statistics: the live pill shows the rest
  } catch (error) {
    $("viewer-note").textContent = error.message;
    button.disabled = false;
  }
}

async function openViewer(runId) {
  armReturn();
  let replay, lab;
  try {
    [replay, lab] = await Promise.all([loadReplay(runId), loadMap()]);
  } catch (error) {
    return;
  }
  if (!lab) return;
  if (!player) {
    player = createPlayer($("viewer-map"), {
      onTime(text, phase) {
        const clock = $("viewer-clock");
        clock.textContent = text;
        clock.classList.toggle("is-before", phase === "before");
      },
      onEnd() {
        playing = false;
        const end = viewing?.end;
        $("viewer-end").textContent = end === "finished" ? "Im Ziel." : STATUS_TEXT[end] || "";
        $("viewer-end").classList.toggle("is-wall", end === "wall");
        armReturn(RETURN_AFTER_END_MS);
      },
    });
  }
  player.setGeometry(lab);
  viewing = replay;
  $("viewer-name").textContent = replay.name;
  $("viewer-meta").textContent = [`${stats ? stats.year - replay.birth_year : ""} Jahre`,
    MODE_LABEL[replay.mode] || "Normal", replay.status === "finished" ? formatTime(replay.time_ms) : null]
    .filter(Boolean).join(" · ");
  $("viewer-end").textContent = "";
  $("viewer-note").textContent = "";
  $("viewer-real").textContent = "Am echten Roboter";
  updateRealButton();
  $("recent").hidden = true;
  $("viewer").hidden = false;
  playing = true;
  clearTimeout(returnTimer);                  // while it plays, nothing closes
  player.play(replay);
}

$("viewer-again").addEventListener("click", () => {
  if (!viewing || !player) return;
  clearTimeout(returnTimer);
  playing = true;
  $("viewer-end").textContent = "";
  player.play(viewing);
});
$("viewer-real").addEventListener("click", () => { if (viewing) requestReal(viewing.run_id, $("viewer-real")); });
