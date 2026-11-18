"""Словарь русских названий модели и команда `ru`.

Перевод - поиск по `dictionary-ru.json` в обе стороны, без ИИ и без сети. Полноту
словаря против схемы считает `missing_terms`; её проверяет тест.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import SchemaValidator


def load_dictionary(path: Path) -> dict:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def schema_terms(validator: SchemaValidator):
    """Виды, свойства и значения перечислений схемы: (виды, свойства, {свойство: значения})."""
    # Виды - значения `type` элементов и определения с заглавной буквы без `type` (`Form`).
    kinds = set(validator.kinds)
    kinds.update(name for name, node in validator.defs.items()
                 if name[0].isupper() and not validator.type_values(node))
    properties = set()
    values = {}

    def visit(node):
        for prop, spec in node.get("properties", {}).items():
            if prop.startswith("$"):
                continue
            properties.add(prop)
            if prop == "type":
                continue
            spec = validator.resolve(spec)
            if "enum" in spec:
                values.setdefault(prop, set()).update(spec["enum"])

    visit(validator.schema)
    for node in validator.defs.values():
        visit(node)
    return kinds, properties, values


def missing_terms(validator: SchemaValidator, dictionary: dict) -> list:
    """Чего из схемы нет в словаре - строки для отчёта теста."""
    kinds, properties, values = schema_terms(validator)
    missing = [f"вид {kind}" for kind in sorted(kinds - set(dictionary.get("types", {})))]
    missing += [f"свойство {prop}" for prop in sorted(properties - set(dictionary.get("properties", {})))]
    known_values = dictionary.get("values", {})
    for prop in sorted(values):
        for value in sorted(values[prop] - set(known_values.get(prop, {}))):
            missing.append(f"значение {prop}: {value}")
    return missing


def translate(dictionary: dict, word: str, marks=None) -> list:
    """Строки перевода слова в обе стороны; пусто - не найдено.

    Слово - вид, свойство, значение или пара `свойство=значение` на любом из языков.
    Русские названия сравниваются без учёта регистра. `marks` - свойство → пометка
    «нет в 1С» / «в 1С не напрямую» (`SchemaValidator.platform_mark`), дописывается к
    строке свойства.
    """
    if "=" in word:
        return translate_pair(dictionary, *word.split("=", 1))

    key = word.strip().casefold()
    lines = []
    for english, russian in dictionary.get("types", {}).items():
        if key in (english.casefold(), russian.casefold()):
            lines.append(f"{english} - {russian} (вид)")
    for english, russian in dictionary.get("properties", {}).items():
        if key in (english.casefold(), russian.casefold()):
            mark = marks(english) if marks else ""
            lines.append(f"{english} - {russian} (свойство{'; ' + mark if mark else ''})")

    found = {}
    for prop, mapping in dictionary.get("values", {}).items():
        for english, russian in mapping.items():
            if key in (english.casefold(), russian.casefold()):
                found.setdefault((english, russian), []).append(prop)
    for (english, russian), props in found.items():
        lines.append(f"{english} - {russian} (значение: {', '.join(props)})")
    return lines


def translate_pair(dictionary: dict, prop_word: str, value_word: str) -> list:
    """`titleLocation=None` - «Положение заголовка = Нет» и обратно."""
    prop_key = prop_word.strip().casefold()
    value_key = value_word.strip().casefold()
    lines = []
    for prop, prop_russian in dictionary.get("properties", {}).items():
        if prop_key not in (prop.casefold(), prop_russian.casefold()):
            continue
        for english, russian in dictionary.get("values", {}).get(prop, {}).items():
            if value_key in (english.casefold(), russian.casefold()):
                lines.append(f"{prop}={english} - {prop_russian} = {russian}")
    return lines
