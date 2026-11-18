"""Сравнение двух версий модели формы.

Элементы сопоставляются по `name`; `renamedFrom` в новой версии связывает элемент с прежним
именем. Итог - правки и объединенное дерево для режима «Правки» страницы: новая форма, в
которую на старые места вставлены удаленные элементы и тени перенесенных.

Правка - корень изменившегося поддерева: у добавленной группы своя правка, ее элементы - в
составе правки, а не отдельными; так же у удаленной. Перенос - другой родитель или другое
место среди соседей; место считается по наибольшей цепочке соседей, сохранивших порядок,
поэтому вставка элемента не делает перенесенными всех, кто стоит после него.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import re

from .attributes import Paths, path_title
from .importer import FORM_TITLES, STANDARD_COMMANDS
from .metadata import split_name

FORM_NAME = "Форма"            # имя корня на странице (`data-name` окна формы)
GHOST_SUFFIX = " (было)"       # тень перенесенного элемента на старом месте
CHILD_KEYS = ("commandBar", "items")
OWN_SKIP = {"items", "commandBar", "name", "renamedFrom"}
OPS = ("added", "removed", "moved", "changed")
OP_TEXT = {"added": "добавлен", "removed": "удален", "moved": "перенесен", "changed": "изменен"}
MISSING = object()
COMMAND_FACE = ("title", "picture", "representation")   # кнопка команды формы без своих берет их у команды
SHORT = 60


@dataclass
class Change:
    """Правка элемента: виды правки, имена в обеих версиях, подробности по-русски."""

    ops: list
    kind: str
    title: str
    after: str = None
    before: str = None
    details: list = field(default_factory=list)
    number: int = 0
    ghost: str = None
    # Измененные свойства как в модели, с прежним значением (нет `before` - свойства не было): «вернуть как было»
    # конструктора; заголовок по пути и по команде сюда не входят - их в модели нет
    props: list = field(default_factory=list)

    @property
    def op(self) -> str:
        return min(self.ops, key=OPS.index)

    @property
    def what(self) -> str:
        text = ", ".join(OP_TEXT[op] for op in sorted(self.ops, key=OPS.index))
        return text[:1].upper() + text[1:]

    @property
    def name(self) -> str:
        return self.before if self.op == "removed" else self.after

    def as_data(self) -> dict:
        """Правка для страницы: номер, вид правки, имена по режимам, текст списка."""
        return {"n": self.number, "op": self.op, "what": self.what, "kind": self.kind, "title": self.title,
                "after": self.after, "before": self.before, "ghost": self.ghost, "details": self.details,
                "props": self.props}


@dataclass
class Diff:
    changes: list
    tree: dict
    warnings: list


@dataclass
class Place:
    parent: dict      # None у корня
    slot: str         # commandBar | items
    index: int


def places(form: dict) -> dict:
    """id(узла) → место в дереве; корень - форма."""
    result = {id(form): Place(None, "", 0)}

    def visit(node):
        for slot, child, index in child_slots(node):
            result[id(child)] = Place(node, slot, index)
            visit(child)

    visit(form)
    return result


def child_slots(node: dict):
    bar = node.get("commandBar")
    if isinstance(bar, dict):
        yield "commandBar", bar, 0
    items = node.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, dict):
                yield "items", item, index


def preorder(node: dict):
    yield node
    for _, child, _ in child_slots(node):
        yield from preorder(child)


def same(left, right) -> bool:
    # Сравнение по JSON: в Python True == 1, а в модели это разные значения
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(right, ensure_ascii=False, sort_keys=True)


def display_title(node: dict) -> str:
    """Заголовок элемента, как его видит пользователь: свой или имя по словам."""
    title = node.get("title")
    if isinstance(title, str) and title.strip():
        return " ".join(title.split())
    if "type" not in node:
        return FORM_NAME
    # Командная панель без заголовка - по виду: имя «ТоварыКоманднаяПанель» по словам читается хуже
    if node.get("type") in ("AutoCommandBar", "CommandBar"):
        return "Командная панель"
    return split_name(node.get("name", ""))


def node_name(node: dict) -> str:
    return node.get("name", FORM_NAME) if "type" in node else FORM_NAME


def kind_of(node: dict) -> str:
    return node.get("type", "Form")


STANDARD_COMMAND = re.compile(r"^Form\.(Item\.[^.]+\.)?StandardCommand\.(\w+)$")
OWN_COMMAND = re.compile(r"^(?:Form\.Command|CommonCommand)\.(.+)$")


def command_title(name: str):
    """Заголовок кнопки по команде без заголовка в `commands`, как `commandTitle` рендерера:
    стандартная команда - заголовок платформы (у формы объекта - свой), команда формы и общая - имя по словам."""
    found = STANDARD_COMMAND.match(name)
    if found:
        command = found.group(2)
        return (not found.group(1) and FORM_TITLES.get(command)) or STANDARD_COMMANDS.get(command, command)
    found = OWN_COMMAND.match(name)
    return split_name(found.group(1)) if found else None


def as_drawn(model: dict) -> dict:
    """Модель, как ее видит пользователь на рисунке: кнопка команды формы (`Form.Command.<Имя>`) без своих
    заголовка, картинки и отображения несет их от команды из `commands`, кнопка прочей команды - заголовок по команде
    (`command_title`); элемент с путем к данным без своего
    заголовка - заголовок по пути (`path_title`). Правки и таблицы видят элементы, как на рисунке. Исходная не
    меняется."""
    commands = {item["name"]: item for item in model.get("commands") or []
                if isinstance(item, dict) and isinstance(item.get("name"), str)}
    if not isinstance(model.get("form"), dict):
        return model
    paths = Paths(model.get("attributes"), model.get("types"))

    def fill(node: dict) -> dict:
        result = dict(node)
        path = result.get("dataPath")
        if "title" not in result and isinstance(path, str) and path:
            result["title"] = path_title(paths, path)
        name = result.get("commandName")
        if result.get("type") == "Button" and isinstance(name, str) and name.startswith("Form.Command."):
            command = commands.get(name[len("Form.Command."):], {})
            for key in COMMAND_FACE:
                # Отображение «Авто» у кнопки - отображение команды
                if key in command and (key not in result or key == "representation" and result[key] == "Auto"):
                    result[key] = command[key]
        if result.get("type") == "Button" and isinstance(name, str) and "title" not in result:
            title = command_title(name)
            if title is not None:
                result["title"] = title
        if isinstance(result.get("commandBar"), dict):
            result["commandBar"] = fill(result["commandBar"])
        if isinstance(result.get("items"), list):
            result["items"] = [fill(item) if isinstance(item, dict) else item for item in result["items"]]
        return result

    return dict(model, form=fill(model["form"]))


def compare(before_model: dict, after_model: dict, dictionary: dict) -> Diff:
    raw_before, raw_after = by_name(before_model.get("form")), by_name(after_model.get("form"))
    before_model, after_model = as_drawn(before_model), as_drawn(after_model)
    before_form = before_model["form"]
    after_form = after_model["form"]
    warnings = []
    pairs, back = match(before_form, after_form, warnings)
    before_places = places(before_form)
    after_places = places(after_form)
    moved = moved_nodes(after_form, before_places, pairs, back)

    changes = []
    for node in preorder(after_form):
        old = back.get(id(node))
        place = after_places[id(node)]
        if old is None:
            parent = place.parent
            # Элементы добавленной группы - в составе ее правки
            if parent is not None and id(parent) not in back:
                continue
            change = Change(["added"], kind_of(node), display_title(node), after=node_name(node))
            change.details.append("место: " + place_text(node, after_places))
            change.details += content_text(node)
            change.details += own_props(node, dictionary)
        else:
            ops = []
            details = []
            if id(node) in moved:
                ops.append("moved")
                details.append(move_text(node, old, after_places, before_places, back))
            props = prop_changes(old, node, dictionary)
            if props:
                ops.append("changed")
                details += props
            if not ops:
                continue
            change = Change(ops, kind_of(node), display_title(node), after=node_name(node),
                            before=node_name(old), details=details)
            if "changed" in ops and node_name(old) in raw_before and node_name(node) in raw_after:
                change.props = raw_props(raw_before[node_name(old)], raw_after[node_name(node)])
            if "moved" in ops:
                change.ghost = node_name(old) + GHOST_SUFFIX
        if note_of(node):
            change.details.append("комментарий: " + note_of(node))
        changes.append(change)

    for node in preorder(before_form):
        if id(node) in pairs:
            continue
        parent = before_places[id(node)].parent
        if parent is not None and id(parent) not in pairs:
            continue
        change = Change(["removed"], kind_of(node), display_title(node), before=node_name(node))
        change.details.append("место: " + place_text(node, before_places))
        change.details += content_text(node)
        changes.append(change)

    tree = Merger(pairs, back, moved).build(after_form)
    number(tree, changes)
    changes.sort(key=lambda change: change.number)
    return Diff(changes, tree, warnings)


def match(before_form: dict, after_form: dict, warnings: list):
    """Пары узлов: id(узла «было») → узел «стало» и обратно. Сначала `renamedFrom`, затем имя."""
    before_by_name = {}
    for node in preorder(before_form):
        if node is not before_form and isinstance(node.get("name"), str):
            before_by_name[node["name"]] = node
    pairs = {id(before_form): after_form}
    back = {id(after_form): before_form}
    claimed = set()
    after_nodes = [node for node in preorder(after_form) if node is not after_form]

    def pair(old, new):
        pairs[id(old)] = new
        back[id(new)] = old
        claimed.add(old["name"])

    for node in after_nodes:
        old_name = node.get("renamedFrom")
        if not isinstance(old_name, str):
            continue
        if old_name not in before_by_name:
            warnings.append(f"{node.get('name')}: renamedFrom {old_name} - в прежней версии нет элемента {old_name}")
        elif old_name in claimed:
            warnings.append(f"{node.get('name')}: renamedFrom {old_name} - элемент {old_name} уже сопоставлен")
        else:
            pair(before_by_name[old_name], node)
    for node in after_nodes:
        name = node.get("name")
        if id(node) in back or name not in before_by_name or name in claimed:
            continue
        pair(before_by_name[name], node)
    return pairs, back


def moved_nodes(after_form: dict, before_places: dict, pairs: dict, back: dict) -> set:
    """id узлов «стало», перенесенных в другого родителя или на другое место среди соседей."""
    moved = set()
    for parent in preorder(after_form):
        old_parent = back.get(id(parent))
        for slot in CHILD_KEYS:
            kept = []
            for child_slot, child, _ in child_slots(parent):
                if child_slot != slot or id(child) not in back:
                    continue
                old_place = before_places[id(back[id(child)])]
                if old_parent is None or old_place.parent is not old_parent or old_place.slot != slot:
                    moved.add(id(child))
                else:
                    kept.append((old_place.index, child))
            stay = longest_increasing([index for index, _ in kept])
            for position, (_, child) in enumerate(kept):
                if position not in stay:
                    moved.add(id(child))
    return moved


def longest_increasing(values: list) -> set:
    """Позиции наибольшей возрастающей подпоследовательности; при равной длине - левее."""
    if not values:
        return set()
    length = [1] * len(values)
    previous = [-1] * len(values)
    for right in range(len(values)):
        for left in range(right):
            if values[left] < values[right] and length[left] + 1 > length[right]:
                length[right] = length[left] + 1
                previous[right] = left
    position = max(range(len(values)), key=lambda index: (length[index], -index))
    result = set()
    while position >= 0:
        result.add(position)
        position = previous[position]
    return result


class Merger:
    """Объединенное дерево: «стало» с удаленными и тенями перенесенных на старых местах."""

    def __init__(self, pairs: dict, back: dict, moved: set):
        self.pairs = pairs
        self.back = back
        self.moved = moved

    def build(self, node: dict) -> dict:
        old = self.back.get(id(node))
        result = {key: value for key, value in node.items() if key not in CHILD_KEYS}
        bar = node.get("commandBar")
        old_bar = old.get("commandBar") if old else None
        if isinstance(bar, dict):
            result["commandBar"] = self.build(bar)
        elif isinstance(old_bar, dict):
            result["commandBar"] = self.ghost(old_bar) if id(old_bar) in self.pairs else self.removed(old_bar)
        old_items = [item for item in (old.get("items") or []) if isinstance(item, dict)] if old else []
        if isinstance(node.get("items"), list) or old_items:
            entries = [(self.build(item), self.back.get(id(item))) for item in node.get("items") or []
                       if isinstance(item, dict)]
            anchor = -1
            for item in old_items:
                new = self.pairs.get(id(item))
                if new is not None and id(new) not in self.moved:
                    # Остался на месте - он и есть опора для следующих вставок
                    anchor = next(index for index, (_, origin) in enumerate(entries) if origin is item)
                    continue
                inserted = self.ghost(item) if new is not None else self.removed(item)
                anchor += 1
                entries.insert(anchor, (inserted, item))
            result["items"] = [entry for entry, _ in entries]
        return result

    def removed(self, node: dict) -> dict:
        """Удаленный элемент на старом месте; перенесенные из него - тенями."""
        result = {key: value for key, value in node.items() if key not in CHILD_KEYS}
        for slot, child, _ in child_slots(node):
            copy = self.ghost(child) if id(child) in self.pairs else self.removed(child)
            if slot == "commandBar":
                result["commandBar"] = copy
            else:
                result.setdefault("items", []).append(copy)
        if isinstance(node.get("items"), list):
            result.setdefault("items", [])
        return result

    def ghost(self, node: dict) -> dict:
        """Тень: прежний вид поддерева, имена с пометкой - не совпадают с именами формы."""
        result = {key: value for key, value in node.items() if key not in CHILD_KEYS}
        if isinstance(result.get("name"), str):
            # Заголовок по имени - прежний: пометка в имени на рисунок не выходит
            if "title" not in result and "type" in result:
                result["title"] = split_name(result["name"])
            result["name"] = result["name"] + GHOST_SUFFIX
        result.pop("renamedFrom", None)
        for slot, child, _ in child_slots(node):
            if slot == "commandBar":
                result["commandBar"] = self.ghost(child)
            else:
                result.setdefault("items", []).append(self.ghost(child))
        if isinstance(node.get("items"), list):
            result.setdefault("items", [])
        return result


def number(tree: dict, changes: list):
    """Номера правок - по порядку элементов объединенного дерева сверху вниз."""
    by_name = {}
    for change in changes:
        by_name[change.name] = change
    counter = 0
    for node in preorder(tree):
        change = by_name.get(node_name(node))
        if change and not change.number:
            counter += 1
            change.number = counter
    for change in changes:
        if not change.number:
            counter += 1
            change.number = counter


# Текст правок

def prop_label(dictionary: dict, prop: str) -> str:
    return dictionary.get("properties", {}).get(prop, prop)


def value_text(dictionary: dict, prop: str, value) -> str:
    if value is MISSING:
        return "не задано"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        russian = dictionary.get("values", {}).get(prop, {}).get(value)
        if russian:
            return russian
        return "«" + shorten(" ".join(value.split())) + "»"
    return shorten(json.dumps(value, ensure_ascii=False))


def shorten(text: str) -> str:
    return text if len(text) <= SHORT else text[:SHORT - 1] + "…"


def prop_changes(old: dict, new: dict, dictionary: dict) -> list:
    lines = []
    if node_name(old) != node_name(new):
        lines.append(f"{prop_label(dictionary, 'name')}: {node_name(old)} → {node_name(new)}")
    keys = [key for key in new if key not in OWN_SKIP] + [key for key in old if key not in OWN_SKIP and key not in new]
    for key in keys:
        before = old.get(key, MISSING)
        after = new.get(key, MISSING)
        if before is not MISSING and after is not MISSING and same(before, after):
            continue
        lines.append(f"{prop_label(dictionary, key)}: {value_text(dictionary, key, before)} → "
                     f"{value_text(dictionary, key, after)}")
    return lines


def by_name(form: dict) -> dict:
    """Узлы модели как есть по имени (корень - «Форма»): имена уникальны, иначе модель блокирована `check`."""
    return {node_name(node): node for node in preorder(form)} if isinstance(form, dict) else {}


def raw_props(old: dict, new: dict) -> list:
    """Свойства, различающиеся в модели: `{prop, before}`, без `before` - в «было» свойства не было."""
    result = []
    if node_name(old) != node_name(new):
        result.append({"prop": "name", "before": node_name(old)})
    keys = [key for key in new if key not in OWN_SKIP] + [key for key in old if key not in OWN_SKIP and key not in new]
    for key in keys:
        before = old.get(key, MISSING)
        after = new.get(key, MISSING)
        if before is not MISSING and after is not MISSING and same(before, after):
            continue
        result.append({"prop": key} if before is MISSING else {"prop": key, "before": before})
    return result


def own_props(node: dict, dictionary: dict) -> list:
    """Свойства добавленного элемента, кроме заголовка, имени и вида: из них видно, что он такое."""
    skip = OWN_SKIP | {"type", "title", "note", "sample"}
    return [f"{prop_label(dictionary, key)}: {value_text(dictionary, key, value)}"
            for key, value in node.items() if key not in skip]


def content_text(node: dict) -> list:
    names = ["«" + display_title(child) + "»" for _, child, _ in child_slots(node)]
    if not names:
        return []
    shown = names[:10]
    more = f" и еще {len(names) - 10}" if len(names) > 10 else ""
    return ["состав: " + ", ".join(shown) + more]


def note_of(node: dict) -> str:
    note = node.get("note")
    return " ".join(note.split()) if isinstance(note, str) else ""


def note_numbers(form: dict) -> dict:
    """Номера примечаний: id узла → номер. Элементы с `note` порядком обхода дерева - форма, ее
    командная панель, элементы; так же нумерует рендерер (`noteMarks`): номер на макете и в таблице один."""
    numbers = {}
    for node in preorder(form):
        if note_of(node):
            numbers[id(node)] = len(numbers) + 1
    return numbers


def parent_text(place: Place, all_places: dict) -> str:
    """Родитель по-русски: форма, группа по заголовку, командная панель - по владельцу."""
    parent = place.parent
    if parent is None or "type" not in parent:
        return "форма"
    if place.slot == "commandBar":
        return bar_text(parent)
    # Командная панель среди элементов - самостоятельный элемент: по имени («Командная панель» - заголовок
    # группы вокруг нее в БП, по нему ее не найти)
    if parent.get("type") == "CommandBar" and not display_own_title(parent):
        return "командная панель " + parent.get("name", "")
    if parent.get("type") == "AutoCommandBar" and not display_own_title(parent):
        owner = all_places[id(parent)].parent
        if owner is None or "type" not in owner:
            return "командная панель формы"
        return bar_text(owner)
    return "«" + display_title(parent) + "»"


def bar_text(owner: dict) -> str:
    return "командная панель «" + display_title(owner) + "»" if "type" in owner else "командная панель формы"


def display_own_title(node: dict) -> bool:
    title = node.get("title")
    return isinstance(title, str) and bool(title.strip())


def place_text(node: dict, all_places: dict) -> str:
    """Где элемент: родитель и сосед перед ним."""
    place = all_places[id(node)]
    where = parent_text(place, all_places)
    if place.slot == "commandBar":
        return where
    siblings = [item for item in place.parent.get("items") or [] if isinstance(item, dict)]
    position = next(index for index, item in enumerate(siblings) if item is node)
    if position == 0:
        return f"{where}, в начале"
    return f"{where}, после «{display_title(siblings[position - 1])}»"


def move_text(node: dict, old: dict, after_places: dict, before_places: dict, back: dict) -> str:
    new_place = after_places[id(node)]
    old_place = before_places[id(old)]
    same_parent = back.get(id(new_place.parent)) is old_place.parent and new_place.slot == old_place.slot
    if same_parent:
        return "новое место: " + place_text(node, after_places)
    return "из " + parent_text(old_place, before_places) + " в " + place_text(node, after_places)
