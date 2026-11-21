// Live map of the labyrinth as SVG: plate, channel, allowed area, path, gates, pen.

const NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function ringPath(points) {
  if (!points || !points.length) return "";
  return "M" + points.map((p) => `${p[0]},${p[1]}`).join("L") + "Z";
}

function polyPath(poly) {
  return ringPath(poly.outer) + poly.holes.map(ringPath).join("");
}

export function createMap(container, { onTap } = {}) {
  const root = svg("svg", { class: "map", viewBox: "0 0 400 400", role: "img",
                             "aria-label": "Karte des Labyrinths" });
  const layers = {};
  for (const name of ["base", "overlay", "taps", "pen"]) {
    layers[name] = svg("g");
    root.append(layers[name]);
  }
  const halo = svg("circle", { class: "pen-halo", r: 9 });
  const dot = svg("circle", { class: "pen", r: 4 });
  layers.pen.append(halo, dot);
  layers.pen.style.display = "none";
  container.replaceChildren(root);

  let target = null;
  let shown = null;
  let raf = 0;

  function frame() {
    raf = 0;
    if (!target || !shown) return;
    // Ease towards the last reported position: smooth between 20 Hz updates.
    shown[0] += (target[0] - shown[0]) * 0.35;
    shown[1] += (target[1] - shown[1]) * 0.35;
    const done = Math.hypot(target[0] - shown[0], target[1] - shown[1]) < 0.05;
    if (done) shown = [...target];
    for (const c of [halo, dot]) { c.setAttribute("cx", shown[0]); c.setAttribute("cy", shown[1]); }
    if (!done) raf = requestAnimationFrame(frame);
  }

  function gate(line, kind) {
    if (!line) return [];
    const mid = [(line.a[0] + line.b[0]) / 2, (line.a[1] + line.b[1]) / 2];
    const tip = [mid[0] + line.n[0] * 9, mid[1] + line.n[1] * 9];
    const side = [-line.n[1] * 2.5, line.n[0] * 2.5];
    const back = [tip[0] - line.n[0] * 3.5, tip[1] - line.n[1] * 3.5];
    return [
      svg("line", { class: `gate gate-${kind}`, x1: line.a[0], y1: line.a[1], x2: line.b[0], y2: line.b[1] }),
      svg("path", { class: `arrow arrow-${kind}`,
                    d: `M${mid[0]},${mid[1]}L${tip[0]},${tip[1]}M${back[0] + side[0]},${back[1] + side[1]}L${tip[0]},${tip[1]}L${back[0] - side[0]},${back[1] - side[1]}` }),
    ];
  }

  if (onTap) {
    root.classList.add("is-tappable");
    root.addEventListener("click", (event) => {
      const point = root.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const local = point.matrixTransform(root.getScreenCTM().inverse());
      onTap([Math.round(local.x * 10) / 10, Math.round(local.y * 10) / 10]);
    });
  }

  return {
    element: root,
    setGeometry(lab) {
      layers.base.replaceChildren();
      layers.overlay.replaceChildren();
      if (!lab) return;
      root.setAttribute("viewBox", `0 0 ${lab.width} ${lab.height}`);
      layers.base.append(svg("rect", { class: "plate", x: 0, y: 0, width: lab.width, height: lab.height, rx: 2 }));
      layers.base.append(svg("path", { class: "channel", d: polyPath(lab.channel), "fill-rule": "evenodd" }));
      for (const d of lab.engraving || []) layers.base.append(svg("path", { class: "engraving", d, "fill-rule": "evenodd" }));
      for (const d of lab.markers || []) layers.base.append(svg("path", { class: "marker", d }));
      for (const h of lab.holes || []) layers.base.append(svg("circle", { class: "hole", cx: h[0], cy: h[1], r: 2.5 }));
      for (const lost of lab.lost || []) layers.overlay.append(svg("path", { class: "lost", d: polyPath(lost), "fill-rule": "evenodd" }));
      if (lab.allowed) layers.overlay.append(svg("path", { class: "allowed", d: polyPath(lab.allowed) }));
      if (lab.path) {
        layers.overlay.append(svg("path", { class: "path", d: "M" + lab.path.points.map((p) => `${p[0]},${p[1]}`).join("L") }));
      }
      layers.overlay.append(...gate(lab.start_gate, "start"), ...gate(lab.finish_gate, "finish"));
      for (const [point, label] of [[lab.start_point, "S"], [lab.finish_point, "Z"]]) {
        if (!point) continue;
        const text = svg("text", { class: "mark", x: point[0], y: point[1] });
        text.textContent = label;
        layers.overlay.append(text);
      }
    },
    setTaps(points) {
      layers.taps.replaceChildren(...points.map((p) => svg("circle", { class: "tap", cx: p[0], cy: p[1], r: 2.5 })));
    },
    setPen(position) {
      if (!position) {
        layers.pen.style.display = "none";
        target = shown = null;
        return;
      }
      layers.pen.style.display = "";
      target = [position[0], position[1]];
      if (!shown || Math.hypot(target[0] - shown[0], target[1] - shown[1]) > 60) shown = [...target];
      if (!raf) raf = requestAnimationFrame(frame);
    },
  };
}
