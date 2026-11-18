"""Загрузка модели формы и проверка `check`.

Проверка - схема плюс правила, которые схема не выражает. Правила обходят дерево
терпимо: модель с нарушениями схемы проверяется до конца, чтобы агент получил все
замечания за один прогон.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .attributes import Paths
from .colors import STYLE_NAME
from .schema import Issue, SchemaValidator, format_path

# Замечания, с которыми модель не рисуется (`render`) и не пишется (конструктор): нарушение схемы
# и повтор имени (по имени страница ищет закладки и свернутые группы, сравнение версий - элементы)
BLOCKING_CODES = {"schema", "foreign-property", "duplicate-name"}

MARKUP_STYLE = re.compile(r"<(?:bg)?color\s+" + STYLE_NAME.pattern + ">")

MAX_VISIBLE_ITEMS = 25
MAX_GROUP_DEPTH = 4

# Виды, которые считаются в правиле «больше 25 видимых элементов»: то, что пользователь
# видит отдельным элементом. Группы, закладки и командные панели - разметка, колонки
# таблицы - часть таблицы.
CONTAINERS = {"UsualGroup", "Pages", "Page", "CommandBar", "AutoCommandBar", "ButtonGroup", "ColumnGroup"}

EMPTY_MESSAGES = {
    "UsualGroup": "пустая группа",
    "Pages": "панель закладок без закладок",
    "Page": "пустая закладка",
    "ColumnGroup": "пустая группа колонок",
    "ButtonGroup": "пустая группа кнопок",
    "Popup": "пустое подменю",
}


class ModelLoadError(Exception):
    """Файл не прочитан или не JSON - код возврата 2."""


def load_model(path: Path):
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise ModelLoadError(f"файл не найден: {path}")
    except json.JSONDecodeError as error:
        raise ModelLoadError(f"{path}: не JSON - {error.msg}, строка {error.lineno}, позиция {error.colno}")
    except UnicodeDecodeError:
        raise ModelLoadError(f"{path}: не текст в UTF-8")


def children(node: dict, path: tuple):
    """Дочерние узлы элемента: командная панель и `items`."""
    bar = node.get("commandBar")
    if isinstance(bar, dict):
        yield bar, path + ("commandBar",)
    items = node.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, dict):
                yield item, path + ("items", index)


def walk(node: dict, path: tuple, ancestors: tuple = ()):
    """Все элементы поддерева: (элемент, путь, предки от корня)."""
    for child, child_path in children(node, path):
        yield child, child_path, ancestors
        yield from walk(child, child_path, ancestors + (child,))


def name_chain(model, path) -> str:
    """Имена элементов по пути: `ГруппаШапка/Контрагент`."""
    names = []
    node = model
    for part in path:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and isinstance(node.get("name"), str):
            names.append(node["name"])
    return "/".join(names)


def check(model, validator: SchemaValidator) -> list:
    issues = validator.validate(model)
    form = model.get("form") if isinstance(model, dict) else None
    if not isinstance(form, dict):
        return issues
    root = ("form",)
    issues += check_names(form, root)
    issues += check_containers(form, root)
    issues += check_visible_count(form, root)
    issues += check_group_depth(form, root)
    issues += check_data_paths(model, form, root)
    issues += check_style_colors(model, form, root)
    return issues


def check_style_colors(model: dict, form: dict, root: tuple) -> list:
    """Цвет стиля без значения в `styles`: макет рисует элемент без цвета, не блокирует."""
    styles = model.get("styles")
    styles = styles if isinstance(styles, dict) else {}
    issues = []
    for node, path, _ in walk(form, root):
        for key, value in node.items():
            if not isinstance(value, str) or "style:" not in value:
                continue
            # Свойство-цвет целиком или разметка форматированного заголовка (`<color style:Имя>`)
            names = [value[6:]] if value.startswith("style:") else \
                MARKUP_STYLE.findall(value) if key == "title" and node.get("formatted") else []
            missing = [name for name in names if name not in styles]
            for name in dict.fromkeys(missing):
                issues.append(Issue("style-color", path + (key,),
                                    f"цвет стиля {name} без значения в styles: элемент рисуется без цвета"))
    return issues


def check_names(form: dict, root: tuple) -> list:
    issues = []
    seen = {}
    for node, path, _ in walk(form, root):
        name = node.get("name")
        if not isinstance(name, str):
            continue
        if name in seen:
            issues.append(Issue("duplicate-name", path, f"имя {name} уже занято: {seen[name]}"))
        else:
            seen[name] = format_path(path)
    return issues


def check_containers(form: dict, root: tuple) -> list:
    issues = []
    for node, path, _ in walk(form, root):
        kind = kind_of(node)
        items = node.get("items") if isinstance(node.get("items"), list) else []
        if kind in EMPTY_MESSAGES and not items:
            issues.append(Issue("empty-container", path, EMPTY_MESSAGES[kind]))
        if kind == "Pages" and len(items) == 1:
            issues.append(Issue("single-page", path, "одна закладка в панели - закладки не нужны, содержимое - в группу"))
        if kind == "Table" and not items:
            issues.append(Issue("table-no-columns", path, "таблица без колонок"))
        if kind == "Pages" and "currentPage" in node:
            pages = [item.get("name") for item in items if isinstance(item, dict)]
            if node["currentPage"] not in pages:
                issues.append(Issue("current-page", path + ("currentPage",),
                                    f"закладки {node['currentPage']} нет в панели; есть: {', '.join(map(str, pages))}"))
    return issues


def check_visible_count(form: dict, root: tuple) -> list:
    """Видимые элементы по экранам: форма вне закладок и каждая закладка отдельно."""
    issues = []
    regions = [(form, root, "в форме вне закладок")]
    for node, path, ancestors in walk(form, root):
        if node.get("type") == "Page" and visible(node, ancestors):
            regions.append((node, path, f"на закладке {node.get('name')}"))
    for node, path, where in regions:
        count = count_visible(node, path)
        if count > MAX_VISIBLE_ITEMS:
            issues.append(Issue("too-many-items", path,
                                f"{count} видимых элементов {where} при пределе {MAX_VISIBLE_ITEMS} - разбить на закладки или свернуть группы"))
    return issues


def count_visible(node: dict, path: tuple) -> int:
    count = 0
    for child, child_path in children(node, path):
        if child.get("visible") is False or child.get("userVisible") is False or child_path[-1] == "commandBar":
            continue
        kind = kind_of(child)
        if kind == "Pages":
            continue
        if kind in CONTAINERS:
            count += count_visible(child, child_path)
        else:
            count += 1
    return count


def check_group_depth(form: dict, root: tuple) -> list:
    issues = []
    for node, path, ancestors in walk(form, root):
        if node.get("type") != "UsualGroup":
            continue
        depth = 1 + sum(1 for item in ancestors if item.get("type") == "UsualGroup")
        if depth == MAX_GROUP_DEPTH + 1:
            issues.append(Issue("group-depth", path,
                                f"вложенность групп {depth} при пределе {MAX_GROUP_DEPTH} - упростить раскладку"))
    return issues


def check_data_paths(model: dict, form: dict, root: tuple) -> list:
    """Пути к данным по реквизитам формы: только при заданных `attributes`, не блокирует.

    Колонка - только внутри пути своей таблицы: другой путь EDT не принимает (опыт в EDT).
    """
    attributes = model.get("attributes")
    if not isinstance(attributes, list):
        return []
    paths = Paths(attributes, model.get("types"))
    issues = []
    for node, path, ancestors in walk(form, root):
        data_path = node.get("dataPath")
        if not isinstance(data_path, str) or not data_path or data_path.startswith("Items."):
            continue
        table = next((item for item in reversed(ancestors) if item.get("type") == "Table"), None)
        table_path = table.get("dataPath") if table is not None else None
        if node is not table and isinstance(table_path, str) and table_path and not table_path.startswith("Items.") \
                and not data_path.startswith(table_path + "."):
            issues.append(Issue("data-path", path + ("dataPath",),
                                f"колонка таблицы {table.get('name')} с путем вне ее пути {table_path}"))
            continue
        _, problem = paths.walk(data_path)
        if problem:
            issues.append(Issue("data-path", path + ("dataPath",), problem))
    return issues


def kind_of(node: dict):
    """Вид элемента; не строка (нарушение схемы) - None, чтобы правила не падали."""
    kind = node.get("type")
    return kind if isinstance(kind, str) else None


def visible(node: dict, ancestors: tuple) -> bool:
    return all(item.get("visible") is not False and item.get("userVisible") is not False for item in ancestors + (node,))
