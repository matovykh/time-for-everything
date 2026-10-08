/*
 * world-art.js — code-native art direction for the four living worlds.
 *
 * Public API (pure string builders, no DOM access, no timers):
 *   worldEmblem(id)                         -> SVG string (viewBox 0 0 96 96)
 *   worldScene(id, level, { motion = true }) -> HTML string: div.island-scene > svg.living-island (960×480)
 *   upgradeArtwork(id, index)               -> compact static SVG string (viewBox 0 0 240 140)
 *
 * Invariants (relied on by smoke tests):
 *   - a scene contains exactly 2 + 2 * level elements with class "citizen";
 *   - emblems and upgrade artworks never contain "citizen";
 *   - motion=false adds "motion-off wa-still" to the wrapper, CSS removes every animation;
 *   - every <defs> id is unique per call (counter based), so many scenes can share a page;
 *   - all animation classes are prefixed with "wa-" (see world-art.css).
 *
 * This module is intentionally self-contained (no import from worlds.js) to avoid
 * an import cycle when worlds.js starts importing it.
 */

let seq = 0;
const uid = (p) => `wa-${p}-${(++seq).toString(36)}`;
const r1 = (n) => Math.round(n * 10) / 10;
const clampLevel = (level) =>
  Math.max(0, Math.min(4, Math.floor(Number(level) || 0)));

/** Deterministic pseudo random (mulberry32) — textures look hand-placed but never change. */
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Lighten (amt > 0) or darken (amt < 0) a #rrggbb colour. */
function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const f = (c) =>
    Math.max(
      0,
      Math.min(255, Math.round(amt < 0 ? c * (1 + amt) : c + (255 - c) * amt)),
    );
  const r = f(n >> 16),
    g = f((n >> 8) & 255),
    b = f(n & 255);
  return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

/** transform="translate(x y) scale(s)" */
const at = (x, y, s = 1) =>
  `transform="translate(${r1(x)} ${r1(y)})${s !== 1 ? ` scale(${s})` : ""}"`;

/** class + timing variables for an ambient loop. t = duration (s), o = phase offset (s). */
const A = (cls, t, o = 0) =>
  `class="${cls}" style="--wa-t:${t}s;--wa-o:-${r1(o)}s"`;

/**
 * Invisible circle that fixes the bounding box of a rotating group so that
 * `transform-box: fill-box; transform-origin: center` pivots exactly on (0,0).
 */
const pivot = (r) => `<circle r="${r}" fill="none" stroke="none"/>`;

/**
 * A living inhabitant. The outer <g> positions, the inner .citizen animates
 * (CSS transforms on the inner group never fight the SVG transform attribute).
 */
function actor(x, y, body, o = {}) {
  const {
    a = "wa-walk",
    dx = 0,
    dy = 0,
    t = 14,
    d = 0,
    s = 1,
    flip = false,
  } = o;
  return `<g ${at(x, y, s)}><g class="citizen ${a}" style="--wa-dx:${dx}px;--wa-dy:${dy}px;--wa-t:${t}s;--wa-o:-${r1(d)}s">${flip ? `<g transform="scale(-1 1)">${body}</g>` : body}</g></g>`;
}

const gate = (level, n, str) => (level >= n ? str : "");

/** Soft drifting cloud made of circles (settlers / helpers). */
function puffCloud(x, y, s, fill = "#fff", op = 0.85) {
  return `<g ${at(x, y, s)} opacity="${op}" fill="${fill}"><ellipse cx="0" cy="0" rx="46" ry="15"/><circle cx="-18" cy="-10" r="16"/><circle cx="6" cy="-16" r="21"/><circle cx="28" cy="-6" r="13"/></g>`;
}

/** A small flock: each bird flaps, the whole flock glides. */
function flock(x, y, color, n = 3, s = 1, t = 22, o = 0) {
  let birds = "";
  for (let i = 0; i < n; i++) {
    const bx = i * 17 - (i % 2) * 4,
      by = (i % 2) * 9 - i * 2;
    birds += `<g ${at(bx, by)}><path ${A("wa-flap", 0.42 + i * 0.07, i * 0.2)} d="M-7 0q3.5-6 7 0q3.5-6 7 0" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round"/></g>`;
  }
  return `<g ${at(x, y, s)}><g ${A("wa-glide", t, o)}>${birds}</g></g>`;
}

/** Rising smoke: three staggered puffs (a static trail when motion is off). */
function smoke(x, y, color = "#ffffff", s = 1, square = false) {
  let out = "";
  for (let i = 0; i < 3; i++) {
    const px = i * 5 - 2,
      py = -i * 13,
      r = 4 + i * 2.2,
      op = 0.75 - i * 0.2;
    const shape = square
      ? `<rect x="${px - r}" y="${py - r}" width="${r * 2}" height="${r * 2}" fill="${color}" opacity="${op}"/>`
      : `<circle cx="${px}" cy="${py}" r="${r}" fill="${color}" opacity="${op}"/>`;
    out += `<g ${A("wa-smoke", 4.2, i * 1.4)}>${shape}</g>`;
  }
  return `<g ${at(x, y, s)}>${out}</g>`;
}

/** Waving flag on a pole. Pole bottom at (0,0). */
function flag(x, y, h, color, s = 1, pole = "#6d5a4a") {
  return `<g ${at(x, y, s)}><path d="M0 0V${-h}" stroke="${pole}" stroke-width="2.4" stroke-linecap="round"/><path ${A("wa-flag", 1.6)} d="M1 ${-h}h18l-5 6 5 6H1Z" fill="${color}"/></g>`;
}

/** Lantern garland along a quadratic curve. */
function garland(x1, y1, x2, y2, sag, colors, n = 8, cord = "#6e6a62") {
  const cx = (x1 + x2) / 2,
    cy = (y1 + y2) / 2 + sag;
  let lamps = "";
  for (let i = 1; i < n; i++) {
    const t = i / n,
      px = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t * t * x2,
      py = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t * t * y2;
    const c = colors[i % colors.length];
    lamps += `<g ${at(px, py)}><path d="M0 0v3" stroke="${cord}" stroke-width="1"/><circle cy="7" r="7" fill="${c}" opacity=".25" ${A("wa-twinkle", 1.8, i * 0.5)}/><rect x="-3.5" y="3" width="7" height="8" rx="3" fill="${c}"/></g>`;
  }
  return `<path d="M${x1} ${y1}Q${cx} ${cy} ${x2} ${y2}" fill="none" stroke="${cord}" stroke-width="1.4"/>${lamps}`;
}

/** Wrapper shared by every world scene. */
function frame(m, id, level, motion, body) {
  const lands = 1 + (level >= 1 ? 1 : 0) + (level >= 3 ? 1 : 0);
  const label = `${m.name}: ${lands} ${lands === 1 ? "территория" : "территории"}, ${2 + level * 2} ${m.people}. ${m.story[level]}`;
  return `<div class="island-scene wa-scene wa-${id}${motion ? " wa-live" : " motion-off wa-still"}" data-world-art="${id}" data-level="${level}" style="--island-sky:${m.skyBottom};--wa-sky-top:${m.skyTop};--wa-sky-bottom:${m.skyBottom};--world-accent:${m.accent}"><svg class="living-island wa-art" viewBox="0 0 960 480" role="img" aria-label="${label}" focusable="false">${body}</svg></div>`;
}

const META = {
  settlers: {
    name: "Тихая бухта",
    people: "поселенцев",
    accent: "#3ca781",
    skyTop: "#bfe6e2",
    skyBottom: "#5fb0b0",
    story: [
      "Два путника развели костёр у бревенчатого домика, за туманом ждёт лес.",
      "Туман ушёл: яблоневая поляна, лесник несёт брёвна, сборщица — корзину яблок.",
      "Ветряная пекарня крутит крылья, жители несут хлеб к дому.",
      "Мост ведёт к рыбацкой гавани, лодка покачивается у причала.",
      "Маяк светит, корабль гостей входит в бухту, над лагерем горят фонарики.",
    ],
  },
  bricks: {
    name: "Брик-сити",
    people: "строителей",
    accent: "#df8560",
    skyTop: "#cfe0fb",
    skyBottom: "#3f7fd6",
    story: [
      "Первая пластина и кирпичный домик с флажком; соседние пластины пока на чертеже.",
      "Долина деталей: склад, горки кирпичиков и два сборщика.",
      "Сборочная станция крутит шестерню, по ленте едут детали.",
      "Грузовой порт: кран поднимает контейнер на катер.",
      "Башня изобретений сияет, по улице едет парад машин, в небе дирижабль.",
    ],
  },
  voxel: {
    name: "Куболесье",
    people: "исследователей",
    accent: "#648e60",
    skyTop: "#c9e6f7",
    skyBottom: "#5d4a3a",
    story: [
      "Кубический домик в долине у гор, исследователи греются у костра.",
      "Ступенчатая долина открылась: шахта, кристаллы и овечка на террасе.",
      "Мастерская механизмов вращает кубическую шестерню, светящиеся блоки едут по ленте.",
      "Через реку перекинут мост, по воде идут экспедиционные плоты.",
      "Кристалл на вершине осветил остров, вокруг парят светящиеся кубики.",
    ],
  },
  helpers: {
    name: "Банановый залив",
    people: "непосед",
    accent: "#c3a22d",
    skyTop: "#8fdcf2",
    skyBottom: "#22a7c5",
    story: [
      "Жёлтые непоседы качаются в гамаке у хижины на сваях.",
      "Банановая роща: непоседы собирают связки и катят тележку.",
      "Фабрика смузи булькает и крутит блендер, курьеры несут стаканчики.",
      "Банановый порт: лодки-бананы у причала на сваях.",
      "Карнавал: прожекторы, флажки, конфетти и корабль друзей.",
    ],
  },
};

const IDS = ["settlers", "bricks", "voxel", "helpers"];
const metaOf = (id) => META[id] || META.settlers;
const idOf = (id) => (META[id] ? id : "settlers");

/* ───────────────────────── 1. ТИХАЯ БУХТА — settlers ─────────────────────────
 * Side-view layered landscape, soft organic curves, morning light, warm wood.
 */

const S_SKIN = ["#f3cba8", "#d9a07a", "#b77a55", "#f6d6bd"];
const S_COAT = [
  "#d9734e",
  "#4c8db5",
  "#6f9a47",
  "#c69a4e",
  "#8a68b0",
  "#d4566a",
];
const S_PROPS = {
  log: `<rect x="2" y="-27" width="22" height="5.5" rx="2.7" fill="#a87148" transform="rotate(-14)"/><circle cx="2.6" cy="-24.4" r="2.7" fill="#d9a979" transform="rotate(-14)"/>`,
  basket: `<path d="M6-15h12l-2 8H8Z" fill="#c8954f"/><path d="M7-15q5-7 10 0" fill="none" stroke="#a87440" stroke-width="1.4"/><circle cx="10" cy="-16" r="2.2" fill="#e04b3c"/><circle cx="14.4" cy="-16.4" r="2.2" fill="#e8653f"/>`,
  bread: `<ellipse cx="11" cy="-17" rx="7" ry="3.8" fill="#e0a257"/><path d="M7-18l2 2m1-3 2 2m1-3 2 2" stroke="#f6d19a" stroke-width="1.1"/>`,
  sack: `<path d="M5-26q7-3 13 1l-1 12q-6 3-12 0Z" fill="#e8d8b4"/><path d="M8-21h7" stroke="#c4ab7d" stroke-width="1.2"/>`,
  fish: `<path d="M6-15h12l-2 8H8Z" fill="#9e7a52"/><path d="M8-17q4-4 8 0q-4 3-8 0Zm8 0 3-2v4Z" fill="#8fc3d6"/>`,
  rod: `<path d="M6-17 32-46" stroke="#7a5a3c" stroke-width="1.8" stroke-linecap="round"/><path d="M32-46q6 22 4 52" fill="none" stroke="#fff" stroke-width=".8" opacity=".9"/>`,
  lantern: `<path d="M7-18v-10" stroke="#6b4b33" stroke-width="1.6"/><rect x="4" y="-31" width="6" height="7" rx="2" fill="#ffd36b"/><circle cx="7" cy="-27.5" r="7" fill="#ffd36b" opacity=".25"/>`,
  none: "",
};

function settler(i, prop = "none") {
  const skin = S_SKIN[i % 4],
    coat = S_COAT[i % 6];
  const hat = [
    `<path d="M-10-31h20" stroke="#c9a15a" stroke-width="3" stroke-linecap="round"/><path d="M-6-32q6-9 12 0Z" fill="#e6c57d"/><path d="M-6-32.5h12" stroke="#c4553f" stroke-width="1.6"/>`,
    `<path d="M-7-27q0-11 7-11t7 11q-7-4-14 0Z" fill="${shade(coat, -0.28)}"/>`,
    `<path d="M-6-31q6-7 12 0" fill="none" stroke="#6b4a32" stroke-width="4.4" stroke-linecap="round"/>`,
  ][i % 3];
  return `<ellipse cy="1.5" rx="9" ry="2.6" fill="#173f3f" opacity=".2"/><g class="wa-gait"><path d="M-3-1v-9M3-1v-9" stroke="#5b4535" stroke-width="3.4" stroke-linecap="round"/><path d="M-8.5-9C-8.5-19-6-24 0-24S8.5-19 8.5-9Z" fill="${coat}"/><path d="M-7.6-12.5h15.2" stroke="${shade(coat, -0.32)}" stroke-width="2"/><path d="M-7-20l-3 8M7-20l3 8" stroke="${shade(coat, -0.1)}" stroke-width="3.4" stroke-linecap="round"/><circle cy="-29" r="5.8" fill="${skin}"/><circle cx="-2" cy="-29.2" r=".95" fill="#3b2a20"/><circle cx="2.1" cy="-29.2" r=".95" fill="#3b2a20"/><circle cx="-3.4" cy="-26.9" r="1.3" fill="#e88a7a" opacity=".55"/>${hat}${S_PROPS[prop] || ""}</g>`;
}

function sRoundTree(x, y, s = 1, fruit = false, o = 0) {
  const apples = fruit
    ? `<g fill="#e2513e"><circle cx="-12" cy="-50" r="3.2"/><circle cx="9" cy="-60" r="3.2"/><circle cx="14" cy="-40" r="3.2"/><circle cx="-3" cy="-38" r="3.2"/><circle cx="-16" cy="-66" r="3.2"/></g>`
    : `<g fill="#fff4c8" opacity=".9"><circle cx="-10" cy="-58" r="1.8"/><circle cx="12" cy="-48" r="1.8"/><circle cx="2" cy="-68" r="1.8"/></g>`;
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="24" ry="5" fill="#1d5248" opacity=".18"/><path d="M-3.5 0C-2-18-3-30 0-42C3-30 2-18 3.5 0Z" fill="#8a6247"/><g ${A("wa-sway", 5.5, o)}>${pivot(80)}<circle cy="-52" r="26" fill="#4f9e6c"/><circle cx="-15" cy="-44" r="17" fill="#5aad74"/><circle cx="14" cy="-45" r="18" fill="#468f5c"/><circle cx="-6" cy="-63" r="15" fill="#72c180"/>${apples}</g></g>`;
}

function sPine(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="17" ry="4" fill="#1d5248" opacity=".18"/><rect x="-3" y="-12" width="6" height="12" fill="#7a5a40"/><g ${A("wa-sway", 6.5, o)}>${pivot(80)}<path d="M0-78-15-50h7l-13 22h9L-26-8h52L12-28h9L8-50h7Z" fill="#3a836a"/><path d="M0-78-15-50h7l-13 22h9L-26-8H0Z" fill="#4b9c78"/></g></g>`;
}

function sCabin(x, y, s = 1) {
  let logs = "";
  for (let r = 0; r < 5; r++)
    logs += `<path d="M-40 ${-4 - r * 9}h80" stroke="#8f5f3e" stroke-width="1.4" opacity=".55"/><circle cx="-40" cy="${-4.5 - r * 9}" r="4.3" fill="#d8a676" stroke="#8f5f3e" stroke-width="1.2"/><circle cx="40" cy="${-4.5 - r * 9}" r="4.3" fill="#d8a676" stroke="#8f5f3e" stroke-width="1.2"/>`;
  return `<g ${at(x, y, s)}><ellipse cy="3" rx="58" ry="8" fill="#1d4a44" opacity=".16"/><rect x="18" y="-92" width="13" height="36" fill="#9c9690"/><path d="M18-82h13m-13 10h13" stroke="#7f7973" stroke-width="1.5"/><rect x="16" y="-95" width="17" height="5" rx="1.5" fill="#7f7973"/>${smoke(24, -102, "#ffffff", 1)}<rect x="-40" y="-46" width="80" height="46" fill="#b9825a"/>${logs}<path d="M-56-40 0-86l56 46-6 5L0-76l-50 41Z" fill="#e07d55"/><path d="M-38-42 0-74l38 32Z" fill="#c99068"/><circle cy="-56" r="6" fill="#ffd98a" stroke="#8f5f3e" stroke-width="2"/><path d="M-50-35 0-76l50 41" fill="none" stroke="#b55f3e" stroke-width="2"/><path d="M-40-80l-14 12m24-21-18 15m40-15 18 15m-8-24 14 12" stroke="#f0a07c" stroke-width="2" opacity=".55"/><path d="M-10 0v-22a10 10 0 0 1 20 0V0Z" fill="#6b4a35"/><circle cx="5" cy="-11" r="1.4" fill="#e6c27a"/><rect x="-33" y="-34" width="15" height="14" rx="2" fill="#ffd98a" stroke="#7a4f33" stroke-width="2"/><rect x="18" y="-34" width="15" height="14" rx="2" fill="#ffd98a" stroke="#7a4f33" stroke-width="2"/><path d="M-25.5-34v14M25.5-34v14" stroke="#7a4f33" stroke-width="1.5"/><rect x="-35" y="-19" width="19" height="4" rx="1" fill="#8f5f3e"/><g fill="#ef6f7c"><circle cx="-31" cy="-20" r="2"/><circle cx="-25.5" cy="-21" r="2"/><circle cx="-20" cy="-20" r="2"/></g><rect x="-16" y="0" width="32" height="4" rx="2" fill="#a77b56"/></g>`;
}

function sCampfire(x, y, s = 1) {
  return `<g ${at(x, y, s)}><circle cy="-10" r="26" fill="#ffcf6a" opacity=".22" ${A("wa-glow", 2.2)}/><ellipse rx="17" ry="5.5" fill="#1d4a44" opacity=".14"/><g fill="#a8a29a"><circle cx="-13" cy="-1" r="3.6"/><circle cx="13" cy="-1" r="3.6"/><circle cx="-6" cy="2.5" r="3.6"/><circle cx="6" cy="2.5" r="3.6"/></g><path d="M-12-2 12-9M-12-9 12-2" stroke="#7a5236" stroke-width="5" stroke-linecap="round"/><g ${at(0, -5)}><g ${A("wa-flicker", 0.7)}><path d="M-8 0C-10-10-2-15 0-26 3-16 11-12 8 0Z" fill="#ff9640"/><path d="M-4 0C-4.5-7 0-10 0-16 2.5-9 5.5-7 4 0Z" fill="#ffe18a"/></g></g>${smoke(3, -36, "#e9eef0", 0.8)}</g>`;
}

function sWindmill(x, y, s = 1) {
  let sails = "";
  for (let k = 0; k < 4; k++)
    sails += `<g transform="rotate(${k * 90})"><path d="M0 0V-56" stroke="#7d5b3e" stroke-width="3"/><path d="M2.5-14h13v-40h-13Z" fill="#fff8e8" stroke="#b7926b" stroke-width="1.4"/><path d="M2.5-24h13m-13 10h13m-13 10h13m-13 10h13M9-54v40" stroke="#c9ab86" stroke-width=".9"/></g>`;
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="32" ry="6" fill="#1d4a44" opacity=".18"/><path d="M-23 0-15-86h30l8 86Z" fill="#f2e3c4"/><path d="M0-86h15l8 86H0Z" fill="#e0cba3"/><path d="M-21-22h42M-19-46h38M-17-66h34" stroke="#d2bb93" stroke-width="1.5"/><path d="M-7 0v-14a7 7 0 0 1 14 0V0Z" fill="#7a5638"/><circle cy="-52" r="5" fill="#ffd98a" stroke="#a77b56" stroke-width="1.5"/><path d="M-21-84Q0-116 21-84Z" fill="#d26f4c"/><g ${at(0, -94)}><g ${A("wa-spin", 16)}>${pivot(58)}<g transform="rotate(28)">${sails}</g></g><circle r="5.5" fill="#8a5a3c"/></g></g>`;
}

function sWheat(x, y, n = 9, o = 0) {
  let g = "";
  for (let i = 0; i < n; i++)
    g += `<g ${at(x + i * 7, y + (i % 2) * 3)}><g ${A("wa-sway", 3.2, o + i * 0.3)}>${pivot(16)}<path d="M0 0V-14" stroke="#d6a849" stroke-width="1.6"/><ellipse cy="-15" rx="2.2" ry="4.4" fill="#e9bf55"/></g></g>`;
  return g;
}

function sStall(x, y, s = 1) {
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="28" ry="4" fill="#1d4a44" opacity=".15"/><path d="M-20 0v-28M20 0v-28" stroke="#8f5f3e" stroke-width="3"/><rect x="-22" y="-14" width="44" height="14" rx="2" fill="#c98d5c"/><path d="M-24-28h48l-4 9h-40Z" fill="#fff4dc"/><path d="M-18-28l-2 9m10-9-1 9m9-9v9m9-9 1 9m9-9 2 9" stroke="#e05f4c" stroke-width="4.5"/><g fill="#e0a257"><ellipse cx="-11" cy="-16" rx="6" ry="3.4"/><ellipse cx="2" cy="-16.5" rx="6" ry="3.4"/><ellipse cx="14" cy="-16" rx="5" ry="3"/></g>${flag(22, -28, 14, "#f2c14e", 0.8, "#8f5f3e")}</g>`;
}

function sBoat(x, y, s = 1, sail = "#fff3dc", o = 0, flagC = "#e05f4c") {
  return `<g ${at(x, y, s)}><ellipse cy="12" rx="36" ry="4" fill="#ffffff" opacity=".35" ${A("wa-ripple", 3.4, o)}/><g ${A("wa-float", 3.4, o)}>${pivot(60)}<path d="M-32 0h64l-9 13h-46Z" fill="#b9784a"/><path d="M-30 3h60" stroke="#e8c49a" stroke-width="2"/><path d="M0 0v-52" stroke="#6b4a33" stroke-width="2.6"/><path d="M3-50 28-6H3Z" fill="${sail}" stroke="#c4a17a" stroke-width="1.2"/><path d="M-3-44-21-6h18Z" fill="${shade(sail, -0.08)}" stroke="#c4a17a" stroke-width="1.2"/>${flag(0, -52, 6, flagC, 0.7, "#6b4a33")}</g></g>`;
}

function sGuestShip(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><g ${A("wa-sail", 18, o)}><g ${A("wa-float", 4, o)}>${pivot(90)}<path d="M-70 0h140l-18 22H-52Z" fill="#8f5a3a"/><path d="M-66 5h132" stroke="#d9a46b" stroke-width="3"/><g fill="#ffe08a"><circle cx="-34" cy="12" r="3"/><circle cx="-14" cy="12" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="26" cy="12" r="3"/></g><path d="M-22 0v-82M26 0v-66" stroke="#5f4030" stroke-width="3.4"/><path d="M-44-74q22-6 44 0v50q-22-6-44 0Z" fill="#fff6e3" stroke="#c9a77d" stroke-width="1.4"/><path d="M8-60q18-5 36 0v40q-18-5-36 0Z" fill="#f6e7c6" stroke="#c9a77d" stroke-width="1.4"/><path d="M-44-46q22-5 44 0" fill="none" stroke="#e05f4c" stroke-width="4"/>${flag(-22, -82, 6, "#3ca781", 1, "#5f4030")}${flag(26, -66, 6, "#f2c14e", 0.9, "#5f4030")}</g></g></g>`;
}

function sLighthouse(x, y, beamId, s = 1) {
  const w = (yy) => r1(16 - (-yy / 104) * 6);
  const band = (a, b) =>
    `<path d="M${-w(a)} ${a}L${-w(b)} ${b}H${w(b)}L${w(a)} ${a}Z" fill="#d9574a"/>`;
  return `<g ${at(x, y, s)}><g ${at(0, -118)}><g ${A("wa-beam", 7)}>${pivot(330)}<path d="M0-5-330-64v120L0 5Z" fill="url(#${beamId})"/></g></g><path d="M-40 6q8-22 28-18 10-12 26-2 20-4 26 20Z" fill="#8c958f"/><path d="M-16 0-10-104h20l6 104Z" fill="#fbf6ec"/>${band(-22, -38)}${band(-62, -78)}<path d="M0-104h10l6 104H0Z" fill="#000" opacity=".07"/><rect x="-14" y="-108" width="28" height="5" rx="1.5" fill="#5b5f62"/><rect x="-8" y="-126" width="16" height="18" fill="#ffe27a" ${A("wa-glow", 1.8)}/><path d="M-8-126v18m8-18v18m8-18v18" stroke="#5b5f62" stroke-width="1.4"/><path d="M-12-126 0-140l12 14Z" fill="#d9574a"/><circle cy="-142" r="2.2" fill="#5b5f62"/><rect x="-4" y="-16" width="8" height="16" rx="4" fill="#5d6b74"/></g>`;
}

function sFisherHut(x, y, s = 1) {
  return `<g ${at(x, y, s)}><ellipse cy="3" rx="40" ry="5" fill="#1d4a44" opacity=".15"/><path d="M-26 0v-6m52 6v-6" stroke="#7a5a40" stroke-width="4"/><rect x="-28" y="-40" width="50" height="34" fill="#d8c3a0"/><path d="M-28-30h50M-28-20h50" stroke="#bda57f" stroke-width="1.2"/><path d="M-36-38 -3-62l33 24Z" fill="#4c8db5"/><path d="M-3-62l33 24-5 3-28-20Z" fill="#3a7096"/><rect x="-20" y="-28" width="12" height="12" rx="2" fill="#ffd98a" stroke="#7a5a40" stroke-width="1.6"/><rect x="2" y="-28" width="12" height="22" rx="2" fill="#6b4a35"/><path d="M26-30h20M28-30v26M44-30v26" stroke="#7a5a40" stroke-width="2"/><path d="M29-29h14v20H29Z" fill="none" stroke="#e8dcc0" stroke-width="1" stroke-dasharray="2 2"/><path d="M29-22h14M29-15h14M33-29v20M38-29v20" stroke="#e8dcc0" stroke-width=".8"/><rect x="-44" y="-12" width="12" height="12" rx="3" fill="#9a6a44"/><path d="M-44-6h12" stroke="#6b4a33" stroke-width="1.4"/></g>`;
}

function sDuck(x, y, s = 1, o = 0, chick = false) {
  const c = chick ? "#ffd75a" : "#ffffff";
  return `<g ${at(x, y, s)}><g ${A("wa-float", 2.6, o)}>${pivot(14)}<ellipse rx="8" ry="4.5" fill="${c}"/><circle cx="6" cy="-5" r="3.8" fill="${c}"/><path d="M9.4-5.6 14-4.6 9.4-3.6Z" fill="#f2a93b"/><circle cx="7.2" cy="-6" r=".8" fill="#2f2f2f"/><path d="M-5-1q4 2 8 0" fill="none" stroke="#d9d3c6" stroke-width="1.2"/></g></g>`;
}

function sWave(x, y, o = 0, w = 12) {
  return `<path ${A("wa-wave", 5, o)} d="M${x} ${y}q${w / 2}-4 ${w} 0t${w} 0" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" opacity=".6"/>`;
}

function sFog(cx, cy, w, label, o = 0) {
  return `<g class="wa-locked"><g ${A("wa-drift", 24, o)}><g fill="#ffffff"><ellipse cx="${cx}" cy="${cy}" rx="${w}" ry="${w * 0.36}" opacity=".78"/><ellipse cx="${cx - w * 0.38}" cy="${cy - w * 0.2}" rx="${w * 0.5}" ry="${w * 0.27}" opacity=".7"/><ellipse cx="${cx + w * 0.34}" cy="${cy - w * 0.16}" rx="${w * 0.46}" ry="${w * 0.25}" opacity=".66"/></g></g><text x="${cx}" y="${cy + 6}" text-anchor="middle" class="wa-tag" fill="#4d7f84">${label}</text></g>`;
}

const S_RIDGE = [
  [0, 292],
  [70, 270],
  [150, 272],
  [220, 258],
  [300, 250],
  [370, 274],
  [450, 278],
  [540, 266],
  [610, 254],
  [690, 262],
  [780, 270],
  [860, 254],
  [960, 266],
];
const ridgeY = (x) => {
  for (let i = 1; i < S_RIDGE.length; i++)
    if (x <= S_RIDGE[i][0]) {
      const [x0, y0] = S_RIDGE[i - 1],
        [x1, y1] = S_RIDGE[i];
      return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
    }
  return 266;
};

function settlersScene(level) {
  const k = uid("s"),
    sky = `${k}-sky`,
    sea = `${k}-sea`,
    glow = `${k}-glow`,
    beam = `${k}-beam`;
  const rand = rng(11);
  let pines = "";
  for (let i = 0; i < 34; i++) {
    const x = r1(rand() * 960),
      y = r1(ridgeY(x) + 6),
      h = r1(9 + rand() * 9);
    pines += `M${x} ${r1(y - h)}l${r1(h * 0.38)} ${h}h${r1(-h * 0.76)}Z`;
  }
  let o = `<defs><linearGradient id="${sky}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bfe6e2"/><stop offset=".55" stop-color="#e8f4e8"/><stop offset="1" stop-color="#fde6c4"/></linearGradient><linearGradient id="${sea}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a6ddd3"/><stop offset=".45" stop-color="#76bfbd"/><stop offset="1" stop-color="#4c9ea6"/></linearGradient><radialGradient id="${glow}"><stop offset="0" stop-color="#fff7d6" stop-opacity=".95"/><stop offset="1" stop-color="#fff7d6" stop-opacity="0"/></radialGradient><linearGradient id="${beam}" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stop-color="#fff6b8" stop-opacity=".75"/><stop offset="1" stop-color="#fff6b8" stop-opacity="0"/></linearGradient></defs>`;
  // sky, sun, weather
  o += `<rect x="-10" y="-10" width="980" height="320" fill="url(#${sky})"/><circle cx="772" cy="150" r="96" fill="url(#${glow})"/><circle cx="772" cy="150" r="34" fill="#fff3cf"/>`;
  o += `<g ${A("wa-drift", 34)}>${puffCloud(150, 92, 1.1)}${puffCloud(600, 64, 0.8, "#fff", 0.75)}</g><g ${A("wa-drift", 46, 12)}>${puffCloud(880, 104, 0.7, "#fff", 0.7)}</g>`;
  o +=
    flock(380, 108, "#4f7f86", 3, 1, 24) +
    flock(700, 70, "#4f7f86", 2, 0.8, 30, 8);
  // mountains & far forest
  o += `<path d="M0 270C60 226 120 206 180 222c50 14 80-26 140-36 60-10 100 44 160 50 60 6 120-36 180-40 60-4 100 36 160 30 50-6 100-30 140-20v120H0Z" fill="#acd8cf"/><path d="M296 190l24-4 16 14-18-2Zm364 6 18-2 14 10-16 0Z" fill="#fff" opacity=".7"/>`;
  o += `<path d="M${S_RIDGE.map((p) => p.join(" ")).join("L")}V320H0Z" fill="#8cc4b2"/><path d="${pines}" fill="#6fae9a"/>`;
  // sea
  o += `<rect x="-10" y="290" width="980" height="200" fill="url(#${sea})"/><path d="M0 292h960" stroke="#e8f7f2" stroke-width="2" opacity=".8"/>`;
  o += [
    [60, 318],
    [420, 312],
    [880, 330],
    [250, 452],
    [560, 462],
    [80, 420],
    [890, 466],
    [700, 440],
  ]
    .map(([x, y], i) => sWave(x, y, i * 0.7, 10 + (i % 3) * 3))
    .join("");
  // ── territory 2: forest glade (left, back)
  o += `<ellipse cx="160" cy="388" rx="150" ry="10" fill="#2f7f86" opacity=".22"/><path d="M14 366c16 22 216 26 288-12l2 10c-60 38-250 36-292 12Z" fill="#ecd6a4"/><path d="M18 362c12-40 62-62 132-66 70-4 130 10 150 34 12 16 0 32-30 38-70 12-180 14-230 8-16-4-26-8-22-14Z" fill="${level >= 1 ? "#9ad08c" : "#b9d9c4"}"/>`;
  if (level >= 1)
    o += `<g class="wa-reveal">${sPine(140, 318, 0.8, 1)}${sRoundTree(196, 322, 1, true, 2)}${sPine(256, 330, 0.75, 3)}${sRoundTree(80, 340, 0.85, true)}<g ${at(124, 360)}><ellipse rx="9" ry="3.5" fill="#c99a6a"/><rect x="-9" y="-6" width="18" height="6" fill="#a87148"/><ellipse cy="-6" rx="9" ry="3.5" fill="#e3bd8a"/><path d="M2-8 10-20" stroke="#6b4a33" stroke-width="2"/><path d="M8-22l6 2-3 5Z" fill="#9aa3a8"/></g><g ${at(224, 360)} fill="#a87148" stroke="#7a5236" stroke-width="1.2"><rect x="-16" y="-6" width="32" height="6" rx="3"/><rect x="-13" y="-12" width="26" height="6" rx="3"/><rect x="-8" y="-18" width="16" height="6" rx="3"/></g><path d="M40 368q60-10 120-4t130-6" fill="none" stroke="#e8d4a3" stroke-width="5" stroke-linecap="round" opacity=".85"/>${actor(92, 364, settler(2, "log"), { dx: 70, dy: 2, t: 15 })}${actor(178, 366, settler(3, "basket"), { dx: -44, dy: 2, t: 12, d: 4 })}</g>`;
  else o += sFog(160, 334, 150, "За туманом — лес");
  // ── windmill hill (workshop sits here from level 2)
  o += `<path d="M520 332c18-42 70-70 122-70 52 0 82 30 90 60Z" fill="#86c58a"/>`;
  if (level >= 2)
    o += `<g class="wa-reveal">${sWheat(566, 318, 8)}${sWheat(660, 316, 7, 1)}${sWindmill(640, 290, 1)}</g>`;
  // ── territory 3: harbour headland (right)
  o += `<ellipse cx="830" cy="398" rx="140" ry="9" fill="#2f7f86" opacity=".22"/><path d="M690 360c20 30 200 36 270 20v14c-70 16-250 12-272-18Z" fill="#ecd6a4"/><path d="M690 352c10-34 70-56 140-60 70-4 120 12 130 24v66c-60 10-200 10-246 2-20-6-28-18-24-32Z" fill="${level >= 3 ? "#93cd88" : "#b9d9c4"}"/>`;
  if (level >= 3)
    o += `<g class="wa-reveal">${sPine(746, 330, 0.7, 2)}${sFisherHut(800, 352, 1)}${sRoundTree(880, 346, 0.7, false, 1)}<path d="M664 360q30-34 62-4" fill="none" stroke="#8f5f3e" stroke-width="7"/><path d="M664 350q30-34 62-4" fill="none" stroke="#c4935f" stroke-width="2.4"/><path d="M672 342v12m10-20v14m10-17v15m10-14v14m10-10v12" stroke="#c4935f" stroke-width="2"/><path d="M740 410h132" stroke="#9e6d45" stroke-width="9"/><path d="M748 406h120" stroke="#d4a473" stroke-width="2"/><path d="M752 414v16m30-16v16m30-16v16m30-16v16" stroke="#7a5236" stroke-width="4"/>${sBoat(908, 436, 0.9, "#fff3dc", 1)}${actor(820, 406, settler(6, "rod"), { a: "wa-idle", t: 5 })}${actor(760, 372, settler(7, "fish"), { dx: 56, dy: -6, t: 13, d: 3 })}</g>`;
  else o += sFog(830, 340, 130, "Там — гавань", 6);
  // ── main island: camp
  o += `<ellipse cx="470" cy="418" rx="236" ry="11" fill="#2f7f86" opacity=".25"/><path d="M256 370c20 32 140 40 224 40 120 0 186-14 206-50l4 12c-16 40-90 52-210 52-100 0-210-10-226-42Z" fill="#efd8a5"/><path d="M262 368c8-42 58-68 138-74 80-6 160-2 220 12 48 12 70 34 60 54-10 18-80 32-210 34-110 2-190-4-208-26Z" fill="#8fce86"/><path d="M300 330c30-22 80-30 150-32 70-2 130 2 170 14" fill="none" stroke="#b5e0a6" stroke-width="10" stroke-linecap="round" opacity=".7"/><path d="M430 356c40 8 80 14 110 8s60-20 98-26" fill="none" stroke="#ead6a6" stroke-width="9" stroke-linecap="round"/>`;
  o += `${sRoundTree(300, 358, 1.05, false, 1)}${sPine(612, 350, 0.95, 2)}${sCabin(440, 352, 1)}${sCampfire(536, 372, 1)}<rect x="556" y="378" width="24" height="7" rx="3.5" fill="#a87148"/>`;
  o += `<g fill="#f6e3a0"><circle cx="330" cy="384" r="2.4"/><circle cx="394" cy="392" r="2.4"/><circle cx="604" cy="380" r="2.4"/></g><g fill="#ef8fa0"><circle cx="340" cy="388" r="2.2"/><circle cx="620" cy="386" r="2.2"/></g>`;
  if (level >= 2)
    o += `<g class="wa-reveal">${sStall(352, 380, 1)}${actor(372, 398, settler(4, "bread"), { dx: 60, dy: -2, t: 14 })}${actor(626, 372, settler(5, "sack"), { dx: -54, dy: 14, t: 16, d: 5 })}</g>`;
  o += actor(486, 386, settler(0), { dx: 40, dy: 4, t: 16 });
  o += actor(586, 392, settler(1, "lantern"), { dx: -36, dy: -2, t: 13, d: 6 });
  // ── foreground water life
  o += `${sDuck(330, 446, 1, 0)}${sDuck(348, 450, 0.6, 1, true)}${sDuck(362, 452, 0.6, 2, true)}`;
  // ── festival: lighthouse, garland, guest ship
  if (level >= 4)
    o += `<g class="wa-reveal">${sLighthouse(918, 330, beam, 1)}${garland(441, 268, 611, 276, 46, ["#ffd35c", "#ef8f86", "#9ec9f0", "#b9a2ec"], 9)}${sGuestShip(150, 446, 0.9, 0)}${actor(500, 400, settler(8), { a: "wa-dance", t: 0.9 })}${actor(530, 404, settler(9), { a: "wa-dance", t: 0.9, d: 0.4 })}</g>`;
  return o;
}

/* ───────────────────────── 2. БРИК-СИТИ — bricks ─────────────────────────
 * Isometric toy baseplates floating on a blue stud-sea, primary colours,
 * crisp edges, studs on every top face, builders with C-hands.
 */

const BX = 400,
  BY = 80,
  CU = 16,
  CV = 8,
  KH = 13;
const P = (i, j, k = 0) => [
  r1(BX + (i - j) * CU),
  r1(BY + (i + j) * CV - k * KH),
];
const poly = (pts, fill, extra = "") =>
  `<path d="M${pts.map((p) => p.join(" ")).join("L")}Z" fill="${fill}"${extra}/>`;
const quadJ = (j, i1, i2, k1, k2) => [
  P(i1, j, k1),
  P(i2, j, k1),
  P(i2, j, k2),
  P(i1, j, k2),
];
const quadI = (i, j1, j2, k1, k2) => [
  P(i, j1, k1),
  P(i, j2, k1),
  P(i, j2, k2),
  P(i, j1, k2),
];

function studs(i, j, k, a, b, color, step = 1) {
  let side = "",
    top = "";
  for (let u = 0; u < a; u += step)
    for (let v = 0; v < b; v += step) {
      const [x, y] = P(i + u + step / 2, j + v + step / 2, k);
      side += `M${r1(x - 4.4)} ${r1(y - 3)}V${y}a4.4 2.4 0 0 0 8.8 0V${r1(y - 3)}Z`;
      top += `M${r1(x - 4.4)} ${r1(y - 3)}a4.4 2.4 0 1 0 8.8 0a4.4 2.4 0 1 0-8.8 0Z`;
    }
  return `<path d="${side}" fill="${shade(color, -0.22)}"/><path d="${top}" fill="${shade(color, 0.16)}"/>`;
}

/** Iso brick/box. Faces: top, front-left (j = j+b), front-right (i = i+a). */
function box(
  i,
  j,
  k,
  a,
  b,
  c,
  color,
  { stud = true, step = 1, edge = true } = {},
) {
  const t = k + c;
  const top = [P(i, j, t), P(i + a, j, t), P(i + a, j + b, t), P(i, j + b, t)];
  let out =
    poly(quadJ(j + b, i, i + a, k, t), shade(color, -0.1)) +
    poly(quadI(i + a, j, j + b, k, t), shade(color, -0.27)) +
    poly(top, color);
  if (edge)
    out += `<path d="M${P(i, j + b, t).join(" ")}L${P(i + a, j + b, t).join(" ")}L${P(i + a, j, t).join(" ")}" fill="none" stroke="${shade(color, 0.3)}" stroke-width="1"/>`;
  if (stud) out += studs(i, j, t, a, b, color, step);
  return out;
}

const BR_TORSO = [
  "#e3342f",
  "#2f6fdb",
  "#2ea44f",
  "#f28c28",
  "#8a4fd8",
  "#f4f1e8",
];
const BR_LEGS = ["#1f3a6e", "#2b2b2b", "#6b4a2e"];
const BR_PROPS = {
  brick: `<g transform="translate(9 -19)"><rect x="-5" y="-4" width="10" height="5" rx=".8" fill="#2f6fdb"/><rect x="-4" y="-6" width="3" height="2" fill="#5b8fe8"/><rect x="1" y="-6" width="3" height="2" fill="#5b8fe8"/></g>`,
  wrench: `<path d="M9-14 15-24" stroke="#9aa5b1" stroke-width="2.4" stroke-linecap="round"/><circle cx="15.5" cy="-25" r="2.6" fill="none" stroke="#9aa5b1" stroke-width="1.8"/>`,
  flag: `<path d="M10-13V-40" stroke="#5b5b5b" stroke-width="1.4"/><path ${A("wa-flag", 1.2)} d="M10.5-40h11l-3 4 3 4h-11Z" fill="#f2c14e"/>`,
  crate: `<g transform="translate(10 -18)"><rect x="-6" y="-6" width="12" height="10" fill="#c8894b"/><path d="M-6-1h12M0-6v10" stroke="#8f5a2c" stroke-width="1.2"/></g>`,
  none: "",
};

function minifig(i, prop = "none") {
  const torso = BR_TORSO[i % 6],
    legs = BR_LEGS[i % 3],
    yel = "#ffd23f";
  const hat = [
    `<path d="M-6.8-32.6q0-7.4 6.8-7.4t6.8 7.4Z" fill="#f6c21c"/><rect x="-7.6" y="-33.4" width="15.2" height="2" rx="1" fill="#e0a800"/>`,
    `<path d="M-5.4-33q0-5.6 5.4-5.6t5.4 5.6Z" fill="#e3342f"/><rect x="0" y="-34" width="9" height="2" rx="1" fill="#b8231f"/>`,
    `<path d="M-5.6-31.8q-1-6.4 5.6-6.6 6.6.2 5.6 6.6-2-3.6-5.6-3.4-3.6-.2-5.6 3.4Z" fill="#6b3d1f"/>`,
    `<rect x="-2.6" y="-36.4" width="5.2" height="2.6" rx=".8" fill="${yel}"/>`,
  ][i % 4];
  return `<ellipse cy="1.5" rx="9" ry="2.6" fill="#0d2d5a" opacity=".24"/><g class="wa-gait"><path d="M-6 0v-10h5.4V0Zm6.6 0v-10H6V0Z" fill="${legs}"/><rect x="-6.4" y="-12.4" width="12.8" height="3" rx=".6" fill="${shade(legs, -0.25)}"/><path d="M-7-12h14l-1.5-12h-11Z" fill="${torso}"/><path d="M-3-22.5v8m6-8v8" stroke="${shade(torso, -0.25)}" stroke-width="1.2" opacity=".7"/><path d="M-6.2-22.5-9.6-14M6.2-22.5 9.6-14" stroke="${shade(torso, -0.08)}" stroke-width="3.8" stroke-linecap="round"/><circle cx="-9.9" cy="-12.6" r="2.1" fill="${yel}"/><circle cx="9.9" cy="-12.6" r="2.1" fill="${yel}"/><rect x="-2" y="-26" width="4" height="2.4" fill="${yel}"/><rect x="-5.2" y="-34.4" width="10.4" height="9.4" rx="2.8" fill="${yel}"/><rect x="2" y="-33" width="2.2" height="6" rx="1.1" fill="#fff" opacity=".35"/><circle cx="-2" cy="-30.6" r=".95" fill="#222"/><circle cx="2" cy="-30.6" r=".95" fill="#222"/><path d="M-2.3-28.2q2.3 1.9 4.6 0" fill="none" stroke="#222" stroke-width=".9" stroke-linecap="round"/>${hat}${BR_PROPS[prop] || ""}</g>`;
}

const bActor = (i, j, k, body, o = {}) => {
  const [x, y] = P(i, j, k);
  return actor(x, y, body, o);
};
/** Screen vector for a move of (di, dj) grid units — used for walk/drive paths. */
const vec = (di, dj) => ({ dx: r1((di - dj) * CU), dy: r1((di + dj) * CV) });
/** Move a whole iso group by (di, dj) grid units (projection is linear). */
const shift = (di, dj, inner) => {
  const v = vec(di, dj);
  return `<g transform="translate(${v.dx} ${v.dy})">${inner}</g>`;
};

function bTree(i, j, k, s = 1, o = 0) {
  const [x, y] = P(i + 0.5, j + 0.5, k);
  return `<g ${at(x, y, s)}><ellipse cy="1" rx="18" ry="6" fill="#0d2d5a" opacity=".18"/><rect x="-4" y="-16" width="8" height="16" fill="#8b5a2b"/><rect x="0" y="-16" width="4" height="16" fill="#6e4520"/><g ${A("wa-sway", 6, o)}>${pivot(70)}<path d="M0-66c8 0 18 18 22 34l3 16c0 6-50 6-50 0l3-16C-18-48-8-66 0-66Z" fill="#2ea44f"/><path d="M0-66c8 0 18 18 22 34l3 16c0 3-12 5-25 5Z" fill="#23853f"/><path d="M-21-30q21 8 43 0M-17-46q17 7 34 0" fill="none" stroke="#1d6e34" stroke-width="2" opacity=".6"/><ellipse cy="-66" rx="4.4" ry="2.2" fill="#55c472"/><rect x="-4.4" y="-69" width="8.8" height="3" fill="#2ea44f"/><ellipse cy="-69" rx="4.4" ry="2.2" fill="#6fd38a"/></g></g>`;
}

function brickCloud(x, y, s = 1) {
  let st = "";
  for (let n = 0; n < 4; n++)
    st += `<rect x="${-34 + n * 18}" y="-20" width="12" height="5" rx="1.5"/>`;
  return `<g ${at(x, y, s)} fill="#ffffff"><g opacity=".92">${st}<rect x="-40" y="-16" width="76" height="20" rx="3"/></g><rect x="-40" y="-2" width="76" height="6" rx="2" fill="#dbe6f7"/><g opacity=".9">${`<rect x="-14" y="-38" width="12" height="5" rx="1.5"/><rect x="4" y="-38" width="12" height="5" rx="1.5"/>`}<rect x="-20" y="-34" width="40" height="18" rx="3"/></g></g>`;
}

function blueprint(i, j, a, b, label) {
  const pts = [P(i, j), P(i + a, j), P(i + a, j + b), P(i, j + b)];
  const [cx, cy] = P(i + a / 2, j + b / 2);
  let grid = "";
  for (let u = 1; u < a; u++)
    grid += `M${P(i + u, j).join(" ")}L${P(i + u, j + b).join(" ")}`;
  for (let v = 1; v < b; v++)
    grid += `M${P(i, j + v).join(" ")}L${P(i + a, j + v).join(" ")}`;
  const pw = Math.round(label.length * 7.6 + 30);
  return `<g class="wa-locked">${poly(pts, "#ffffff", ` opacity=".22"`)}<path d="${grid}" stroke="#ffffff" stroke-width="1" opacity=".35"/>${poly(pts, "none", ` stroke="#ffffff" stroke-width="2.4" stroke-dasharray="8 6" ${A("wa-march", 3)}`)}<g ${at(cx, cy)}><rect x="${-pw / 2}" y="-14" width="${pw}" height="24" rx="12" fill="#1d4f9c" opacity=".78"/><text y="3" text-anchor="middle" class="wa-tag" fill="#ffffff">${label}</text></g></g>`;
}

function bHouse() {
  const door = poly(quadJ(15, 13.1, 13.9, 0.34, 2.4), "#2f6fdb");
  const winL =
    poly(quadJ(15, 12.3, 12.8, 1.2, 2.3), "#a8d8ff") +
    poly(quadJ(15, 14.2, 14.7, 1.2, 2.3), "#a8d8ff");
  const winR =
    poly(quadI(15, 12.6, 13.4, 1.2, 2.3), "#a8d8ff") +
    poly(quadI(15, 13.9, 14.6, 1.2, 2.3), "#a8d8ff");
  const [fx, fy] = P(12.5, 14.5, 5.34);
  return `${box(12, 12, 0.34, 3, 3, 3, "#f4f1e8", { stud: false })}${door}${winL}${winR}${box(11.8, 11.8, 3.34, 3.4, 3.4, 1, "#e3342f", { stud: false })}${box(12.3, 12.3, 4.34, 2.4, 2.4, 1, "#e3342f", { step: 1.2 })}${box(14.2, 12.2, 4.34, 0.8, 0.8, 2, "#9aa5b1", { stud: false })}${smoke(...P(14.6, 12.6, 6.6), "#ffffff", 0.9)}${flag(fx, fy, 30, "#f2c14e", 1, "#5b5b5b")}`;
}

function bStation() {
  const [gx, gy] = P(18, 11.5, 6.6);
  let teeth = "";
  for (let t = 0; t < 10; t++)
    teeth += `<rect x="-4" y="-27" width="8" height="8" rx="1.4" transform="rotate(${t * 36})"/>`;
  const belt = (c, dash, off) =>
    `<path d="M${P(19.1, 12.6, 1.6).join(" ")}L${P(19.1, 17.2, 0.6).join(" ")}" stroke="${c}" stroke-width="5" stroke-dasharray="${dash}" stroke-dashoffset="${off}" ${A("wa-belt", 1.6)}/>`;
  return `${box(16, 10.4, 0.34, 3, 3, 4, "#9aa5b1", { stud: false })}${poly(quadI(19, 11, 12.6, 0.34, 2.6), "#2b2b2b")}${poly(quadJ(13.4, 16.4, 18.6, 2.6, 3.4), "#f6c21c")}${box(15.8, 10.2, 4.34, 3.4, 3.4, 0.6, "#f6c21c")}${box(16.2, 10.6, 4.94, 0.9, 0.9, 2.4, "#e3342f", { stud: false })}${smoke(...P(16.65, 11.05, 7.6), "#e9eef5", 0.8)}<path d="M${P(19.1, 12.6, 1.4).join(" ")}L${P(19.1, 17.2, 0.4).join(" ")}" stroke="#3b3b3b" stroke-width="9" stroke-linecap="round"/>${belt("#e3342f", "6 22", 0)}${belt("#2f6fdb", "6 22", 9)}${belt("#f6c21c", "6 22", 18)}<g ${at(gx, gy)}><g ${A("wa-spin", 9)}>${pivot(28)}<g fill="#f6c21c">${teeth}<circle r="21"/></g><circle r="13" fill="#e0a800"/><circle r="6" fill="#9aa5b1"/><path d="M0-13V13M-13 0H13" stroke="#f6c21c" stroke-width="3"/></g></g>`;
}

function bTower(level) {
  const cols = [
    "#2f6fdb",
    "#f4f1e8",
    "#e3342f",
    "#f6c21c",
    "#2ea44f",
    "#2f6fdb",
    "#f4f1e8",
    "#e3342f",
  ];
  let t = "",
    k = 0.34;
  cols.forEach((c, n) => {
    const w = n < 5 ? 2.4 : 1.8,
      o = (2.4 - w) / 2;
    t += box(10.4 + o, 10.4 + o, k, w, w, 1.4, c, { stud: n === 7, step: 0.9 });
    if (n % 2 === 0)
      t += poly(
        quadJ(10.4 + o + w, 10.4 + o + 0.4, 10.4 + o + w - 0.4, k + 0.4, k + 1),
        "#bfe6ff",
      );
    k += 1.4;
  });
  const [x, y] = P(11.6, 11.6, k + 0.4);
  return `<g class="wa-reveal">${t}<g ${at(x, y)}><circle cy="-14" r="24" fill="#fff6b0" opacity=".35" ${A("wa-pulse", 2.6)}/><path d="M0 0V-34" stroke="#5b5b5b" stroke-width="2"/><circle cy="-14" r="11" fill="#bfe6ff" stroke="#ffffff" stroke-width="2"/><circle cy="-14" r="5" fill="#ffe27a" ${A("wa-glow", 1.2)}/><g ${at(0, -36)}><g ${A("wa-spin", 2.4)}>${pivot(16)}<path d="M-15-2h30v4h-30Z" fill="#e3342f"/></g><circle r="3" fill="#5b5b5b"/></g></g>${level ? "" : ""}</g>`;
}

function bCar(i, j, color, o) {
  const body = `${box(0, 0, 0, 2, 1, 0.8, color, { stud: false })}${box(0.6, 0.15, 0.8, 0.9, 0.7, 0.7, "#bfe6ff", { stud: false })}${box(0.5, 0.05, 1.5, 1.1, 0.9, 0.25, color, { step: 1 })}`;
  const wheel = (u, v) => {
    const [x, y] = P(u, v, 0.1);
    return `<ellipse cx="${x}" cy="${y}" rx="4" ry="4.4" fill="#222"/>`;
  };
  const [x0, y0] = P(0, 0);
  const [x, y] = P(i, j, 0.34);
  const { dx, dy } = vec(4.5, 0);
  return `<g ${at(x - x0, y - y0)}><g class="wa-drive" style="--wa-dx:${dx}px;--wa-dy:${dy}px;--wa-t:7s;--wa-o:-${o}s">${wheel(0.5, 1)}${wheel(1.6, 1)}${body}</g></g>`;
}

function bBoat(o = 0) {
  const [x0, y0] = P(0, 0);
  const [x, y] = P(31.4, 12.4, -0.2);
  const hull = `${poly([P(0, 0, 0), P(6, 0, 0), P(7.4, 1, 0), P(6, 2, 0), P(0, 2, 0)], "#c22f2a")}${poly([P(0, 2, -0.6), P(6, 2, -0.6), P(6, 2, 0.6), P(0, 2, 0.6)], "#e3342f")}${poly([P(6, 2, -0.6), P(7.4, 1, -0.2), P(7.4, 1, 0.8), P(6, 2, 0.6)], "#b8231f")}${poly([P(0, 0, 0.6), P(6, 0, 0.6), P(7.4, 1, 0.8), P(6, 2, 0.6), P(0, 2, 0.6)], "#f4f1e8")}${poly([P(0, 2, 0.1), P(6, 2, 0.1), P(6, 2, 0.3), P(0, 2, 0.3)], "#f4f1e8")}`;
  return `<g ${at(x - x0, y - y0)}><g ${A("wa-float", 3.6, o)}>${pivot(80)}${hull}${box(0.4, 0.3, 0.6, 1.4, 1.4, 1.6, "#f4f1e8", { stud: false })}${poly(quadI(1.8, 0.5, 1.5, 1.4, 2), "#2f6fdb")}${box(0.5, 0.4, 2.2, 1.2, 1.2, 0.3, "#2f6fdb")}${box(2.2, 0.2, 0.6, 2, 1.6, 1, "#2ea44f", { stud: false })}${box(4.3, 0.2, 0.6, 1.5, 1.6, 1, "#f6c21c", { stud: false })}${box(2.2, 0.2, 1.6, 2, 1.6, 1, "#2f6fdb", { stud: false })}</g></g>`;
}

function bCrane() {
  const [mx, my] = P(27.5, 10.5, 9.3);
  return `${box(27, 10, 0.34, 1, 1, 9, "#f6c21c", { stud: false })}<path d="M${P(27, 11, 0.4).join(" ")}L${P(28, 11, 9.3).join(" ")}M${P(28, 11, 0.4).join(" ")}L${P(27, 11, 9.3).join(" ")}" stroke="#c99a00" stroke-width="1.4"/><g ${at(mx, my)}><g ${A("wa-swing", 6)}>${pivot(120)}<path d="M-110 6 30-4v-7l-140 9Z" fill="#f6c21c"/><path d="M-110 6 30-11" stroke="#c99a00" stroke-width="1.2"/><rect x="18" y="-12" width="16" height="16" rx="2" fill="#5b5b5b"/><path d="M-96 5v52" stroke="#3b3b3b" stroke-width="1.4"/><g transform="translate(-96 70)"><rect x="-16" y="-13" width="32" height="15" fill="#e3342f"/><path d="M-16-6h32M-8-13v15M0-13v15M8-13v15" stroke="#b8231f" stroke-width="1.2"/></g></g></g>`;
}

function bricksScene(level) {
  const k = uid("b"),
    sky = `${k}-sky`,
    pat = `${k}-studs`,
    sea = `${k}-sea`;
  let o = `<defs><linearGradient id="${sky}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cfe0fb"/><stop offset="1" stop-color="#eef3ff"/></linearGradient><linearGradient id="${sea}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5aa2ec"/><stop offset="1" stop-color="#2f6fd0"/></linearGradient><pattern id="${pat}" patternUnits="userSpaceOnUse" width="28" height="14" x="${BX}" y="${BY}"><ellipse cx="0" cy="0" rx="4.4" ry="2.4" fill="#ffffff" opacity=".16"/><ellipse cx="14" cy="7" rx="4.4" ry="2.4" fill="#ffffff" opacity=".16"/><ellipse cx="28" cy="0" rx="4.4" ry="2.4" fill="#ffffff" opacity=".16"/><ellipse cx="0" cy="14" rx="4.4" ry="2.4" fill="#ffffff" opacity=".16"/><ellipse cx="28" cy="14" rx="4.4" ry="2.4" fill="#ffffff" opacity=".16"/></pattern></defs>`;
  o += `<rect x="-10" y="-10" width="980" height="500" fill="url(#${sky})"/>`;
  o += `<g ${A("wa-drift", 30)}>${brickCloud(120, 80, 1)}${brickCloud(820, 60, 0.8)}</g><g ${A("wa-drift", 40, 10)}>${brickCloud(700, 150, 0.6)}</g>`;
  o += flock(250, 150, "#3d5f9c", 3, 0.9, 26);
  const toyBoats = bToyBoat(28, -1, 0) + bToyBoat(4, 27, 6);
  // blue stud-sea baseplate
  const seaPts = [P(-4, -4), P(64, -4), P(64, 64), P(-4, 64)];
  o += poly(seaPts, `url(#${sea})`) + poly(seaPts, `url(#${pat})`);
  o += `<path d="M${P(-4, 64).join(" ")}L${P(-4, -4).join(" ")}L${P(64, -4).join(" ")}" fill="none" stroke="#8cc0f5" stroke-width="4"/>`;
  o +=
    [
      [2, 25],
      [10, 26],
      [26, 18],
      [24, 22],
      [33, 2],
      [36, 8],
      [6, 6],
    ]
      .map(
        ([i, j], n) =>
          `<path ${A("wa-wave", 4.5, n)} d="M${P(i, j).join(" ")}l28 14m10 5 14 7" stroke="#bfe0ff" stroke-width="3" stroke-linecap="round" opacity=".7"/>`,
      )
      .join("") + toyBoats;
  // ── territory 2: parts valley (back-left)
  if (level >= 1) {
    let v = `${box(1, 10, 0, 8, 8, 0.34, "#dcc08a")}${bTree(1.5, 10.5, 0.34, 0.85, 1)}${bTree(3.5, 10.4, 0.34, 0.75, 2)}${box(5, 10.5, 0.34, 3, 2.5, 2.4, "#f28c28", { stud: false })}${poly(quadJ(13, 5.5, 7.5, 0.34, 2), "#3b2a1c")}${box(5.6, 12.4, 0.34, 0.8, 0.5, 0.5, "#e3342f", { stud: false })}${box(6.6, 12.4, 0.34, 0.8, 0.5, 0.8, "#2f6fdb", { stud: false })}${box(4.8, 10.3, 2.74, 3.4, 2.9, 0.4, "#2f6fdb", { step: 1 })}`;
    v += `${box(2, 15, 0.34, 2, 1, 1, "#e3342f")}${box(2.5, 14.6, 1.34, 1, 1, 1, "#f6c21c")}${box(5, 15.6, 0.34, 1, 2, 1, "#2ea44f")}${box(7, 14.4, 0.34, 1, 1, 1, "#f4f1e8")}${box(7, 16.4, 0.34, 1, 1, 2, "#8a4fd8")}`;
    v += `${bActor(4.6, 14.2, 0.34, minifig(2, "brick"), { ...vec(2.5, 2), t: 12 })}${bActor(6.4, 17.6, 0.34, minifig(3, "crate"), { ...vec(-3, -0.6), t: 14, d: 4 })}`;
    o += `<g class="wa-reveal">${shift(0, 2, v)}</g>`;
  } else o += blueprint(1, 12, 8, 8, "Чертёж: долина деталей");
  // ── main plate
  o += box(10, 10, 0, 10, 10, 0.34, "#5cb85c");
  if (level >= 4) o += bTower(level);
  o += bTree(17.4, 10.2, 0.34, 0.9, 1);
  if (level >= 2) o += `<g class="wa-reveal">${bStation()}</g>`;
  o += bHouse();
  o += bTree(10.6, 15, 0.34, 1, 2) + bDog(18.2, 15.6, 0.34);
  o += box(10, 17, 0.34, 10, 1.4, 0.12, "#7d8794", { stud: false });
  o += `<path d="M${P(10.6, 17.7, 0.46).join(" ")}L${P(19.6, 17.7, 0.46).join(" ")}" stroke="#ffe27a" stroke-width="2" stroke-dasharray="10 8"/>`;
  o +=
    poly(quadJ(15, 12.9, 14.1, 0.34, 0.46), "#7d8794") +
    `<path d="M${P(13.5, 15.1, 0.46).join(" ")}L${P(13.5, 17, 0.46).join(" ")}" stroke="#bfc6cf" stroke-width="10"/>`;
  if (level >= 2)
    o += `<g class="wa-reveal">${bActor(17.2, 14.6, 0.34, minifig(4, "brick"), { ...vec(0, 2), t: 9 })}${bActor(15.6, 19.2, 0.34, minifig(5, "wrench"), { ...vec(2.6, 0), t: 13, d: 3 })}</g>`;
  o += bActor(12.2, 16.2, 0.46, minifig(0), { ...vec(3.2, 0), t: 15 });
  o += bActor(16, 16.4, 0.46, minifig(1, "brick"), {
    ...vec(-2.6, 0.6),
    t: 12,
    d: 5,
  });
  if (level >= 4)
    o += `<g class="wa-reveal">${bCar(11, 17.2, "#e3342f", 0)}${bCar(14.6, 17.2, "#2f6fdb", 2.5)}${bActor(12.4, 19.4, 0.34, minifig(8, "flag"), { a: "wa-dance", t: 0.8 })}${bActor(14.2, 19.6, 0.34, minifig(9), { a: "wa-dance", t: 0.8, d: 0.4 })}</g>`;
  // ── territory 3: cargo port (right-front)
  if (level >= 3) {
    o += `<g class="wa-reveal">${box(20, 10.3, 0.1, 2, 1.4, 0.24, "#9aa5b1", { stud: false })}<path d="M${P(20, 10.3, 0.6).join(" ")}L${P(22, 10.3, 0.6).join(" ")}M${P(20, 11.7, 0.6).join(" ")}L${P(22, 11.7, 0.6).join(" ")}" stroke="#f6c21c" stroke-width="2"/>`;
    let v = `${box(22, 9, 0, 8, 7, 0.34, "#c3c9cf")}<path d="M${P(22, 16, 0.34).join(" ")}L${P(30, 16, 0.34).join(" ")}L${P(30, 9, 0.34).join(" ")}" fill="none" stroke="#f6c21c" stroke-width="3" stroke-dasharray="6 6"/>${bCrane()}`;
    v += `${box(23, 13, 0.34, 2, 1, 1, "#e3342f", { stud: false })}${box(23, 14.2, 0.34, 2, 1, 1, "#2f6fdb", { stud: false })}${box(23, 13.6, 1.34, 2, 1, 1, "#2ea44f", { stud: false })}${box(25.6, 14.4, 0.34, 2, 1, 1, "#f28c28", { stud: false })}`;
    v += `${bActor(24.4, 11.2, 0.34, minifig(6, "wrench"), { ...vec(2.4, 0), t: 11 })}${bActor(28.6, 14.6, 0.34, minifig(7, "crate"), { ...vec(-2.4, 0.5), t: 13, d: 4 })}`;
    o += `${shift(0, -4, v)}${shift(0, -7, bBoat(0))}</g>`;
  } else o += blueprint(22, 5, 8, 7, "Чертёж: грузовой порт");
  if (level >= 4) {
    o += `<g class="wa-reveal"><g ${at(150, 120)}><g ${A("wa-sail", 22)}><g ${A("wa-float", 4)}>${pivot(60)}<rect x="-52" y="-16" width="104" height="32" rx="16" fill="#f4f1e8"/><path d="M-36-16h72" stroke="#e3342f" stroke-width="6"/><path d="M-44 0h88" stroke="#2f6fdb" stroke-width="3" opacity=".5"/><path d="M48-4l14-10v28l-14-10Z" fill="#e3342f"/><rect x="-14" y="16" width="28" height="10" rx="2" fill="#f6c21c"/><text y="6" text-anchor="middle" class="wa-tag" fill="#2f6fdb" font-size="11">БРИК</text></g></g></g>`;
    const balloons = [
      ["#e3342f", 476, 120],
      ["#f6c21c", 520, 86],
      ["#2f6fdb", 556, 136],
      ["#8a4fd8", 318, 128],
    ];
    o += balloons
      .map(
        ([c, x, y], n) =>
          `<g ${at(x, y)}><g ${A("wa-float", 3 + n * 0.4, n)}>${pivot(30)}<path d="M0 12q-4 10 2 22" fill="none" stroke="#5b5b5b" stroke-width="1"/><ellipse rx="10" ry="12" fill="${c}"/><ellipse cx="-3" cy="-4" rx="3" ry="4" fill="#fff" opacity=".4"/><path d="M-2 12h4l-2 3Z" fill="${c}"/></g></g>`,
      )
      .join("");
    o += `</g>`;
  }
  return o;
}

/* ───────────────────────── 3. КУБОЛЕСЬЕ — voxel ─────────────────────────
 * Side-on diorama slice of cube columns (oblique projection), pixel textures
 * via SVG patterns, stepped mountains with atmospheric haze, amethyst crystals.
 */

const VB = 24,
  VDX = 10,
  VDY = -8,
  VBASE = 480;

function vTile(id, base, a, b, seed, size = 24, extra = "") {
  const r = rng(seed);
  let sp = "";
  for (let n = 0; n < 8; n++)
    sp += `<rect x="${Math.floor(r() * 6) * 4}" y="${Math.floor(r() * 6) * 4}" width="4" height="4" fill="${n % 2 ? a : b}"/>`;
  const tf = size !== 24 ? ` patternTransform="scale(${r1(size / 24)})"` : "";
  return `<pattern id="${id}" patternUnits="userSpaceOnUse" width="24" height="24"${tf}><rect width="24" height="24" fill="${base}"/>${sp}${extra}<path d="M0 23.5h24M23.5 0v24" stroke="#000" stroke-opacity=".13"/></pattern>`;
}

function vDefs(k) {
  const g = (extra) => extra;
  const grassTop = `<rect width="24" height="6" fill="#6bb04a"/><rect x="4" y="6" width="4" height="4" fill="#6bb04a"/><rect x="16" y="6" width="4" height="3" fill="#6bb04a"/><rect x="12" width="4" height="4" fill="#82c45a"/>`;
  const snowTop = `<rect width="24" height="7" fill="#f4f8ff"/><rect x="8" y="7" width="4" height="4" fill="#f4f8ff"/><rect x="20" y="7" width="4" height="3" fill="#f4f8ff"/>`;
  const planks = `<path d="M0 8h24M0 16h24" stroke="#7c5531" stroke-width="1.4"/><rect x="10" y="1" width="2" height="2" fill="#7c5531"/>`;
  const waterL = `<path d="M2 6h8M14 14h8M4 19h6" stroke="#bfe6ff" stroke-width="2" opacity=".6"/>`;
  return [
    vTile(`${k}-dirt`, "#8a5d3b", "#74492b", "#a2734c", 1),
    vTile(`${k}-gside`, "#8a5d3b", "#74492b", "#a2734c", 2, 24, g(grassTop)),
    vTile(`${k}-stone`, "#8b9197", "#767c82", "#a3a9ae", 3),
    vTile(`${k}-sand`, "#e6cf93", "#d6bb7a", "#f2e0ae", 4),
    vTile(`${k}-leaf`, "#3f8f3a", "#2f7430", "#5aa84a", 5),
    vTile(`${k}-plank`, "#b88a52", "#a87a44", "#c99a62", 6, 24, planks),
    vTile(`${k}-purple`, "#8c6dc2", "#7558ad", "#a488d6", 7),
    vTile(
      `${k}-brick`,
      "#9aa0a6",
      "#80868c",
      "#b1b6bb",
      8,
      24,
      `<path d="M0 12h24M12 0v12M4 12v12" stroke="#6f757a" stroke-width="1.2"/>`,
    ),
    vTile(`${k}-water`, "#3f9ad8", "#3489c4", "#58aee6", 9, 24, waterL),
    // back-layer (16 px) variants
    vTile(`${k}-bdirt`, "#8a6a52", "#7c5e48", "#9a7a62", 10, 16),
    vTile(`${k}-bgside`, "#8a6a52", "#7c5e48", "#9a7a62", 11, 16, grassTop),
    vTile(`${k}-bstone`, "#8f969c", "#7f868c", "#a2a8ad", 12, 16),
    vTile(`${k}-bsnow`, "#8f969c", "#7f868c", "#a2a8ad", 13, 16, snowTop),
  ].join("");
}

/** Cuboid in oblique projection: front face (pattern), top face and right side. */
function vbox(x, y, w, h, front, top, side, d = 1) {
  const dx = VDX * d,
    dy = VDY * d;
  return `<path d="M${x + w} ${y}l${dx} ${dy}v${h}l${-dx} ${-dy}Z" fill="${side}"/><path d="M${x} ${y}l${dx} ${dy}h${w}l${-dx} ${-dy}Z" fill="${top}"/><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${front}"/>`;
}

const V_FRONT = [
  10, 10, 9, 9, 9, 8, 7, 6, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 3, 3, 2, 1,
  1, 1, 1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 4, 4, 4,
];
const vType = (c) => (c >= 21 && c <= 32 ? "sand" : "grass");
const vTop = (c) => VBASE - V_FRONT[c] * VB;

function vColumn(
  c,
  u,
  size = VB,
  h = V_FRONT[c],
  type = vType(c),
  base = VBASE,
  back = false,
) {
  const x = c * size,
    yTop = base - h * size,
    d = size / VB,
    dx = VDX * d,
    dy = VDY * d;
  const pre = back ? "b" : "";
  const topF = { grass: "gside", sand: "sand", stone: "stone", snow: "snow" }[
    type
  ];
  const topPat = back
    ? `url(#${u}-b${type === "grass" ? "gside" : type === "snow" ? "snow" : "stone"})`
    : `url(#${u}-${topF})`;
  const midPat = back
    ? `url(#${u}-${type === "grass" ? "bdirt" : "bstone"})`
    : type === "sand"
      ? `url(#${u}-sand)`
      : `url(#${u}-dirt)`;
  const lowPat = back ? `url(#${u}-bstone)` : `url(#${u}-stone)`;
  const topC = {
    grass: "#8fd06a",
    sand: "#f0dca6",
    stone: "#b3b8bd",
    snow: "#f6f9ff",
  }[type];
  const mid = Math.min(2, h - 1);
  let s = `<path d="M${x + size} ${yTop}l${dx} ${dy}V${base + dy}l${-dx} ${-dy}Z" fill="${back ? "#6d6a6e" : "#4a3524"}"/><path d="M${x + size} ${yTop}l${dx} ${dy}v${size}l${-dx} ${-dy}Z" fill="${type === "grass" ? (back ? "#6d8a5f" : "#4f8a39") : type === "snow" ? "#c9d3df" : "#b29a62"}"/>`;
  s += `<path d="M${x} ${yTop}l${dx} ${dy}h${size}l${-dx} ${-dy}Z" fill="${topC}"/>`;
  s += `<rect x="${x}" y="${yTop}" width="${size}" height="${size}" fill="${topPat}"/>`;
  if (mid > 0)
    s += `<rect x="${x}" y="${yTop + size}" width="${size}" height="${mid * size}" fill="${midPat}"/>`;
  if (h - 1 - mid > 0)
    s += `<rect x="${x}" y="${yTop + (1 + mid) * size}" width="${size}" height="${(h - 1 - mid) * size}" fill="${lowPat}"/>`;
  return pre ? s : s;
}

const V_SKIN = ["#e9b98f", "#c98e64", "#f2cfae", "#a8704d"];
const V_SHIRT = ["#2fa39a", "#e07a3a", "#7c5cc4", "#c94a4a", "#3f74c9"];
const V_PROPS = {
  pick: `<g transform="translate(8 -14)"><g ${A("wa-chop", 0.9)}>${pivot(19)}<rect x="-1.2" y="-16" width="2.4" height="16" fill="#8a5d3b"/><path d="M-8-17h16v3H-8Z" fill="#a3a9ae"/></g></g>`,
  crystal: `<path d="M12-24l4 6-4 6-4-6Z" fill="#b69af3"/><path d="M12-24l4 6h-8Z" fill="#d9c9ff"/>`,
  glow: `<rect x="7" y="-22" width="10" height="10" fill="#c7b2ff"/><rect x="5" y="-24" width="14" height="14" fill="#c7b2ff" opacity=".3"/>`,
  torch: `<rect x="8" y="-26" width="2.5" height="14" fill="#8a5d3b"/><rect x="7" y="-31" width="5" height="5" fill="#ffcf4a" ${A("wa-glow", 0.8)}/>`,
  glass: `<rect x="6" y="-28" width="12" height="3.4" fill="#6b4a32" transform="rotate(-18 6 -28)"/>`,
  crate: `<rect x="7" y="-22" width="12" height="11" fill="#b88a52"/><path d="M7-17h12" stroke="#7c5531"/>`,
  none: "",
};

function voxelite(i, prop = "none") {
  const skin = V_SKIN[i % 4],
    shirt = V_SHIRT[i % 5],
    hair = ["#4a3020", "#2b2b2b", "#c98a3a", "#7a3b20"][i % 4];
  return `<rect x="-9" y="-1" width="18" height="3" fill="#1d2a1a" opacity=".22"/><g class="wa-gait"><rect x="-5" y="-10" width="4.4" height="10" fill="#3b4a6b"/><rect x=".6" y="-10" width="4.4" height="10" fill="#334260"/><rect x="-9" y="-19" width="4" height="9" fill="#6b4a32"/><rect x="-6" y="-22" width="12" height="12" fill="${shirt}"/><rect x="-6" y="-14" width="12" height="2" fill="${shade(shirt, -0.3)}"/><rect x="6" y="-22" width="3.4" height="9" fill="${shade(shirt, -0.15)}"/><rect x="6" y="-13" width="3.4" height="3" fill="${skin}"/><rect x="-6" y="-34" width="12" height="12" fill="${skin}"/><rect x="-6" y="-34" width="12" height="4" fill="${hair}"/><rect x="-6" y="-30" width="2" height="3" fill="${hair}"/><rect x="-3.6" y="-28" width="2.4" height="2.4" fill="#ffffff"/><rect x="1.4" y="-28" width="2.4" height="2.4" fill="#ffffff"/><rect x="-2.4" y="-28" width="1.2" height="2.4" fill="#2a2140"/><rect x="2.6" y="-28" width="1.2" height="2.4" fill="#2a2140"/><rect x="-2" y="-24.6" width="4" height="1.2" fill="#9c5a44"/>${V_PROPS[prop] || ""}</g>`;
}

function vTree(x, y, u, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><rect x="-6" y="-36" width="12" height="36" fill="url(#${u}-plank)"/><rect x="-6" y="-36" width="12" height="36" fill="#6b4a2e" opacity=".55"/><g ${A("wa-sway", 6, o)}>${pivot(84)}${vbox(-26, -84, 52, 40, `url(#${u}-leaf)`, "#5fb14f", "#2c6a2a", 1.2)}${vbox(-14, -100, 28, 18, `url(#${u}-leaf)`, "#6fc35a", "#2c6a2a", 0.9)}<rect x="10" y="-70" width="6" height="6" fill="#d94a4a"/></g></g>`;
}

function vCrystal(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><rect x="-16" y="-34" width="32" height="32" fill="#b69af3" opacity=".22" ${A("wa-shimmer", 2.6, o)}/><path d="M-4 0V-26l6-8 6 8V0Z" fill="#9b7be0"/><path d="M2-34l6 8V0H2Z" fill="#7c5cc4"/><path d="M-12 0V-14l4-6 4 6V0Z" fill="#b69af3"/><path d="M8 0V-12l4-5 4 5V0Z" fill="#a488d6"/><path d="M-2-26 2-32" stroke="#efe6ff" stroke-width="2"/></g>`;
}

function vSheep(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><rect x="-12" y="-6" width="4" height="6" fill="#3a3a3a"/><rect x="6" y="-6" width="4" height="6" fill="#3a3a3a"/><rect x="-14" y="-20" width="26" height="15" fill="#f4f1ea"/><rect x="-10" y="-20" width="4" height="4" fill="#ddd8cc"/><rect x="2" y="-14" width="4" height="4" fill="#ddd8cc"/><g ${at(12, -16)}><g ${A("wa-graze", 3.4, o)}>${pivot(12)}<rect x="0" y="-4" width="10" height="10" fill="#3a3a3a"/><rect x="5" y="-1" width="2" height="2" fill="#fff"/><rect x="-1" y="-6" width="4" height="3" fill="#f4f1ea"/></g></g></g>`;
}

function vRaft(x, y, s = 1, sail = "#f4f1ea", o = 0, u = "") {
  return `<g ${at(x, y, s)}><g ${A("wa-float", 3.2, o)}>${pivot(50)}<rect x="-26" y="-6" width="52" height="8" fill="url(#${u}-plank)"/><rect x="-26" y="-6" width="52" height="3" fill="#d0a56c"/><rect x="-1.5" y="-46" width="3" height="40" fill="#6b4a2e"/><rect x="2" y="-42" width="22" height="26" fill="${sail}"/><rect x="2" y="-30" width="22" height="4" fill="${shade(sail, -0.15)}"/><g ${at(0, -46)}><rect ${A("wa-flag", 1.4)} x="0" y="0" width="12" height="7" fill="#7c5cc4"/></g></g></g>`;
}

function vSquareCloud(x, y, s = 1) {
  return `<g ${at(x, y, s)} fill="#ffffff"><rect x="-48" y="-12" width="96" height="16" opacity=".9"/><rect x="-28" y="-28" width="48" height="16" opacity=".9"/><rect x="-48" y="0" width="96" height="4" fill="#dfe9f5"/></g>`;
}

function vFog(c0, c1, yTop, yBot, label, seed) {
  const r = rng(seed);
  let sq = "";
  for (let y = yTop; y < yBot; y += 24)
    for (let c = c0; c < c1; c++) {
      if (r() < 0.12) continue;
      sq += `<rect x="${c * 24}" y="${y}" width="24" height="24" opacity="${r1(0.55 + r() * 0.35)}"/>`;
    }
  const cx = ((c0 + c1) / 2) * 24,
    cy = (yTop + yBot) / 2;
  return `<g class="wa-locked"><g ${A("wa-shimmer", 5)} fill="#f4f6ff">${sq}</g><g ${at(cx, cy)}><rect x="${-(label.length * 4 + 16)}" y="-14" width="${label.length * 8 + 32}" height="26" fill="#4b3a7a" opacity=".82"/><text y="4" text-anchor="middle" class="wa-tag" fill="#ffffff">${label}</text></g></g>`;
}

/** Cube cottage: plank walls, stepped amethyst roof, chimney with square smoke. */
function vHouse(u, x = 252, y = 382) {
  const X = (n) => x + n,
    Y = (n) => y + n;
  return `${vbox(X(0), Y(-72), 96, 72, `url(#${u}-plank)`, "#d0a56c", "#7c5531")}${vbox(X(-8), Y(-96), 112, 24, `url(#${u}-purple)`, "#a488d6", "#5d4596")}${vbox(X(16), Y(-120), 64, 24, `url(#${u}-purple)`, "#b49ae0", "#5d4596")}${vbox(X(74), Y(-136), 16, 40, `url(#${u}-stone)`, "#b3b8bd", "#6f757a", 0.6)}${smoke(X(82), Y(-146), "#eef0f6", 1, true)}<rect x="${X(36)}" y="${Y(-48)}" width="24" height="48" fill="#6b4a2e"/><rect x="${X(53)}" y="${Y(-26)}" width="3" height="3" fill="#e6c27a"/><rect x="${X(8)}" y="${Y(-60)}" width="20" height="18" fill="#ffe39a"/><rect x="${X(68)}" y="${Y(-60)}" width="20" height="18" fill="#ffe39a"/><path d="M${X(18)} ${Y(-60)}v18M${X(78)} ${Y(-60)}v18" stroke="#7c5531" stroke-width="2"/>`;
}

/** Mechanism workshop: stone block hall, square-tooth cog, crystal furnace and piston. */
function vWorkshop(u, x = 400, y = 382) {
  let teeth = "";
  for (let t = 0; t < 8; t++)
    teeth += `<rect x="-5" y="-27" width="10" height="10" transform="rotate(${t * 45})"/>`;
  return `${vbox(x, y - 72, 72, 72, `url(#${u}-brick)`, "#b8bdc2", "#6f757a")}<rect x="${x + 8}" y="${y - 64}" width="20" height="20" fill="#c7b2ff" ${A("wa-glow", 1.6)}/><g ${at(x + 48, y - 34)}><g ${A("wa-spin", 8)}>${pivot(28)}<g fill="#b88a52">${teeth}<rect x="-19" y="-19" width="38" height="38"/></g><rect x="-8" y="-8" width="16" height="16" fill="#6b4a2e"/></g></g>${vbox(x + 56, y - 100, 12, 28, `url(#${u}-stone)`, "#b3b8bd", "#6f757a", 0.6)}${smoke(x + 62, y - 106, "#eef0f6", 0.9, true)}<g ${at(x + 90, y)}><rect x="-10" y="-14" width="20" height="14" fill="#5b5f66"/><g ${A("wa-piston", 1.2)}><rect x="-3" y="-44" width="6" height="22" fill="#9aa0a6"/><rect x="-9" y="-26" width="18" height="8" fill="#6b7077"/></g><rect x="-6" y="-20" width="12" height="6" fill="#c7b2ff" ${A("wa-glow", 1.2)}/></g>`;
}

function voxelScene(level) {
  const u = uid("v");
  let o = `<defs><linearGradient id="${u}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bfe3f7"/><stop offset=".7" stop-color="#e9ecfb"/><stop offset="1" stop-color="#f3e6fb"/></linearGradient><linearGradient id="${u}-fall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8fd3ff"/><stop offset="1" stop-color="#5fb4ea"/></linearGradient>${vDefs(u)}</defs>`;
  o += `<rect x="-10" y="-10" width="980" height="500" fill="url(#${u}-sky)"/>`;
  // square sun with stepped halo
  o += `<g ${at(792, 78)}><rect x="-44" y="-44" width="88" height="88" fill="#fff6c8" opacity=".35"/><rect x="-32" y="-32" width="64" height="64" fill="#fff3b0" opacity=".55"/><rect x="-22" y="-22" width="44" height="44" fill="#fff1a0"/></g>`;
  o += `<g ${A("wa-drift", 32)}>${vSquareCloud(130, 70, 1)}${vSquareCloud(560, 50, 0.8)}</g><g ${A("wa-drift", 44, 9)}>${vSquareCloud(900, 140, 0.7)}</g>`;
  // pixel birds
  let birds = "";
  for (let n = 0; n < 3; n++)
    birds += `<g ${at(n * 18, (n % 2) * 8)}><path ${A("wa-flap", 0.5 + n * 0.06, n * 0.2)} d="M-8-3h4v3h8v-3h4" fill="none" stroke="#4a4f6b" stroke-width="2.6"/></g>`;
  o += `<g ${at(420, 120)}><g ${A("wa-glide", 24)}>${birds}</g></g>`;
  // back mountains (16 px cubes) + haze
  const hb = (c) =>
    Math.max(
      3,
      Math.round(
        Math.max(
          19 - Math.abs(c - 14) * 1.5,
          12 - Math.abs(c - 45) * 1.3,
          6 - Math.abs(c - 30) * 0.5,
        ),
      ),
    );
  let back = "";
  for (let c = 0; c < 61; c++) {
    const h = hb(c);
    back += vColumn(
      c,
      u,
      16,
      h,
      h >= 16 ? "snow" : h >= 11 ? "stone" : "grass",
      400,
      true,
    );
  }
  o +=
    back +
    `<rect x="-10" y="0" width="980" height="420" fill="#e3ecfb" opacity=".38"/><rect x="-10" y="396" width="980" height="90" fill="#8ec8ea"/><path d="M-10 396h980" stroke="#d4eeff" stroke-width="3"/>`;
  // waterfall from the right mountain shoulder into the far lake
  o += `<rect x="656" y="282" width="16" height="116" fill="url(#${u}-fall)"/><path ${A("wa-fall", 1.1)} d="M660 282v116m8-116v116" stroke="#e6f6ff" stroke-width="2.4" stroke-dasharray="10 14"/><rect x="648" y="394" width="32" height="6" fill="#ffffff" opacity=".8" ${A("wa-glow", 0.9)}/>`;
  if (level >= 4) {
    let rays = "";
    for (let n = 0; n < 8; n++)
      rays += `<rect x="-3" y="-120" width="6" height="84" fill="#e9dcff" opacity=".55" transform="rotate(${n * 45})"/>`;
    o += `<g class="wa-reveal"><g ${at(236, 74)}><g ${A("wa-spin", 30)}>${pivot(124)}${rays}</g><rect x="-34" y="-34" width="68" height="68" fill="#c7b2ff" opacity=".35" ${A("wa-pulse", 2.4)}/></g>${vCrystal(236, 96, 1.7)}</g>`;
  }
  // front terrain
  let front = "";
  for (let c = 0; c < 40; c++) {
    if (c >= 24 && c <= 31) front += vColumn(c, u, VB, 1, "sand");
    else front += vColumn(c, u);
  }
  o += front;
  // water body of the bay
  o += `<rect x="576" y="436" width="192" height="44" fill="url(#${u}-water)" opacity=".86"/><path d="M576 436l10-8h192l-10 8Z" fill="#8fd0f5" opacity=".9"/><path ${A("wa-wave", 3.5)} d="M590 446h20m40 6h24m30-8h18" stroke="#d8f1ff" stroke-width="3"/>`;
  o += `<g ${at(700, 438)}><g ${A("wa-hop", 1.6)}><rect x="-7" y="-6" width="12" height="6" fill="#f28c3a"/><rect x="5" y="-8" width="4" height="10" fill="#f28c3a"/><rect x="-5" y="-5" width="2" height="2" fill="#2a2140"/></g></g>`;
  // ── territory 2: crystal terrace (left)
  if (level >= 1)
    o += `<g class="wa-reveal">${vTree(26, 236, u, 0.8, 1)}<rect x="52" y="290" width="40" height="46" fill="#2a2140"/><path d="M50 336v-48h44v48" fill="none" stroke="#b88a52" stroke-width="5"/>${vCrystal(70, 334, 0.7, 1)}${vCrystal(108, 262, 1, 0)}${vCrystal(138, 286, 0.75, 1.3)}${vSheep(166, 334, 1, 0)}${actor(56, 238, voxelite(2, "pick"), { a: "wa-idle", t: 3 })}${actor(196, 358, voxelite(3, "crystal"), { dx: 40, dy: 24, t: 11 })}</g>`;
  else o += vFog(0, 9, 216, 360, "Кубический туман", 21);
  // ── valley: camp
  o += vTree(228, 382, u, 1, 2);
  if (level >= 2) {
    o += `<g class="wa-reveal">${vWorkshop(u)}</g>`;
  } else o += vTree(470, 382, u, 0.9, 3);
  // house
  o += vHouse(u);
  // campfire (pixel flames)
  o += `<g ${at(374, 382)}><rect x="-18" y="-24" width="36" height="28" fill="#ffcf4a" opacity=".2" ${A("wa-glow", 1.8)}/><rect x="-12" y="-4" width="24" height="5" fill="#6b4a2e"/><g ${A("wa-flicker", 0.6)}><rect x="-8" y="-12" width="16" height="8" fill="#ff8a3a"/><rect x="-4" y="-20" width="8" height="8" fill="#ffb347"/><rect x="-2" y="-12" width="4" height="6" fill="#ffe08a"/></g></g>`;
  if (level >= 2)
    o += `<g class="wa-reveal">${actor(470, 384, voxelite(4, "glow"), { dx: -64, t: 12 })}${actor(522, 406, voxelite(0, "crate"), { dx: 30, t: 9, d: 3 })}</g>`;
  o += actor(236, 384, voxelite(0, "torch"), { dx: 44, t: 14 });
  o += actor(420, 384, voxelite(1), { dx: -26, t: 11, d: 5 });
  // ── territory 3: explorers' bay (bridge + right bank)
  if (level >= 3) {
    let posts = "";
    for (let x = 560; x <= 776; x += 54)
      posts += `<rect x="${x}" y="392" width="6" height="46" fill="#6b4a2e"/>`;
    o += `<g class="wa-reveal">${posts}${vbox(528, 382, 264, 10, `url(#${u}-plank)`, "#d0a56c", "#7c5531", 0.8)}<path d="M534 382v-14h252v14M534 368h252" fill="none" stroke="#7c5531" stroke-width="2"/>${vRaft(612, 446, 0.9, "#f4f1ea", 0, u)}${vRaft(746, 450, 0.75, "#f2c14e", 1.4, u)}`;
    o += `<g ${at(860, 382)}><path d="M-34 0h68L0-46Z" fill="#e07a3a"/><path d="M0-46 34 0h-10L0-34Z" fill="#b85f2a"/><path d="M-8 0 0-16 8 0Z" fill="#3a2a1c"/></g>${flag(906, 382, 54, "#7c5cc4", 1, "#6b4a2e")}${vTree(934, 382, u, 0.75, 1)}<rect x="808" y="368" width="14" height="14" fill="url(#${u}-plank)"/>`;
    o += `${actor(830, 384, voxelite(2, "glass"), { a: "wa-idle", t: 4 })}${actor(780, 382, voxelite(3), { dx: -150, dy: 0, t: 18, d: 4 })}</g>`;
  } else o += vFog(32, 40, 312, 408, "Неизведанный берег", 33);
  // ── festival: floating light cubes, guest ship, dancers
  if (level >= 4) {
    const cubes = [
      [268, 220],
      [312, 196],
      [360, 230],
      [410, 200],
      [462, 236],
      [520, 208],
      [580, 240],
      [640, 214],
    ];
    o += `<g class="wa-reveal">${cubes.map(([x, y], n) => `<g ${at(x, y)}><g ${A("wa-float", 3 + (n % 3) * 0.6, n * 0.7)}>${pivot(12)}<rect x="-9" y="-9" width="18" height="18" fill="${["#ffe27a", "#c7b2ff", "#9fe3ff"][n % 3]}" opacity=".35"/><rect x="-5" y="-5" width="10" height="10" fill="${["#ffe27a", "#c7b2ff", "#9fe3ff"][n % 3]}" ${A("wa-twinkle", 1.6, n * 0.4)}/></g></g>`).join("")}`;
    o += `<g ${at(680, 444)}><g ${A("wa-sail", 16)}><g ${A("wa-float", 3.8)}>${pivot(70)}<path d="M-50-14h100l-12 18h-76Z" fill="#8a5d3b"/><rect x="-46" y="-18" width="92" height="5" fill="#d0a56c"/><rect x="-2" y="-80" width="4" height="64" fill="#6b4a2e"/><rect x="4" y="-74" width="38" height="44" fill="#8c6dc2"/><rect x="4" y="-58" width="38" height="6" fill="#c7b2ff"/><rect x="-36" y="-64" width="32" height="36" fill="#f4f1ea"/><g ${at(0, -80)}><rect ${A("wa-flag", 1.3)} x="0" y="0" width="16" height="9" fill="#ffe27a"/></g></g></g></g>`;
    o += `${actor(296, 384, voxelite(4), { a: "wa-dance", t: 0.8 })}${actor(330, 384, voxelite(1, "torch"), { a: "wa-dance", t: 0.8, d: 0.4 })}</g>`;
  }
  return o;
}

/* ───────────────────────── 4. БАНАНОВЫЙ ЗАЛИВ — helpers ─────────────────────────
 * Bright tropical lagoon, bouncy rounded shapes, saturated turquoise + banana
 * yellow. Inhabitants are original teardrop "непоседы" with a leaf sprout —
 * no goggles, no overalls, never human silhouettes.
 */

const H_OUTFIT = ["#4c7bd9", "#e5527a", "#2fb39a", "#8a5bd6", "#f08a3c"];
const H_PROPS = {
  banana: `<path d="M9-20q8 2 9 12q-4-7-10-8Z" fill="#ffe14a" stroke="#c99a12" stroke-width="1"/>`,
  bunch: `<g transform="translate(13 -16)"><path d="M-5-6q3 9 10 7M-4-8q5 9 11 5M-2-9q6 7 11 2" fill="none" stroke="#ffd21f" stroke-width="3.4" stroke-linecap="round"/><path d="M-4-9h5" stroke="#6b8a2e" stroke-width="2"/></g>`,
  cup: `<g transform="translate(12 -16)"><path d="M-4-6h8l-1.4 10h-5.2Z" fill="#ff9ec4"/><path d="M-4-6h8" stroke="#fff" stroke-width="1.4"/><path d="M1-6 4-13" stroke="#2fb39a" stroke-width="1.4"/><circle cx="-1" cy="-7" r="1.6" fill="#ffe14a"/></g>`,
  crate: `<g transform="translate(13 -18)"><rect x="-7" y="-5" width="14" height="10" rx="1" fill="#c8894b"/><path d="M-7 0h14" stroke="#8f5a2c"/><path d="M-5-5q2-5 6-3m0 3q2-5 6-3" fill="none" stroke="#ffd21f" stroke-width="2.4" stroke-linecap="round"/></g>`,
  rod: `<path d="M8-16 30-44" stroke="#8a5d3b" stroke-width="1.8" stroke-linecap="round"/><path d="M30-44q6 24 4 50" fill="none" stroke="#fff" stroke-width=".8"/>`,
  maracas: `<path d="M-12-16-18-26M12-16l6-10" stroke="#8a5d3b" stroke-width="1.6"/><circle cx="-19" cy="-28" r="3.4" fill="#e5527a"/><circle cx="19" cy="-28" r="3.4" fill="#2fb39a"/>`,
  none: "",
};

function neposeda(i, prop = "none") {
  const fit = H_OUTFIT[i % 5];
  const deco = [
    `<g ${at(5, -33)}><circle r="3.6" fill="#ff6f91"/><circle r="1.4" fill="#ffe14a"/></g>`,
    `<path d="M-11-30q11-6 22 0" fill="none" stroke="#e2b562" stroke-width="3" stroke-linecap="round"/><path d="M-7-31q7-10 14 0Z" fill="#f2cf7c"/><path d="M-7-31.5h14" stroke="#e5527a" stroke-width="1.4"/>`,
    `<g fill="#ffffff"><circle cx="-8" cy="-10" r="1.8"/><circle cx="-3" cy="-8.4" r="1.8" fill="#ff9ec4"/><circle cx="3" cy="-8.4" r="1.8"/><circle cx="8" cy="-10" r="1.8" fill="#ff9ec4"/></g>`,
  ][i % 3];
  return `<ellipse cy="1.5" rx="10.5" ry="2.8" fill="#0d4a5a" opacity=".2"/><g class="wa-gait-hop"><ellipse cx="-4.6" cy="-1.2" rx="3.8" ry="2.3" fill="#f08a3c"/><ellipse cx="4.6" cy="-1.2" rx="3.8" ry="2.3" fill="#f08a3c"/><path d="M-11-14q-6 2-6.4 7.4M11-14q6 2 6.4 7.4" fill="none" stroke="#f7c928" stroke-width="3.2" stroke-linecap="round"/><path d="M0-35C8-35 12.5-23 12.5-12.5 12.5-4 7 0 0 0S-12.5-4-12.5-12.5C-12.5-23-8-35 0-35Z" fill="#ffd93b"/><path d="M6-31c4 6 6.5 12 6.5 18.5C12.5-4 7 0 0 0c5-4 8.4-12 6-31Z" fill="#f2bf1f"/><path d="M-12.2-9.4h24.4C11.4-3.4 7 0 0 0s-11.4-3.4-12.2-9.4Z" fill="${fit}"/><path d="M-9-6h3m3 2h3m3-2h3" stroke="#ffffff" stroke-width="1.3" opacity=".6"/><path d="M0-35q-2-8-9.5-9 3 6.5 9.5 9Z" fill="#43a047"/><path d="M0-35q3-9.5 10.5-8.4Q6.6-37.4 0-35Z" fill="#66c25a"/><g class="wa-blink" style="--wa-t:${4 + (i % 3)}s;--wa-o:-${i * 0.7}s"><ellipse cx="-4.2" cy="-22" rx="3.8" ry="4.4" fill="#fff"/><ellipse cx="4.2" cy="-22" rx="3.8" ry="4.4" fill="#fff"/><circle cx="-3.4" cy="-21.4" r="2" fill="#2b2540"/><circle cx="5" cy="-21.4" r="2" fill="#2b2540"/><circle cx="-2.8" cy="-22.4" r=".7" fill="#fff"/><circle cx="5.6" cy="-22.4" r=".7" fill="#fff"/></g><circle cx="-8" cy="-15.6" r="2.1" fill="#ff8f7a" opacity=".55"/><circle cx="8" cy="-15.6" r="2.1" fill="#ff8f7a" opacity=".55"/><path d="M-3-14.4q3 3.2 6 0" fill="none" stroke="#7a3b2a" stroke-width="1.3" stroke-linecap="round"/>${deco}${H_PROPS[prop] || ""}</g>`;
}

function hPalm(x, y, s = 1, lean = 1, o = 0) {
  const L = lean;
  let fronds = "";
  [-160, -120, -75, -30, 10, 45].forEach((ang, n) => {
    const c = n % 2 ? "#2f9e55" : "#43b863";
    fronds += `<g transform="rotate(${ang})"><path d="M0 0Q22-16 52 2Q40 0 34 6 26 0 20 8 12 2 0 0Z" fill="${c}"/><path d="M0 0Q22-12 50 2" fill="none" stroke="#1f7a3f" stroke-width="1.2"/></g>`;
  });
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="22" ry="5" fill="#a07d3c" opacity=".25"/><path d="M-6 0C-4-32 ${2 * L}-62 ${12 * L}-92h${8 * L > 0 ? 9 : -9}C${8 * L}-60 4-30 6 0Z" fill="#b8874f"/><path d="M-5-14h10M-4-30h9M${-2 + 3 * L}-46h8M${2 + 6 * L}-62h8M${5 * L + 4}-78h7" stroke="#8f6331" stroke-width="2" stroke-linecap="round"/><g ${at(16 * L, -94)}><g ${A("wa-sway", 4.6, o)}>${pivot(56)}${fronds}<circle cx="-4" cy="5" r="4.4" fill="#7a5226"/><circle cx="4" cy="6" r="4.4" fill="#8f6331"/></g></g></g>`;
}

function hBananaPlant(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><ellipse cy="2" rx="20" ry="4" fill="#1d5a2a" opacity=".2"/><path d="M-4 0V-34h8V0Z" fill="#7fae3c"/><g ${A("wa-sway", 5, o)}>${pivot(60)}<path d="M0-34Q-30-56-46-34-26-40 0-34Z" fill="#3fae5a"/><path d="M0-34Q30-58 48-36 26-42 0-34Z" fill="#2f9e55"/><path d="M0-34Q-14-66-4-74 2-56 0-34Z" fill="#4cbf62"/><path d="M0-34Q18-64 30-66 18-50 0-34Z" fill="#43b863"/><path d="M0-34Q-30-56-46-34M0-34Q30-58 48-36" fill="none" stroke="#1f7a3f" stroke-width="1.2"/><g transform="translate(6 -30)"><path d="M0 0v8" stroke="#6b8a2e" stroke-width="2"/><path d="M-6 6q2 9 9 8M-2 4q3 9 10 6M2 3q5 7 10 1M-5 12q3 8 10 7" fill="none" stroke="#ffd21f" stroke-width="4" stroke-linecap="round"/><path d="M4 20q-2 8 2 12 3-5 0-12Z" fill="#a2386b"/></g></g></g>`;
}

function hStiltHut(x, y, s = 1, roof = "#e9a23b", wall = "#f2d8a2") {
  let fringe = "";
  for (let n = -46; n < 46; n += 8) fringe += `l4 7l4-7`;
  return `<g ${at(x, y, s)}><ellipse cy="3" rx="44" ry="6" fill="#0d4a5a" opacity=".15"/><path d="M-28 0v-28M28 0v-28M0 0v-28" stroke="#8f6331" stroke-width="5" stroke-linecap="round"/><path d="M-36-28h72v6h-72Z" fill="#b8874f"/><path d="M34-22l12 22M40-12h6M37-17h6M43-6h5" stroke="#8f6331" stroke-width="2.4" stroke-linecap="round"/><rect x="-26" y="-60" width="52" height="34" rx="6" fill="${wall}"/><path d="M-18-60v34M-10-60v34M-2-60v34M6-60v34M14-60v34" stroke="#d6b77a" stroke-width="1.4"/><circle cx="-12" cy="-44" r="7" fill="#7fd8e8" stroke="#8f6331" stroke-width="2"/><path d="M4-26v-20a8 8 0 0 1 16 0v20Z" fill="#8f6331"/><path d="M-46-56 0-94l46 38Z" fill="${roof}"/><path d="M-46-56${fringe}" fill="${shade(roof, -0.18)}"/><path d="M-30-62 0-88m10 8 18 14" stroke="${shade(roof, 0.25)}" stroke-width="2.4" opacity=".7"/><path d="M0-94v-10" stroke="#8f6331" stroke-width="2"/><path ${A("wa-flag", 1.3)} d="M1-104h12l-3 4 3 4H1Z" fill="#e5527a"/></g>`;
}

function hCrab(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><g class="wa-scuttle" style="--wa-dx:26px;--wa-t:5s;--wa-o:-${o}s"><path d="M-8-2l-6 4m6 0-6 5m22-9 6 4m-6 0 6 5" stroke="#d9473a" stroke-width="1.8" stroke-linecap="round"/><ellipse cy="-4" rx="10" ry="6.4" fill="#ef5a45"/><path d="M-6-9l-4-6M6-9l4-6" stroke="#d9473a" stroke-width="1.6"/><circle cx="-10" cy="-16" r="3.4" fill="#ef5a45"/><circle cx="10" cy="-16" r="3.4" fill="#ef5a45"/><circle cx="-3" cy="-11" r="1.8" fill="#fff"/><circle cx="3" cy="-11" r="1.8" fill="#fff"/><circle cx="-3" cy="-11" r=".9" fill="#222"/><circle cx="3" cy="-11" r=".9" fill="#222"/></g></g>`;
}

function hBananaBoat(x, y, s = 1, o = 0) {
  return `<g ${at(x, y, s)}><ellipse cy="8" rx="38" ry="4" fill="#ffffff" opacity=".4" ${A("wa-ripple", 3, o)}/><g ${A("wa-float", 3, o)}>${pivot(50)}<path d="M-40-10Q-34 10 0 10T40-12Q30 0 0 0T-40-10Z" fill="#ffd93b" stroke="#c99a12" stroke-width="1.5"/><path d="M-40-10l-5-3 2 5ZM40-12l5-4-1 6Z" fill="#6b4a2e"/><path d="M-26 2q26 6 52-2" fill="none" stroke="#f2bf1f" stroke-width="2"/><path d="M0 0v-40" stroke="#8f6331" stroke-width="2.2"/><path d="M2-38q20 14 0 32Z" fill="#ff9ec4"/><path d="M2-32q10 8 0 18" fill="none" stroke="#fff" stroke-width="2" opacity=".7"/></g></g>`;
}

function hFactory(x, y, s = 1) {
  let bubbles = "";
  [
    [-26, -112, 5],
    [-14, -126, 3.6],
    [-30, -136, 4.4],
    [-18, -150, 3],
  ].forEach(([bx, by, r], n) => {
    bubbles += `<circle ${A("wa-bubble", 3.2, n * 0.8)} cx="${bx}" cy="${by}" r="${r}" fill="#ffffff" opacity=".75" stroke="#ff9ec4" stroke-width="1"/>`;
  });
  return `<g ${at(x, y, s)}><ellipse cy="3" rx="64" ry="7" fill="#0d4a5a" opacity=".15"/><rect x="-44" y="-62" width="88" height="62" rx="18" fill="#ff8fb3"/><path d="M-44-40h88M-44-20h88" stroke="#e5527a" stroke-width="3"/><circle cx="-22" cy="-30" r="9" fill="#7fd8e8" stroke="#fff" stroke-width="3"/><path d="M8 0v-26a10 10 0 0 1 20 0V0Z" fill="#8a5bd6"/><path d="M-30-62h60l-8-48h-44Z" fill="#c9f2ff" opacity=".85" stroke="#ffffff" stroke-width="3"/><path d="M-27-80h54l-5-30h-44Z" fill="#ffd93b" opacity=".9"/><g ${at(0, -86)}><g ${A("wa-spin", 2.2)}>${pivot(20)}<path d="M0 0C10-14 20-2 12 6S-6 10-10 0" fill="none" stroke="#ff8fb3" stroke-width="4" stroke-linecap="round"/><path d="M0 0C-10 14-20 2-12-6" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/></g></g><rect x="-36" y="-118" width="72" height="10" rx="5" fill="#2fb39a"/><path d="M36-50q30 0 30 24v14" fill="none" stroke="#2fb39a" stroke-width="7" stroke-linecap="round"/><path d="M-44-30q-26 0-26 18v12" fill="none" stroke="#f08a3c" stroke-width="7" stroke-linecap="round"/>${bubbles}<g ${at(78, 0)}><path d="M-22 0v-30M22 0v-30" stroke="#8f6331" stroke-width="3"/><rect x="-24" y="-16" width="48" height="16" rx="3" fill="#f2d8a2"/><path d="M-28-30h56l-4 10h-48Z" fill="#fff"/><path d="M-22-30l-2 10m12-10-1 10m11-10v10m11-10 1 10m11-10 2 10" stroke="#2fb39a" stroke-width="5"/><g fill="#ff9ec4"><path d="M-16-22h7l-1 6h-5Z"/><path d="M-3-22h7l-1 6h-5Z" fill="#ffe14a"/><path d="M10-22h7l-1 6h-5Z" fill="#9be37a"/></g></g></g>`;
}

function hLightTower(x, y, beamA, beamB, s = 1) {
  return `<g ${at(x, y, s)}><g ${at(0, -126)}><g ${A("wa-beam", 5)}>${pivot(260)}<path d="M0-4 250-120v60L0 4Z" fill="url(#${beamA})"/></g><g ${A("wa-beam", 6.4, 2)}>${pivot(260)}<path d="M0-4 200-210v54L0 4Z" fill="url(#${beamB})"/></g></g><path d="M-16 0-6-120h12L16 0" fill="none" stroke="#5b5f8a" stroke-width="4"/><path d="M-14-10 12-40M-12-40 10-70M-9-70 8-100M14-10-12-40M12-40-10-70M9-70-8-100" stroke="#5b5f8a" stroke-width="2"/><rect x="-14" y="-134" width="28" height="12" rx="4" fill="#3d3f66"/><circle cx="-6" cy="-128" r="4" fill="#ffe14a" ${A("wa-glow", 0.9)}/><circle cx="6" cy="-128" r="4" fill="#ff8fb3" ${A("wa-glow", 1.1, 0.5)}/></g>`;
}

function hBunting(x1, y1, x2, y2, sag, n = 11) {
  const cx = (x1 + x2) / 2,
    cy = (y1 + y2) / 2 + sag;
  const cols = ["#e5527a", "#ffd93b", "#2fb39a", "#4c7bd9", "#f08a3c"];
  let f = "";
  for (let i = 1; i < n; i++) {
    const t = i / n,
      px = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t * t * x2,
      py = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t * t * y2;
    f += `<g ${at(px, py)}><path ${A("wa-flutter", 1.4, i * 0.3)} d="M-6 0h12L0 13Z" fill="${cols[i % 5]}"/></g>`;
  }
  return `<path d="M${x1} ${y1}Q${cx} ${cy} ${x2} ${y2}" fill="none" stroke="#5b5f8a" stroke-width="1.4"/>${f}`;
}

function hStage(x, y, s = 1) {
  return `<g ${at(x, y, s)}><rect x="-50" y="-22" width="100" height="22" rx="3" fill="#8a5bd6"/><path d="M-50-12h100" stroke="#ffd93b" stroke-width="3" stroke-dasharray="8 6"/><path d="M-50-22v-50M50-22v-50" stroke="#5b5f8a" stroke-width="3"/><path d="M-56-72h112v10q-7 8-14 0-7 8-14 0-7 8-14 0-7 8-14 0-7 8-14 0-7 8-14 0-7 8-14 0-7 8-14 0Z" fill="#e5527a"/><path d="M-42-72v10m28-10v10m28-10v10m28-10v10" stroke="#ffd93b" stroke-width="9"/></g>`;
}

function hConfetti(x, y, w, h, n, seed, size = 1) {
  const r = rng(seed);
  let c = "";
  for (let i = 0; i < n; i++)
    c += `<rect ${A("wa-confetti", 3.4 + r() * 2, r() * 4)} x="${r1(x + r() * w)}" y="${r1(y + r() * h)}" width="${r1((i % 2 ? 5 : 3) * size)}" height="${r1((i % 2 ? 3 : 5) * size)}" fill="${["#e5527a", "#ffd93b", "#2fb39a", "#4c7bd9", "#f08a3c"][i % 5]}"/>`;
  return c;
}

function helpersScene(level) {
  const u = uid("h");
  let o = `<defs><linearGradient id="${u}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fd3f0"/><stop offset=".6" stop-color="#c9f0f2"/><stop offset="1" stop-color="#fff1c2"/></linearGradient><linearGradient id="${u}-sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#58d3dc"/><stop offset=".5" stop-color="#2dbacd"/><stop offset="1" stop-color="#1797bd"/></linearGradient><linearGradient id="${u}-ba" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff59a" stop-opacity=".8"/><stop offset="1" stop-color="#fff59a" stop-opacity="0"/></linearGradient><linearGradient id="${u}-bb" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffb3d1" stop-opacity=".75"/><stop offset="1" stop-color="#ffb3d1" stop-opacity="0"/></linearGradient></defs>`;
  o += `<rect x="-10" y="-10" width="980" height="270" fill="url(#${u}-sky)"/>`;
  // sun with turning rays
  let rays = "";
  for (let n = 0; n < 12; n++)
    rays += `<path d="M-5-58h10l-5-20Z" fill="#ffd34d" transform="rotate(${n * 30})"/>`;
  o += `<g ${at(836, 96)}><g ${A("wa-spin", 40)}>${pivot(80)}${rays}</g><circle r="46" fill="#ffe36b"/><circle r="36" fill="#fff0a0"/></g>`;
  o += `<g ${A("wa-drift", 30)}>${puffCloud(190, 86, 1, "#ffffff", 0.9)}${puffCloud(560, 58, 0.8, "#fff8ea", 0.85)}</g>`;
  // parrots
  let parrots = "";
  ["#e5527a", "#2fb39a", "#ffd93b"].forEach((c, n) => {
    parrots += `<g ${at(n * 22, (n % 2) * 10)}><ellipse rx="6" ry="3.4" fill="${c}"/><circle cx="6" cy="-2" r="2.8" fill="${c}"/><path d="M8.4-2.4l3 1.2-3 1Z" fill="#3d3f66"/><path ${A("wa-flap", 0.4 + n * 0.05, n * 0.15)} d="M-2-2q-4-9-10-8 3 6 6 9Z" fill="${shade(c, -0.2)}"/><path d="M-6 1l-7 4" stroke="${c}" stroke-width="2.4"/></g>`;
  });
  o += `<g ${at(360, 130)}><g ${A("wa-glide", 20)}>${parrots}</g></g>`;
  // volcano island on the horizon
  o += `<path d="M30 252 104 196h14l8 6 8-6h12l84 56Z" fill="#7cb89a"/><path d="M104 196h42l-12 12-8-4-10 6Z" fill="#5a8f78"/>${smoke(126, 186, "#ffffff", 1.1)}`;
  // lagoon
  o += `<rect x="-10" y="248" width="980" height="240" fill="url(#${u}-sea)"/><path d="M-10 250h980" stroke="#e9fbff" stroke-width="2"/>`;
  o += [
    [60, 300],
    [520, 272],
    [900, 300],
    [40, 470],
    [600, 468],
    [860, 470],
    [300, 276],
  ]
    .map(
      ([x, y], n) =>
        `<path ${A("wa-wave", 4, n * 0.6)} d="M${x} ${y}q8-5 16 0t16 0" fill="none" stroke="#e9fbff" stroke-width="2.4" stroke-linecap="round" opacity=".7"/>`,
    )
    .join("");
  // ── territory 2: banana grove (left jungle hill)
  o += `<path d="M-10 412C6 336 80 292 160 290c74-2 116 40 126 92 2 18-20 30-50 32H-10Z" fill="${level >= 1 ? "#4fb05c" : "#9ccfb0"}"/><path d="M-10 420c80 6 200 6 300-6" fill="none" stroke="#f6dc9a" stroke-width="12"/>`;
  if (level >= 1)
    o += `<g class="wa-reveal">${hBananaPlant(54, 352, 1, 0)}${hBananaPlant(150, 322, 1.15, 1)}${hBananaPlant(232, 360, 0.9, 2)}${hPalm(100, 384, 0.8, -1, 1)}<g ${at(190, 398)}><rect x="-18" y="-16" width="36" height="16" rx="2" fill="#c8894b"/><path d="M-18-8h36" stroke="#8f5a2c"/><circle cx="-10" cy="2" r="5" fill="#6b4a2e"/><circle cx="10" cy="2" r="5" fill="#6b4a2e"/><path d="M-12-16q4-10 10-6m2 6q4-10 10-6" fill="none" stroke="#ffd21f" stroke-width="5" stroke-linecap="round"/></g>${actor(150, 382, neposeda(2, "bunch"), { a: "wa-idle", t: 3 })}${actor(222, 402, neposeda(3, "banana"), { dx: -60, dy: 2, t: 11, d: 3 })}</g>`;
  else o += sFog(140, 346, 140, "За туманом — роща");
  // ── territory 3: banana port islet (right)
  o += `<path d="M716 414c40-44 140-62 254-58v78c-90 10-190 8-254-20Z" fill="${level >= 3 ? "#f6dc9a" : "#cfe6e0"}"/><path d="M716 414c60 26 160 30 254 20" fill="none" stroke="#ffffff" stroke-width="3" opacity=".7"/>`;
  if (level >= 3)
    o += `<g class="wa-reveal">${hStiltHut(860, 392, 0.8, "#4c7bd9", "#ffe9b8")}${hPalm(936, 400, 0.9, -1, 2)}<path d="M690 446h150" stroke="#8f6331" stroke-width="9"/><path d="M694 442h142" stroke="#c99a5c" stroke-width="2"/><path d="M700 450v22m36-22v22m36-22v22m36-22v22" stroke="#6b4a2e" stroke-width="4"/><g ${at(820, 432)}><circle r="8" fill="none" stroke="#ef5a45" stroke-width="4.4"/><path d="M-8 0h16M0-8v16" stroke="#fff" stroke-width="4.4" stroke-dasharray="3 7"/></g>${hBananaBoat(890, 456, 1, 0)}${hBananaBoat(640, 462, 0.8, 1.2)}${actor(722, 444, neposeda(6, "rod"), { a: "wa-idle", t: 4 })}${actor(800, 412, neposeda(7, "crate"), { dx: -64, dy: 26, t: 12, d: 2 })}</g>`;
  else o += sFog(846, 392, 110, "Скоро порт", 5);
  // ── main beach island
  o += `<ellipse cx="486" cy="444" rx="300" ry="14" fill="#0e7c9a" opacity=".25"/><path d="M200 404c18-62 120-104 270-108 150-4 260 26 300 76 18 26-2 48-50 54-122 14-392 14-466 4-44-6-60-14-54-26Z" fill="#f6dc9a"/><path d="M204 412c40 22 400 26 560 6" fill="none" stroke="#ffffff" stroke-width="4" opacity=".8" ${A("wa-shimmer", 3)}/><path d="M300 360c30-30 120-46 200-46s150 14 190 40c-40 18-330 24-390 6Z" fill="#9fd86a"/><path d="M330 352c40-18 200-26 320-4" fill="none" stroke="#bfe88a" stroke-width="6" stroke-linecap="round"/>`;
  o += `${hPalm(392, 372, 1.05, -1, 0)}${hStiltHut(476, 356, 1)}${hPalm(600, 362, 1, 1, 1.5)}`;
  // hammock between hut and palm, with a dozing inhabitant
  o += `<g ${at(552, 330)}><g ${A("wa-swing", 3.6)}>${pivot(50)}<path d="M-44 0q44 30 88 0" fill="none" stroke="#e5527a" stroke-width="7" stroke-linecap="round"/><path d="M-40 4q40 24 80 0" fill="none" stroke="#ffd93b" stroke-width="2.4"/>${actor(-2, 16, `<g transform="rotate(-72)">${neposeda(0)}</g>`, { a: "wa-idle", t: 4 })}</g></g>`;
  o += `${hCrab(334, 428, 1, 0)}<path d="M650 420l3-7 3 7 7 1-6 4 2 7-6-4-6 4 2-7-6-4Z" fill="#ff8f6b"/>`;
  if (level >= 2)
    o += `<g class="wa-reveal">${hFactory(668, 388, 0.92)}${actor(560, 412, neposeda(4, "cup"), { dx: 76, dy: -4, t: 11 })}${actor(700, 412, neposeda(5, "cup"), { dx: -96, dy: 6, t: 13, d: 4 })}</g>`;
  o += actor(410, 410, neposeda(1, "banana"), { dx: 70, dy: 2, t: 12, d: 2 });
  // ── carnival
  if (level >= 4) {
    const confetti = hConfetti(240, 220, 320, 110, 22, 77);
    o += `<g class="wa-reveal">${hLightTower(236, 412, `${u}-ba`, `${u}-bb`, 1)}${hBunting(244, 292, 470, 262, 40)}${hStage(312, 410)}${confetti}`;
    o += `<g ${at(116, 452)}><g ${A("wa-sail", 18)}><g ${A("wa-float", 3.6)}>${pivot(80)}<path d="M-64-6h128l-18 22H-46Z" fill="#8a5bd6"/><path d="M-60-2h120" stroke="#ffd93b" stroke-width="3"/><path d="M0-6v-74" stroke="#5b3d2a" stroke-width="3"/><path d="M4-76Q44-50 4-14Z" fill="#ffd93b" stroke="#c99a12" stroke-width="1.5"/><path d="M-4-66Q-30-46-4-20Z" fill="#ff9ec4"/>${flag(0, -80, 6, "#2fb39a", 1, "#5b3d2a")}</g></g></g>`;
    o += `${actor(294, 388, neposeda(8, "maracas"), { a: "wa-dance", t: 0.7 })}${actor(330, 388, neposeda(9), { a: "wa-dance", t: 0.7, d: 0.35 })}</g>`;
  }
  return o;
}

/* ───────────────────────── Emblems (96×96) ───────────────────────── */

const EMBLEMS = {
  settlers(u) {
    return `<defs><linearGradient id="${u}-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bfe6e2"/><stop offset="1" stop-color="#fde6c4"/></linearGradient><clipPath id="${u}-c"><circle cx="48" cy="48" r="38"/></clipPath></defs><circle cx="48" cy="48" r="47" fill="#2d7f6a"/><circle cx="48" cy="48" r="42.5" fill="none" stroke="#f1deb2" stroke-width="2" stroke-dasharray="1.5 4.5" stroke-linecap="round"/><g clip-path="url(#${u}-c)"><rect width="96" height="96" fill="url(#${u}-g)"/><circle cx="64" cy="40" r="10" fill="#fff3cf"/><path d="M8 58 26 36l10 9 12-15 18 22 22-10v20H8Z" fill="#8cc4b2"/><path d="M36 30l5 4-3 1Zm-14 10 4-4 3 3Z" fill="#fff"/><rect x="0" y="60" width="96" height="40" fill="#4c9ea6"/><path d="M14 74q4-3 8 0t8 0M54 84q4-3 8 0t8 0" fill="none" stroke="#e6f7f2" stroke-width="2" stroke-linecap="round"/><path d="M8 64c10-14 30-18 44-12 6 3 6 10-2 12Z" fill="#8fce86"/><g transform="translate(25 60) scale(.42)">${`<path d="M0-78-15-50h7l-13 22h9L-26-8h52L12-28h9L8-50h7Z" fill="#3a836a"/><rect x="-3" y="-10" width="6" height="10" fill="#7a5a40"/>`}</g><g transform="translate(66 74) scale(.62)"><path d="M-32 0h64l-9 13h-46Z" fill="#b9784a"/><path d="M0 0v-46" stroke="#6b4a33" stroke-width="2.6"/><path d="M3-44 26-6H3Z" fill="#fff3dc"/><path d="M-3-38-19-6h16Z" fill="#f2e3c4"/><path d="M0-46h12l-3 3 3 3H0Z" fill="#e05f4c"/></g><g transform="translate(40 56) scale(.36)"><path d="M-40 0V-44h80V0Z" fill="#b9825a"/><path d="M-50-40 0-80l50 40Z" fill="#e07d55"/><rect x="-8" y="-24" width="16" height="24" fill="#6b4a35"/></g></g><circle cx="48" cy="48" r="38" fill="none" stroke="#24695a" stroke-width="2"/>`;
  },
  bricks() {
    const inner =
      box(-1, -1, 0, 2, 2, 1, "#2f6fdb") +
      box(-1, -1, 1, 2, 2, 1, "#f6c21c") +
      box(-1, -1, 2, 2, 2, 1, "#e3342f", { step: 1 });
    const [fx, fy] = P(-0.5, 0.5, 3);
    return `<rect x="3" y="3" width="90" height="90" rx="22" fill="#e5ecfa"/><rect x="3" y="3" width="90" height="90" rx="22" fill="none" stroke="#2f6fdb" stroke-width="3"/><g transform="translate(48 50) scale(1.08) translate(${-BX} ${-(BY - 13)})">${inner}<path d="M${fx} ${fy}v-30" stroke="#5b5b5b" stroke-width="2"/><path d="M${fx + 1} ${fy - 30}h16l-4 5 4 5h-16Z" fill="#2ea44f"/><path d="M${r1(BX - 6)} ${r1(BY + 8)}h12" stroke="#ffffff" stroke-width="2.2" opacity=".55"/></g>`;
  },
  voxel(u) {
    const r = rng(5);
    let px = "";
    for (let n = 0; n < 9; n++)
      px += `<rect x="${r1(22 + r() * 22)}" y="${r1(42 + r() * 30)}" width="4" height="4" fill="${n % 2 ? "#74492b" : "#a2734c"}"/>`;
    for (let n = 0; n < 6; n++)
      px += `<rect x="${r1(50 + r() * 22)}" y="${r1(46 + r() * 26)}" width="4" height="4" fill="#5c3c24"/>`;
    return `<path d="M48 2 88 25v46L48 94 8 71V25Z" fill="#2f2a4a"/><path d="M48 8 82 28v40L48 88 14 68V28Z" fill="#3d3561"/><rect x="18" y="16" width="3" height="3" fill="#ffe27a"/><rect x="76" y="20" width="3" height="3" fill="#c7b2ff"/><rect x="74" y="74" width="3" height="3" fill="#9fe3ff"/><path d="M20 40 48 54v28L20 68Z" fill="#8a5d3b"/><path d="M48 54 76 40v28L48 82Z" fill="#6e4a2e"/>${px}<path d="M20 40 48 54v7L44 59v3l-4-2v-3l-6-3v4l-4-2v-4l-10-5Z" fill="#6bb04a"/><path d="M48 54 76 40v6l-6 3v4l-4 2v-4l-8 4v3l-4 2v-4l-6 3Z" fill="#4f8a39"/><path d="M48 26 76 40 48 54 20 40Z" fill="#8fd06a"/><path d="M34 37h4v2h-4Zm22-4h4v2h-4Zm-6 12h4v2h-4Z" fill="#6bb04a"/><g transform="translate(48 44)"><rect x="-14" y="-38" width="28" height="36" fill="#c7b2ff" opacity=".28"/><path d="M-5 0V-26l7-9 7 9V0Z" fill="#9b7be0"/><path d="M2-35l7 9V0H2Z" fill="#7c5cc4"/><path d="M-13 0V-13l4-6 4 6V0Z" fill="#b69af3"/><path d="M9 0V-11l4-5 4 5V0Z" fill="#a488d6"/><path d="M-2-26 2-31" stroke="#efe6ff" stroke-width="2"/></g>`;
  },
  helpers(u) {
    let rays = "";
    for (let n = 0; n < 16; n++)
      rays += `<path d="M46-2h4l-2 9Z" fill="#ffb92e" transform="rotate(${n * 22.5} 48 48)"/>`;
    return `<defs><radialGradient id="${u}-s" cx=".5" cy=".42" r=".6"><stop offset="0" stop-color="#fff3a8"/><stop offset="1" stop-color="#ffc93b"/></radialGradient><clipPath id="${u}-c"><circle cx="48" cy="48" r="40"/></clipPath></defs>${rays}<circle cx="48" cy="48" r="42" fill="#ff9a3c"/><g clip-path="url(#${u}-c)"><circle cx="48" cy="48" r="40" fill="url(#${u}-s)"/><rect y="70" width="96" height="30" fill="#2dbacd"/><path d="M6 74q6-4 12 0t12 0 12 0 12 0 12 0 12 0 12 0" fill="none" stroke="#e9fbff" stroke-width="2.4"/><g transform="translate(14 8) rotate(30)"><path d="M0 0Q22-16 52 2Q40 0 34 6 26 0 20 8 12 2 0 0Z" fill="#43b863"/></g><g transform="translate(14 8) rotate(70)"><path d="M0 0Q22-16 52 2Q40 0 34 6 26 0 20 8 12 2 0 0Z" fill="#2f9e55"/></g><g transform="translate(48 88) scale(1.7)">${neposeda(0)}</g></g><circle cx="48" cy="48" r="40" fill="none" stroke="#ffffff" stroke-width="3"/>`;
  },
};

export function worldEmblem(id) {
  const key = idOf(id),
    u = uid("e");
  return `<svg class="wa-emblem wa-emblem-${key}" viewBox="0 0 96 96" role="img" aria-label="Эмблема мира «${metaOf(key).name}»" focusable="false">${EMBLEMS[key](u)}</svg>`;
}

/* ───────────────────────── Upgrade artworks (240×140, static) ───────────────────────── */

const UPGRADE_NAMES = {
  settlers: [
    "Лесная поляна",
    "Ветряная пекарня",
    "Рыбацкая гавань",
    "Праздник маяка",
  ],
  bricks: [
    "Долина деталей",
    "Сборочная станция",
    "Грузовой порт",
    "Башня изобретений",
  ],
  voxel: [
    "Кристальная долина",
    "Мастерская механизмов",
    "Бухта исследователей",
    "Кристальный маяк",
  ],
  helpers: [
    "Банановая роща",
    "Фабрика смузи",
    "Банановый порт",
    "Большой карнавал",
  ],
};

/** Decorative figure (never .citizen) — keeps smoke-test counts honest. */
const figure = (x, y, body, s = 1) =>
  `<g class="wa-figure" ${at(x, y, s)}>${body}</g>`;

/** Re-centre a fragment drawn in scene coordinates into the 240×140 card. */
const fit = (cx, cy, s, inner, tx = 120, ty = 70) =>
  `<g transform="translate(${tx} ${ty}) scale(${s}) translate(${-cx} ${-cy})">${inner}</g>`;

function sCardBg(u, land = "#9ad08c") {
  return `<defs><linearGradient id="${u}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bfe6e2"/><stop offset="1" stop-color="#fde6c4"/></linearGradient><linearGradient id="${u}-beam" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stop-color="#fff6b8" stop-opacity=".8"/><stop offset="1" stop-color="#fff6b8" stop-opacity="0"/></linearGradient></defs><rect width="240" height="140" fill="url(#${u}-sky)"/><path d="M0 92c40-26 80-30 120-20s70-24 120-10v80H0Z" fill="#acd8cf"/><rect y="108" width="240" height="40" fill="#5fb0b0"/><path d="M-10 124c40-30 140-36 200-20 30 8 40 20 60 30v20H-10Z" fill="${land}"/>`;
}

const UPGRADES_ART = {
  settlers: [
    (u) =>
      `${sCardBg(u)}${sPine(150, 112, 0.62, 1)}${sRoundTree(66, 124, 0.78, true)}${sRoundTree(196, 122, 0.6, true, 2)}${sPine(112, 118, 0.5)}<g transform="translate(150 128)" fill="#a87148" stroke="#7a5236" stroke-width="1.2"><rect x="-16" y="-6" width="32" height="6" rx="3"/><rect x="-12" y="-12" width="24" height="6" rx="3"/></g>${figure(104, 132, settler(2, "log"), 0.95)}`,
    (u) =>
      `${sCardBg(u, "#a4d48e")}${sWheat(34, 128, 6)}${sWindmill(110, 128, 0.82)}${sStall(186, 128, 0.95)}${figure(152, 134, settler(4, "bread"), 0.95)}`,
    (u) =>
      `${sCardBg(u)}<rect y="104" width="240" height="40" fill="#5fb0b0"/><path d="M-10 118c30-16 70-20 110-8v30H-10Z" fill="#93cd88"/>${sFisherHut(48, 116, 0.72)}<path d="M84 118h86" stroke="#9e6d45" stroke-width="7"/><path d="M90 122v12m26-12v12m26-12v12" stroke="#7a5236" stroke-width="3"/>${sBoat(198, 120, 0.72)}${figure(140, 116, settler(6, "rod"), 0.95)}${sDuck(70, 132, 0.8)}`,
    (u) =>
      `${sCardBg(u)}${sLighthouse(196, 124, `${u}-beam`, 0.66)}${garland(18, 70, 150, 74, 28, ["#ffd35c", "#ef8f86", "#9ec9f0", "#b9a2ec"], 8)}${sGuestShip(82, 124, 0.5)}${figure(138, 134, settler(8), 0.9)}${figure(158, 136, settler(9), 0.9)}`,
  ],
  bricks: [
    () =>
      `<rect width="240" height="140" fill="#3f7fd6"/>${fit(
        ...P(4.5, 13.5, 1),
        0.92,
        `${box(1, 10, 0, 7, 7, 0.34, "#dcc08a")}${box(4.6, 10.4, 0.34, 3, 2.5, 2.4, "#f28c28", { stud: false })}${poly(quadJ(12.9, 5, 7, 0.34, 2), "#3b2a1c")}${box(4.4, 10.2, 2.74, 3.4, 2.9, 0.4, "#2f6fdb")}${box(2, 14, 0.34, 2, 1, 1, "#e3342f")}${box(2.5, 13.6, 1.34, 1, 1, 1, "#f6c21c")}${box(5, 14.6, 0.34, 1, 2, 1, "#2ea44f")}${bTree(1.4, 10.4, 0.34, 0.8)}${(() => {
          const [x, y] = P(4, 15.8, 0.34);
          return figure(x, y, minifig(2, "brick"));
        })()}`,
      )}`,
    () =>
      `<rect width="240" height="140" fill="#3f7fd6"/>${fit(
        ...P(17.6, 13, 2.2),
        0.82,
        `${box(14.6, 9.6, 0, 6.6, 8.2, 0.34, "#5cb85c")}${bStation()}${(() => {
          const [x, y] = P(16.6, 16.4, 0.34);
          return figure(x, y, minifig(4, "brick"));
        })()}`,
      )}`,
    () =>
      `<rect width="240" height="140" fill="#3f7fd6"/>${fit(
        ...P(27.4, 10.4, 3.4),
        0.56,
        `${box(22, 9, 0, 8, 7, 0.34, "#c3c9cf")}${bCrane()}${box(23, 13, 0.34, 2, 1, 1, "#e3342f", { stud: false })}${box(23, 14.2, 0.34, 2, 1, 1, "#2f6fdb", { stud: false })}${box(23, 13.6, 1.34, 2, 1, 1, "#2ea44f", { stud: false })}${shift(0, -3, bBoat())}${(() => {
          const [x, y] = P(26, 14.6, 0.34);
          return figure(x, y, minifig(7, "crate"));
        })()}`,
      )}`,
    () =>
      `<rect width="240" height="140" fill="#cfe0fb"/><rect y="96" width="240" height="44" fill="#3f7fd6"/>${fit(
        ...P(11.6, 11.6, 6),
        0.62,
        `${box(9, 9, 0, 6, 6, 0.34, "#5cb85c")}${bTower(4)}${(() => {
          const [x, y] = P(13.6, 14.4, 0.34);
          return figure(x, y, minifig(8, "flag"));
        })()}`,
      )}${[
        ["#e3342f", 40, 46],
        ["#f6c21c", 64, 30],
        ["#2f6fdb", 186, 40],
        ["#8a4fd8", 208, 64],
      ]
        .map(
          ([c, x, y]) =>
            `<g ${at(x, y)}><path d="M0 10q-3 8 2 18" fill="none" stroke="#5b5b5b" stroke-width="1"/><ellipse rx="8" ry="10" fill="${c}"/><ellipse cx="-2.4" cy="-3" rx="2.4" ry="3.2" fill="#fff" opacity=".4"/></g>`,
        )
        .join("")}`,
  ],
  voxel: [
    (u) =>
      `<defs>${vDefs(u)}</defs><rect width="240" height="140" fill="#cfe6f7"/>${[6, 6, 5, 5, 4, 4, 3, 3, 3, 3, 2, 2, 2, 2, 2].map((h, c) => vColumn(c, u, 16, h, "grass", 144)).join("")}<rect x="16" y="66" width="22" height="26" fill="#2a2140"/><path d="M15 92V65h24v27" fill="none" stroke="#b88a52" stroke-width="3"/>${vCrystal(27, 90, 0.5)}${vCrystal(70, 78, 0.8, 1)}${vCrystal(112, 94, 0.6)}${vSheep(150, 96, 0.9)}${figure(24, 48, voxelite(2, "pick"), 0.95)}${figure(196, 110, voxelite(3, "crystal"), 0.95)}`,
    (u) =>
      `<defs>${vDefs(u)}</defs><rect width="240" height="140" fill="#cfe6f7"/>${Array.from({ length: 16 }, (_, c) => vColumn(c, u, 16, 2, "grass", 144)).join("")}${fit(436, 330, 0.95, vWorkshop(u), 112, 72)}${figure(196, 110, voxelite(4, "glow"), 0.95)}`,
    (u) =>
      `<defs>${vDefs(u)}</defs><rect width="240" height="140" fill="#cfe6f7"/><rect y="96" width="240" height="50" fill="#8ec8ea"/>${[2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2].map((h, c) => vColumn(c, u, 16, h, c < 2 || c > 11 ? "grass" : "sand", 144)).join("")}<rect x="32" y="106" width="160" height="38" fill="url(#${u}-water)" opacity=".86"/><rect x="20" y="88" width="196" height="7" fill="#d0a56c"/><rect x="20" y="93" width="196" height="3" fill="#7c5531"/><path d="M48 96v14m60-14v14m60-14v14" stroke="#6b4a2e" stroke-width="4"/>${vRaft(84, 120, 0.7, "#f4f1ea", 0, u)}${vRaft(156, 124, 0.62, "#f2c14e", 1, u)}${figure(206, 88, voxelite(2, "glass"), 0.9)}`,
    (u) => {
      let rays = "";
      for (let n = 0; n < 8; n++)
        rays += `<rect x="-2.4" y="-70" width="4.8" height="40" fill="#e9dcff" opacity=".35" transform="rotate(${n * 45})"/>`;
      const hs = [2, 3, 4, 5, 6, 6, 7, 7, 6, 6, 5, 4, 3, 2, 2];
      return `<defs>${vDefs(u)}</defs><rect width="240" height="140" fill="#3d3561"/><g fill="#ffe27a"><rect x="24" y="20" width="3" height="3"/><rect x="200" y="30" width="3" height="3"/><rect x="170" y="12" width="3" height="3" fill="#c7b2ff"/></g>${hs.map((h, c) => vColumn(c, u, 16, h, h >= 6 ? "stone" : "grass", 144)).join("")}<g ${at(120, 30)}>${rays}<rect x="-26" y="-26" width="52" height="52" fill="#c7b2ff" opacity=".3"/></g>${vCrystal(120, 34, 1.1)}${[
        [50, 50],
        [190, 60],
        [80, 30],
        [168, 92],
      ]
        .map(
          ([x, y], n) =>
            `<rect x="${x}" y="${y}" width="8" height="8" fill="${["#ffe27a", "#c7b2ff", "#9fe3ff"][n % 3]}"/>`,
        )
        .join("")}`;
    },
  ],
  helpers: [
    (u) =>
      `${hCardBg(u)}${hBananaPlant(54, 118, 1.05)}${hBananaPlant(196, 112, 0.9, 1)}<g ${at(132, 124)}><rect x="-18" y="-16" width="36" height="16" rx="2" fill="#c8894b"/><circle cx="-10" cy="2" r="5" fill="#6b4a2e"/><circle cx="10" cy="2" r="5" fill="#6b4a2e"/><path d="M-12-16q4-10 10-6m2 6q4-10 10-6" fill="none" stroke="#ffd21f" stroke-width="5" stroke-linecap="round"/></g>${figure(100, 130, neposeda(2, "bunch"))}`,
    (u) =>
      `${hCardBg(u)}${hFactory(98, 128, 0.78)}${figure(196, 132, neposeda(4, "cup"))}`,
    (u) =>
      `${hCardBg(u, false)}<path d="M0 104c40-12 80-12 100 0v40H0Z" fill="#f6dc9a"/><path d="M60 112h140" stroke="#8f6331" stroke-width="7"/><path d="M70 116v18m40-18v18m40-18v18m40-18v18" stroke="#6b4a2e" stroke-width="3.4"/>${hBananaBoat(96, 128, 0.8)}${hBananaBoat(194, 126, 0.7, 1)}${figure(150, 110, neposeda(6, "rod"))}${hPalm(30, 112, 0.6, 1)}`,
    (u) =>
      `${hCardBg(u)}<defs><linearGradient id="${u}-ba" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff59a" stop-opacity=".8"/><stop offset="1" stop-color="#fff59a" stop-opacity="0"/></linearGradient><linearGradient id="${u}-bb" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffb3d1" stop-opacity=".75"/><stop offset="1" stop-color="#ffb3d1" stop-opacity="0"/></linearGradient></defs>${hLightTower(32, 132, `${u}-ba`, `${u}-bb`, 0.62)}${hBunting(40, 52, 230, 40, 30, 12)}${hStage(140, 132, 0.95)}${hConfetti(60, 20, 170, 60, 16, 9)}${figure(124, 112, neposeda(8, "maracas"))}${figure(156, 112, neposeda(9))}`,
  ],
};

function hCardBg(u, sand = true) {
  return `<defs><linearGradient id="${u}-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fd3f0"/><stop offset="1" stop-color="#fff1c2"/></linearGradient></defs><rect width="240" height="140" fill="url(#${u}-sky)"/><circle cx="206" cy="30" r="16" fill="#ffe36b"/><rect y="88" width="240" height="60" fill="#2dbacd"/><path d="M10 100q8-5 16 0t16 0M170 98q8-5 16 0t16 0" fill="none" stroke="#e9fbff" stroke-width="2"/>${sand ? `<path d="M-10 118c60-24 200-26 260-6v40H-10Z" fill="#f6dc9a"/>` : ""}`;
}

export function upgradeArtwork(id, index = 0) {
  const key = idOf(id),
    i = Math.max(0, Math.min(3, Math.floor(Number(index) || 0))),
    u = uid("u");
  return `<svg class="wa-upgrade wa-upgrade-${key}" data-upgrade="${i}" viewBox="0 0 240 140" preserveAspectRatio="xMidYMid slice" role="img" aria-label="${UPGRADE_NAMES[key][i]}" focusable="false">${UPGRADES_ART[key][i](u)}</svg>`;
}

/** Brick puppy — wags its tail, sniffs around the plate. */
function bDog(i, j, k) {
  const [x, y] = P(i, j, k);
  return `<g ${at(x, y)}><g class="wa-scuttle" style="--wa-dx:18px;--wa-t:6s"><ellipse cy="1" rx="10" ry="3" fill="#0d2d5a" opacity=".2"/><rect x="-9" y="-6" width="3" height="6" fill="#6e4520"/><rect x="5" y="-6" width="3" height="6" fill="#6e4520"/><rect x="-10" y="-13" width="19" height="8" rx="1.5" fill="#a8692e"/><rect x="5" y="-21" width="9" height="9" rx="1.5" fill="#a8692e"/><rect x="12" y="-17" width="4" height="4" rx="1" fill="#3b2a1c"/><rect x="5" y="-23" width="3" height="5" fill="#6e4520"/><circle cx="10" cy="-18" r="1" fill="#111"/><g ${at(-10, -12)}><g ${A("wa-wag", 0.5)}>${pivot(7)}<rect x="-6" y="-1.5" width="6" height="3" rx="1.5" fill="#a8692e"/></g></g></g></g>`;
}

/** Toy sailboat drifting on the stud-sea (always present, gives water life). */
function bToyBoat(i, j, o = 0) {
  const [x, y] = P(i, j);
  return `<g ${at(x, y)}><g ${A("wa-sail", 20, o)}><g ${A("wa-float", 3.2, o)}>${pivot(36)}<path d="M-20-4h40l-6 9h-28Z" fill="#f6c21c"/><path d="M-20-4h40" stroke="#ffe27a" stroke-width="2"/><path d="M0-4v-30" stroke="#5b5b5b" stroke-width="2"/><path d="M2-32 18-8H2Z" fill="#f4f1e8"/><path d="M-2-28-14-8h12Z" fill="#e3342f"/></g></g></g>`;
}

/* ───────────────────────── Public API ───────────────────────── */

const SCENES = {
  settlers: settlersScene,
  bricks: bricksScene,
  voxel: voxelScene,
  helpers: helpersScene,
};

export function worldScene(id, level = 0, { motion = true } = {}) {
  const key = idOf(id),
    lv = clampLevel(level);
  return frame(
    metaOf(key),
    key,
    lv,
    motion,
    (SCENES[key] || settlersScene)(lv),
  );
}
