"""Цвет для макета: значение 1С → цвет модели.

В XML формы цвет - элемент стиля (`Style.Имя`, в выгрузке `style:Имя`), web-цвет (`Web.Gainsboro`,
`web:Gainsboro`) или абсолютный (`#RRGGBB`, в EDT - красный, зеленый, синий). В модель элемент стиля
пишется именем `style:<Имя>` (стиль платформы - английским именем, как в XML), а его значение для
рисования - в словарь `styles` модели: элементы стиля конфигурации - из исходников с поправкой
основного стиля конфигурации, стиль платформы - из основного стиля или таблицы «Такси» инструмента
(`schema/colors-1c.json`). Неразрешимый элемент стиля остается именем без значения: макет без цвета.
В `styles` - только цвета, на которые ссылается форма: агент читает модель целиком.
Все цветовые элементы стиля конфигурации - для закладки «Из стиля» конструктора - отдает `config_styles`
(сервер, `serve --src`).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import ROOT

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
WEB = re.compile(r"^(?:Web\.|web:)([A-Za-z]+)$")
STYLE = re.compile(r"^(?:Style\.|style:)(.+)$")
DESIGNER_VALUE = re.compile(r"<Value[^>]*>([^<]+)</Value>")
DESIGNER_TYPE = re.compile(r"<Type>([^<]+)</Type>")
# Форматированная строка: элемент стиля конфигурации по UUID (`<colorstyle 0:UUID>`)
COLOR_STYLE = re.compile(r"<(bg)?colorstyle 0:([0-9a-fA-F-]{36})>")
ITEM_UUID = re.compile(r'<(?:mdclass:)?StyleItem\b[^>]*\buuid="([0-9a-fA-F-]{36})"')
# Цвет стиля в модели - в свойствах и в разметке форматированной строки
STYLE_NAME = re.compile(r"style:([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)")

TABLE = json.loads((ROOT / "schema" / "colors-1c.json").read_text(encoding="utf-8"))
PLATFORM = {row["name"]: row["value"] for row in TABLE["platform"]}
# Русское имя цвета стиля платформы (ЦветаСтиля.ЦветТекстаФормы) → английское, как в XML формы
PLATFORM_RU = {row["ru"]: row["name"] for row in TABLE["platform"]}
WEB_COLORS = {row["name"].lower(): row["value"] for row in TABLE["web"]}

CACHE: dict = {}


def edt_value(node):
    """Цвет из узла EDT (`backColor`, значение элемента стиля): строка 1С или `#RRGGBB`."""
    if node is None:
        return None
    color = node.findtext("color")
    if color:
        return color
    # Абсолютный цвет: EDT не пишет компонент, равный 0 (умолчание модели)
    parts = [node.findtext(tag) for tag in ("red", "green", "blue")]
    if (node.get(XSI_TYPE) or "").endswith("ColorDef") or any(part is not None for part in parts):
        try:
            return "#{:02X}{:02X}{:02X}".format(*(int(part or 0) for part in parts))
        except ValueError:
            return None
    inner = node.find("value")
    if inner is not None:
        return edt_value(inner)
    return (node.text or "").strip() or None


def resolve(value):
    """Значение цвета 1С → цвет модели: `#RRGGBB`, имя web-цвета или `style:<Имя>`; None - не цвет."""
    if not value:
        return None
    value = value.strip()
    if HEX.match(value):
        return value.upper()
    found = WEB.match(value)
    if found:
        return found.group(1).lower()
    found = STYLE.match(value)
    if found and STYLE_NAME.fullmatch("style:" + found.group(1)):
        return "style:" + PLATFORM_RU.get(found.group(1), found.group(1))
    return None


def hex_of(value):
    """Цвет модели без стиля → `#RRGGBB` (значение `styles`); web-цвет - по таблице 1С."""
    if not value:
        return None
    if HEX.match(value):
        return value.upper()
    return WEB_COLORS.get(value.lower())


def used_styles(node, found: set) -> set:
    """Имена элементов стиля, на которые ссылается модель: свойства-цвета и разметка заголовков."""
    if isinstance(node, dict):
        for value in node.values():
            used_styles(value, found)
    elif isinstance(node, list):
        for value in node:
            used_styles(value, found)
    elif isinstance(node, str) and "style:" in node:
        found.update(STYLE_NAME.findall(node))
    return found


def styles(src: Path | None, edt: bool, used: set) -> dict:
    """Словарь `styles` модели: значения цветов стиля, использованных формой, - конфигурации и платформы. Без
    исходников - только стиль платформы по таблице «Такси»."""
    table = Styles.of(src, edt) if src else None
    result = {}
    for name in sorted(used):
        value = table.value(name) if table else PLATFORM.get(name)
        if value:
            result[name] = value
    return result


def config_styles(src: Path, edt: bool) -> list:
    """Цветовые элементы стиля конфигурации со значением (с поправкой основного стиля): `[{name, value}]` по имени -
    вторая часть закладки «Из стиля» конструктора (`GET /config-styles`)."""
    table = Styles.of(src, edt)
    result = []
    for name in sorted(table.items):
        value = table.value(name)
        if value:
            result.append({"name": name, "value": value})
    return result


class Styles:
    """Элементы стиля конфигурации и основной стиль: одно чтение на конфигурацию."""

    @classmethod
    def of(cls, src: Path, edt: bool):
        key = (src, edt)
        if key not in CACHE:
            CACHE[key] = cls(src, edt)
        return CACHE[key]

    def __init__(self, src: Path, edt: bool):
        self.src = src
        self.edt = edt
        self.items = {}       # имя цветового элемента стиля конфигурации → значение 1С
        self.uuids = {}       # UUID элемента стиля → имя (форматированные строки)
        self.main = {}        # основной стиль: имя (`StyleItem.Имя` - элемент конфигурации) → значение 1С
        self.read_items()
        self.read_main()

    def read_items(self):
        folder = self.src / "StyleItems"
        paths = folder.glob("*/*.mdo") if self.edt else folder.glob("*.xml")
        for path in sorted(paths) if folder.is_dir() else []:
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            found = ITEM_UUID.search(text)
            if found:
                self.uuids[found.group(1).lower()] = path.stem
            if self.edt:
                try:
                    value = ET.fromstring(text).find("value")
                except ET.ParseError:
                    continue
                if value is not None and (value.get(XSI_TYPE) or "").endswith("ColorValue"):
                    self.items[path.stem] = edt_value(value)
            else:
                kind = DESIGNER_TYPE.search(text)
                value = DESIGNER_VALUE.search(text)
                if kind and kind.group(1) == "Color" and value:
                    self.items[path.stem] = value.group(1)

    def read_main(self):
        config = self.src / "Configuration" / "Configuration.mdo" if self.edt else self.src / "Configuration.xml"
        try:
            text = config.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return
        found = re.search(r"<(?:defaultStyle|DefaultStyle)>Style\.([^<]+)<", text)
        if not found:
            return
        path = self.src / "Styles" / found.group(1) / ("Style.style" if self.edt else "Ext/Style.xml")
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return
        for item in root:
            tag = item.tag.rsplit("}", 1)[-1]
            if self.edt and tag == "items" and (item.get(XSI_TYPE) or "").endswith("ColorStyleItem"):
                self.main[item.findtext("name") or ""] = edt_value(item.find("color"))
            elif not self.edt and tag == "Item":
                color = next((child for child in item if child.tag.rsplit("}", 1)[-1] == "Color"), None)
                if color is not None and color.text:
                    self.main[item.get("name") or ""] = color.text.strip()

    def value(self, name: str, depth: int = 0):
        """`#RRGGBB` элемента стиля (конфигурации или платформы) или None."""
        if depth > 4:
            return None
        raw = self.main.get(name if name in PLATFORM else "StyleItem." + name)
        # Основной стиль ссылается на сам элемент («стиль: Гиперссылка») - значение элемента
        if raw is not None and resolve(raw) == "style:" + name:
            raw = None
        if raw is None:
            raw = self.items.get(name)
        if raw is None:
            return PLATFORM.get(name)
        color = resolve(raw)
        if color and color.startswith("style:"):
            return self.value(color[6:], depth + 1)
        return hex_of(color)


def formatted(text: str, src: Path | None, edt: bool) -> str:
    """Форматированная строка: `<colorstyle 0:UUID>` элемента стиля конфигурации → `<color style:Имя>`;
    стиль платформы (`<colorstyle -N>`) и неразрешимое остаются как есть - рендерер рисует без цвета."""
    if not src or "colorstyle 0:" not in text:
        return text
    names = Styles.of(src, edt).uuids

    def replace(found):
        name = names.get(found.group(2).lower())
        return f"<{found.group(1) or ''}color style:{name}>" if name else found.group(0)
    return COLOR_STYLE.sub(replace, text)
