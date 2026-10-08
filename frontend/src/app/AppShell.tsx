import type { ReactNode } from "react";
import { Icon, type IconName } from "../shared/ui/Icon";
import { hrefFor, type Route } from "./router";
import { useSession } from "./session";
import { ThemeSwitch } from "./ThemeSwitch";
import { useTour } from "./tour";

export const MENUS: [Route["page"], IconName, string][] = [
  ["home", "home", "Мой день"],
  ["lessons", "lessons", "Уроки"],
  ["walk", "walk", "Прогулка"],
  ["chores", "chores", "Поручения"],
  ["world", "world", "Мой мир"],
  ["rewards", "rewards", "Награды"],
  ["settings", "settings", "Настройки"],
];

export function AppShell({
  route,
  activeMenu,
  crumb,
  children,
}: {
  route: Route;
  activeMenu: Route["page"] | null;
  crumb: string;
  children: ReactNode;
}) {
  const { me, balance } = useSession();
  const openTour = useTour();
  const actingChild = me?.children.find((c) => c.id === me.acting_child_id);
  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="#home">
          <img src="/logos/full-logo.png" alt="Всё успею" />
        </a>
        <span className="eyebrow">МАЛЕНЬКИЕ ШАГИ · БОЛЬШИЕ ОТКРЫТИЯ</span>
        <nav aria-label="Главное меню">
          {MENUS.map(([id, icon, name]) => {
            const active = activeMenu === id;
            return (
              <a
                key={id}
                href={hrefFor({ page: id } as Route)}
                className={active ? "active" : ""}
                aria-current={route.page === id ? "page" : undefined}
                title={name}
              >
                <Icon name={icon} />
                <em>{name}</em>
              </a>
            );
          })}
        </nav>
        <button className="tour-sidebar" onClick={() => openTour()}>
          ✦ Знакомство с миром
        </button>
        <div className="sidebar-bottom">
          <img src="/logos/logo.png" alt="" width={42} />
          <div>
            <b>В своём темпе</b>
            <small>Ты соревнуешься только с собой</small>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <div className="breadcrumb">
            Мой остров <span>/</span> <b>{crumb}</b>
          </div>
          <div className="header-right">
            {actingChild && me?.role !== "child" && (
              <span className="demo" title="Вы действуете от имени ребёнка">
                Профиль: {actingChild.display_name}
              </span>
            )}
            <ThemeSwitch />
            <a href="#rewards" className="wallet" aria-label={`Баланс: ${balance ?? "загружается"} звёзд`}>
              ✦ <b>{balance ?? "—"}</b>
            </a>
            <a className="avatar profile-trigger" href="#profile" aria-label="Открыть профиль пользователя">
              <img src="/logos/user.png" alt="" />
              <span>{me?.display_name}</span>
            </a>
          </div>
        </header>
        <main id="main">{children}</main>
        <footer>
          Всё успею · Здесь важен прогресс, а не рекорды
          <span>Данные хранятся на сервере и доступны только тебе и твоему взрослому</span>
        </footer>
      </div>
    </div>
  );
}
