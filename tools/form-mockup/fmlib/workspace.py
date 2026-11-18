"""Папка макетов: поиск моделей, настройки папки, обзор каталогов.

Сервис конструктора обслуживает папку, а не один файл: стартовая страница показывает модели макетов в папке
и подкаталогах, к папке запоминается путь к исходникам конфигурации (`.form-mockup.json`). Здесь - то, что
не зависит от HTTP: сервер (`fmlib.server`) берет отсюда списки и проверки.
"""

from __future__ import annotations

import json
import os
import string
import sys
from datetime import datetime
from pathlib import Path

from . import write_text_lf
from .metadata import FOLDERS, long_path

SETTINGS_NAME = ".form-mockup.json"
# Последняя папка ярлыка - у пользователя, не в репозитории
USER_DIR_NAME = ".form-mockup"
LAST_NAME = "last.json"
# Каталоги, которые поиск моделей не просматривает: вывод `render`, служебные, зависимости
SKIP_DIRS = {"out", "node_modules", "__pycache__", "venv", "bin", "obj"}
MAX_FILES = 20000           # предел просмотра: папку макетов по ошибке указали на диск целиком
MAX_MODEL_BYTES = 10 * 1024 * 1024
KIND_BY_FOLDER = {folder: kind for kind, folder in FOLDERS.items()}


class WorkspaceError(Exception):
    """Путь вне папки макетов, не каталог, не исходники - текст для пользователя."""


# Модели

def is_model(data) -> bool:
    """JSON - модель макета: `version` и `form` (схема), имя файла не важно."""
    return isinstance(data, dict) and isinstance(data.get("version"), int) and isinstance(data.get("form"), dict)


def skipped(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS


def find_models(root: Path) -> list:
    """Модели макетов в папке и подкаталогах: путь от папки (через `/`), заголовок формы, вид, дата изменения.

    Модель распознается по содержимому; каталоги вывода `render` (`out`), скрытые и служебные не просматриваются."""
    found = []
    seen = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not skipped(name))
        for name in sorted(files):
            if not name.lower().endswith(".json") or name.startswith("."):
                continue
            seen += 1
            if seen > MAX_FILES:
                return found
            path = Path(folder) / name
            try:
                if path.stat().st_size > MAX_MODEL_BYTES:
                    continue
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not is_model(data):
                continue
            form = data["form"]
            title = form.get("title") if isinstance(form.get("title"), str) else ""
            relative = path.relative_to(root)
            found.append({
                "file": relative.as_posix(),
                "title": title or path.stem,
                "kind": form.get("formKind") or "",
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                # Группа - подкаталог от папки, метки - из модели
                "group": relative.parent.as_posix() if relative.parent != Path(".") else "",
                "tags": clean_tags(data.get("tags")),
            })
    return found


def inside(root: Path, file: str) -> Path:
    """Файл модели по пути от папки; путь вне папки или не `.json` - WorkspaceError."""
    if not file or not file.lower().endswith(".json"):
        raise WorkspaceError(f"ожидается файл .json: {file}")
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkspaceError(f"файл вне папки макетов: {file}")
    return path


# Группы и метки

# Символы, недопустимые в имени каталога Windows; на Mac годятся все, кроме `/`, - правило одно на обе ОС
BAD_NAME_CHARS = set('<>:"\\|?*')


def clean_tags(value) -> list:
    """Метки модели: строки без пробелов по краям, без пустых и повторов, в исходном порядке."""
    tags = []
    for tag in value if isinstance(value, list) else []:
        if isinstance(tag, str) and tag.strip() and tag.strip() not in tags:
            tags.append(tag.strip())
    return tags


def group_path(root: Path, group: str) -> Path:
    """Каталог группы по пути от папки (`/` - вложенность); недопустимое имя - WorkspaceError, пусто - корень."""
    parts = [part.strip() for part in (group or "").replace("\\", "/").split("/")]
    if parts == [""]:
        return root
    for part in parts:
        if not part or part in (".", "..") or part.startswith(".") or part.endswith((".", " ")) \
                or part in SKIP_DIRS or BAD_NAME_CHARS & set(part) or any(ord(char) < 32 for char in part):
            raise WorkspaceError(f"недопустимое имя группы: {group}")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise WorkspaceError(f"группа вне папки макетов: {group}")
    return path


def list_groups(root: Path, models: list) -> list:
    """Группы папки: подкаталоги с макетами и созданные группы из настроек, которые еще есть на диске."""
    groups = {model["group"] for model in models if model["group"]}
    for group in read_settings(root).get("groups") or []:
        if isinstance(group, str) and (root / group).is_dir():
            groups.add(group)
    return sorted(groups, key=str.casefold)


def free_path(path: Path) -> Path:
    """Свободное имя рядом: `имя.json`, `имя-2.json`, `имя-3.json`..."""
    if not path.exists():
        return path
    number = 2
    while path.with_name(f"{path.stem}-{number}{path.suffix}").exists():
        number += 1
    return path.with_name(f"{path.stem}-{number}{path.suffix}")


# Исходники конфигурации

def source_kind(path: Path) -> str | None:
    """Формат исходников: `edt` (`Configuration/Configuration.mdo`), `designer` (`Configuration.xml`) или None."""
    try:
        if (path / "Configuration" / "Configuration.mdo").is_file():
            return "edt"
        if (path / "Configuration.xml").is_file():
            return "designer"
    except OSError:
        return None
    return None


def suggest_src(root: Path) -> Path | None:
    """Исходники рядом с папкой: папка или ее предок - исходники, или в предке есть `src` проекта EDT."""
    for ancestor in [root, *root.parents]:
        for candidate in (ancestor, ancestor / "src"):
            if source_kind(candidate):
                return candidate
    return None


def repository_root(path: Path) -> Path | None:
    """Корень репозитория git, в котором лежит путь; не в репозитории - None."""
    for ancestor in [path, *path.parents]:
        if (ancestor / ".git").exists():
            return ancestor
    return None


def stored_path(root: Path, src: Path) -> str:
    """Путь исходников для настроек: относительный от папки, если оба в одном репозитории (папка работает на
    обеих машинах), иначе абсолютный."""
    repository = repository_root(root.resolve())
    src = src.resolve()
    if repository and src.is_relative_to(repository):
        return Path(os.path.relpath(src, root.resolve())).as_posix()
    return str(src)


def read_settings(root: Path) -> dict:
    """Настройки папки; файла нет или он испорчен - пусто."""
    try:
        data = json.loads((root / SETTINGS_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(root: Path, settings: dict):
    write_text_lf(root / SETTINGS_NAME, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")


def settings_src(root: Path) -> Path | None:
    """Исходники из настроек папки; путь больше не исходники - None (сервис работает без них)."""
    value = read_settings(root).get("src")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    path = (root / path).resolve() if not path.is_absolute() else path
    return path if source_kind(path) else None


def settings_path(root: Path, value) -> Path | None:
    """Путь из настроек: относительный - от папки макетов."""
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return (root / path).resolve() if not path.is_absolute() else path


def settings_sources(root: Path) -> tuple:
    """Исходники из настроек папки: (папка проектов, конфигурация, расширения). Прежний `src` - одиночные
    исходники без папки проектов; путь, который больше не исходники, пропускается."""
    settings = read_settings(root)
    if "projects" not in settings:
        return None, settings_src(root), []
    folder = settings_path(root, settings.get("projects"))
    configuration = settings_path(root, settings.get("configuration"))
    extensions = [settings_path(root, value) for value in settings.get("extensions") or [] if isinstance(value, str)]
    configuration = configuration if configuration and source_kind(configuration) else None
    extensions = [path for path in extensions if path and source_kind(path)] if configuration else []
    return (folder if folder and folder.is_dir() else None), configuration, extensions


def config_forms(src: Path, edt: bool) -> list:
    """Формы конфигурации для импорта из дерева объектов: ключ `Вид.Объект.Форма`, вид, объект, форма, путь.

    EDT - `<Каталог>/<Объект>/Forms/<Форма>/Form.form`, общая форма - `CommonForms/<Форма>/Form.form`;
    выгрузка конфигуратора - то же с `Ext/Form.xml`."""
    tail = ["Form.form"] if edt else ["Ext", "Form.xml"]
    result = []
    # Формы глубоких объектов выгрузки - путь длиннее 260 символов: на Windows - через префикс `\\?\`
    for folder, kind in sorted(KIND_BY_FOLDER.items(), key=lambda item: item[1]):
        base = src / folder
        if not base.is_dir():
            continue
        if kind == "CommonForm":
            for form in sorted(base.iterdir()):
                path = form.joinpath(*tail)
                if long_path(path).is_file():
                    result.append({"key": f"CommonForm.{form.name}", "kind": kind, "object": "", "form": form.name,
                                   "path": str(path)})
            continue
        for owner in sorted(base.iterdir()):
            forms = owner / "Forms"
            if not long_path(forms).is_dir():
                continue
            for form in sorted(long_path(forms).iterdir()):
                path = forms / form.name / Path(*tail)
                if long_path(path).is_file():
                    result.append({"key": f"{kind}.{owner.name}.{form.name}", "kind": kind, "object": owner.name,
                                   "form": form.name, "path": str(path)})
    return result


# Обзор каталогов

def drive_roots() -> list:
    """Корни для обзора: диски Windows или `/` и тома Mac."""
    if sys.platform == "win32":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.isdir(f"{letter}:\\")]
    roots = ["/"]
    volumes = Path("/Volumes")
    if volumes.is_dir():
        roots += [str(path) for path in sorted(volumes.iterdir()) if path.is_dir()]
    return roots


def list_dirs(path: Path) -> dict:
    """Подкаталоги для выбора папки и исходников: имя, путь, признак исходников; скрытые - нет."""
    path = path.resolve()
    if not path.is_dir():
        raise WorkspaceError(f"не каталог: {path}")
    dirs = []
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError as error:
        raise WorkspaceError(f"каталог не прочитать: {path} - {error.strerror or error}")
    for child in children:
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
        except OSError:
            continue
        dirs.append({"name": child.name, "path": str(child), "source": source_kind(child)})
    parent = path.parent if path.parent != path else None
    return {"path": str(path), "parent": str(parent) if parent else None, "source": source_kind(path),
            "dirs": dirs, "roots": drive_roots(), "home": str(Path.home())}


# Последняя папка

def user_dir() -> Path:
    return Path.home() / USER_DIR_NAME


def remember_folder(root: Path):
    """Запомнить папку макетов для ярлыка без аргументов; не записалось - не беда."""
    try:
        user_dir().mkdir(exist_ok=True)
        write_text_lf(user_dir() / LAST_NAME, json.dumps({"folder": str(root.resolve())}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def last_folder() -> Path | None:
    try:
        value = json.loads((user_dir() / LAST_NAME).read_text(encoding="utf-8")).get("folder")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    return Path(value) if isinstance(value, str) and Path(value).is_dir() else None
