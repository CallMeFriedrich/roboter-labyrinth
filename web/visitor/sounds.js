// Sounds for the visitor screen: synthesised with the Web Audio API, so no audio files,
// no licences and nothing to download (works offline). Volume and on/off come from the admin.

const NOTE = (n) => 440 * 2 ** ((n - 69) / 12);     // MIDI note number -> Hz

let ctx = null;
let master = null;
let enabled = true;
let volume = 0.7;                                     // 0 … 1

function audio() {
  if (!ctx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    ctx = new Ctx();
    master = ctx.createGain();
    // Soft limiter so several notes together never clip.
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -10;
    limiter.ratio.value = 8;
    master.connect(limiter).connect(ctx.destination);
    applyVolume();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

function applyVolume() {
  // Ears hear loudness roughly logarithmically: square the slider for an even feel.
  if (master) master.gain.value = enabled ? volume * volume : 0;
}

/** Settings from the server: {on: bool, volume: 0…100}. */
export function configure(sound) {
  if (!sound) return;
  enabled = Boolean(sound.on);
  volume = Math.min(1, Math.max(0, Number(sound.volume) / 100));
  applyVolume();
}

/** Browsers only allow sound after the first key press or click: unlock early. */
export function unlock() { audio(); }

// One note: oscillator through an envelope (quick attack, exponential release).
function tone(c, { freq, start, dur, type = "triangle", gain = 0.3, glideTo = null, cutoff = null }) {
  const osc = c.createOscillator();
  const env = c.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, start + dur);
  env.gain.setValueAtTime(0.0001, start);
  env.gain.exponentialRampToValueAtTime(gain, start + 0.012);
  env.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  let node = osc.connect(env);
  if (cutoff) {
    const filter = c.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = cutoff;
    node = node.connect(filter);
  }
  node.connect(master);
  osc.start(start);
  osc.stop(start + dur + 0.05);
}

// A bell-like note: fundamental plus a quiet octave on top.
function bell(c, midi, start, dur, gain = 0.28) {
  tone(c, { freq: NOTE(midi), start, dur, type: "triangle", gain });
  tone(c, { freq: NOTE(midi + 12), start, dur: dur * 0.6, type: "sine", gain: gain * 0.35 });
}

const SOUNDS = {
  // Reached the finish: a bright rising arpeggio.
  win(c, t) {
    [72, 76, 79].forEach((n, i) => bell(c, n, t + i * 0.11, 0.35));
    bell(c, 84, t + 0.33, 0.9, 0.32);
  },
  // New best time: longer fanfare that ends on a full chord.
  record(c, t) {
    [72, 76, 79, 84, 88].forEach((n, i) => bell(c, n, t + i * 0.09, 0.3, 0.26));
    for (const n of [84, 88, 91]) bell(c, n, t + 0.5, 1.4, 0.2);
    bell(c, 96, t + 0.62, 1.1, 0.12);
  },
  // Touched the wall: two falling, muffled buzzer notes.
  wall(c, t) {
    tone(c, { freq: NOTE(55), start: t, dur: 0.28, type: "sawtooth", gain: 0.32, cutoff: 900 });
    tone(c, { freq: NOTE(50), start: t + 0.3, dur: 0.75, type: "sawtooth", gain: 0.34, cutoff: 700,
              glideTo: NOTE(46) });
  },
  // Given up: one soft, falling note (nothing dramatic).
  giveup(c, t) {
    tone(c, { freq: NOTE(67), start: t, dur: 0.5, type: "sine", gain: 0.25, glideTo: NOTE(60) });
  },
};

export function play(name) {
  if (!enabled || volume <= 0 || !SOUNDS[name]) return;
  const c = audio();
  if (!c) return;
  SOUNDS[name](c, c.currentTime + 0.02);
}
