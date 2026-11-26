// TFO logo from the engraving of the active labyrinth, drawn as vector (visitor screen, stats page).
// The engraving is one-coloured; on screen the three corner marks get the school colours
// (measured from the official logo): petrol top left, green top right, grey bottom left.
const LOGO_MARKS = [
  { colour: "#0082a3", box: [0, 0, 0.09, 0.25] },
  { colour: "#96c11a", box: [0.09, 0, 0.19, 0.25] },
  { colour: "#838383", box: [0, 0.27, 0.09, 0.55] },
];

function colourLogo(svg, paths, bounds) {
  const [x0, y0, x1, y1] = bounds;
  const w = x1 - x0, h = y1 - y0;
  const ns = "http://www.w3.org/2000/svg";
  for (const d of paths) {
    for (const sub of d.match(/[Mm][^Mm]*/g) || []) {
      const piece = document.createElementNS(ns, "path");
      piece.setAttribute("d", sub);
      svg.append(piece);
      let b;
      try { b = piece.getBBox(); } catch { piece.remove(); continue; }
      const r = [(b.x - x0) / w, (b.y - y0) / h, (b.x + b.width - x0) / w, (b.y + b.height - y0) / h];
      const mark = LOGO_MARKS.find(({ box }) =>
        r[0] >= box[0] - 0.005 && r[1] >= box[1] - 0.005 && r[2] <= box[2] && r[3] <= box[3]);
      if (mark) piece.style.fill = mark.colour;    // solid shapes: drawn over the white logo
      else piece.remove();
    }
  }
}
export async function loadLogo(target) {
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
    target.replaceChildren(svg);
    colourLogo(svg, data.paths, data.bounds);
  } catch { /* the logo is decoration; the screen works without it */ }
}
