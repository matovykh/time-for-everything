import { islandScene, WORLDS, getWorld } from "./worlds.js";
import { icon } from "./icons.js";

const steps = [
  {
    label: "Замечай время",
    title: "У твоих стараний\nпоявится свой мир",
    text: "Включай таймер, когда садишься за уроки. Перерывы и проверка — на паузе. Сравнивай себя только с собой, а не с одноклассниками.",
    note: "Не гонись за секундомером. Понять задачу важнее, чем закончить первым.",
    symbol: "timer",
    stage: 0,
  },
  {
    label: "Расти понемногу",
    title: "Маленькие дела.\nБольшие перемены.",
    text: "Учись внимательнее, находи время для прогулки и выполняй свои поручения. Регулярность важнее одного идеального дня.",
    note: "Улучшения оцениваются за неделю. Разовый быстрый урок — ещё не повод для награды.",
    symbol: "chores",
    stage: 1,
  },
  {
    label: "Получай звёзды",
    title: "Старался всю неделю?\nЭто стоит звёзд.",
    text: "За подтверждённый прогресс и полезные привычки ты получаешь звёзды. Они превращают старания в открытия — без покупок за настоящие деньги.",
    note: "Здесь показан пример награды. В знакомстве звёзды не начисляются и не тратятся.",
    symbol: "rewards",
    stage: 2,
  },
  {
    label: "Пробуждай жизнь",
    title: "Твой остров.\nТвои открытия.",
    text: "За туманом — новые земли и ресурсы. Мастерские дают жителям занятия, гавань — лодки и путешествия. Ты не просто строишь: ты меняешь их жизнь.",
    note: "Остров не голодает и не разрушается без тебя. Возвращайся, когда захочешь.",
    symbol: "world",
    stage: 4,
  },
];

export function openOnboarding({ state, onFinish }) {
  const previous = document.querySelector("#onboarding");
  if (previous?.open) return;
  previous?.remove();
  const opener = document.activeElement;
  const dialog = document.createElement("dialog");
  dialog.id = "onboarding";
  dialog.className = "onboarding";
  dialog.setAttribute("aria-labelledby", "tour-title");
  document.body.append(dialog);
  let step = 0,
    world = state.activeWorld,
    previewStage = 4,
    finished = false;
  function close(completed = false) {
    if (finished) return;
    finished = true;
    dialog.close();
    dialog.remove();
    onFinish(completed ? world : null);
    if (opener?.isConnected) opener.focus();
    else document.querySelector('[data-tour="open"]')?.focus();
  }
  function draw() {
    const s = steps[step],
      stage = step === 3 ? previewStage : s.stage;
    dialog.innerHTML = `<div class="tour-top"><span class="tour-brand">${icon("spark", 20)} Всё успею <span>/ первое открытие</span></span><button data-tour-close aria-label="Закрыть знакомство">${icon("close")}</button></div><div class="tour-layout"><div class="tour-copy"><div class="tour-steps">${steps.map((s, i) => `<span class="${i === step ? "current" : i < step ? "passed" : ""}" title="${s.label}">${i + 1}</span>`).join("")}</div><span class="overline">ШАГ ${step + 1} ИЗ 4 · ${s.label.toUpperCase()}</span><h2 id="tour-title">${s.title.replace("\n", "<br>")}</h2><p>${s.text}</p><div class="tour-note">${icon(s.symbol, 22)}<span>${s.note}</span></div>${step === 3 ? `<label class="tour-world-label">Какой мир тебе ближе?<select id="tour-world">${WORLDS.map((w) => `<option value="${w.id}" ${w.id === world ? "selected" : ""}>${w.name} — ${w.type}</option>`).join("")}</select></label>` : ""}</div><div class="tour-visual"><span class="tour-preview-label">${step === 3 ? "ПОПРОБУЙ: МИР ДО И ПОСЛЕ ОТКРЫТИЙ" : "ТВОЯ ИСТОРИЯ ТОЛЬКО НАЧИНАЕТСЯ"}</span>${islandScene(world, stage, { preview: true, motion: true })}<div class="tour-demo-card">${step === 0 ? `${icon("timer", 30)}<div><small>Математика · пример таймера</small><b>00:24:08</b></div><span class="pill">На паузе</span>` : step === 1 ? `${icon("check", 30)}<div><small>Шаг за шагом</small><b>Уроки · прогулки · помощь дома</b></div>` : step === 2 ? `${icon("rewards", 32)}<div><small>Пример недельного результата</small><b>+ 60 звёзд для открытий</b></div>` : `<div><small>${getWorld(world).name} · предпросмотр</small><b>${stage === 0 ? "Тихий лагерь и два друга" : stage === 2 ? "Работают мастерские, жители заняты делом" : "Живой остров с гостями и путешествиями"}</b></div>`}</div>${
      step === 3
        ? `<div class="tour-comparison">${[
            [0, "До открытий"],
            [2, "Первые улучшения"],
            [4, "Живой мир"],
          ]
            .map(
              ([n, l]) =>
                `<button data-tour-stage="${n}" class="${previewStage === n ? "selected" : ""}" aria-pressed="${previewStage === n}">${l}</button>`,
            )
            .join("")}</div>`
        : `<div class="tour-caption">${["Сначала маленький лагерь. Дальше — целое приключение.", "Новые территории открывают новые возможности.", "Мастерская меняет не только вид, но и жизнь острова."][step]}</div>`
    }</div></div><div class="tour-bottom"><button class="text-button" data-tour-close>Познакомлюсь позже</button><div><button class="ghost" data-tour-back ${step === 0 ? "disabled" : ""}>Назад</button><button class="primary tour-next" data-tour-next>${step === 3 ? "Отправиться на мой остров" : "Дальше"} ${icon("arrow", 18)}</button></div></div>`;
    const heading = dialog.querySelector("#tour-title");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    dialog.scrollTop = 0;
  }
  dialog.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-tour-close")) close();
    else if (b.hasAttribute("data-tour-back")) {
      step = Math.max(0, step - 1);
      draw();
    } else if (b.hasAttribute("data-tour-next")) {
      if (step === 3) close(true);
      else {
        step++;
        draw();
      }
    } else if (b.dataset.tourStage !== undefined) {
      previewStage = Number(b.dataset.tourStage);
      draw();
    }
  });
  dialog.addEventListener("change", (e) => {
    if (e.target.id === "tour-world") {
      world = e.target.value;
      draw();
      dialog.querySelector("#tour-world").focus();
    }
  });
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    close();
  });
  draw();
  dialog.showModal();
  dialog.querySelector("#tour-title").focus({ preventScroll: true });
  dialog.scrollTop = 0;
}
