// Admin panel (tablet): overview, robot, calibration, labyrinth, game, leaderboard.
import { connect } from "/static/shared/ws.js";
import { createMap } from "/static/shared/map.js";
import { el, formatDateTime, formatNumber, formatTime } from "/static/shared/format.js";
import { createPlayer, forgetMap, loadMap, loadReplay } from "/static/shared/replay.js";

const $ = (id) => document.getElementById(id);
const icon = (name) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `/static/shared/icons.svg#${name}`);
  svg.setAttribute("aria-hidden", "true");
  svg.append(use);
  return svg;
};

let S = null;               // latest admin state message
let defs = {};              // setting definitions (limits, choices)
let limits = {};
let socket = null;
let current = "overview";
const updaters = [];        // functions called with every new state

const STATE_LABEL = {
  DISCONNECTED: "Getrennt", IDLE: "Bereit", MOVING_TO_START: "Anfahrt zum Start",
  COUNTDOWN: "Countdown", ARMED: "Wartet auf die Startlinie", RUNNING: "Lauf läuft",
  FINISHED: "Im Ziel", RETURNING_HOME: "Rückfahrt", ABORTING: "Abbruch",
  AUTO_REQUESTED: "Auto-Lauf angefragt", AUTO_RUN: "Auto-Lauf", ERROR: "Fehler",
};
const ABORTABLE = new Set(["MOVING_TO_START", "COUNTDOWN", "ARMED", "RUNNING", "AUTO_RUN", "AUTO_REQUESTED"]);
const DRIVER_LABEL = { sim: "Simulator", standard: "Standard", extended: "Erweitert" };

// ============================================================== small helpers
function toast(message, error = false) {
  const node = el("div", { class: `toast${error ? " is-error" : ""}`, text: message });
  $("toasts").append(node);
  setTimeout(() => node.remove(), error ? 5000 : 2500);
}

async function request(method, path, body) {
  const response = await fetch(path, {
    method, credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (response.status === 401 && !path.endsWith("/login")) {
    showLogin();
    throw new Error("Bitte neu anmelden.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || data.detail || "Das hat nicht geklappt.");
  return data;
}

/** Run an admin command; errors become a toast. Returns the result or null. */
async function cmd(name, body = {}) {
  try {
    const data = await request("POST", `/api/admin/cmd/${name}`, body);
    return data.result ?? true;
  } catch (error) {
    toast(error.message, true);
    return null;
  }
}

function confirmSheet({ title, text, action, destructive = true }) {
  return new Promise((resolve) => {
    const layer = $("sheet-layer");
    const close = (value) => { layer.hidden = true; layer.replaceChildren(); resolve(value); };
    layer.replaceChildren(el("div", { class: "sheet", role: "dialog", "aria-modal": "true" },
      el("div", { class: "sheet-body" },
        el("div", { class: "sheet-text" }, el("strong", { text: title }), text || ""),
        el("button", { type: "button", class: destructive ? "is-destructive" : "", text: action,
                       onclick: () => close(true) })),
      el("button", { type: "button", class: "sheet-cancel", text: "Abbrechen", onclick: () => close(false) })));
    layer.onclick = (event) => { if (event.target === layer) close(false); };
    layer.hidden = false;
  });
}

// ------------------------------------------------------------- list builders
function group(header, cells, footer) {
  const list = el("ul", { class: "group" }, cells);
  return { node: el("div", { class: "group-wrap" },
    header ? el("p", { class: "group-header", text: header }) : null, list,
    footer ? el("p", { class: "group-footer", text: footer }) : null), list };
}

function valueCell(label, sub) {
  const value = el("span", { class: "cell-value" });
  const node = el("li", { class: "cell" },
    el("span", { class: "cell-label" }, label, sub ? el("span", { class: "cell-sub", text: sub }) : null), value);
  return { node, value, set(text, tone) {
    value.textContent = text;
    value.classList.toggle("is-good", tone === "good");
    value.classList.toggle("is-bad", tone === "bad");
  } };
}

function actionCell(label, onclick, { danger = false } = {}) {
  const button = el("button", { type: "button", class: `cell ${danger ? "cell-danger" : "cell-action"}`,
                                text: label, onclick });
  return { node: el("li", {}, button), button };
}

function segmented(options, onChange, wide = false) {
  const node = el("div", { class: `segmented${wide ? " segmented-wide" : ""}`, role: "group" });
  const buttons = new Map();
  let value = null;
  for (const option of options) {
    const button = el("button", { type: "button", text: option.label, disabled: option.disabled || false,
      onclick: () => { if (option.value !== value) onChange(option.value); } });
    buttons.set(option.value, button);
    node.append(button);
  }
  return { node, get value() { return value; }, set(next) {
    value = next;
    for (const [key, button] of buttons) button.classList.toggle("is-on", key === next);
  } };
}

async function patchSetting(key, value) {
  await cmd("settings", { values: { [key]: value } });
}

function sliderCell(key, label, { step = 1, digits = 0, sub } = {}) {
  const def = defs[key];
  const input = el("input", { type: "range", class: "slider", min: def.min, max: def.max, step,
                              "aria-label": label });
  const value = el("span", { class: "slider-value" });
  const show = (v) => { value.textContent = `${formatNumber(Number(v), digits)} ${def.unit}`.trim(); };
  let dragging = false;
  input.addEventListener("input", () => { dragging = true; show(input.value); });
  input.addEventListener("change", async () => { await patchSetting(key, Number(input.value)); dragging = false; });
  updaters.push((s) => {
    if (dragging || document.activeElement === input) return;
    input.value = s.admin.settings[key];
    show(s.admin.settings[key]);
  });
  return el("li", { class: "cell cell-stack" },
    el("div", { class: "cell-row" },
      el("span", { class: "cell-label" }, label, sub ? el("span", { class: "cell-sub", text: sub }) : null), value),
    input);
}

function stepperCell(key, label, { step = 1, digits = 0, sub } = {}) {
  const def = defs[key];
  // The value is a text field: type a number and press Enter, or use − / +.
  const input = el("input", { class: "text-input num-input stepper-input", type: "text", inputmode: "decimal",
                              "aria-label": label });
  const show = () => { input.value = formatNumber(S.admin.settings[key], digits); };
  const commit = async () => {
    const typed = Number(input.value.replace(",", ".").trim());
    if (!input.value.trim() || !Number.isFinite(typed)) { toast("Bitte eine Zahl eingeben.", true); show(); return; }
    if (typed === S.admin.settings[key]) { show(); return; }
    if (!(await cmd("settings", { values: { [key]: typed } }))) show();
  };
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); input.blur(); } });
  input.addEventListener("change", commit);
  const change = (delta) => {
    const now = S.admin.settings[key];
    const next = Math.min(def.max, Math.max(def.min, Math.round((now + delta) / step) * step));
    if (next !== now) patchSetting(key, Number(next.toFixed(4)));
  };
  updaters.push(() => { if (document.activeElement !== input) show(); });
  const value = el("span", { class: "cell-value stepper-value" }, input, def.unit ? el("span", { text: def.unit }) : null);
  return el("li", { class: "cell" },
    el("span", { class: "cell-label" }, label, sub ? el("span", { class: "cell-sub", text: sub }) : null), value,
    el("div", { class: "stepper" },
      el("button", { type: "button", "aria-label": `${label} verringern`, onclick: () => change(-step) }, icon("i-minus")),
      el("button", { type: "button", "aria-label": `${label} erhöhen`, onclick: () => change(step) }, icon("i-plus"))));
}

function choiceCell(key, label, options, sub) {
  const control = segmented(options, (value) => patchSetting(key, value));
  updaters.push((s) => control.set(s.admin.settings[key]));
  return el("li", { class: "cell" },
    el("span", { class: "cell-label" }, label, sub ? el("span", { class: "cell-sub", text: sub }) : null), control.node);
}

const RUN_MODE = { slow: "Langsam", normal: "Normal", turbo: "Turbo" };

function modeBadge(mode) {
  const m = RUN_MODE[mode] ? mode : "normal";
  const badge = el("span", { class: `run-mode run-mode-${m}`, title: RUN_MODE[m] });
  badge.append(icon(`i-speed-${m}`), el("span", { text: RUN_MODE[m] }));
  return badge;
}

// ------------------------------------------------------------------ replays
const END_TEXT = { finished: "Im Ziel.", wall: "Wand berührt.", aborted: "Aufgegeben." };

async function replayReal(run) {
  if (await confirmSheet({ title: `Lauf von ${run.name} am Roboter wiederholen?`, action: "Roboter fährt", destructive: false,
    text: "Der Roboter fährt den aufgezeichneten Weg mit dem damaligen Tempo nach – innerhalb der heutigen Wände. "
      + "Es entsteht kein neuer Eintrag." })) cmd("replay_start", { id: run.id });
}

/** Virtual replay in a sheet: the map with the pen moving like in the real run. */
async function replayVirtual(run) {
  let replay, lab;
  try { [replay, lab] = await Promise.all([loadReplay(run.id), loadMap()]); } catch (error) { toast(error.message, true); return; }
  if (!lab) { toast("Es ist kein Labyrinth aktiv.", true); return; }
  const layer = $("sheet-layer");
  const clock = el("p", { class: "replay-clock num", text: "0:00.00" });
  const end = el("p", { class: "replay-end" });
  const mapBox = el("div", { class: "replay-map" });
  const player = createPlayer(mapBox, {
    onTime(text, phase) { clock.textContent = text; clock.classList.toggle("is-before", phase === "before"); },
    onEnd() { end.textContent = END_TEXT[replay.end] || ""; },
  });
  player.setGeometry(lab);
  const close = () => { player.stop(); layer.hidden = true; layer.replaceChildren(); };
  const mode = RUN_MODE[replay.mode] || "Normal";
  layer.replaceChildren(el("div", { class: "replay-sheet", role: "dialog", "aria-modal": "true" },
    mapBox,
    el("div", { class: "replay-info" },
      el("strong", { text: replay.name }),
      el("span", { class: "cell-sub", text: `${replay.birth_year} · ${mode}${replay.status === "finished" ? " · " + formatTime(replay.time_ms) : ""}` }),
      clock, end,
      el("div", { class: "replay-actions" },
        el("button", { type: "button", class: "btn mini-btn", text: "Nochmal", onclick: () => { end.textContent = ""; player.play(replay); } }),
        el("button", { type: "button", class: "btn btn-primary mini-btn", text: "Am Roboter", onclick: () => { close(); replayReal(run); } }),
        el("button", { type: "button", class: "btn mini-btn", text: "Schließen", onclick: close })))));
  layer.onclick = (event) => { if (event.target === layer) close(); };
  layer.hidden = false;
  player.play(replay);
}

function replayButtons(run) {
  if (!run.replay) return el("span", { class: "run-noreplay", text: "ohne Aufzeichnung" });
  return el("span", { class: "cell-row run-replay" },
    el("button", { type: "button", class: "btn mini-btn", text: "Ansehen", onclick: () => replayVirtual(run) }),
    el("button", { type: "button", class: "btn mini-btn", text: "Am Roboter", onclick: () => replayReal(run) }));
}

function runCells(runs, { deletable = false, onDelete, replay = false } = {}) {
  return runs.map((run) => el("li", { class: "cell" },
    el("span", { class: "cell-label" }, run.name,
      el("span", { class: "cell-sub num", text: `${run.birth_year} · ${formatDateTime(run.created_at)}` })),
    replay && !deletable ? replayButtons(run) : null,
    modeBadge(run.speed_mode),
    run.status === "finished"
      ? el("span", { class: "run-time", text: formatTime(run.time_ms) })
      : el("span", { class: "run-aborted", text: "abgebrochen" }),
    deletable ? el("button", { type: "button", class: "btn btn-danger-text mini-btn", text: "Löschen",
                               onclick: () => onDelete(run) }) : null));
}

// =================================================================== sections
const sections = {};

// ------------------------------------------------- visitor release (overview)
const HOME_TEXT = "Der Stift muss frei sein. Steckt er noch im Kanal und die Position ist unbekannt, zuerst von Hand herausfahren.";
const FIX = {
  connect: { label: "Verbinden", run: () => cmd("connect") },
  home: { label: "Home anfahren", run: async () => {
    if (await confirmSheet({ title: "Home anfahren?", action: "Home anfahren", destructive: false, text: HOME_TEXT })) await cmd("home");
  } },
  labyrinth: { label: "Einrichten", run: () => show("labyrinth") },
  calibration: { label: "Einmessen", run: () => show("calibration") },
  release: { label: "Freigeben", run: () => cmd("release") },
};

/** One tap to let visitors play: fixes what can be fixed here and says why the rest blocks. */
async function releaseVisitors() {
  const needs = (key) => S.admin.readiness.find((c) => c.key === key && !c.ok);
  if (needs("robot") && !(await cmd("connect"))) return;
  const setup = S.admin.readiness.filter((c) => !c.ok && (c.key === "labyrinth" || c.key === "calibration"));
  if (setup.length) {
    toast(`Noch nicht möglich: ${setup.map((c) => c.detail).join(" ")}`, true);
    return;
  }
  if (S.admin.paused) await cmd("release");
  if (needs("home")) {
    if (!(await confirmSheet({ title: "Besucher freigeben?", action: "Home anfahren und freigeben", destructive: false,
                               text: `Der Roboter fährt dazu einmal Home. ${HOME_TEXT}` }))) return;
    if (!(await cmd("home"))) return;
  }
  toast("Besucher sind freigegeben.");
}

function buildRelease() {
  const headline = el("strong", { class: "release-title" });
  const reason = el("span", { class: "release-reason" });
  const go = el("button", { type: "button", class: "btn btn-primary", onclick: releaseVisitors });
  const hold = el("button", { type: "button", class: "btn", text: "Pausieren", onclick: () => cmd("pause") });
  const list = el("ul", { class: "group" });
  const node = el("div", { class: "group-wrap" },
    el("p", { class: "group-header", text: "Besucher" }),
    el("div", { class: "group release" },
      el("div", { class: "release-head" }, el("div", { class: "release-text" }, headline, reason),
        el("div", { class: "release-actions" }, hold, go))),
    el("div", { class: "release-checks" }, list),
    el("p", { class: "group-footer",
              text: "„Freigeben“ verbindet bei Bedarf und fährt Home. Einrichten und Einmessen gehen nur auf ihren eigenen Seiten." }));

  let key = null;
  updaters.push((s) => {
    const a = s.admin;
    const checks = a.readiness || [];
    const open = checks.filter((c) => !c.ok);
    const running = !["IDLE", "DISCONNECTED", "ERROR"].includes(s.state);
    const ready = !a.why_not;
    headline.textContent = ready ? "Besucher können starten"
      : running ? "Gerade läuft ein Lauf"
      : a.paused && open.length === 1 ? "Besucher sind pausiert"
      : "Besucher können noch nicht starten";
    headline.classList.toggle("is-good", ready);
    reason.textContent = ready ? "Name und Geburtsjahr eingeben, dann Start."
      : running ? `${STATE_LABEL[s.state]}. Danach geht es mit dem nächsten Besucher weiter.`
      : open.length ? open.map((c) => c.detail).filter(Boolean)[0] || "" : (a.why_not || "");
    go.textContent = a.paused || open.length ? "Freigeben" : "Freigegeben";
    go.disabled = ready || running || a.busy;
    hold.hidden = a.paused;

    const next = JSON.stringify(checks.map((c) => [c.key, c.ok, c.detail, c.fix]));
    if (next === key) return;
    key = next;
    list.replaceChildren(...checks.map((c) => {
      const mark = icon(c.ok ? "i-check" : "i-open");
      mark.setAttribute("class", `check-mark ${c.ok ? "is-ok" : "is-open"}`);
      const fix = c.fix && FIX[c.fix];
      return el("li", { class: "cell" }, mark,
        el("span", { class: "cell-label" }, c.label,
          el("span", { class: "cell-sub", text: c.ok ? "Erledigt" : c.detail || "Fehlt noch" })),
        fix ? el("button", { type: "button", class: "btn mini-btn", text: fix.label, onclick: fix.run }) : null);
    }));
  });
  return node;
}

// ------------------------------------------------------------------ overview
sections.overview = { title: "Übersicht", build(root) {
  const connection = valueCell("Roboter");
  const game = valueCell("Spiel");
  const ready = valueCell("Startbereit");
  const visitor = valueCell("Am Zug");
  const best = valueCell("Bestzeit Roboter");
  const notice = el("p", { class: "note is-danger", hidden: true });
  const abort = el("button", { type: "button", class: "btn btn-danger btn-abort", text: "Lauf abbrechen",
    onclick: () => { if (!socket.send({ type: "abort" })) cmd("abort"); } });   // one tap, no dialog
  const status = group("Status", [connection.node, game.node, ready.node, visitor.node, best.node]);
  status.list.append(el("li", {}, notice));

  const mapHost = el("div");
  const map = createMap(mapHost);
  let mapRev = null;
  const recent = group("Letzte Läufe", []);
  let recentKey = null;

  const release = buildRelease();
  root.append(abort, release, status.node, el("div", { class: "map-card" }, mapHost), recent.node);

  sections.overview.setPen = (message) => map.setPen(message.frame === "plate" ? message.pos : null);

  updaters.push(async (s) => {
    const a = s.admin;
    connection.set(s.robot.connected ? `Verbunden · ${DRIVER_LABEL[s.robot.driver]}` : "Getrennt",
                   s.robot.connected ? "good" : "bad");
    game.set(s.state === "DISCONNECTED" && s.robot.connected ? "Home nicht bestätigt" : STATE_LABEL[s.state]);
    ready.set(a.why_not ? a.why_not : "Ja", a.why_not ? null : "good");
    visitor.set(a.run_detail ? (a.run_detail.birth_year ? `${a.run_detail.name}, ${a.run_detail.birth_year}` : a.run_detail.name) : "–");
    best.set(formatTime(s.robot_best_ms));
    notice.hidden = !a.message;
    notice.textContent = a.message || "";
    abort.disabled = !ABORTABLE.has(s.state);

    const rev = `${s.labyrinth_rev}:${a.active_labyrinth ? a.active_labyrinth.id : 0}`;
    if (rev !== mapRev) {
      mapRev = rev;
      if (a.active_labyrinth) {
        try { map.setGeometry(await request("GET", `/api/admin/labyrinths/${a.active_labyrinth.id}`)); }
        catch { map.setGeometry(null); }
      } else {
        map.setGeometry(null);
      }
    }
    const key = `${s.state}:${s.leaderboard.length}:${rev}`;
    if (key !== recentKey) {
      recentKey = key;
      try {
        const runs = (await request("GET", "/api/admin/runs")).slice(0, 5);
        recent.list.replaceChildren(...(runs.length ? runCells(runs)
          : [el("li", { class: "empty", text: "Noch keine Läufe." })]));
      } catch { /* shown again with the next state */ }
    }
  });
} };

// --------------------------------------------------------------------- robot
sections.robot = { title: "Roboter", build(root) {
  const status = valueCell("Verbindung");
  const info = valueCell("Controller");
  const latency = valueCell("Antwortzeit", "letzter Befehl · Jog-Zyklus");
  const connectCell = actionCell("Verbinden", () => cmd("connect"));
  const disconnectCell = actionCell("Trennen", () => cmd("disconnect"), { danger: true });
  const driver = segmented([
    { value: "sim", label: "Simulator" }, { value: "standard", label: "Standard" },
    { value: "extended", label: "Erweitert", disabled: true }],
    async (value) => {
      if (await confirmSheet({ title: "Treiber wechseln?", destructive: false, action: `${DRIVER_LABEL[value]} verwenden`,
        text: value === "standard" ? "Der Standard-Treiber bewegt den echten Roboter. Der Arbeitsraum muss frei und abgesichert sein." : "" })) {
        patchSetting("driver", value);
      }
    });
  root.append(group("Verbindung", [
    status.node, info.node, latency.node,
    el("li", { class: "cell" }, el("span", { class: "cell-label", text: "Treiber" }), driver.node),
    connectCell.node, disconnectCell.node,
  ], "„Erweitert“ wird erst nach dem Robotertermin und nur mit Freigabe gebaut.").node);

  // Pose + jog
  const frame = segmented([{ value: "base", label: "Basis" }, { value: "plate", label: "Platte" }],
    (value) => cmd("set_frame", { mode: value }));
  const pose = ["x", "y", "z"].map((axis) => valueCell(axis.toUpperCase()));
  root.append(group("Position des Stifts", [
    el("li", { class: "cell" }, el("span", { class: "cell-label", text: "Koordinatensystem" }), frame.node),
    ...pose.map((p) => p.node),
  ]).node);

  let step = 1;
  const stepControl = segmented([
    { value: 0.1, label: "0,1 mm" }, { value: 1, label: "1 mm" }, { value: 10, label: "10 mm" },
    { value: "hold", label: "Dauer" }], (value) => { step = value; stepControl.set(value); });
  stepControl.set(step);

  // Pad direction (dx, dy as seen on the pad; z: +1 = "forward") → axis vector of the frame.
  const vector = (dx, dy, dz) => {
    if (S.admin.frame === "plate") {
      const towards = (S.admin.viewer_side || S.admin.settings.viewer_side) === "opposite" ? -1 : 1;
      return [dx, dy, dz * towards];
    }
    return [dz, -dx, -dy];       // base: right = −Y, up = +Z, forward = +X (standing behind the robot)
  };
  let holdTimer = 0;
  const stopHold = () => {
    if (!holdTimer) return;
    clearInterval(holdTimer);
    holdTimer = 0;
    socket.send({ type: "jog_hold", frame: S.admin.frame, dir: [0, 0, 0] });
  };
  const jogButton = (dx, dy, dz, content, label) => {
    const button = el("button", { type: "button", class: "jog-btn", "aria-label": label }, content);
    const release = () => { button.classList.remove("is-pressed"); stopHold(); };
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      if (button.disabled) return;
      const dir = vector(dx, dy, dz);
      if (step === "hold") {
        button.setPointerCapture(event.pointerId);
        button.classList.add("is-pressed");
        const beat = () => socket.send({ type: "jog_hold", frame: S.admin.frame, dir });
        beat();
        holdTimer = setInterval(beat, 100);      // heartbeat: the server stops after 300 ms silence
      } else {
        cmd("jog_step", { frame: S.admin.frame, dir, step });
      }
    });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) button.addEventListener(type, release);
    return button;
  };
  const arrow = (angle, diagonal) => {
    const node = icon(diagonal ? "i-arrow-diag" : "i-arrow");
    node.style.transform = `rotate(${angle}deg)`;
    return node;
  };
  const center = el("div", { class: "jog-center" });
  const pad = el("div", { class: "jog-pad" },
    jogButton(-1, -1, 0, arrow(-90, true), "links oben"), jogButton(0, -1, 0, arrow(0), "oben"),
    jogButton(1, -1, 0, arrow(0, true), "rechts oben"), jogButton(-1, 0, 0, arrow(-90), "links"), center,
    jogButton(1, 0, 0, arrow(90), "rechts"), jogButton(-1, 1, 0, arrow(180, true), "links unten"),
    jogButton(0, 1, 0, arrow(180), "unten"), jogButton(1, 1, 0, arrow(90, true), "rechts unten"));
  const forward = jogButton(0, 0, 1, "", "vor");
  const backward = jogButton(0, 0, -1, "", "zurück");
  const jogFooter = el("p", { class: "group-footer" });
  root.append(el("div", { class: "group-wrap" },
    el("p", { class: "group-header", text: "Von Hand fahren" }),
    el("div", { class: "group" },
      el("div", { class: "cell" }, el("span", { class: "cell-label", text: "Schrittweite" }), stepControl.node),
      el("div", { class: "jog" }, pad, el("div", { class: "jog-z" }, forward, backward))),
    jogFooter));

  // Drive to an exact coordinate (same frame as the pad, head orientation unchanged).
  const gotoInputs = ["X", "Y", "Z"].map((axis) => el("input", { class: "text-input num-input", type: "text",
    inputmode: "decimal", "aria-label": `Ziel ${axis}` }));
  let gotoDirty = false;
  gotoInputs.forEach((input) => input.addEventListener("input", () => { gotoDirty = true; }));
  const fillFromPose = () => {
    if (!S.admin.pose) { toast("Die aktuelle Position ist noch unbekannt. Einmal mit dem Pad fahren.", true); return; }
    S.admin.pose.forEach((v, i) => { gotoInputs[i].value = formatNumber(v, 1); });
    gotoDirty = true;
  };
  const gotoFooter = el("p", { class: "group-footer" });
  const gotoCell = actionCell("Anfahren", async () => {
    const target = gotoInputs.map((input) => Number(input.value.replace(",", ".").trim()));
    if (target.some((v) => !Number.isFinite(v)) || gotoInputs.some((input) => !input.value.trim())) {
      toast("Bitte für X, Y und Z je eine Zahl eingeben.", true);
      return;
    }
    const frameName = S.admin.frame === "plate" ? "Platte" : "Basis";
    const from = S.admin.pose;
    const distance = from ? Math.hypot(target[0] - from[0], target[1] - from[1], target[2] - from[2]) : null;
    const seconds = distance === null ? null : distance / (limits.admin_jog_speed || 20);
    const text = `Ziel im Koordinatensystem ${frameName}: X ${formatNumber(target[0], 1)} · Y ${formatNumber(target[1], 1)} · `
      + `Z ${formatNumber(target[2], 1)} mm. `
      + (distance === null ? "Die Startposition ist unbekannt. " : `Strecke ${formatNumber(distance, 0)} mm, ca. ${formatNumber(seconds, 0)} s. `)
      + "Der Roboter fährt in gerader Linie mit gleicher Kopfstellung. Der Weg muss frei sein.";
    if (await confirmSheet({ title: "Koordinate anfahren?", action: "Anfahren", destructive: false, text })) {
      if (await cmd("goto", { frame: S.admin.frame, xyz: target })) { gotoDirty = false; toast("Ziel erreicht."); }
    }
  });
  root.append(group("Koordinate anfahren", [
    el("li", { class: "cell cell-stack" },
      el("div", { class: "inline-fields" }, ["X", "Y", "Z"].map((axis, i) => el("label", {}, `${axis} (mm)`, gotoInputs[i])))),
    actionCell("Aktuelle Position übernehmen", fillFromPose).node,
    gotoCell.node,
  ], "").node);
  root.lastChild.append(gotoFooter);

  root.append(group("Home", [
    actionCell("Home anfahren", async () => {
      if (await confirmSheet({ title: "Home anfahren?", action: "Home anfahren", destructive: false,
        text: "Der Stift muss frei sein. Steckt er noch im Kanal und die Position ist unbekannt, zuerst von Hand herausfahren." })) cmd("home");
    }).node,
    actionCell("Aktuelle Stellung als Home einlernen", async () => {
      if (await confirmSheet({ title: "Home überschreiben?", action: "Als Home speichern",
        text: "Die aktuelle Gelenkstellung wird die neue Home-Position." })) {
        if (await cmd("teach_home")) toast("Home gespeichert.");
      }
    }).node,
    actionCell("Gelenke auf Startpose", async () => {
      if (await confirmSheet({ title: "Startpose anfahren?", action: "Startpose anfahren", destructive: false,
        text: "Der Roboter fährt mit allen Achsen auf die Startpose aus config.toml." })) cmd("start_pose");
    }).node,
  ], "Nach jeder Verbindung und nach jedem Fahren von Hand muss Home bestätigt werden, bevor ein Lauf starten kann.").node);

  updaters.push((s) => {
    const a = s.admin;
    status.set(s.robot.connected ? (a.home_confirmed ? "Verbunden" : "Verbunden, Home offen") : (a.last_error || "Getrennt"),
               s.robot.connected ? "good" : "bad");
    info.set(a.info ? [a.info.robot_type, a.info.robotware, a.info.serial].filter(Boolean).join(" · ") : "–");
    latency.set(`${formatNumber(a.latency_ms, 0)} ms · ${formatNumber(a.cycle_ms, 0)} ms`);
    driver.set(a.settings.driver);
    connectCell.button.disabled = s.robot.connected;
    disconnectCell.button.disabled = !s.robot.connected;
    frame.set(a.frame);
    const plate = a.frame === "plate";
    center.textContent = plate ? "Platte" : "Basis";
    forward.textContent = plate ? "Zur Platte" : "Vor  (X +)";
    backward.textContent = plate ? "Von der Platte weg" : "Zurück  (X −)";
    jogFooter.textContent = plate
      ? `Pfeile wie auf dem Besucher-Bildschirm. Geschwindigkeit ${formatNumber(limits.admin_jog_speed, 0)} mm/s.`
      : `Basis, hinter dem Roboter stehend: links/rechts = Y, oben/unten = Z. Geschwindigkeit ${formatNumber(limits.admin_jog_speed, 0)} mm/s.`;
    if (!holdTimer) {
      a.pose ? pose.forEach((p, i) => p.set(`${formatNumber(a.pose[i], 1)} mm`)) : pose.forEach((p) => p.set("–"));
    }
    if (!gotoDirty && !gotoInputs.includes(document.activeElement) && a.pose) {
      a.pose.forEach((v, i) => { gotoInputs[i].value = formatNumber(v, 1); });
    }
    gotoCell.button.disabled = !s.robot.connected || a.busy;
    gotoFooter.textContent = plate
      ? "Plattenkoordinaten wie im SVG (oben links = 0, y nach unten). Z = Abstand zur Plattenoberfläche. "
        + "Außerhalb der Platte oder durch die Wand wird das Ziel abgelehnt."
      : "Basiskoordinaten des Roboters in mm (X vor, Y links, Z hoch). Die Kopfstellung bleibt gleich. "
        + `Geschwindigkeit ${formatNumber(limits.admin_jog_speed, 0)} mm/s.`;
  });
  sections.robot.setPen = (message) => {
    message.pos ? pose.forEach((p, i) => p.set(`${formatNumber(message.pos[i], 1)} mm`)) : pose.forEach((p) => p.set("–"));
  };
} };

// --------------------------------------------------------------- calibration
sections.calibration = { title: "Einmessen", build(root) {
  const HOLES = [[1, "Bohrung oben links"], [2, "Bohrung oben rechts"], [3, "Bohrung unten links"],
                 [4, "Kontrolle unten rechts"]];
  const sketch = (index) => {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 36 36");
    svg.setAttribute("class", "hole-sketch");
    svg.setAttribute("aria-hidden", "true");
    const rect = document.createElementNS(ns, "rect");
    for (const [k, v] of Object.entries({ x: 3, y: 3, width: 30, height: 30, rx: 3 })) rect.setAttribute(k, v);
    svg.append(rect);
    [[9, 9], [27, 9], [9, 27], [27, 27]].forEach(([cx, cy], i) => {
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("r", i + 1 === index ? 4 : 2.5);
      if (i + 1 === index) dot.setAttribute("class", "is-on");
      svg.append(dot);
    });
    return svg;
  };
  const values = new Map();
  const simButtons = [];
  const goButtons = new Map();
  const goToHole = async (index, label) => {
    const pred = S.admin.hole_predictions && S.admin.hole_predictions[String(index)];
    if (!pred) { toast("Zuerst eine Bohrung anfahren und übernehmen.", true); return; }
    const waiting = S.admin.hole_waiting;
    if (waiting && waiting.index === index && waiting.clearance > S.admin.hole_near_clearance) {
      // Second step: straight towards the plate, stop 2 mm in front.
      const near = formatNumber(S.admin.hole_near_clearance, 0);
      if (await confirmSheet({ title: "Näher ran?", action: `Bis ${near} mm vor die Platte`, destructive: false,
        text: `Der Stift fährt gerade auf die Platte zu und hält ${near} mm vor der geschätzten Bohrung. `
          + "Die letzten Millimeter fährst du mit dem Pad (0,1 / 1 mm), dann „Übernehmen“." })) {
        if (await cmd("calib_goto", { index, clearance: S.admin.hole_near_clearance })) {
          toast(`${near} mm vor „${label}“. Jetzt mit dem Pad genau auf die Bohrung.`);
        }
      }
      return;
    }
    const clearance = formatNumber(S.admin.hole_clearance || 20, 0);
    const basis = pred.based_on === 1 ? "einer gemessenen Bohrung (Annahme: Platte steht senkrecht und quer vor dem Roboter)"
      : `${pred.based_on} gemessenen Bohrungen`;
    const text = `Der Stift fährt erst ${clearance} mm von der Platte weg und dann ${clearance} mm vor die Bohrung „${label}“ `
      + `(geschätzt aus ${basis}). Ziel: X ${formatNumber(pred.approach[0], 1)} · Y ${formatNumber(pred.approach[1], 1)} · `
      + `Z ${formatNumber(pred.approach[2], 1)} mm. Der Kopf dreht sich nicht. Das letzte Stück mit dem Pad fahren, dann „Übernehmen“.`;
    if (await confirmSheet({ title: "Zur Bohrung fahren?", action: "Hinfahren", destructive: false, text })) {
      if (await cmd("calib_goto", { index })) toast(`Vor „${label}“. Jetzt mit dem Pad genau hinfahren.`);
    }
  };
  const cells = HOLES.map(([index, label]) => {
    const sub = el("span", { class: "cell-sub num", text: "noch nicht gemessen" });
    values.set(index, sub);
    const sim = el("button", { type: "button", class: "btn mini-btn", text: "Sim: setzen", hidden: true,
                               onclick: () => cmd("sim_hole", { index }) });
    simButtons.push(sim);
    const go = el("button", { type: "button", class: "btn mini-btn", text: "Hinfahren", disabled: true,
                              onclick: () => goToHole(index, label) });
    goButtons.set(index, go);
    return el("li", { class: "cell" }, sketch(index), el("span", { class: "cell-label" }, label, sub), sim, go,
      el("button", { type: "button", class: "btn mini-btn", text: "Übernehmen",
                     onclick: () => cmd("calib_point", { index }) }));
  });
  root.append(group("Messpunkte", cells,
    "Fahr die Stiftspitze im Basis-Koordinatensystem mittig auf jede Bohrung und übernimm die Position. "
    + "Reihenfolge immer aus Sicht der Besucher. Nach der ersten Bohrung schätzt die Software die anderen: "
    + "„Hinfahren“ bringt den Stift 20 mm vor die Bohrung, das letzte Stück fährst du mit dem Pad. "
    + "Mit jeder weiteren Bohrung wird die Schätzung genauer.").node);

  const d12 = valueCell("Abstand oben links → oben rechts", "Soll 385,0 mm");
  const d13 = valueCell("Abstand oben links → unten links", "Soll 385,0 mm");
  const skew = valueCell("Winkelfehler der Ecke");
  const turn = valueCell("Kopfdrehung zwischen den Bohrungen", "Soll unter 1°");
  const check = valueCell("Abweichung Kontrollbohrung", "Soll unter 2 mm");
  const warnings = el("ul", { class: "warn-list", hidden: true });
  const activate = actionCell("Einmessung aktivieren", async () => {
    const hasWarnings = S.admin.calib_result && S.admin.calib_result.warnings.length;
    if (await confirmSheet({ title: "Einmessung überschreiben?", action: "Aktivieren",
      text: hasWarnings ? "Achtung: Es gibt Warnungen. Die bisherige Einmessung wird ersetzt."
                        : "Die bisherige Einmessung wird ersetzt." })) {
      if (await cmd("calib_activate")) toast("Einmessung aktiv.");
    }
  });
  const result = group("Ergebnis", [d12.node, d13.node, skew.node, turn.node, check.node, el("li", {}, warnings),
    activate.node, actionCell("Messpunkte verwerfen", () => cmd("calib_clear"), { danger: true }).node]);
  root.append(result.node);

  const active = valueCell("Aktive Einmessung");
  const origin = valueCell("Ursprung der Platte", "Basiskoordinaten");
  root.append(group("Aktuell", [active.node, origin.node,
    actionCell("Aktive Einmessung entfernen", async () => {
      if (await confirmSheet({ title: "Einmessung entfernen?", action: "Entfernen",
        text: "Ohne Einmessung kann mit dem echten Roboter kein Lauf starten." })) cmd("calib_remove");
    }, { danger: true }).node]).node);

  // Tool
  const TOOL = ["x", "y", "z", "q1", "q2", "q3", "q4"];
  const toolInputs = TOOL.map((name) => el("input", { class: "text-input num-input", type: "text",
    inputmode: "decimal", "aria-label": `Tool ${name}` }));
  let toolDirty = false;
  toolInputs.forEach((input) => input.addEventListener("input", () => { toolDirty = true; }));
  root.append(group("Werkzeug", [
    el("li", { class: "cell cell-stack" },
      el("div", { class: "inline-fields" }, TOOL.map((name, i) => el("label", {}, name, toolInputs[i])))),
    actionCell("Tool setzen", async () => {
      const numbers = toolInputs.map((input) => Number(input.value.replace(",", ".")));
      if (numbers.some(Number.isNaN)) { toast("Bitte nur Zahlen eingeben.", true); return; }
      if (await cmd("set_tool", { values: numbers })) { toolDirty = false; toast("Tool gesetzt."); }
    }).node,
  ], "Versatz der Stiftspitze zum Flansch in mm, Orientierung als Quaternion [w, x, y, z].").node);

  root.append(group("Stift und Platte", [
    stepperCell("pin_diameter", "Stiftdurchmesser", { step: 0.5, digits: 1 }),
    stepperCell("insert_depth", "Eintauchtiefe", { step: 1 }),
    stepperCell("retract_distance", "Rückzug", { step: 5 }),
    stepperCell("tool_roll_deg", "Stiftdrehung", { step: 15, sub: "Drehung um die Stiftachse" }),
    choiceCell("viewer_side", "Besucher stehen", [
      { value: "opposite", label: "Gegenüber" }, { value: "robot", label: "Roboterseite" }]),
  ], "Nach dem Einmessen behält der Roboter die Kopfstellung, mit der die Bohrungen angefahren wurden. "
    + "Besucherseite und Eintauchrichtung ergeben sich dann aus der Einmessung, die Stiftdrehung wird nicht verwendet.").node);

  updaters.push((s) => {
    const a = s.admin;
    const sim = s.robot.driver === "sim";
    simButtons.forEach((button) => { button.hidden = !sim; });
    // Immediate check: distance to the neighbouring hole(s) right after each point.
    const plateSize = a.active_labyrinth?.size || [400, 400];
    const neighbours = { 2: [[1, plateSize[0] - 15]], 3: [[1, plateSize[1] - 15]],
                         4: [[2, plateSize[1] - 15], [3, plateSize[0] - 15]] };
    for (const [index, node] of values) {
      const p = a.calib_points[String(index)];
      const pred = a.hole_predictions && a.hole_predictions[String(index)];
      let text = p ? p.map((v) => formatNumber(v, 2)).join("  ·  ")
        : pred ? `geschätzt: ${pred.xyz.map((v) => formatNumber(v, 1)).join("  ·  ")}` : "noch nicht gemessen";
      const go = goButtons.get(index);
      go.disabled = !pred || !s.robot.connected || a.busy;
      const waitingHere = a.hole_waiting && a.hole_waiting.index === index;
      go.textContent = waitingHere && a.hole_waiting.clearance > a.hole_near_clearance
        ? `Näher ran (${formatNumber(a.hole_near_clearance, 0)} mm)` : "Hinfahren";
      if (waitingHere && !p) {
        text = `steht ${formatNumber(a.hole_waiting.clearance, 0)} mm vor der Bohrung — mit dem Pad ganz hinfahren, dann übernehmen`;
      }
      let bad = false;
      for (const [other, soll] of (p ? neighbours[index] || [] : [])) {
        const q = a.calib_points[String(other)];
        if (!q) continue;
        const d = Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
        bad = bad || Math.abs(d - soll) > 2;
        text += `  —  zu Bohrung ${other}: ${formatNumber(d, 1)} mm (Soll ${formatNumber(soll, 0)})`;
      }
      node.textContent = text;
      node.classList.toggle("is-bad-text", bad);
    }
    const r = a.calib_result;
    const usable = r && !r.error;
    d12.set(usable ? `${formatNumber(r.distance_12, 2)} mm` : "–");
    d13.set(usable ? `${formatNumber(r.distance_13, 2)} mm` : "–");
    const size = a.active_labyrinth?.size;
    const soll = (v) => `Soll ${formatNumber(v, 1)} mm`;
    d12.node.querySelector(".cell-sub").textContent = soll(usable ? r.expected_12 : (size ? size[0] - 15 : 385));
    d13.node.querySelector(".cell-sub").textContent = soll(usable ? r.expected_13 : (size ? size[1] - 15 : 385));
    skew.set(usable ? `${formatNumber(r.skew_deg, 2)}°` : "–");
    const spread = usable ? r.orientation_spread_deg : null;
    turn.set(spread === null || spread === undefined ? "–" : `${formatNumber(spread, 1)}°`,
             spread === null || spread === undefined ? null : (spread > 1 ? "bad" : "good"));
    check.set(usable && r.check_error !== null ? `${formatNumber(r.check_error, 2)} mm` : "–",
              usable && r.check_error !== null ? (r.check_error > 2 ? "bad" : "good") : null);
    const list = r ? (r.error ? [r.error] : r.warnings) : [];
    warnings.hidden = list.length === 0;
    warnings.replaceChildren(...list.map((text) => el("li", { text })));
    activate.button.disabled = !usable;
    const c = a.calibration;
    active.set(!c ? "Keine" : c.source === "sim" ? "Simulator-Platte" : `Gemessen ${formatDateTime(c.created_at)}`,
               c ? "good" : "bad");
    origin.set(c ? c.wobj.slice(0, 3).map((v) => formatNumber(v, 1)).join("  ·  ") : "–");
    if (!toolDirty && !toolInputs.includes(document.activeElement)) {
      a.tool.forEach((v, i) => { toolInputs[i].value = formatNumber(v, i < 3 ? 1 : 4); });
    }
  });
} };

// ----------------------------------------------------------------- labyrinth
sections.labyrinth = { title: "Labyrinth", build(root) {
  let selected = null;
  let detail = null;
  let mode = "view";
  let taps = [];

  const list = group("Vorhandene Labyrinthe", []);
  const file = el("input", { type: "file", accept: ".svg,image/svg+xml", hidden: true });
  file.addEventListener("change", async () => {
    const chosen = file.files[0];
    file.value = "";
    if (!chosen) return;
    const result = await cmd("lab_upload", { name: chosen.name.replace(/\.svg$/i, ""), svg: await chosen.text() });
    if (result) { selected = result.id; await refreshList(); await loadDetail(); toast("Labyrinth hochgeladen."); }
  });
  list.node.append(el("p", { class: "group-footer",
    text: "SVG in mm (z. B. 300 × 300), Gruppe „Schnitt“ für Kanal und Bohrungen, „Startlinie“/„Ziellinie“ quer über den Gang, „Gravur_…“ nur zur Ansicht." }));
  root.append(list.node, file);

  const detailRoot = el("div", { hidden: true });
  root.append(detailRoot);
  const mapHost = el("div");
  const map = createMap(mapHost, { onTap: (p) => onTap(p) });
  const modeControl = segmented([
    { value: "view", label: "Ansehen" }, { value: "start", label: "Start" }, { value: "finish", label: "Ziel" },
    { value: "gate_start", label: "Startlinie" }, { value: "gate_finish", label: "Ziellinie" }],
    (value) => { mode = value; taps = []; map.setTaps([]); modeControl.set(value); showHint(); }, true);
  modeControl.set(mode);
  const hint = el("p", { class: "note" });
  const showHint = () => {
    hint.textContent = {
      view: "Wähle oben, was du auf der Karte setzen möchtest.",
      start: "Tippe auf den Startpunkt. In einem Kreis wird die Linie automatisch vorgeschlagen.",
      finish: "Tippe auf den Zielpunkt. In einem Kreis wird die Linie automatisch vorgeschlagen.",
      gate_start: "Tippe zwei Punkte quer über den Kanal. Die Linie schnappt auf die Wände.",
      gate_finish: "Tippe zwei Punkte quer über den Kanal. Die Linie schnappt auf die Wände.",
    }[mode];
  };
  showHint();

  const width = valueCell("Schmalste Stelle");
  const islands = valueCell("Inseln");
  const holes = valueCell("Bohrungen");
  const length = valueCell("Kürzester Weg", "zwischen Start- und Ziellinie");
  const autoTime = valueCell("Geschätzte Roboterzeit");
  const visitorTime = valueCell("Ideale Besucherzeit", "ohne Umwege, bei aktueller Geschwindigkeit");
  const status = valueCell("Status");
  const warnings = el("ul", { class: "warn-list", hidden: true });
  const activate = actionCell("Dieses Labyrinth aktivieren", async () => {
    if (await confirmSheet({ title: "Labyrinth aktivieren?", action: "Aktivieren", destructive: false,
      text: "Bestenliste und Roboter-Bestzeit gehören zum Labyrinth: Mit dem neuen Labyrinth beginnt eine neue Liste." })) {
      if (await cmd("lab_activate", { id: selected })) { await refreshList(); await loadDetail(); }
    }
  });
  const remove = actionCell("Labyrinth löschen", async () => {
    if (await confirmSheet({ title: "Labyrinth löschen?", action: "Löschen" })) {
      if (await cmd("lab_delete", { id: selected })) { selected = null; detailRoot.hidden = true; await refreshList(); }
    }
  }, { danger: true });
  const run = async (name, body = {}) => { if (await cmd(name, { id: selected, ...body })) await loadDetail(); };

  detailRoot.append(
    el("div", { class: "map-card" }, modeControl.node, hint, mapHost),
    group("Prüfung", [status.node, width.node, islands.node, holes.node, el("li", {}, warnings)]).node,
    group("Start, Ziel und Weg", [
      actionCell("Start und Ziel tauschen", () => run("lab_swap")).node,
      actionCell("Startlinie umdrehen", () => run("lab_flip", { which: "start" })).node,
      actionCell("Ziellinie umdrehen", () => run("lab_flip", { which: "finish" })).node,
      actionCell("Kürzesten Weg berechnen", async () => { await run("lab_path"); }).node,
      length.node, autoTime.node, visitorTime.node,
    ], "Der Pfeil an jeder Linie zeigt die Fahrtrichtung. Nur in dieser Richtung zählt das Überfahren.").node,
    group(null, [activate.node, remove.node]).node);

  async function onTap(point) {
    if (mode === "view" || !selected) return;
    if (mode === "start" || mode === "finish") {
      await run("lab_point", { which: mode, p: point });
      return;
    }
    taps.push(point);
    map.setTaps(taps);
    if (taps.length === 2) {
      const [p, q] = taps;
      taps = [];
      await run("lab_gate", { which: mode === "gate_start" ? "start" : "finish", p, q });
      map.setTaps([]);
    }
  }

  async function refreshList() {
    let items = [];
    try { items = await request("GET", "/api/admin/labyrinths"); } catch { return; }
    if (selected === null && items.length) selected = (items.find((i) => i.active) || items[0]).id;
    const cells = items.map((item) => el("li", {},
      el("button", { type: "button", class: "cell", onclick: async () => { selected = item.id; await refreshList(); await loadDetail(); } },
        el("span", { class: "cell-label" }, item.name,
          el("span", { class: "cell-sub", text: `${item.active ? "Aktiv · " : ""}hochgeladen ${formatDateTime(item.created_at)}` })),
        item.id === selected ? el("span", { class: "cell-value", text: "Ausgewählt" }) : icon("i-chevron"))));
    cells.forEach((cell) => cell.querySelector("svg")?.setAttribute("class", "chevron"));
    cells.push(actionCell("SVG hochladen …", () => file.click()).node);
    list.list.replaceChildren(...cells);
  }

  async function loadDetail() {
    if (selected === null) { detailRoot.hidden = true; return; }
    try { detail = await request("GET", `/api/admin/labyrinths/${selected}`); }
    catch (error) { toast(error.message, true); return; }
    detailRoot.hidden = false;
    map.setGeometry(detail);
    status.set(detail.active ? "Aktiv" : detail.ready ? "Bereit zum Aktivieren" : "Noch nicht vollständig",
               detail.ready ? "good" : null);
    width.set(`${formatNumber(detail.min_width, 1)} mm`);
    islands.set(String(detail.island_count));
    holes.set(`${detail.holes.length} von 4`, detail.holes.length === 4 ? "good" : "bad");
    warnings.hidden = detail.warnings.length === 0;
    warnings.replaceChildren(...detail.warnings.map((text) => el("li", { text })));
    length.set(detail.path ? `${formatNumber(detail.path.timed_length, 0)} mm` : "nicht berechnet");
    autoTime.set(detail.estimates ? `${formatNumber(detail.estimates.auto_s, 1)} s` : "–");
    visitorTime.set(detail.estimates ? `${formatNumber(detail.estimates.visitor_s, 0)} s` : "–");
    activate.button.disabled = !detail.ready || detail.active;
    remove.button.disabled = detail.active;
  }

  let seenRev = null;
  updaters.push(async (s) => {
    if (s.labyrinth_rev === seenRev) return;
    seenRev = s.labyrinth_rev;
    await refreshList();
    await loadDetail();
  });
} };

// ----------------------------------------------------------------- dashboard
// Everything about what the visitors see: live preview, look, board rotation, sounds, flow.
sections.dashboard = { title: "Dashboard", build(root) {
  const PAGES = { visitor: { path: "/?preview", label: "Besucher-Bildschirm" },
                  stats: { path: "/stats?preview", label: "Statistik" } };
  let page = "visitor";
  const frame = el("iframe", { class: "preview-frame", title: "Vorschau", tabindex: "-1",
                               src: PAGES.visitor.path });
  const holder = el("div", { class: "preview" }, frame);
  // The pages are designed for 1920 × 1080: render them at that size and scale down.
  const fit = () => {
    const scale = holder.clientWidth / 1920;
    if (scale > 0) frame.style.transform = `scale(${scale})`;
  };
  new ResizeObserver(fit).observe(holder);
  const pick = segmented(Object.entries(PAGES).map(([value, p]) => ({ value, label: p.label })), (value) => {
    page = value;
    pick.set(value);
    frame.src = PAGES[value].path;
  }, true);
  pick.set(page);
  const open = el("a", { class: "btn btn-text preview-open", target: "_blank", rel: "noopener",
                         text: "In neuem Tab öffnen" });
  open.href = "/";
  pick.node.addEventListener("click", () => { open.href = PAGES[page].path.replace("?preview", ""); });
  root.append(el("div", { class: "group-wrap" }, el("p", { class: "group-header", text: "Live-Vorschau" }),
    el("div", { class: "preview-bar" }, pick.node, open), holder,
    el("p", { class: "group-footer", text: "Die Vorschau zeigt genau, was die Besucher gerade sehen. Sie steuert nichts und spielt keine Töne." })));

  root.append(group("Erscheinungsbild", [
    choiceCell("visitor_theme", "Darstellung", [{ value: "dark", label: "Dunkel" }, { value: "light", label: "Hell" }]),
  ], "Gilt für den Besucher-Bildschirm und die Statistik-Seite. Dunkel wirkt im hellen Raum ruhiger, Hell passt zu Tageslicht.").node);

  root.append(group("Bestenliste", [
    stepperCell("board_rotate_s", "Liste wechseln alle", { sub: "Im Leerlauf: Langsam → Normal → Turbo. 0 = aus" }),
  ], "Steht 20 s niemand am Bildschirm, wechselt die Liste zwischen den drei Tempi.").node);

  const test = (name, label) => el("button", { type: "button", class: "btn mini-btn", text: label,
                                               onclick: () => cmd("sound_test", { name }) });
  root.append(group("Töne", [
    choiceCell("sound", "Töne", [{ value: "on", label: "An" }, { value: "off", label: "Aus" }],
      "Am Besucher-Bildschirm: Countdown 3 · 2 · 1 · Los, Ziel, neue Bestzeit, Wand berührt, Aufgeben"),
    sliderCell("sound_volume", "Lautstärke", { step: 5 }),
    el("li", { class: "cell" }, el("span", { class: "cell-label", text: "Testen" }),
      el("span", { class: "cell-row sound-tests" },
        test("win", "Ziel"), test("record", "Bestzeit"), test("wall", "Wand"), test("giveup", "Aufgeben"), test("tick", "3·2·1"), test("go", "Los"))),
  ], "Der Ton kommt aus dem Laptop am Besucher-Bildschirm. Zusätzlich gilt die Windows-Lautstärke.").node);

  root.append(group("Ablauf", [
    stepperCell("countdown_s", "Countdown", { sub: "0 = aus" }),
    stepperCell("result_display_s", "Ergebnis anzeigen"),
  ]).node);

  // Idle show: big calm movements when nobody plays.
  const checked = valueCell("Geprüfte Bewegungen", "Abstand zu Platte und Tisch mindestens 8 cm");
  const showButton = actionCell("Jetzt vorführen", async () => {
    if (S.admin.show?.running) { cmd("show_stop"); return; }
    if (await confirmSheet({ title: "Show jetzt vorführen?", action: "Roboter bewegt sich", destructive: false,
      text: "Der Arm macht ein paar große Bewegungen und fährt danach Home. Der Bereich um den Roboter muss frei sein." })) {
      cmd("show_start");
    }
  });
  root.append(group("Leerlauf-Show", [
    choiceCell("idle_show", "Automatisch", [{ value: "on", label: "An" }, { value: "off", label: "Aus" }],
      "Spielt eine Weile niemand, bewegt sich der Arm von selbst – ohne Pause, bis jemand kommt"),
    choiceCell("idle_show_style", "Bewegungen", [{ value: "full", label: "Ausgestreckt" }, { value: "compact", label: "Kompakt" }],
      "Ausgestreckt: mit ganz nach oben und links/rechts ausstrecken (braucht ca. 70 cm). Kompakt: bleibt nah am Roboter (ca. 52 cm)"),
    sliderCell("idle_show_scale_full", "Größe: Ausgestreckt", { step: 5, sub: "100 % = volle Figuren, 50 % = jede Achse schwenkt nur halb so weit" }),
    sliderCell("idle_show_scale_compact", "Größe: Kompakt", { step: 5 }),
    stepperCell("idle_show_min", "Startet nach", { sub: "Minuten ohne Spiel" }),
    sliderCell("idle_show_speed", "Tempo der Show", { step: 10 }),
    stepperCell("idle_show_radius", "Freier Umkreis", { step: 5, sub: "So weit darf der Arm vom Roboter weg. Ganz ausgestreckt braucht er 70 cm" }),
    checked.node, showButton.node,
  ], "Jede Bewegung wird vorher mit der Einmessung, dem Tool und der Home-Position berechnet. Nur Bewegungen mit "
    + "mindestens 8 cm Abstand zur Platte und zum Tisch werden gefahren, und nur so weit, wie der freie Umkreis erlaubt. "
    + "Startet jemand ein Spiel oder tippt am Besucher-Bildschirm, beendet der Arm die aktuelle Bewegung und fährt sofort Home. "
    + "„Jetzt vorführen“ spielt die Show einmal ab. "
    + "Erst am Roboter mit niedrigem Tempo ausprobieren, Hand am Not-Halt.").node);
  updaters.push((s) => {
    const show = s.admin.show || {};
    const homeBlocked = show.total === 1 && show.safe === 0;   // home itself is too close: no show at all
    checked.set(!show.total ? "erst einmessen" : homeBlocked ? "Home zu nah an der Platte" : `${show.safe} von ${show.total} frei`,
      show.total && show.safe === show.total ? "good" : show.total ? "bad" : null);
    checked.node.title = (show.skipped || []).join("\n");
    showButton.button.textContent = show.running ? "Show stoppen" : "Jetzt vorführen";
  });

  const address = valueCell("Adresse am iPad");
  root.append(group("Statistik-Seite", [address.node],
    "Eigene Seite für ein zweites iPad: Bestenlisten, Zeiten nach Alter und Zahlen zum Tag, live aktualisiert. "
    + "Im Safari öffnen und über Teilen → Zum Home-Bildschirm als Vollbild-App ablegen.").node);
  const host = ["localhost", "127.0.0.1"].includes(location.hostname) ? "192.168.137.1:8000" : location.host;
  address.set(`http://${host}/stats`);
} };

// ---------------------------------------------------------------------- game
sections.game = { title: "Spiel", build(root) {
  root.append(group("Geschwindigkeit", [
    sliderCell("speed_slow", "Besucher: Langsam", { step: 5 }),
    sliderCell("visitor_speed", "Besucher: Normal", { step: 5 }),
    sliderCell("speed_turbo", "Besucher: Turbo", { step: 5 }),
    sliderCell("auto_speed", "Auto-Lauf", { step: 10 }),
    sliderCell("approach_speed", "Anfahrt und Rückzug", { step: 10 }),
  ], "Die harten Obergrenzen stehen in config.toml und lassen sich hier nicht überschreiten.").node);

  root.append(group("Steuerung", [
    sliderCell("jog_rate_hz", "Takt der Steuerung", { step: 1 }),
    choiceCell("jog_zone", "Zone beim Steuern", [
      { value: "z0", label: "z0" }, { value: "z1", label: "z1" }, { value: "z5", label: "z5" }]),
    stepperCell("wall_tolerance", "Wandtoleranz", { step: 0.5, digits: 1,
      sub: "Abstand zur Wand. Negativ = so viele mm darf der Stift in die Wand drücken" }),
    choiceCell("wall_abort", "Wanderkennung", [{ value: "on", label: "An" }, { value: "off", label: "Aus" }],
      "Aus: Kein Lauf wird wegen der Wand abgebrochen. Die virtuellen Wände bleiben."),
    stepperCell("wall_abort_depth", "Abbruch bei Wandtiefe", { step: 0.5, digits: 1,
      sub: "Lauf endet, wenn der Stift so tief in der Wand ist. 0 = aus" }),
    stepperCell("auto_extra_margin", "Reserve im Auto-Lauf", { step: 0.5, digits: 1 }),
  ], "Wandtoleranz und Reserve berechnen die befahrbare Fläche neu. Der Auto-Lauf bleibt immer frei von den Wänden. "
    + "Damit der Abbruch greift, muss er höchstens so groß sein wie die negative Wandtoleranz (z. B. Toleranz −10, Abbruch 10).").node);

  const effective = valueCell("Wird verwendet");
  const start = actionCell("Auto-Lauf starten", async () => {
    if (await confirmSheet({ title: "Auto-Lauf starten?", action: "Starten", destructive: false,
      text: "Der Roboter fährt den kürzesten Weg mit der Auto-Geschwindigkeit." })) cmd("auto_start");
  });
  root.append(group("Auto-Lauf", [
    choiceCell("timing_method", "Zeitmessung", [
      { value: "logger", label: "LOGGER" }, { value: "fine", label: "Halt an Linien" },
      { value: "analytic", label: "Berechnet" }]),
    effective.node, start.node,
  ], "LOGGER misst die echte Position (Port 5001). Ohne LOGGER hält der Roboter kurz an Start- und Ziellinie.").node);

  updaters.push((s) => {
    effective.set({ logger: "LOGGER", fine: "Halt an Linien", analytic: "Berechnet" }[s.admin.timing_effective]);
    start.button.disabled = Boolean(s.admin.why_not) && s.state !== "AUTO_REQUESTED";
  });
} };

// --------------------------------------------------------------- leaderboard
sections.leaderboard = { title: "Bestenliste", build(root) {
  // Leaderboard profiles: separate boards (e.g. rehearsal, open day). One is active.
  const profiles = group("Profile", [], "Alle neuen Zeiten landen im aktiven Profil. Die anderen bleiben gespeichert. "
    + "Wechseln geht nur, wenn gerade kein Lauf ist.");
  const newName = el("input", { class: "text-input", type: "text", placeholder: "z. B. Tag der offenen Tür",
                                maxlength: "40", "aria-label": "Name des neuen Profils" });
  const create = el("button", { type: "button", class: "btn mini-btn", text: "Anlegen" });
  const createRow = el("li", { class: "cell" }, el("span", { class: "cell-label", text: "Neues Profil" }),
    el("span", { class: "cell-row profile-new" }, newName, create));
  const addProfile = async () => {
    const name = newName.value.trim();
    if (!name) { toast("Bitte gib einen Namen ein.", true); return; }
    if (await cmd("profile_add", { name })) { newName.value = ""; toast("Profil angelegt."); }
  };
  create.addEventListener("click", addProfile);
  newName.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); addProfile(); } });

  const exportCell = actionCell("Aktives Profil exportieren (CSV für Excel)", () => {
    location.href = "/api/admin/export.csv";
  });
  root.append(profiles.node, group(null, [exportCell.node],
    "Alle Läufe des Profils mit Tempo, Platz, Alter und Datum. Am iPad öffnet sich die Datei zum Teilen oder Sichern.").node);

  let profileKey = null;
  updaters.push((s) => {
    const list = s.admin.profiles || [];
    const next = JSON.stringify(list);
    if (next === profileKey) return;
    profileKey = next;
    profiles.list.replaceChildren(...list.map((p) => {
      const actions = el("span", { class: "cell-row profile-actions" });
      if (p.active) {
        actions.append(el("span", { class: "profile-active", text: "Aktiv" }));
      } else {
        actions.append(el("button", { type: "button", class: "btn mini-btn", text: "Aktivieren",
          onclick: () => cmd("profile_activate", { id: p.id }) }));
      }
      actions.append(
        el("button", { type: "button", class: "btn mini-btn", text: "Export",
          onclick: () => { location.href = `/api/admin/export.csv?profile=${p.id}`; } }),
        el("button", { type: "button", class: "btn mini-btn", text: "Umbenennen", onclick: async () => {
          const name = window.prompt("Neuer Name für das Profil", p.name);
          if (name !== null && name.trim() && name.trim() !== p.name) cmd("profile_rename", { id: p.id, name });
        } }));
      if (!p.active) {
        actions.append(el("button", { type: "button", class: "btn btn-danger-text mini-btn", text: "Löschen",
          onclick: async () => {
            if (await confirmSheet({ title: `Profil „${p.name}“ löschen?`, action: "Profil und Zeiten löschen",
              text: `${p.runs} Zeiten gehen verloren. Exportiere sie vorher, wenn du sie behalten willst.` })) {
              cmd("profile_delete", { id: p.id });
            }
          } }));
      }
      return el("li", { class: `cell${p.active ? " is-current" : ""}` },
        el("span", { class: "cell-label" }, p.name,
          el("span", { class: "cell-sub num", text: `${p.runs} ${p.runs === 1 ? "Zeit" : "Zeiten"} · seit ${formatDateTime(p.created_at)}` })),
        actions);
    }), createRow);
  });

  let editing = false;
  let query = "";
  const search = el("input", { class: "text-input", type: "search", placeholder: "Name suchen",
                               "aria-label": "Name suchen" });
  const edit = el("button", { type: "button", class: "btn btn-text", text: "Bearbeiten" });
  const runs = group("Alle Läufe", []);
  root.append(el("div", { class: "cell-row", style: "margin-bottom: var(--s-5)" }, search, edit), runs.node);

  async function refresh() {
    let items = [];
    try { items = await request("GET", `/api/admin/runs?search=${encodeURIComponent(query)}`); } catch { return; }
    runs.list.replaceChildren(...(items.length
      ? runCells(items, { deletable: editing, replay: true,
          onDelete: async (run) => { if (await cmd("run_delete", { id: run.id })) refresh(); } })
      : [el("li", { class: "empty", text: query ? "Kein Lauf mit diesem Namen." : "Noch keine Läufe." })]));
  }
  let timer = 0;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = search.value.trim(); refresh(); }, 200);
  });
  edit.addEventListener("click", () => { editing = !editing; edit.textContent = editing ? "Fertig" : "Bearbeiten"; refresh(); });

  root.append(group(null, [
    actionCell("Bestenliste zurücksetzen", async () => {
      if (await confirmSheet({ title: "Bestenliste zurücksetzen?", action: "Alle Läufe löschen",
        text: "Alle Zeiten des aktiven Profils auf diesem Labyrinth werden entfernt. Das lässt sich nicht rückgängig machen." })) {
        if (await cmd("board_reset")) refresh();
      }
    }, { danger: true }).node,
    actionCell("Roboter-Bestzeit zurücksetzen", async () => {
      if (await confirmSheet({ title: "Roboter-Bestzeit zurücksetzen?", action: "Zurücksetzen" })) cmd("robot_best_reset");
    }, { danger: true }).node,
  ]).node);

  let key = null;
  updaters.push((s) => {
    const next = `${s.state}:${s.runs_rev}`;
    if (next !== key) { key = next; refresh(); }
  });
} };

// ================================================================ navigation
function show(name) {
  current = name;
  $("title").textContent = sections[name].title;
  for (const [key, section] of Object.entries(sections)) section.root.hidden = key !== name;
  for (const node of $("nav").querySelectorAll(".cell")) node.classList.toggle("is-active", node.dataset.name === name);
  $("app").classList.add("is-detail");
  $("content").scrollTop = 0;
}

function buildApp() {
  for (const [name, section] of Object.entries(sections)) {
    section.root = el("section", { class: "section", hidden: true });
    section.build(section.root);
    $("sections").append(section.root);
    const button = el("button", { type: "button", class: "cell", dataset: { name }, onclick: () => show(name) },
      el("span", { class: "cell-label", text: section.title }), icon("i-chevron"));
    button.querySelector("svg").setAttribute("class", "chevron");
    $("nav").append(el("li", {}, button));
  }
  $("back").addEventListener("click", () => $("app").classList.remove("is-detail"));
  $("logout").addEventListener("click", async () => { await request("POST", "/api/admin/logout").catch(() => {}); location.reload(); });
  $("banner-approve").addEventListener("click", () => cmd("auto_start"));
  $("banner-reject").addEventListener("click", () => cmd("auto_reject"));
  show("overview");
  if (window.matchMedia("(max-width: 899px)").matches) $("app").classList.remove("is-detail");
}

function applyState(state) {
  S = state;
  $("banner").hidden = !state.auto_request;
  if (state.auto_request) {
    const r = state.replay;
    $("banner-title").textContent = r ? "Wiederholung angefragt" : "Auto-Lauf angefragt";
    $("banner-sub").textContent = r
      ? `Jemand am Statistik-iPad möchte den Lauf von ${r.name} am Roboter sehen.`
      : "Ein Besucher möchte den Roboter fahren lassen.";
  }
  if (state.labyrinth_rev !== applyState.labRev) { applyState.labRev = state.labyrinth_rev; forgetMap(); }
  $("nav-status").textContent = state.state === "DISCONNECTED" && state.robot.connected
    ? "Home nicht bestätigt" : STATE_LABEL[state.state];
  for (const update of updaters) {
    try { update(state); } catch (error) { console.error(error); }
  }
}

// ===================================================================== start
function showLogin() {
  socket?.close();
  $("app").hidden = true;
  $("login").hidden = false;
  $("pin").value = "";
  $("pin").focus();
}

async function startApp() {
  const data = await request("GET", "/api/admin/state");
  defs = data.definitions;
  limits = data.limits;
  $("login").hidden = true;
  $("app").hidden = false;
  if (!$("nav").children.length) { S = data.state; buildApp(); }
  applyState(data.state);
  socket = connect("/ws/admin", {
    onMessage(message) {
      if (message.type === "state") applyState(message);
      else if (message.type === "pos") { sections.overview.setPen(message); sections.robot.setPen(message); }
      else if (message.type === "error") toast(message.message, true);
    },
    onClose(event) { if (event.code === 4401) showLogin(); },
  });
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("login-error").textContent = "";
  try {
    await request("POST", "/api/admin/login", { pin: $("pin").value });
    await startApp();
  } catch (error) {
    $("login-error").textContent = error.message;
    $("pin").select();
  }
});

(async () => {
  try {
    const session = await request("GET", "/api/admin/session");
    if (session.ok) await startApp(); else showLogin();
  } catch { showLogin(); }
})();
