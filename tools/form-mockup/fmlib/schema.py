"""Проверка модели по JSON Schema - подмножество стандарта без внешних библиотек.

Поддержаны ключевые слова, которыми пользуется `form-model.schema.json`; схема с
другим ключевым словом не загружается (`SchemaError`), чтобы правка схемы не
проверялась молча наполовину.

Две особенности ради понятных сообщений агенту:

- `oneOf`, у всех ветвей которого есть `properties.type` с `const` или `enum`,
  разбирается по значению `type` элемента: сообщение называет вид, а не перечисляет
  несовпадения всех ветвей;
- лишнее свойство, которое есть у другого вида, - замечание `foreign-property`
  («не относится к виду»), а не просто неизвестное свойство.

Своё ключевое слово схемы - `x-platform` в корне: реестр свойств, которых нет в
платформе (`model`) или которые переносятся в 1С не напрямую (`indirect`), с
пояснением. Проверку модели оно не меняет; свойство вне реестра - свойство платформы
с тем же именем.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_KEYWORDS = {
    "$schema", "$id", "$defs", "$ref", "title", "description",
    "type", "const", "enum", "pattern", "minimum",
    "properties", "required", "additionalProperties", "unevaluatedProperties",
    "items", "allOf", "oneOf",
}

# Пометки свойств вне платформы: группа реестра `x-platform` → как назвать её человеку.
PLATFORM_GROUPS = {
    "model": "нет в 1С",
    "indirect": "в 1С не напрямую",
}

TYPE_NAMES = {
    "object": "объект",
    "array": "массив",
    "string": "строка",
    "integer": "целое число",
    "number": "число",
    "boolean": "булево",
    "null": "null",
}


class SchemaError(Exception):
    """Схема использует то, чего валидатор не умеет."""


@dataclass
class Issue:
    """Замечание проверки: код правила, путь до места в модели, текст."""

    code: str
    path: tuple
    message: str


def format_path(path) -> str:
    """Путь вида `form.items[0].items[2]`."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += ("." if text else "") + part
    return text or "(корень)"


def json_type(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def type_matches(value, expected: str) -> bool:
    actual = json_type(value)
    if expected == "number":
        return actual in ("integer", "number")
    return actual == expected


class SchemaValidator:
    """Валидатор модели по загруженной схеме."""

    def __init__(self, schema: dict):
        self.schema = schema
        self.defs = schema.get("$defs", {})
        self._check_keywords(schema, "#")
        self.def_names = {id(node): name for name, node in self.defs.items()}
        self.kinds = self._collect_kinds()
        self.owners = self._collect_owners()
        self.platform = self._load_platform()

    @classmethod
    def from_file(cls, path: Path) -> "SchemaValidator":
        with open(path, encoding="utf-8") as file:
            return cls(json.load(file))

    # Разбор схемы

    def _check_keywords(self, node, where: str):
        if not isinstance(node, dict):
            raise SchemaError(f"{where}: узел схемы не объект")
        allowed = SUPPORTED_KEYWORDS | ({"x-platform"} if where == "#" else set())
        unknown = set(node) - allowed
        if unknown:
            raise SchemaError(f"{where}: не поддержано {sorted(unknown)}")
        for name, sub in node.get("properties", {}).items():
            self._check_keywords(sub, f"{where}/properties/{name}")
        for name, sub in node.get("$defs", {}).items():
            self._check_keywords(sub, f"{where}/$defs/{name}")
        if "items" in node:
            self._check_keywords(node["items"], f"{where}/items")
        for key in ("allOf", "oneOf"):
            for index, sub in enumerate(node.get(key, [])):
                self._check_keywords(sub, f"{where}/{key}/{index}")
        if isinstance(node.get("additionalProperties"), dict):
            # Словарь «имя → значение»: схема значения, своих свойств у узла нет
            if "properties" in node:
                raise SchemaError(f"{where}/additionalProperties: схема значений - только у словаря без properties")
            self._check_keywords(node["additionalProperties"], f"{where}/additionalProperties")
        elif "additionalProperties" in node and node["additionalProperties"] is not False:
            raise SchemaError(f"{where}/additionalProperties: поддержано false или схема значений словаря")
        if "unevaluatedProperties" in node and node["unevaluatedProperties"] is not False:
            raise SchemaError(f"{where}/unevaluatedProperties: поддержано только false")

    def _load_platform(self) -> dict:
        """Реестр `x-platform`: свойство → (группа, пояснение)."""
        registry = self.schema.get("x-platform", {})
        if not isinstance(registry, dict) or set(registry) - set(PLATFORM_GROUPS):
            raise SchemaError(f"#/x-platform: ожидаются группы {sorted(PLATFORM_GROUPS)}")
        known = self.property_names()
        platform = {}
        for group, entries in registry.items():
            if not isinstance(entries, dict):
                raise SchemaError(f"#/x-platform/{group}: ожидается объект свойство → пояснение")
            for prop, text in entries.items():
                where = f"#/x-platform/{group}/{prop}"
                if prop not in known:
                    raise SchemaError(f"{where}: такого свойства в схеме нет")
                if prop in platform:
                    raise SchemaError(f"{where}: свойство уже в группе {platform[prop][0]}")
                if not isinstance(text, str) or not text.strip():
                    raise SchemaError(f"{where}: нужно пояснение строкой")
                platform[prop] = (group, text)
        return platform

    def property_names(self) -> set:
        """Все свойства модели: корня и всех определений."""
        names = set()
        for node in [self.schema, *self.defs.values()]:
            names.update(prop for prop in node.get("properties", {}) if not prop.startswith("$"))
        return names

    def platform_mark(self, prop: str) -> str:
        """Пометка свойства вне платформы для человека; пусто - свойство платформы."""
        if prop not in self.platform:
            return ""
        group, text = self.platform[prop]
        return f"{PLATFORM_GROUPS[group]}: {text}"

    def resolve(self, node: dict) -> dict:
        """Следует по `$ref` до узла без ссылки."""
        seen = set()
        while "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                raise SchemaError(f"циклическая ссылка {ref}")
            seen.add(ref)
            if not ref.startswith("#/"):
                raise SchemaError(f"внешняя ссылка не поддержана: {ref}")
            target = self.schema
            for part in ref[2:].split("/"):
                target = target[part]
            node = target
        return node

    def type_values(self, node: dict) -> list:
        """Значения `type` элемента, которые принимает узел, - пусто у неэлементов."""
        node = self.resolve(node)
        spec = node.get("properties", {}).get("type")
        if spec is None:
            return []
        spec = self.resolve(spec)
        if "const" in spec:
            return [spec["const"]]
        return list(spec.get("enum", []))

    def evaluated_properties(self, node: dict) -> set:
        """Свойства, описанные узлом и его `allOf` (для `unevaluatedProperties`)."""
        node = self.resolve(node)
        names = set(node.get("properties", {}))
        for sub in node.get("allOf", []):
            names |= self.evaluated_properties(sub)
        return names

    def _collect_kinds(self) -> set:
        kinds = set()
        for node in self.defs.values():
            kinds.update(self.type_values(node))
        return kinds

    def _collect_owners(self) -> dict:
        """Свойство → виды элементов, у которых оно есть."""
        owners = {}
        for name, node in self.defs.items():
            kinds = self.type_values(node) or ([name] if name[0].isupper() else [])
            for prop in self.evaluated_properties(node):
                if prop == "type":
                    continue
                for kind in kinds:
                    owners.setdefault(prop, set()).add(kind)
        return owners

    # Проверка

    def validate(self, instance) -> list:
        issues = []
        self._validate(instance, self.schema, (), issues, None)
        return issues

    def _validate(self, value, node, path, issues, kind):
        if "$ref" in node:
            target = self.resolve(node)
            kind = self.def_names.get(id(target), kind)
            node = target

        if "type" in node:
            expected = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(type_matches(value, item) for item in expected):
                wanted = " или ".join(TYPE_NAMES[item] for item in expected)
                got = TYPE_NAMES[json_type(value)]
                issues.append(Issue("schema", path, f"ожидается {wanted}, получено: {got}"))
                return
        if "const" in node and value != node["const"]:
            issues.append(Issue("schema", path, f"ожидается {json.dumps(node['const'], ensure_ascii=False)}"))
        if "enum" in node and value not in node["enum"]:
            allowed = ", ".join(str(item) for item in node["enum"])
            issues.append(Issue("schema", path, f"значение {value!r} не из списка: {allowed}"))
        if "pattern" in node and isinstance(value, str) and not re.search(node["pattern"], value):
            issues.append(Issue("schema", path, f"{value!r} - не имя 1С (буквы, цифры, _, не с цифры)"))
        if "minimum" in node and isinstance(value, (int, float)) and value < node["minimum"]:
            issues.append(Issue("schema", path, f"значение меньше {node['minimum']}"))

        for sub in node.get("allOf", []):
            self._validate(value, sub, path, issues, kind)
        if "oneOf" in node:
            self._validate_one_of(value, node["oneOf"], path, issues, kind)

        if isinstance(value, dict):
            self._validate_object(value, node, path, issues, kind)
        if isinstance(value, list) and "items" in node:
            for index, item in enumerate(value):
                self._validate(item, node["items"], path + (index,), issues, kind)

    def _validate_object(self, value, node, path, issues, kind):
        properties = node.get("properties", {})
        for prop, sub in properties.items():
            if prop in value:
                self._validate(value[prop], sub, path + (prop,), issues, kind)
        for prop in node.get("required", []):
            if prop not in value:
                issues.append(Issue("schema", path, f"нет обязательного свойства {prop}"))

        if isinstance(node.get("additionalProperties"), dict):
            for prop, item in value.items():
                self._validate(item, node["additionalProperties"], path + (prop,), issues, kind)
            return
        if node.get("additionalProperties") is False:
            allowed = set(properties)
        elif node.get("unevaluatedProperties") is False:
            allowed = self.evaluated_properties(node)
        else:
            return
        for prop in value:
            if prop not in allowed:
                issues.append(self._extra_property(prop, path, kind))

    def _extra_property(self, prop, path, kind) -> Issue:
        owners = self.owners.get(prop)
        if owners and kind:
            listed = ", ".join(sorted(owners))
            return Issue("foreign-property", path + (prop,),
                         f"свойство {prop} не относится к виду {kind}; оно есть у: {listed}")
        return Issue("schema", path + (prop,), f"неизвестное свойство {prop}")

    def _validate_one_of(self, value, branches, path, issues, kind):
        by_type = {}
        for branch in branches:
            values = self.type_values(branch)
            if not values:
                by_type = None
                break
            for item in values:
                by_type[item] = branch

        if by_type is None:
            matched = 0
            for branch in branches:
                probe = []
                self._validate(value, branch, path, probe, kind)
                matched += not probe
            if matched != 1:
                issues.append(Issue("schema", path, f"подходит вариантов: {matched}, нужен ровно один"))
            return

        if not isinstance(value, dict):
            issues.append(Issue("schema", path, f"ожидается элемент формы (объект), получено: {TYPE_NAMES[json_type(value)]}"))
            return
        element_type = value.get("type")
        if element_type is None:
            issues.append(Issue("schema", path, "нет свойства type - вида элемента"))
            return
        if not isinstance(element_type, str):
            got = TYPE_NAMES[json_type(element_type)]
            issues.append(Issue("schema", path + ("type",), f"вид элемента - строка, получено: {got}"))
            return
        if element_type in by_type:
            self._validate(value, by_type[element_type], path, issues, element_type)
            return
        allowed = ", ".join(sorted(by_type))
        if element_type in self.kinds:
            issues.append(Issue("schema", path, f"вид {element_type} здесь не допускается; допустимые: {allowed}"))
        else:
            issues.append(Issue("schema", path, f"неизвестный вид {element_type!r}; допустимые здесь: {allowed}"))
