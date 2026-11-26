// Virtual replay of a recorded run on the labyrinth map: the pen moves in the original rhythm
// and leaves a trail. Used by the stats page and the admin panel.
import { createMap } from "/static/shared/map.js";
import { timeParts } from "/static/shared/format.js";

const NS = "http://www.w3.org/2000/svg";
let mapCache = null;

export async function loadMap() {
  if (!mapCache) {
    const response = await fetch("/api/map", { cache: "no-store" });
    mapCache = response.ok ? await response.json() : null;
  }
  return mapCache;
}
export function forgetMap() { mapCache = null; }

export async function loadReplay(runId) {
  const response = await fetch(`/api/runs/${runId}/replay`, { cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || "Diesen Lauf kann man nicht abspielen.");
  return data;
}

/**
 * Player in `container`. `onTime(text, phase)` gets the clock ("0:12.34") and the phase
 * ("before" | "running" | "after"); `onEnd()` is called once when the replay is over.
 */
export function createPlayer(container, { onTime, onEnd } = {}) {
  const map = createMap(container);
  const trail = document.createElementNS(NS, "path");
  trail.setAttribute("class", "replay-trail");
  map.element.insertBefore(trail, map.element.lastChild);       // under the pen
  let raf = 0;
  let data = null;
  let began = 0;
  let index = 0;
  let ended = false;

  function position(t) {
    const pts = data.path.points;
    while (index < pts.length - 2 && pts[index + 1][0] <= t) index += 1;
    const a = pts[index], b = pts[Math.min(index + 1, pts.length - 1)];
    if (t >= b[0] || b[0] === a[0]) return [b[1], b[2], index + 1];
    const f = Math.max(0, (t - a[0]) / (b[0] - a[0]));
    return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, index];
  }

  function clock(t) {
    const { start_ms: start, finish_ms: finish } = data.path;
    if (start === null || start === undefined || t < start) return ["0:00.00", "before"];
    const end = finish ?? Infinity;
    const ms = Math.min(t, end) - start;
    const { main, fraction } = timeParts(ms);
    return [main + fraction, t >= end ? "after" : "running"];
  }

  function frame(now) {
    const pts = data.path.points;
    const total = pts[pts.length - 1][0];
    const t = Math.min(total, now - began);
    const [x, y, i] = position(t);
    const done = pts.slice(0, i + 1).map((p) => `${p[1]},${p[2]}`);
    trail.setAttribute("d", `M${done.join("L")}L${x},${y}`);
    map.setPen([x, y]);
    const [text, phase] = clock(t);
    onTime?.(text, phase);
    if (t >= total) {
      if (!ended) { ended = true; onEnd?.(); }
      raf = 0;
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  return {
    setGeometry(lab) { map.setGeometry(lab); },
    play(replay) {
      cancelAnimationFrame(raf);
      data = replay;
      index = 0;
      ended = false;
      trail.dataset.end = replay.end;
      began = performance.now();
      raf = requestAnimationFrame(frame);
    },
    stop() { cancelAnimationFrame(raf); raf = 0; },
  };
}
