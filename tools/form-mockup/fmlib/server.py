"""Локальный сервер макетов - команда `serve`.

Сервер обслуживает папку макетов (`Workspace`): стартовая страница со списком моделей папки (`home.js`),
новая форма, импорт, настройки папки. Каждый макет (`Editor`) - страница конструктора (рендерер +
`editor.js`), чтение, проверка и запись `model.json`; макет запроса - параметр `file`, без него - макет
запуска (`serve model.json`, как раньше). Общее для папки (`Sources`) - схема, словарь, стандартные
картинки и исходники конфигурации (`--src` или настройки папки): общие картинки, ссылочные типы и их состав,
элементы стиля, формы - для окон выбора и импорта. Версия файла - хеш содержимого в заголовке `ETag`: по ней
страница видит запись мимо конструктора (агент, редактор), а запись по устаревшей версии
отклоняется кодом 409. Модель с блокирующими замечаниями (`BLOCKING_CODES`) не пишется - 422. Страница
привязана к папке макетов, из которой открыта (`folder` в запросах): после «Другой папки» ее запросы - 409.

Только стандартная библиотека; слушает только 127.0.0.1. От чужих страниц браузера - проверка
заголовка Host (подмена DNS) и тело правок только `application/json` (простая форма с чужого
сайта его не пошлет без предварительного запроса, на который сервер не отвечает разрешением).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import DICTIONARY_PATH, ROOT, SCHEMA_PATH, colors, pictures, write_text_lf
from .diff import FORM_NAME, by_name, compare
from .dictionary import load_dictionary
from .importer import ImportFailure, describe_type, import_form
from .metadata import FOLDERS, LayeredMetadata, Metadata, read_designer, read_mdo, split_name
from .projects import find_projects, project_label, suggest_projects
from .model import BLOCKING_CODES, check, name_chain
from .render import build_editor_html, build_home_html, build_html
from .schema import SchemaValidator, format_path
from . import workspace as folders  # user_dir - через модуль: тесты подменяют его там
from .workspace import (WorkspaceError, clean_tags, config_forms, find_models, free_path, group_path, inside,
                        is_model, list_dirs, list_groups, read_settings, remember_folder, settings_sources,
                        source_kind, stored_path, suggest_src, write_settings)

GROUPS_PATH = ROOT / "schema" / "property-groups.json"
DEFAULT_PORT = 8190
PORT_TRIES = 21             # первый порт и следующие 20
# Первый порт перебора без терминала (ярлык): у пользователя занят весь диапазон 8190-8210
PORT_ENV = "FORMMOCKUP_PORT"
CONFIG_NAME = "config.json"


def base_port() -> int:
    """Первый порт перебора: переменная FORMMOCKUP_PORT, иначе `port` из `~/.form-mockup/config.json`, иначе 8190.
    Не число или вне 1024-65514 - 8190."""
    value = os.environ.get(PORT_ENV)
    if not value:
        try:
            config = json.loads((folders.user_dir() / CONFIG_NAME).read_text(encoding="utf-8-sig"))
            value = config.get("port") if isinstance(config, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            value = None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return port if 1024 <= port <= 65535 - PORT_TRIES else DEFAULT_PORT
SERVICE = "form-mockup"     # имя сервиса в `GET /about`: повторный запуск ищет по нему свой сервер
# Автоостановка: пауза без отметок вкладок и ожидание первой вкладки, секунды;
# `FORMMOCKUP_AUTOSTOP="<пауза>,<ожидание>"` - короче для тестов
IDLE_SECONDS = 60
FIRST_SECONDS = 30 * 60
AUTOSTOP_ENV = "FORMMOCKUP_AUTOSTOP"
# Свойства-структура: в панели свойств их нет, их правит дерево
STRUCTURE = {"type", "items", "commandBar"}
# Поля формы: у них `type` правится в панели как «Вид»
FIELD_DEFS = ["InputField", "CheckBoxField", "RadioButtonField", "LabelField", "PictureField", "StubField"]
# Русские имена стандартных картинок - из списка скрипта выгрузки (`|Имя;Name`)
STD_NAMES_PATH = ROOT / "1c" / "ВыгрузитьСтандартныеКартинки.bsl"
FORM_KINDS = ["DocumentObjectForm", "CatalogObjectForm", "ListForm", "ChoiceForm", "DataProcessorForm"]
# Объекты метаданных, на которые бывает ссылочный тип, - окно выбора типа конструктора (`GET /config-types`)
REF_TYPE_KINDS = ["Catalog", "Document", "Enum", "ChartOfCharacteristicTypes", "ChartOfAccounts",
                  "ChartOfCalculationTypes", "ExchangePlan", "BusinessProcess", "Task"]
# Окно типа (снимок окна «Редактирование типа данных», владелец 04.11.2026): еще объекты отчетов и обработок,
# наборы записей регистров, определяемые типы
TYPE_WINDOW_KINDS = REF_TYPE_KINDS + ["Report", "DataProcessor", "InformationRegister", "AccumulationRegister",
                                      "AccountingRegister", "CalculationRegister", "DefinedType"]


class ServeError(Exception):
    """Файл или папку не открыть, порт занят, не исходники - код выхода 2."""


# Корзина папки макетов: скрытый каталог - список макетов его не просматривает
TRASH_NAME = ".trash"


def now_text() -> str:
    """Дата и время для `origin` макета."""
    return datetime.now().isoformat(timespec="seconds")


def dump(model) -> str:
    """Формат записи - как у `import`: агент и `git diff` видят только правку."""
    return json.dumps(model, ensure_ascii=False, indent=2) + "\n"


def empty_model(form_kind: str) -> dict:
    return {"version": 1, "form": {"formKind": form_kind, "items": []}}


def etag_of(content: bytes) -> str:
    return '"' + hashlib.sha256(content).hexdigest()[:20] + '"'


def source_format(src: Path) -> bool:
    """Формат исходников конфигурации: EDT (`Configuration/Configuration.mdo`) - True, выгрузка конфигуратора
    (`Configuration.xml`) - False; ни то, ни другое - ServeError."""
    kind = source_kind(src)
    if kind:
        return kind == "edt"
    raise ServeError(f"не исходники конфигурации (нет Configuration/Configuration.mdo или Configuration.xml): {src}")


def object_names(src: Path, edt: bool, folder: str) -> list:
    """Имена объектов каталога исходников: EDT - `<Каталог>/<Имя>/<Имя>.mdo`, выгрузка - `<Каталог>/<Имя>.xml`."""
    base = src / folder
    if not base.is_dir():
        return []
    if edt:
        return sorted(path.name for path in base.iterdir() if (path / f"{path.name}.mdo").is_file())
    return sorted(path.stem for path in base.iterdir() if path.suffix == ".xml" and path.is_file())


# Описание видов для панели свойств: схема без $ref и allOf - то, что нужно странице

def property_specs(validator: SchemaValidator, node: dict) -> dict:
    """Свойства узла схемы с его `allOf`: имя → исходная запись схемы (с `$ref`)."""
    node = validator.resolve(node)
    specs = {}
    for sub in node.get("allOf", []):
        specs.update(property_specs(validator, sub))
    specs.update(node.get("properties", {}))
    return specs


def field_spec(validator: SchemaValidator, raw: dict) -> dict:
    """Запись схемы → вид поля панели: enum, boolean, integer, string, name, color, list, choices, rows, simple, font."""
    ref = raw.get("$ref", "")
    named = {"#/$defs/name": "name", "#/$defs/color": "color", "#/$defs/stringList": "list", "#/$defs/choiceList": "choices"}
    if ref in named:
        spec = {"input": named[ref]}
        if named[ref] in ("name", "color"):
            spec["pattern"] = validator.resolve(raw)["pattern"]
        return spec
    node = validator.resolve(raw)
    if "enum" in node:
        return {"input": "enum", "values": list(node["enum"])}
    kind = node.get("type")
    if kind == "boolean":
        return {"input": "boolean"}
    if kind == "integer":
        return {"input": "integer", "minimum": node.get("minimum")}
    if kind == "string":
        spec = {"input": "string"}
        if "pattern" in node:
            spec["pattern"] = node["pattern"]
        return spec
    if kind == ["string", "number"]:
        return {"input": "simple"}
    if kind == "array":
        items = validator.resolve(node.get("items", {}))
        return {"input": "rows" if items.get("type") == "array" else "list"}
    if kind == "object":
        return {"input": "font", "keys": list(node.get("properties", {}))}
    raise ValueError(f"вид поля панели не определен: {raw}")


def kinds_description(validator: SchemaValidator) -> dict:
    """Вид элемента → {свойство: поле панели}; у формы - ключ `Form`."""
    kinds = {"Form": validator.defs["Form"]}
    for node in validator.defs.values():
        for kind in validator.type_values(node):
            kinds[kind] = node
    # Тип значения поля и его квалификаторы конструктор переносит из реквизита: в панели элемента их нет
    derived = set(json.loads(GROUPS_PATH.read_text(encoding="utf-8")).get("derived", []))
    result = {}
    for kind, node in sorted(kinds.items()):
        specs = property_specs(validator, node)
        result[kind] = {prop: field_spec(validator, raw) for prop, raw in specs.items()
                        if prop not in STRUCTURE and prop not in derived and not prop.startswith("$")}
    # «Вид» поля (ВидПоляФормы): смена `type` в пределах полей, список видов - по типу реквизита и месту (editor.js)
    for name in FIELD_DEFS:
        for kind in validator.type_values(validator.defs[name]):
            result[kind]["type"] = {"input": "fieldKind"}
    # Реквизит формы - для панели свойств реквизитов; колонки правит дерево реквизитов
    specs = property_specs(validator, validator.defs["attribute"])
    result["Attribute"] = {prop: ({"input": "type"} if prop == "valueType" else field_spec(validator, raw))
                           for prop, raw in specs.items() if prop not in ("columns", "additionalColumns")}
    # Команда формы - панель левой колонки «Команды»
    specs = property_specs(validator, validator.defs["command"])
    result["Command"] = {prop: field_spec(validator, raw) for prop, raw in specs.items()}
    return result


def containment(validator: SchemaValidator) -> dict:
    """Контейнер → виды, которые схема принимает в его `items` (правка структуры); у формы - ключ `Form`."""
    kinds = {"Form": validator.defs["Form"]}
    for node in validator.defs.values():
        for kind in validator.type_values(node):
            kinds[kind] = node
    result = {}
    for kind, node in sorted(kinds.items()):
        items = property_specs(validator, node).get("items")
        if items is None:
            continue
        accepted = []
        for option in validator.resolve(validator.resolve(items).get("items", {})).get("oneOf", []):
            accepted += [value for value in validator.type_values(option) if value not in accepted]
        result[kind] = accepted
    return result


class Sources:
    """Общее для папки макетов: схема, словарь, группы свойств, стандартные картинки и исходники
    конфигурации с их кэшами. Один на сервис: макеты папки берут его у `Workspace`."""

    def __init__(self, std_pictures: Path | None = None, src: Path | None = None, extensions: list | None = None):
        self.validator = SchemaValidator.from_file(SCHEMA_PATH)
        self.dictionary = load_dictionary(DICTIONARY_PATH)
        with open(GROUPS_PATH, encoding="utf-8") as file:
            self.groups = json.load(file)
        self.std_source = std_pictures
        self.std_cache = {}
        self.source_lock = threading.Lock()
        self.description = None
        self.set_src(src, extensions)

    def set_src(self, src: Path | None, extensions: list | None = None):
        """Исходники конфигурации (`--src` или настройки папки) и выбранные ее расширения:
        читаются лениво при первом запросе и помнятся; смена исходников сбрасывает кэши. Не исходники - ServeError."""
        paths = [src, *(extensions or [])] if src else []
        layers = [Metadata(path, source_format(path)) for path in paths]
        metadata = LayeredMetadata(layers) if len(layers) > 1 else layers[0] if layers else None
        with self.source_lock:
            self.src = src
            self.extensions = list(paths[1:])
            self.layers = layers
            self.metadata = metadata
            self.picture_list = None
            self.type_list = None
            self.form_list = None

    def metadata_for(self, form: Path):
        """Метаданные для импорта формы исходников: у конфигурации с расширениями - объединение, справка и
        принадлежность формы - из исходников, где она лежит; одиночные исходники - None (импорт найдет их сам)."""
        if len(self.layers) < 2:
            return None
        own = [layer for layer in self.layers if Path(form).resolve().is_relative_to(layer.src.resolve())]
        return LayeredMetadata(self.layers, own[0] if own else None)

    # Проверка

    def issues(self, model) -> list:
        """Замечания схемы и `check`: код, цепочка имен, место в JSON, текст, блокирует ли."""
        result = []
        for issue in check(model, self.validator):
            chain = name_chain(model, issue.path)
            result.append({
                "code": issue.code,
                "path": chain,
                "name": chain.split("/")[-1] if chain else "Форма",
                "where": format_path(issue.path),
                "message": issue.message,
                "blocking": issue.code in BLOCKING_CODES,
            })
        return result

    # Картинки

    def pictures(self, model) -> dict:
        """Стандартные картинки, которых нет в модели, - для рисования, как у `render`; в файл не идут."""
        if not self.std_source or not isinstance(model, dict) or not isinstance(model.get("form"), dict):
            return {}
        names = pictures.used(pictures.referencing(model), set(), (pictures.STD_PREFIX,))
        names |= {pictures.STD_PREFIX + name for name in pictures.RENDER_STD}
        own = model.get("pictures") or {}
        missing = [name for name in sorted(names) if name not in own and name not in self.std_cache]
        if missing:
            files = pictures.std_files(self.std_source)
            for name in missing:
                self.std_cache[name] = pictures.load_std(files, name)
        return {name: self.std_cache[name] for name in names if name not in own and self.std_cache.get(name)}

    def std_library(self) -> list:
        """Библиотека стандартных картинок для окна выбора: имя, русское имя, data URI; по русскому имени."""
        if not self.std_source:
            return []
        russian = {}
        try:
            for line in STD_NAMES_PATH.read_text(encoding="utf-8").splitlines():
                parts = line.lstrip("|").split(";")
                if line.startswith("|") and len(parts) == 2:
                    russian[parts[1].strip()] = parts[0].strip()
        except OSError:
            pass
        files = pictures.std_files(self.std_source)
        result = []
        for name in sorted(files):
            key = pictures.STD_PREFIX + name
            if key not in self.std_cache:
                self.std_cache[key] = pictures.load_std(files, key)
            if self.std_cache[key]:
                result.append({"name": key, "ru": russian.get(name, ""), "uri": self.std_cache[key]})
        return sorted(result, key=lambda entry: (entry["ru"] or entry["name"]).lower())

    # Исходники конфигурации

    def config_pictures(self) -> list:
        """Общие картинки конфигурации (`GET /config-pictures`): имя, синоним, data URI варианта «Такси», как у импорта;
        картинка без значка (не найдена, крупнее предела) не входит. По имени."""
        if not self.metadata:
            return []
        with self.source_lock:
            if self.picture_list is None:
                # Конфигурация и расширения: картинка расширения с тем же именем важнее
                found = {}
                for layer in self.layers:
                    src, edt = layer.src, layer.edt
                    for name in object_names(src, edt, "CommonPictures"):
                        uri = pictures.load(src, edt, pictures.PREFIX + name)
                        if not uri:
                            continue
                        path = src / "CommonPictures" / (f"{name}/{name}.mdo" if edt else f"{name}.xml")
                        try:
                            synonym = (read_mdo if edt else read_designer)(path, "CommonPicture", name).synonym
                        except (ET.ParseError, OSError):
                            synonym = None
                        found[name] = {"name": pictures.PREFIX + name, "title": synonym or split_name(name), "uri": uri}
                self.picture_list = [found[name] for name in sorted(found)]
            return self.picture_list

    def config_types(self) -> list:
        """Ссылочные объекты конфигурации (`GET /config-types`): ключ, вид, имя, синоним; у перечисления - синонимы
        значений, как `enumValues` импорта. По видам `TYPE_WINDOW_KINDS`, внутри вида - по имени."""
        if not self.metadata:
            return []
        with self.source_lock:
            if self.type_list is None:
                result = []
                for kind in TYPE_WINDOW_KINDS:
                    names = sorted({name for layer in self.layers for name in object_names(layer.src, layer.edt, FOLDERS[kind])})
                    for name in names:
                        found = self.metadata.object(kind, name)
                        if found is None and kind in REF_TYPE_KINDS:
                            continue
                        entry = {"key": f"{kind}.{name}", "kind": kind, "name": name,
                                 "title": getattr(found, "caption", "") or ""}
                        if kind == "Enum":
                            entry["values"] = [synonym or split_name(value) for value, synonym in found.values.items()]
                        result.append(entry)
                self.type_list = result
            return self.type_list

    def type_description(self, key: str):
        """Состав типа `Catalog.Имя` (`GET /type-description`) - как импорт пишет его в `types` модели; нет - None."""
        kind, _, name = (key or "").partition(".")
        if not self.metadata or kind not in REF_TYPE_KINDS or not name or "." in name:
            return None
        with self.source_lock:
            return describe_type(self.metadata, key)

    def config_styles(self) -> list:
        """Цветовые элементы стиля конфигурации (`GET /config-styles`): имя и `#RRGGBB` с поправкой основного стиля -
        вторая часть закладки «Из стиля»; в модель импорт пишет только использованные формой."""
        if not self.metadata:
            return []
        with self.source_lock:
            found = {}
            for layer in self.layers:
                for style in colors.config_styles(layer.src, layer.edt):
                    found[style["name"]] = style
            return [found[name] for name in sorted(found)]

    def config_forms(self) -> list:
        """Формы конфигурации для «Импорт из 1С» по дереву объектов."""
        if not self.metadata:
            return []
        with self.source_lock:
            if self.form_list is None:
                result = []
                for layer in self.layers:
                    forms = config_forms(layer.src, layer.edt)
                    if len(self.layers) > 1:
                        # У формы - проект, из которого она: ключ с ним, формы проектов не смешиваются
                        label = project_label(layer.src)
                        for form in forms:
                            form.update(key=f"{label}:{form['key']}", project=label)
                    result += forms
                self.form_list = result
            return self.form_list

    # Страницы

    def page(self, file: str, folder: str | None = None) -> str:
        """Страница конструктора макета `file`; описание видов и групп свойств считается один раз на сервис.
        `folder` - папка макетов, из которой открыта страница: ее запросы макета идут с ней."""
        if self.description is None:
            self.description = {
                "dictionary": self.dictionary,
                "kinds": kinds_description(self.validator),
                "children": containment(self.validator),
                "platform": {prop: self.validator.platform_mark(prop) for prop in self.validator.platform},
                "groups": self.groups,
                "formKinds": FORM_KINDS,
                "colors": {"platform": colors.TABLE["platform"], "web": colors.TABLE["web"]},
            }
        name = Path(file).name
        # Есть исходники конфигурации: окна выбора картинки и типа берут их с сервера
        editor = dict(self.description, file=name, source=self.metadata is not None, folder=folder)
        return build_editor_html(self.dictionary, editor, f"Конструктор макета - {name}")

    def home_page(self) -> str:
        kinds = self.dictionary.get("values", {}).get("formKind", {})
        # Значки видов метаданных дерева «Из конфигурации»
        icons = json.loads((ROOT / "render" / "metadata-icons.json").read_text(encoding="utf-8"))["icons"]
        return build_home_html({"formKinds": [{"kind": kind, "title": kinds.get(kind, kind)} for kind in FORM_KINDS],
                                "metadataIcons": icons})

    def thumbnail(self, model: dict, title: str) -> str:
        """Миниатюра списка: страница рендерера с моделью и недостающими стандартными картинками, как у `render`."""
        drawn = dict(model, pictures={**self.pictures(model), **(model.get("pictures") or {})})
        return build_html(drawn, self.dictionary, title)


class Editor:
    """Один макет: файл модели, «было» для правок, чтение и запись. Общее для папки - `sources`."""

    def __init__(self, path: Path, std_pictures: Path | None = None, src: Path | None = None,
                 base: dict | None = None, base_file: Path | None = None, sources: Sources | None = None):
        self.path = path
        # Чтение и запись файла - под одной блокировкой: на Windows `os.replace` при открытом на чтение файле
        # дает PermissionError (опрос `/version` страницы во время «Сохранить»)
        self.lock = threading.RLock()
        self.sources = sources if sources is not None else Sources(std_pictures, src)
        # «Было» для правок: модель `--before` (`base_file`) или файла на запуске; держится всю работу сервера
        self.base_file = base_file
        if base is None:
            content = self.read()[0]
            try:
                base = json.loads(content.decode("utf-8")) if content is not None else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                base = {}
        self.base = base
        self.base_blocked = any(issue["blocking"] for issue in self.issues(base))

    @property
    def metadata(self):
        return self.sources.metadata

    @property
    def dictionary(self):
        return self.sources.dictionary

    @property
    def validator(self):
        return self.sources.validator

    # Файл

    def read(self):
        """Содержимое файла и его версия; файла нет - (None, None)."""
        with self.lock:
            try:
                content = self.path.read_bytes()
            except FileNotFoundError:
                return None, None
        return content, etag_of(content)

    def version(self):
        """Версия файла для слежения страницы (`GET /version`)."""
        return self.read()[1]

    def write(self, model) -> str:
        """Запись во временный файл рядом и переименование: читатель не застанет файл наполовину.

        Файл модели на Windows может держать открытым и чужой читатель (агент, редактор): переименование
        повторяется несколько раз с короткой паузой, прежде чем ответить ошибкой."""
        content = dump(model).encode("utf-8")
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        with self.lock:
            try:
                temporary.write_bytes(content)
                replace_with_retry(temporary, self.path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return etag_of(content)

    # Проверка и правки

    def issues(self, model) -> list:
        return self.sources.issues(model)

    def base_info(self) -> dict:
        """«Было» для страницы: файл `--before` и имена элементов - по ним конструктор ставит `renamedFrom`."""
        names = sorted(name for name in by_name(self.base.get("form")) if name != FORM_NAME)
        return {"file": self.base_file.name if self.base_file else None, "names": names}

    def changes(self, model, issues: list, tree: bool) -> dict:
        """Правки против «было», как у `render --before`; модель или «было» с блокирующими замечаниями - `null`."""
        if self.base_blocked or any(issue["blocking"] for issue in issues):
            return {"changes": None}
        diff = compare(self.base, model, self.dictionary)
        result = {"changes": [change.as_data() for change in diff.changes]}
        if tree:
            result["tree"] = diff.tree
        return result

    def pictures(self, model) -> dict:
        return self.sources.pictures(model)

    def page(self, folder: str | None = None) -> str:
        return self.sources.page(self.path.name, folder)


class Workspace:
    """Папка макетов: макеты в ней, общие `Sources`, настройки папки. Сервис обслуживает одну
    папку; «Другая папка» стартовой страницы переключает его. `default` - макет запуска (`serve model.json`):
    запросы макета без `file` идут к нему - прежний API не меняется."""

    def __init__(self, root: Path, sources: Sources, default: Editor | None = None, pinned_src: bool = False,
                 projects: Path | None = None):
        self.lock = threading.Lock()
        self.sources = sources
        # `--src` в командной строке важнее настроек папки на этот запуск
        self.pinned_src = pinned_src
        self.open_folder(root, default)
        self.set_projects_folder(projects)

    @classmethod
    def single(cls, editor: Editor) -> "Workspace":
        """Сервис на папку одного макета - как прежний `serve model.json`."""
        return cls(editor.path.parent, editor.sources, editor, editor.metadata is not None)

    def open_folder(self, root: Path, default: Editor | None = None):
        root = Path(root).resolve()
        if not root.is_dir():
            raise WorkspaceError(f"папка не найдена: {root}")
        with self.lock:
            self.root = root
            self.editors = {}
            self.default = None
            self.suggested = False      # папка проектов рядом с папкой макетов: еще не искалась
            if default is not None:
                self.default = default.path.resolve().relative_to(root).as_posix()
                self.editors[self.default] = default

    def switch(self, root: Path):
        """«Другая папка»: макеты и исходники - из новой папки, ее настроек."""
        self.open_folder(root)
        self.pinned_src = False
        projects, configuration, extensions = settings_sources(self.root)
        self.sources.set_src(configuration, extensions)
        self.set_projects_folder(projects)
        remember_folder(self.root)

    def editor(self, file: str | None) -> Editor:
        """Макет по пути от папки; без пути - макет запуска."""
        with self.lock:
            if not file:
                if self.default is None:
                    raise WorkspaceError("не указан файл макета (file)")
                return self.editors[self.default]
            path = inside(self.root, file)
            key = path.relative_to(self.root).as_posix()
            if key not in self.editors:
                self.editors[key] = Editor(path, sources=self.sources)
            return self.editors[key]

    def info(self) -> dict:
        """Стартовая страница (`GET /models`): папка, исходники (конфигурация и расширения), папка проектов с
        найденным в ней, предложенные исходники и папка проектов, макеты."""
        src = self.sources.src
        suggested = suggest_src(self.root) if src is None else None
        if self.suggested is False:
            self.suggested = suggest_projects(self.root)
        projects = None
        if self.projects is not None:
            projects = {"folder": str(self.projects), "items": [project.as_data() for project in self.found]}
        return {"folder": str(self.root), "src": str(src) if src else None, "srcPinned": self.pinned_src,
                "extensions": [str(path) for path in self.sources.extensions], "projects": projects,
                "suggestedSrc": str(suggested) if suggested else None,
                "suggestedProjects": str(self.suggested) if self.suggested and src is None and projects is None else None,
                "default": self.default, **self.models_info()}

    def models_info(self) -> dict:
        """Макеты папки с группами и метками: `models`, `groups` - все группы, `tags` - метки папки."""
        models = find_models(self.root)
        tags = sorted({tag for model in models for tag in model["tags"]}, key=str.casefold)
        return {"models": models, "groups": list_groups(self.root, models), "tags": tags}

    # Новые макеты

    def target(self, file: str) -> Path:
        path = inside(self.root, file)
        if path.exists():
            raise FileExistsError(f"файл уже есть: {file}")
        return path

    def create(self, file: str, kind: str) -> dict:
        """«Новая форма»: пустая модель вида `kind`."""
        if kind not in FORM_KINDS:
            raise WorkspaceError(f"неизвестный вид формы: {kind}")
        path = self.target(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, dump(empty_model(kind)))
        return {"file": path.relative_to(self.root).as_posix(), "report": []}

    def import_file(self, file: str, source: Path, metadata: Metadata | None = None, origin: dict | None = None) -> dict:
        """«Импорт из 1С»: модель по `Form.form` / `Form.xml`, как команда `import`; `origin` - откуда взята."""
        path = self.target(file)
        model, report = import_form(source, self.sources.std_source, metadata)
        if origin:
            model["origin"] = dict(origin, at=now_text())
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, dump(model))
        return {"file": path.relative_to(self.root).as_posix(), "report": report.lines()}

    def import_text(self, file: str, name: str, text: str) -> dict:
        """Импорт перетащенного файла: текст XML с именем `Form.form` или `Form.xml`."""
        if name not in ("Form.form", "Form.xml"):
            raise WorkspaceError(f"ожидается Form.form (EDT) или Form.xml (выгрузка конфигуратора): {name}")
        with tempfile.TemporaryDirectory(prefix="formmockup-import-") as folder:
            source = Path(folder) / name
            source.write_text(text, encoding="utf-8")
            return self.import_file(file, source, origin={"kind": "file", "name": name})

    def import_object(self, file: str, key: str) -> dict:
        """Импорт формы из дерева объектов исходников папки (`GET /config-forms`): у конфигурации с расширениями
        форма видит объекты всех выбранных исходников."""
        found = [form for form in self.sources.config_forms() if form["key"] == key]
        if not found:
            raise WorkspaceError(f"форма не найдена в исходниках конфигурации: {key}"
                                 if self.sources.metadata else "исходники конфигурации не заданы")
        path = Path(found[0]["path"])
        origin = {"kind": "config", "object": key}
        if found[0].get("project"):
            origin["project"] = found[0]["project"]
        return self.import_file(file, path, self.sources.metadata_for(path), origin)

    # Группы, метки, перенос и копирование

    def create_group(self, group: str) -> dict:
        """«Новая группа»: подкаталог и запись в настройках папки - пустая группа видна в списке."""
        path = group_path(self.root, group)
        if path == self.root.resolve():
            raise WorkspaceError("не задано имя группы")
        if path.exists():
            raise FileExistsError(f"группа уже есть: {group}")
        path.mkdir(parents=True)
        key = path.relative_to(self.root.resolve()).as_posix()
        settings = read_settings(self.root)
        groups = [item for item in settings.get("groups") or [] if isinstance(item, str) and item != key]
        settings["groups"] = sorted(groups + [key], key=str.casefold)
        write_settings(self.root, settings)
        return self.info()

    def delete_group(self, group: str) -> dict:
        """«Удалить группу» - только пустую (в каталоге ничего нет); непустая - FileExistsError."""
        path = group_path(self.root, group)
        if path == self.root.resolve() or not path.is_dir():
            raise WorkspaceError(f"нет такой группы: {group}")
        if any(path.iterdir()):
            raise FileExistsError(f"группа не пуста: {group}")
        path.rmdir()
        key = path.relative_to(self.root.resolve()).as_posix()
        settings = read_settings(self.root)
        if settings.get("groups"):
            settings["groups"] = [item for item in settings["groups"] if item != key]
            if not settings["groups"]:
                settings.pop("groups")
            write_settings(self.root, settings)
        return self.info()

    def set_tags(self, file: str, tags) -> dict:
        """Метки макета: пишутся в модель; конструктор открытого макета увидит внешнее изменение."""
        editor = self.editor(file)
        try:
            model = json.loads(editor.path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkspaceError(f"макет не читается: {file}: {error}") from error
        if not is_model(model):
            raise WorkspaceError(f"не макет: {file}")
        cleaned = clean_tags(tags)
        if cleaned:
            model["tags"] = cleaned
        else:
            model.pop("tags", None)
        editor.write(model)
        return self.info()

    def move(self, file: str, group: str) -> dict:
        """«Переместить в...»: файл - в группу, имя то же; занято - FileExistsError."""
        source = inside(self.root, file)
        if not source.is_file():
            raise WorkspaceError(f"нет такого макета: {file}")
        folder = group_path(self.root, group)
        target = folder / source.name
        if target == source:
            return {"file": file}
        if target.exists():
            raise FileExistsError(f"в группе уже есть файл {source.name}")
        folder.mkdir(parents=True, exist_ok=True)
        with self.lock:
            replace_with_retry(source, target)
            self.editors.pop(source.relative_to(self.root.resolve()).as_posix(), None)
        return {"file": target.relative_to(self.root.resolve()).as_posix()}

    def copy(self, file: str, copy_from: str, from_folder: str | None = None, to_folder: str | None = None) -> dict:
        """Копия макета: из этой папки или из другой (`from_folder`) в `file` этой папки или другой
        (`to_folder`); занятое имя - с номером. Метки копируются, `origin` - копия; оригинал в другой папке -
        путь от его папки и сама папка."""
        folder = self.other_folder(from_folder)
        root = self.other_folder(to_folder)
        source = inside(folder, copy_from)
        try:
            model = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkspaceError(f"макет не читается: {copy_from}: {error}") from error
        if not is_model(model):
            raise WorkspaceError(f"не макет: {copy_from}")
        target = free_path(inside(root, file))
        origin = {"kind": "copy", "from": source.relative_to(folder).as_posix()}
        if folder != root:
            origin["folder"] = str(folder)
        model["origin"] = dict(origin, at=now_text())
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(target, dump(model))
        return {"file": target.relative_to(root).as_posix(), "folder": str(root)}

    def trash(self, file: str) -> dict:
        """«Удалить...»: макет - в `.trash/<дата-время>/<путь макета>` папки; вернуть - `restore`."""
        source = inside(self.root, file)
        if not source.is_file():
            raise WorkspaceError(f"нет такого макета: {file}")
        relative = source.relative_to(self.root.resolve())
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = self.root.resolve() / TRASH_NAME / stamp / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            replace_with_retry(source, target)
            self.editors.pop(relative.as_posix(), None)
        return {"trashed": f"{stamp}/{relative.as_posix()}"}

    def restore(self, trashed: str) -> dict:
        """«Вернуть»: из корзины на прежнее место; занято - свободное имя с номером."""
        trash = (self.root.resolve() / TRASH_NAME).resolve()
        source = (trash / (trashed or "")).resolve()
        parts = Path(trashed or "").parts
        if not trashed or not source.is_relative_to(trash) or len(parts) < 2 or not source.is_file():
            raise WorkspaceError(f"нет в корзине: {trashed}")
        target = free_path(inside(self.root, Path(*parts[1:]).as_posix()))
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_with_retry(source, target)
        # Пустые каталоги отметки времени в корзине не копятся
        folder = source.parent
        while folder != trash and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
        return {"file": target.relative_to(self.root.resolve()).as_posix()}

    def other_folder(self, value: str | None) -> Path:
        """Папка макетов копирования: своя (пусто) или другая - существующий каталог."""
        if not value:
            return self.root.resolve()
        folder = Path(value).expanduser()
        if not folder.is_dir():
            raise WorkspaceError(f"нет такой папки макетов: {value}")
        return folder.resolve()

    @staticmethod
    def folder_models(path: str) -> dict:
        """Макеты другой папки для «Из папки макетов» - только список."""
        folder = Path(path or "").expanduser()
        if not path or not folder.is_dir():
            raise WorkspaceError(f"нет такой папки: {path}")
        folder = folder.resolve()
        return {"folder": str(folder), "models": find_models(folder)}

    # Настройки папки

    def set_src(self, value: str | None) -> dict:
        """Исходники папки: проверить, запомнить в `.form-mockup.json`, подхватить; пусто - без исходников."""
        settings = read_settings(self.root)
        if not value:
            self.sources.set_src(None)
            settings.pop("src", None)
        else:
            path = Path(value).expanduser()
            path = (self.root / path if not path.is_absolute() else path).resolve()
            if not source_kind(path):
                raise WorkspaceError(f"не исходники конфигурации: {path} - нужен каталог `src` проекта EDT "
                                     "(в нем Configuration/Configuration.mdo) или выгрузка конфигуратора "
                                     "(в нем Configuration.xml)")
            self.sources.set_src(path)
            settings["src"] = stored_path(self.root, path)
        for key in ("projects", "configuration", "extensions"):
            settings.pop(key, None)
        self.projects = None
        self.found = []
        self.pinned_src = False
        write_settings(self.root, settings)
        return self.info()

    # Папка проектов

    def set_projects_folder(self, folder: Path | None):
        """Папка проектов и найденное в ней: конфигурации, расширения с основой."""
        self.projects = Path(folder).resolve() if folder else None
        self.found = find_projects(self.projects) if self.projects else []

    def set_projects(self, folder: str | None, configuration=None, extensions=None) -> dict:
        """Папка проектов и выбор в ней (`PUT /settings`): новая папка - поиск и выбор по умолчанию (одна
        конфигурация - она и все ее расширения; ни одной, одно расширение - оно одиночными исходниками); выбор -
        конфигурация из найденного и ее расширения. Пусто - без исходников."""
        settings = {key: value for key, value in read_settings(self.root).items()
                    if key not in ("src", "projects", "configuration", "extensions")}
        if not folder:
            self.projects, self.found = None, []
            self.sources.set_src(None)
        else:
            path = Path(folder).expanduser()
            path = (self.root / path if not path.is_absolute() else path).resolve()
            if not path.is_dir():
                raise WorkspaceError(f"папка не найдена: {path}")
            if path != self.projects or configuration is None:
                self.set_projects_folder(path)
            if not self.found:
                raise WorkspaceError(f"в папке нет исходников конфигураций и расширений (Configuration/Configuration.mdo "
                                     f"проекта EDT или Configuration.xml выгрузки): {path}")
            chosen, added = self.choose(configuration, extensions)
            self.sources.set_src(chosen, added)
            settings["projects"] = stored_path(self.root, path)
            settings["configuration"] = stored_path(self.root, chosen) if chosen else None
            settings["extensions"] = [stored_path(self.root, item) for item in added]
        self.pinned_src = False
        write_settings(self.root, settings)
        return self.info()

    def choose(self, configuration, extensions) -> tuple:
        """Конфигурация и расширения из найденного: не задано - по умолчанию, пустая строка - ничего; чужое
        расширение не берется. Основы в папке нет - расширения без основы берутся вместе, первое - главным слоем."""
        by_path = {str(project.src).lower(): project for project in self.found}
        configurations = [project for project in self.found if not project.extension]
        if configuration == "":
            return None, []
        if configuration is None:
            if len(configurations) == 1:
                chosen = configurations[0]
                return chosen.src, [project.src for project in self.found if project.base == chosen.src]
            alone = [project for project in self.found if project.extension]
            return (alone[0].src, []) if not configurations and len(alone) == 1 else (None, [])
        found = by_path.get(str(Path(configuration).resolve()).lower())
        if found is None:
            raise WorkspaceError(f"не найдено в папке проектов: {configuration}")
        added = []
        for value in extensions or []:
            extension = by_path.get(str(Path(value).resolve()).lower())
            if extension is None or not extension.extension:
                raise WorkspaceError(f"не расширение этой конфигурации: {value}")
            if found.extension:
                if found.base is not None or extension.base is not None or extension.src == found.src:
                    raise WorkspaceError(f"расширения с основой в папке берутся с ней, а не вместе: {extension.name}")
            elif extension.base not in (None, found.src) or found.src not in extension.candidates:
                raise WorkspaceError(f"расширение не подходит к конфигурации {found.name}: {extension.name}")
            added.append(extension.src)
        return found.src, added


class Lifetime:
    """Автоостановка сервиса: открытые страницы шлют отметки вкладки (`POST /alive`); нет отметок
    от всех вкладок дольше `idle` - сервис останавливается, как и когда за `first` после запуска не открылась ни
    одна вкладка. «Завершить» (`POST /shutdown`) - сразу. Правила одни для ярлыка и `serve` агента."""

    def __init__(self, idle: float = IDLE_SECONDS, first: float = FIRST_SECONDS, clock=time.monotonic):
        self.idle = idle
        self.first = first
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()
        self.tabs = {}              # вкладка → (время отметки, макет, есть несохраненные правки)
        self.reason = None
        self.stopped = threading.Event()

    @classmethod
    def from_env(cls) -> "Lifetime":
        """Паузы из `FORMMOCKUP_AUTOSTOP` («пауза,ожидание» в секундах), иначе по спеке."""
        try:
            idle, first = (float(part) for part in os.environ.get(AUTOSTOP_ENV, "").split(","))
        except ValueError:
            return cls()
        return cls(idle, first)

    def mark(self, tab: str, file: str | None = None, dirty: bool = False):
        with self.lock:
            self.tabs[str(tab)] = (self.clock(), file or None, bool(dirty))

    def open_files(self) -> set:
        """Макеты, открытые в живых вкладках конструктора, - их не переносят."""
        now = self.clock()
        with self.lock:
            return {file for moment, file, _ in self.tabs.values() if file and now - moment <= self.idle}

    def dirty_files(self) -> list:
        """Макеты с несохраненными правками в живых вкладках - предупреждение перед «Завершить»."""
        now = self.clock()
        with self.lock:
            return sorted({file or "" for moment, file, dirty in self.tabs.values()
                           if dirty and now - moment <= self.idle})

    def expired(self) -> str | None:
        """Причина остановки или None - работать дальше."""
        now = self.clock()
        with self.lock:
            if not self.tabs:
                if now - self.started > self.first:
                    return f"за {self.first / 60:g} мин после запуска страница так и не открылась"
                return None
            if now - max(moment for moment, _, _ in self.tabs.values()) > self.idle:
                return f"открытых страниц нет больше {self.idle:g} с"
        return None

    def stop(self, server, reason: str):
        """Остановить сервер из любого потока: `shutdown` ждет конца `serve_forever`, поэтому - в своем потоке."""
        with self.lock:
            if self.reason is not None:
                return
            self.reason = reason
        self.stopped.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    def watch(self, server, period: float = 1.0):
        """Слежение в фоне: раз в `period` - не пора ли остановиться."""
        def loop():
            while not self.stopped.wait(period):
                reason = self.expired()
                if reason:
                    self.stop(server, reason)
        threading.Thread(target=loop, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "formmockup"
    workspace: Workspace = None

    def log_message(self, format, *args):  # noqa: A002 - сигнатура базового класса
        pass

    # Ответы

    def send(self, status, body, content_type="application/json; charset=utf-8", etag=None):
        data = body if isinstance(body, bytes) else (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if etag:
            self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(data)

    def allowed(self) -> bool:
        """Только свой адрес в Host: страница чужого сайта через подмену DNS сюда не дойдет. Запрос страницы,
        открытой из другой папки макетов, - 409 (`same_folder`)."""
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send(HTTPStatus.FORBIDDEN, {"error": "чужой адрес"})
            return False
        return self.same_folder()

    def same_folder(self) -> bool:
        """Страница привязана к папке макетов, из которой открыта: запросы конструктора и стартовой
        страницы несут ее в `folder`. После «Другой папки» запрос старой вкладки - 409 `folderChanged`, а не
        запись или удаление одноименного файла новой папки. Без `folder` (API агента, тесты) - без проверки."""
        folder = self.query(urlsplit(self.path), "folder")
        root = self.workspace.root
        if not folder or Path(folder).resolve() == root:
            return True
        self.send(HTTPStatus.CONFLICT, {"error": f"папка макетов сменилась: страница открыта из папки {folder}, "
                                                 f"сервис работает с папкой {root}", "folderChanged": True,
                                        "folder": str(root)})
        return False

    def body_model(self):
        """JSON из тела запроса (модель или параметры); не JSON - ответ 400 и None."""
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self.send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "ожидается application/json"})
            return None
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.send(HTTPStatus.BAD_REQUEST, {"error": f"тело не JSON: {error}"})
            return None

    def body_object(self):
        """Параметры запроса - объект JSON; иначе ответ 400 и None."""
        body = self.body_model()
        if body is not None and not isinstance(body, dict):
            self.send(HTTPStatus.BAD_REQUEST, {"error": "ожидается объект JSON"})
            return None
        return body

    @staticmethod
    def query(url, name: str) -> str:
        return (parse_qs(url.query).get(name) or [""])[0]

    def target(self, url) -> Editor | None:
        """Макет запроса по `file`, без него - макет запуска; не найти - ответ 400 и None."""
        try:
            return self.workspace.editor(self.query(url, "file") or None)
        except WorkspaceError as error:
            self.send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return None

    def read_model(self, editor: Editor):
        """(модель, версия) файла макета; нет файла или не JSON - ответ 422 и (None, None)."""
        content, etag = editor.read()
        if content is None:
            self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"файл не найден: {editor.path}"})
            return None, None
        try:
            return json.loads(content.decode("utf-8")), etag
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": f"файл не читается как JSON: {error}"}, etag=etag)
            return None, None

    # Запросы

    def do_GET(self):  # noqa: N802 - имя метода задает http.server
        if not self.allowed():
            return
        workspace = self.workspace
        sources = workspace.sources
        url = urlsplit(self.path)
        if url.path == "/":
            self.send(HTTPStatus.OK, sources.home_page(), "text/html; charset=utf-8")
        elif url.path == "/edit":
            editor = self.target(url)
            if editor:
                self.send(HTTPStatus.OK, editor.page(str(workspace.root)), "text/html; charset=utf-8")
        elif url.path == "/thumb":
            editor = self.target(url)
            model = self.read_model(editor)[0] if editor else None
            if model is not None:
                self.send(HTTPStatus.OK, sources.thumbnail(model, editor.path.name), "text/html; charset=utf-8")
        elif url.path == "/model":
            editor = self.target(url)
            model, etag = self.read_model(editor) if editor else (None, None)
            if model is not None:
                self.send(HTTPStatus.OK, {"model": model, "issues": editor.issues(model),
                                          "pictures": editor.pictures(model), "base": editor.base_info()}, etag=etag)
        elif url.path == "/version":
            editor = self.target(url)
            if editor:
                self.send(HTTPStatus.OK, {"etag": editor.version()})
        elif url.path == "/models":
            self.send(HTTPStatus.OK, workspace.info())
        elif url.path == "/folder-models":
            try:
                self.send(HTTPStatus.OK, workspace.folder_models(self.query(url, "path") or ""))
            except WorkspaceError as error:
                self.send(HTTPStatus.NOT_FOUND, {"error": str(error)})
        elif url.path == "/about":
            # Повторный запуск ярлыка ищет по нему сервис своей папки
            self.send(HTTPStatus.OK, {"service": SERVICE, "folder": str(workspace.root), "pid": os.getpid()})
        elif url.path == "/dirs":
            try:
                self.send(HTTPStatus.OK, list_dirs(Path(self.query(url, "path") or workspace.root)))
            except WorkspaceError as error:
                self.send(HTTPStatus.NOT_FOUND, {"error": str(error)})
        elif url.path == "/std-pictures":
            self.send(HTTPStatus.OK, {"pictures": sources.std_library()})
        elif url.path in ("/config-pictures", "/config-types", "/config-styles", "/config-forms"):
            key, values = {"/config-pictures": ("pictures", sources.config_pictures),
                           "/config-types": ("types", sources.config_types),
                           "/config-styles": ("styles", sources.config_styles),
                           "/config-forms": ("forms", sources.config_forms)}[url.path]
            body = {key: values()}
            if sources.metadata is None:
                body["available"] = False
            self.send(HTTPStatus.OK, body)
        elif url.path == "/type-description":
            key = self.query(url, "key")
            found = sources.type_description(key)
            if found is None:
                self.send(HTTPStatus.NOT_FOUND, {"error": f"тип не найден в исходниках конфигурации: {key}"
                                                 if sources.metadata else "исходники конфигурации не указаны (--src)"})
                return
            self.send(HTTPStatus.OK, found)
        else:
            self.send(HTTPStatus.NOT_FOUND, {"error": f"нет такого адреса: {self.path}"})

    def do_POST(self):  # noqa: N802
        if not self.allowed():
            return
        url = urlsplit(self.path)
        if url.path == "/check":
            self.check(url)
        elif url.path == "/models":
            self.new_model()
        elif url.path in ("/groups", "/move", "/delete", "/restore"):
            self.folder_change(url)
        elif url.path == "/alive":
            body = self.body_object()
            if body is not None:
                self.server.lifetime.mark(body.get("tab") or "", body.get("file"), body.get("dirty"))
                self.send(HTTPStatus.OK, {})
        elif url.path == "/shutdown":
            self.stop_service()
        else:
            self.send(HTTPStatus.NOT_FOUND, {"error": f"нет такого адреса: {self.path}"})

    def stop_service(self):
        """«Завершить»: несохраненные правки в живых вкладках - 409 со списком макетов, пока страница
        не подтвердит (`force`); иначе ответ и остановка. Тело - JSON, как у правок: простая форма чужого сайта
        сервис не остановит."""
        body = self.body_object()
        if body is None:
            return
        lifetime = self.server.lifetime
        dirty = lifetime.dirty_files()
        if dirty and not body.get("force"):
            self.send(HTTPStatus.CONFLICT, {"error": "есть несохраненные правки", "dirty": dirty})
            return
        self.send(HTTPStatus.OK, {"stopped": True})
        self.wfile.flush()
        lifetime.stop(self.server, "«Завершить» на странице")

    def check(self, url):
        editor = self.target(url)
        if editor is None:
            return
        model = self.body_model()
        if model is None:
            return
        issues = editor.issues(model)
        # Правки против «было»; объединенное дерево - только по просьбе страницы: правки показываются
        tree = self.query(url, "tree") == "1"
        body = {"issues": issues, "pictures": editor.pictures(model)}
        body.update(editor.changes(model, issues, tree))
        self.send(HTTPStatus.OK, body)

    def new_model(self):
        """«Новая форма» `{file, kind}`, импорт перетащенного файла `{file, name, xml}` или формы из исходников
        `{file, object}`: 201; файл уже есть - 409; не тот путь, вид, не форма - 422."""
        body = self.body_object()
        if body is None:
            return
        workspace = self.workspace
        file = body.get("file") or ""
        try:
            if body.get("copyFrom"):
                result = workspace.copy(file, body["copyFrom"], body.get("fromFolder"), body.get("toFolder"))
            elif body.get("xml") is not None:
                result = workspace.import_text(file, body.get("name") or "", body["xml"])
            elif body.get("object"):
                result = workspace.import_object(file, body["object"])
            else:
                result = workspace.create(file, body.get("kind") or "")
        except FileExistsError as error:
            self.send(HTTPStatus.CONFLICT, {"error": str(error)})
            return
        except (WorkspaceError, ImportFailure) as error:
            self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            return
        self.send(HTTPStatus.CREATED, result)

    def folder_change(self, url):
        """Группы, перенос, корзина: `POST /groups {group}`, `DELETE /groups?group=`, `POST /move {file, to}`,
        `POST /delete {file}`, `POST /restore {trashed}`. Занято, не пусто, открыто в живой вкладке - 409;
        недопустимое имя, нет такого - 422."""
        workspace = self.workspace
        try:
            if self.command == "DELETE":
                result = workspace.delete_group(self.query(url, "group") or "")
            else:
                body = self.body_object()
                if body is None:
                    return
                if url.path == "/groups":
                    result = workspace.create_group(body.get("group") or "")
                elif url.path == "/restore":
                    result = workspace.restore(body.get("trashed") or "")
                else:
                    file = body.get("file") or ""
                    key = inside(workspace.root, file).relative_to(workspace.root.resolve()).as_posix()
                    if key in self.server.lifetime.open_files():
                        raise FileExistsError("макет открыт в конструкторе - закройте его вкладку и повторите")
                    result = (workspace.trash(file) if url.path == "/delete"
                              else workspace.move(file, body.get("to") or ""))
        except FileExistsError as error:
            self.send(HTTPStatus.CONFLICT, {"error": str(error)})
            return
        except (WorkspaceError, OSError) as error:
            self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
            return
        created = self.command == "POST" and url.path == "/groups"
        self.send(HTTPStatus.CREATED if created else HTTPStatus.OK, result)

    def do_DELETE(self):  # noqa: N802
        if not self.allowed():
            return
        url = urlsplit(self.path)
        if url.path == "/groups":
            self.folder_change(url)
        else:
            self.send(HTTPStatus.NOT_FOUND, {"error": f"нет такого адреса: {self.path}"})

    def do_PUT(self):  # noqa: N802
        if not self.allowed():
            return
        url = urlsplit(self.path)
        if url.path == "/model":
            self.save(url)
        elif url.path == "/tags":
            body = self.body_object()
            if body is None:
                return
            try:
                self.send(HTTPStatus.OK, self.workspace.set_tags(body.get("file") or "", body.get("tags")))
            except WorkspaceError as error:
                self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
        elif url.path in ("/settings", "/folder"):
            body = self.body_object()
            if body is None:
                return
            try:
                if url.path == "/settings" and ("projects" in body or "configuration" in body):
                    result = self.workspace.set_projects(body.get("projects"), body.get("configuration"),
                                                         body.get("extensions"))
                elif url.path == "/settings":
                    result = self.workspace.set_src(body.get("src"))
                else:
                    self.workspace.switch(Path(body.get("path") or ""))
                    result = self.workspace.info()
            except (WorkspaceError, ServeError) as error:
                self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
                return
            self.send(HTTPStatus.OK, result)
        else:
            self.send(HTTPStatus.NOT_FOUND, {"error": f"нет такого адреса: {self.path}"})

    def save(self, url):
        editor = self.target(url)
        if editor is None:
            return
        model = self.body_model()
        if model is None:
            return
        expected = self.headers.get("If-Match")
        if not expected:
            self.send(HTTPStatus.PRECONDITION_REQUIRED, {"error": "нет заголовка If-Match - версии файла"})
            return
        issues = editor.issues(model)
        if any(issue["blocking"] for issue in issues):
            self.send(HTTPStatus.UNPROCESSABLE_ENTITY, {"issues": issues})
            return
        with editor.lock:
            current = editor.read()[1]
            if current != expected:
                self.send(HTTPStatus.CONFLICT, {"error": "файл изменился на диске", "etag": current})
                return
            try:
                etag = editor.write(model)
            except OSError as error:
                self.send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"файл не записан: {error}"})
                return
        self.send(HTTPStatus.OK, {"issues": issues}, etag=etag)


def make_server(target: Editor | Workspace, port: int = None, lifetime: Lifetime | None = None) -> ThreadingHTTPServer:
    """Сервер на 127.0.0.1 для папки макетов (или папки одного макета - `Editor`, как раньше): явный порт -
    только он, иначе 8190 и следующие 20. `server.lifetime` - отметки вкладок и «Завершить»; следит за паузами
    `lifetime.watch(server)` - его включает команда `serve`, тесты API без него.

    Отказ в доступе (PermissionError) значит разное: на Windows так отвечает и занятый порт (WSAEACCES, а не
    «адрес занят»), и порт из зарезервированного системой диапазона; в песочнице агента без сети (Codex:
    `workspace-write` без `network_access`, проба 06.11.2026) - любой порт. Поэтому отказ - не повод
    остановить перебор: песочница - это когда отказали все порты и ни один не занят."""
    workspace = target if isinstance(target, Workspace) else Workspace.single(target)
    handler = type("EditorHandler", (Handler,), {"workspace": workspace})
    first = base_port()
    ports = [port] if port is not None else range(first, first + PORT_TRIES)
    denied = None
    busy = False
    for candidate in ports:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            server.lifetime = lifetime or Lifetime()
            return server
        except PermissionError as error:
            if port_listening(candidate):
                busy = True
            else:
                denied = denied or (candidate, error)
        except OSError:
            busy = True
    if denied and not busy:
        candidate, error = denied
        raise ServeError(f"порт {candidate} не открыть: {error.strerror} - нет доступа к сети (песочница агента?) "
                         "или порт зарезервирован системой; запустите serve в своем терминале, разрешите агенту "
                         "сеть или укажите другой --port") from error
    if port is not None:
        raise ServeError(f"порт {port} занят")
    raise ServeError(f"порты {first}-{first + PORT_TRIES - 1} заняты - укажите другой первый порт: "
                     f"{{\"port\": 9000}} в {folders.user_dir() / CONFIG_NAME}, переменная {PORT_ENV} или --port")


def port_listening(port: int) -> bool:
    """На порту 127.0.0.1 кто-то слушает - порт занят, а не запрещен."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def replace_with_retry(source: Path, target: Path, tries: int = 10, pause: float = 0.05):
    """`os.replace` с повтором: на Windows открытый кем-то на чтение файл не заменить, пока его не закроют."""
    for attempt in range(tries):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(pause)
