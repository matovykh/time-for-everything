import "@fontsource-variable/nunito-sans";
import { icon } from "./icons.js";
import {
  WORLDS,
  UPGRADES,
  getWorld,
  worldLevel,
  migrateWorlds,
  islandScene,
  worldPage,
} from "./worlds.js";
import { openOnboarding } from "./onboarding.js";
import { openWorldCatalog } from "./catalog.js";
import "./world-art.css";
import {
  disposeCharts,
  mountCharts,
  stackedChart,
  donutChart,
  progressChart,
} from "./charts.js";

const KEY = "vse-uspeyu-prototype-v1";
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const dayAgo = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const initial = () => ({
  theme: "system",
  balance: 145,
  bought: [],
  tasks: [
    { id: "math", name: "Математика", icon: "∑", group: "lessons" },
    { id: "russian", name: "Русский язык", icon: "Аа", group: "lessons" },
    {
      id: "literature",
      name: "Литературное чтение",
      icon: "▤",
      group: "lessons",
    },
    { id: "nature", name: "Окружающий мир", icon: "❀", group: "lessons" },
    { id: "english", name: "Английский язык", icon: "En", group: "lessons" },
    { id: "walk", name: "Прогулка", icon: "☀", group: "walk" },
    { id: "reading", name: "Внеклассное чтение", icon: "▥", group: "other" },
  ],
  chores: [
    { id: "bag", name: "Собрать рюкзак на завтра", schedule: "weekdays" },
    { id: "plants", name: "Полить цветы", schedule: "weekly", weekday: 5 },
    { id: "room", name: "Навести порядок на столе", schedule: "daily" },
    { id: "help", name: "Помочь дома", schedule: "any" },
  ],
  done: {},
  timers: {},
  entries: Array.from({ length: 28 }, (_, n) => [
    {
      task: "math",
      date: dayAgo(n + 1),
      seconds: (24 + Math.floor(n / 7) * 4 + (n % 5)) * 60,
      source: "Демо",
    },
    {
      task: "russian",
      date: dayAgo(n + 1),
      seconds: (25 + (n % 8)) * 60,
      source: "Демо",
    },
    {
      task: "literature",
      date: dayAgo(n + 1),
      seconds: 15 * 60,
      source: "Демо",
    },
    {
      task: "walk",
      date: dayAgo(n + 1),
      seconds: (n < 7 ? 110 + (n % 3) * 5 : 85 + (n % 4) * 5) * 60,
      source: "Демо",
    },
    { task: "reading", date: dayAgo(n + 1), seconds: 20 * 60, source: "Демо" },
  ]).flat(),
  mode: "math",
});
let state;
try {
  state = JSON.parse(localStorage.getItem(KEY)) || initial();
} catch {
  state = initial();
}
migrateWorlds(state);
let page = "home",
  selected = "math",
  toastTimeout,
  previewLevel = null;
let signedOut = sessionStorage.getItem("vse-demo-signed-out") === "1";
const $ = (id) => document.getElementById(id);
const escapeHTML = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    toast("Браузер не сохранил данные. Проверь свободное место.");
  }
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").style.display = "block";
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => ($("toast").style.display = "none"), 3500);
}
function applyTheme() {
  document.body.dataset.theme =
    state.theme === "system"
      ? matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : state.theme;
  document.documentElement.style.colorScheme = document.body.dataset.theme;
  document.body.classList.toggle(
    "theme-dark",
    document.body.dataset.theme === "dark",
  );
  document
    .querySelectorAll("[data-theme-choice]")
    .forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.themeChoice === state.theme),
      ),
    );
}
matchMedia("(prefers-color-scheme: dark)").addEventListener(
  "change",
  applyTheme,
);
const menus = [
  ["home", "⌂", "Мой день"],
  ["lessons", "▤", "Уроки"],
  ["walk", "☀", "Прогулка"],
  ["chores", "☑", "Поручения"],
  ["world", "✧", "Мой мир"],
  ["rewards", "☆", "Награды"],
  ["settings", "⚙", "Настройки"],
];
const scheduleName = (c) =>
  ({
    daily: "Каждый день",
    weekdays: "По будням",
    weekly: `Раз в неделю · ${["вс", "пн", "вт", "ср", "чт", "пт", "сб"][c.weekday]}`,
    any: "Без расписания · по желанию",
  })[c.schedule];
const due = (c) =>
  c.schedule === "daily" ||
  c.schedule === "any" ||
  (c.schedule === "weekdays" &&
    new Date().getDay() > 0 &&
    new Date().getDay() < 6) ||
  (c.schedule === "weekly" && new Date().getDay() === Number(c.weekday));
const completed = (c) => !!state.done[today() + ":" + c.id];
const minutes = (task, date) =>
  state.entries
    .filter((e) => (!task || e.task === task) && e.date === date)
    .reduce((s, e) => s + e.seconds / 60, 0);
const fmt = (n) => Math.round(n).toLocaleString("ru-RU");
function worldArt() {
  return islandScene(state.activeWorld, worldLevel(state), {
    motion: false,
  });
}
function homeHero() {
  const w = getWorld(state.activeWorld),
    level = worldLevel(state),
    next = UPGRADES[level];
  return `<section class="hero living-hero"><div class="hero-copy"><span class="tag">${w.name.toUpperCase()} · ТВОЙ ЖИВОЙ МИР</span><h2>Маленькие старания.<br>Большая жизнь.</h2><p>${level ? w.effects[level - 1] : "Два друга у костра, а за туманом — неизведанные земли. Твои звёзды помогут им открыть новый мир."}</p><button class="gold" data-page="world">На мой остров ${icon("arrow", 18)}</button><button class="hero-tour" data-tour="open">Как оживает мир?</button><div class="hero-progress"><span>${next ? `Следом: ${w.names[level]}` : "Все открытия этого острова — твои!"}</span>${next ? `<progress value="${Math.min(state.balance, next.cost)}" max="${next.cost}"></progress><span>${state.balance} / ${next.cost} ✦</span>` : ""}</div></div>${worldArt()}</section>`;
}
function title(name, sub) {
  return `<div class="page-title"><div><h1>${name}</h1><p class="muted">${sub}</p></div><span class="date">${new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "short" })}</span></div>`;
}
function choresList(all = false) {
  const list = state.chores.filter((c) => all || due(c));
  return list.length
    ? list
        .map(
          (c) =>
            `<div class="task ${completed(c) ? "done" : ""}"><input type="checkbox" id="chore-${c.id}" data-chore="${c.id}" ${completed(c) ? "checked" : ""} ${!due(c) ? "disabled" : ""}><label for="chore-${c.id}"><b>${escapeHTML(c.name)}</b><small>${scheduleName(c)}</small></label><span class="pill">${!due(c) ? "Не сегодня" : completed(c) ? "Готово ✓" : c.schedule === "any" ? "Доброе дело" : "На сегодня"}</span></div>`,
        )
        .join("")
    : '<p class="empty">На сегодня поручений нет. Можно отдохнуть!</p>';
}
function lessonTiles() {
  return `<div class="lesson-grid">${state.tasks
    .filter((t) => t.group !== "walk")
    .map(
      (t) =>
        `<button class="lesson" data-task="${t.id}"><span class="icon">${t.icon}</span><span>${escapeHTML(t.name)}<small>${state.timers[t.id]?.started ? "Таймер идёт" : state.timers[t.id]?.elapsed ? "На паузе · время сохранено" : "Открыть таймер →"}</small></span></button>`,
    )
    .join("")}</div>`;
}
function totals() {
  let result = [0, 0, 0];
  state.entries
    .filter((e) => e.date >= dayAgo(6) && e.date <= today())
    .forEach((e) => {
      const task = state.tasks.find((t) => t.id === e.task);
      result[task?.group === "lessons" ? 0 : task?.group === "walk" ? 1 : 2] +=
        e.seconds / 60;
    });
  return result;
}
function barChart() {
  const local = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const weeks = Array.from({ length: 4 }, (_, i) => {
    const start = new Date();
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 7 * (3 - i));
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    const values = [0, 0, 0];
    state.entries
      .filter((e) => e.date >= local(start) && e.date <= local(end))
      .forEach((e) => {
        const t = state.tasks.find((t) => t.id === e.task);
        values[t?.group === "lessons" ? 0 : t?.group === "walk" ? 1 : 2] +=
          e.seconds / 60;
      });
    return {
      label:
        start.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) +
        (i === 3 ? " *" : ""),
      values,
    };
  });
  return stackedChart(weeks);
}
function donut() {
  return donutChart(totals());
}
function home() {
  let done = state.chores.filter((c) => due(c) && completed(c)).length,
    total = state.chores.filter(due).length,
    walk = minutes("walk", today());
  return (
    title(
      `Привет, ${escapeHTML(state.profile.name)}!`,
      "Сегодня — ещё один шаг к большим открытиям",
    ) +
    homeHero() +
    `<section class="stats"><div class="card stat"><span class="icon">↗</span><div><div class="stat-label">Время на математику</div><div class="stat-value">−14% <span class="positive">↘</span></div><small>Пример достижения · без потери качества</small></div></div><div class="card stat"><span class="icon teal">☀</span><div><div class="stat-label">Прогулка сегодня</div><div class="stat-value">${fmt(walk)} <small>/ 120 мин</small></div><small>${walk >= 120 ? "Цель достигнута. Отличная прогулка!" : "Время для воздуха и новых открытий"}</small></div></div><div class="card stat"><span class="icon gold">✓</span><div><div class="stat-label">Дела на сегодня</div><div class="stat-value">${done} <small>из ${total}</small></div><small>Маленькие дела становятся привычками</small></div></div></section><div class="grid"><section class="card"><div class="section-head"><h2>Мои дела на сегодня</h2><button class="text-button" data-page="chores">Все поручения →</button></div>${choresList()}</section><section class="card"><div class="section-head"><h2>Пора позаниматься?</h2><small>Выбери занятие</small></div>${lessonTiles()}<div class="walk-strip"><div><b>☀ А потом — на прогулку!</b><br><small>Твоя цель — 2 часа на свежем воздухе</small></div><button data-task="walk" aria-label="Открыть таймер прогулки">→</button></div></section></div><div class="grid"><section class="card"><div class="section-head"><h2>Как проходит моё время</h2><span class="pill">4 недели</span></div>${barChart()}</section><section class="card"><div class="section-head"><h2>Баланс занятий</h2><span class="pill">7 дней</span></div>${donut()}<small>Только записанное время, а не весь день</small></section></div><section class="card"><div class="section-head"><h2>Есть чем гордиться</h2><button class="text-button" data-page="rewards">Мои награды →</button></div><div class="achievement"><span class="icon gold">✦</span><div><h3>Шаг за шагом — к новым островам</h3><p>Пример: неделя регулярных прогулок и выполненных дел. Награды в макете демонстрационные.</p></div><span>+45 ✦</span></div></section>`
  );
}
function timerData() {
  return (
    state.timers[selected] ||
    (state.timers[selected] = { elapsed: 0, started: null })
  );
}
function elapsed(t) {
  return t.elapsed + (t.started ? Date.now() - t.started : 0);
}
function timeString(ms) {
  const s = Math.floor(ms / 1000);
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}
function lineChart() {
  const days = new Map();
  for (const entry of state.entries) {
    if (entry.task === selected) {
      days.set(entry.date, (days.get(entry.date) || 0) + entry.seconds / 60);
    }
  }
  return progressChart(
    [...days]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({ date, v })),
  );
}
function taskPage() {
  const t = state.tasks.find((t) => t.id === selected),
    timer = timerData(),
    rows = state.entries
      .filter((e) => e.task === selected)
      .sort((a, b) => b.date.localeCompare(a.date));
  return (
    title(
      `${t.icon} ${escapeHTML(t.name)}`,
      t.group === "lessons"
        ? "Не торопись: понять важнее, чем закончить первым."
        : "Время для того, что важно тебе",
    ) +
    `<div class="tab-row"><button data-page="home">← Мой день</button>${state.tasks.map((t) => `<button class="${t.id === selected ? "selected" : ""}" data-task="${t.id}">${escapeHTML(t.name)}</button>`).join("")}</div><div class="grid"><section class="card timer"><span class="pill" id="timer-status">${timer.started ? "● Таймер идёт" : "Таймер готов · можно продолжить"}</span><div class="timer-number" id="timer-value">${timeString(elapsed(timer))}</div><p class="muted">Проверка и перерыв? Поставь на паузу.</p><div class="timer-actions"><button class="primary" id="toggle-timer">${timer.started ? "Ⅱ Пауза" : "▶ Начать / продолжить"}</button><button class="gold" id="save-timer">✓ Сохранить за сегодня</button><button class="ghost" id="reset-timer">Сбросить</button></div><small>У каждого занятия свой таймер. Время не пропадёт при переходе.</small></section><section class="card"><h2>Добавить время вручную</h2><p class="muted">Если забыл включить таймер — ничего страшного.</p><form id="manual-form" class="fields"><label>Дата<input name="date" type="date" value="${today()}" max="${today()}" required></label><label>Сколько минут?<input name="minutes" type="number" min="1" max="1440" step="1" placeholder="Например, 25" required></label><button class="primary">Добавить запись</button></form></section></div><section class="card"><div class="section-head"><h2>Мой прогресс</h2><span class="pill">За всё время</span></div>${lineChart()}<small>Показана вся история. Записи за день суммируются; даты без занятий не считаются нулями. Линия последовательно соединяет все записанные даты.</small></section><section class="card" style="margin-top:22px"><div class="section-head"><h2>История за всё время</h2><small>${rows.length} записей</small></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Время</th><th>Источник</th></tr></thead><tbody>${rows.map((e) => `<tr><td>${e.date.split("-").reverse().join(".")}</td><td>${fmt(e.seconds / 60)} мин</td><td>${e.source}</td></tr>`).join("") || '<tr><td colspan="3">Пока нет записей. Начнём с первой!</td></tr>'}</tbody></table></div></section>`
  );
}
function rewards() {
  return (
    title(
      "Твои маленькие победы",
      "Звёзды за привычки, которые остаются с тобой",
    ) +
    `<div class="notice">Демонстрация экрана: начисления ниже — примеры, а не расчёт по локальным записям. Настоящие награды рассчитывает сервер раз в 7 дней.</div><div class="stats"><div class="card"><small>Можно потратить</small><div class="stat-value">${state.balance} ✦</div></div><div class="card"><small>За пример последней недели</small><div class="stat-value">+95 ✦</div></div><div class="card"><small>Следующая оценка</small><div class="stat-value">Через 4 дня</div></div></div><div class="grid"><section class="card"><h2>За что приходят звёзды</h2>${[
      [
        "↗",
        "Уроки стали даваться быстрее",
        "Есть подтверждённый прогресс, а качество не снизилось.",
        "+30",
      ],
      [
        "☀",
        "Больше времени на воздухе",
        "Цель прогулки достигнута в 5 из 7 дней.",
        "+40",
      ],
      [
        "✓",
        "На тебя можно положиться",
        "Все запланированные поручения выполнены.",
        "+25",
      ],
    ]
      .map(
        (r) =>
          `<div class="achievement"><span class="icon">${r[0]}</span><div><h3>${r[1]}</h3><p>${r[2]}</p></div><span>${r[3]} ✦</span></div>`,
      )
      .join(
        "",
      )}<p class="notice">Нет улучшения времени уроков — нет звёзд за скорость. Но награды за прогулки и поручения остаются доступными.</p></section><section class="card"><h2>Письмо от хранителя острова</h2><p>«Алексей, ты всё чаще находишь время для прогулки и не забываешь про свои дела. Это замечательно!</p><p>С уроками не нужно спешить. Продолжай разбираться в сложных задачах, а я буду ждать тебя на острове».</p><p class="muted">Пример доброжелательной обратной связи. OpenAI в макете не подключён.</p><button class="gold" data-page="world">Потратить звёзды →</button></section></div><section class="card"><h2>История кошелька</h2><table><thead><tr><th>Событие</th><th>Звёзды</th></tr></thead><tbody><tr><td>Начальный демонстрационный баланс</td><td>+145 ✦</td></tr>${state.purchases.map((p) => `<tr><td>${getWorld(p.world).name} · ${getWorld(p.world).names[UPGRADES.findIndex((u) => u.id === p.id)]}</td><td>−${p.cost} ✦</td></tr>`).join("")}${state.bought.map((id) => `<tr><td>${{ garden: "Сад светлячков", bridge: "Солнечный мост", lighthouse: "Маяк открытий" }[id]}</td><td>−${{ garden: 60, bridge: 90, lighthouse: 200 }[id]} ✦</td></tr>`).join("")}</tbody></table></section>`
  );
}
function world() {
  return worldPage(state, previewLevel);
}
function settings() {
  return (
    title(
      "Настройки приложения",
      "Занятия, правила наград и подключения. Личные данные — в профиле по клику на аватар.",
    ) +
    `<div class="settings-grid"><div><section class="card"><h2>Новое занятие или поручение</h2><form id="new-task" class="fields"><label>Название<input name="name" maxlength="70" placeholder="Например, покормить кота" required></label><label>Тип<select name="type"><option value="boolean">Поручение · выполнено / нет</option><option value="timed">Занятие · с таймером</option></select></label><label>Расписание поручения<select name="schedule"><option value="daily">Каждый день</option><option value="weekdays">По будням</option><option value="weekly">Раз в неделю</option><option value="any">Без расписания</option></select></label><label>День для «раз в неделю»<select name="weekday">${["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"].map((d, i) => `<option value="${i}" ${i === 5 ? "selected" : ""}>${d}</option>`).join("")}</select></label><button class="primary">Добавить</button></form><small>В макете расписание применяется к поручениям. Настройка целей занятий описана в спецификации.</small></section></div><div><section class="card"><h2>Как начислять награды</h2><p class="muted">В рабочем приложении — только для взрослого.</p><label>Режим<select id="reward-mode"><option value="math" ${state.mode === "math" ? "selected" : ""}>По понятным правилам</option><option value="ai" ${state.mode === "ai" ? "selected" : ""}>AI-оценка в пределах правил</option></select></label><div class="notice">Модель сможет объяснить результат и выбрать бонус в разрешённом диапазоне. Проверка условий и кошелёк остаются под контролем сервера.</div></section><section class="card"><h2>Подключения сервера</h2><p class="muted">Визуальный образец защищённой формы администратора.</p><div class="fields"><label>OpenAI API key<input type="password" placeholder="••••••••••••••••" disabled autocomplete="off"></label><label>Supabase URL<input type="password" placeholder="••••••••••••••••" disabled autocomplete="off"></label><label>Строка подключения PostgreSQL<input type="password" placeholder="••••••••••••••••" disabled autocomplete="off"></label><button disabled>Проверить и сохранить в .env</button></div><small>Не вводи настоящие ключи в макет. В реализации они сохраняются только на сервере, никогда в браузере или Git.</small></section><section class="card"><h2>Демонстрационные данные</h2><p class="muted">Авторизация и Supabase пока не подключены. Этот профиль не является защищённым аккаунтом.</p><button id="reset-demo" class="ghost">Восстановить исходный макет</button></section></div></div>`
  );
}
function render() {
  disposeCharts();
  applyTheme();
  document.querySelector(".app").hidden = signedOut;
  document.getElementById("signed-out").hidden = !signedOut;
  if (signedOut) return;
  $("balance").textContent = state.balance;
  $("header-name").textContent = state.profile.name;
  $("crumb").textContent =
    page === "profile"
      ? "Мой профиль"
      : menus.find((m) => m[0] === page)?.[2] || "Занятие";
  $("nav").innerHTML = menus
    .map(
      ([id, unused, name]) =>
        `<a href="#${id}" class="${page === id || (page === "task" && ((selected === "walk" && id === "walk") || (selected !== "walk" && id === "lessons"))) ? "active" : ""}" ${page === id ? 'aria-current="page"' : ""} title="${name}">${icon(id)}<em>${name}</em></a>`,
    )
    .join("");
  $("main").innerHTML =
    page === "profile"
      ? profile()
      : page === "home"
        ? home()
        : page === "task"
          ? taskPage()
          : page === "rewards"
            ? rewards()
            : page === "world"
              ? world()
              : page === "settings"
                ? settings()
                : page === "chores"
                  ? title(
                      "Мои поручения",
                      "Забота о себе и помощь другим — тоже достижения",
                    ) +
                    `<section class="card"><h2>Сегодня и по расписанию</h2>${choresList(true)}<div class="notice">Отметка сохраняется за сегодняшний день. Звёзды за регулярность появятся после оценки недели. Дела без расписания отмечаются не более одного раза в день.</div><button data-page="settings" class="primary">+ Добавить поручение</button></section>`
                  : title(
                      "Мои занятия",
                      "Выбери урок или занятие, чтобы включить его таймер",
                    ) + `<section class="card">${lessonTiles()}</section>`;
  mountCharts();
  if (page === "world") revealActiveWorld();
}
function revealActiveWorld() {
  const rail = document.querySelector(".world-rail");
  const card = rail?.querySelector('[aria-pressed="true"]');
  if (!rail || !card) return;
  const left =
    card.getBoundingClientRect().left -
    rail.getBoundingClientRect().left +
    rail.scrollLeft;
  if (left < rail.scrollLeft) rail.scrollLeft = left;
  else if (left + card.offsetWidth > rail.scrollLeft + rail.clientWidth)
    rail.scrollLeft = left + card.offsetWidth - rail.clientWidth;
}
function go(p, task) {
  location.hash = task ? "task/" + task : p;
}
function route() {
  const [p, id] = location.hash.slice(1).split("/");
  if (p === "walk") {
    page = "task";
    selected = "walk";
  } else if (p === "task" && state.tasks.some((t) => t.id === id)) {
    page = "task";
    selected = id;
  } else page = p === "profile" || menus.some((m) => m[0] === p) ? p : "home";
  previewLevel = null;
  render();
}
window.addEventListener("hashchange", () => {
  route();
  window.scrollTo(0, 0);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.id === "demo-sign-in") {
    signedOut = false;
    sessionStorage.removeItem("vse-demo-signed-out");
    go("home");
    route();
    if (!state.onboardingSeen) startTour();
    return;
  }
  if (b.dataset.page) return go(b.dataset.page);
  if (b.dataset.task) return go("task", b.dataset.task);
  if (signedOut) return;
  if (b.dataset.themeChoice) {
    state.theme = b.dataset.themeChoice;
    persist();
    applyTheme();
    return;
  }
  if (b.dataset.tour === "open") {
    startTour();
    return;
  }
  if (b.dataset.catalog === "open") {
    openWorldCatalog(state, (id) => {
      if (!WORLDS.some((w) => w.id === id)) return;
      if (!state.worldShelf.includes(id)) state.worldShelf.push(id);
      state.activeWorld = id;
      previewLevel = null;
      persist();
      render();
      const card = document.querySelector(`[data-world="${id}"]`);
      card?.focus({ preventScroll: true });
      revealActiveWorld();
    });
    return;
  }
  if (b.dataset.rail) {
    const rail = document.querySelector(".world-rail");
    rail?.scrollBy({
      left: Number(b.dataset.rail) * rail.clientWidth * 0.75,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
    return;
  }
  if (b.dataset.world) {
    state.activeWorld = b.dataset.world;
    previewLevel = null;
    persist();
    render();
    document
      .querySelector(`.world-rail [data-world="${state.activeWorld}"]`)
      ?.focus({ preventScroll: true });
    return;
  }
  if (b.dataset.preview !== undefined) {
    previewLevel =
      b.dataset.preview === "actual" ? null : Number(b.dataset.preview);
    render();
    document
      .querySelector(".world-stage")
      ?.scrollIntoView({ block: "start", behavior: "instant" });
    return;
  }
  if (b.dataset.buy) {
    const u = UPGRADES.find((u) => u.id === b.dataset.buy),
      w = getWorld(state.activeWorld),
      progress = state.worlds[w.id];
    if (
      !u ||
      progress.unlocked.includes(u.id) ||
      (u.requires && !progress.unlocked.includes(u.requires)) ||
      state.balance < u.cost
    )
      return;
    state.balance -= u.cost;
    progress.unlocked.push(u.id);
    progress.log.push({ id: u.id, date: new Date().toISOString() });
    state.purchases.push({ world: w.id, id: u.id, cost: u.cost });
    previewLevel = null;
    persist();
    render();
    toast(`${w.names[UPGRADES.indexOf(u)]}: остров изменился!`);
    document
      .querySelector(".world-stage")
      ?.scrollIntoView({ block: "start", behavior: "instant" });
    return;
  }
  if (b.id === "sign-out") {
    for (const t of Object.values(state.timers)) {
      if (t.started) {
        t.elapsed = elapsed(t);
        t.started = null;
      }
    }
    persist();
    signedOut = true;
    sessionStorage.setItem("vse-demo-signed-out", "1");
    render();
    document.getElementById("demo-sign-in").focus();
    return;
  }
  if (b.id === "toggle-timer") {
    let t = timerData();
    if (t.started) {
      t.elapsed = elapsed(t);
      t.started = null;
    } else t.started = Date.now();
    persist();
    render();
  }
  if (
    b.id === "reset-timer" &&
    confirm("Сбросить несохранённое время этого занятия?")
  ) {
    state.timers[selected] = { elapsed: 0, started: null };
    persist();
    render();
  }
  if (b.id === "save-timer") {
    const t = timerData(),
      seconds = Math.floor(elapsed(t) / 1000);
    if (seconds < 1) return toast("Сначала запусти таймер хотя бы на секунду.");
    if (seconds > 86400)
      return toast(
        "Больше 24 часов: сбрось забытый таймер и внеси время вручную.",
      );
    state.entries.push({
      task: selected,
      date: today(),
      seconds,
      source: "Таймер",
    });
    state.timers[selected] = { elapsed: 0, started: null };
    persist();
    render();
    toast("Время записано за сегодня. Таймер сброшен.");
  }
  if (
    b.id === "reset-demo" &&
    confirm("Удалить изменения макета и вернуть демо-данные?")
  ) {
    state = initial();
    migrateWorlds(state);
    previewLevel = null;
    persist();
    render();
    startTour();
    toast("Макет восстановлен");
  }
});
document.addEventListener("change", (e) => {
  if (e.target.dataset.chore) {
    state.done[today() + ":" + e.target.dataset.chore] = e.target.checked;
    persist();
    render();
    toast(e.target.checked ? "Дело сделано. Здорово!" : "Отметка отменена");
  }
  if (e.target.id === "theme") {
    state.theme = e.target.value;
    persist();
    applyTheme();
  }
  if (e.target.id === "reward-mode") {
    state.mode = e.target.value;
    persist();
    toast("Выбор сохранён для демонстрации");
  }
});
document.addEventListener("submit", (e) => {
  e.preventDefault();
  if (signedOut) return;
  const data = new FormData(e.target);
  if (e.target.id === "profile-form") {
    const name = String(data.get("name")).trim();
    if (!name) return toast("Введи имя.");
    state.profile = {
      name,
      grade: String(data.get("grade")),
      timezone: String(data.get("timezone")),
    };
    persist();
    render();
    toast("Профиль сохранён");
    return;
  }
  if (e.target.id === "manual-form") {
    const date = String(data.get("date")),
      n = Number(data.get("minutes"));
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      date > today() ||
      n < 1 ||
      n > 1440 ||
      !Number.isInteger(n)
    )
      return toast("Проверь дату и время от 1 до 1440 минут.");
    state.entries.push({
      task: selected,
      date,
      seconds: n * 60,
      source: "Вручную",
    });
    persist();
    render();
    toast("Запись добавлена. Текущий таймер не изменён.");
  }
  if (e.target.id === "new-task") {
    const name = String(data.get("name")).trim();
    if (!name) return toast("Введи название.");
    const id = "custom-" + Date.now();
    if (data.get("type") === "timed")
      state.tasks.push({ id, name, icon: "◷", group: "other" });
    else
      state.chores.push({
        id,
        name,
        schedule: data.get("schedule"),
        weekday: Number(data.get("weekday")),
      });
    persist();
    render();
    toast("Добавлено! Найди новое дело в соответствующем разделе.");
  }
});
setInterval(() => {
  if (page === "task" && $("timer-value")) {
    $("timer-value").textContent = timeString(elapsed(timerData()));
  }
}, 500);
window.addEventListener("storage", (e) => {
  if (e.key === KEY && e.newValue) {
    try {
      state = JSON.parse(e.newValue);
      migrateWorlds(state);
      render();
    } catch {}
  }
});
document.addEventListener("visibilitychange", () => {
  document.body.classList.toggle("world-document-hidden", document.hidden);
});
route();
if (!signedOut && !state.onboardingSeen) startTour();

function profile() {
  return (
    title(
      "Мой профиль",
      "Только о тебе — без подключений и настроек приложения.",
    ) +
    `<section class="card profile-card"><div class="profile-heading"><img src="../logos/user.png" alt="Аватар пользователя"><div><span class="overline">ИССЛЕДОВАТЕЛЬ ОСТРОВОВ</span><h2>${escapeHTML(state.profile.name)}</h2><p class="muted">Личный демонстрационный профиль</p></div></div><form id="profile-form" class="fields"><label>Как тебя зовут?<input name="name" maxlength="40" value="${escapeHTML(state.profile.name)}" required></label><label>Класс<select name="grade">${[1, 2, 3, 4].map((n) => `<option value="${n}" ${state.profile.grade === String(n) ? "selected" : ""}>${n} класс</option>`).join("")}</select></label><label>Часовой пояс профиля<select name="timezone">${["Europe/Moscow", "Europe/Kaliningrad", "Asia/Yekaterinburg", "Asia/Novosibirsk", "Asia/Vladivostok"].map((z) => `<option ${state.profile.timezone === z ? "selected" : ""}>${z}</option>`).join("")}</select></label><small>В макете даты пока используют часовой пояс браузера. Серверный учёт по профилю — следующий этап.</small><button class="primary">Сохранить профиль</button></form><div class="profile-exit"><div><b>До следующего открытия!</b><small>При выходе таймеры встанут на паузу. Данные макета останутся в этом браузере.</small></div><button id="sign-out" class="ghost">${icon("exit", 18)} Sign Out / Выйти</button></div></section>`
  );
}
function startTour() {
  openOnboarding({
    state,
    onFinish: (world) => {
      state.onboardingSeen = true;
      if (world) {
        state.activeWorld = world;
        if (!state.worldShelf.includes(world)) state.worldShelf.push(world);
        previewLevel = null;
      }
      persist();
      if (world) {
        go("world");
        if (page === "world") render();
      }
    },
  });
}
