"""Реквизиты формы и состав типов в модели.

`attributes` модели - реквизиты формы: имя, тип (`valueType`), заголовок, признак основного, у коллекции -
колонки, у динамического списка - основная таблица. `types` - состав объектных и ссылочных типов
(`Catalog.Контрагенты` → реквизиты и табличные части): тип описан один раз, дерево пути к данным раскрывает
его в каждом месте, где он встречается.

Путь к данным проходится по сегментам (`Paths`): реквизит формы → колонка коллекции или реквизит и табличная
часть типа → дальше по ссылке. Опыт в EDT: глубина по ссылке не ограничена ни вне таблицы, ни в
колонке, ни в колонке динамического списка; колонка - только внутри пути своей таблицы. Поэтому проход
останавливается только там, где состав неизвестен (тип не описан, запрос динамического списка, стандартный
реквизит платформы с английским именем) - такой путь не считается ошибкой.
"""

from __future__ import annotations

import re

from .metadata import REF_KINDS, STANDARD, STANDARD_RU, Attribute, MetaObject, parse_type, split_name

PREFIX = re.compile(r"^(cfg|v8|v8ui|xs|dcsset|dcssch|dcscor|mxl|fd|d\d+p\d+):")
# Типы выгрузки конфигуратора → имена, как в EDT
DESIGNER_TYPES = {
    "xs:string": "String", "xs:decimal": "Number", "xs:dateTime": "Date", "xs:boolean": "Boolean",
    "v8:ValueListType": "ValueList", "v8:ValueTable": "ValueTable", "v8:ValueTree": "ValueTree",
    "cfg:DynamicList": "DynamicList", "v8:UUID": "UUID", "v8:Null": "Null",
}
# XML-имя типа выгрузки, отличное от имени платформы (EDT пишет имя платформы): сравнение пар форм полной БСП
# 07.11.2026; прочие типы выгрузки - имя платформы с префиксом пространства имен
XML_TYPES = {"dcsset:SettingsComposer": "DataCompositionSettingsComposer", "dcsset:Filter": "DataCompositionFilter",
             "dcsset:Settings": "DataCompositionSettings", "dcscor:Field": "DataCompositionField"}
# Префикс пространства имен схемы - свой в каждом файле (`d5p1:`): по имени без него
LOCAL_TYPES = {"FlowchartContextType": "GraphicalSchema"}
COLLECTIONS = {"ValueTable", "ValueTree", "ValueList", "DynamicList"}
# Роли типа, у которых есть реквизиты: ссылка, объект, запись регистра
ROLES = {"Ref", "Object", "RecordManager", "RecordSet"}
LINE_NUMBER = {"LineNumber", "НомерСтроки"}
# Стандартные реквизиты, которые пишутся в состав типа по виду объекта (имена - как в пути к данным EDT)
# Порядок - как в окне выбора реквизита конфигуратора (по снимку окна)
STANDARD_BY_KIND = {
    "Catalog": ("Ref", "Code", "Description", "Owner", "Parent", "IsFolder", "DeletionMark", "Predefined",
                "PredefinedDataName"),
    "Document": ("Ref", "Number", "Date", "Posted", "DeletionMark"),
    "ChartOfCharacteristicTypes": ("Ref", "Code", "Description", "Parent", "IsFolder", "DeletionMark", "Predefined",
                                   "PredefinedDataName"),
    "ChartOfAccounts": ("Ref", "Code", "Description", "Parent", "DeletionMark", "Predefined", "PredefinedDataName"),
    "ChartOfCalculationTypes": ("Ref", "Code", "Description", "DeletionMark", "Predefined", "PredefinedDataName"),
    "ExchangePlan": ("Ref", "Code", "Description", "DeletionMark"),
    "BusinessProcess": ("Ref", "Number", "Date", "Started", "Completed", "DeletionMark"),
    "Task": ("Ref", "Number", "Date", "Description", "Executed", "BusinessProcess", "RoutePoint", "DeletionMark"),
}
OPTIONAL_STANDARD = {"Code", "Description", "Number"}   # есть при ненулевой длине в метаданных


def type_name(text: str) -> str:
    text = (text or "").strip()
    found = DESIGNER_TYPES.get(text) or XML_TYPES.get(text)
    if found:
        return found
    name = PREFIX.sub("", text)
    return LOCAL_TYPES.get(name, name)


def value_type(types):
    """`valueType` модели: одна строка или список при составном типе; пусто - None."""
    names = [type_name(item) for item in types or [] if item and item.strip()]
    if not names:
        return None
    return names[0] if len(names) == 1 else names


def type_names(node) -> list:
    value = node.get("valueType") if isinstance(node, dict) else None
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def type_key(text: str):
    """`CatalogRef.Контрагенты`, `DocumentObject.Заказ` → `Catalog.Контрагенты`; не объектный тип - None."""
    parsed = parse_type(type_name(text))
    if not parsed or parsed[0] == "Enum" or parsed[1] not in ROLES:
        return None
    return f"{parsed[0]}.{parsed[2]}"


def is_ref(text: str) -> bool:
    parsed = parse_type(type_name(text))
    return bool(parsed) and parsed[1] == "Ref"


def entry(attribute: Attribute, main: bool = False) -> dict:
    """Реквизит формы, колонка или реквизит типа - запись модели."""
    node = {"name": attribute.name}
    if attribute.title and attribute.title != split_name(attribute.name):
        node["title"] = attribute.title
    found = value_type(attribute.types)
    if found:
        node["valueType"] = found
    for key in ("length", "digits", "fractionDigits", "dateFractions"):
        # Состав даты «Дата и время» - умолчание: в модель не пишется
        if key in (attribute.qualifiers or {}) and attribute.qualifiers[key] != "DateTime":
            node[key] = attribute.qualifiers[key]
    if main:
        node["main"] = True
    if attribute.main_table:
        node["mainTable"] = attribute.main_table
    if attribute.columns:
        node["columns"] = [entry(column) for column in attribute.columns.values()]
    extra = {table: [entry(column) for column in columns.values()] for table, columns in attribute.additional.items() if columns}
    if extra:
        node["additionalColumns"] = extra
    return node


def describe(obj: MetaObject, common: list = ()) -> dict:
    """Состав типа: стандартные реквизиты вида, реквизиты (измерения, ресурсы), общие реквизиты конфигурации,
    табличные части."""
    result = {}
    if obj.caption != split_name(obj.name):
        result["title"] = obj.caption
    attributes = []
    for name in STANDARD_BY_KIND.get(obj.kind, ()):
        if name in OPTIONAL_STANDARD and name not in obj.standard_qualifiers:
            continue
        if name == "Owner" and not obj.owners or name == "Posted" and not obj.posting:
            continue
        if name in ("Parent", "IsFolder") and not obj.hierarchical and obj.kind != "ChartOfAccounts" \
                or name == "IsFolder" and obj.kind == "ChartOfAccounts":
            continue
        found = obj.field(name)
        if found is not None and name == "Ref" and obj.kind in REF_KINDS:
            # Ссылка - на сам объект: дерево раскрывает ее его же составом
            found = Attribute(found.name, found.title, [f"{REF_KINDS[obj.kind]}.{obj.name}"])
        if found is not None:
            attributes.append(entry(found))
    attributes += [entry(item) for item in obj.attributes.values()]
    attributes += [entry(item) for item in common if item.name not in obj.attributes]
    if attributes:
        result["attributes"] = attributes
    sections = []
    for section in obj.tabular.values():
        node = {"name": section.name}
        if section.title and section.title != split_name(section.name):
            node["title"] = section.title
        node["columns"] = [entry(column) for column in section.columns.values()]
        sections.append(node)
    if sections:
        result["tabularSections"] = sections
    return result


class Paths:
    """Проход пути к данным по `attributes` и `types` модели.

    `describe(key)` - добор состава типа, которого нет в `types` (импорт - из метаданных); без него
    неописанный тип - неизвестный состав.
    """

    def __init__(self, attributes, types, describe=None):
        self.attributes = [item for item in attributes or [] if isinstance(item, dict)]
        self.types = types if isinstance(types, dict) else {}
        self.describe = describe

    def roots(self) -> dict:
        return {item["name"]: item for item in self.attributes if isinstance(item.get("name"), str)}

    def type_of(self, key: str):
        if key not in self.types and self.describe:
            found = self.describe(key)
            if found is not None:
                self.types[key] = found
        found = self.types.get(key)
        return found if isinstance(found, dict) else None

    def members(self, node):
        """Подчиненные узла пути: имя → узел; None - состав неизвестен (дальше путь не проверяется)."""
        result, known = {}, False
        if isinstance(node.get("columns"), list):
            known = True
            for item in node["columns"]:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    result[item["name"]] = item
        names = type_names(node)
        if "DynamicList" in names:
            # Поля динамического списка - из запроса; основная таблица дает только часть из них
            return None
        for name in names:
            if name in COLLECTIONS:
                continue
            key = type_key(name)
            described = self.type_of(key) if key else None
            if described is None:
                if key or name not in ("String", "Number", "Date", "Boolean"):
                    return None
                continue
            known = True
            for item in described.get("attributes") or []:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    result.setdefault(item["name"], item)
            for item in described.get("tabularSections") or []:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    result.setdefault(item["name"], dict(item, collection=True))
        return result if known else {}

    @staticmethod
    def with_additional(root: dict, table: str, node: dict) -> dict:
        """Табличная часть с дополнительными колонками формы (`additionalColumns` реквизита формы)."""
        extra = root.get("additionalColumns")
        columns = extra.get(table) if isinstance(extra, dict) else None
        if not is_collection(node) or not isinstance(columns, list):
            return node
        return dict(node, columns=list(node.get("columns") or []) + columns)

    def walk(self, path: str):
        """(узлы по сегментам, текст замечания или ""). Замечание - только если сегмента точно нет."""
        segments = path.split(".")
        roots = self.roots()
        if segments[0] not in roots:
            return [], f"реквизита {segments[0]} нет в реквизитах формы (attributes)"
        root = roots[segments[0]]
        nodes = [root]
        for index, segment in enumerate(segments[1:], 1):
            current = nodes[-1]
            members = self.members(current)
            if members is None:
                return nodes, ""
            if segment in members:
                nodes.append(self.with_additional(root, ".".join(segments[1:index + 1]), members[segment]))
                continue
            # Набор записей регистра бухгалтерии: ресурс и измерение без признака баланса - по дебету и кредиту
            side = re.match(r"(.+)(Dr|Cr)$", segment)
            if side and side.group(1) in members:
                nodes.append(members[side.group(1)])
                continue
            collection = isinstance(current.get("columns"), list) or current.get("collection")
            # Номер строки и итоги коллекции, стандартные реквизиты платформы (английские имена: Ref,
            # SettingsComposer, RegisterRecords; русские - в запросе) - состав модели их не перечисляет
            if collection and (segment in LINE_NUMBER or segment.startswith("Total")) or re.match(r"[A-Za-z]", segment) \
                    or segment in STANDARD_RU:
                return nodes, ""
            if not members:
                kind = ", ".join(type_names(current)) or "без типа"
                return nodes, f"у {'.'.join(segments[:index])} ({kind}) нет реквизитов, а в пути есть {segment}"
            return nodes, f"у {'.'.join(segments[:index])} нет реквизита {segment}"
        return nodes, ""


def path_title(paths: Paths, path: str) -> str:
    """Заголовок элемента без своего - по пути к данным, как у импорта (`field_title`) и рисунка (`pathTitle`
    рендерера): заголовок реквизита по пути, иначе последнее имя пути - стандартный реквизит русским заголовком,
    прочее по словам."""
    segments = path.split(".")
    nodes, _ = paths.walk(path)
    if len(nodes) == len(segments) and isinstance(nodes[-1].get("title"), str) and nodes[-1]["title"]:
        return nodes[-1]["title"]
    english = STANDARD_RU.get(segments[-1], segments[-1])
    return STANDARD[english][0] if english in STANDARD else split_name(segments[-1])


def is_collection(node: dict) -> bool:
    """Коллекция - то, к чему привязывается таблица: колонки, табличная часть, коллекция платформы, набор записей."""
    names = type_names(node)
    record_set = any((parse_type(type_name(name)) or ("", "", ""))[1] == "RecordSet" for name in names)
    return isinstance(node.get("columns"), list) or bool(node.get("collection")) or bool(set(names) & COLLECTIONS) \
        or record_set
