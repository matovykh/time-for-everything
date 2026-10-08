"""World theme registry — content mirrors prototype/worlds.js (WORLDS, UPGRADES).

Codes, costs and prerequisites are also seeded in SQL (world_themes / world_catalog); the server
reads prices and prerequisites from the database at purchase time. A test checks that the SQL seed
and this registry agree. Texts (titles, effects) are served from here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpgradeSpec:
    code: str
    cost: int
    kind: str
    space: str
    requires: str | None


@dataclass(frozen=True)
class ThemeSpec:
    code: str
    name: str
    type: str
    badge: str
    color: str
    resource: str
    inhabitants_label: str
    titles: tuple[str, str, str, str]
    effects: tuple[str, str, str, str]


UPGRADES: tuple[UpgradeSpec, ...] = (
    UpgradeSpec("meadow", 60, "Открытие территории", "+1 территория · +2 жителя", None),
    UpgradeSpec("workshop", 90, "Улучшение жизни", "Производство · +2 жителя", "meadow"),
    UpgradeSpec("harbor", 120, "Открытие территории", "+1 территория · +2 жителя", "workshop"),
    UpgradeSpec("beacon", 180, "Улучшение жизни", "Гости и праздник · +2 жителя", "harbor"),
)

THEMES: tuple[ThemeSpec, ...] = (
    ThemeSpec(
        "settlers", "Тихая бухта", "Поселенцы и путешественники", "ПРИРОДА", "#3ca781",
        "Дерево и плоды", "поселенцев",
        ("Лесная поляна", "Ветряная пекарня", "Рыбацкая гавань", "Праздник маяка"),
        (
            "Туман рассеется: откроются лес и яблони. Придут два лесника, появится место для пекарни.",
            "Крылья мельницы закрутятся. Пекарь откроет прилавок, а жители понесут хлеб домой.",
            "У нового берега появится причал. Рыбаки выйдут на лодках, а мост соединит берега.",
            "Маяк зажжётся, прибудет корабль гостей. На площади начнётся праздник с фонариками.",
        ),
    ),
    ThemeSpec(
        "bricks", "Брик-сити", "Мир яркого конструктора", "КОНСТРУКТОР", "#df8560",
        "Детали и механизмы", "строителей",
        ("Долина деталей", "Сборочная станция", "Грузовой порт", "Башня изобретений"),
        (
            "Появятся новые строительные пластины и склад деталей. Два сборщика начнут сортировать кубики.",
            "Заработает колесо сборочной машины. Строители повезут яркие детали по дорожкам.",
            "Кран и грузовой катер свяжут площадки. Откроется новая территория для больших изобретений.",
            "Засветится башня изобретений. Жители устроят парад построенных машин и запустят фонарики.",
        ),
    ),
    ThemeSpec(
        "voxel", "Куболесье", "Кубический мир исследователей", "КУБИЧЕСКИЙ", "#648e60",
        "Кристаллы и древесина", "исследователей",
        ("Кристальная долина", "Мастерская механизмов", "Бухта исследователей", "Кристальный маяк"),
        (
            "Откроется ступенчатая долина. Исследователи найдут кристаллы и проложат новую тропинку.",
            "Запустится механизм обработки кристаллов. Мастера начнут переносить светящиеся блоки.",
            "Появятся мост и экспедиционные лодки. Исследователи отправятся к новому берегу.",
            "Кристалл осветит остров. Прибудут гости, и над кубическими домами засияют огоньки.",
        ),
    ),
    ThemeSpec(
        "helpers", "Банановый залив", "Остров весёлых непосед", "НЕПОСЕДЫ", "#c3a22d",
        "Бананы и изобретения", "непосед",
        ("Банановая роща", "Фабрика смузи", "Банановый порт", "Большой карнавал"),
        (
            "Туман откроет рощу. Жёлтые непоседы начнут собирать бананы и возить их к домикам.",
            "Завертится смешная машина смузи. Курьеры понесут напитки, а у прилавка соберутся друзья.",
            "Причал примет банановые лодки. На новом берегу появится место для карнавальной сцены.",
            "Заиграет световая башня: непоседы соберутся на карнавал. В залив войдёт корабль друзей.",
        ),
    ),
)

THEMES_BY_CODE = {t.code: t for t in THEMES}
UPGRADE_INDEX = {u.code: i for i, u in enumerate(UPGRADES)}
DEFAULT_THEME = "settlers"


def theme_summary(t: ThemeSpec) -> dict:
    return {
        "code": t.code,
        "name": t.name,
        "type": t.type,
        "badge": t.badge,
        "color": t.color,
        "resource": t.resource,
        "inhabitants_label": t.inhabitants_label,
        "upgrades_total": len(UPGRADES),
    }
