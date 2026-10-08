import { WORLDS, worldLevel } from "./worlds.js";
import { worldEmblem } from "./world-art.js";
import { icon } from "./icons.js";

// No fixed limit: the registry can be extended without changing the shelf layout.
export function openWorldCatalog(state, onSelect) {
  if (document.getElementById("world-catalog")) return;
  const opener = document.activeElement;
  const dialog = document.createElement("dialog");
  dialog.id = "world-catalog";
  dialog.className = "world-catalog";
  dialog.setAttribute("aria-labelledby", "catalog-title");
  dialog.innerHTML = `<div class="catalog-heading"><div><span class="overline">ОДНИ ПРАВИЛА · РАЗНЫЕ ПРИКЛЮЧЕНИЯ</span><h2 id="catalog-title">Каталог миров</h2></div><button data-close-catalog aria-label="Закрыть каталог">${icon("close")}</button></div><p>Добавление мира бесплатно. Звёзды нужны только для его открытий. Прогресс каждого мира сохраняется отдельно.</p><label class="catalog-search">Найти свой мир<input type="search" id="catalog-search" placeholder="Название или настроение мира" autocomplete="off"></label><div id="catalog-results" class="catalog-grid"></div><small class="catalog-footnote">Сейчас доступно ${WORLDS.length} мира. Коллекция не ограничена числом слотов — новые темы можно добавлять в каталог.</small>`;
  document.body.append(dialog);
  function draw(query = "") {
    const matches = WORLDS.filter((w) =>
      `${w.name} ${w.type}`
        .toLocaleLowerCase("ru")
        .includes(query.trim().toLocaleLowerCase("ru")),
    );
    dialog.querySelector("#catalog-results").innerHTML =
      matches
        .map((w) => {
          const owned = state.worldShelf.includes(w.id);
          return `<article class="catalog-world"><div class="catalog-emblem">${worldEmblem(w.id)}</div><span class="overline">${w.badge}</span><h3>${w.name}</h3><p>${w.type}</p><small>${owned ? `${worldLevel(state, w.id)} из 4 открытий · уже в коллекции` : "Новый мир · начни с первого лагеря"}</small><button data-catalog-select="${w.id}" class="${owned ? "ghost" : "primary"}">${owned ? "Открыть мой мир" : "Добавить в мои миры"}</button></article>`;
        })
        .join("") ||
      '<p class="empty">Мир не найден. Попробуй другое название.</p>';
  }
  function close() {
    dialog.close();
    dialog.remove();
    if (opener?.isConnected) opener.focus({ preventScroll: true });
  }
  dialog.addEventListener("input", (event) => {
    if (event.target.id === "catalog-search") draw(event.target.value);
  });
  dialog.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-close-catalog")) close();
    if (button.dataset.catalogSelect) {
      const id = button.dataset.catalogSelect;
      close();
      onSelect(id);
    }
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  draw();
  dialog.showModal();
  dialog.querySelector("#catalog-search").focus();
}
