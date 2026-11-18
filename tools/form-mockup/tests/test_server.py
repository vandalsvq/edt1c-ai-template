"""Сервер конструктора и группы свойств панели.

Сервер поднимается в потоке на свободном порту; запросы - urllib стандартной библиотеки.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import SCHEMA_PATH, pictures  # noqa: E402
from fmlib.importer import import_form  # noqa: E402
from fmlib.schema import SchemaValidator  # noqa: E402
from fmlib.server import (GROUPS_PATH, STRUCTURE, Editor, ServeError, base_port, containment, dump,  # noqa: E402
                          kinds_description, make_server)
from support import temp_dir  # noqa: E402

EXAMPLE = ROOT / "examples" / "zakaz-pokupatelya.json"
STALO = ROOT / "examples" / "pravki" / "zakaz-pokupatelya-stalo.json"
CLI = ROOT / "formmockup.py"
DESIGNER_SRC = ROOT / "tests" / "fixtures" / "import" / "designer"
EDT_SRC = ROOT / "tests" / "fixtures" / "import" / "edt"
CONTRACT_FORM = EDT_SRC / "Catalogs" / "_ДемоДоговоры" / "Forms" / "ФормаЭлемента" / "Form.form"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class Server:
    """Сервер конструктора на копии модели во временном каталоге."""

    def __init__(self, source: Path = EXAMPLE, editor_class=Editor, src: Path = None, before: Path = None):
        self.folder = Path(temp_dir(prefix="formmockup-serve-"))
        self.path = self.folder / "model.json"
        shutil.copy(source, self.path)
        # «Было» для правок: файл `--before` или модель на запуске
        base = json.loads(before.read_text(encoding="utf-8")) if before else None
        self.editor = editor_class(self.path, pictures.std_source(), src, base, before)
        self.server = make_server(self.editor, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.folder, ignore_errors=True)

    def request(self, method, path, body=None, headers=None):
        """(код, заголовки, JSON или текст ответа)."""
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        all_headers = {"Content-Type": "application/json"} if body is not None else {}
        all_headers.update(headers or {})
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                         headers=all_headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.headers, self.decode(response)
        except urllib.error.HTTPError as error:
            return error.code, error.headers, self.decode(error)

    @staticmethod
    def decode(response):
        text = response.read().decode("utf-8")
        return json.loads(text) if response.headers.get("Content-Type", "").startswith("application/json") else text


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def test_page(self):
        status, headers, page = self.server.request("GET", "/edit")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        for marker in ("window.FMRender", "fe-editor", "property-groups", '"kinds"'):
            self.assertIn(marker, page)
        self.assertNotIn("/*FM_SCRIPT*/", page)

    def test_read_model_with_version(self):
        status, headers, data = self.server.request("GET", "/model")
        self.assertEqual(status, 200)
        self.assertEqual(data["model"], json.loads(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(data["issues"], [])
        self.assertTrue(headers["ETag"])
        _, _, version = self.server.request("GET", "/version")
        self.assertEqual(version["etag"], headers["ETag"])
        # Стандартные картинки для рисования - отдельно, в модель не входят
        self.assertIn("StdPicture.InputFieldCalendar", data["pictures"])

    def test_check_without_write(self):
        before = self.server.path.read_bytes()
        model = json.loads(before)
        model["form"]["items"][0]["items"][0]["items"].append({"type": "InputField", "name": "Контрагент"})
        status, _, data = self.server.request("POST", "/check", model)
        self.assertEqual(status, 200)
        self.assertEqual([(issue["code"], issue["blocking"]) for issue in data["issues"]], [("duplicate-name", True)])
        self.assertEqual(data["issues"][0]["name"], "Контрагент")
        self.assertEqual(self.server.path.read_bytes(), before)

    def test_write_with_current_version(self):
        _, headers, data = self.server.request("GET", "/model")
        model = data["model"]
        model["form"]["title"] = "Заказ клиента"
        status, answer_headers, answer = self.server.request("PUT", "/model", model, {"If-Match": headers["ETag"]})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["issues"], [])
        written = self.server.path.read_text(encoding="utf-8")
        # Формат - как у import: отступ 2, кириллица без экранирования, перевод строки в конце
        self.assertEqual(written, dump(model))
        self.assertIn('  "form": {\n    "title": "Заказ клиента"', written)
        self.assertTrue(written.endswith("}\n"))
        self.assertNotEqual(answer_headers["ETag"], headers["ETag"])
        _, _, version = self.server.request("GET", "/version")
        self.assertEqual(version["etag"], answer_headers["ETag"])
        self.assertEqual(list(self.server.folder.iterdir()), [self.server.path], "временный файл остался")

    def test_stale_version_conflict(self):
        _, headers, data = self.server.request("GET", "/model")
        # Агент записал файл мимо конструктора
        other = dict(data["model"], form=dict(data["model"]["form"], title="Агент"))
        self.server.path.write_text(dump(other), encoding="utf-8")
        _, _, version = self.server.request("GET", "/version")
        self.assertNotEqual(version["etag"], headers["ETag"])
        status, _, answer = self.server.request("PUT", "/model", data["model"], {"If-Match": headers["ETag"]})
        self.assertEqual(status, 409)
        self.assertEqual(answer["etag"], version["etag"])
        self.assertEqual(json.loads(self.server.path.read_text(encoding="utf-8"))["form"]["title"], "Агент")

    def test_blocking_issues_not_written(self):
        _, headers, data = self.server.request("GET", "/model")
        before = self.server.path.read_bytes()
        model = data["model"]
        model["form"]["items"][0]["checkBoxType"] = "Switch"
        status, _, answer = self.server.request("PUT", "/model", model, {"If-Match": headers["ETag"]})
        self.assertEqual(status, 422)
        self.assertEqual({issue["code"] for issue in answer["issues"]}, {"foreign-property"})
        self.assertEqual(self.server.path.read_bytes(), before)

    def test_layout_rules_do_not_block_write(self):
        _, headers, data = self.server.request("GET", "/model")
        model = data["model"]
        model["form"]["items"].append({"type": "UsualGroup", "name": "ПустаяГруппа"})
        status, _, answer = self.server.request("PUT", "/model", model, {"If-Match": headers["ETag"]})
        self.assertEqual(status, 200)
        self.assertEqual([issue["code"] for issue in answer["issues"]], ["empty-container"])
        self.assertFalse(answer["issues"][0]["blocking"])

    def test_version_required(self):
        _, _, data = self.server.request("GET", "/model")
        status, _, _ = self.server.request("PUT", "/model", data["model"])
        self.assertEqual(status, 428)

    def test_unreadable_file(self):
        self.server.path.write_text('{"version": 1, "form": {', encoding="utf-8")
        status, headers, data = self.server.request("GET", "/model")
        self.assertEqual(status, 422)
        self.assertIn("JSON", data["error"])
        _, _, version = self.server.request("GET", "/version")
        self.assertEqual(version["etag"], headers["ETag"])

    def test_foreign_host_and_body_type_rejected(self):
        status, _, _ = self.server.request("GET", "/model", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.port}/check", data=b"{}", method="POST",
                                         headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 415)

    def test_write_failure_reported(self):
        # Отказ записи - подменой `os.replace`, а не `chmod` каталога: на Windows `chmod` запись не запрещает
        _, headers, data = self.server.request("GET", "/model")
        denied = PermissionError(13, "Отказано в доступе")
        with mock.patch("fmlib.server.os.replace", side_effect=denied), mock.patch("fmlib.server.time.sleep"):
            status, _, answer = self.server.request("PUT", "/model", data["model"], {"If-Match": headers["ETag"]})
        self.assertEqual(status, 500)
        self.assertIn("не записан", answer["error"])
        self.assertEqual(list(self.server.folder.glob(".*.tmp")), [], "временный файл убран")

    def test_write_retries_while_file_is_read(self):
        # На Windows открытый на чтение файл не заменить: сохранение ждет, пока читатель его закроет
        _, headers, data = self.server.request("GET", "/model")
        reader = open(self.server.path, "rb")
        timer = threading.Timer(0.15, reader.close)
        timer.start()
        try:
            status, _, _ = self.server.request("PUT", "/model", data["model"], {"If-Match": headers["ETag"]})
        finally:
            timer.join()
            reader.close()
        self.assertEqual(status, 200)

    def test_written_file_has_lf(self):
        _, headers, data = self.server.request("GET", "/model")
        status, _, _ = self.server.request("PUT", "/model", data["model"], {"If-Match": headers["ETag"]})
        self.assertEqual(status, 200)
        self.assertNotIn(b"\r\n", self.server.path.read_bytes())


class ConfigSourceTest(unittest.TestCase):
    """Исходники конфигурации (`serve --src`): общие картинки, ссылочные типы и их состав."""

    def serve(self, src=None):
        server = Server(src=src)
        self.addCleanup(server.close)
        return server

    def designer_src(self) -> Path:
        """Выгрузка конфигуратора: справочник и перечисление фикстуры импорта, общая картинка с синонимом."""
        folder = Path(temp_dir(prefix="formmockup-src-"))
        self.addCleanup(shutil.rmtree, folder, True)
        src = folder / "src"
        shutil.copytree(DESIGNER_SRC, src)
        (src / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        pictures_folder = src / "CommonPictures"
        (pictures_folder / "Значок" / "Ext" / "Picture").mkdir(parents=True)
        (pictures_folder / "Значок" / "Ext" / "Picture" / "Picture.png").write_bytes(PNG)
        (pictures_folder / "Значок.xml").write_text(
            '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:v8="http://v8.1c.ru/8.1/data/core">'
            '<CommonPicture uuid="00000000-0000-0000-0000-000000000099"><Properties><Name>Значок</Name>'
            '<Synonym><v8:item><v8:lang>ru</v8:lang><v8:content>Значок партнера</v8:content></v8:item></Synonym>'
            '</Properties></CommonPicture></MetaDataObject>', encoding="utf-8")
        # Картинка без файла картинки - не значок: в список не входит
        (pictures_folder / "Пустая.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        return src

    def test_without_source(self):
        server = self.serve()
        for path, key in (("/config-pictures", "pictures"), ("/config-types", "types"), ("/config-styles", "styles")):
            status, _, data = server.request("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(data, {key: [], "available": False})
        status, _, data = server.request("GET", "/type-description?key=" + urllib.parse.quote("Catalog.Партнеры"))
        self.assertEqual(status, 404)
        self.assertIn("--src", data["error"])
        _, _, page = server.request("GET", "/edit")
        self.assertIn('"source": false', page)

    def test_config_styles(self):
        """Элементы стиля конфигурации для «Из стиля»: со значением, по имени; в модель - только выбранный."""
        status, _, data = self.serve(EDT_SRC).request("GET", "/config-styles")
        self.assertEqual(status, 200)
        self.assertNotIn("available", data)
        self.assertEqual(data["styles"], [{"name": "_ДемоЦветАкцента", "value": "#1955AE"}])

    def test_edt_source(self):
        server = self.serve(EDT_SRC)
        _, _, page = server.request("GET", "/edit")
        self.assertIn('"source": true', page)
        status, _, data = server.request("GET", "/config-pictures")
        self.assertEqual(status, 200)
        self.assertNotIn("available", data)
        # По имени; заголовок - синоним, без синонима - по имени
        self.assertEqual([(item["name"], item["title"]) for item in data["pictures"]],
                         [("CommonPicture._ДемоЗначок", "Значок договора"), ("CommonPicture._ДемоСтатус", "_Демо статус")])
        # Тот же вариант картинки, что кладет в модель импорт: из архива с вариантами - «Такси» для масштаба 100 %
        for item in data["pictures"]:
            self.assertEqual(item["uri"], pictures.load(EDT_SRC, True, item["name"]))
        self.assertTrue(data["pictures"][0]["uri"].startswith("data:image/png;base64,"))
        model, _ = import_form(CONTRACT_FORM)
        self.assertEqual(data["pictures"][1]["uri"], model["pictures"]["CommonPicture._ДемоСтатус"])
        _, _, data = server.request("GET", "/config-types")
        types = {item["key"]: item for item in data["types"]}
        self.assertEqual(types["Catalog._ДемоДоговоры"]["kind"], "Catalog")
        self.assertEqual(types["Catalog._ДемоДоговоры"]["name"], "_ДемоДоговоры")
        self.assertEqual(types["Catalog._ДемоДоговоры"]["title"], "Договоры")
        # Окно типа: объекты обработок - тоже
        self.assertEqual(types["DataProcessor.ВитринаЭлементов"]["kind"], "DataProcessor")
        self.assertFalse(any(key.startswith(("CommonModule.", "Role.")) for key in types))

    def test_type_description_as_import(self):
        """Состав типа - ровно как импорт пишет его в `types` модели."""
        server = self.serve(EDT_SRC)
        model, _ = import_form(CONTRACT_FORM)
        status, _, data = server.request("GET", "/type-description?key=" + urllib.parse.quote("Catalog._ДемоДоговоры"))
        self.assertEqual(status, 200)
        self.assertEqual(data, model["types"]["Catalog._ДемоДоговоры"])
        for key in ("Catalog.НетТакого", "DataProcessor.ВитринаЭлементов", ""):
            with self.subTest(key=key):
                status, _, data = server.request("GET", "/type-description?key=" + urllib.parse.quote(key))
                self.assertEqual(status, 404)
                self.assertIn("error", data)

    def test_designer_source(self):
        server = self.serve(self.designer_src())
        _, _, data = server.request("GET", "/config-pictures")
        self.assertEqual([(item["name"], item["title"]) for item in data["pictures"]],
                         [("CommonPicture.Значок", "Значок партнера")])
        self.assertTrue(data["pictures"][0]["uri"].startswith("data:image/png;base64,"))
        _, _, data = server.request("GET", "/config-types")
        types = {item["key"]: item for item in data["types"]}
        self.assertEqual(list(types), ["Catalog.Партнеры", "Enum.ВидыПартнеров"])
        # Значения перечисления - синонимами, без синонима - по имени (как `enumValues` импорта)
        self.assertEqual(types["Enum.ВидыПартнеров"]["values"], ["Покупатель", "Поставщик и покупатель"])
        self.assertNotIn("values", types["Catalog.Партнеры"])
        status, _, data = server.request("GET", "/type-description?key=" + urllib.parse.quote("Catalog.Партнеры"))
        self.assertEqual(status, 200)
        self.assertIn("ОсновнойМенеджер", [item["name"] for item in data["attributes"]])

    def test_not_a_source(self):
        with self.assertRaises(ServeError):
            Editor(EXAMPLE, None, ROOT)


class PortTest(unittest.TestCase):
    def setUp(self):
        # Первый порт - не из настроек того, кто гоняет тесты
        self.home = Path(temp_dir(prefix="formmockup-port-"))
        for patcher in (mock.patch.dict("os.environ", {}, clear=False),
                        mock.patch("fmlib.workspace.user_dir", return_value=self.home)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("FORMMOCKUP_PORT", None)

    def test_base_port_settings(self):
        """Первый порт без терминала (ярлык): `port` в `~/.form-mockup/config.json`, переменная FORMMOCKUP_PORT важнее;
        мусор и порт вне диапазона - 8190; все порты заняты - сообщение называет, где поменять."""
        self.assertEqual(base_port(), 8190)
        (self.home / "config.json").write_text('{"port": 9300}', encoding="utf-8")
        self.assertEqual(base_port(), 9300)
        os.environ["FORMMOCKUP_PORT"] = "9400"
        self.assertEqual(base_port(), 9400)
        for bad in ("порт", "80", "65530"):
            os.environ["FORMMOCKUP_PORT"] = bad
            self.assertEqual(base_port(), 8190, bad)
        os.environ.pop("FORMMOCKUP_PORT")
        with mock.patch("fmlib.server.ThreadingHTTPServer", side_effect=OSError(98, "busy")) as created:
            with self.assertRaises(ServeError) as caught:
                make_server(Editor(EXAMPLE))
        self.assertEqual(created.call_args_list[0].args[0], ("127.0.0.1", 9300))
        self.assertIn("порты 9300-9320 заняты", str(caught.exception))
        self.assertIn("config.json", str(caught.exception))
        self.assertIn("FORMMOCKUP_PORT", str(caught.exception))

    def test_busy_explicit_port(self):
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        try:
            with self.assertRaises(ServeError):
                make_server(Editor(EXAMPLE), busy.getsockname()[1])
        finally:
            busy.close()

    def test_sandbox_without_network(self):
        """Песочница агента без сети (Codex `workspace-write`): bind - EPERM на всех портах, ни один не занят;
        сказать про сеть, а не «порт занят»."""
        with mock.patch("fmlib.server.ThreadingHTTPServer", side_effect=PermissionError(1, "Operation not permitted")), \
                mock.patch("fmlib.server.port_listening", return_value=False):
            with self.assertRaises(ServeError) as caught:
                make_server(Editor(EXAMPLE))
        self.assertIn("нет доступа к сети", str(caught.exception))
        self.assertIn("8190", str(caught.exception), "в сообщении - первый отказавший порт")

    def test_windows_busy_port_denied(self):
        """Windows: занятый порт отвечает отказом в доступе (WSAEACCES), а не «адрес занят» - это занятый порт,
        берется следующий."""
        server = SimpleNamespace()     # сервер-заглушка: к нему цепляется `lifetime`
        denied = PermissionError(13, "Сделана попытка доступа к сокету методом, запрещенным правами доступа")
        with mock.patch("fmlib.server.ThreadingHTTPServer", side_effect=[denied, server]) as created, \
                mock.patch("fmlib.server.port_listening", return_value=True):
            self.assertIs(make_server(Editor(EXAMPLE)), server)
        self.assertEqual(created.call_args.args[0], ("127.0.0.1", 8191))

    def test_windows_busy_explicit_port_denied(self):
        denied = PermissionError(13, "Сделана попытка доступа к сокету методом, запрещенным правами доступа")
        with mock.patch("fmlib.server.ThreadingHTTPServer", side_effect=denied), \
                mock.patch("fmlib.server.port_listening", return_value=True):
            with self.assertRaises(ServeError) as caught:
                make_server(Editor(EXAMPLE), 8300)
        self.assertEqual(str(caught.exception), "порт 8300 занят")


class ChangesApiTest(unittest.TestCase):
    """Правки против «было»: те же, что у `table --before`; база держится всю работу сервера."""

    def test_before_file_like_table(self):
        server = Server(STALO, before=EXAMPLE)
        try:
            _, _, data = server.request("GET", "/model")
            self.assertEqual(data["base"]["file"], "zakaz-pokupatelya.json")
            self.assertIn("Предоплата", data["base"]["names"])
            self.assertNotIn("Форма", data["base"]["names"])
            status, _, answer = server.request("POST", "/check", data["model"])
            self.assertEqual(status, 200)
            self.assertNotIn("tree", answer, "дерево - только по просьбе")
            got = [(change["n"], change["op"], change["after"] or change["before"]) for change in answer["changes"]]
            # Как `formmockup.py table stalo --before zakaz`
            self.assertEqual(got, [(1, "moved", "ПечатьСчет"), (2, "moved", "Склад"), (3, "changed", "ДатаОтгрузки"),
                                   (4, "removed", "Предоплата"), (5, "added", "СпособОплаты"),
                                   (6, "added", "ТоварыЗаполнитьПоОстаткам"), (7, "changed", "ТоварыСуммаСНДС"),
                                   (8, "added", "ГруппаДоставка")])
            self.assertEqual(answer["changes"][2]["props"], [{"prop": "title", "before": "Отгрузка"}])
            self.assertEqual(answer["changes"][6]["props"][0], {"prop": "name", "before": "ТоварыСумма"})
            _, _, with_tree = server.request("POST", "/check?tree=1", data["model"])
            names = json.dumps(with_tree["tree"], ensure_ascii=False)
            self.assertIn('"Предоплата"', names, "удаленный - в объединенном дереве")
            self.assertIn("Склад (было)", names, "тень перенесенного")
        finally:
            server.close()

    def test_base_is_file_at_start_and_survives_save(self):
        server = Server()
        try:
            _, headers, data = server.request("GET", "/model")
            self.assertIsNone(data["base"]["file"])
            model = data["model"]
            _, _, same = server.request("POST", "/check", model)
            self.assertEqual(same["changes"], [])
            model["form"]["title"] = "Заказ клиента"
            status, _, _ = server.request("PUT", "/model", model, {"If-Match": headers["ETag"]})
            self.assertEqual(status, 200)
            _, _, after_save = server.request("POST", "/check", model)
            self.assertEqual([(change["op"], change["props"]) for change in after_save["changes"]],
                             [("changed", [{"prop": "title", "before": "Заказ покупателя"}])],
                             "сохранение «было» не меняет")
        finally:
            server.close()

    def test_blocking_model_without_changes(self):
        server = Server()
        try:
            model = json.loads(server.path.read_text(encoding="utf-8"))
            model["form"]["items"][0]["items"][0]["items"].append({"type": "InputField", "name": "Контрагент"})
            _, _, data = server.request("POST", "/check?tree=1", model)
            self.assertIsNone(data["changes"])
            self.assertNotIn("tree", data)
        finally:
            server.close()


class CliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(CLI), "serve", *arguments], capture_output=True, text=True, encoding="utf-8",
                              timeout=30)

    def test_missing_file(self):
        result = self.run_cli(str(Path(temp_dir()) / "нет.json"), "--no-browser")
        self.assertEqual(result.returncode, 2)
        self.assertIn("не найден", result.stderr)

    def test_not_json(self):
        path = Path(temp_dir()) / "model.json"
        path.write_text("не json", encoding="utf-8")
        result = self.run_cli(str(path), "--no-browser")
        self.assertEqual(result.returncode, 2)

    def test_src_not_a_source(self):
        result = self.run_cli(str(EXAMPLE), "--no-browser", "--src", str(ROOT))
        self.assertEqual(result.returncode, 2)
        self.assertIn("не исходники конфигурации", result.stderr)

    def test_missing_before(self):
        result = self.run_cli(str(EXAMPLE), "--no-browser", "--before", str(Path(temp_dir()) / "нет.json"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("не найден", result.stderr)

    def test_new_creates_empty_model(self):
        path = Path(temp_dir()) / "new" / "model.json"
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        try:
            # Занятый порт - код 2 уже после создания файла: проверка --new без живого сервера
            result = self.run_cli(str(path), "--no-browser", "--new", "--kind", "ListForm", "--port", str(busy.getsockname()[1]))
        finally:
            busy.close()
        self.assertEqual(result.returncode, 2)
        self.assertIn("занят", result.stderr)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"version": 1, "form": {"formKind": "ListForm", "items": []}})


class ContainmentTest(unittest.TestCase):
    """Вложенность для правки структуры - по схеме, как таблица «Где что лежит» `model.md`."""

    def test_containment(self):
        children = containment(SchemaValidator.from_file(SCHEMA_PATH))
        self.assertEqual(children["Pages"], ["Page"])
        for kind in ("Form", "UsualGroup", "Page"):
            self.assertIn("Table", children[kind])
            self.assertNotIn("Page", children[kind])
            self.assertNotIn("ColumnGroup", children[kind])
        for kind in ("Table", "ColumnGroup"):
            self.assertIn("ColumnGroup", children[kind])
            self.assertNotIn("UsualGroup", children[kind])
            self.assertNotIn("Button", children[kind])
        for kind in ("AutoCommandBar", "CommandBar", "ButtonGroup", "Popup"):
            self.assertEqual(set(children[kind]), {"Button", "ButtonGroup", "Popup", "Addition", "Unknown"})
        self.assertNotIn("InputField", children, "у поля подчиненных нет")


class PropertyGroupsTest(unittest.TestCase):
    """Каждое свойство каждого вида - в группе панели (нет «Прочих»), в группах нет чужих свойств."""

    @classmethod
    def setUpClass(cls):
        cls.kinds = kinds_description(SchemaValidator.from_file(SCHEMA_PATH))
        cls.groups = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))

    def listed(self, kind):
        layout = self.groups["kinds"].get(kind, self.groups["default"])
        props = [prop for group in layout for block in group["blocks"] for prop in block]
        return props, [group["group"] for group in layout]

    def test_every_property_in_a_group(self):
        for kind, specs in self.kinds.items():
            with self.subTest(kind=kind):
                props, _ = self.listed(kind)
                self.assertEqual(sorted(set(specs) - set(props)), [], "свойства вне групп - попали бы в «Прочие»")
                self.assertEqual(len(props), len(set(props)), "свойство в группах дважды")

    def test_no_foreign_properties_in_own_lists(self):
        for kind, layout in self.groups["kinds"].items():
            with self.subTest(kind=kind):
                props, _ = self.listed(kind)
                self.assertEqual(sorted(set(props) - set(self.kinds[kind])), [], "в списке вида свойства, которых у него нет")

    def test_structure_not_in_panel(self):
        fields = {"InputField", "CheckBoxField", "RadioButtonField", "LabelField", "PictureField", "HTMLDocumentField"}
        for kind, specs in self.kinds.items():
            # «Вид» поля - `type` в пределах полей (ВидПоляФормы), у прочих видов `type` в панели нет
            self.assertFalse(set(specs) & (STRUCTURE - {"type"}), kind)
            self.assertEqual("type" in specs, kind in fields or kind.endswith("Field"), kind)

    def test_group_order_like_palette(self):
        order = ["Основные", "Использование", "Оформление", "Расположение", "Макет"]
        for kind in list(self.groups["kinds"]) + [None]:
            _, names = self.listed(kind)
            with self.subTest(kind=kind):
                self.assertEqual(names, [name for name in order if name in names])

    def test_defaults_are_valid_values(self):
        for kind, values in self.groups["defaults"].items():
            for prop, value in values.items():
                with self.subTest(kind=kind, prop=prop):
                    owners = self.kinds if kind == "*" else {kind: self.kinds[kind]}
                    specs = [specs[prop] for specs in owners.values() if prop in specs]
                    self.assertTrue(specs, "умолчание свойства, которого нет у вида")
                    for spec in specs:
                        if spec["input"] == "enum":
                            self.assertIn(value, spec["values"])
                        elif spec["input"] == "boolean":
                            self.assertIsInstance(value, bool)
                        elif spec["input"] == "integer":
                            self.assertIsInstance(value, int)

    def test_locked_and_layout_group(self):
        self.assertEqual(self.groups["locked"], ["renamedFrom", "sourceType"])
        # Реквизит и команда формы - не элементы: группы «Макет» у них нет
        for kind in (kind for kind in self.kinds if kind not in ("Attribute", "Command")):
            props, names = self.listed(kind)
            layout = self.groups["kinds"].get(kind, self.groups["default"])
            maket = [prop for group in layout if group["group"] == "Макет" for block in group["blocks"] for prop in block]
            with self.subTest(kind=kind):
                self.assertEqual(names[-1], "Макет")
                self.assertIn("note", maket)


class PlacesTest(unittest.TestCase):
    """Применимость свойств по месту: каждая оговорка справочника синтаксиса о свойстве модели -
    в places с теми же местами; в places только свойства своих видов и известные места."""

    PLACES = {"column", "body", "commandBar", "form"}

    @classmethod
    def setUpClass(cls):
        cls.kinds = kinds_description(SchemaValidator.from_file(SCHEMA_PATH))
        cls.places = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))["places"]
        cls.clauses = json.loads((ROOT / "tests" / "fixtures" / "hbk-places.json").read_text(encoding="utf-8"))["clauses"]

    def test_every_clause_in_places(self):
        for clause in self.clauses:
            if clause["model"] is None:
                continue
            with self.subTest(platform=clause["platform"], prop=clause["model"]):
                own = self.places.get(clause["kind"], {})
                self.assertIn(clause["model"], own, "оговорка справочника не попала в places")
                self.assertEqual(own[clause["model"]], clause["places"])

    def test_places_are_known(self):
        for kind, props in self.places.items():
            owners = self.kinds if kind == "*" else {kind: self.kinds[kind]}
            for prop, places in props.items():
                with self.subTest(kind=kind, prop=prop):
                    self.assertTrue(any(prop in specs for specs in owners.values()), "свойства нет у вида")
                    self.assertLessEqual(set(places), self.PLACES)


if __name__ == "__main__":
    unittest.main()
