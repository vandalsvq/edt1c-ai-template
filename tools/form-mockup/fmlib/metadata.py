"""Метаданные конфигурации для импорта формы.

Заголовок и тип поля без своего заголовка импорт берет по цепочке: реквизит формы →
метаданные объекта → имя, разбитое по словам. Здесь - вторая ступень: объект
метаданных по виду и имени, его реквизиты, табличные части, стандартные реквизиты и
команды. Два формата исходников:

- EDT: `<src>/Catalogs/<Имя>/<Имя>.mdo`;
- выгрузка конфигуратора: `<src>/Catalogs/<Имя>.xml`.

Объекты читаются лениво и кешируются: форма БП ссылается на десятки справочников.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

LONG_PATH = 240             # с запасом до предела Windows в 260 символов


def long_path(path: Path) -> Path:
    """Путь для чтения: на Windows длинный путь - с префиксом `\\\\?\\` (формы глубоких объектов выгрузки
    конфигуратора длиннее 260 символов); короткий и на других ОС - как есть."""
    text = str(path)
    if sys.platform != "win32" or len(text) < LONG_PATH or text.startswith("\\\\?\\"):
        return path
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
V8 = "{http://v8.1c.ru/8.1/data/core}"
XR = "{http://v8.1c.ru/8.3/xcf/readable}"
MD = "{http://v8.1c.ru/8.3/MDClasses}"

# Вид объекта метаданных → каталог в исходниках (одинаков в EDT и выгрузке)
FOLDERS = {
    "Catalog": "Catalogs",
    "Document": "Documents",
    "DataProcessor": "DataProcessors",
    "Report": "Reports",
    "Enum": "Enums",
    "InformationRegister": "InformationRegisters",
    "AccumulationRegister": "AccumulationRegisters",
    "AccountingRegister": "AccountingRegisters",
    "CalculationRegister": "CalculationRegisters",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartOfAccounts": "ChartsOfAccounts",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "ExchangePlan": "ExchangePlans",
    "BusinessProcess": "BusinessProcesses",
    "Task": "Tasks",
    "DocumentJournal": "DocumentJournals",
    "CommonCommand": "CommonCommands",
    "CommonForm": "CommonForms",
    "Constant": "Constants",
    "FilterCriterion": "FilterCriteria",
    "SettingsStorage": "SettingsStorages",
    "DefinedType": "DefinedTypes",
    "CommandGroup": "CommandGroups",
    "CommonAttribute": "CommonAttributes",
}
# Виды объектов со своими командами: их команды с группой командной панели формы - глобальные команды
# формы объекта, как общие (по снимку 1С: общая форма обработки и подменю обработки)
COMMAND_OWNERS = ("Catalog", "Document", "DataProcessor", "Report", "InformationRegister", "AccumulationRegister",
                  "AccountingRegister", "CalculationRegister", "ChartOfCharacteristicTypes", "ChartOfAccounts",
                  "ChartOfCalculationTypes", "ExchangePlan", "BusinessProcess", "Task", "DocumentJournal",
                  "FilterCriterion")
KINDS = {folder: kind for kind, folder in FOLDERS.items()}

# Тип значения платформы: `CatalogRef.Контрагенты`, `DocumentObject.Заказ`,
# `InformationRegisterRecordManager.Цены` → (вид объекта, роль, имя)
TYPE_PATTERN = re.compile(
    r"^(?P<kind>" + "|".join(sorted(FOLDERS, key=len, reverse=True)) + r")"
    r"(?P<role>Ref|Object|RecordManager|RecordSet|RecordKey|Manager|List|Selection|TabularSection\w*)?\.(?P<name>[^.]+)$"
)

# Стандартные реквизиты: имя в пути данных (EDT и выгрузка пишут английское, запрос
# динамического списка - русское) → заголовок и упрощенный тип модели
STANDARD = {
    "Ref": ("Ссылка", "ref"),
    "Code": ("Код", "string"),
    "Description": ("Наименование", "string"),
    "Owner": ("Владелец", "ref"),
    "Parent": ("Родитель", "ref"),
    "IsFolder": ("Это группа", "boolean"),
    "DeletionMark": ("Пометка удаления", "boolean"),
    "Predefined": ("Предопределенный", "boolean"),
    "PredefinedDataName": ("Имя предопределенных данных", "string"),
    "Date": ("Дата", "date"),
    "Number": ("Номер", "string"),
    "Posted": ("Проведен", "boolean"),
    "LineNumber": ("N", "number"),
    "Period": ("Период", "date"),
    "Recorder": ("Регистратор", "ref"),
    "Active": ("Активность", "boolean"),
    "Started": ("Стартован", "boolean"),
    "Completed": ("Завершен", "boolean"),
    "Executed": ("Выполнена", "boolean"),
    "BusinessProcess": ("Бизнес-процесс", "ref"),
    "RoutePoint": ("Точка маршрута", "ref"),
    "Order": ("Порядок", "number"),
    "ValueType": ("Тип значения", "string"),
}
STANDARD_RU = {
    "Ссылка": "Ref", "Код": "Code", "Наименование": "Description", "Владелец": "Owner",
    "Родитель": "Parent", "ЭтоГруппа": "IsFolder", "ПометкаУдаления": "DeletionMark",
    "Предопределенный": "Predefined", "Дата": "Date", "Номер": "Number", "Проведен": "Posted",
    "НомерСтроки": "LineNumber", "Период": "Period", "Регистратор": "Recorder", "Активность": "Active",
}

PRIMITIVES = {
    "String": "string", "xs:string": "string",
    "Number": "number", "xs:decimal": "number",
    "Date": "date", "xs:dateTime": "date",
    "Boolean": "boolean", "xs:boolean": "boolean",
}


def split_name(name: str) -> str:
    """Имя по словам, как синоним по умолчанию в 1С: `ДатаОтгрузки` → «Дата отгрузки».

    То же правило, что `splitName` рендерера: слова из одних заглавных (ИНН) не меняются.
    """
    text = re.sub(r"([а-яёa-z0-9])([А-ЯЁA-Z])", r"\1 \2", name or "")
    # Аббревиатура перед словом: `ИННКонтрагента` → «ИНН контрагента», `ВКаждой` → «в каждой»
    text = re.sub(r"([А-ЯЁA-Z])([А-ЯЁA-Z][а-яёa-z])", r"\1 \2", text)
    result = []
    for index, word in enumerate(text.split(" ")):
        if index == 0 or len(word) > 1 and re.fullmatch(r"[А-ЯЁA-Z0-9]+", word):
            result.append(word)
        else:
            result.append(word.lower())
    return " ".join(result)


NAME = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$")


def clean_path(path):
    """Путь к данным, пригодный для цепочки заголовков, или None.

    Выгрузка пишет непривязанный путь с `~` (`~Список.Код`), иногда дважды, а
    реквизит другой конфигурации - идентификаторами (`1/0:<uuid>`): такой путь -
    не путь, заголовок берется по имени элемента.
    """
    if not path:
        return None
    path = path.lstrip("~").split("~", 1)[0]
    if not all(NAME.match(segment) for segment in path.split(".")):
        return None
    return path


def simple_type(types) -> str | None:
    """Упрощенный тип модели по списку типов платформы; составной с ссылкой - ссылка."""
    kinds = []
    for item in types or []:
        item = re.sub(r"^(cfg|d\d+p\d+):", "", item.strip())
        if item in PRIMITIVES:
            kinds.append(PRIMITIVES[item])
        elif TYPE_PATTERN.match(item) or item.endswith("Ref") or ".Ref" in item or "Ref." in item:
            kinds.append("ref")
        else:
            kinds.append(None)
    known = [kind for kind in kinds if kind]
    if not known:
        return None
    if "ref" in known:
        return "ref"
    return known[0]


def parse_type(text: str):
    """`CatalogRef.Контрагенты` → (Catalog, Ref, Контрагенты) или None."""
    text = re.sub(r"^(cfg|d\d+p\d+):", "", (text or "").strip())
    found = TYPE_PATTERN.match(text)
    if not found:
        return None
    return found.group("kind"), found.group("role") or "", found.group("name")


@dataclass
class Attribute:
    """Реквизит объекта, табличной части или реквизит формы."""

    name: str
    title: str | None = None
    types: list = field(default_factory=list)
    columns: dict = field(default_factory=dict)      # табличная часть, колонки реквизита формы
    additional: dict = field(default_factory=dict)   # реквизит формы: табличная часть по пути от него → свои колонки
    main_table: str | None = None                   # динамический список: Catalog.Имя
    fill_check: bool = False                        # проверка заполнения «Выдавать ошибку»
    multi_line: bool = False                        # «Многострочный режим» реквизита: поле «Авто» берет его
    qualifiers: dict = field(default_factory=dict)   # квалификаторы типа: length, digits, fractionDigits
    tool_tip: str | None = None                     # подсказка реквизита: поле без своей берет ее
    format: str | None = None                       # «Формат» реквизита: поле без своего берет его

    @property
    def caption(self) -> str:
        return self.title or split_name(self.name)


@dataclass
class MetaObject:
    """Объект метаданных: то, что нужно импорту формы."""

    kind: str
    name: str
    synonym: str | None = None
    object_presentation: str | None = None
    list_presentation: str | None = None
    attributes: dict = field(default_factory=dict)   # имя → Attribute (реквизиты, измерения, ресурсы)
    tabular: dict = field(default_factory=dict)      # имя → Attribute с columns
    standard: dict = field(default_factory=dict)     # английское имя → синоним, если переопределен
    standard_fill: set = field(default_factory=set)  # стандартные реквизиты с проверкой заполнения
    standard_qualifiers: dict = field(default_factory=dict)  # Code, Description, Number → квалификаторы
    as_code: bool = False                            # основное представление «В виде кода» (план счетов БП)
    hierarchical: bool = False                       # иерархический справочник или ПВХ: есть реквизит Родитель
    owners: list = field(default_factory=list)       # владельцы справочника: `Catalog.Контрагенты`
    commands: dict = field(default_factory=dict)     # имя → (синоним, картинка, представление)
    command_objects: list = field(default_factory=list)  # команды объекта: MetaObject вида Command
    category: str | None = None                      # группа команд: категория (FormCommandBar и т.п.)
    full: str | None = None                          # команда: полное имя в форме (`CommonCommand.Имя`)
    values: dict = field(default_factory=dict)       # перечисление: имя значения → синоним
    types: list = field(default_factory=list)        # определяемый тип: типы платформы
    group: str | None = None                         # общая команда: группа размещения
    parameter_types: list = field(default_factory=list)  # общая команда: тип параметра
    picture: str | None = None                       # общая команда: картинка
    representation: str | None = None                # общая команда: представление кнопки
    forms: dict = field(default_factory=dict)        # defaultObjectForm и т.п. → имя формы
    posting: bool = True                             # документ: проведение разрешено
    path: Path | None = None

    @property
    def caption(self) -> str:
        return self.synonym or split_name(self.name)

    def field(self, name: str):
        """Реквизит объекта или стандартный реквизит: Attribute или None."""
        if name in self.attributes:
            return self.attributes[name]
        english = STANDARD_RU.get(name, name)
        if english in STANDARD:
            title, kind = STANDARD[english]
            types = [kind_type(kind)]
            # Родитель - ссылка на сам объект, владелец - на владельцев: тип нужен для кнопок поля и ширины по коду
            if english == "Parent" and self.kind in REF_KINDS:
                types = [REF_KINDS[self.kind] + "." + self.name]
            elif english == "Owner" and self.owners:
                types = [REF_KINDS.get(owner.split(".")[0], "AnyRef") + "." + owner.split(".")[-1] for owner in self.owners]
            return Attribute(english, self.standard.get(english) or title, types,
                             fill_check=english in self.standard_fill,
                             qualifiers=self.standard_qualifiers.get(english, {}))
        return None


def kind_type(kind: str) -> str:
    """Упрощенный тип стандартного реквизита обратно в имя типа платформы (для simple_type)."""
    return {"string": "String", "number": "Number", "date": "Date", "boolean": "Boolean"}.get(kind, "AnyRef")


def local_text(entries, lang="ru"):
    """Строка на языке: EDT `<key>/<value>`, выгрузка `<v8:item>/<v8:lang>/<v8:content>`.

    Нет `ru` - первый язык.
    """
    values = []
    for key, value in entries:
        if value is None:
            continue
        if key == lang:
            return value
        values.append(value)
    return values[0] if values else None


def edt_text(parent, tag):
    """Многоязычная строка EDT: повторяющиеся `<tag><key/><value/></tag>`."""
    return local_text((item.findtext("key"), item.findtext("value")) for item in parent.findall(tag))


def designer_text(element):
    """Многоязычная строка выгрузки: `<v8:item><v8:lang/><v8:content/></v8:item>`."""
    if element is None:
        return None
    items = element.findall(V8 + "item")
    if not items:
        return element.text.strip() if element.text and element.text.strip() else None
    return local_text((item.findtext(V8 + "lang"), item.findtext(V8 + "content") or "") for item in items)


BASED_ON_KINDS = ("Document", "Catalog", "BusinessProcess", "Task", "ChartOfCharacteristicTypes",
                  "ChartOfAccounts", "ChartOfCalculationTypes")
BASED_ON_EDT = re.compile(r"<basedOn>([^<]+)</basedOn>")
BASED_ON_DESIGNER = re.compile(r"<BasedOn>(.*?)</BasedOn>", re.S)
MD_REF = re.compile(r"MDObjectRef\">([^<]+)<")
BASED_ON_CACHE = {}
COMMANDS_CACHE = {}          # (корень, формат) → общие команды панели формы с раскрытыми типами параметра
COMMON_CACHE = {}            # (корень, формат) → общие реквизиты: [(Attribute, автоиспользование, {объект: использование})]
REF_KINDS = {"Document": "DocumentRef", "Catalog": "CatalogRef", "BusinessProcess": "BusinessProcessRef",
             "Task": "TaskRef", "ExchangePlan": "ExchangePlanRef", "ChartOfAccounts": "ChartOfAccountsRef",
             "ChartOfCharacteristicTypes": "ChartOfCharacteristicTypesRef",
             "ChartOfCalculationTypes": "ChartOfCalculationTypesRef"}          # (корень, формат) → полное имя объекта → кто вводится на его основании


class Metadata:
    """Объекты метаданных по виду и имени: ленивое чтение с кешем.

    `src` - корень исходников (каталог с Catalogs, Documents...), `edt` - формат.
    Нет корня (форма вне конфигурации) - объектов нет, цепочка идет к имени.
    """

    def __init__(self, src: Path | None, edt: bool):
        self.src = src
        self.edt = edt
        self.cache = {}
        self.missing = []

    def object(self, kind: str, name: str):
        key = (kind, name)
        if key in self.cache:
            return self.cache[key]
        result = None
        path = self.path_of(kind, name)
        if path and long_path(path).is_file():
            try:
                result = (read_mdo if self.edt else read_designer)(path, kind, name)
            except (ET.ParseError, OSError):
                result = None
        if result is None:
            self.missing.append(f"{kind}.{name}" + (f" ({path})" if path else ""))
        self.cache[key] = result
        return result

    def path_of(self, kind: str, name: str):
        if not self.src or kind not in FOLDERS:
            return None
        folder = self.src / FOLDERS[kind]
        return folder / name / f"{name}.mdo" if self.edt else folder / f"{name}.xml"

    def by_type(self, text: str):
        parsed = parse_type(text)
        return self.object(parsed[0], parsed[2]) if parsed else None

    def based_on(self, full_name: str) -> list:
        """Объекты, которые вводятся на основании `full_name` (`Document.Имя`): по свойству «Вводится на основании»."""
        if not self.src:
            return []
        key = (self.src, self.edt)
        if key not in BASED_ON_CACHE:
            BASED_ON_CACHE[key] = self.based_on_index()
        return BASED_ON_CACHE[key].get(full_name, [])

    def based_on_index(self) -> dict:
        index = {}
        for kind in BASED_ON_KINDS:
            folder = self.src / FOLDERS[kind]
            if not folder.is_dir():
                continue
            files = folder.glob("*/*.mdo") if self.edt else folder.glob("*.xml")
            for path in files:
                try:
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                except OSError:
                    continue
                if self.edt:
                    bases = BASED_ON_EDT.findall(text)
                else:
                    bases = [ref for block in BASED_ON_DESIGNER.findall(text) for ref in MD_REF.findall(block)]
                for base in bases:
                    index.setdefault(base.strip(), []).append(f"{kind}.{path.stem}")
        return index

    def form_commands(self, full_name: str) -> list:
        """Общие команды панели формы объекта `full_name`: группа `FormCommandBar*` и тип параметра -
        ссылка на объект (в том числе через определяемый тип). По имени, как список в конфигураторе."""
        kind, _, name = (full_name or "").partition(".")
        if not self.src or kind not in REF_KINDS:
            return []
        key = (self.src, self.edt)
        if key not in COMMANDS_CACHE:
            COMMANDS_CACHE[key] = self.commands_index()
        ref = f"{REF_KINDS[kind]}.{name}"
        return [command for command, types in COMMANDS_CACHE[key] if ref in types]

    def commands_index(self) -> list:
        """Команды с группой командной панели формы: общие и команды объектов (полное имя команды в
        форме - `CommonCommand.Имя`, `DataProcessor.Обработка.Command.Имя`); группа - `FormCommandBar*`
        или группа команд категории «Командная панель формы»."""
        result = []
        folder = self.src / FOLDERS["CommonCommand"]
        names = sorted(path.name if self.edt else path.stem
                       for path in folder.iterdir() if (path.is_dir() if self.edt else path.suffix == ".xml")) \
            if folder.is_dir() else []
        for name in names:
            command = self.object("CommonCommand", name)
            if command is not None and self.form_bar_group(command.group):
                # Имя - из объекта: имя каталога на macOS бывает в разложенной форме («й» как и + U+0306)
                command.full = f"CommonCommand.{command.name}"
                result.append((command, self.ref_types(command.parameter_types)))
        for kind in COMMAND_OWNERS:
            folder = self.src / FOLDERS[kind]
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                file = path / f"{path.name}.mdo" if self.edt else path
                if not file.is_file() or (not self.edt and path.suffix != ".xml"):
                    continue
                # Быстрый отбор по тексту: разбирать стоит только объекты с командами панели формы
                text = file.read_text(encoding="utf-8", errors="ignore")
                if "FormCommandBar" not in text and "CommandGroup." not in text:
                    continue
                owner = self.object(kind, path.name if self.edt else path.stem)
                for command in (owner.command_objects if owner else []):
                    if self.form_bar_group(command.group):
                        command.full = f"{kind}.{owner.name}.Command.{command.name}"
                        result.append((command, self.ref_types(command.parameter_types)))
        return result

    def ref_types(self, types) -> set:
        return {re.sub(r"^(cfg|d\d+p\d+):", "", item) for item in self.expand_types(types)}

    def form_bar_group(self, group) -> bool:
        """Группа команды - в командной панели формы: `FormCommandBar*` или группа команд этой категории."""
        group = group or ""
        if group.startswith("FormCommandBar"):
            return True
        if group.startswith("CommandGroup."):
            found = self.object("CommandGroup", group.split(".", 1)[1])
            return bool(found and found.category == "FormCommandBar")
        return False

    def has_help(self, owner_path, form_path: Path) -> bool:
        """Справка у формы или у ее объекта: в командной панели формы - кнопка «?»."""
        if self.edt:
            places = [form_path.parent / "Help"] + ([owner_path.parent / "Help"] if owner_path else [])
        else:
            places = [form_path.parent / "Help.xml"] + (
                [owner_path.parent / owner_path.stem / "Ext" / "Help.xml"] if owner_path else [])
        return any(place.exists() for place in places)

    def common_attributes(self, full_name: str) -> list:
        """Общие реквизиты объекта `Catalog.Имя`: в составе «Использовать» или автоиспользование без «Не использовать»."""
        if not self.src:
            return []
        key = (self.src, self.edt)
        if key not in COMMON_CACHE:
            COMMON_CACHE[key] = self.common_index()
        return [attribute for attribute, auto, content in COMMON_CACHE[key]
                if content.get(full_name) == "Use" or auto and content.get(full_name) != "DontUse"]

    def common_index(self) -> list:
        result = []
        folder = self.src / FOLDERS["CommonAttribute"]
        if not folder.is_dir():
            return result
        for path in sorted(folder.iterdir()):
            file = path / f"{path.name}.mdo" if self.edt else path
            if not file.is_file() or (not self.edt and path.suffix != ".xml"):
                continue
            try:
                root = ET.parse(file).getroot()
            except ET.ParseError:
                continue
            if self.edt:
                attribute = Attribute(root.findtext("name") or path.name, edt_text(root, "synonym"),
                                      edt_types(root.find("type")), qualifiers=edt_qualifiers(root.find("type")))
                # EDT не пишет автоиспользование «Использовать» - первое значение (разделители БП без тега)
                auto = root.findtext("autoUse") != "DontUse"
                content = {item.findtext("metadata") or "": item.findtext("use") or "Auto" for item in root.findall("content")}
            else:
                body = next(iter(root), None)
                properties = body.find(MD + "Properties") if body is not None else None
                if properties is None:
                    continue
                attribute = designer_attribute(body)
                auto = properties.findtext(MD + "AutoUse") == "Use"
                items = properties.findall(f"{MD}Content/{XR}Item")
                content = {item.findtext(XR + "Metadata") or "": item.findtext(XR + "Use") or "Auto" for item in items}
            result.append((attribute, auto, content))
        return result

    def expand_types(self, types) -> list:
        """Типы с раскрытыми определяемыми (`DefinedType.Организация` → `CatalogRef.Организации`)."""
        result = []
        for item in types or []:
            name = re.sub(r"^(cfg|d\d+p\d+):", "", item.strip())
            if name.startswith("DefinedType."):
                found = self.object("DefinedType", name.split(".", 1)[1])
                result.extend(found.types if found else [])
            else:
                result.append(item)
        return result

    def by_full_name(self, text: str):
        """`Catalog.Контрагенты` → объект."""
        parts = (text or "").split(".")
        return self.object(parts[0], parts[1]) if len(parts) >= 2 else None

    @property
    def layers(self) -> list:
        """Исходники, из которых собраны объекты: у одиночных - они сами."""
        return [self]


class LayeredMetadata(Metadata):
    """Конфигурация и выбранные ее расширения: объект конфигурации, дополненный заимствованным
    объектом расширений (реквизиты, табличные части, команды, значения перечисления), и собственные объекты
    расширений. `layers` - сначала конфигурация; `own` - исходники формы при импорте (их `src` - для справки формы)."""

    def __init__(self, layers: list, own: Metadata | None = None):
        own = own or layers[0]
        super().__init__(own.src, own.edt)
        self.parts = list(layers)

    @property
    def layers(self) -> list:
        return self.parts

    def object(self, kind: str, name: str):
        key = (kind, name)
        if key in self.cache:
            return self.cache[key]
        found = [item for item in (layer.object(kind, name) for layer in self.parts) if item is not None]
        result = merged(found) if found else None
        if result is None:
            self.missing.append(f"{kind}.{name}")
        self.cache[key] = result
        return result

    def path_of(self, kind: str, name: str):
        for layer in self.parts:
            path = layer.path_of(kind, name)
            if path and long_path(path).is_file():
                return path
        return None

    def based_on(self, full_name: str) -> list:
        result = []
        for layer in self.parts:
            result += [name for name in layer.based_on(full_name) if name not in result]
        return result

    def form_commands(self, full_name: str) -> list:
        result, seen = [], set()
        for layer in self.parts:
            for command in layer.form_commands(full_name):
                if command.full not in seen:
                    seen.add(command.full)
                    result.append(command)
        return result

    def common_attributes(self, full_name: str) -> list:
        result = []
        for layer in self.parts:
            names = {attribute.name for attribute in result}
            result += [attribute for attribute in layer.common_attributes(full_name) if attribute.name not in names]
        return result


def merged(found: list) -> MetaObject:
    """Объект первого слоя (конфигурации), дополненный тем же объектом следующих слоев: заимствованный объект
    расширения несет свои новые реквизиты, табличные части и команды, а заимствованные части - повтор основы."""
    first = found[0]
    result = replace(first, attributes=dict(first.attributes),
                     tabular={name: replace(section, columns=dict(section.columns)) for name, section in first.tabular.items()},
                     commands=dict(first.commands), command_objects=list(first.command_objects),
                     values=dict(first.values), forms=dict(first.forms), standard=dict(first.standard))
    for extra in found[1:]:
        for name, attribute in extra.attributes.items():
            result.attributes.setdefault(name, attribute)
        for name, section in extra.tabular.items():
            if name not in result.tabular:
                result.tabular[name] = section
                continue
            for column, attribute in section.columns.items():
                result.tabular[name].columns.setdefault(column, attribute)
        for name, command in extra.commands.items():
            result.commands.setdefault(name, command)
        known = {command.name for command in result.command_objects}
        result.command_objects += [command for command in extra.command_objects if command.name not in known]
        for name, value in extra.values.items():
            result.values.setdefault(name, value)
        for name, value in extra.forms.items():
            result.forms.setdefault(name, value)
        for name, value in extra.standard.items():
            result.standard.setdefault(name, value)
    return result


def locate(form_path: Path, edt: bool):
    """Корень исходников и объект-владелец формы по пути к ней.

    EDT: `<src>/<Каталог вида>/<Объект>/Forms/<Форма>/Form.form`, общая форма -
    `<src>/CommonForms/<Форма>/Form.form`; выгрузка - то же с `Ext/Form.xml`.
    Возвращает (src, вид, имя объекта, имя формы); чего нет - None.
    """
    form_dir = form_path.resolve().parent
    if not edt and form_dir.name == "Ext":
        form_dir = form_dir.parent
    form_name = form_dir.name
    parent = form_dir.parent
    if parent.name == "Forms" and parent.parent.parent.name in KINDS:
        owner = parent.parent
        return owner.parent.parent, KINDS[owner.parent.name], owner.name, form_name
    if parent.name == "CommonForms":
        return parent.parent, "CommonForm", None, form_name
    return None, None, None, form_name


# EDT `.mdo`


def edt_types(element):
    if element is None:
        return []
    return [item.text for item in element.findall("types") if item.text]


def qualifiers_of(types, length, digits, fraction, fractions=None) -> dict:
    """Квалификаторы типа из одного примитива: строка - длина (0 - неограниченная), число - разрядность, дата - состав
    (EDT не пишет «Дата и время» - умолчание своей модели)."""
    result = {}
    if types == ["Date"]:
        result["dateFractions"] = fractions or "DateTime"
    if types == ["String"] and length is not None:
        result["length"] = int(length or 0)
    if types == ["Number"] and int(digits or 0) > 0:
        result["digits"] = int(digits)
        result["fractionDigits"] = int(fraction or 0)
    return result


def edt_numeric(kind: str):
    """EDT не пишет тип кода и номера «Число» (первое значение перечисления); у ПВХ и планов обмена типа нет."""
    return "Number" if kind in ("Catalog", "Document") else None


def standard_qualifiers(code_length, code_type, description_length, number_length, number_type) -> dict:
    """Длина кода, наименования и номера объекта; числовой код или номер - разрядность."""
    result = {}
    for name, length, kind in (("Code", code_length, code_type), ("Description", description_length, "String"),
                               ("Number", number_length, number_type)):
        if length and length != "0":
            result[name] = {"digits": int(length), "fractionDigits": 0} if kind == "Number" else {"length": int(length)}
    return result


def edt_qualifiers(element) -> dict:
    if element is None:
        return {}
    string = element.find("stringQualifiers")
    number = element.find("numberQualifiers")
    date = element.find("dateQualifiers")
    return qualifiers_of(edt_types(element), "" if string is None else string.findtext("length") or "",
                         None if number is None else number.findtext("precision"),
                         None if number is None else number.findtext("scale"),
                         None if date is None else date.findtext("dateFractions"))


def designer_qualifiers(element) -> dict:
    if element is None:
        return {}
    types = [{"xs:string": "String", "xs:decimal": "Number", "xs:dateTime": "Date"}.get(item, item)
             for item in designer_types(element)]
    string = element.find(V8 + "StringQualifiers")
    number = element.find(V8 + "NumberQualifiers")
    date = element.find(V8 + "DateQualifiers")
    return qualifiers_of(types, "" if string is None else string.findtext(V8 + "Length") or "",
                         None if number is None else number.findtext(V8 + "Digits"),
                         None if number is None else number.findtext(V8 + "FractionDigits"),
                         None if date is None else date.findtext(V8 + "DateFractions"))


def edt_picture(element):
    """Картинка команды или элемента EDT: `<picture><picture>CommonPicture.Имя</picture></picture>`."""
    found = element.find("picture")
    return (found.findtext("picture") or None) if found is not None else None


# Представление команды метаданных, которое EDT не пишет (первое значение перечисления), а выгрузка пишет
# `<Representation>Text</Representation>` (общая команда БСП)
EDT_COMMAND_REPRESENTATION = "Text"


def command_representation(value):
    """Представление кнопки у команды: в EDT и выгрузке «Картинка и текст» команды - `TextPicture`."""
    if not value or value == "Auto":
        return None
    return "PictureAndText" if value == "TextPicture" else value


def read_mdo(path: Path, kind: str, name: str) -> MetaObject:
    root = ET.parse(long_path(path)).getroot()
    result = MetaObject(kind, root.findtext("name") or name, path=path)
    result.synonym = edt_text(root, "synonym")
    result.object_presentation = edt_text(root, "objectPresentation")
    result.list_presentation = edt_text(root, "listPresentation")
    result.standard_qualifiers = standard_qualifiers(
        root.findtext("codeLength"), root.findtext("codeType") or edt_numeric(kind), root.findtext("descriptionLength"),
        root.findtext("numberLength"), root.findtext("numberType") or edt_numeric(kind))
    # EDT не пишет значение по умолчанию «В виде кода»: справочники БП - явно AsDescription, план счетов - без тега
    result.as_code = (root.findtext("defaultPresentation") or "AsCode") == "AsCode" and "Code" in result.standard_qualifiers
    result.owners = [item.text.strip() for item in root.findall("owners") if item.text]
    result.hierarchical = root.findtext("hierarchical") == "true"
    for tag in ("attributes", "dimensions", "resources", "accountingFlags", "addressingAttributes"):
        for item in root.findall(tag):
            attribute = Attribute(item.findtext("name") or "", edt_text(item, "synonym"), edt_types(item.find("type")),
                                  fill_check=item.findtext("fillChecking") == "ShowError",
                                  multi_line=item.findtext("multiLine") == "true",
                                  qualifiers=edt_qualifiers(item.find("type")), tool_tip=edt_text(item, "toolTip"),
                                  format=edt_text(item, "format"))
            result.attributes[attribute.name] = attribute
    for item in root.findall("tabularSections"):
        section = Attribute(item.findtext("name") or "", edt_text(item, "synonym"), tool_tip=edt_text(item, "toolTip"))
        for column in item.findall("attributes"):
            section.columns[column.findtext("name") or ""] = Attribute(
                column.findtext("name") or "", edt_text(column, "synonym"), edt_types(column.find("type")),
                fill_check=column.findtext("fillChecking") == "ShowError",
                multi_line=column.findtext("multiLine") == "true",
                qualifiers=edt_qualifiers(column.find("type")), tool_tip=edt_text(column, "toolTip"),
                format=edt_text(column, "format"))
        result.tabular[section.name] = section
    for item in root.findall("standardAttributes"):
        if item.findtext("fillChecking") == "ShowError":
            result.standard_fill.add(item.findtext("name") or "")
        synonym = edt_text(item, "synonym")
        if synonym:
            result.standard[item.findtext("name") or ""] = synonym
    for item in root.findall("commands"):
        representation = command_representation(item.findtext("representation") or EDT_COMMAND_REPRESENTATION)
        result.commands[item.findtext("name") or ""] = (edt_text(item, "synonym"), edt_picture(item), representation)
        command = MetaObject("Command", item.findtext("name") or "", synonym=edt_text(item, "synonym"),
                             group=item.findtext("group"), parameter_types=edt_types(item.find("commandParameterType")),
                             picture=edt_picture(item), representation=representation)
        result.command_objects.append(command)
    result.category = root.findtext("category")
    result.picture = edt_picture(root)
    representation = root.findtext("representation")
    if representation is None and kind == "CommonCommand":
        representation = EDT_COMMAND_REPRESENTATION
    result.representation = command_representation(representation)
    result.types = edt_types(root.find("type"))
    result.group = root.findtext("group")
    result.parameter_types = edt_types(root.find("commandParameterType"))
    result.posting = root.findtext("posting") != "Deny"
    for item in root.findall("enumValues"):
        result.values[item.findtext("name") or ""] = edt_text(item, "synonym")
    for tag in ("defaultObjectForm", "defaultListForm", "defaultChoiceForm", "defaultForm",
                "auxiliaryObjectForm", "auxiliaryListForm", "auxiliaryChoiceForm"):
        value = root.findtext(tag)
        if value:
            result.forms[tag] = value.rsplit(".", 1)[-1]
    return result


# Выгрузка конфигуратора `<Объект>.xml`


def designer_types(element):
    if element is None:
        return []
    return [item.text for item in element.findall(V8 + "Type") + element.findall(V8 + "TypeSet") if item.text]


def designer_attribute(element) -> Attribute:
    properties = element.find(MD + "Properties")
    if properties is None:
        return Attribute(element.get("name") or "")
    return Attribute(properties.findtext(MD + "Name") or "", designer_text(properties.find(MD + "Synonym")),
                     designer_types(properties.find(MD + "Type")),
                     fill_check=properties.findtext(MD + "FillChecking") == "ShowError",
                     multi_line=properties.findtext(MD + "MultiLine") == "true",
                     qualifiers=designer_qualifiers(properties.find(MD + "Type")),
                     tool_tip=designer_text(properties.find(MD + "ToolTip")),
                     format=designer_text(properties.find(MD + "Format")))


def designer_picture(properties):
    found = properties.find(MD + "Picture")
    return (found.findtext(XR + "Ref") or None) if found is not None else None


def read_designer(path: Path, kind: str, name: str) -> MetaObject:
    root = ET.parse(long_path(path)).getroot()
    body = next(iter(root), None)
    if body is None:
        return MetaObject(kind, name, path=path)
    properties = body.find(MD + "Properties")
    result = MetaObject(kind, name, path=path)
    if properties is not None:
        result.name = properties.findtext(MD + "Name") or name
        result.synonym = designer_text(properties.find(MD + "Synonym"))
        result.object_presentation = designer_text(properties.find(MD + "ObjectPresentation"))
        result.list_presentation = designer_text(properties.find(MD + "ListPresentation"))
        result.standard_qualifiers = standard_qualifiers(
            properties.findtext(MD + "CodeLength"), properties.findtext(MD + "CodeType"),
            properties.findtext(MD + "DescriptionLength"), properties.findtext(MD + "NumberLength"),
            properties.findtext(MD + "NumberType"))
        result.as_code = properties.findtext(MD + "DefaultPresentation") == "AsCode" and "Code" in result.standard_qualifiers
        owners = properties.find(MD + "Owners")
        result.owners = [item.text.strip() for item in owners if item.text] if owners is not None else []
        result.hierarchical = properties.findtext(MD + "Hierarchical") == "true"
        standard = properties.find(MD + "StandardAttributes")
        if standard is not None:
            for item in standard.findall(XR + "StandardAttribute"):
                if item.findtext(XR + "FillChecking") == "ShowError":
                    result.standard_fill.add(item.get("name") or "")
                synonym = designer_text(item.find(XR + "Synonym"))
                if synonym:
                    result.standard[item.get("name") or ""] = synonym
        result.picture = designer_picture(properties)
        result.types = designer_types(properties.find(MD + "Type"))
        result.group = properties.findtext(MD + "Group")
        result.parameter_types = designer_types(properties.find(MD + "CommandParameterType"))
        result.posting = properties.findtext(MD + "Posting") != "Deny"
        result.representation = command_representation(properties.findtext(MD + "Representation"))
        result.category = properties.findtext(MD + "Category")
        for tag in ("DefaultObjectForm", "DefaultListForm", "DefaultChoiceForm", "DefaultForm",
                    "AuxiliaryObjectForm", "AuxiliaryListForm", "AuxiliaryChoiceForm"):
            value = properties.findtext(MD + tag)
            if value:
                result.forms[tag[0].lower() + tag[1:]] = value.rsplit(".", 1)[-1]
    children = body.find(MD + "ChildObjects")
    if children is None:
        return result
    for tag in ("Attribute", "Dimension", "Resource", "AccountingFlag", "AddressingAttribute"):
        for item in children.findall(MD + tag):
            attribute = designer_attribute(item)
            result.attributes[attribute.name] = attribute
    for item in children.findall(MD + "TabularSection"):
        section = designer_attribute(item)
        columns = item.find(MD + "ChildObjects")
        if columns is not None:
            for column in columns.findall(MD + "Attribute"):
                attribute = designer_attribute(column)
                section.columns[attribute.name] = attribute
        result.tabular[section.name] = section
    for item in children.findall(MD + "EnumValue"):
        value = designer_attribute(item)
        result.values[value.name] = value.title
    for item in children.findall(MD + "Command"):
        command = designer_attribute(item)
        command_properties = item.find(MD + "Properties")
        picture = designer_picture(command_properties) if command_properties is not None else None
        representation = (command_representation(command_properties.findtext(MD + "Representation"))
                          if command_properties is not None else None)
        result.commands[command.name] = (command.title, picture, representation)
        if command_properties is not None:
            result.command_objects.append(MetaObject(
                "Command", command.name, synonym=command.title, group=command_properties.findtext(MD + "Group"),
                parameter_types=designer_types(command_properties.find(MD + "CommandParameterType")),
                picture=picture, representation=representation))
    return result
