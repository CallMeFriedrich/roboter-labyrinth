// Number formats used everywhere: times as m:ss.cc, German decimal comma.

export function timeParts(ms) {
  const cs = Math.floor(Math.max(0, ms) / 10);
  const minutes = Math.floor(cs / 6000);
  const seconds = Math.floor(cs / 100) % 60;
  return {
    main: `${minutes}:${String(seconds).padStart(2, "0")}`,
    fraction: `.${String(cs % 100).padStart(2, "0")}`,
  };
}

export function formatTime(ms) {
  if (ms === null || ms === undefined) return "–:––.––";
  const { main, fraction } = timeParts(ms);
  return main + fraction;
}

export function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number(value).toLocaleString("de-DE", {
    minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false,
  });
}

export function formatDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}. ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
