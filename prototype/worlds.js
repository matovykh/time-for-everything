import { icon } from "./icons.js";
import { worldEmblem, worldScene, upgradeArtwork } from "./world-art.js";

export const WORLDS = [
  {
    id: "settlers",
    name: "Тихая бухта",
    type: "Поселенцы и путешественники",
    badge: "ПРИРОДА",
    color: "#3ca781",
    sky: "#d8f1ee",
    land: "#9cd7a0",
    side: "#548776",
    roof: "#ea9067",
    resource: "Дерево и плоды",
    inhabitants: "поселенцев",
    names: [
      "Лесная поляна",
      "Ветряная пекарня",
      "Рыбацкая гавань",
      "Праздник маяка",
    ],
    effects: [
      "Туман рассеется: откроются лес и яблони. Придут два лесника, появится место для пекарни.",
      "Крылья мельницы закрутятся. Пекарь откроет прилавок, а жители понесут хлеб домой.",
      "У нового берега появится причал. Рыбаки выйдут на лодках, а мост соединит берега.",
      "Маяк зажжётся, прибудет корабль гостей. На площади начнётся праздник с фонариками.",
    ],
  },
  {
    id: "bricks",
    name: "Брик-сити",
    type: "Мир яркого конструктора",
    badge: "КОНСТРУКТОР",
    color: "#df8560",
    sky: "#e5ecfa",
    land: "#95c6ba",
    side: "#5d8b93",
    roof: "#ef665a",
    resource: "Детали и механизмы",
    inhabitants: "строителей",
    names: [
      "Долина деталей",
      "Сборочная станция",
      "Грузовой порт",
      "Башня изобретений",
    ],
    effects: [
      "Появятся новые строительные пластины и склад деталей. Два сборщика начнут сортировать кубики.",
      "Заработает колесо сборочной машины. Строители повезут яркие детали по дорожкам.",
      "Кран и грузовой катер свяжут площадки. Откроется новая территория для больших изобретений.",
      "Засветится башня изобретений. Жители устроят парад построенных машин и запустят фонарики.",
    ],
  },
  {
    id: "voxel",
    name: "Куболесье",
    type: "Кубический мир исследователей",
    badge: "КУБИЧЕСКИЙ",
    color: "#648e60",
    sky: "#d9edf8",
    land: "#95bf69",
    side: "#997857",
    roof: "#8c6dc2",
    resource: "Кристаллы и древесина",
    inhabitants: "исследователей",
    names: [
      "Кристальная долина",
      "Мастерская механизмов",
      "Бухта исследователей",
      "Кристальный маяк",
    ],
    effects: [
      "Откроется ступенчатая долина. Исследователи найдут кристаллы и проложат новую тропинку.",
      "Запустится механизм обработки кристаллов. Мастера начнут переносить светящиеся блоки.",
      "Появятся мост и экспедиционные лодки. Исследователи отправятся к новому берегу.",
      "Кристалл осветит остров. Прибудут гости, и над кубическими домами засияют огоньки.",
    ],
  },
  {
    id: "helpers",
    name: "Банановый залив",
    type: "Остров весёлых непосед",
    badge: "НЕПОСЕДЫ",
    color: "#c3a22d",
    sky: "#f4edcb",
    land: "#bad795",
    side: "#7c9981",
    roof: "#8d89d5",
    resource: "Бананы и изобретения",
    inhabitants: "непосед",
    names: [
      "Банановая роща",
      "Фабрика смузи",
      "Банановый порт",
      "Большой карнавал",
    ],
    effects: [
      "Туман откроет рощу. Жёлтые непоседы начнут собирать бананы и возить их к домикам.",
      "Завертится смешная машина смузи. Курьеры понесут напитки, а у прилавка соберутся друзья.",
      "Причал примет банановые лодки. На новом берегу появится место для карнавальной сцены.",
      "Заиграет световая башня: непоседы соберутся на карнавал. В залив войдёт корабль друзей.",
    ],
  },
];
export const UPGRADES = [
  {
    id: "meadow",
    cost: 60,
    kind: "Открытие территории",
    space: "+1 территория · +2 жителя",
    requires: null,
  },
  {
    id: "workshop",
    cost: 90,
    kind: "Улучшение жизни",
    space: "Производство · +2 жителя",
    requires: "meadow",
  },
  {
    id: "harbor",
    cost: 120,
    kind: "Открытие территории",
    space: "+1 территория · +2 жителя",
    requires: "workshop",
  },
  {
    id: "beacon",
    cost: 180,
    kind: "Улучшение жизни",
    space: "Гости и праздник · +2 жителя",
    requires: "harbor",
  },
];
export function migrateWorlds(state) {
  const hadWorlds = Boolean(state.worldVersion);
  state.activeWorld ||= "settlers";
  state.worlds ||= {};
  for (const w of WORLDS) state.worlds[w.id] ||= { unlocked: [], log: [] };
  if (!state.worldVersion) {
    const count = state.bought?.includes("lighthouse")
      ? 4
      : state.bought?.includes("bridge")
        ? 2
        : state.bought?.includes("garden")
          ? 1
          : 0;
    state.worlds.settlers.unlocked = UPGRADES.slice(0, count).map((u) => u.id);
    state.worldVersion = 2;
  }
  if (!WORLDS.some((w) => w.id === state.activeWorld))
    state.activeWorld = "settlers";
  state.worldShelf ||= hadWorlds
    ? WORLDS.map((w) => w.id)
    : [state.activeWorld];
  state.worldShelf = [...new Set(state.worldShelf)].filter((id) =>
    WORLDS.some((w) => w.id === id),
  );
  if (!state.worldShelf.includes(state.activeWorld))
    state.worldShelf.push(state.activeWorld);
  state.purchases ||= [];
  state.profile ||= { name: "Алексей", grade: "3", timezone: "Europe/Moscow" };
}
export const getWorld = (id) => WORLDS.find((w) => w.id === id) || WORLDS[0];
export const worldLevel = (state, id = state.activeWorld) =>
  state.worlds[id].unlocked.length;

// The art module is authored by Claude; game rules stay independent of drawing.
export function islandScene(
  id = "settlers",
  level = 0,
  { motion = true } = {},
) {
  return worldScene(id, level, { motion });
}

export function worldSwitcher(state) {
  return `<section class="world-shelf"><div class="section-head"><div><h2>Мои миры</h2><small>Листай коллекцию или добавь мир из каталога — бесплатно</small></div><div class="shelf-controls"><button data-rail="-1" class="ghost" aria-label="Прокрутить миры влево">←</button><button data-rail="1" class="ghost" aria-label="Прокрутить миры вправо">→</button><button data-catalog="open" class="primary">Каталог миров</button></div></div><div class="world-rail" tabindex="0" role="region" aria-label="Коллекция миров, горизонтальная прокрутка">${state.worldShelf
    .map(getWorld)
    .map(
      (w) =>
        `<button data-world="${w.id}" class="world-choice ${state.activeWorld === w.id ? "selected" : ""}" aria-pressed="${state.activeWorld === w.id}" style="--world-accent:${w.color}"><span class="world-emblem">${worldEmblem(w.id)}</span><span class="world-choice-copy"><b>${w.name}</b><small>${w.type}</small><span class="world-progress-label">${worldLevel(state, w.id)} из ${UPGRADES.length} открытий</span></span></button>`,
    )
    .join(
      "",
    )}<button data-catalog="open" class="world-add"><span>＋</span><b>Найти новый мир</b><small>Посмотреть каталог</small></button></div></section>`;
}

export function worldPage(state, previewLevel = null) {
  const w = getWorld(state.activeWorld),
    actual = worldLevel(state),
    level = previewLevel ?? actual;
  const next = UPGRADES[actual],
    log = state.worlds[w.id].log;
  return `<div class="page-title"><div><span class="overline">АРХИПЕЛАГ ВОЗМОЖНОСТЕЙ</span><h1>Здесь оживают твои старания</h1><p class="muted">Не просто постройки. Новые истории, которые начинаются благодаря тебе.</p></div><button class="ghost" data-tour="open">${icon("play", 18)} Как это работает</button></div>${worldSwitcher(state)}
  <section class="world-stage"><div class="world-stage-top"><div><span class="overline">${previewLevel !== null ? "БЕСПЛАТНЫЙ ПРЕДПРОСМОТР · НЕ КУПЛЕНО" : "ТВОЙ ЖИВОЙ МИР"}</span><h2>${w.name}</h2></div><div class="world-tools"><span class="live-badge"><i></i> Всё спокойно</span></div></div>
  ${islandScene(w.id, level, { preview: previewLevel !== null, motion: true })}
  <div class="world-stage-bottom"><span>${icon("flag", 18)} ${1 + (level >= 1 ? 1 : 0) + (level >= 3 ? 1 : 0)} территории</span><span>${icon("people", 18)} ${2 + level * 2} ${w.inhabitants}</span><span>${icon("spark", 18)} ${level >= 2 ? "Мастерская работает" : "Первый лагерь"}</span><span>${level >= 1 ? w.resource : "Ресурсы ждут за туманом"}</span></div></section>
  <div class="world-preview-bar"><div><b>Загляни в будущее</b><small>Сравни, как изменится жизнь. Звёзды не тратятся.</small></div><div class="preview-steps"><button data-preview="actual" class="${previewLevel === null ? "selected" : ""}">Мой остров</button>${[0, 1, 2, 3, 4].map((n) => `<button data-preview="${n}" class="${previewLevel === n ? "selected" : ""}" aria-label="Предпросмотр этапа ${n}">${n === 0 ? "Старт" : n}</button>`).join("")}</div></div>
  <div class="world-story" role="status"><span class="story-avatar">${icon("people", 25)}</span><div><b>${previewLevel !== null ? "Вот что изменится на этом этапе" : log.length ? "Новое в твоём мире" : "Первая история уже началась"}</b><p>${previewLevel !== null ? (level ? w.effects[level - 1] : "Пока здесь маленький лагерь и два друга. Всё большое начинается с этого.") : log.length ? w.effects[actual - 1] : "Два друга поселились у костра. За туманом — целый мир. Какой будет их следующая история?"}</p></div></div>
  <div class="section-head"><div><h2>Открывай территории. Меняй жизнь.</h2><p class="muted">${next ? `Следующая цель: ${w.names[actual]} · ${next.cost} звёзд` : "Этот остров расцвёл! Можно развивать другой — всё здесь сохранится."}</p></div><span class="wallet">✦ ${state.balance}</span></div>
  <div class="upgrade-grid">${UPGRADES.map((u, i) => {
    const owned = state.worlds[w.id].unlocked.includes(u.id),
      ready = !u.requires || state.worlds[w.id].unlocked.includes(u.requires);
    return `<article class="upgrade-card ${owned ? "owned" : ""}"><div class="upgrade-art">${upgradeArtwork(w.id, i)}<span class="upgrade-number">0${i + 1}</span></div><div class="upgrade-copy"><span class="overline">${u.kind}</span><h3>${w.names[i]}</h3><p>${w.effects[i]}</p><span class="upgrade-property">${u.space}</span><button class="text-button" data-preview="${i + 1}">Посмотреть изменения ${icon("arrow", 16)}</button><button data-buy="${u.id}" class="${owned ? "ghost" : "gold"}" ${owned || !ready || state.balance < u.cost ? "disabled" : ""}>${owned ? "✓ Жизнь уже изменилась" : !ready ? `Сначала: ${w.names[i - 1]}` : state.balance < u.cost ? `Нужно ещё ${u.cost - state.balance} ✦` : `Открыть за ${u.cost} ✦`}</button></div></article>`;
  }).join("")}</div>
  <div class="notice peaceful">${icon("check", 20)} Мир не голодает, не разрушается и не забывает тебя. Можно вернуться когда угодно — все открытия останутся.</div>`;
}
