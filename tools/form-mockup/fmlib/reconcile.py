"""Сверка собранной формы с макетом - команда `compare`.

Макет - модель, согласованная в ТЗ; форма - модель, импортированная из XML собранной формы. Сравнение -
`diff.compare` («макет → форма») после нормализации обеих моделей, чтобы в отличия не попадал шум:

- свойства только для ТЗ (`note`, `sample`, данные картинок, типов и стилей) не сравниваются;
- одно и то же, записанное по-разному, приводится к одному виду: `choiceList` - список представлений,
  `excludedCommands` - без учета порядка, заголовок элемента - как его видит пользователь (свой, по пути к
  данным, по команде или по имени);
- явное умолчание платформы равно отсутствию свойства (таблица `defaults` в `property-groups.json` - та
  же, что у панели свойств конструктора);
- уточнение верстальщика - свойство элемента формы, которого нет у пары в макете: в отдельный раздел, не
  в отличия;
- отметка `generated` в макете: `element` - элемент создает код или выводит платформа, его не ищут в
  форме; `title` - заголовок в макете - пример текста, его не сравнивают. Пропущенное - в раздел
  «Заполняется кодом».

Пары элементов - по имени и `renamedFrom`, как у `table --before` (`diff.match`).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import SCHEMA_PATH
from .diff import (CHILD_KEYS, MISSING, Diff, as_drawn, child_slots, compare, display_title, kind_of, match,
                   node_name, prop_label, same, value_text)
from .tables import changes_table, kind_text, row

GROUPS_PATH = SCHEMA_PATH.parent / "property-groups.json"

TZ_ONLY = ("note", "sample", "generated")              # свойства элемента только для ТЗ
MODEL_ONLY = ("pictures", "types", "styles", "commands", "attributes")   # корень: данные рисования
SET_PROPS = ("excludedCommands",)                      # списки без порядка
KEEP = set(CHILD_KEYS) | {"name", "type", "renamedFrom"}
BARS = ("AutoCommandBar", "CommandBar")
ELEMENT = "element"
TITLE = "title"


@dataclass
class Skipped:
    """Место кода: что сверка пропустила и что в форме на этом месте."""

    kind: str
    title: str
    name: str
    what: str            # element | title
    sample: str = ""     # заголовок-пример макета
    found: str = ""      # что в форме


@dataclass
class Refinement:
    """Уточнение верстальщика: свойства элемента формы, которых нет у пары в макете."""

    kind: str
    title: str
    name: str
    props: list = field(default_factory=list)


@dataclass
class Reconciliation:
    diff: Diff
    skipped: list
    refinements: list

    @property
    def changes(self) -> list:
        return self.diff.changes


def load_defaults(path: Path = GROUPS_PATH) -> dict:
    """Умолчания платформы по видам (`*` - у всех видов, у которых свойство есть)."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)["defaults"]


def default_of(defaults: dict, node: dict, prop: str):
    own = defaults.get(kind_of(node), {})
    if prop in own:
        return own[prop]
    return defaults.get("*", {}).get(prop, MISSING)


def is_default(defaults: dict, node: dict, prop: str, value) -> bool:
    default = default_of(defaults, node, prop)
    return default is not MISSING and same(default, value)


def preorder(node: dict):
    yield node
    for _, child, _ in child_slots(node):
        yield from preorder(child)


def reconcile(mockup: dict, form: dict, dictionary: dict, defaults: dict | None = None) -> Reconciliation:
    """Отличия формы от макета после нормализации, места кода и уточнения. Исходные модели не меняются."""
    defaults = load_defaults() if defaults is None else defaults
    before = prepare(mockup)
    after = prepare(form)
    marks = {id(node): node.get("generated") for node in preorder(before["form"]) if node.get("generated")}
    for model in (before, after):
        for node in preorder(model["form"]):
            for key in TZ_ONLY:
                node.pop(key, None)
            normalize(node)
    warnings = []
    pairs, _ = match(before["form"], after["form"], warnings)
    skipped = apply_marks(before["form"], after["form"], marks, pairs)
    refinements = []
    paired = set()
    for node in preorder(before["form"]):
        pair = pairs.get(id(node))
        if pair is not None:
            paired.update((id(node), id(pair)))
            refinement = align(node, pair, defaults, dictionary)
            if refinement.props:
                refinements.append(refinement)
    for model in (before, after):
        for node in preorder(model["form"]):
            if id(node) in paired:
                continue
            for key in [key for key in node if key not in KEEP and is_default(defaults, node, key, node[key])]:
                # Умолчание у элемента без пары (добавлен, удален): в подробностях правки оно - шум
                del node[key]
    diff = compare(before, after, dictionary)
    diff.warnings[:0] = warnings
    return Reconciliation(diff, skipped, refinements)


def prepare(model: dict) -> dict:
    """Копия модели, как ее видит пользователь (`as_drawn`), без данных рисования: заголовок по пути и по
    команде, картинка кнопки по команде уже в элементах - повторный `as_drawn` сравнения их не добавит."""
    drawn = copy.deepcopy(as_drawn(copy.deepcopy(model)))
    for key in MODEL_ONLY:
        drawn.pop(key, None)
    for node in preorder(drawn["form"]):
        if "type" in node and "title" not in node and node["type"] not in BARS:
            # Заголовок по имени - тоже то, что видит пользователь: свой заголовок «Срок» у поля «Срок» не отличие.
            # Командная панель без заголовка - по владельцу, как в тексте правок (`diff.parent_text`)
            node["title"] = display_title(node)
    return drawn


def normalize(node: dict):
    """Одно и то же, записанное по-разному, - к одному виду."""
    choices = node.get("choiceList")
    if isinstance(choices, list):
        node["choiceList"] = [presentation(item) for item in choices]
    for key in SET_PROPS:
        if isinstance(node.get(key), list):
            node[key] = sorted(node[key], key=lambda value: json.dumps(value, ensure_ascii=False))


def presentation(item):
    if isinstance(item, dict):
        text = item.get("presentation")
        return text if isinstance(text, str) and text else item.get("value")
    return item


def apply_marks(before_form: dict, after_form: dict, marks: dict, pairs: dict) -> list:
    """Места кода: элемент целиком убирается из обеих моделей, заголовок макета заменяется заголовком формы."""
    skipped = []
    for node in list(preorder(before_form)):
        what = marks.get(id(node))
        if what is None or not any(alive is node for alive in preorder(before_form)):
            # Без отметки или внутри элемента кода, уже убранного целиком
            continue
        pair = pairs.get(id(node))
        # Элемент - по заголовку формы: заголовок макета - пример текста, он в колонке «Пропущено»
        item = Skipped(kind_of(node), display_title(pair if pair is not None else node), node_name(node), what)
        if what == ELEMENT:
            item.found = "есть" if pair is not None else "нет"
            remove(before_form, node)
            if pair is not None:
                remove(after_form, pair)
        else:
            item.sample = node.get("title", "")
            if pair is None:
                item.found = "элемента нет"
            else:
                item.found = pair.get("title", "")
                if "title" in pair:
                    node["title"] = pair["title"]
                else:
                    node.pop("title", None)
        skipped.append(item)
    return skipped


def remove(form: dict, target: dict) -> bool:
    """Убрать узел из дерева; узла нет (уже убран вместе с родителем) - ничего."""
    for node in preorder(form):
        if node.get("commandBar") is target:
            del node["commandBar"]
            return True
        items = node.get("items")
        if isinstance(items, list) and any(item is target for item in items):
            node["items"] = [item for item in items if item is not target]
            return True
    return False


def align(before: dict, after: dict, defaults: dict, dictionary: dict) -> Refinement:
    """Пара макет - форма: умолчания в макете и форме равны отсутствию; свойство формы, которого нет в макете, -
    уточнение, убирается из формы."""
    refinement = Refinement(kind_of(after), display_title(after), node_name(after))
    for key in [key for key in after if key not in KEEP]:
        if key in before:
            if is_default(defaults, before, key, before[key]) and is_default(defaults, after, key, after[key]):
                del before[key], after[key]
            continue
        value = after.pop(key)
        if not is_default(defaults, after, key, value):
            refinement.props.append(f"{prop_label(dictionary, key)}: {value_text(dictionary, key, value)}")
    for key in [key for key in before if key not in KEEP and key not in after]:
        if is_default(defaults, before, key, before[key]):
            del before[key]
    return refinement


# Вывод

def report(result: Reconciliation, dictionary: dict) -> str:
    """Markdown: отличия (как таблица изменений `table --before`), места кода, уточнения."""
    lines = ["## Отличия", "", changes_table(result.diff, dictionary).rstrip("\n"), "",
             "## Заполняется кодом", ""]
    if result.skipped:
        lines += [row(["Элемент", "Вид", "Пропущено", "В форме"]), row(["---"] * 4)]
        for item in result.skipped:
            what = "элемент" if item.what == ELEMENT else "заголовок «" + " ".join(item.sample.split()) + "»"
            found = item.found if item.what == ELEMENT or item.found == "элемента нет" else \
                "«" + " ".join(item.found.split()) + "»"
            lines.append(row([f"{item.title} (`{item.name}`)", kind_text(dictionary, item.kind), what, found]))
    else:
        lines.append("Нет")
    lines += ["", "## Уточнения", ""]
    if result.refinements:
        lines += [row(["Элемент", "Вид", "Свойства формы"]), row(["---"] * 3)]
        for item in result.refinements:
            lines.append(row([f"{item.title} (`{item.name}`)", kind_text(dictionary, item.kind),
                              "; ".join(item.props)]))
    else:
        lines.append("Нет")
    return "\n".join(lines) + "\n"
