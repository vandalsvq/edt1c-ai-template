"""Запуск сервиса для человека: автоостановка, «Завершить», окно приложения, повторный
запуск на ту же папку, ярлык Windows.

Сценарии страницы в headless Chrome пропускаются, если Chrome не найден; ярлык `.cmd` - только на Windows.
Команды `serve` идут с коротким ожиданием (`FORMMOCKUP_AUTOSTOP`) и своим домашним каталогом: последняя папка
ярлыка не попадает в профиль того, кто гоняет тесты.
"""

import html
import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fmlib import launch, render, splash  # noqa: E402
from fmlib.server import AUTOSTOP_ENV, Lifetime, port_listening  # noqa: E402
from test_workspace import ServiceServer, models_folder, temporary_folder  # noqa: E402

CLI = ROOT / "formmockup.py"
SHORTCUT = ROOT / "Открыть макеты.cmd"
CHROME, _ = render.find_chrome()
URL = re.compile(r"http://127\.0\.0\.1:(\d+)/\S*")


class Clock:
    """Время для `Lifetime` - вручную."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LifetimeTest(unittest.TestCase):
    """Правила автоостановки без сервера."""

    def test_waits_for_first_tab(self):
        clock = Clock()
        lifetime = Lifetime(60, 1800, clock)
        clock.now += 1799
        self.assertIsNone(lifetime.expired())
        clock.now += 2
        self.assertIn("так и не открылась", lifetime.expired())

    def test_idle_after_last_mark(self):
        clock = Clock()
        lifetime = Lifetime(60, 1800, clock)
        lifetime.mark("a")
        clock.now += 40
        lifetime.mark("b", "zakaz.json")
        clock.now += 59
        self.assertIsNone(lifetime.expired(), "вкладка b отметилась меньше минуты назад")
        clock.now += 2
        self.assertIn("больше 60 с", lifetime.expired())

    def test_dirty_files(self):
        clock = Clock()
        lifetime = Lifetime(60, 1800, clock)
        lifetime.mark("a", "zakaz.json", True)
        lifetime.mark("b", "spisok.json", False)
        lifetime.mark("c", "старый.json", True)
        clock.now += 30
        lifetime.mark("a", "zakaz.json", True)
        lifetime.mark("b", "spisok.json", False)
        clock.now += 40
        lifetime.mark("a", "zakaz.json", True)
        self.assertEqual(lifetime.dirty_files(), ["zakaz.json"], "вкладка c закрыта - ее правки не в счет")
        lifetime.mark("a", "zakaz.json", False)
        self.assertEqual(lifetime.dirty_files(), [])

    def test_from_env(self):
        with mock.patch.dict(os.environ, {AUTOSTOP_ENV: "2,5"}):
            lifetime = Lifetime.from_env()
        self.assertEqual((lifetime.idle, lifetime.first), (2, 5))
        with mock.patch.dict(os.environ, {AUTOSTOP_ENV: "чушь"}):
            lifetime = Lifetime.from_env()
        self.assertEqual((lifetime.idle, lifetime.first), (60, 1800))


class ServiceLifeApiTest(unittest.TestCase):
    """`POST /alive`, `POST /shutdown`, `GET /about`."""

    def setUp(self):
        self.folder = models_folder(self)
        self.service = ServiceServer(self, self.folder)
        self.lifetime = self.service.server.lifetime

    def test_about(self):
        status, data, _ = self.service.request("GET", "/about")
        self.assertEqual(status, 200)
        self.assertEqual(data["service"], "form-mockup")
        self.assertEqual(data["folder"], str(self.folder))

    def test_alive(self):
        status, _, _ = self.service.request("POST", "/alive", {"tab": "t1", "file": "zakaz.json", "dirty": True})
        self.assertEqual(status, 200)
        self.assertEqual(self.lifetime.dirty_files(), ["zakaz.json"])

    def test_shutdown_warns_about_unsaved(self):
        self.service.request("POST", "/alive", {"tab": "t1", "file": "zakaz.json", "dirty": True})
        status, data, _ = self.service.request("POST", "/shutdown", {})
        self.assertEqual(status, 409)
        self.assertEqual(data["dirty"], ["zakaz.json"])
        self.assertIsNone(self.lifetime.reason)
        status, data, _ = self.service.request("POST", "/shutdown", {"force": True})
        self.assertEqual(status, 200)
        self.assertTrue(self.lifetime.stopped.wait(5))
        self.assertIn("Завершить", self.lifetime.reason)

    def test_shutdown_needs_json(self):
        """Простая форма чужой страницы сервис не остановит: тело - только JSON."""
        request = urllib.request.Request(f"http://127.0.0.1:{self.service.port}/shutdown", data=b"force=1",
                                         method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 415)
        self.assertIsNone(self.lifetime.reason)

    def test_watch_stops_server(self):
        self.lifetime.idle, self.lifetime.first = 0.3, 0.3
        self.service.request("POST", "/alive", {"tab": "t1"})
        self.lifetime.watch(self.service.server, 0.1)
        self.assertTrue(self.lifetime.stopped.wait(5))
        self.assertIn("открытых страниц нет", self.lifetime.reason)


class WindowTest(unittest.TestCase):
    """Окно приложения: команда по найденному браузеру, без него - вкладка."""

    def test_app_command(self):
        url = "http://127.0.0.1:8190/"
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.assertEqual(launch.app_command(chrome, url, "win32"), [chrome, "--app=" + url])
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.assertEqual(launch.app_command(mac, url, "darwin"),
                         ["open", "-na", "/Applications/Google Chrome.app", "--args", "--app=" + url])
        self.assertEqual(launch.app_command("/usr/bin/chromium", url, "linux"), ["/usr/bin/chromium", "--app=" + url])

    def test_open_window_found(self):
        url = "http://127.0.0.1:8190/"
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        with mock.patch.object(render, "find_chrome", return_value=(edge, [])), \
                mock.patch.object(launch.subprocess, "Popen") as popen, \
                mock.patch.object(launch.webbrowser, "open") as browser:
            self.assertEqual(launch.open_window(url), "app")
        self.assertEqual(popen.call_args.args[0], launch.app_command(edge, url))
        browser.assert_not_called()

    def test_open_window_without_browser(self):
        url = "http://127.0.0.1:8190/"
        with mock.patch.object(render, "find_chrome", return_value=(None, [])), \
                mock.patch.object(launch.subprocess, "Popen") as popen, \
                mock.patch.object(launch.webbrowser, "open") as browser:
            self.assertEqual(launch.open_window(url), "tab")
        popen.assert_not_called()
        browser.assert_called_once_with(url)


class FindServiceTest(unittest.TestCase):
    """Повторный запуск: сервис своей папки находится по `GET /about`."""

    def test_find_service(self):
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        with mock.patch.object(launch, "base_port", return_value=service.port), mock.patch.object(launch, "PORT_TRIES", 1):
            address = f"http://127.0.0.1:{service.port}/"
            self.assertEqual(launch.find_service(folder), (address, folder))
            self.assertEqual(launch.find_service(folder / "spiski" / "spisok.json"), (address, folder),
                             "модель из подкаталога - в сервисе папки выше")
            self.assertIsNone(launch.find_service(folder / "spiski"), "папка - только ровно та")
            self.assertIsNone(launch.find_service(temporary_folder(self)))


def user_env(test: unittest.TestCase, autostop: str) -> dict:
    """Окружение `serve`: свой домашний каталог (последняя папка, журнал) и короткие паузы автоостановки."""
    home = temporary_folder(test, "formmockup-home-")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), FORMMOCKUP_NO_PAUSE="1")
    env[AUTOSTOP_ENV] = autostop
    env[splash.NO_SPLASH_ENV] = "1"         # вывод ярлыка - в консоль; заставку проверяет SplashTest
    return env


def post(port: int, path: str, body: dict):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST",
                                     data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def wait_closed(port: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not port_listening(port):
            return True
        time.sleep(0.2)
    return False


class ServeLifeCliTest(unittest.TestCase):
    """`serve` останавливается сам и по «Завершить» с кодом 0; второй запуск на ту же папку - тот же сервис."""

    def start_with(self, env, *arguments):
        process = subprocess.Popen([sys.executable, str(CLI), "serve", *arguments, "--no-browser"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   env=env)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.addCleanup(process.stdout.close)
        line = process.stdout.readline()
        found = URL.search(line)
        self.assertTrue(found, f"нет адреса в выводе: {line}")
        return process, int(found.group(1)), found.group(0)

    def finish(self, process) -> str:
        output = process.stdout.read()
        self.assertEqual(process.wait(timeout=15), 0, output)
        return output

    def start(self, *arguments, autostop="1.5,2"):
        self.env = user_env(self, autostop)
        return self.start_with(self.env, *arguments)

    def test_stops_without_tabs(self):
        process, port, _ = self.start(str(models_folder(self)))
        self.assertIn("так и не открылась", self.finish(process))
        # `serve` агента не меняет последнюю папку ярлыка человека
        self.assertFalse((Path(self.env["USERPROFILE"]) / ".form-mockup" / "last.json").exists())

    def test_marks_keep_alive(self):
        process, port, _ = self.start(str(models_folder(self)))
        # Отметки дольше паузы и ожидания: сервис работает; «обновление страницы» - новая вкладка, тоже в счет
        for index in range(8):
            post(port, "/alive", {"tab": f"t{index // 4}"})
            time.sleep(0.5)
        self.assertIsNone(process.poll(), "сервис остановился, хотя вкладка отмечалась")
        self.assertIn("открытых страниц нет", self.finish(process))

    def test_quit(self):
        process, port, _ = self.start(str(models_folder(self)), autostop="60,60")
        started = time.monotonic()
        self.assertEqual(post(port, "/shutdown", {}), 200)
        self.assertIn("«Завершить»", self.finish(process))
        self.assertLess(time.monotonic() - started, 10)

    def test_second_launch_reuses_service(self):
        folder = models_folder(self)
        process, port, _ = self.start(str(folder), autostop="60,60")
        env = user_env(self, "60,60")
        for target, address in ((folder, f"http://127.0.0.1:{port}/"),
                                (folder / "spiski" / "spisok.json", f"http://127.0.0.1:{port}/edit?file=spiski/spisok.json")):
            with self.subTest(target=target.name):
                result = subprocess.run([sys.executable, str(CLI), "serve", str(target), "--no-browser"],
                                        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("уже запущен", result.stdout)
                self.assertIn(address, result.stdout)
        post(port, "/shutdown", {})
        self.finish(process)


@unittest.skipUnless(sys.platform == "win32", "ярлык .cmd - только Windows")
class ShortcutWindowsTest(unittest.TestCase):
    """Ярлык `Открыть макеты.cmd`: перетаскивание папки и модели, повторный запуск, нет Python."""

    def run_shortcut(self, *arguments, env):
        # Как Проводник: путь ярлыка и аргументы в кавычках; строка целиком - `cmd /s /c "..."`, без экранирования
        # кавычек по правилам `subprocess` (cmd их не понимает)
        command = f'"{SHORTCUT}" ' + " ".join(f'"{argument}"' for argument in arguments)
        return subprocess.run(f'cmd /d /s /c "{command}"', capture_output=True, env=env, timeout=60)

    @staticmethod
    def text(result) -> str:
        return (result.stdout + result.stderr).decode("utf-8", errors="replace")

    def test_no_python(self):
        env = user_env(self, "1,1")
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        env["PATH"] = str(system)
        result = self.run_shortcut(str(temporary_folder(self)), env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Не найден Python", self.text(result))
        self.assertIn("python.org", self.text(result))

    def test_folder_model_and_second_launch(self):
        folder = models_folder(self)
        env = user_env(self, "60,4")
        result = self.run_shortcut(str(folder), "--no-browser", env=env)
        output = self.text(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("Traceback", output)
        port = int(URL.search(output).group(1))
        self.addCleanup(lambda: port_listening(port) and post(port, "/shutdown", {"force": True}))
        self.assertTrue(port_listening(port), "сервис после ярлыка не работает")
        last = json.loads((Path(env["USERPROFILE"]) / ".form-mockup" / "last.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(last["folder"]), folder, "ярлык запомнил папку")
        # Окно ярлыка закрылось, сервис живет сам; второй запуск и модель - тот же сервис
        again = self.text(self.run_shortcut(str(folder), "--no-browser", env=env))
        self.assertIn("уже запущен", again)
        self.assertIn(f"127.0.0.1:{port}/", again)
        model = self.text(self.run_shortcut(str(folder / "zakaz.json"), "--no-browser", env=env))
        self.assertIn(f"127.0.0.1:{port}/edit?file=zakaz.json", model)
        # Вкладка так и не открылась - сервис ярлыка останавливается сам
        self.assertTrue(wait_closed(port, 15), "сервис ярлыка не остановился сам")

    def test_model_starts_constructor(self):
        folder = models_folder(self)
        env = user_env(self, "60,60")
        result = self.run_shortcut(str(folder / "spiski" / "spisok.json"), "--no-browser", env=env)
        output = self.text(result)
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Конструктор: http://127.0.0.1:", output)
        self.assertIn("edit?file=spisok.json", output)
        port = int(URL.search(output).group(1))
        self.assertEqual(post(port, "/shutdown", {}), 200)
        self.assertTrue(wait_closed(port, 10))

    def test_missing_folder(self):
        result = self.run_shortcut(str(temporary_folder(self) / "нет такой"), env=user_env(self, "1,1"))
        output = self.text(result)
        self.assertEqual(result.returncode, 1)
        self.assertIn("не найдены", output)
        self.assertNotIn("Traceback", output)


class SplashLinesTest(unittest.TestCase):
    """Заставка ярлыка: вывод запуска построчно, строки человеку, выключатель."""

    def test_lines(self):
        sink = __import__("queue").Queue()
        out = splash.Lines(sink)
        out.write("Первая\nВто")
        out.write("рая\n\n  \nхвост")
        out.flush()
        self.assertEqual([sink.get_nowait() for _ in range(sink.qsize())], ["Первая", "Вторая", "хвост"])

    def test_status_text(self):
        self.assertEqual(splash.status_text("Макеты: http://127.0.0.1:8190/ - папка X"), "Открываю окно макетов...")
        self.assertEqual(splash.status_text("Конструктор: http://127.0.0.1:8190/edit?file=a.json"),
                         "Открываю окно макетов...")
        self.assertIn("уже открыты", splash.status_text("Сервис на эту папку уже запущен: http://127.0.0.1:8190/"))
        self.assertEqual(splash.status_text("Ошибка: нет"), "Ошибка: нет")

    def test_switch_off(self):
        with mock.patch.dict(os.environ, {splash.NO_SPLASH_ENV: "1"}):
            self.assertFalse(splash.available())


@unittest.skipUnless(sys.platform == "win32" and splash.windowed_python() and
                     __import__("importlib").util.find_spec("tkinter"), "заставка - Windows с pythonw и tkinter")
class SplashShortcutTest(unittest.TestCase):
    """Ярлык с заставкой: консоль закрывается сразу, запуск идет в окне заставки, итог - в журнале."""

    def run_shortcut(self, *arguments, hold: str = "0.3"):
        env = user_env(self, "60,60")
        env.pop(splash.NO_SPLASH_ENV)
        env[splash.HOLD_ENV] = hold
        command = f'"{SHORTCUT}" ' + " ".join(f'"{argument}"' for argument in arguments)
        started = time.monotonic()
        result = subprocess.run(f'cmd /d /s /c "{command}"', capture_output=True, env=env, timeout=60)
        return result, time.monotonic() - started, Path(env["USERPROFILE"]) / ".form-mockup" / "serve.log"

    @staticmethod
    def wait_log(log: Path, mark: str, seconds: float = 30) -> str:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            text = log.read_text(encoding="utf-8") if log.is_file() else ""
            if mark in text:
                return text
            time.sleep(0.3)
        return log.read_text(encoding="utf-8") if log.is_file() else ""

    def test_folder(self):
        folder = models_folder(self)
        result, seconds, log = self.run_shortcut(str(folder), "--no-browser")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), b"", "консоль ярлыка пустая - вывод в заставке")
        self.assertLess(seconds, 10, "консоль ярлыка не ждет сервис")
        text = self.wait_log(log, "Заставка ярлыка: код")
        self.assertIn("Заставка ярлыка: код 0", text)
        port = int(URL.search(text).group(1))
        self.addCleanup(lambda: port_listening(port) and post(port, "/shutdown", {"force": True}))
        self.assertTrue(port_listening(port), "сервис после заставки не работает")

    def test_error_stays_in_splash(self):
        result, _, log = self.run_shortcut(str(temporary_folder(self) / "нет такой"))
        self.assertEqual(result.returncode, 0, "консоль ярлыка закрывается - ошибку показывает заставка")
        text = self.wait_log(log, "Заставка ярлыка: код")
        self.assertIn("Заставка ярлыка: код 2", text)
        self.assertIn("не найдены", text)


@unittest.skipUnless(CHROME, "Chrome не найден")
class PageLifeTest(unittest.TestCase):
    """Страницы шлют отметки вкладки; «Завершить» останавливает сервис."""

    def dump(self, service, path: str, marker: str) -> dict:
        dom = render.run_chrome(CHROME, ["--window-size=1400,900", "--virtual-time-budget=8000", "--dump-dom",
                                         f"http://127.0.0.1:{service.port}{path}"])
        found = re.findall(rf'<pre id="{marker}"[^>]*>(.*?)</pre>', dom, re.S)
        self.assertTrue(found and found[-1].strip(), f"страница не отдала итог ({marker} пуст)")
        return json.loads(html.unescape(found[-1]))

    def test_pages_mark_tab(self):
        service = ServiceServer(self, models_folder(self))
        tabs = service.server.lifetime.tabs
        result = self.dump(service, "/", "fh-result")
        self.assertEqual(result["errors"], [])
        self.assertEqual([file for _, file, _ in tabs.values()], [None], "стартовая страница отметилась")
        result = self.dump(service, "/edit?file=zakaz.json#do=", "fe-result")
        self.assertEqual(result["errors"], [])
        self.assertIn("zakaz.json", [file for _, file, _ in tabs.values()], "конструктор отметился со своим макетом")

    def test_quit_button(self):
        service = ServiceServer(self, models_folder(self))
        result = self.dump(service, "/#open=quit", "fh-result")
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["stopped"])
        self.assertTrue(service.server.lifetime.stopped.wait(5))


class PythonVersionTest(unittest.TestCase):
    """Инструмент обещает Python 3.9+ (README), тесты гоняются на новом (на 3.9 падали создание, импорт и
    рендер - `write_text(newline=)` появился в 3.10). Синтаксис 3.10+ и этот вызов ловятся без Python 3.9."""

    def test_code_runs_on_python_39(self):
        import ast
        found = []
        for path in sorted(ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(path), feature_version=(3, 9))
            except SyntaxError as error:
                found.append(f"{path.relative_to(ROOT)}:{error.lineno}: синтаксис новее 3.9")
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("write_text", "read_text")
                        and any(keyword.arg == "newline" for keyword in node.keywords)):
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.attr}(newline=) - с Python 3.10")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
