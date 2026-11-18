"""Сборка HTML макета и снимки PNG через headless Chrome.

HTML - один файл: шаблон `render/template.html`, в него вписаны `style.css`, `render.js`,
модель и словарь. Раскладку считает браузер: Chrome открывает страницу, `render.js`
пишет итог в `<pre id="fm-result">` - замечания раскладки, ошибки JS, размер окна,
закладки; `measure` читает его из `--dump-dom`. Снимок - `--screenshot` того же файла в
статичном состоянии (`#static&page=...`) с размером окна по замеру.

С прежней версией модели (`--before`) в странице три формы - «стало», «было» и объединенное
дерево правок (`fmlib.diff`); режим выбирает адрес (`mode=after|before|diff`), подсветку
правок снимает `nodiff`. Номера примечаний (`note`) рисует адрес `notes` - отдельным
снимком: основной снимок и эталон от примечаний не меняются.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from . import ROOT
from .diff import as_drawn

RENDER_DIR = ROOT / "render"
CHROME_ENV = "FORMMOCKUP_CHROME"
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
# Windows: установка для всех и для пользователя; переменные окружения, а не `C:\`
WINDOWS_ROOTS = ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]
WINDOWS_CHROME = r"Google\Chrome\Application\chrome.exe"
CHROME_COMMANDS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]
# Запасной движок - Edge (тот же Chromium, на Windows 11 есть всегда; решение владельца 07.11.2026)
EDGE_PATHS = ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
WINDOWS_EDGE = r"Microsoft\Edge\Application\msedge.exe"
EDGE_COMMANDS = ["microsoft-edge", "microsoft-edge-stable", "msedge"]
MEASURE_WINDOW = (2400, 3000)
SCALE = 2
TIMEOUT = 90


class ChromeError(Exception):
    """Chrome не отработал: код, тайм-аут или нет итога раскладки."""


@dataclass
class Layout:
    """Итог раскладки в браузере (`fm-result`)."""

    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    width: int = 0
    height: int = 0
    pages: list = field(default_factory=list)
    dom: dict = field(default_factory=dict)


def build_html(model: dict, dictionary: dict, title: str, pages: dict = None, before: dict = None,
               diff=None) -> str:
    """Самодостаточная страница: стили, скрипт и данные внутри. `pages` - закладки по умолчанию;
    `before` и `diff` (`fmlib.diff.Diff`) - прежняя версия и правки для режимов «Было / Стало / Правки»."""
    data = {"model": model, "dict": {"types": dictionary.get("types", {})}, "state": {"pages": pages or {}}}
    if before is not None and diff is not None:
        # Кнопки прежней версии - с ее командами: рендерер знает только команды новой (`model.commands`)
        data["before"] = as_drawn(before)
        data["diff"] = {"tree": diff.tree, "changes": [change.as_data() for change in diff.changes]}
    return assemble(title, data, ["style.css"], ["render.js"])


def build_editor_html(dictionary: dict, editor: dict, title: str) -> str:
    """Страница конструктора: шаблон и рендерер те же, поверх - `editor.css` и `editor.js`.
    Модели в странице нет - конструктор берет ее у сервера (`GET /model`) вместе с версией файла;
    `editor` - словарь, описание видов для панели свойств, группы свойств."""
    data = {"model": {"version": 1, "form": {}}, "dict": {"types": dictionary.get("types", {})},
            "state": {"pages": {}}, "editor": editor}
    return assemble(title, data, ["style.css", "editor.css"], ["alive.js", "render.js", "format.js", "editor.js"],
                    icon=True)


def build_home_html(data: dict) -> str:
    """Стартовая страница сервиса макетов: список макетов берет у сервера (`GET /models`);
    `data` - то, что не меняется за работу сервиса (виды форм)."""
    return assemble("Макеты форм", data, ["home.css"], ["alive.js", "home.js"], "home.html", icon=True)


def icon_links() -> str:
    """Значок страниц сервиса: вкладка и окно приложения в панели задач. SVG - основной, PNG - для
    окна, которому нужен растр; оба вписаны в страницу, отдельного запроса нет."""
    links = []
    for name, kind, extra in (("icon.svg", "image/svg+xml", ""), ("icon.png", "image/png", ' sizes="128x128"')):
        data = base64.b64encode((RENDER_DIR / name).read_bytes()).decode("ascii")
        links.append(f'<link rel="icon" type="{kind}"{extra} href="data:{kind};base64,{data}">')
    return "\n".join(links)


def assemble(title: str, data: dict, styles: list, scripts: list, template_name: str = "template.html",
             icon: bool = False) -> str:
    template = (RENDER_DIR / template_name).read_text(encoding="utf-8")
    style = "\n".join((RENDER_DIR / name).read_text(encoding="utf-8") for name in styles)
    script = "\n".join((RENDER_DIR / name).read_text(encoding="utf-8") for name in scripts)
    # `</` в JSON внутри <script> закрыл бы тег - экранируем
    data_text = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("{{TITLE}}", html.escape(title))
    if icon:
        page = page.replace("</title>", "</title>\n" + icon_links(), 1)
    page = page.replace("/*FM_STYLE*/", style, 1)
    page = page.replace("/*FM_DATA*/", data_text, 1)
    return page.replace("/*FM_SCRIPT*/", script, 1)


def windows_paths(relative: str) -> list:
    """Полные пути программы под каталогами установки Windows; нет переменной - нет пути.

    Относительный путь записан с обратной косой и делится по ней: склейка та же на любой ОС (тесты поиска на Mac)."""
    roots = [os.environ.get(name) for name in WINDOWS_ROOTS]
    return [str(Path(root, *relative.split("\\"))) for root in roots if root]


def find_chrome():
    """Путь к браузеру для снимков и список мест, где искали (для сообщения, если не нашли).

    Chrome, а без него Edge; что из них найдено - `is_edge`."""
    searched = []
    explicit = os.environ.get(CHROME_ENV)
    if explicit:
        # Явная настройка главнее поиска: неверный путь - «не найден», а не другой Chrome
        searched.append(f"{CHROME_ENV}={explicit}")
        return (explicit if Path(explicit).is_file() else None), searched
    places = [(CHROME_PATHS + windows_paths(WINDOWS_CHROME), CHROME_COMMANDS),
              (EDGE_PATHS + windows_paths(WINDOWS_EDGE), EDGE_COMMANDS)]
    for paths, commands in places:
        for path in paths:
            searched.append(path)
            if Path(path).is_file():
                return path, searched
        for command in commands:
            searched.append(command)
            found = shutil.which(command)
            if found:
                return found, searched
    return None, searched


def is_edge(browser: str) -> bool:
    """Найденный браузер - Edge, а не Chrome: эталон снимков снят на Chrome."""
    return "edge" in Path(browser).name.lower()


def browser_version(browser: str) -> str:
    """Версия браузера строкой, как ее печатает `--version` на Mac: «Google Chrome 156.0.8078.74».

    На Windows `chrome.exe --version` ничего не печатает, а каталогов версий рядом бывает два (ожидает
    обновление) - версия берется из ресурса версии самого файла: она и запустится."""
    if sys.platform == "win32":
        version = file_version(browser)
        name = "Microsoft Edge" if is_edge(browser) else "Google Chrome"
        return f"{name} {version}" if version else ""
    try:
        result = subprocess.run([browser, "--version"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def file_version(path: str) -> str:
    """Версия продукта из ресурса версии исполняемого файла Windows; не прочиталась - пусто."""
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("version")
    size = api.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(path, 0, size, buffer):
        return ""
    info = ctypes.c_void_p()
    length = wintypes.UINT()
    if not api.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)):
        return ""
    # VS_FIXEDFILEINFO: подпись, версия структуры, затем dwFileVersionMS / LS, dwProductVersionMS / LS
    fixed = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD * 6)).contents
    high, low = fixed[4], fixed[5]
    return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"


def state_hash(pages: dict = None, static: bool = True, actions: list = None, expand: bool = None,
               flags: list = None) -> str:
    """Адрес состояния страницы. Снимок (`static`) по умолчанию разворачивает свернутые группы - для ТЗ.
    `flags` - прочие части адреса как есть: `mode=after`, `nodiff`."""
    parts = ["static"] if static else []
    if static if expand is None else expand:
        parts.append("expand")
    parts += flags or []
    if pages:
        parts.append("page=" + quote(";".join(f"{key}:{value}" for key, value in pages.items())))
    if actions:
        parts.append("act=" + quote(";".join(actions)))
    return "&".join(parts)


def run_chrome(chrome: str, arguments: list) -> str:
    # Профиль - свой каталог и удаление без ошибок: на Windows процесс отчетов о сбоях Chrome бывает
    # еще держит файлы после выхода, и `TemporaryDirectory` упал бы на очистке
    profile = tempfile.mkdtemp(prefix="formmockup-chrome-")
    command = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions", "--disable-crash-reporter",
        f"--user-data-dir={profile}",
    ] + arguments
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ChromeError(f"Chrome не ответил за {TIMEOUT} с")
    finally:
        remove_tree(profile)
    if result.returncode != 0:
        raise ChromeError(f"Chrome завершился с кодом {result.returncode}: {result.stderr.strip()[-500:]}")
    return result.stdout


def remove_tree(path, tries: int = 20, pause: float = 0.1):
    """Удалить каталог без ошибки: на Windows файлы профиля Chrome еще держит его процесс отчетов о сбоях - несколько
    попыток с паузой, иначе каталог оставался во временной папке после каждого снимка."""
    for _ in range(tries):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(pause)


def measure(chrome: str, html_path: Path, pages: dict = None, actions: list = None, expand: bool = True,
            flags: list = None) -> Layout:
    """Раскладка страницы в браузере: замечания, ошибки JS, размер, закладки.

    `actions` - щелчки после отрисовки (`tab:Панель:Закладка`, `toggle:Группа`); итог
    `dom` - текущие закладки и свернутые группы после них. `expand` - свернутые группы развернуты, как на
    снимке; без него - как откроется страница в браузере.
    """
    url = html_path.resolve().as_uri() + "#" + state_hash(pages, actions=actions, expand=expand, flags=flags)
    width, height = MEASURE_WINDOW
    dom = run_chrome(chrome, [f"--window-size={width},{height}", "--virtual-time-budget=5000", "--dump-dom", url])
    found = re.search(r'<pre id="fm-result"[^>]*>(.*?)</pre>', dom, re.S)
    if not found or not found.group(1).strip():
        raise ChromeError("страница не отдала итог раскладки (fm-result пуст)")
    data = json.loads(html.unescape(found.group(1)))
    return Layout(data.get("notes", []), data.get("errors", []), data.get("width", 0),
                  data.get("height", 0), data.get("pages", []), data.get("dom", {}))


def screenshot(chrome: str, html_path: Path, png_path: Path, layout: Layout, pages: dict = None,
               flags: list = None):
    url = html_path.resolve().as_uri() + "#" + state_hash(pages, flags=flags)
    width = max(layout.width, 200)
    height = max(layout.height, 100)
    run_chrome(chrome, [f"--window-size={width},{height}", f"--force-device-scale-factor={SCALE}",
                        "--virtual-time-budget=5000", f"--screenshot={png_path.resolve()}", url])
    if not png_path.is_file():
        raise ChromeError(f"снимок не создан: {png_path}")


def tab_states(layout: Layout, base: dict, changed_only: bool = False, noted_only: bool = False) -> list:
    """Закладки, не показанные по умолчанию: (панель, закладка, состояние страниц для снимка).
    `changed_only` - только закладки с правками (режим «Правки»), `noted_only` - с примечаниями."""
    states = []
    for item in layout.pages:
        if item.get("current") or changed_only and not item.get("changes") or noted_only and not item.get("notes"):
            continue
        pages = dict(base)
        for link in item.get("chain", []):
            parent, page = link.split(":", 1)
            pages[parent] = page
        pages[item["pages"]] = item["page"]
        states.append((item["pages"], item["page"], pages))
    return states
