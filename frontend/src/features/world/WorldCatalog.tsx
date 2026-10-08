import { useEffect, useState } from "react";
import * as ep from "../../shared/api/endpoints";
import type { CatalogWorld } from "../../shared/api/types";
import { Dialog } from "../../shared/ui/Dialog";
import { Icon } from "../../shared/ui/Icon";
import { ErrorState, Loading } from "../../shared/ui/States";
import { CatalogEmblem } from "./WorldArt";

/** Searchable, unlimited catalogue. Adding a world is free; stars are only for upgrades. */
export function WorldCatalog({ onClose, onSelect }: { onClose: () => void; onSelect: (code: string) => void }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<CatalogWorld[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<{ loading: boolean; error: unknown }>({ loading: true, error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const t = window.setTimeout(async () => {
      setState({ loading: true, error: null });
      try {
        const page = await ep.searchCatalog(query.trim());
        if (cancelled) return;
        setItems(page.items);
        setCursor(page.next_cursor);
        setState({ loading: false, error: null });
      } catch (e) {
        if (!cancelled) setState({ loading: false, error: e });
      }
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [query, attempt]);

  async function more() {
    if (!cursor) return;
    setState({ loading: true, error: null });
    try {
      const page = await ep.searchCatalog(query.trim(), cursor);
      setItems((prev) => [...prev, ...page.items]);
      setCursor(page.next_cursor);
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }

  return (
    <Dialog className="world-catalog" labelledBy="catalog-title" onClose={onClose}>
      <div className="catalog-heading">
        <div>
          <span className="overline">ОДНИ ПРАВИЛА · РАЗНЫЕ ПРИКЛЮЧЕНИЯ</span>
          <h2 id="catalog-title">Каталог миров</h2>
        </div>
        <button onClick={onClose} aria-label="Закрыть каталог">
          <Icon name="close" />
        </button>
      </div>
      <p>Добавление мира бесплатно. Звёзды нужны только для его открытий. Прогресс каждого мира сохраняется отдельно.</p>
      <label className="catalog-search">
        Найти свой мир
        <input
          type="search"
          placeholder="Название или настроение мира"
          autoComplete="off"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {state.error && !items.length ? (
        <ErrorState error={state.error} onRetry={() => setAttempt((a) => a + 1)} />
      ) : state.loading && !items.length ? (
        <Loading />
      ) : (
        <div className="catalog-grid" aria-live="polite">
          {items.length ? (
            items.map((w) => (
              <article key={w.code} className="catalog-world">
                <CatalogEmblem code={w.code} />
                <span className="overline">{w.badge}</span>
                <h3>{w.name}</h3>
                <p>{w.type}</p>
                <small>
                  {w.in_collection
                    ? `${w.level} из ${w.upgrades_total} открытий · уже в коллекции`
                    : "Новый мир · начни с первого лагеря"}
                </small>
                <button className={w.in_collection ? "ghost" : "primary"} onClick={() => onSelect(w.code)}>
                  {w.in_collection ? "Открыть мой мир" : "Добавить в мои миры"}
                </button>
              </article>
            ))
          ) : (
            <p className="empty">Мир не найден. Попробуй другое название.</p>
          )}
        </div>
      )}
      {cursor && (
        <button className="ghost load-more" onClick={more} disabled={state.loading}>
          Показать ещё
        </button>
      )}
      <small className="catalog-footnote">
        Коллекция не ограничена числом слотов — новые темы появляются в каталоге без перестройки меню.
      </small>
    </Dialog>
  );
}
