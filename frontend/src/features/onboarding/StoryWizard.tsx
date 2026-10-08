import { useEffect, useRef, useState } from "react";
import * as ep from "../../shared/api/endpoints";
import type { CatalogWorld } from "../../shared/api/types";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon, type IconName } from "../../shared/ui/Icon";
import { WorldScene } from "../world/WorldArt";

const STEPS: { label: string; title: string; text: string; note: string; symbol: IconName; stage: number }[] = [
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

const CAPTIONS = [
  "Сначала маленький лагерь. Дальше — целое приключение.",
  "Новые территории открывают новые возможности.",
  "Мастерская меняет не только вид, но и жизнь острова.",
];

/**
 * Preview-only wizard. Choosing a theme here never purchases anything: on
 * finish the parent saves the theme choice and shows the child's real island.
 */
export function StoryWizard({
  initialWorld,
  onClose,
}: {
  initialWorld: string;
  onClose: (result: { completed: boolean; world: string | null }) => void;
}) {
  const [step, setStep] = useState(0);
  const [world, setWorld] = useState(initialWorld);
  const [previewStage, setPreviewStage] = useState(4);
  const [themes, setThemes] = useState<CatalogWorld[]>([]);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const s = STEPS[step];
  const stage = step === 3 ? previewStage : s.stage;
  const themeName = themes.find((t) => t.code === world)?.name ?? "Твой остров";

  useEffect(() => {
    ep.searchCatalog("").then(
      (p) => setThemes(p.items),
      () => setThemes([]),
    );
  }, []);

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  return (
    <Dialog className="onboarding" labelledBy="tour-title" onClose={() => onClose({ completed: false, world: null })}>
      <div className="tour-top">
        <span className="tour-brand">
          <Icon name="spark" size={20} /> Всё успею <span>/ первое открытие</span>
        </span>
        <button onClick={() => onClose({ completed: false, world: null })} aria-label="Закрыть знакомство">
          <Icon name="close" />
        </button>
      </div>
      <div className="tour-layout">
        <div className="tour-copy">
          <div className="tour-steps" aria-hidden="true">
            {STEPS.map((x, i) => (
              <span key={x.label} className={i === step ? "current" : i < step ? "passed" : ""} title={x.label}>
                {i + 1}
              </span>
            ))}
          </div>
          <span className="overline">
            ШАГ {step + 1} ИЗ 4 · {s.label.toUpperCase()}
          </span>
          <h2 id="tour-title" tabIndex={-1} ref={headingRef}>
            {s.title.split("\n").map((line, i) => (
              <span key={i}>
                {i > 0 && <br />}
                {line}
              </span>
            ))}
          </h2>
          <p>{s.text}</p>
          <div className="tour-note">
            <Icon name={s.symbol} size={22} />
            <span>{s.note}</span>
          </div>
          {step === 3 && themes.length > 0 && (
            <label className="tour-world-label">
              Какой мир тебе ближе?
              <select value={world} onChange={(e) => setWorld(e.target.value)}>
                {themes.map((w) => (
                  <option key={w.code} value={w.code}>
                    {w.name} — {w.type}
                  </option>
                ))}
              </select>
            </label>
          )}
          {step === 3 && (
            <p className="muted tour-honesty">
              Качество уроков важнее скорости. Звёзды приходят за устойчивые привычки, а мир не страдает, если ты давно не
              заходил.
            </p>
          )}
        </div>
        <div className="tour-visual">
          <span className="tour-preview-label">
            {step === 3 ? "ПОПРОБУЙ: МИР ДО И ПОСЛЕ ОТКРЫТИЙ" : "ТВОЯ ИСТОРИЯ ТОЛЬКО НАЧИНАЕТСЯ"}
          </span>
          <WorldScene key={`${world}-${stage}`} code={world} level={stage} motion />
          <div className="tour-demo-card">
            {step === 0 ? (
              <>
                <Icon name="timer" size={30} />
                <div>
                  <small>Математика · пример таймера</small>
                  <b>00:24:08</b>
                </div>
                <span className="pill">На паузе</span>
              </>
            ) : step === 1 ? (
              <>
                <Icon name="check" size={30} />
                <div>
                  <small>Шаг за шагом</small>
                  <b>Уроки · прогулки · помощь дома</b>
                </div>
              </>
            ) : step === 2 ? (
              <>
                <Icon name="rewards" size={32} />
                <div>
                  <small>Пример недельного результата</small>
                  <b>+ 60 звёзд для открытий</b>
                </div>
              </>
            ) : (
              <div>
                <small>{themeName} · предпросмотр</small>
                <b>
                  {stage === 0
                    ? "Тихий лагерь и два друга"
                    : stage === 2
                      ? "Работают мастерские, жители заняты делом"
                      : "Живой остров с гостями и путешествиями"}
                </b>
              </div>
            )}
          </div>
          {step === 3 ? (
            <div className="tour-comparison">
              {(
                [
                  [0, "До открытий"],
                  [2, "Первые улучшения"],
                  [4, "Живой мир"],
                ] as const
              ).map(([n, l]) => (
                <button key={n} className={previewStage === n ? "selected" : ""} aria-pressed={previewStage === n} onClick={() => setPreviewStage(n)}>
                  {l}
                </button>
              ))}
            </div>
          ) : (
            <div className="tour-caption">{CAPTIONS[step]}</div>
          )}
        </div>
      </div>
      <div className="tour-bottom">
        <button className="text-button" onClick={() => onClose({ completed: false, world: null })}>
          Познакомлюсь позже
        </button>
        <div>
          <button className="ghost" disabled={step === 0} onClick={() => setStep((x) => Math.max(0, x - 1))}>
            Назад
          </button>
          <button
            className="primary tour-next"
            onClick={() => (step === 3 ? onClose({ completed: true, world }) : setStep((x) => x + 1))}
          >
            {step === 3 ? "Отправиться на мой остров" : "Дальше"} <Icon name="arrow" size={18} />
          </button>
        </div>
      </div>
    </Dialog>
  );
}
