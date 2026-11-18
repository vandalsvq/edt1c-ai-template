"""Запуск сервиса макетов для человека: окно приложения, повторный запуск на ту же
папку, запуск ярлыком без окна консоли.

- Окно - ключ `--app=<адрес>` браузера, найденного тем же поиском, что у снимков (`render.find_chrome`: Chrome,
  без него Edge); на Mac - `open -na <приложение> --args --app=...`. Окно открывается в обычном профиле
  пользователя, сервер его не ждет. Нет ни Chrome, ни Edge - вкладка браузера по умолчанию (`webbrowser`).
- Сервис на папку уже запущен - его находит `GET /about` на портах сервиса: второй сервер не поднимается.
- Ярлык (`serve --shortcut`) запускает сервис отдельным процессом без окна консоли (`--detached`) и ждет строку
  с адресом: ошибка запуска остается в окне ярлыка, а работающий сервис окна не держит. Окно ярлыка на Windows -
  заставка (`splash`), а не консоль.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import ROOT, render
from .server import PORT_TRIES, SERVICE, base_port, port_listening
from .splash import console_python
from .workspace import user_dir

SCRIPT = ROOT / "formmockup.py"
LOG_NAME = "serve.log"
# Строка готовности `serve`: «Макеты: http://127.0.0.1:<порт>/...» или «Конструктор: ...»
READY_MARK = "http://127.0.0.1:"
CHROME_URL = "https://www.google.com/chrome/"
NO_BROWSER_NOTE = ("Chrome и Edge не найдены - страница откроется вкладкой браузера по умолчанию. Для отдельного "
                   f"окна и снимков PNG поставьте Google Chrome: {CHROME_URL}")


# Окно приложения

def app_command(browser: str, url: str, platform: str = sys.platform) -> list:
    """Команда окна приложения: на Mac - через `open -na` пакета `.app` (сам исполняемый файл внутри пакета
    второй экземпляр не откроет), иначе - браузер с `--app`."""
    if platform == "darwin":
        bundle = next((parent for parent in PurePosixPath(browser).parents if parent.suffix == ".app"), None)
        if bundle is not None:
            return ["open", "-na", str(bundle), "--args", f"--app={url}"]
    return [browser, f"--app={url}"]


def detached() -> dict:
    """Параметры `Popen` процесса, который живет сам по себе: без окна консоли и сигналов родителя."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def open_window(url: str, browser: str | None = None) -> str:
    """Открыть страницу окном приложения; `browser` - найденный заранее (None - искать). Итог: `app` - окно,
    `tab` - вкладка браузера по умолчанию."""
    if browser is None:
        browser = render.find_chrome()[0]
    if browser:
        try:
            subprocess.Popen(app_command(browser, url), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **detached())
            return "app"
        except OSError:
            pass
    webbrowser.open(url)
    return "tab"


# Повторный запуск

def same_path(first, second) -> bool:
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def about(port: int) -> dict | None:
    """Ответ `GET /about` сервиса на порту; не сервис макетов - None. Без прокси: `http.client`, а не `urllib`."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/about")
        response = connection.getresponse()
        data = json.loads(response.read().decode("utf-8")) if response.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()
    return data if isinstance(data, dict) and data.get("service") == SERVICE else None


def find_service(target: Path) -> tuple | None:
    """Запущенный сервис для папки или модели: (адрес `http://127.0.0.1:<порт>/`, его папка) или None. Папка -
    сервис ровно на нее; модель - сервис, в папке которого она лежит (ближайший): перетащенная на ярлык модель из
    подкаталога открывается в уже запущенном сервисе."""
    target = Path(os.path.realpath(target))
    found = None
    first = base_port()
    for port in range(first, first + PORT_TRIES):
        if not port_listening(port):
            continue
        data = about(port)
        if not data or not isinstance(data.get("folder"), str):
            continue
        folder = Path(os.path.realpath(data["folder"]))
        if target.is_dir():
            matches = same_path(folder, target)
        else:
            matches = os.path.normcase(str(target)).startswith(os.path.normcase(str(folder)) + os.sep)
        if matches and (found is None or len(str(folder)) > len(str(found[1]))):
            found = (f"http://127.0.0.1:{port}/", folder)
    return found


# Ярлык

def log_path() -> Path:
    return user_dir() / LOG_NAME


def log(text: str):
    """Запись в журнал сервиса ярлыка: трассировка человеку не показывается, но не теряется."""
    try:
        user_dir().mkdir(exist_ok=True)
        with open(log_path(), "a", encoding="utf-8", newline="\n") as file:
            file.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text.rstrip()}\n")
    except OSError:
        pass


def spawn(arguments: list) -> int:
    """Сервис отдельным процессом без окна (`serve ... --detached`): вывод до строки с адресом - в окно ярлыка;
    процесс завершился раньше - его код (ошибка запуска уже напечатана)."""
    command = [console_python(), str(SCRIPT), "serve", *arguments, "--detached"]
    if sys.platform == "win32":
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        flags = {"start_new_session": True}
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               encoding="utf-8", errors="replace", **flags)
    for line in process.stdout:
        print(line.rstrip("\n"), flush=True)
        if READY_MARK in line:
            return 0
    return process.wait() or 2


def detach_output():
    """После строки с адресом: вывод - в журнал, канал к окну ярлыка закрывается (оно ждет только эту строку)."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        user_dir().mkdir(exist_ok=True)
        target = open(log_path(), "a", encoding="utf-8", newline="\n")
    except OSError:
        target = open(os.devnull, "w", encoding="utf-8")
    os.dup2(target.fileno(), 1)
    os.dup2(target.fileno(), 2)
