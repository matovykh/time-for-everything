import { useEffect, useRef, useState } from "react";
import { useMe, useSession } from "../../app/session";
import { useTour } from "../../app/tour";
import { ApiError } from "../../shared/api/client";
import * as ep from "../../shared/api/endpoints";
import type { CollectionWorld, WorldDetail, WorldUpgrade } from "../../shared/api/types";
import { useApi } from "../../shared/api/useApi";
import { ruDateTime } from "../../shared/dates";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";
import { ErrorState, Loading, errorText } from "../../shared/ui/States";
import { useToast } from "../../shared/ui/Toast";
import { WorldCatalog } from "./WorldCatalog";
import { UpgradeArt, WorldEmblem, WorldScene } from "./WorldArt";

const reduceMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function WorldPage() {
  const me = useMe();
  const { setBalance, updateMe } = useSession();
  const openTour = useTour();
  const toast = useToast();
  const worlds = useApi(() => ep.getWorlds(), [me.acting_child_id]);
  const [active, setActive] = useState<string | null>(me.active_world);
  const [catalogOpen, setCatalogOpen] = useState(false);

  useEffect(() => {
    if (worlds.data) setBalance(worlds.data.balance);
  }, [worlds.data, setBalance]);

  // The profile is the source of truth for the active world (also changed by onboarding).
  useEffect(() => {
    setActive(me.active_world);
  }, [me.active_world]);

  async function choose(code: string) {
    if (code === active) return;
    const previous = active;
    setActive(code);
    try {
      const res = await ep.setActiveWorld(code);
      updateMe({ ...me, active_world: res.active_world });
    } catch (e) {
      setActive(previous);
      toast(e instanceof ApiError && e.code === "not_in_collection" ? "Сначала добавь этот мир в коллекцию." : errorText(e));
    }
  }

  async function addFromCatalog(code: string) {
    setCatalogOpen(false);
    try {
      const inShelf = worlds.data?.items.some((w) => w.code === code);
      if (!inShelf) await ep.addWorld(code);
      await worlds.reload();
      await choose(code);
      toast(inShelf ? "Открываем твой мир" : "Мир добавлен в коллекцию — бесплатно!");
    } catch (e) {
      toast(errorText(e));
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <span className="overline">АРХИПЕЛАГ ВОЗМОЖНОСТЕЙ</span>
          <h1>Здесь оживают твои старания</h1>
          <p className="muted">Не просто постройки. Новые истории, которые начинаются благодаря тебе.</p>
        </div>
        <button className="ghost" onClick={() => openTour()}>
          <Icon name="play" size={18} /> Как это работает
        </button>
      </div>
      {worlds.loading && !worlds.data ? (
        <Loading label="Загружаем острова…" />
      ) : worlds.error && !worlds.data ? (
        <ErrorState error={worlds.error} onRetry={worlds.reload} />
      ) : (
        <>
          <WorldShelf items={worlds.data!.items} active={active} onChoose={choose} onCatalog={() => setCatalogOpen(true)} />
          {active && worlds.data!.items.some((w) => w.code === active) && (
            <WorldStage
              key={active}
              code={active}
              onPurchased={() => void worlds.reload()}
            />
          )}
        </>
      )}
      {catalogOpen && (
        <WorldCatalog onClose={() => setCatalogOpen(false)} onSelect={addFromCatalog} />
      )}
    </>
  );
}

function WorldShelf({
  items,
  active,
  onChoose,
  onCatalog,
}: {
  items: CollectionWorld[];
  active: string | null;
  onChoose: (code: string) => void;
  onCatalog: () => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  // Keep the active panel visible inside the horizontally scrolling rail.
  useEffect(() => {
    const r = rail.current;
    const card = r?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!r || !card) return;
    const left = card.offsetLeft - r.offsetLeft;
    if (left < r.scrollLeft) r.scrollLeft = left;
    else if (left + card.offsetWidth > r.scrollLeft + r.clientWidth) r.scrollLeft = left + card.offsetWidth - r.clientWidth;
  }, [active, items.length]);
  const scroll = (dir: number) =>
    rail.current?.scrollBy({ left: dir * rail.current.clientWidth * 0.75, behavior: reduceMotion() ? "instant" : "smooth" });
  return (
    <section className="world-shelf">
      <div className="section-head">
        <div>
          <h2>Мои миры</h2>
          <small>Листай коллекцию или добавь мир из каталога — бесплатно</small>
        </div>
        <div className="shelf-controls">
          <button className="ghost" onClick={() => scroll(-1)} aria-label="Прокрутить миры влево">
            ←
          </button>
          <button className="ghost" onClick={() => scroll(1)} aria-label="Прокрутить миры вправо">
            →
          </button>
          <button className="primary" onClick={onCatalog}>
            Каталог миров
          </button>
        </div>
      </div>
      <div className="world-rail" ref={rail} tabIndex={0} role="region" aria-label="Коллекция миров, горизонтальная прокрутка">
        {[...items]
          .sort((a, b) => a.position - b.position)
          .map((w) => (
            <button
              key={w.code}
              className={`world-choice ${active === w.code ? "selected" : ""}`}
              aria-pressed={active === w.code}
              style={{ ["--world-accent" as string]: w.color }}
              onClick={() => onChoose(w.code)}
            >
              <WorldEmblem code={w.code} />
              <span className="world-choice-copy">
                <b>{w.name}</b>
                <small>{w.type}</small>
                <span className="world-progress-label">
                  {w.level} из {w.upgrades_total} открытий
                </span>
              </span>
            </button>
          ))}
        <button className="world-add" onClick={onCatalog}>
          <span>＋</span>
          <b>Найти новый мир</b>
          <small>Посмотреть каталог</small>
        </button>
      </div>
    </section>
  );
}

function WorldStage({ code, onPurchased }: { code: string; onPurchased: () => void }) {
  const { setBalance, balance } = useSession();
  const toast = useToast();
  const detail = useApi(() => ep.getWorld(code), [code]);
  const [preview, setPreview] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<WorldUpgrade | null>(null);
  const [buying, setBuying] = useState(false);
  const stageRef = useRef<HTMLElement>(null);
  const [hidden, setHidden] = useState(typeof document !== "undefined" && document.hidden);

  useEffect(() => {
    if (detail.data) setBalance(detail.data.balance);
  }, [detail.data, setBalance]);

  // Pause animation while the tab is hidden; resume on return (no catch-up simulation).
  useEffect(() => {
    const onVis = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  if (detail.loading && !detail.data) return <Loading label="Открываем остров…" />;
  if (detail.error && !detail.data) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  const w: WorldDetail = detail.data!;
  const actual = w.level;
  const level = preview ?? actual;
  const have = balance ?? w.balance;
  const next = w.upgrades.find((u) => !u.owned);
  const events = [...w.events].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const lastEvent = events[0];
  const effectFor = (lvl: number) => w.upgrades.find((u) => u.index === lvl - 1)?.effect;
  const showStage = () => stageRef.current?.scrollIntoView({ block: "start", behavior: "instant" as ScrollBehavior });

  async function buy(u: WorldUpgrade) {
    setBuying(true);
    try {
      const res = await ep.purchaseUpgrade(code, u.code);
      setBalance(res.balance);
      detail.setData(res.world);
      setPreview(null);
      setConfirming(null);
      toast(`${u.title}: остров изменился!`);
      onPurchased();
      requestAnimationFrame(showStage);
    } catch (e) {
      const map: Record<string, string> = {
        insufficient_balance: "Пока не хватает звёзд.",
        prerequisite_missing: "Сначала нужно открыть предыдущий этап.",
        already_owned: "Это открытие уже твоё.",
        not_in_collection: "Этого мира нет в твоей коллекции.",
      };
      toast(e instanceof ApiError ? (map[e.code] ?? errorText(e)) : errorText(e));
      setConfirming(null);
      void detail.reload();
    } finally {
      setBuying(false);
    }
  }

  const territories = 1 + (level >= 1 ? 1 : 0) + (level >= 3 ? 1 : 0);
  const inhabitants = 2 + level * 2;

  return (
    <>
      <section className={`world-stage ${hidden ? "world-document-hidden" : ""}`} ref={stageRef}>
        <div className="world-stage-top">
          <div>
            <span className="overline">{preview !== null ? "БЕСПЛАТНЫЙ ПРЕДПРОСМОТР · НЕ КУПЛЕНО" : "ТВОЙ ЖИВОЙ МИР"}</span>
            <h2>{w.theme.name}</h2>
          </div>
          <div className="world-tools">
            <span className="live-badge">
              <i /> Всё спокойно
            </span>
          </div>
        </div>
        {/* key forces a fresh scene (and removes the old animated DOM) on every stage change */}
        <WorldScene key={`${code}-${level}`} code={code} level={level} motion />
        <div className="world-stage-bottom">
          <span>
            <Icon name="flag" size={18} /> {preview === null ? w.territories : territories} территории
          </span>
          <span>
            <Icon name="people" size={18} /> {preview === null ? w.inhabitants : inhabitants} {w.theme.inhabitants_label}
          </span>
          <span>
            <Icon name="spark" size={18} /> {level >= 2 ? "Мастерская работает" : "Первый лагерь"}
          </span>
          <span>{level >= 1 ? w.theme.resource : "Ресурсы ждут за туманом"}</span>
        </div>
      </section>
      <div className="world-preview-bar">
        <div>
          <b>Загляни в будущее</b>
          <small>Сравни, как изменится жизнь. Звёзды не тратятся.</small>
        </div>
        <div className="preview-steps">
          <button className={preview === null ? "selected" : ""} aria-pressed={preview === null} onClick={() => setPreview(null)}>
            Мой остров
          </button>
          {[0, 1, 2, 3, 4].map((n) => (
            <button
              key={n}
              className={preview === n ? "selected" : ""}
              aria-pressed={preview === n}
              aria-label={`Предпросмотр этапа ${n}`}
              onClick={() => {
                setPreview(n);
                showStage();
              }}
            >
              {n === 0 ? "Старт" : n}
            </button>
          ))}
        </div>
      </div>
      <div className="world-story" role="status">
        <span className="story-avatar">
          <Icon name="people" size={25} />
        </span>
        <div>
          <b>
            {preview !== null
              ? "Вот что изменится на этом этапе"
              : lastEvent
                ? "Новое в твоём мире"
                : "Первая история уже началась"}
          </b>
          <p>
            {preview !== null
              ? level
                ? effectFor(level)
                : "Пока здесь маленький лагерь и два друга. Всё большое начинается с этого."
              : lastEvent
                ? lastEvent.text
                : "Два друга поселились у костра. За туманом — целый мир. Какой будет их следующая история?"}
          </p>
        </div>
      </div>
      <div className="section-head">
        <div>
          <h2>Открывай территории. Меняй жизнь.</h2>
          <p className="muted">
            {next ? `Следующая цель: ${next.title} · ${next.cost} звёзд` : "Этот остров расцвёл! Можно развивать другой — всё здесь сохранится."}
          </p>
        </div>
        <span className="wallet">✦ {have}</span>
      </div>
      <div className="upgrade-grid">
        {[...w.upgrades]
          .sort((a, b) => a.index - b.index)
          .map((u) => {
            const prev = w.upgrades.find((x) => x.code === u.requires);
            const label = u.owned
              ? "✓ Жизнь уже изменилась"
              : u.blocked_reason === "prerequisite_missing"
                ? `Сначала: ${prev?.title ?? "предыдущий этап"}`
                : u.blocked_reason === "insufficient_balance" || have < u.cost
                  ? `Нужно ещё ${Math.max(0, u.cost - have)} ✦`
                  : `Открыть за ${u.cost} ✦`;
            return (
              <article key={u.code} className={`upgrade-card ${u.owned ? "owned" : ""}`}>
                <div className="upgrade-art">
                  <UpgradeArt code={code} index={u.index} />
                  <span className="upgrade-number">0{u.index + 1}</span>
                </div>
                <div className="upgrade-copy">
                  <span className="overline">{u.kind}</span>
                  <h3>{u.title}</h3>
                  <p>{u.effect}</p>
                  <span className="upgrade-property">{u.space}</span>
                  <button
                    className="text-button"
                    onClick={() => {
                      setPreview(u.index + 1);
                      showStage();
                    }}
                  >
                    Посмотреть изменения <Icon name="arrow" size={16} />
                  </button>
                  <button
                    className={u.owned ? "ghost" : "gold"}
                    disabled={u.owned || !u.can_purchase || have < u.cost || buying}
                    onClick={() => setConfirming(u)}
                  >
                    {label}
                  </button>
                </div>
              </article>
            );
          })}
      </div>
      {events.length > 0 && (
        <section className="card world-journal">
          <h2>Журнал острова</h2>
          <ul>
            {events.map((e) => (
              <li key={e.id}>
                <small>{ruDateTime(e.created_at)}</small>
                <p>{e.text}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="notice peaceful">
        <Icon name="check" size={20} /> Мир не голодает, не разрушается и не забывает тебя. Можно вернуться когда угодно — все
        открытия останутся.
      </div>
      {confirming && (
        <Dialog className="confirm-dialog" labelledBy="confirm-title" onClose={() => !buying && setConfirming(null)}>
          <h2 id="confirm-title">Открыть «{confirming.title}»?</h2>
          <p>{confirming.effect}</p>
          <p>
            Стоимость: <b>{confirming.cost} ✦</b>. После покупки останется <b>{have - confirming.cost} ✦</b>.
          </p>
          <div className="dialog-actions">
            <button className="ghost" onClick={() => setConfirming(null)} disabled={buying}>
              Пока нет
            </button>
            <button className="gold" onClick={() => buy(confirming)} disabled={buying} autoFocus>
              {buying ? "Открываем…" : `Открыть за ${confirming.cost} ✦`}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
