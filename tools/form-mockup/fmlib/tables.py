"""Таблицы для ТЗ - команда `table`.

Обе таблицы - Markdown русскими названиями: виды, свойства и значения - по словарю
`dictionary-ru.json`, английское - только имя элемента. Таблица элементов идет по дереву
модели, вложенность - отступом в колонке «Элемент»; таблица изменений - по правкам
сравнения, номер совпадает с номером на рисунке.
"""

from __future__ import annotations

from .diff import OWN_SKIP, child_slots, as_drawn, display_title, note_numbers, note_of, prop_label, value_text

INDENT = "\u00a0\u00a0"         # неразрывные пробелы: обычные Markdown схлопывает
ELEMENT_SKIP = OWN_SKIP | {"type", "title", "dataPath", "note", "enumValues"}


def cell(text) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def row(values) -> str:
    return "| " + " | ".join(cell(value) for value in values) + " |"


def kind_text(dictionary: dict, kind: str) -> str:
    return dictionary.get("types", {}).get(kind, kind)


def elements_table(model: dict, dictionary: dict) -> str:
    # Кнопка команды формы - с заголовком команды, как на рисунке
    form = as_drawn(model)["form"]
    # Номер примечания - как на снимке примечаний `render`; колонка - только когда примечания есть
    numbers = note_numbers(form)

    def number(node) -> list:
        return [numbers.get(id(node), "")] if numbers else []

    columns = (["№"] if numbers else []) + ["Элемент", "Вид", "Имя", "Путь к данным", "Свойства", "Комментарий"]
    lines = [row(columns), row(["---"] * len(columns))]
    lines.append(row(number(form) + [display_title(form), kind_text(dictionary, "Form"), "", "",
                                     props_text(form, dictionary), note_of(form)]))

    def visit(node, depth):
        for _, child, _ in child_slots(node):
            lines.append(row(number(child) + [INDENT * depth + display_title(child),
                                              kind_text(dictionary, child.get("type", "")), f"`{child.get('name', '')}`",
                                              child.get("dataPath", ""), props_text(child, dictionary), note_of(child)]))
            visit(child, depth + 1)

    visit(form, 1)
    return "\n".join(lines) + "\n"


def props_text(node: dict, dictionary: dict) -> str:
    """Свойства элемента, кроме тех, что стоят в своих колонках; пример значения - только у поля."""
    parts = []
    for key, value in node.items():
        if key in ELEMENT_SKIP or (key == "sample" and not isinstance(value, (str, bool, int, float))):
            continue
        parts.append(f"{prop_label(dictionary, key)}: {value_text(dictionary, key, value)}")
    return "; ".join(parts)


def changes_table(diff, dictionary: dict) -> str:
    lines = [row(["№", "Элемент", "Вид", "Что сделано", "Подробности"]), row(["---"] * 5)]
    for change in diff.changes:
        element = f"{change.title} (`{change.name}`)"
        lines.append(row([change.number, element, kind_text(dictionary, change.kind), change.what,
                          "; ".join(change.details)]))
    if not diff.changes:
        lines.append(row(["", "Изменений нет", "", "", ""]))
    return "\n".join(lines) + "\n"
