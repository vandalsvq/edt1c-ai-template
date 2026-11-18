"""Импорт формы из XML в модель.

Формат - по корневому элементу: `form:Form` EDT (`Form.form`) или `Form` в пространстве
`http://v8.1c.ru/8.3/xcf/logform` (выгрузка конфигуратора `Form.xml`). Читатели формата
(`import_edt`, `import_designer`) отдают нейтральный вид со своими умолчаниями, модель
строит общий сборщик: цепочка заголовков и типов, вид формы и стандартные
команды п. 3, скрытые элементы п. 4, заглушки и отчет о нераспознанном п. 5. Реквизиты формы и состав
их типов - `attributes` и `types` модели: дерево пути к данным конструктора.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import SCHEMA_PATH, attributes, colors, import_designer, import_edt, pictures
from .importer_raw import FormRaw, Raw
from .metadata import Attribute, Metadata, locate, long_path, parse_type, simple_type, split_name
from .model import walk

EDT_FORM = "{http://g5.1c.ru/v8/dt/form}Form"
DESIGNER_FORM = "{http://v8.1c.ru/8.3/xcf/logform}Form"

# Виды, которые модель рисует заглушкой - из схемы, чтобы не разойтись с ней
# Поле картинки - свой вид схемы со свойствами, для импорта - как прочие поля-заглушки
STUBS = set(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]["StubField"]["properties"]["type"]["enum"]) | {"PictureField"}
FIELDS = {"InputField", "CheckBoxField", "RadioButtonField", "LabelField", "Table"} | STUBS
# Виды без своих свойств, которые рендерер рисует пустым полем своего вида, а не заглушкой
DRAWN = {"SpreadsheetDocumentField", "TextDocumentField", "PictureField"}

# Где какой вид допустим (схема: bodyItem, pageItem, columnItem, commandItem)
BODY = {"UsualGroup", "Pages", "InputField", "CheckBoxField", "RadioButtonField", "LabelField", "Table",
        "LabelDecoration", "PictureDecoration", "CommandBar", "Button", "Popup", "Addition"} | STUBS
BORDER_DEFAULTS = {"PictureField": "Single", "LabelField": "WithoutBorder"}
COLUMNS = {"InputField", "CheckBoxField", "LabelField", "ColumnGroup"} | STUBS
COMMANDS = {"Button", "ButtonGroup", "Popup", "Addition"}
PLACES = {"body": BODY, "pages": {"Page"}, "columns": COLUMNS, "commands": COMMANDS}
CHILD_PLACE = {"UsualGroup": "body", "Page": "body", "Pages": "pages", "Table": "columns",
               "ColumnGroup": "columns", "CommandBar": "commands", "ButtonGroup": "commands",
               "Popup": "commands", "AutoCommandBar": "commands"}

# Заголовки стандартных команд (синтакс-помощник, «Стандартные команды формы»)
STANDARD_COMMANDS = {
    "WriteAndClose": "Записать и закрыть", "Write": "Записать", "PostAndClose": "Провести и закрыть",
    "Post": "Провести", "UndoPosting": "Отмена проведения", "Close": "Закрыть", "Cancel": "Отмена",
    "OK": "ОК", "Yes": "Да", "No": "Нет", "Abort": "Прервать", "Retry": "Повторить", "Ignore": "Пропустить",
    "Help": "Справка", "Reread": "Перечитать", "Add": "Добавить", "Copy": "Скопировать",
    "Change": "Изменить", "Delete": "Удалить", "Create": "Создать", "CreateFolder": "Создать группу",
    "Choose": "Выбрать", "SetDeletionMark": "Пометить на удаление", "MoveUp": "Переместить вверх",
    "MoveDown": "Переместить вниз", "Find": "Расширенный поиск", "CancelSearch": "Отменить поиск",
    "FindByCurrentValue": "Найти по текущему значению", "SearchEverywhere": "Искать везде",
    "Refresh": "Обновить", "OutputList": "Вывести список...", "CustomizeForm": "Изменить форму...",
    "ListSettings": "Настроить список...", "SortListAsc": "Сортировать по возрастанию",
    "SortListDesc": "Сортировать по убыванию", "SelectAll": "Выделить все",
    "CopyToClipboard": "Скопировать в буфер обмена", "EndEdit": "Закончить редактирование",
    "ShowInList": "Показать в списке", "ChangeHistory": "История изменений",
    "SetDateInterval": "Установить период...", "Preview": "Предварительный просмотр", "Print": "Печать",
    "Generate": "Сформировать", "RestoreValues": "Восстановить значения...",
    "SaveValues": "Сохранить значения...", "Activate": "Активировать", "Start": "Старт",
    "ExecuteTask": "Выполнить", "LevelUp": "Перейти на уровень выше", "LevelDown": "Перейти на уровень ниже",
    "Hierarchy": "Иерархический просмотр", "List": "Список", "Tree": "Дерево",
    "Expand": "Развернуть", "Collapse": "Свернуть",
}
ENUM_VALUE = re.compile(r"^Enum\.([^.]+)\.EnumValue\.([^.]+)$")
STANDARD_PICTURES = {
    "Write": "StdPicture.Write", "Post": "StdPicture.Post", "Copy": "StdPicture.CloneListItem", "Change": "StdPicture.Change", "Delete": "StdPicture.Delete",
    "SetDeletionMark": "StdPicture.MarkToDelete", "MoveUp": "StdPicture.MoveUp", "MoveDown": "StdPicture.MoveDown",
    "Print": "StdPicture.Print", "Find": "StdPicture.Find", "CancelSearch": "StdPicture.CancelSearch",
    "Refresh": "StdPicture.Refresh", "CreateFolder": "StdPicture.CreateFolder",
    # «Добавить» с картинкой - зеленый «+» (по снимку 1С: таблица с кнопкой «Добавить»)
    "Add": "StdPicture.CreateListItem",
}
# Стандартные команды формы и таблицы - те, что рендерер сам ставит в автопанель по виду формы
# и таблицы (при автозаполнении их явные кнопки не дублируются), и те, которыми платформа
# заполняет группу кнопок с источником команд (`commandSource`): «Форма» - команды формы,
# `Item.<Таблица>` - таблицы. Порядок и кнопка по умолчанию - как в автопанелях рендерера
# Хвост - команды формы объекта «только в Еще» (по снимку 1С: меню «Еще» формы элемента)
FORM_MORE = ["Reread", "Copy", "SetDeletionMark", "Delete", "ShowInList", "ChangeHistory"]
SOURCE_FORM = {
    "DocumentObjectForm": ["PostAndClose", "Write", "Post", "UndoPosting"] + FORM_MORE,
    "CatalogObjectForm": ["WriteAndClose", "Write"] + FORM_MORE,
}
# Заголовок команды формы, отличный от заголовка той же команды таблицы
FORM_TITLES = {"SetDeletionMark": "Пометить на удаление / Снять пометку"}
# Разметка форматированной строки 1С: <b>, <link адрес>, </> и т.п.
MARKUP = re.compile(r"</?[a-z]*(?:\s[^<>]*)?>", re.I)
# Стандартные команды таблицы в меню «Еще» по секциям между чертами (снимки 1С: «Объекты
# метаданных», «Поля набора», «Поля запроса», «Соединения»). Без «Изменять состав строк» нет добавления,
# копирования и удаления, без «Изменять порядок строк» - перемещения и сортировки. Группа кнопок с
# источником - таблицей заполняется ими же: на панели - «Добавить» и стрелки, остальное - в «Еще»
MORE_TABLE = [["Add", "Copy", "Change", "Delete", "EndEdit", "FindByCurrentValue", "Find", "CancelSearch"],
              ["MoveUp", "MoveDown"], ["SortListAsc", "SortListDesc", "OutputList"]]
ROW_SET = {"Add", "Copy", "Delete"}
ROW_ORDER = {"MoveUp", "MoveDown", "SortListAsc", "SortListDesc"}
SOURCE_LIST = ["Create", "Copy", "Change", "SetDeletionMark"]
ICON_COMMANDS = {"Copy", "Change", "SetDeletionMark", "MoveUp", "MoveDown"}
# В 1С они в меню «Еще», если их не вынесли в панель явно
MORE_ONLY = {"Help", "CustomizeForm", "OutputList", "ListSettings", "SortListAsc", "SortListDesc",
             "SelectAll", "CopyToClipboard", "FindByCurrentValue", "SearchEverywhere", "ChangeHistory",
             "Reread", "ShowInList", "SaveValues", "RestoreValues", "EndEdit", "Find", "CancelSearch"}

MORE_ONLY_FORM = {"Copy", "SetDeletionMark", "Delete", "UndoPosting"}
# Стандартные команды поля табличного документа: заголовки 1С; в командной панели при «Авто» - значком
# (снимок 1С: две строки панели над документом); значки рисует рендерер - в стандартных
# картинках платформы их нет
SPREADSHEET_COMMANDS = {
    "PasteFromClipboard": "Вставить из буфера обмена", "CopyToClipboard": "Скопировать в буфер обмена",
    "Undo": "Отменить", "Redo": "Вернуть", "SetName": "Назначить имя", "RemoveName": "Убрать имя",
    "GoToCell": "Перейти к ячейке", "InsertRows": "Раздвинуть", "SplitCell": "Разбить ячейку",
    "InsertRowsTop": "Вставить строки сверху", "InsertRowsBottom": "Вставить строки снизу",
    "DeleteRows": "Удалить строки", "InsertColumnsLeft": "Вставить колонки слева",
    "InsertColumnsRight": "Вставить колонки справа", "DeleteColumns": "Удалить колонки",
    "ClearAll": "Очистить все", "ClearContent": "Очистить содержимое", "Hide": "Скрыть", "Show": "Отобразить",
    "RowHeight": "Высота строк", "ColumnWidth": "Ширина колонок", "PageSetup": "Параметры страницы",
    "Font": "Шрифт", "Bold": "Жирный", "Italic": "Наклонный", "Underline": "Подчеркнутый",
    "AlignLeft": "Выровнять влево", "AlignCenter": "Выровнять по центру", "AlignRight": "Выровнять вправо",
    "AlignJustify": "Выровнять по ширине", "BackColor": "Цвет фона", "TextColor": "Цвет текста",
    "BorderColor": "Цвет рамки", "Merge": "Объединить", "BorderLeft": "Граница слева",
    "BorderTop": "Граница сверху", "BorderRight": "Граница справа", "BorderBottom": "Граница снизу",
    "BorderAll": "Граница везде", "BorderOutline": "Граница вокруг", "BorderInside": "Граница внутри",
    "ThickBorderOutline": "Толстая граница вокруг", "ThickBorderTop": "Толстая граница сверху",
    "ThickBorderBottom": "Толстая граница снизу", "BorderNone": "Нет границы",
}
SPREADSHEET_ICONS = {"PasteFromClipboard", "CopyToClipboard", "Undo", "Redo", "SetName", "RemoveName", "PageSetup",
                     "Font", "Bold", "Italic", "Underline", "AlignLeft", "AlignCenter", "AlignRight", "AlignJustify",
                     "BackColor", "TextColor", "BorderColor", "Merge", "BorderLeft", "BorderTop", "BorderRight",
                     "BorderBottom", "BorderAll", "BorderOutline", "BorderInside", "ThickBorderOutline", "ThickBorderTop",
                     "ThickBorderBottom", "BorderNone"}
# Команды строки таблицы, которые 1С держит в «Еще», если у кнопки отображение «Авто» (снимки 1С:
# «Области макета», «Поля набора», «Соединения»); с картинкой - на панели; у списка - кнопками (калибровка БП)
MORE_ONLY_TABLE = {"Copy", "Change", "Delete"}

# Поля, у которых в колонке таблицы свои свойства шапки, подвала и ячеек (схема: `columnBase`)
COLUMN_FIELDS = {"InputField", "CheckBoxField", "LabelField"}

COMMAND_NAME = re.compile(r"^[A-Za-zА-Яа-яЁё_][\wЁё]*(\.[A-Za-zА-Яа-яЁё_][\wЁё]*)+$")

OBJECT_FORMS = {"Catalog", "ChartOfCharacteristicTypes", "ChartOfAccounts", "ChartOfCalculationTypes",
                "ExchangePlan", "BusinessProcess", "Task"}


class ImportFailure(Exception):
    """Файл не XML или не форма - код возврата 2."""


@dataclass
class Report:
    """Отчет импорта: что распознано, откуда заголовки, что не нарисуется как есть."""

    path: Path
    format: str = ""
    form_kind: str = ""
    owner: str | None = None
    owner_path: Path | None = None
    kinds: Counter = field(default_factory=Counter)
    stubs: Counter = field(default_factory=Counter)
    pictures: tuple = (0, 0)                         # общих картинок: найдено в исходниках, всего
    std_pictures: tuple | None = None                # стандартных: найдено в выгрузке, всего
    styles: tuple = (0, 0)                           # цветов стиля формы: со значением, всего
    user_hidden: list = field(default_factory=list)  # элементы со снятой видимостью пользователя
    unknown: dict = field(default_factory=dict)       # исходный вид → имена элементов
    misplaced: dict = field(default_factory=dict)     # «вид в месте» → имена
    skipped: Counter = field(default_factory=Counter)
    titles: Counter = field(default_factory=Counter)  # откуда заголовок поля
    missing: list = field(default_factory=list)       # объекты метаданных, которых нет

    def lines(self) -> list:
        result = [f"Формат: {self.format}; вид формы: {self.form_kind}"]
        if self.owner:
            where = self.owner_path or "не найден"
            result.append(f"Объект метаданных: {self.owner} ({where})")
        result.append(f"Элементов: {sum(self.kinds.values())} - " + ", ".join(
            f"{kind} {count}" for kind, count in self.kinds.most_common()))
        sources = [("element", "свой"), ("attribute", "реквизит формы"), ("metadata", "метаданные"), ("name", "по имени")]
        result.append("Заголовки полей: " + ", ".join(f"{label} {self.titles[key]}" for key, label in sources))
        if self.pictures[1]:
            result.append(f"Общие картинки: из исходников {self.pictures[0]} из {self.pictures[1]}")
        if self.std_pictures:
            result.append(f"Стандартные картинки: из выгрузки {self.std_pictures[0]} из {self.std_pictures[1]}")
        if self.styles[1]:
            result.append(f"Цвета стиля: со значением {self.styles[0]} из {self.styles[1]}")
        if self.user_hidden:
            names = self.user_hidden
            result.append(f"Скрыты видимостью пользователя: {len(names)} - " + ", ".join(names[:8]) + (" ..." if len(names) > 8 else ""))
        if self.stubs:
            result.append("Заглушки: " + ", ".join(f"{kind} {count}" for kind, count in self.stubs.most_common()))
        if self.skipped:
            result.append("Не рисуются: " + ", ".join(f"{kind} {count}" for kind, count in self.skipped.most_common()))
        if self.missing:
            result.append("Нет в метаданных: " + ", ".join(sorted(set(self.missing))[:10]) +
                          (" ..." if len(set(self.missing)) > 10 else ""))
        if self.unknown or self.misplaced:
            for kind, names in sorted(self.unknown.items()):
                result.append(f"Не распознано: {kind} - {', '.join(names[:5])}" + (" ..." if len(names) > 5 else ""))
            for kind, names in sorted(self.misplaced.items()):
                result.append(f"Не на своем месте: {kind} - {', '.join(names[:5])}" + (" ..." if len(names) > 5 else ""))
        else:
            result.append("Не распознано: нет")
        return result

    @property
    def unrecognized(self) -> int:
        return sum(len(names) for names in self.unknown.values()) + sum(len(names) for names in self.misplaced.values())


def import_form(path: Path, std_pictures: Path | None = None, metadata: Metadata | None = None):
    """Модель и отчет по `Form.form` или `Form.xml`; `std_pictures` - выгрузка стандартных картинок
    платформы (каталог или zip), не указана - архив инструмента. `metadata` - метаданные исходников, выбранных у
    папки (конфигурация с расширениями); не указаны - исходники, в которых лежит форма."""
    try:
        root = ET.parse(long_path(path)).getroot()
    except FileNotFoundError:
        raise ImportFailure(f"файл не найден: {path}")
    except ET.ParseError as error:
        raise ImportFailure(f"{path}: не XML - {error}")
    if root.tag == EDT_FORM:
        raw, edt, name = import_edt.read(root), True, "EDT Form.form"
    elif root.tag == DESIGNER_FORM:
        raw, edt, name = import_designer.read(root), False, "выгрузка конфигуратора Form.xml"
    else:
        raise ImportFailure(f"{path}: не форма 1С - корневой элемент {root.tag}, "
                            f"ожидается form:Form (EDT) или Form в {DESIGNER_FORM[1:].split('}')[0]}")
    report = Report(path, name)
    builder = Builder(raw, path, edt, report, std_pictures, metadata)
    return builder.model(), report


class Builder:
    def __init__(self, raw: FormRaw, path: Path, edt: bool, report: Report, std_pictures: Path | None = None,
                 metadata: Metadata | None = None):
        self.raw = raw
        self.report = report
        self.path = path
        self.std_pictures = std_pictures or (pictures.BUNDLED if pictures.BUNDLED.is_file() else None)
        src, kind, name, form_name = locate(path, edt)
        self.metadata = metadata if metadata is not None else Metadata(src, edt)
        self.form_name = form_name
        self.owner = None
        if kind == "CommonForm":
            self.owner = self.metadata.object("CommonForm", form_name)
            report.owner = f"CommonForm.{form_name}"
        elif kind:
            self.owner = self.metadata.object(kind, name)
            report.owner = f"{kind}.{name}"
        report.owner_path = self.owner.path if self.owner else None
        self.form_kind = self.detect_kind()
        report.form_kind = self.form_kind
        self.names = set()
        self.auto_commands = set()
        self.placed = set()           # команды явных кнопок текущей панели: источник их не дублирует
        self.in_table = False         # родитель - таблица или группа колонок
        self.table_paths = {}
        self.table_excluded = {}
        self.table_flags = {}         # таблица → (изменять состав строк, изменять порядок строк)
        self.spreadsheets = set()     # поля табличного документа: свои стандартные команды
        self.collect_tables(raw.items)
        self.has_default = has_default(raw.items) or (raw.bar is not None and has_default(raw.bar.items))
        # Группа глобальных команд в форме есть - они идут в нее, нет - в группу «источник: Форма»
        self.global_group = has_source(raw.items, "FormCommandPanelGlobalCommands") or (
            raw.bar is not None and has_source(raw.bar.items, "FormCommandPanelGlobalCommands"))

    def collect_tables(self, items: list):
        """Пути данных таблиц: поле `Items.Таблица.CurrentData.Колонка` берет заголовок колонки."""
        for raw in items:
            if raw.kind == "SpreadsheetDocumentField":
                self.spreadsheets.add(raw.name)
            if raw.kind == "Table" and raw.props.get("dataPath"):
                self.table_paths[raw.name] = raw.props["dataPath"]
            if raw.kind == "Table":
                self.table_excluded[raw.name] = raw.props.get("excluded") or set()
                self.table_flags[raw.name] = (raw.props.get("changeRowSet", True) is not False,
                                              raw.props.get("changeRowOrder", True) is not False)
            self.collect_tables(raw.items)

    # Форма

    def model(self) -> dict:
        raw = self.raw
        form = {"title": self.form_title(), "formKind": self.form_kind}
        if raw.width:
            form["width"] = raw.width
        if raw.height:
            form["height"] = raw.height
        if raw.group not in ("Vertical", "Auto", "AutoScreenTypeSensitive"):
            form["group"] = raw.group
        if raw.command_bar_location != "Auto":
            form["commandBarLocation"] = raw.command_bar_location
        for key, value in (("autoTitle", raw.auto_title), ("showTitle", raw.show_title), ("showCloseButton", raw.show_close)):
            if value is False:
                form[key] = False
        if raw.excluded:
            form["excludedCommands"] = sorted(raw.excluded)
        if raw.bar is not None:
            bar = self.command_bar(raw.bar, "Form")
            if bar:
                form["commandBar"] = bar
        form["items"] = self.children(raw.items, "body")
        if self.metadata.has_help(self.owner.path if self.owner else None, self.path):
            form["help"] = True
        found, types = self.form_attributes(form)
        self.report.missing = self.metadata.missing
        model = {"version": 1, "form": form}
        if found:
            model["attributes"] = found
        commands = self.form_commands()
        if commands:
            model["commands"] = commands
        if types:
            model["types"] = types
        # Картинки элементов и команд формы
        used = pictures.referencing({"form": form, "commands": commands})
        names = sorted(pictures.used(used, set()))
        found = {name: layered_picture(self.metadata, name) for name in names}
        self.report.pictures = (sum(1 for uri in found.values() if uri), len(names))
        if self.std_pictures:
            # Стандартные картинки элементов и те, что рендерер рисует сам (кнопки поля, таблиц)
            self.report.std_pictures = pictures.add_std(found, used, self.std_pictures)
        if any(found.values()):
            model["pictures"] = {name: uri for name, uri in found.items() if uri}
        # Цвета стиля - именами в форме, значения для рисования - в `styles`
        used = colors.used_styles(form, set())
        values = layered_styles(self.metadata, used)
        self.report.styles = (sum(1 for name in used if name in values), len(used))
        if values:
            model["styles"] = values
        return model

    def form_commands(self) -> list:
        """Команды формы в порядке XML: заданное - имя, заголовок, подсказка, обработчик, картинка,
        отображение (не «Авто»)."""
        result = []
        for name, command in self.raw.commands.items():
            node = {"name": name}
            for key in ("title", "toolTip", "action", "picture", "representation"):
                if command.get(key):
                    node[key] = command[key]
            result.append(node)
        return result

    def form_attributes(self, form: dict):
        """Реквизиты формы и состав типов: объекты реквизитов формы (основной реквизит), основные таблицы
        списков и типы по путям элементов. Прочие ссылки в дереве конструктора - листья: путь набирается строкой,
        тип описывается в окне выбора. Ссылки реквизитов формы не описываются: состав типов БП - в разы больше формы."""
        raw = self.raw
        found = [attributes.entry(item, item.name == raw.main_attribute) for item in raw.attributes.values()]
        paths = attributes.Paths(found, {}, self.describe_type if self.metadata.src else None)
        for item in found:
            for node in [item] + item.get("columns", []):
                for name in attributes.type_names(node):
                    key = attributes.type_key(name)
                    if key and not attributes.is_ref(name):
                        paths.type_of(key)
            if item.get("mainTable"):
                paths.type_of(item["mainTable"])
        for node, _, _ in walk(form, ("form",)):
            path = node.get("dataPath")
            if found and isinstance(path, str) and not path.startswith("Items."):
                paths.walk(path)
        return found, {key: paths.types[key] for key in sorted(paths.types)}

    def describe_type(self, key: str):
        return describe_type(self.metadata, key)

    def detect_kind(self) -> str:
        main = self.raw.attributes.get(self.raw.main_attribute or "")
        types = main.types if main else []
        for text in types:
            if text.split(":")[-1] == "DynamicList":
                forms = self.owner.forms if self.owner else {}
                choice = {forms.get("defaultChoiceForm"), forms.get("auxiliaryChoiceForm")}
                return "ChoiceForm" if self.form_name in choice or "Выбор" in self.form_name else "ListForm"
            parsed = parse_type(text)
            if not parsed:
                continue
            kind, role, _ = parsed
            if role == "Object" and kind == "Document":
                return "DocumentObjectForm"
            if role == "Object" and kind in OBJECT_FORMS or role == "RecordManager":
                return "CatalogObjectForm"
        return "DataProcessorForm"

    def form_title(self) -> str:
        if self.raw.title:
            return self.raw.title
        owner = self.owner
        if owner:
            if self.form_kind in ("DocumentObjectForm", "CatalogObjectForm") and owner.object_presentation:
                return owner.object_presentation
            if self.form_kind in ("ListForm", "ChoiceForm") and owner.list_presentation:
                return owner.list_presentation
            return owner.caption
        return split_name(self.form_name)

    # Элементы

    def children(self, items: list, place: str) -> list:
        result = []
        for raw in items:
            node = self.item(raw, place)
            if node is not None:
                result.append(node)
        return result

    def item(self, raw: Raw, place: str):
        if raw.kind == "skip":
            self.report.skipped[raw.source] += 1
            return None
        name = self.unique(raw.name)
        if raw.kind == "?":
            self.report.unknown.setdefault(raw.source, []).append(name)
            return self.unknown(raw, name)
        if raw.kind not in PLACES[place]:
            self.report.misplaced.setdefault(f"{raw.kind} ({place})", []).append(name)
            return self.unknown(raw, name)
        location = self.button_location(raw) if raw.kind == "Button" else None
        # Среди элементов формы (не в панели) кнопка «только в Еще» не рисуется вовсе
        if location == "skip" or (location == "InAdditionalSubmenu" and place != "commands"):
            return None
        self.report.kinds[raw.kind] += 1
        if raw.kind in STUBS - DRAWN:
            self.report.stubs[raw.kind] += 1
        node = {"type": raw.kind, "name": name}
        if location and place == "commands":
            node["locationInCommandBar"] = location
        build = getattr(self, "build_" + raw.kind, None)
        if raw.kind in FIELDS:
            self.data_item(raw, node)
        if build:
            build(raw, node)
        self.common(raw, node)
        if place == "columns" and raw.kind in FIELDS and raw.props.get("showInHeader") is False:
            # Колонка без заголовка в шапке таблицы («Отображать в шапке» = Ложь)
            node["showInHeader"] = False
        if place == "columns" and raw.props.get("headerPicture"):
            node["headerPicture"] = raw.props["headerPicture"]
        if place == "columns" and raw.props.get("fixingInTable") in ("Left", "Right"):
            # Закрепленная колонка стоит на месте при прокрутке таблицы
            node["fixingInTable"] = raw.props["fixingInTable"]
        if place == "columns" and raw.kind in COLUMN_FIELDS:
            self.column(raw, node)
        if raw.kind == "CommandBar":
            self.placed = placed_commands(raw)
        if raw.kind in CHILD_PLACE:
            outer = self.in_table
            # Колонка таблицы: многострочный режим реквизита ячейку не меняет
            self.in_table = raw.kind in ("Table", "ColumnGroup")
            try:
                filled = self.source_commands(raw)
                explicit = self.children(raw.items, CHILD_PLACE[raw.kind])
            finally:
                self.in_table = outer
            # Заполненные платформой - перед явными, и в группе глобальных команд: документы БП - «Создать на
            # основании» первым (В-4), контрагент - явные «Присоединенные файлы» последними (Г-15)
            items = filled + explicit
            if raw.kind == "ButtonGroup" and not items:
                return None
            node["items"] = items
        return node

    def unique(self, name: str) -> str:
        """Имя элемента: пустое или повтор (имена пропущенных элементов не занимают) - с номером."""
        base = name or "Элемент"
        result, number = base, 1
        while result in self.names:
            number += 1
            result = f"{base}{number}"
        self.names.add(result)
        return result

    def unknown(self, raw: Raw, name: str) -> dict:
        node = {"type": "Unknown", "name": name, "sourceType": raw.source}
        title = raw.props.get("title")
        if title:
            node["title"] = title
        self.common(raw, node)
        return node

    def common(self, raw: Raw, node: dict):
        props = raw.props
        if props.get("groupHorizontalAlign") in ("Left", "Center", "Right"):
            node["groupHorizontalAlign"] = props["groupHorizontalAlign"]
        if props.get("groupVerticalAlign") in ("Top", "Center", "Bottom"):
            node["groupVerticalAlign"] = props["groupVerticalAlign"]
        if raw.kind in ("LabelDecoration", "LabelField"):
            color = colors.resolve(props.get("textColor"))
            if color:
                node["textColor"] = color
        if raw.kind in FIELDS:
            color = colors.resolve(props.get("titleTextColor"))
            if color:
                node["titleTextColor"] = color
        if raw.kind == "LabelDecoration":
            color = colors.resolve(props.get("backColor"))
            if color:
                node["backColor"] = color
        if props.get("visible") is False:
            node["visible"] = False
        if props.get("userVisible") is False:
            # Снята «Видимость пользователя»: 1С скрывает до «Изменить форму», конфигуратор показывает
            node["userVisible"] = False
            self.report.user_hidden.append(node.get("name", raw.name))
        if props.get("enabled") is False:
            node["enabled"] = False
        for key in ("width", "height"):
            if props.get(key):
                node[key] = props[key]
        for key in ("horizontalStretch", "verticalStretch"):
            # Таблица растягивается и так: в модель - только отказ
            if props.get(key) is not None and not (raw.kind == "Table" and props[key]):
                node[key] = props[key]
        tip = props.get("toolTip")
        if not tip and raw.kind in FIELDS and props.get("dataPath"):
            # Поле без своей подсказки показывает подсказку реквизита (снимки 1С: «?» у полей)
            found, _ = self.resolve(props["dataPath"])
            tip = getattr(found, "tool_tip", None)
        # Подсказка группы и декорации - для «?» при отображении «Кнопка» (Г-12 БП: «Договор закрыт ?»)
        if tip and raw.kind in FIELDS | {"Button", "UsualGroup", "LabelDecoration", "PictureDecoration"}:
            node["toolTip"] = tip
        extended = props.get("extendedTooltip")
        if extended and props.get("extendedTooltipFormatted"):
            extended = MARKUP.sub("", extended)
        if extended and extended.strip():
            node["extendedTooltip"] = extended
            # Цвет текста подсказки (договор БП: «Договор закрыт» справа от флажка - цвет текста формы, не серый)
            color = colors.resolve(props.get("extendedTooltipTextColor"))
            if color:
                node["extendedTooltipTextColor"] = color
        if props.get("toolTipRepresentation") not in (None, "Auto"):
            node["toolTipRepresentation"] = props["toolTipRepresentation"]

    def data_item(self, raw: Raw, node: dict):
        props = raw.props
        title, types = self.field_title(raw)
        node["title"] = title
        if props.get("dataPath"):
            node["dataPath"] = props["dataPath"]
        if props.get("titleLocation") not in (None, "Auto"):
            node["titleLocation"] = props["titleLocation"]
        # Высота заголовка 1 - как не задана
        if (props.get("titleHeight") or 0) > 1:
            node["titleHeight"] = props["titleHeight"]
        if props.get("readOnly"):
            node["readOnly"] = True
        if raw.kind == "InputField":
            expanded = self.metadata.expand_types(types)
            node["dataType"] = simple_type(expanded) or "string"
            # Составной тип со ссылкой и характеристика - только кнопка выбора «…», без списка и открытия
            # (Г-6 БП: «Плательщик» - Контрагенты и ФизическиеЛица, «Документ» сделки, «Субконто Кт1..3»)
            names = [re.sub(r"^(cfg|d\d+p\d+):", "", item.strip()) for item in expanded]
            characteristic = any(name.startswith("Characteristic.") for name in names)
            # Ссылка любого объекта вида (`DocumentRef`, `AnyRef`) - тоже составной: «Документ» однострочного поступления
            any_ref = any(name.endswith("Ref") and "." not in name for name in names)
            # Ссылка, представленная кодом, - шириной по длине кода (Г-7 БП: счета плана счетов, код 8 символов)
            if len(names) == 1 and node["dataType"] == "ref":
                parsed = parse_type(names[0])
                owner = self.metadata.object(parsed[0], parsed[2]) if parsed else None
                if owner is not None and owner.as_code:
                    code = owner.standard_qualifiers["Code"]
                    node["length"] = code.get("length") or code.get("digits")
            if characteristic or any_ref or (len(names) > 1 and node["dataType"] == "ref"):
                node["dataType"] = "ref"
                for key, value in (("choiceButton", True), ("dropListButton", False), ("openButton", False)):
                    if props.get(key) is None:
                        props[key] = value
            # Квалификаторы типа: ширина поля «по типу» (руководство разработчика 7.7.13.3)
            found, _ = self.resolve(props.get("dataPath") or "")
            qualifiers = getattr(found, "qualifiers", None) or {}
            keys = {"string": ("length",), "number": ("digits", "fractionDigits"), "date": ("dateFractions",)}.get(node["dataType"], ())
            for key in keys:
                # Состав даты «Дата и время» - умолчание модели: не пишется
                if key in qualifiers and qualifiers[key] != "DateTime":
                    node[key] = qualifiers[key]
            # Тип - одно перечисление: его значения для выпадающего списка макета
            values = self.enum_values(self.metadata.expand_types(types))
            if values:
                node["enumValues"] = values

    def enum_values(self, types: list):
        """Синонимы значений перечисления, если тип поля - ровно одно перечисление."""
        if len(types) != 1:
            return None
        parsed = parse_type(types[0])
        if not parsed or parsed[0] != "Enum":
            return None
        owner = self.metadata.object("Enum", parsed[2])
        if not owner or not owner.values:
            return None
        return [synonym or split_name(name) for name, synonym in owner.values.items()]

    def field_title(self, raw: Raw):
        """Заголовок и типы поля по цепочке; источник - в отчет."""
        title = raw.props.get("title")
        path = raw.props.get("dataPath") or ""
        found, source = self.resolve(path) if path else (None, None)
        types = found.types if found else []
        if title is not None:
            self.report.titles["element"] += 1
            return title, types
        if found and found.title:
            self.report.titles[source] += 1
            return found.title, types
        self.report.titles["name"] += 1
        last = path.split(".")[-1] if path else raw.name
        return split_name(last), types

    def resolve(self, path: str):
        """Реквизит по пути данных: (Attribute, "attribute" | "metadata") или (None, None)."""
        segments = path.split(".")
        if len(segments) > 3 and segments[0] == "Items" and segments[2] == "CurrentData":
            table = self.table_paths.get(segments[1])
            return self.resolve(".".join([table] + segments[3:])) if table else (None, None)
        attribute = self.raw.attributes.get(segments[0])
        if attribute is None:
            return None, None
        if len(segments) == 1:
            return attribute, "attribute"
        rest = segments[1:]
        if rest[0] in attribute.columns:
            column = attribute.columns[rest[0]]
            if len(rest) == 1:
                return column, "attribute"
            return self.walk(self.object_of(column), rest[1:]), "metadata"
        return self.walk(self.object_of(attribute), rest), "metadata"

    def object_of(self, attribute: Attribute):
        if attribute.main_table:
            return self.metadata.by_full_name(attribute.main_table)
        for text in attribute.types:
            parsed = parse_type(text)
            if parsed and parsed[0] not in ("Enum",):
                found = self.metadata.object(parsed[0], parsed[2])
                if found:
                    return found
        return None

    def walk(self, obj, segments: list):
        index = 0
        while obj is not None and index < len(segments):
            segment = segments[index]
            last = index == len(segments) - 1
            if segment in obj.tabular:
                section = obj.tabular[segment]
                if last:
                    return section
                column = section.columns.get(segments[index + 1])
                if column is None and segments[index + 1] in ("LineNumber", "НомерСтроки"):
                    column = Attribute("LineNumber", "N", ["Number"])
                if column is None or index + 1 == len(segments) - 1:
                    return column
                obj = self.object_of(column)
                index += 2
                continue
            found = obj.field(segment)
            if found is None or last:
                return found
            obj = self.object_of(found)
            index += 1
        return None

    # Виды

    def build_UsualGroup(self, raw: Raw, node: dict):
        props = raw.props
        self.group_title(raw, node)
        if props["group"] not in ("Vertical", "Auto", "AutoScreenTypeSensitive"):
            node["group"] = props["group"]
        if props["representation"] != "None":
            node["representation"] = props["representation"]
        if props["behavior"] not in ("Usual", "Auto"):
            node["behavior"] = props["behavior"]
            if props["collapsed"]:
                node["collapsed"] = True
            if props.get("controlRepresentation") == "Picture":
                node["controlRepresentation"] = "Picture"
        if props["throughAlign"] == "DontUse":
            node["throughAlign"] = "DontUse"
        if props["childItemsHorizontalAlign"] not in (None, "Auto"):
            node["childItemsHorizontalAlign"] = props["childItemsHorizontalAlign"]
        if props.get("childItemsVerticalAlign") in ("Top", "Center", "Bottom"):
            node["childItemsVerticalAlign"] = props["childItemsVerticalAlign"]
        color = colors.resolve(props.get("backColor"))
        if color:
            node["backColor"] = color
        color = colors.resolve(props.get("titleTextColor"))
        if color:
            node["titleTextColor"] = color

    def group_title(self, raw: Raw, node: dict):
        if raw.props.get("title") is not None:
            node["title"] = raw.props["title"]
        if raw.props.get("showTitle") is False:
            node["showTitle"] = False

    def build_Pages(self, raw: Raw, node: dict):
        if raw.props.get("title") is not None:
            node["title"] = raw.props["title"]
        if raw.props["pagesRepresentation"] != "Auto":
            node["pagesRepresentation"] = raw.props["pagesRepresentation"]

    def build_Page(self, raw: Raw, node: dict):
        if raw.props.get("title") is not None:
            node["title"] = raw.props["title"]
        if raw.props.get("picture"):
            node["picture"] = raw.props["picture"]
        if raw.props["group"] not in ("Vertical", "Auto", "AutoScreenTypeSensitive"):
            node["group"] = raw.props["group"]

    def build_ColumnGroup(self, raw: Raw, node: dict):
        props = raw.props
        node["group"] = props["group"]
        # Полоса заголовка над колонками - только при «Отображать заголовок»
        if props.get("title") is not None and props.get("showTitle"):
            node["title"] = props["title"]
        if props.get("showInHeader"):
            node["showInHeader"] = True
        if props.get("headerHorizontalAlign") in ("Center", "Right"):
            node["headerHorizontalAlign"] = props["headerHorizontalAlign"]

    def build_CommandBar(self, raw: Raw, node: dict):
        if raw.props.get("horizontalAlign") in ("Center", "Right"):
            node["horizontalAlign"] = raw.props["horizontalAlign"]
        self.command_source(raw, node)

    def build_Addition(self, raw: Raw, node: dict):
        node["additionType"] = raw.props.get("additionType") or "SearchStringAddition"
        if raw.props.get("source"):
            node["additionSource"] = raw.props["source"]

    def build_ButtonGroup(self, raw: Raw, node: dict):
        if raw.props.get("title") is not None:
            node["title"] = raw.props["title"]
        if raw.props.get("representation") in ("Usual", "Compact"):
            node["representation"] = raw.props["representation"]
        self.command_source(raw, node)

    def command_source(self, raw: Raw, node: dict):
        # Кнопки источника импорт кладет явно; сам источник «Форма» дает панели «Еще» и «?»
        if raw.props.get("commandSource"):
            node["commandSource"] = raw.props["commandSource"]

    def build_Popup(self, raw: Raw, node: dict):
        props = raw.props
        node["title"] = props.get("title") or split_name(raw.name)
        if props.get("picture"):
            node["picture"] = props["picture"]
        if props.get("representation") not in (None, "Auto"):
            node["representation"] = props["representation"]
        self.command_source(raw, node)

    def build_InputField(self, raw: Raw, node: dict):
        props = raw.props
        if props.get("autoMaxWidth") is False:
            node["autoMaxWidth"] = False
        # «Многострочный режим» Авто - режим реквизита в метаданных («Комментарий» ЗЕРНО БП - многострочный
        # реквизит; «Комментарий» «Увольнения» - нет)
        if props.get("multiLine") is None and not self.in_table:
            found, _ = self.resolve(props.get("dataPath") or "")
            if getattr(found, "multi_line", False):
                props["multiLine"] = True
        if props.get("maxWidth"):
            node["maxWidth"] = props["maxWidth"]
        # Предел высоты многострочного поля: снятое «авто» и максимум - как у надписи; у колонки таблицы
        # свойства нет (панель его там не показывает)
        if not self.in_table:
            self.field_look(raw, node, ("autoMaxHeight", "maxHeight"))
        # «Режим выбора из списка» (только «▾», снимок «Формирование партий ЗЕРНО» БП) и «Отображение кнопки
        # выбора» («▾» вместо «…», Ф-4 БП) - свойствами модели: кнопки из них выводит рендерер
        if props.get("listChoiceMode"):
            node["listChoiceMode"] = True
        if props.get("choiceButtonRepresentation") not in (None, "Auto"):
            node["choiceButtonRepresentation"] = props["choiceButtonRepresentation"]
        if props.get("createButton") is not None:
            node["createButton"] = props["createButton"]
        if props.get("choiceButtonPicture"):
            node["choiceButtonPicture"] = props["choiceButtonPicture"]
        # Фон поля (снимок «Формирование партий ЗЕРНО» БП: «Операция», «Вид продукции» - стиль конфигурации)
        for key in ("backColor", "textColor", "borderColor"):
            color = colors.resolve(props.get(key))
            if color:
                node[key] = color
        for key in ("font", "titleFont"):
            if props.get(key):
                node[key] = props[key]
        for key in ("choiceButton", "clearButton", "openButton", "dropListButton", "multiLine"):
            if props.get(key) is not None:
                node[key] = props[key]
        # «Автоотметка незаполненного» задана - свойством модели; «Авто» - по проверке заполнения реквизита
        # (снимок «Увольнение»): отметка импорта `markIncomplete`
        mark = props.get("markIncomplete")
        if mark is not None:
            node["autoMarkIncomplete"] = mark
        elif not props.get("readOnly"):
            found, _ = self.resolve(props.get("dataPath") or "")
            if found and found.fill_check:
                node["markIncomplete"] = True
        for key in ("inputHint", "footerText"):
            if props.get(key):
                node[key] = props[key]
        # Формат: формат редактирования поля, иначе формат поля, иначе формат реквизита; от него пустое число
        # (Г-5 БП: «Сумма расходов» с «ЧДЦ=2» - «0,00», «в т.ч. НДС» без формата - «0»)
        form_format = props.get("format")
        if not form_format:
            found, _ = self.resolve(props.get("dataPath") or "")
            form_format = getattr(found, "format", None)
        if form_format and form_format.strip():
            node["format"] = form_format.strip()
        if props.get("choiceList"):
            node["choiceList"] = self.choice_list(props["choiceList"])

    def choice_list(self, entries: list) -> list:
        """Пункты списка выбора: значение так, как 1С показывает его без представления, - строкой;
        с представлением - `{value, presentation}`. Перечисление - синонимом из метаданных, предопределенный - именем
        по словам, булево - «Да» / «Нет» (Ложь EDT пишет пустым тегом), число и строка - как есть."""
        result = []
        for presentation, kind, text in entries:
            value = self.choice_value(kind, text)
            result.append({"value": value, "presentation": presentation}
                          if presentation and presentation != value else value)
        return result

    def choice_value(self, kind: str, text: str) -> str:
        if kind == "boolean":
            return "Да" if text == "true" else "Нет"
        if kind != "ref":
            return text
        found = ENUM_VALUE.match(text)
        if found:
            owner = self.metadata.object("Enum", found.group(1))
            synonym = owner.values.get(found.group(2)) if owner else None
            return synonym or split_name(found.group(2))
        return split_name(text.rsplit(".", 1)[-1])

    def build_CheckBoxField(self, raw: Raw, node: dict):
        if raw.props["checkBoxType"] != "Auto":
            node["checkBoxType"] = raw.props["checkBoxType"]
        self.field_look(raw, node, ("titleFont", "borderColor", "verticalAlign"))

    # Оформление полей надписи, флажка, картинки: свойства вида, отличные от умолчаний платформы;
    # рамка по умолчанию у поля картинки - одинарная (EDT пишет ее почти всегда), у надписи - без рамки
    def field_look(self, raw: Raw, node: dict, keys: tuple):
        props = raw.props
        for key in keys:
            value = props.get(key)
            if key == "border" and value == BORDER_DEFAULTS.get(raw.kind):
                value = None
            if key in ("borderColor", "backColor", "textColor"):
                value = colors.resolve(value)
            if key in ("horizontalAlign", "verticalAlign") and value == "Auto":
                value = None
            if key == "autoMaxHeight":
                value = False if value is False else None
            # Ложь - значение (снятое «авто»), ноль и пустое - нет
            if value is False or value not in (None, 0, ""):
                node[key] = value

    def build_PictureField(self, raw: Raw, node: dict):
        props = raw.props
        if props.get("valuesPicture"):
            node["valuesPicture"] = props["valuesPicture"]
        if props.get("hyperlink"):
            node["hyperlink"] = True
        if props.get("pictureSize"):
            node["pictureSize"] = props["pictureSize"]
        if props.get("autoMaxWidth") is False:
            node["autoMaxWidth"] = False
        self.field_look(raw, node, ("autoMaxHeight", "maxWidth", "maxHeight", "textColor", "borderColor", "border",
                                    "font", "titleFont"))

    def build_RadioButtonField(self, raw: Raw, node: dict):
        props = raw.props
        if props["radioButtonType"] != "Auto":
            node["radioButtonType"] = props["radioButtonType"]
        if props.get("columnsCount"):
            node["columnsCount"] = props["columnsCount"]
        if props.get("choiceList"):
            node["choiceList"] = self.choice_list(props["choiceList"])

    def build_LabelField(self, raw: Raw, node: dict):
        if raw.props.get("autoMaxWidth") is False:
            node["autoMaxWidth"] = False
        self.field_look(raw, node, ("autoMaxHeight", "maxWidth", "maxHeight", "horizontalAlign", "verticalAlign",
                                    "backColor", "borderColor", "border", "font", "titleFont"))
        if raw.props.get("hyperlink"):
            node["hyperlink"] = True
            # Рендерер рисует ссылку без примера текстом заголовка; заголовок не свой (из реквизита, часто
            # равен подсказке) на форме 1С не виден - ссылка пустая (владелец: «Склад / Контрагент» ЗЕРНО)
            if raw.props.get("title") is None:
                node["sample"] = ""
        if raw.props.get("footerText"):
            node["footerText"] = raw.props["footerText"]

    def build_Table(self, raw: Raw, node: dict):
        props = raw.props
        if props["representation"] != "List":
            node["representation"] = props["representation"]
        if not props["header"]:
            node["header"] = False
        if props["footer"]:
            node["footer"] = True
        if props.get("heightInTableRows"):
            node["heightInTableRows"] = props["heightInTableRows"]
        if props["commandBarLocation"] != "Auto":
            node["commandBarLocation"] = props["commandBarLocation"]
        if props.get("searchStringLocation", "Auto") != "Auto":
            node["searchStringLocation"] = props["searchStringLocation"]
        for key in ("changeRowSet", "changeRowOrder", "horizontalLines", "verticalLines"):
            if props.get(key) is False:
                node[key] = False
        for key in ("multipleChoice", "useAlternationRowColor"):
            if props.get(key):
                node[key] = True
        for key in ("viewStatusLocation", "searchControlLocation"):
            if props.get(key, "Auto") != "Auto":
                node[key] = props[key]
        for key in ("rowPictureDataPath", "rowsPicture", "font", "titleFont"):
            if props.get(key):
                node[key] = props[key]
        for key in ("backColor", "textColor", "borderColor"):
            color = colors.resolve(props.get(key))
            if color:
                node[key] = color
        # Снятые в «Составе команд» стандартные команды таблицы: их нет на панели и в «Еще»
        # `ShowRowRearrangement` - стрелки перемещения строк на панели
        known = ({command for section in MORE_TABLE for command in section} | set(SOURCE_LIST) |
                 {"Choose", "Create", "ShowRowRearrangement"})
        excluded = sorted(set(props.get("excluded") or ()) & known)
        if excluded:
            node["excludedCommands"] = excluded
        if raw.bar is not None and props["commandBarLocation"] != "None":
            bar = self.command_bar(raw.bar, f"Item.{raw.name}")
            if bar:
                node["commandBar"] = bar

    def build_LabelDecoration(self, raw: Raw, node: dict):
        node["title"] = raw.props.get("title") or ""
        if raw.props.get("formatted"):
            node["formatted"] = True
            if isinstance(node["title"], str):
                node["title"] = colors.formatted(node["title"], self.metadata.src, self.metadata.edt)
        if raw.props.get("hyperlink"):
            node["hyperlink"] = True

    def build_PictureDecoration(self, raw: Raw, node: dict):
        if raw.props.get("title"):
            node["title"] = raw.props["title"]
        if raw.props.get("picture"):
            node["picture"] = raw.props["picture"]
        if raw.props.get("hyperlink"):
            node["hyperlink"] = True

    def column(self, raw: Raw, node: dict):
        """Свойства колонки таблицы, только не умолчания. Положение в шапке - только «Центр» и «Право»:
        «Лево» и «Авто» в шапке рисуются одинаково, а EDT пишет «Лево» у каждого поля."""
        props = raw.props
        if props.get("headerHorizontalAlign") in ("Center", "Right"):
            node["headerHorizontalAlign"] = props["headerHorizontalAlign"]
        if props.get("footerHorizontalAlign") in ("Left", "Center", "Right"):
            node["footerHorizontalAlign"] = props["footerHorizontalAlign"]
        if props.get("showInFooter") is False:
            node["showInFooter"] = False
        for key in ("headerBackColor", "footerBackColor", "footerTextColor"):
            color = colors.resolve(props.get(key))
            if color:
                node[key] = color
        for key in ("footerPicture", "footerFont"):
            if props.get(key):
                node[key] = props[key]
        for key in ("cellHyperlink", "autoCellHeight"):
            if props.get(key):
                node[key] = True

    def build_Button(self, raw: Raw, node: dict):
        props = raw.props
        command = props.get("commandName") or ""
        if not COMMAND_NAME.match(command):
            # Команда другой конфигурации в выгрузке - идентификаторами (`154:<uuid>`), в EDT - `0`
            command = ""
        if command.startswith("Form.Command.") and command.split(".")[-1] in self.raw.commands:
            self.form_command_button(raw, node, command)
            return
        title, picture, representation = self.command(command)
        node["title"] = props.get("title") or title or split_name(raw.name)
        if props.get("buttonType") in ("Hyperlink", "CommandBarHyperlink"):
            node["buttonType"] = props["buttonType"]
        if command:
            node["commandName"] = command
        # Представление «Авто» у кнопки - представление ее команды
        representation = props.get("representation") if props.get("representation") not in (None, "Auto") else representation
        standard = command.split(".")[-1] if ".StandardCommand." in "." + command else None
        if standard and standard not in ICON_COMMANDS and representation not in ("Picture", "PictureAndText"):
            # Стандартная команда при «Авто» в «Такси» - текстом: картинку не берем
            picture = None
        picture = props.get("picture") or picture
        # Значок стандартной команды таблицы рендерер берет сам, как у кнопки автозаполнения
        if picture and picture == table_command_picture(command):
            picture = None
        if picture:
            node["picture"] = picture
        if representation:
            node["representation"] = representation
        self.button_look(props, node)

    def form_command_button(self, raw: Raw, node: dict, command: str):
        """Кнопка команды формы: заголовок, картинка и отображение - только свои, отличные от команды;
        остальное рендерер берет из `commands` модели (заголовка нет и у команды - имя кнопки по словам)."""
        props = raw.props
        own = self.raw.commands[command.split(".")[-1]]
        title = props.get("title")
        if title and title != own.get("title"):
            node["title"] = title
        elif not title and not own.get("title") and node["name"] != raw.name:
            # Имя кнопки изменено при повторе - заголовок по исходному имени, как в 1С
            node["title"] = split_name(raw.name)
        if props.get("buttonType") in ("Hyperlink", "CommandBarHyperlink"):
            node["buttonType"] = props["buttonType"]
        node["commandName"] = command
        if props.get("picture") and props["picture"] != own.get("picture"):
            node["picture"] = props["picture"]
        # Отображение «Авто» у кнопки - отображение команды
        representation = props.get("representation")
        if representation not in (None, "Auto") and representation != (own.get("representation") or "Auto"):
            node["representation"] = representation
        self.button_look(props, node)

    def button_look(self, props: dict, node: dict):
        """Кнопка по умолчанию, пометка, шрифт, рамка и форма кнопки."""
        if props.get("defaultButton"):
            node["defaultButton"] = True
        # Пометка: в исходниках записана только установленная
        if props.get("check"):
            node["check"] = True
        # Начертание (по снимку 1С: жирные кнопки формы)
        if props.get("font"):
            node["font"] = props["font"]
        # Цвет рамки кнопки (по снимку 1С: рамка Web.SteelBlue)
        color = colors.resolve(props.get("borderColor"))
        if color:
            node["borderColor"] = color
        # Форма кнопки «Овальная» (по снимку 1С)
        if props.get("shape") == "Oval":
            node["shape"] = "Oval"

    # Команды

    def command(self, name: str):
        """Заголовок, картинка и представление команды по ее имени в кнопке."""
        parts = name.split(".")
        if "StandardCommand" in parts:
            standard = parts[-1]
            if len(parts) > 2 and parts[2] in self.spreadsheets and standard in SPREADSHEET_COMMANDS:
                return SPREADSHEET_COMMANDS[standard], None, "Picture" if standard in SPREADSHEET_ICONS else None
            return STANDARD_COMMANDS.get(standard), STANDARD_PICTURES.get(standard), None
        if name.startswith("Form.Command."):
            found = self.raw.commands.get(parts[-1], {})
            return found.get("title"), found.get("picture"), found.get("representation")
        if name.startswith("CommonCommand."):
            found = self.metadata.object("CommonCommand", parts[-1])
            return (found.synonym, found.picture, found.representation) if found else (None, None, None)
        if len(parts) == 4 and parts[2] == "Command":
            found = self.metadata.object(parts[0], parts[1])
            return (found.commands.get(parts[3]) or (None, None, None)) if found else (None, None, None)
        return None, None, None

    def form_command_kind(self) -> str:
        """Вид формы для стандартных команд: документ без проведения - как справочник, без «Провести»."""
        if self.form_kind == "DocumentObjectForm" and self.owner and not self.owner.posting:
            return "CatalogObjectForm"
        return self.form_kind

    def standard_commands(self, source: str):
        """Стандартные команды источника: (команды по порядку, префикс имени, исключенные)."""
        if source == "Form":
            return SOURCE_FORM.get(self.form_command_kind(), []), "Form.StandardCommand.", self.raw.excluded
        table = source[5:]
        # Источник - не таблица (поле табличного документа): его команды импорт не знает
        if table not in self.table_flags:
            return [], f"Form.Item.{table}.StandardCommand.", set()
        path = self.table_paths.get(table, "")
        if self.form_kind in ("ListForm", "ChoiceForm") and not path.startswith("Объект."):
            commands = (["Choose"] if self.form_kind == "ChoiceForm" else []) + SOURCE_LIST
        else:
            commands = [command for section in self.table_sections(table) for command in section]
        return commands, f"Form.Item.{table}.StandardCommand.", self.table_excluded.get(table, set())

    def table_sections(self, table: str) -> list:
        """Секции стандартных команд таблицы (не списка) по ее флагам изменения строк."""
        flags = self.table_flags.get(table, (True, True))
        return [[command for command in section
                 if (command not in ROW_SET or flags[0]) and (command not in ROW_ORDER or flags[1])]
                for section in MORE_TABLE]

    def source_commands(self, raw: Raw) -> list:
        """Кнопки, которыми платформа заполняет группу по источнику команд."""
        source = raw.props.get("commandSource") or ""
        if source == "Form":
            buttons = self.standard_buttons(raw.name, source)
            return buttons + ([] if self.global_group else self.global_commands(raw.name))
        if source.startswith("Item."):
            return self.standard_buttons(raw.name, source)
        if source == "FormCommandPanelGlobalCommands":
            return self.global_commands(raw.name)
        if source:
            self.report.skipped[f"команды {source}"] += 1
        return []

    def global_commands(self, owner: str) -> list:
        """Глобальные команды панели формы объекта: команды «Важное» (общие и команды объектов) кнопками,
        команды групп команд категории «Командная панель формы» - подменю группы (по снимку 1С:
        подменю группы команд обработки), подменю «Создать на основании» (объекты, вводимые
        на основании, и общие команды этой группы)."""
        if self.form_kind not in ("DocumentObjectForm", "CatalogObjectForm") or not self.owner:
            return []
        result, based, groups, indexes = [], [], {}, {}
        for command in self.metadata.form_commands(self.report.owner):
            full = command.full
            if full in self.placed:
                continue
            node = {"type": "Button", "name": self.unique(owner + command.name),
                    "title": command.synonym or split_name(command.name), "commandName": full}
            if command.picture:
                node["picture"] = command.picture
            if command.representation:
                node["representation"] = command.representation
            # Командный интерфейс формы переносит команду в другую группу, ставит место в группе и скрывает
            group, index, visible = self.raw.interface.get(full, (None, None, True))
            group = group or command.group
            if not visible:
                node["userVisible"] = False
            if group == "FormCommandBarImportant":
                result.append(node)
                if index is not None:
                    indexes[node["name"]] = index
            elif group == "FormCommandBarCreateBasedOn":
                based.append(node)
            elif (group or "").startswith("CommandGroup."):
                groups.setdefault(group, []).append(node)
        # Команды с индексом командного интерфейса - первыми по индексу, остальные - в порядке метаданных
        # (контрагент БП: «Досье» отчета впереди общих команд, Г-15)
        result.sort(key=lambda node: (node["name"] not in indexes, indexes.get(node["name"], 0)))
        for name in self.metadata.based_on(self.report.owner):
            target = self.metadata.by_full_name(name)
            title = (target.object_presentation or target.caption) if target else split_name(name.split(".")[-1])
            based.append({"type": "Button", "name": self.unique(owner + name.split(".")[-1]), "title": title})
        if based:
            result.append({"type": "Popup", "name": self.unique(owner + "СоздатьНаОсновании"),
                           "title": "Создать на основании", "items": based})
            self.report.kinds["Popup"] += 1
        for group, buttons in groups.items():
            found = self.metadata.object("CommandGroup", group.split(".", 1)[1])
            popup = {"type": "Popup", "name": self.unique(owner + group.split(".", 1)[1]),
                     "title": (found.synonym if found else None) or split_name(group.split(".", 1)[1])}
            if found and found.picture:
                popup["picture"] = found.picture
            if found and found.representation:
                popup["representation"] = found.representation
            if all(button.get("userVisible") is False for button in buttons):
                # Подменю без видимых команд в 1С:Предприятие не показывается
                popup["userVisible"] = False
            popup["items"] = buttons
            self.report.kinds["Popup"] += 1
            self.report.kinds["Button"] += len(buttons)
            result.append(popup)
        self.report.kinds["Button"] += sum(1 for node in result if node["type"] == "Button") + len(based)
        return result

    def standard_buttons(self, owner: str, source: str) -> list:
        """Кнопки стандартных команд источника, кроме исключенных и уже размещенных явно. У таблицы - весь
        набор меню «Еще»: команды «только в Еще» помечены положением, последняя секция - группой кнопок,
        чтобы меню отделило ее чертой."""
        commands, prefix, excluded = self.standard_commands(source)
        table = source[5:] if source.startswith("Item.") else None
        listed = table is not None and self.listed(table)
        result, tail = [], []
        for index, command in enumerate(commands):
            if prefix + command in self.placed or command in excluded:
                continue
            title = (FORM_TITLES.get(command) if source == "Form" else None) or STANDARD_COMMANDS[command]
            node = {"type": "Button", "name": self.unique(owner + command), "title": title,
                    "commandName": prefix + command}
            # Картинка - только у кнопок-значков: при «Авто» картинка на панели заменила бы текст; пункт
            # меню «Еще» рендерер рисует со стандартной картинкой команды сам
            if command in ICON_COMMANDS:
                node["picture"] = STANDARD_PICTURES[command]
                node["representation"] = "Picture"
            if index == 0 and (source == "Form" or command in ("Create", "Choose")) and not self.has_default:
                # Кнопка по умолчанию у формы одна: явная (`defaultButton` в XML) важнее стандартной
                node["defaultButton"] = True
            if self.more_only(prefix + command, None, listed):
                node["locationInCommandBar"] = "InAdditionalSubmenu"
            self.report.kinds["Button"] += 1
            (tail if table and not listed and command in MORE_TABLE[-1] else result).append(node)
        result = self.join_move_buttons(owner, result)
        if tail:
            result.append({"type": "ButtonGroup", "name": self.unique(owner + "Список"), "items": tail})
            self.report.kinds["ButtonGroup"] += 1
        return result

    def listed(self, table: str) -> bool:
        """Таблица - динамический список формы списка или выбора (не табличная часть объекта)."""
        return self.form_kind in ("ListForm", "ChoiceForm") and not self.table_paths.get(table, "").startswith("Объект.")

    def join_move_buttons(self, owner: str, buttons: list) -> list:
        """«Вверх» и «Вниз» источника платформа ставит вплотную - компактной группой."""
        names = [button["commandName"].split(".")[-1] for button in buttons]
        for index in range(len(names) - 1):
            if names[index] == "MoveUp" and names[index + 1] == "MoveDown":
                group = {"type": "ButtonGroup", "name": self.unique(owner + "Перемещение"),
                         "representation": "Compact", "items": buttons[index:index + 2]}
                self.report.kinds["ButtonGroup"] += 1
                return buttons[:index] + [group] + buttons[index + 2:]
        return buttons

    def button_location(self, raw: Raw):
        """Положение кнопки в панели: "skip" - кнопки нет совсем (без команды, дубль автозаполнения),
        `InAdditionalSubmenu` - только в меню «Еще», `InCommandBar` - только на панели, None - и там, и там."""
        props = raw.props
        location = props.get("locationInCommandBar")
        command = props.get("commandName") or ""
        # Кнопка без команды в 1С не показывается (по снимку 1С)
        if not command:
            return "skip"
        standard = command.split(".")[-1] if ".StandardCommand." in "." + command else None
        if standard in self.auto_commands:
            return "skip"
        if location in ("InAdditionalSubmenu", "InCommandBar"):
            return location
        table = command.split(".")[2] if command.startswith("Form.Item.") else None
        if self.more_only(command, props.get("representation"), table is not None and self.listed(table)):
            return "InAdditionalSubmenu"
        return None

    @staticmethod
    def more_only(command: str, representation, listed: bool) -> bool:
        """Стандартная команда, которую 1С при положении «Авто» держит только в меню «Еще»."""
        standard = command.split(".")[-1] if ".StandardCommand." in "." + command else None
        if standard in MORE_ONLY:
            return True
        if command.startswith("Form.Item.") and standard in MORE_ONLY_TABLE and representation in (None, "Auto") \
                and not listed:
            return True
        # Команды формы объекта, которые 1С держит в «Еще» (снимок «Формирование партий ЗЕРНО» БП);
        # у таблиц и списков те же команды - кнопками (`Form.Item.<Таблица>.StandardCommand.*`)
        return command.startswith("Form.StandardCommand.") and standard in MORE_ONLY_FORM

    def command_bar(self, raw: Raw, source: str):
        """Автоматическая командная панель формы (`source` - "Form") или таблицы (`Item.<Имя>`).

        Автозаполнение рисует рендерер по виду формы; если часть его команд исключена,
        стандартные кнопки переносятся в модель явно, а автозаполнение выключается.
        """
        node = {"type": "AutoCommandBar", "name": self.unique(raw.name)}
        auto = bool(raw.props.get("autoFill"))
        commands, _, excluded = self.standard_commands(source)
        # Рендерер рисует автозаполнение по виду формы: у документа без проведения набор другой - явно
        # У таблицы исключенные команды рендерер знает сам (`excludedCommands` таблицы)
        # Исключенная команда «только в Еще» панель не меняет: меню рендерер собирает сам
        explicit = auto and source == "Form" and (bool(excluded & (set(commands) - set(FORM_MORE)))
                                                  or self.form_command_kind() != self.form_kind)
        if not auto or explicit:
            node["autoFill"] = False
        if raw.props.get("horizontalAlign") in ("Center", "Right"):
            node["horizontalAlign"] = raw.props["horizontalAlign"]
        self.placed = placed_commands(raw)
        self.auto_commands = set(commands) if auto and not explicit else set()
        try:
            standard = self.standard_buttons(raw.name, source) if explicit else []
            node["items"] = standard + self.children(raw.items, "commands")
        finally:
            self.auto_commands = set()
        return node


def describe_type(metadata: Metadata, key: str):
    """Состав типа `Catalog.Имя` для `types` модели: реквизиты, общие реквизиты, табличные части; объекта нет - None."""
    kind, _, name = key.partition(".")
    found = metadata.object(kind, name)
    return attributes.describe(found, metadata.common_attributes(key)) if found is not None else None


def layered_picture(metadata: Metadata, name: str):
    """Общая картинка из исходников: у конфигурации с расширениями - сначала расширения (свои важнее)."""
    for layer in reversed(metadata.layers):
        uri = pictures.load(layer.src, layer.edt, name)
        if uri:
            return uri
    return None


def layered_styles(metadata: Metadata, used: set) -> dict:
    """Значения цветов стиля: конфигурации и платформы, элементы стиля расширений - поверх."""
    first, *extensions = metadata.layers
    values = colors.styles(first.src, first.edt, used)
    for layer in extensions:
        if not layer.src:
            continue
        table = colors.Styles.of(layer.src, layer.edt)
        for name in sorted(used):
            if name in table.items:
                value = table.value(name)
                if value:
                    values[name] = value
    return values


TABLE_COMMAND = re.compile(r"^Form\.Item\.[^.]+\.StandardCommand\.(\w+)$")


def table_command_picture(command: str) -> str | None:
    """Картинка, которую рендерер сам дает кнопке стандартной команды таблицы без своей (значок ее кнопки
    автозаполнения); у команды без значка на панели - None."""
    found = TABLE_COMMAND.match(command or "")
    return STANDARD_PICTURES.get(found.group(1)) if found and found.group(1) in ICON_COMMANDS else None


def has_default(items: list) -> bool:
    return any((raw.kind == "Button" and raw.props.get("defaultButton")) or has_default(raw.items) for raw in items)


def has_source(items: list, source: str) -> bool:
    return any(raw.props.get("commandSource") == source or has_source(raw.items, source) for raw in items)


def placed_commands(raw: Raw) -> set:
    """Имена команд всех явных кнопок панели, включая вложенные группы и подменю."""
    found = set()
    for item in raw.items:
        if item.kind == "Button" and item.props.get("commandName"):
            found.add(item.props["commandName"])
        found |= placed_commands(item)
    return found
