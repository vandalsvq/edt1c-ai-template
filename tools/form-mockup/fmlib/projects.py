"""Папка проектов: конфигурации и расширения 1С в любой папке.

Вместо одного каталога исходников указывается папка, где лежат и конфигурация, и ее расширения: проект EDT,
репозиторий, воркспейс EDT, каталог выгрузок конфигуратора. Здесь - поиск корней исходников по XML
конфигураций, признак расширения и сопоставление расширения с его основой по заимствованным объектам. HTTP и
объединение метаданных - в `fmlib.server` и `fmlib.metadata`.

Признаки (проверены на стенде 07.11.2026):

- корень исходников EDT - `Configuration/Configuration.mdo`, выгрузки конфигуратора - `Configuration.xml`; внутрь
  найденного корня поиск не спускается (в формах выгрузки пути длиннее 260 символов);
- расширение - назначение расширения (`configurationExtensionPurpose` EDT, `ConfigurationExtensionPurpose`
  выгрузки) в корне конфигурации, у основы его нет;
- заимствованный объект (`objectBelonging` / `ObjectBelonging` = `Adopted`) - свой uuid и никакой ссылки на объект
  основы: основа - конфигурация, где есть все заимствованные объекты по виду (каталогу) и имени;
- воркспейс EDT: проекты из других мест - путь после `URI//` в
  `.metadata/.plugins/org.eclipse.core.resources/.projects/<проект>/.location`; основа проекта EDT -
  подсказка `Base-Project` в `DT-INF/PROJECT.PMF`, имя проекта - `<name>` в `.project`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .metadata import MD, designer_text, edt_text, long_path
from .workspace import repository_root, skipped, source_kind

MAX_DEPTH = 4
MAX_DIRS = 5000             # предел обхода: папку по ошибке указали на диск целиком
LOCATIONS = Path(".metadata") / ".plugins" / "org.eclipse.core.resources" / ".projects"
LOCATION_URI = re.compile(rb"URI//(file:[^\x00]+)")
BASE_PROJECT = re.compile(r"^Base-Project:\s*(.+?)\s*$", re.M)
ADOPTED_EDT = "<objectBelonging>Adopted</objectBelonging>"
ADOPTED_DESIGNER = "<ObjectBelonging>Adopted</ObjectBelonging>"
PURPOSES = {"Customization": "исправление", "Patch": "исправление", "AddOn": "дополнение",
            "Adaptation": "адаптация"}


@dataclass
class Project:
    """Корень исходников: конфигурация или расширение, EDT или выгрузка конфигуратора."""

    src: Path
    edt: bool
    name: str = ""
    synonym: str | None = None
    purpose: str | None = None          # назначение расширения; у конфигурации - None
    prefix: str | None = None
    project: str = ""                   # имя проекта EDT (`.project`) или каталога выгрузки
    base_hint: str | None = None        # `Base-Project` проекта EDT
    base: Path | None = None            # src основы расширения, если она одна
    candidates: list = field(default_factory=list)   # src конфигураций, где есть все заимствованные объекты
    adopted_cache: set | None = None

    @property
    def extension(self) -> bool:
        return self.purpose is not None

    def adopted(self) -> set:
        """Заимствованные объекты расширения: (каталог вида, имя); у конфигурации - пусто."""
        if self.adopted_cache is None:
            self.adopted_cache = adopted_objects(self.src, self.edt) if self.extension else set()
        return self.adopted_cache

    def as_data(self) -> dict:
        return {"src": str(self.src), "format": "edt" if self.edt else "designer", "name": self.name,
                "synonym": self.synonym or "", "project": self.project, "extension": self.extension,
                "purpose": PURPOSES.get(self.purpose or "", self.purpose or ""), "prefix": self.prefix or "",
                "base": str(self.base) if self.base else None, "baseProject": self.base_hint or "",
                "candidates": [str(path) for path in self.candidates]}


# Поиск

def source_roots(folder: Path, depth: int = MAX_DEPTH) -> list:
    """Корни исходников в папке и ее подкаталогах до `depth` уровней; внутрь корня поиск не спускается. Папка -
    воркспейс EDT: еще проекты, подключенные в него из других мест."""
    found = []
    visited = 0

    def walk(path: Path, level: int):
        nonlocal visited
        visited += 1
        if visited > MAX_DIRS:
            return
        if source_kind(path):
            found.append(path)
            return
        if level >= depth:
            return
        try:
            children = sorted((child for child in path.iterdir() if child.is_dir() and not skipped(child.name)),
                              key=lambda child: child.name.lower())
        except OSError:
            return
        for child in children:
            walk(child, level + 1)

    walk(folder, 0)
    for project in linked_projects(folder):
        for candidate in (project / "src", project):
            if source_kind(candidate):
                found.append(candidate)
                break
    unique = {}
    for path in found:
        unique.setdefault(str(path.resolve()).lower(), path.resolve())
    return list(unique.values())


def linked_projects(folder: Path) -> list:
    """Проекты воркспейса EDT, лежащие вне его: каталоги из `.location` (`URI//file:/D:/GIT/...`)."""
    base = folder / LOCATIONS
    result = []
    try:
        entries = sorted(base.iterdir()) if base.is_dir() else []
    except OSError:
        return result
    for entry in entries:
        try:
            data = (entry / ".location").read_bytes()
        except OSError:
            continue
        found = LOCATION_URI.search(data)
        if not found:
            continue
        path = file_uri_path(found.group(1).decode("utf-8", errors="replace"))
        if path is not None and path.is_dir():
            result.append(path)
    return result


def file_uri_path(uri: str) -> Path | None:
    """`file:/D:/GIT/project/Tests` → путь; на Mac `file:/Users/...` → `/Users/...`."""
    if not uri.startswith("file:"):
        return None
    text = unquote(uri[5:])
    while text.startswith("//"):
        text = text[1:]
    if re.match(r"^/[A-Za-z]:/", text):
        text = text[1:]
    return Path(text)


def find_projects(folder: Path, depth: int = MAX_DEPTH) -> list:
    """Конфигурации и расширения папки, расширения - с основой (одна подходящая конфигурация или подсказка
    `Base-Project`); по имени: сначала конфигурации, потом расширения."""
    projects = [read_project(path) for path in source_roots(folder, depth)]
    projects = [project for project in projects if project is not None]
    match_bases(projects)
    return sorted(projects, key=lambda project: (project.extension, project.name.lower(), str(project.src).lower()))


def suggest_projects(root: Path) -> Path | None:
    """Ближайшая к папке макетов папка с конфигурациями: сама папка или ее предок. Предки - до корня
    репозитория git, вне репозитория - только родитель; домашний каталог и корень диска не просматриваются, поиск у
    предка неглубокий - чтобы не обходить диск целиком."""
    root = root.resolve()
    repository = repository_root(root)
    ancestors = [root, *root.parents]
    ancestors = ancestors[:ancestors.index(repository) + 1] if repository else ancestors[:2]
    for ancestor in ancestors:
        if ancestor == Path.home() or ancestor.parent == ancestor:
            break
        if source_roots(ancestor, 2):
            return ancestor
    return None


# Корень конфигурации

def read_project(src: Path) -> Project | None:
    edt = source_kind(src) == "edt"
    try:
        if edt:
            root = ET.parse(long_path(src / "Configuration" / "Configuration.mdo")).getroot()
            extension = root.find("extension")
            project = Project(src, True, root.findtext("name") or src.parent.name, edt_text(root, "synonym"),
                              root.findtext("configurationExtensionPurpose"), root.findtext("namePrefix"))
            if project.purpose is None and extension is not None:
                project.purpose = "Customization"
            project.project = edt_project_name(src.parent)
            project.base_hint = base_project(src.parent)
        else:
            root = ET.parse(long_path(src / "Configuration.xml")).getroot()
            body = next(iter(root), None)
            properties = body.find(MD + "Properties") if body is not None else None
            if properties is None:
                return None
            project = Project(src, False, properties.findtext(MD + "Name") or src.name,
                              designer_text(properties.find(MD + "Synonym")),
                              properties.findtext(MD + "ConfigurationExtensionPurpose"),
                              properties.findtext(MD + "NamePrefix"), src.name)
    except (OSError, ET.ParseError):
        return None
    return project


def project_label(src: Path) -> str:
    """Подпись исходников в окне импорта: имя проекта EDT или каталога выгрузки."""
    return edt_project_name(src.parent) if source_kind(src) == "edt" else src.name


def edt_project_name(folder: Path) -> str:
    """Имя проекта EDT - из `.project` (каталог может называться иначе: `Project.Tests` - проект `Tests`)."""
    try:
        found = re.search(r"<name>([^<]+)</name>", (folder / ".project").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        found = None
    return found.group(1).strip() if found else folder.name


def base_project(folder: Path) -> str | None:
    try:
        found = BASE_PROJECT.search((folder / "DT-INF" / "PROJECT.PMF").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return found.group(1) if found else None


# Заимствованные объекты и основа

def adopted_objects(src: Path, edt: bool) -> set:
    """(каталог вида, имя) заимствованных объектов: EDT - `<Каталог>/<Имя>/<Имя>.mdo`, выгрузка - `<Каталог>/<Имя>.xml`
    с принадлежностью `Adopted`. Корень конфигурации расширения тоже заимствован - он не в счет."""
    result = set()
    marker = ADOPTED_EDT if edt else ADOPTED_DESIGNER
    try:
        folders = [path for path in src.iterdir() if path.is_dir() and path.name != "Configuration"]
    except OSError:
        return result
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            file = entry / f"{entry.name}.mdo" if edt else entry
            if not edt and entry.suffix != ".xml":
                continue
            try:
                head = long_path(file).read_text(encoding="utf-8-sig", errors="replace")[:4000]
            except OSError:
                continue
            if marker in head:
                result.add((folder.name, entry.name if edt else entry.stem))
    return result


def has_object(project: Project, folder: str, name: str) -> bool:
    path = project.src / folder / name / f"{name}.mdo" if project.edt else project.src / folder / f"{name}.xml"
    try:
        return long_path(path).is_file()
    except OSError:
        return False


def match_bases(projects: list):
    """Основа каждого расширения: конфигурация, в которой есть все его заимствованные объекты; подходят несколько -
    подсказка `Base-Project`, без нее основа не выбрана (выбор пользователя)."""
    configurations = [project for project in projects if not project.extension]
    for extension in (project for project in projects if project.extension):
        adopted = extension.adopted()
        extension.candidates = [configuration.src for configuration in configurations
                                if all(has_object(configuration, folder, name) for folder, name in adopted)]
        if len(extension.candidates) == 1:
            extension.base = extension.candidates[0]
        elif extension.base_hint:
            hinted = [configuration.src for configuration in configurations
                      if configuration.src in extension.candidates and configuration.project == extension.base_hint]
            extension.base = hinted[0] if len(hinted) == 1 else None
