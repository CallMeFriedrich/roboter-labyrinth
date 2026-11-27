// Visitor screen: timer, registration, W A S D steering, leaderboard (CLAUDE.md §9.1).
import { connect } from "/static/shared/ws.js";
import { el, formatTime, timeParts } from "/static/shared/format.js";
import * as sound from "./sounds.js";
import { loadLogo } from "/static/shared/logo.js";

const $ = (id) => document.getElementById(id);
// "?preview" = shown inside the admin panel: never steers, never plays sounds.
const PREVIEW = new URLSearchParams(location.search).has("preview");
const stage = $("stage");

const KEY_MAP = {
  KeyW: "w", KeyA: "a", KeyS: "s", KeyD: "d",
  ArrowUp: "w", ArrowLeft: "a", ArrowDown: "s", ArrowRight: "d",
};
// Fallback by character, for keyboards whose arrow/letter codes differ.
const CHAR_MAP = { w: "w", a: "a", s: "s", d: "d", arrowup: "w", arrowleft: "a", arrowdown: "s", arrowright: "d",
                   up: "w", left: "a", down: "s", right: "d" };
const keyOf = (event) => KEY_MAP[event.code] || CHAR_MAP[(event.key || "").toLowerCase()];
const SPEED_LABEL = { slow: "Langsam", normal: "Normal", turbo: "Turbo" };
const SPEED_ORDER = ["slow", "normal", "turbo"];
const RESULT_IN = { slow: "im Schneckentempo", normal: "im normalen Tempo", turbo: "im Turbo" };
const EMPTY_IN = { slow: "Noch keine Zeiten im Schneckentempo.", normal: "Noch keine Zeiten im normalen Tempo.",
                   turbo: "Noch keine Zeiten im Turbo." };
const BOARD_QUIET_MS = 20_000;     // ... but only after 20 s without anybody at the screen
const SPEED_KEYS = { Digit1: "slow", Digit2: "normal", Digit3: "turbo",
                     Numpad1: "slow", Numpad2: "normal", Numpad3: "turbo" };
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
let boardMode = "normal";    // speed whose top 10 is shown in the list
let rotateMode = "normal";   // idle rotation position
let lastTouch = 0;           // performance.now() of the last visitor input
let lastBoardMode = null;
let rotateEvery = 8000;      // ms; from the admin ("Bestenliste wechseln"), 0 = off
let lastRotate = 0;

// ------------------------------------------------------------------- scaling
function fit() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  stage.style.transform = `scale(${scale})`;
}
window.addEventListener("resize", fit);
fit();

// ----------------------------------------------------------------- websocket
const socket = connect("/ws/visitor", {
  onOpen() { online = true; render(); },
  onClose() { online = false; releaseKeys(); render(); },
  onMessage(message) {
    if (message.type === "hello") {
      control = message.control && !PREVIEW;      // the admin preview only watches
      stage.classList.toggle("is-viewer", !control && !PREVIEW);   // the preview shows the kiosk view
    } else if (message.type === "state") {
      const previous = state;
      state = message;
      sound.configure(state.sound);
      applyDisplay(state.display);
      if (control && previous) playTransition(previous, state);
      if (!previous || previous.labyrinth_rev !== state.labyrinth_rev) loadLogo($("logo"));
      syncTimerBase();
      render(previous);
    } else if (message.type === "sound") {
      if (control) sound.play(message.name);              // admin: "Ton testen"
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
  // Beep with every number so the visitor can watch the robot instead of the screen.
  if (control) sound.play(text === "Los" ? "go" : "tick");
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
    case "IDLE":
      if (s.show) return "Der Roboter vertreibt sich die Zeit. Trag dich ein – er kommt sofort zurück.";
      return s.can_start ? "Steuere den Roboterarm durchs Labyrinth." : "Gleich geht es weiter.";
    case "MOVING_TO_START": return "Der Roboter fährt zum Start …";
    case "COUNTDOWN": return "Mach dich bereit.";
    case "ARMED": return "Die Zeit läuft ab der Startlinie.";
    case "RUNNING": return s.run ? s.run.name : "";
    case "AUTO_REQUESTED":
      return s.replay ? `Wiederholung von ${s.replay.name} – ein Betreuer gibt gleich frei …`
        : "Ein Betreuer gibt den Roboter gleich frei …";
    case "AUTO_RUN":
      return s.replay ? `Wiederholung: Der Roboter fährt den Lauf von ${s.replay.name} nach.`
        : "Der Roboter fährt ganz allein den kürzesten Weg.";
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

// Look chosen by the admin: dark (default) or light; idle rotation of the speed boards.
function applyDisplay(display) {
  if (!display) return;
  document.documentElement.classList.toggle("theme-light", display.theme === "light");
  rotateEvery = Math.max(0, Number(display.rotate_s) || 0) * 1000;
}

// Sounds only on the steering screen (the kiosk), not on screens that just watch.
function playTransition(before, now) {
  const result = now.result;
  if (result && (!before.result || before.result.run_id !== result.run_id)) {
    sound.play(result.new_best ? "record" : "win");
  }
  if (now.wall_hit && !before.wall_hit) sound.play("wall");
}

// Browsers allow sound only after an interaction: any key or click unlocks it.
for (const type of ["keydown", "pointerdown"]) window.addEventListener(type, sound.unlock, { capture: true });

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
  $("tag").hidden = !(s === "AUTO_RUN" || (s === "RETURNING_HOME" && (state.auto_result || state.replay)));
  $("tag").textContent = state.replay ? "Wiederholung" : "Roboter";

  // Timer
  const timer = $("timer");
  const wall = state.wall_hit;
  const finalMs = state.result?.time_ms ?? state.auto_result?.time_ms ?? wall?.time_ms ?? null;
  if (timerBase === null) setTimer(finalMs ?? (state.run ? state.run.elapsed_ms : 0));
  timer.classList.toggle("is-final", finalMs !== null && !wall);
  timer.classList.toggle("is-wall", Boolean(wall));
  if (wall && timerBase === null) setTimer(wall.time_ms);
  if (wall && !(previous && previous.wall_hit)) {
    stage.classList.remove("is-wall-flash");
    void stage.offsetWidth;                      // restart the flash
    stage.classList.add("is-wall-flash");
  }
  stage.classList.toggle("is-wall", Boolean(wall));
  $("wall").hidden = !wall;
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
  renderSpeed(idle, jog);
  if (showResult) {
    $("result-title").textContent = state.result.new_best ? "Neue Bestzeit!" : "Geschafft.";
    const where = RESULT_IN[state.result.speed_mode] || "";
    $("result-rank").textContent = `Platz ${state.result.rank} von ${state.result.total} ${where}`.trim();
  }
  if (!jog) { releaseKeys(); resetGiveUp(); }
  if (idle && previous && previous.state !== "IDLE") {
    clearForm();
    if (control) $("name").focus();
  }

  $("robot-best").textContent = formatTime(state.robot_best_ms);
  renderBoard();
}

// -------------------------------------------------------------------- speed
function renderSpeed(idle, jog) {
  const mode = state.speed_mode || "normal";
  const speeds = state.speeds || {};
  for (const button of document.querySelectorAll(".speed-option")) {
    const on = button.dataset.mode === mode;
    button.classList.toggle("is-on", on);
    button.setAttribute("aria-pressed", String(on));
    button.disabled = !idle || !control;
  }
  for (const node of document.querySelectorAll("[data-speed]")) {
    const v = speeds[node.dataset.speed];
    node.textContent = v ? `${Math.round(v)} mm/s` : "";
  }
  // The robot's own run has its own look; turbo belongs to the visitor.
  const robotDriving = ["AUTO_REQUESTED", "AUTO_RUN"].includes(state.state) || Boolean(state.auto_result);
  const look = robotDriving || state.wall_hit ? "normal" : mode;
  stage.classList.toggle("is-turbo", look === "turbo");
  stage.classList.toggle("is-slow", look === "slow");
  const tag = $("mode-tag");
  tag.hidden = idle || look === "normal";
  tag.textContent = SPEED_LABEL[look] || "";
  tag.dataset.mode = look;
  $("drive-speed").textContent = jog ? `Tempo: ${SPEED_LABEL[mode] || "Normal"}` : "";
}

function chooseSpeed(mode) {
  if (!state || state.state !== "IDLE" || !control || !SPEED_LABEL[mode]) return;
  if (state.speed_mode === mode) return;
  socket.send({ type: "speed", mode });
  touch();
  armFormIdle();
}

for (const button of document.querySelectorAll(".speed-option")) {
  button.addEventListener("click", () => { chooseSpeed(button.dataset.mode); button.blur(); });
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

function touch() { lastTouch = performance.now(); }

// Which speed the list shows: the visitor's own speed while somebody is at the screen,
// otherwise it cycles through all three like a scoreboard.
function shownMode() {
  const quiet = state.state === "IDLE" && !state.result && performance.now() - lastTouch > BOARD_QUIET_MS;
  if (quiet) return rotateMode;
  rotateMode = state.result?.speed_mode || state.speed_mode || "normal";
  return rotateMode;
}

setInterval(() => {
  if (!state || state.state !== "IDLE" || state.result || performance.now() - lastTouch <= BOARD_QUIET_MS) return;
  if (!rotateEvery || performance.now() - lastRotate < rotateEvery) return;
  lastRotate = performance.now();
  rotateMode = SPEED_ORDER[(SPEED_ORDER.indexOf(rotateMode) + 1) % SPEED_ORDER.length];
  renderBoard();
}, 500);

function renderRecords(boards, mode) {
  for (const button of document.querySelectorAll(".record")) {
    const m = button.dataset.mode;
    const best = (boards[m] || [])[0];
    const on = m === mode;
    button.classList.toggle("is-on", on);
    button.setAttribute("aria-pressed", String(on));
    button.querySelector("[data-record]").textContent = best ? formatTime(best.time_ms) : "–:––.––";
    button.querySelector("[data-record-name]").textContent = best ? best.name : "noch frei";
    button.classList.toggle("is-empty", !best);
  }
  $("board-mode").textContent = SPEED_LABEL[mode] || "";
  $("board-mode").dataset.mode = mode;
}

// Tapping a tile only changes the list (the speed itself is chosen at the start form).
for (const button of document.querySelectorAll(".record")) {
  button.addEventListener("click", () => {
    if (!state || state.state !== "IDLE") return;
    touch();
    rotateMode = button.dataset.mode;
    lastTouch = performance.now() - BOARD_QUIET_MS - 1;   // show it right away, then keep rotating
    renderBoard();
    button.blur();
  });
}

function renderBoard() {
  const board = $("board");
  const boards = state.boards || { normal: state.leaderboard || [] };
  const mode = shownMode();
  boardMode = mode;
  const entries = boards[mode] || [];
  renderRecords(boards, mode);
  const resultId = state.result && state.result.speed_mode === mode ? state.result.run_id : null;
  const signature = mode + "|" + JSON.stringify(entries.map((e) => [e.run_id, e.rank])) + "|" + resultId;
  if (board.dataset.signature === signature) return;
  board.dataset.signature = signature;
  $("board-empty").textContent = `${EMPTY_IN[mode] || "Noch keine Zeiten."} Sei die oder der Erste.`;

  // Another speed: cross-fade the whole list instead of moving rows around.
  if (lastBoardMode !== null && lastBoardMode !== mode) {
    lastBoardMode = mode;
    board.replaceChildren(...entries.map((e) => rowNode(e, false)));
    $("board-empty").hidden = entries.length > 0;
    for (const node of [board, $("board-empty")]) {
      node.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, easing: "cubic-bezier(0.25, 0.1, 0.25, 1)" });
    }
    $("own-row").hidden = true;
    return;
  }
  lastBoardMode = mode;

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
  if (resultId !== null && !inTop) {
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
  formIdleTimer = setTimeout(() => { clearForm(); chooseSpeed("normal"); }, FORM_IDLE_MS);
}

let lastTouchSent = 0;
$("form").addEventListener("input", () => {
  showFormError(""); touch(); armFormIdle();
  // Tell the server that somebody is here (restarts the idle-show clock), at most every 5 s.
  if (performance.now() - lastTouchSent > 5000) { lastTouchSent = performance.now(); socket.send({ type: "touch" }); }
});
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
    sound.play("giveup");
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
  // 1 / 2 / 3 choose the speed before the start (not while typing the birth year).
  const speed = SPEED_KEYS[event.code];
  if (speed && state && state.state === "IDLE" && !(event.target instanceof HTMLInputElement)) {
    event.preventDefault();
    chooseSpeed(speed);
    return;
  }
  const key = keyOf(event);
  if (!key || !canSteer()) return;
  event.preventDefault();
  if (event.repeat || down.has(key)) return;   // only state changes are sent
  down.add(key);
  paintKeys();
  sendKeys();
});

window.addEventListener("keyup", (event) => {
  const key = keyOf(event);
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
