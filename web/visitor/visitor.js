// Visitor screen: timer, registration, W A S D steering, leaderboard (CLAUDE.md §9.1).
import { connect } from "/static/shared/ws.js";
import { el, formatTime, timeParts } from "/static/shared/format.js";

const $ = (id) => document.getElementById(id);
const stage = $("stage");

const KEY_MAP = {
  KeyW: "w", KeyA: "a", KeyS: "s", KeyD: "d",
  ArrowUp: "w", ArrowLeft: "a", ArrowDown: "s", ArrowRight: "d",
};
const JOG_STATES = new Set(["ARMED", "RUNNING"]);
const PAUSE_STATES = new Set(["DISCONNECTED", "ERROR"]);
const HEARTBEAT_MS = 100;
const FORM_IDLE_MS = 60_000;

let state = null;            // last state message from the server
let control = false;         // this screen may steer (kiosk on the laptop itself)
let online = false;
let timerBase = null;        // performance.now() at which the running timer was at 0
const down = new Set();
let seq = 0;
let lastHighlight = null;    // run id that was already highlighted in the list
let giveUpTimer = 0;
let formIdleTimer = 0;
let countdownTimer = 0;
let countdownShown = null;

// ------------------------------------------------------------------- scaling
function fit() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  stage.style.transform = `scale(${scale})`;
}
window.addEventListener("resize", fit);
fit();

// ---------------------------------------------------------------------- logo
async function loadLogo() {
  try {
    const data = await (await fetch("/api/logo")).json();
    if (!data.paths.length || !data.bounds) return;
    const [x0, y0, x1, y1] = data.bounds;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
    for (const d of data.paths) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      path.setAttribute("fill-rule", "evenodd");
      svg.append(path);
    }
    $("logo").replaceChildren(svg);
  } catch { /* the logo is decoration; the screen works without it */ }
}

// ----------------------------------------------------------------- websocket
const socket = connect("/ws/visitor", {
  onOpen() { online = true; render(); },
  onClose() { online = false; releaseKeys(); render(); },
  onMessage(message) {
    if (message.type === "hello") {
      control = message.control;
      stage.classList.toggle("is-viewer", !control);
    } else if (message.type === "state") {
      const previous = state;
      state = message;
      if (!previous || previous.labyrinth_rev !== state.labyrinth_rev) loadLogo();
      syncTimerBase();
      render(previous);
    } else if (message.type === "error") {
      showFormError(message.message);
    }
  },
});

// --------------------------------------------------------------------- timer
function syncTimerBase() {
  if (state.run && state.run.running) {
    const base = performance.now() - state.run.elapsed_ms;
    // Keep the local base unless it drifts: avoids visible jitter from network delay.
    if (timerBase === null || Math.abs(base - timerBase) > 120) timerBase = base;
  } else {
    timerBase = null;
  }
}

function setTimer(ms) {
  const { main, fraction } = timeParts(ms);
  const mainNode = $("timer-main");
  const fractionNode = $("timer-fraction");
  if (mainNode.textContent !== main) mainNode.textContent = main;
  if (fractionNode.textContent !== fraction) fractionNode.textContent = fraction;
}

function tick() {
  if (timerBase !== null) setTimer(performance.now() - timerBase);
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// ----------------------------------------------------------------- countdown
function showCount(text) {
  const node = $("countdown");
  if (countdownShown === text) return;
  countdownShown = text;
  stage.classList.add("is-counting");
  node.hidden = false;
  node.textContent = text;
  node.classList.remove("is-in", "is-out");
  void node.offsetWidth;                       // restart the animation
  node.classList.add("is-in");
}

function hideCount() {
  clearTimeout(countdownTimer);
  const node = $("countdown");
  if (node.hidden) return;
  countdownShown = null;
  stage.classList.remove("is-counting");
  node.classList.remove("is-in");
  node.classList.add("is-out");
  setTimeout(() => { if (countdownShown === null) node.hidden = true; }, 200);
}

function runCountdown(remainingMs) {
  clearTimeout(countdownTimer);
  const step = () => {
    const left = endAt - performance.now();
    if (left <= 0) return;                     // "Los" is shown when ARMED arrives
    showCount(String(Math.ceil(left / 1000)));
    countdownTimer = setTimeout(step, (left % 1000) || 1000);
  };
  const endAt = performance.now() + remainingMs;
  step();
}

// ------------------------------------------------------------------- render
function statusText(s) {
  switch (s.state) {
    case "IDLE": return s.can_start ? "Steuere den Roboterarm durchs Labyrinth." : "Gleich geht es weiter.";
    case "MOVING_TO_START": return "Der Roboter fährt zum Start …";
    case "COUNTDOWN": return "Mach dich bereit.";
    case "ARMED": return "Die Zeit läuft ab der Startlinie.";
    case "RUNNING": return s.run ? s.run.name : "";
    case "AUTO_REQUESTED": return "Ein Betreuer gibt den Roboter gleich frei …";
    case "AUTO_RUN": return "Der Roboter fährt den kürzesten Weg.";
    case "FINISHED": return s.result ? s.result.name : "";
    case "ABORTING": return s.notice || "Der Roboter fährt zurück …";
    case "RETURNING_HOME":
      if (s.notice) return s.notice;
      if (s.result) return s.result.name;
      if (s.auto_result) return "Das war der kürzeste Weg.";
      return "Der Roboter fährt zurück …";
    default: return "";
  }
}

function render(previous) {
  const paused = !online || !state || PAUSE_STATES.has(state.state);
  $("pause").hidden = !paused;
  if (!state) return;
  const s = state.state;
  stage.dataset.state = s;

  const jog = JOG_STATES.has(s);
  const showResult = Boolean(state.result);
  const idle = s === "IDLE";

  $("status").textContent = statusText(state);
  $("tag").hidden = !(s === "AUTO_RUN" || (s === "RETURNING_HOME" && state.auto_result));

  // Timer
  const timer = $("timer");
  const finalMs = state.result?.time_ms ?? state.auto_result?.time_ms ?? null;
  if (timerBase === null) setTimer(finalMs ?? (state.run ? state.run.elapsed_ms : 0));
  timer.classList.toggle("is-final", finalMs !== null);
  timer.classList.toggle("is-dim", finalMs === null && !(state.run && state.run.running));

  // Countdown overlay
  if (s === "COUNTDOWN" && state.countdown_ms !== null) {
    if (!previous || previous.state !== "COUNTDOWN") runCountdown(state.countdown_ms);
  } else if (s === "ARMED" && previous && previous.state === "COUNTDOWN") {
    clearTimeout(countdownTimer);
    showCount("Los");
    countdownTimer = setTimeout(hideCount, 700);
  } else if (s !== "ARMED") {
    hideCount();                               // also frees the timer as soon as it runs
  }

  // Context area
  $("form").hidden = !idle;
  $("drive").hidden = !jog;
  $("result").hidden = !showResult;
  $("waiting").hidden = s !== "AUTO_REQUESTED";
  $("start").disabled = !state.can_start;
  $("request-auto").disabled = !state.can_start;
  if (showResult) {
    $("result-title").textContent = state.result.new_best ? "Neue Bestzeit!" : "Geschafft.";
    $("result-rank").textContent = `Platz ${state.result.rank} von ${state.result.total}`;
  }
  if (!jog) { releaseKeys(); resetGiveUp(); }
  if (idle && previous && previous.state !== "IDLE") {
    clearForm();
    if (control) $("name").focus();
  }

  $("robot-best").textContent = formatTime(state.robot_best_ms);
  renderBoard();
}

// -------------------------------------------------------------- leaderboard
function rowNode(entry, isNew) {
  return el("li", { class: `row${entry.rank === 1 ? " is-first" : ""}${isNew ? " is-new" : ""}`,
                    dataset: { id: entry.run_id } },
    el("span", { class: "rank num", text: entry.rank }),
    el("span", { class: "name", text: entry.name }),
    el("span", { class: "year num", text: entry.birth_year }),
    el("span", { class: "time num", text: formatTime(entry.time_ms) }));
}

function renderBoard() {
  const board = $("board");
  const entries = state.leaderboard;
  const resultId = state.result ? state.result.run_id : null;
  const signature = JSON.stringify(entries.map((e) => [e.run_id, e.rank])) + "|" + resultId;
  if (board.dataset.signature === signature) return;
  board.dataset.signature = signature;

  // FLIP: remember where the rows were, re-render, then animate from the old places.
  const before = new Map();
  for (const node of board.children) before.set(node.dataset.id, node.getBoundingClientRect().top);

  const highlight = resultId !== null && resultId !== lastHighlight ? resultId : null;
  board.replaceChildren(...entries.map((e) => rowNode(e, e.run_id === highlight)));
  $("board-empty").hidden = entries.length > 0;

  const scale = stage.getBoundingClientRect().height / 1080 || 1;
  for (const node of board.children) {
    const old = before.get(node.dataset.id);
    const now = node.getBoundingClientRect().top;
    const offset = old === undefined ? 24 * scale : old - now;
    if (Math.abs(offset) < 1) continue;
    node.animate(
      [{ transform: `translateY(${offset / scale}px)`, opacity: old === undefined ? 0 : 1 },
       { transform: "none", opacity: 1 }],
      { duration: 450, easing: "cubic-bezier(0.25, 0.1, 0.25, 1)" });
  }

  // Own result outside the top 10: its own line under the list.
  const own = $("own-row");
  const inTop = entries.some((e) => e.run_id === resultId);
  if (state.result && !inTop) {
    own.replaceChildren(rowNode(state.result, state.result.run_id === highlight));
    own.hidden = false;
  } else {
    own.hidden = true;
  }
  if (highlight !== null) lastHighlight = highlight;
}

// ---------------------------------------------------------------------- form
function showFormError(text) { $("form-error").textContent = text || ""; }

function clearForm() {
  $("name").value = "";
  $("year").value = "";
  showFormError("");
}

function armFormIdle() {
  clearTimeout(formIdleTimer);
  formIdleTimer = setTimeout(clearForm, FORM_IDLE_MS);
}

$("form").addEventListener("input", () => { showFormError(""); armFormIdle(); });
$("year").addEventListener("input", (event) => {
  event.target.value = event.target.value.replace(/\D/g, "").slice(0, 4);
});

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state || !state.can_start) return;
  const name = $("name").value.trim();
  const year = Number($("year").value);
  const thisYear = new Date().getFullYear();
  if (!name) { showFormError("Bitte gib deinen Namen ein."); $("name").focus(); return; }
  if (!/^\d{4}$/.test($("year").value) || year < 1920 || year > thisYear) {
    showFormError("Bitte gib ein Geburtsjahr wie 2009 ein.");
    $("year").focus();
    return;
  }
  document.activeElement?.blur();
  socket.send({ type: "start", name, birth_year: year });
});

$("request-auto").addEventListener("click", () => socket.send({ type: "request_auto" }));
$("cancel-auto").addEventListener("click", () => socket.send({ type: "cancel_auto" }));

// Give up in two steps, without a modal.
function resetGiveUp() {
  clearTimeout(giveUpTimer);
  const button = $("give-up");
  button.classList.remove("is-confirm");
  button.textContent = "Aufgeben";
}

$("give-up").addEventListener("click", () => {
  const button = $("give-up");
  if (button.classList.contains("is-confirm")) {
    socket.send({ type: "give_up" });
    resetGiveUp();
    return;
  }
  button.classList.add("is-confirm");
  button.textContent = "Wirklich aufgeben?";
  giveUpTimer = setTimeout(resetGiveUp, 3000);
  button.blur();                               // the space bar must not trigger it while driving
});

// ------------------------------------------------------------------ keyboard
function sendKeys() {
  socket.send({ type: "keys", down: [...down], seq: ++seq });
}

function paintKeys() {
  for (const cap of document.querySelectorAll(".key")) {
    cap.classList.toggle("is-down", down.has(cap.dataset.key));
  }
}

function releaseKeys() {
  if (down.size === 0) return;
  down.clear();
  paintKeys();
  sendKeys();
}

function canSteer() { return control && state && JOG_STATES.has(state.state); }

window.addEventListener("keydown", (event) => {
  const key = KEY_MAP[event.code];
  if (!key || !canSteer()) return;
  event.preventDefault();
  if (event.repeat || down.has(key)) return;   // only state changes are sent
  down.add(key);
  paintKeys();
  sendKeys();
});

window.addEventListener("keyup", (event) => {
  const key = KEY_MAP[event.code];
  if (!key) return;
  if (canSteer()) event.preventDefault();
  if (!down.delete(key)) return;
  paintKeys();
  sendKeys();
});

// Dead man: without focus nobody is steering.
window.addEventListener("blur", releaseKeys);
document.addEventListener("visibilitychange", () => { if (document.hidden) releaseKeys(); });

// Heartbeat while steering; the server drops the keys after 300 ms of silence.
setInterval(() => { if (canSteer()) sendKeys(); }, HEARTBEAT_MS);

// Kiosk: no context menu, focus stays on the page.
window.addEventListener("contextmenu", (event) => event.preventDefault());
render();
