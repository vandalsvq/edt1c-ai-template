"""Сервис по папке макетов: поиск моделей, настройки папки, API.

Сценарий страницы в headless Chrome пропускается, если Chrome не найден (`fmlib.render.find_chrome`).
"""

import html
import json
import re
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fmlib import pictures, render, workspace  # noqa: E402
from fmlib.metadata import LayeredMetadata, Metadata, long_path  # noqa: E402
from fmlib.projects import file_uri_path, find_projects, suggest_projects  # noqa: E402
from fmlib.server import Sources, Workspace, make_server  # noqa: E402
from fmlib.workspace import (SETTINGS_NAME, WorkspaceError, config_forms, find_models, inside, list_dirs,  # noqa: E402
                             settings_sources, settings_src, stored_path, suggest_src)
from support import temp_dir  # noqa: E402

CLI = ROOT / "formmockup.py"
EXAMPLE = ROOT / "examples" / "zakaz-pokupatelya.json"
LIST_EXAMPLE = ROOT / "examples" / "spisok-zakazov.json"
DESIGNER_SRC = ROOT / "tests" / "fixtures" / "import" / "designer"
DESIGNER_FORM = DESIGNER_SRC / "Catalogs" / "Партнеры" / "Forms" / "ФормаЭлемента" / "Ext" / "Form.xml"
EDT_SRC = ROOT / "tests" / "fixtures" / "import" / "edt"
CHROME, _ = render.find_chrome()
PROJECTS = ROOT / "tests" / "fixtures" / "projects"


def temporary_folder(test: unittest.TestCase, prefix: str = "formmockup-ws-") -> Path:
    folder = Path(temp_dir(prefix=prefix)).resolve()
    test.addCleanup(shutil.rmtree, folder, True)
    return folder


def designer_src(folder: Path) -> Path:
    """Выгрузка конфигуратора из фикстуры импорта: справочник с формой элемента."""
    src = folder / "src"
    shutil.copytree(DESIGNER_SRC, src)
    (src / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
    return src


def edt_workspace(test: unittest.TestCase, hint: bool = True) -> Path:
    """Воркспейс EDT из фикстуры: две копии основы внутри, расширение снаружи - подключено через `.location`
    (путь в нем абсолютный, поэтому файл пишется на месте). `hint=False` - расширение без `Base-Project`."""
    folder = temporary_folder(test, "formmockup-projects-")
    shutil.copytree(PROJECTS / "edt" / "workspace", folder / "workspace")
    extension = PROJECTS / "edt" / "outside" / "Расширение"
    if not hint:
        extension = folder / "outside" / "Расширение"
        shutil.copytree(PROJECTS / "edt" / "outside" / "Расширение", extension)
        shutil.rmtree(extension / "DT-INF")
    posix = extension.resolve().as_posix()
    uri = "file:" + ("" if posix.startswith("/") else "/") + posix
    location = folder / "workspace" / ".metadata" / ".plugins" / "org.eclipse.core.resources" / ".projects" / "Расширение"
    location.mkdir(parents=True)
    (location / ".location").write_bytes(b"\x40\xb1\x8b\x81\x00*URI//" + uri.encode("utf-8") + b"\x00\x00\x00\x00")
    return folder / "workspace"


def models_folder(test: unittest.TestCase) -> Path:
    """Папка макетов: модель в корне, модель в подкаталоге, вывод render, скрытый каталог, чужой JSON."""
    folder = temporary_folder(test)
    shutil.copy(EXAMPLE, folder / "zakaz.json")
    (folder / "spiski").mkdir()
    shutil.copy(LIST_EXAMPLE, folder / "spiski" / "spisok.json")
    (folder / "out").mkdir()
    shutil.copy(EXAMPLE, folder / "out" / "copy.json")
    (folder / ".hidden").mkdir()
    shutil.copy(EXAMPLE, folder / ".hidden" / "copy.json")
    (folder / "package.json").write_text('{"name": "not-a-model", "version": "1.0"}', encoding="utf-8")
    (folder / "broken.json").write_text("{", encoding="utf-8")
    return folder


class FolderTest(unittest.TestCase):
    """Функции папки макетов без HTTP."""

    def test_find_models(self):
        folder = models_folder(self)
        found = find_models(folder)
        self.assertEqual([item["file"] for item in found], ["zakaz.json", "spiski/spisok.json"])
        first = found[0]
        self.assertEqual(first["kind"], "DocumentObjectForm")
        self.assertTrue(first["title"])
        self.assertRegex(first["modified"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_inside(self):
        folder = temporary_folder(self)
        self.assertEqual(inside(folder, "a/b.json"), folder / "a" / "b.json")
        for bad in ("../x.json", "a/../../x.json", "x.txt", ""):
            with self.subTest(file=bad), self.assertRaises(WorkspaceError):
                inside(folder, bad)

    def test_stored_path(self):
        repository = temporary_folder(self)
        (repository / ".git").mkdir()
        (repository / "docs" / "mockups").mkdir(parents=True)
        (repository / "project" / "src").mkdir(parents=True)
        root = repository / "docs" / "mockups"
        self.assertEqual(stored_path(root, repository / "project" / "src"), "../../project/src",
                         "в том же репозитории - относительно папки")
        outside = temporary_folder(self)
        self.assertEqual(stored_path(root, outside), str(outside), "вне репозитория - абсолютный")

    def test_settings_src(self):
        folder = temporary_folder(self)
        src = designer_src(folder)
        root = folder / "mockups"
        root.mkdir()
        self.assertIsNone(settings_src(root), "нет файла настроек")
        (root / SETTINGS_NAME).write_text(json.dumps({"src": "../src"}), encoding="utf-8")
        self.assertEqual(settings_src(root), src)
        (root / SETTINGS_NAME).write_text(json.dumps({"src": "../нет"}), encoding="utf-8")
        self.assertIsNone(settings_src(root), "путь больше не исходники - без исходников")
        (root / SETTINGS_NAME).write_text("{", encoding="utf-8")
        self.assertIsNone(settings_src(root), "испорченный файл настроек")

    def test_suggest_src(self):
        project = temporary_folder(self)
        (project / "src" / "Configuration").mkdir(parents=True)
        (project / "src" / "Configuration" / "Configuration.mdo").write_text("<mdclass/>", encoding="utf-8")
        mockups = project / "docs" / "mockups"
        mockups.mkdir(parents=True)
        self.assertEqual(suggest_src(mockups), project / "src")
        self.assertIsNone(suggest_src(temporary_folder(self)))

    def test_config_forms(self):
        src = designer_src(temporary_folder(self))
        forms = config_forms(src, False)
        self.assertEqual([form["key"] for form in forms], ["Catalog.Партнеры.ФормаЭлемента"])
        self.assertEqual(Path(forms[0]["path"]), src / DESIGNER_FORM.relative_to(DESIGNER_SRC))

    def test_config_forms_edt(self):
        forms = config_forms(EDT_SRC, True)
        self.assertEqual([form["key"] for form in forms],
                         ["Catalog._ДемоДоговоры.ФормаЭлемента", "DataProcessor.ВитринаЭлементов.Форма"])
        self.assertTrue(all(Path(form["path"]).name == "Form.form" for form in forms))

    def test_list_dirs(self):
        folder = temporary_folder(self)
        designer_src(folder)
        (folder / "plain").mkdir()
        (folder / ".hidden").mkdir()
        listed = list_dirs(folder)
        self.assertEqual([(item["name"], item["source"]) for item in listed["dirs"]],
                         [("plain", None), ("src", "designer")])
        self.assertEqual(listed["parent"], str(folder.parent))
        self.assertTrue(listed["roots"])
        with self.assertRaises(WorkspaceError):
            list_dirs(folder / "нет")

    def test_last_folder(self):
        home = temporary_folder(self)
        with mock.patch("fmlib.workspace.user_dir", return_value=home / ".form-mockup"):
            self.assertIsNone(workspace.last_folder())
            workspace.remember_folder(home)
            self.assertEqual(workspace.last_folder(), home)


class ProjectsTest(unittest.TestCase):
    """Папка проектов: поиск по XML конфигураций, расширения и их основа, объединение метаданных."""

    def test_edt_workspace(self):
        found = {project.name: project for project in find_projects(edt_workspace(self))}
        self.assertEqual(sorted(found), ["КопияОсновы", "Основа", "Расширение"])
        extension = found["Расширение"]
        self.assertTrue(extension.extension)
        self.assertEqual((extension.purpose, extension.prefix, extension.project), ("AddOn", "ext_", "Расширение"))
        self.assertEqual(extension.adopted(), {("Catalogs", "Партнеры"), ("CommonModules", "ОбщийМодуль")})
        self.assertEqual(len(extension.candidates), 2, "обе копии основы подходят по заимствованным объектам")
        self.assertEqual(extension.base, found["Основа"].src, "подсказка Base-Project")
        self.assertFalse(found["Основа"].extension)
        self.assertEqual(found["Основа"].as_data()["format"], "edt")

    def test_base_without_hint(self):
        found = {project.name: project for project in find_projects(edt_workspace(self, hint=False))}
        self.assertIsNone(found["Расширение"].base, "две подходящие основы без подсказки - выбор пользователя")
        self.assertEqual(len(found["Расширение"].candidates), 2)

    def test_designer_exports(self):
        found = {project.name: project for project in find_projects(PROJECTS / "designer")}
        extension = found["_ДемоРасширение"]
        self.assertTrue(extension.extension)
        self.assertFalse(extension.as_data()["format"] == "edt")
        self.assertEqual(extension.base, (PROJECTS / "designer" / "base").resolve())
        self.assertEqual(extension.adopted(), {("Catalogs", "_ДемоПартнеры")})

    def test_layered_metadata(self):
        base = PROJECTS / "edt" / "workspace" / "Основа" / "src"
        extension = PROJECTS / "edt" / "outside" / "Расширение" / "src"
        layered = LayeredMetadata([Metadata(base, True), Metadata(extension, True)])
        partners = layered.object("Catalog", "Партнеры")
        self.assertEqual(set(partners.attributes), {"ИНН", "ext_Рейтинг"}, "заимствованный - с реквизитами основы")
        self.assertEqual(partners.attributes["ИНН"].title, "ИНН партнера")
        self.assertIsNotNone(layered.object("Catalog", "ext_Сегменты"), "собственный объект расширения")
        self.assertIsNone(layered.object("Catalog", "Нет"))
        self.assertEqual(Metadata(base, True).object("Catalog", "Партнеры").attributes.keys(), {"ИНН"},
                         "слой основы не изменился")

    def test_file_uri_and_long_path(self):
        self.assertEqual(file_uri_path("file:/D:/GIT/project/Tests"), Path("D:/GIT/project/Tests"))
        self.assertEqual(file_uri_path("file:/Users/user/project/Tests"), Path("/Users/user/project/Tests"))
        self.assertIsNone(file_uri_path("platform:/resource/Tests"))
        short = Path("C:/a/b")
        self.assertEqual(long_path(short), short)
        deep = Path("C:/" + "/".join(["каталог"] * 40))
        self.assertEqual(str(long_path(deep)).startswith("\\\\?\\"), sys.platform == "win32")

    def test_suggest_and_settings(self):
        mockups = temporary_folder(self)
        (mockups / ".git").mkdir()
        shutil.copytree(PROJECTS / "edt" / "workspace" / "Основа", mockups / "Основа")
        (mockups / "specs" / "макеты").mkdir(parents=True)
        self.assertEqual(suggest_projects(mockups / "specs" / "макеты"), mockups, "вверх - до корня репозитория")
        self.assertEqual(settings_sources(mockups), (None, None, []), "нет настроек")
        (mockups / SETTINGS_NAME).write_text(json.dumps({"projects": ".", "configuration": "Основа/src",
                                                         "extensions": ["нет/src"]}), encoding="utf-8")
        self.assertEqual(settings_sources(mockups), (mockups, mockups / "Основа" / "src", []),
                         "пропавшее расширение пропускается")


class ServiceServer:
    """Сервис по папке во временном каталоге."""

    def __init__(self, test: unittest.TestCase, folder: Path, src: Path = None):
        self.folder = folder
        sources = Sources(pictures.std_source(), src)
        self.workspace = Workspace(folder, sources)
        self.server = make_server(self.workspace, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, self.decode(response), response.headers
        except urllib.error.HTTPError as error:
            return error.code, self.decode(error), error.headers

    @staticmethod
    def decode(response):
        text = response.read().decode("utf-8")
        return json.loads(text) if response.headers.get("Content-Type", "").startswith("application/json") else text


class ServiceApiTest(unittest.TestCase):
    """HTTP-API сервиса по папке."""

    def setUp(self):
        self.folder = models_folder(self)
        self.service = ServiceServer(self, self.folder)
        # «Другая папка» запоминает папку у пользователя - не в домашний каталог того, кто гоняет тесты
        patcher = mock.patch("fmlib.workspace.user_dir", return_value=temporary_folder(self) / ".form-mockup")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_home_and_models(self):
        status, page, headers = self.service.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("fh-root", page)
        self.assertNotIn("/*FM_SCRIPT*/", page)
        status, info, _ = self.service.request("GET", "/models")
        self.assertEqual(status, 200)
        self.assertEqual(info["folder"], str(self.folder))
        self.assertIsNone(info["src"])
        self.assertIsNone(info["default"])
        self.assertEqual([item["file"] for item in info["models"]], ["zakaz.json", "spiski/spisok.json"])

    def test_model_by_file(self):
        status, data, headers = self.service.request("GET", "/model?file=spiski/spisok.json")
        self.assertEqual(status, 200)
        self.assertEqual(data["model"]["form"]["formKind"], "ListForm")
        model = data["model"]
        model["form"]["title"] = "Список заказов (правка)"
        request = urllib.request.Request(f"http://127.0.0.1:{self.service.port}/model?file=spiski/spisok.json",
                                         data=json.dumps(model, ensure_ascii=False).encode("utf-8"), method="PUT",
                                         headers={"Content-Type": "application/json", "If-Match": headers["ETag"]})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
        saved = json.loads((self.folder / "spiski" / "spisok.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["form"]["title"], "Список заказов (правка)")
        status, version, _ = self.service.request("GET", "/version?file=spiski/spisok.json")
        self.assertEqual(version["etag"], response.headers["ETag"])

    def test_model_without_file(self):
        status, data, _ = self.service.request("GET", "/model")
        self.assertEqual(status, 400, "у сервиса по папке нет макета запуска")
        self.assertIn("file", data["error"])

    def test_outside_folder(self):
        for path in ("/model?file=../x.json", "/edit?file=../../x.json", "/thumb?file=x.txt"):
            with self.subTest(path=path):
                status, data, _ = self.service.request("GET", path)
                self.assertEqual(status, 400)

    def test_edit_and_thumb(self):
        status, page, _ = self.service.request("GET", "/edit?file=zakaz.json")
        self.assertEqual(status, 200)
        self.assertIn("fe-editor", page)
        self.assertIn("Конструктор макета - zakaz.json", page)
        status, thumb, _ = self.service.request("GET", "/thumb?file=zakaz.json")
        self.assertEqual(status, 200)
        self.assertIn("window.FMRender", thumb)
        status, _, _ = self.service.request("GET", "/thumb?file=nope.json")
        self.assertEqual(status, 422)

    def test_create(self):
        status, result, _ = self.service.request("POST", "/models", {"file": "new/form.json", "kind": "ListForm"})
        self.assertEqual(status, 201)
        self.assertEqual(result["file"], "new/form.json")
        path = self.folder / "new" / "form.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"version": 1, "form": {"formKind": "ListForm", "items": []}})
        self.assertNotIn(b"\r\n", path.read_bytes())
        status, result, _ = self.service.request("POST", "/models", {"file": "new/form.json", "kind": "ListForm"})
        self.assertEqual(status, 409)
        status, result, _ = self.service.request("POST", "/models", {"file": "x.json", "kind": "Нет"})
        self.assertEqual(status, 422)
        status, result, _ = self.service.request("POST", "/models", {"file": "../x.json", "kind": "ListForm"})
        self.assertEqual(status, 422)

    def test_import_dropped_file(self):
        xml = DESIGNER_FORM.read_text(encoding="utf-8-sig")
        status, result, _ = self.service.request("POST", "/models", {"file": "partner.json", "name": "Form.xml", "xml": xml})
        self.assertEqual(status, 201, result)
        model = json.loads((self.folder / "partner.json").read_text(encoding="utf-8"))
        self.assertEqual(model["form"]["formKind"], "CatalogObjectForm")
        self.assertTrue(result["report"])
        status, result, _ = self.service.request("POST", "/models", {"file": "bad.json", "name": "Form.xml", "xml": "<x/>"})
        self.assertEqual(status, 422)
        self.assertIn("не форма", result["error"])
        status, result, _ = self.service.request("POST", "/models", {"file": "bad.json", "name": "a.txt", "xml": xml})
        self.assertEqual(status, 422)

    def test_sources_settings(self):
        src = designer_src(temporary_folder(self))
        status, result, _ = self.service.request("PUT", "/settings", {"src": str(src.parent)})
        self.assertEqual(status, 422)
        self.assertIn("не исходники", result["error"])
        status, result, _ = self.service.request("GET", "/config-forms")
        self.assertEqual(result, {"forms": [], "available": False})
        status, result, _ = self.service.request("PUT", "/settings", {"src": str(src)})
        self.assertEqual(status, 200)
        self.assertEqual(result["src"], str(src))
        self.assertEqual(json.loads((self.folder / SETTINGS_NAME).read_text(encoding="utf-8")), {"src": str(src)})
        status, result, _ = self.service.request("GET", "/config-forms")
        self.assertEqual([form["key"] for form in result["forms"]], ["Catalog.Партнеры.ФормаЭлемента"])
        status, result, _ = self.service.request("POST", "/models",
                                                 {"file": "from-config.json", "object": "Catalog.Партнеры.ФормаЭлемента"})
        self.assertEqual(status, 201, result)
        model = json.loads((self.folder / "from-config.json").read_text(encoding="utf-8"))
        self.assertEqual(model["form"]["formKind"], "CatalogObjectForm")
        self.assertEqual((model["origin"]["kind"], model["origin"]["object"]), ("config", "Catalog.Партнеры.ФормаЭлемента"))
        self.assertTrue(model["origin"]["at"])
        # Перезапуск: исходники - из настроек папки
        self.assertEqual(settings_src(self.folder), src)
        status, result, _ = self.service.request("PUT", "/settings", {"src": None})
        self.assertIsNone(result["src"])
        self.assertEqual(json.loads((self.folder / SETTINGS_NAME).read_text(encoding="utf-8")), {})

    def test_groups(self):
        """Группы: подкаталоги с макетами, созданная пустая группа видна, удаляется только пустая."""
        status, info, _ = self.service.request("GET", "/models")
        self.assertEqual(info["groups"], ["spiski"])
        self.assertEqual({model["file"]: model["group"] for model in info["models"]}, {"zakaz.json": "", "spiski/spisok.json": "spiski"})
        status, info, _ = self.service.request("POST", "/groups", {"group": "issue-12/Новые"})
        self.assertEqual(status, 201, info)
        self.assertEqual(info["groups"], ["issue-12/Новые", "spiski"])
        self.assertTrue((self.folder / "issue-12" / "Новые").is_dir())
        for bad in ("..", "a/../b", ".git", "out", "a:b", "", "x/"):
            with self.subTest(group=bad):
                status, result, _ = self.service.request("POST", "/groups", {"group": bad})
                self.assertEqual(status, 422, result)
        status, result, _ = self.service.request("POST", "/groups", {"group": "spiski"})
        self.assertEqual(status, 409)
        status, result, _ = self.service.request("DELETE", "/groups?group=" + quote("spiski"))
        self.assertEqual(status, 409, "группа с макетом не удаляется")
        status, info, _ = self.service.request("DELETE", "/groups?group=" + quote("issue-12/Новые"))
        self.assertEqual(status, 200, info)
        self.assertEqual(info["groups"], ["spiski"])
        self.assertNotIn("groups", json.loads((self.folder / SETTINGS_NAME).read_text(encoding="utf-8")))

    def test_tags_move_copy(self):
        """Метки в модели, перенос в группу с метками, отказ при занятом имени и открытом макете, копия с номером и
        `origin`, копия в другую папку и из нее."""
        status, info, _ = self.service.request("PUT", "/tags", {"file": "zakaz.json", "tags": [" issue-12 ", "ТЗ", "ТЗ", ""]})
        self.assertEqual(status, 200, info)
        self.assertEqual(info["tags"], ["issue-12", "ТЗ"])
        model = json.loads((self.folder / "zakaz.json").read_text(encoding="utf-8"))
        self.assertEqual(model["tags"], ["issue-12", "ТЗ"])
        # Перенос: метки едут с файлом
        status, result, _ = self.service.request("POST", "/move", {"file": "zakaz.json", "to": "spiski"})
        self.assertEqual((status, result), (200, {"file": "spiski/zakaz.json"}))
        status, info, _ = self.service.request("GET", "/models")
        moved = [model for model in info["models"] if model["file"] == "spiski/zakaz.json"][0]
        self.assertEqual(moved["tags"], ["issue-12", "ТЗ"])
        # Копия в корень, потом еще одна - с номером
        for expected in ("zakaz.json", "zakaz-2.json"):
            status, result, _ = self.service.request("POST", "/models", {"file": "zakaz.json", "copyFrom": "spiski/zakaz.json"})
            self.assertEqual((status, result["file"]), (201, expected))
        copy = json.loads((self.folder / "zakaz-2.json").read_text(encoding="utf-8"))
        self.assertEqual((copy["tags"], copy["origin"]["kind"], copy["origin"]["from"]), (["issue-12", "ТЗ"], "copy", "spiski/zakaz.json"))
        self.assertNotIn("folder", copy["origin"])
        # Занятое имя в группе и открытый в живой вкладке макет не переносятся
        status, result, _ = self.service.request("POST", "/move", {"file": "zakaz.json", "to": "spiski"})
        self.assertEqual(status, 409, result)
        self.service.server.lifetime.mark("tab-1", "zakaz-2.json")
        status, result, _ = self.service.request("POST", "/move", {"file": "zakaz-2.json", "to": "spiski"})
        self.assertEqual(status, 409)
        self.assertIn("закройте", result["error"])
        # Другая папка: копия туда и макет оттуда
        other = temporary_folder(self)
        status, result, _ = self.service.request("POST", "/models", {"file": "z.json", "copyFrom": "zakaz.json",
                                                                     "toFolder": str(other)})
        self.assertEqual((status, result["file"]), (201, "z.json"))
        self.assertEqual(json.loads((other / "z.json").read_text(encoding="utf-8"))["origin"]["folder"], str(self.folder.resolve()))
        status, listed, _ = self.service.request("GET", "/folder-models?path=" + quote(str(other)))
        self.assertEqual([model["file"] for model in listed["models"]], ["z.json"])
        status, result, _ = self.service.request("POST", "/models", {"file": "spiski/z.json", "copyFrom": "z.json",
                                                                     "fromFolder": str(other)})
        self.assertEqual((status, result["file"]), (201, "spiski/z.json"))
        status, result, _ = self.service.request("GET", "/folder-models?path=" + quote(str(other / "нет")))
        self.assertEqual(status, 404)

    def test_trash_and_restore(self):
        """Удаление в корзину папки и возврат на место; открытый в живой вкладке не удаляется."""
        self.service.server.lifetime.mark("tab-1", "zakaz.json")
        status, result, _ = self.service.request("POST", "/delete", {"file": "zakaz.json"})
        self.assertEqual(status, 409)
        self.service.server.lifetime.tabs.clear()
        status, result, _ = self.service.request("POST", "/delete", {"file": "spiski/spisok.json"})
        self.assertEqual(status, 200, result)
        trashed = result["trashed"]
        self.assertTrue(trashed.endswith("/spiski/spisok.json"), trashed)
        self.assertFalse((self.folder / "spiski" / "spisok.json").exists())
        self.assertTrue((self.folder / ".trash" / trashed).is_file())
        status, info, _ = self.service.request("GET", "/models")
        self.assertEqual([model["file"] for model in info["models"]], ["zakaz.json"], "корзина в список не попадает")
        # Место заняли - возврат с номером; корзина без пустых каталогов
        shutil.copy(LIST_EXAMPLE, self.folder / "spiski" / "spisok.json")
        status, result, _ = self.service.request("POST", "/restore", {"trashed": trashed})
        self.assertEqual((status, result), (200, {"file": "spiski/spisok-2.json"}))
        self.assertEqual(list((self.folder / ".trash").iterdir()), [])
        for bad in ("", "../zakaz.json", trashed):
            with self.subTest(trashed=bad):
                status, result, _ = self.service.request("POST", "/restore", {"trashed": bad})
                self.assertEqual(status, 422, result)

    def test_projects_settings(self):
        projects = edt_workspace(self)
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects)})
        self.assertEqual(status, 200, result)
        self.assertEqual(sorted(item["name"] for item in result["projects"]["items"]), ["КопияОсновы", "Основа", "Расширение"])
        self.assertIsNone(result["src"], "две конфигурации - выбор за пользователем")
        base = [item["src"] for item in result["projects"]["items"] if item["name"] == "Основа"][0]
        copy = [item["src"] for item in result["projects"]["items"] if item["name"] == "КопияОсновы"][0]
        extension = [item["src"] for item in result["projects"]["items"] if item["extension"]][0]
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects), "configuration": copy,
                                                                      "extensions": [extension]})
        self.assertEqual(status, 422, "основа расширения - другая копия")
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects), "configuration": base,
                                                                      "extensions": [extension]})
        self.assertEqual(status, 200, result)
        self.assertEqual((result["src"], result["extensions"]), (base, [extension]))
        stored = json.loads((self.folder / SETTINGS_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(stored), ["configuration", "extensions", "projects"])
        self.assertEqual(settings_sources(self.folder), (projects.resolve(), Path(base), [Path(extension)]))
        # Окна выбора и импорт видят объединение
        status, result, _ = self.service.request("GET", "/config-types")
        keys = [item["key"] for item in result["types"]] if isinstance(result, dict) else [item["key"] for item in result]
        self.assertIn("Catalog.ext_Сегменты", keys)
        self.assertIn("Catalog.Партнеры", keys)
        status, result, _ = self.service.request("GET", "/type-description?key=" + quote("Catalog.Партнеры"))
        self.assertLessEqual({"ИНН", "ext_Рейтинг"}, {item["name"] for item in result["attributes"]})
        status, result, _ = self.service.request("GET", "/config-forms")
        form = [item for item in result["forms"] if item["object"] == "Партнеры"][0]
        self.assertEqual((form["project"], form["key"]), ("Расширение", "Расширение:Catalog.Партнеры.ФормаЭлемента"))
        status, result, _ = self.service.request("POST", "/models", {"file": "partner.json", "object": form["key"]})
        self.assertEqual(status, 201, result)
        model = json.loads((self.folder / "partner.json").read_text(encoding="utf-8"))
        self.assertEqual([item.get("title") for item in model["form"]["items"]], ["ИНН партнера", "Рейтинг"],
                         "форма расширения видит реквизит основы")
        # Прежний `src` - одиночные исходники, папка проектов уходит
        status, result, _ = self.service.request("PUT", "/settings", {"projects": None})
        self.assertIsNone(result["projects"])
        self.assertIsNone(result["src"])

    def test_projects_single_configuration(self):
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(PROJECTS / "designer")})
        self.assertEqual(status, 200, result)
        self.assertEqual(Path(result["src"]), (PROJECTS / "designer" / "base").resolve(),
                         "одна конфигурация - она и ее расширения")
        self.assertEqual([Path(item) for item in result["extensions"]], [(PROJECTS / "designer" / "extension").resolve()])
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(temporary_folder(self))})
        self.assertEqual(status, 422)
        self.assertIn("нет исходников", result["error"])

    def test_projects_extensions_without_base(self):
        """В папке только расширения (репозиторий без основы) - берутся вместе, первое - главным слоем."""
        projects = temporary_folder(self, "formmockup-alone-")
        shutil.copytree(PROJECTS / "edt" / "outside" / "Расширение", projects / "Расширение")
        shutil.copytree(PROJECTS / "designer" / "extension", projects / "Выгрузка")
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects)})
        self.assertEqual(status, 200, result)
        self.assertIsNone(result["src"], "два расширения без основы - выбор за пользователем")
        items = {Path(item["src"]).parent.name if item["format"] == "edt" else Path(item["src"]).name: item
                 for item in result["projects"]["items"]}
        self.assertEqual(items["Расширение"]["baseProject"], "Основа", "подсказка, какую основу искать")
        first, second = items["Расширение"]["src"], items["Выгрузка"]["src"]
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects), "configuration": first,
                                                                      "extensions": [second]})
        self.assertEqual(status, 200, result)
        self.assertEqual((result["src"], result["extensions"]), (first, [second]))
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects), "configuration": first,
                                                                      "extensions": [first]})
        self.assertEqual(status, 422, "то же расширение дважды")
        status, result, _ = self.service.request("PUT", "/settings", {"projects": str(projects), "configuration": "",
                                                                      "extensions": []})
        self.assertEqual(status, 200, result)
        self.assertIsNone(result["src"], "флажки сняты - без исходников")

    def test_switch_folder(self):
        other = temporary_folder(self)
        shutil.copy(EXAMPLE, other / "other.json")
        status, info, _ = self.service.request("PUT", "/folder", {"path": str(other)})
        self.assertEqual(status, 200)
        self.assertEqual(info["folder"], str(other))
        self.assertEqual([item["file"] for item in info["models"]], ["other.json"])
        self.assertEqual(workspace.last_folder(), other)
        status, info, _ = self.service.request("PUT", "/folder", {"path": str(other / "нет")})
        self.assertEqual(status, 422)

    def test_stale_folder_tab_rejected(self):
        """Вкладка, открытая до «Другой папки», не пишет и не удаляет одноименный макет новой папки, даже если файлы
        одинаковые и версия совпадает: ее запросы несут свою папку - 409 folderChanged."""
        other = temporary_folder(self)
        shutil.copy(self.folder / "zakaz.json", other / "zakaz.json")
        page = self.service.request("GET", "/edit?file=zakaz.json")[1]
        data = page.split('<script id="fm-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(data.replace("<\\/", "</"))["editor"]["folder"], str(self.folder),
                         "страница знает свою папку")
        mine ="file=zakaz.json&folder=" + urllib.request.quote(str(self.folder))
        status, data, headers = self.service.request("GET", "/model?" + mine)
        self.assertEqual(status, 200)
        etag = headers["ETag"]
        status, _, _ = self.service.request("PUT", "/folder", {"path": str(other)})
        self.assertEqual(status, 200)
        before = (other / "zakaz.json").read_bytes()
        model = data["model"]
        model["form"]["title"] = "Правка старой вкладки"
        request = urllib.request.Request(f"http://127.0.0.1:{self.service.port}/model?" + mine, method="PUT",
                                         data=json.dumps(model, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "If-Match": etag})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 409)
        answer = json.loads(caught.exception.read().decode("utf-8"))
        self.assertTrue(answer["folderChanged"])
        self.assertEqual(answer["folder"], str(other))
        self.assertEqual((other / "zakaz.json").read_bytes(), before, "файл новой папки не тронут")
        for method, path, body in (("GET", "/version?" + mine, None), ("POST", "/delete?folder=" +
                                   urllib.request.quote(str(self.folder)), {"file": "zakaz.json"})):
            status, answer, _ = self.service.request(method, path, body)
            self.assertEqual((status, answer.get("folderChanged")), (409, True), path)
        self.assertTrue((other / "zakaz.json").exists(), "удаление из старой вкладки не прошло")
        # Без папки в запросе (API агента) - как раньше; вернули сервис к папке вкладки - вкладка снова своя
        self.assertEqual(self.service.request("GET", "/version?file=zakaz.json")[0], 200)
        self.service.request("PUT", "/folder", {"path": str(self.folder)})
        self.assertEqual(self.service.request("GET", "/version?" + mine)[0], 200)

    def test_dirs(self):
        status, listed, _ = self.service.request("GET", "/dirs")
        self.assertEqual(status, 200)
        self.assertEqual(listed["path"], str(self.folder))
        self.assertEqual([item["name"] for item in listed["dirs"]], ["out", "spiski"])
        status, _, _ = self.service.request("GET", "/dirs?path=" + urllib.request.quote(str(self.folder / "нет")))
        self.assertEqual(status, 404)


class LaunchModelTest(unittest.TestCase):
    """`serve model.json`: сервис на папку файла, запросы без `file` - к макету запуска (прежний API)."""

    def test_default_and_other_models(self):
        folder = models_folder(self)
        sources = Sources(None, None)
        from fmlib.server import Editor
        editor = Editor(folder / "zakaz.json", sources=sources)
        service = ServiceServer.__new__(ServiceServer)
        service.workspace = Workspace(folder, sources, editor)
        service.server = make_server(service.workspace, 0)
        service.port = service.server.server_address[1]
        threading.Thread(target=service.server.serve_forever, daemon=True).start()
        self.addCleanup(service.close)
        status, info, _ = service.request("GET", "/models")
        self.assertEqual(info["default"], "zakaz.json")
        status, data, _ = service.request("GET", "/model")
        self.assertEqual(data["model"]["form"]["formKind"], "DocumentObjectForm")
        status, data, _ = service.request("GET", "/model?file=spiski/spisok.json")
        self.assertEqual(data["model"]["form"]["formKind"], "ListForm")


class ServeFolderCliTest(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(CLI), "serve", *arguments], capture_output=True, text=True,
                              encoding="utf-8", timeout=30)

    def test_folder_rejects_file_options(self):
        folder = temporary_folder(self)
        result = self.run_cli(str(folder), "--no-browser", "--new")
        self.assertEqual(result.returncode, 2)
        self.assertIn("только с файлом", result.stderr)

    def test_folder_bad_src(self):
        folder = temporary_folder(self)
        result = self.run_cli(str(folder), "--no-browser", "--src", str(folder))
        self.assertEqual(result.returncode, 2)
        self.assertIn("не исходники", result.stderr)


@unittest.skipUnless(CHROME, "Chrome не найден")
class HomePageTest(unittest.TestCase):
    """Стартовая страница в браузере: список макетов, миниатюры, переход в конструктор."""

    def dump(self, service: ServiceServer, path: str, marker: str, size: str = "1400,900") -> dict:
        dom = render.run_chrome(CHROME, [f"--window-size={size}", "--virtual-time-budget=8000", "--dump-dom",
                                         f"http://127.0.0.1:{service.port}{path}"])
        found = re.findall(rf'<pre id="{marker}"[^>]*>(.*?)</pre>', dom, re.S)
        self.assertTrue(found and found[-1].strip(), f"страница не отдала итог ({marker} пуст)")
        return json.loads(html.unescape(found[-1])), dom

    def test_home_lists_models(self):
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        result, dom = self.dump(service, "/", "fh-result")
        self.assertEqual(result["error"], "")
        self.assertEqual(result["models"], ["zakaz.json", "spiski/spisok.json"])
        self.assertIn('href="/edit?file=spiski%2Fspisok.json"', dom)
        self.assertIn("/thumb?file=zakaz.json", dom)
        self.assertFalse(result["overflow"])
        # Узкое окно (меньше 526 px headless Chrome не дает): без горизонтальной прокрутки
        narrow, _ = self.dump(service, "/", "fh-result", "500,900")
        self.assertFalse(narrow["overflow"])

    def test_dialogs_open(self):
        folder = models_folder(self)
        service = ServiceServer(self, folder, designer_src(temporary_folder(self)))
        titles = {"new": "Новая форма", "import": "Импорт из 1С", "config": "Импорт из 1С", "folder": "Папка макетов",
                  "src": "Папка проектов", "mockups": "Импорт из 1С", "group": "Новая группа"}
        for name, title in titles.items():
            with self.subTest(dialog=name):
                result, dom = self.dump(service, "/#open=" + name, "fh-result")
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["dialog"], title)
        # Дерево исходников: виды свернуты, поиск раскрывает ветки найденного - вид, объект, форма
        result, dom = self.dump(service, "/#open=config", "fh-result")
        self.assertIn(">Справочники<", dom, "вид - во множественном числе, как в конфигураторе")
        self.assertNotIn(">ФормаЭлемента<", dom, "виды свернуты")
        self.assertIn("data:image/svg+xml;base64,", dom, "значки видов")
        result, dom = self.dump(service, "/#open=config&find=" + quote("Партнеры"), "fh-result")
        rows = re.findall(r'<button class="fh-item fh-tree-row[^"]*"[^>]*style="padding-left: (\d+)px;"[^>]*>.*?'
                          r'<span class="fh-tree-text">([^<]*)</span>', dom)
        self.assertIn(("10", "Справочники"), rows)
        self.assertIn(("28", "Партнеры"), rows)
        self.assertIn(("46", "ФормаЭлемента"), rows)

    def test_groups_and_tags_page(self):
        """Разделы по группам, пустая созданная группа, метки на карточках и фильтр по ним."""
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        service.request("PUT", "/tags", {"file": "zakaz.json", "tags": ["issue-12", "ТЗ"]})
        service.request("PUT", "/tags", {"file": "spiski/spisok.json", "tags": ["ТЗ"]})
        service.request("POST", "/groups", {"group": "Пустая"})
        result, dom = self.dump(service, "/", "fh-result")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["sections"], [["", ["zakaz.json"]], ["spiski", ["spiski/spisok.json"]], ["Пустая", []]])
        self.assertEqual(result["tags"], ["issue-12", "ТЗ"])
        self.assertIn("Удалить группу", dom)
        self.assertEqual(dom.count('class="fh-card-more"'), 2)
        self.assertFalse(result["overflow"])
        # Фильтр по метке: пустые разделы уходят
        result, dom = self.dump(service, "/#tags=" + quote("issue-12"), "fh-result")
        self.assertEqual(result["sections"], [["", ["zakaz.json"]]])
        result, dom = self.dump(service, "/#tags=" + quote("ТЗ"), "fh-result")
        self.assertEqual([section[0] for section in result["sections"]], ["", "spiski"])

    def test_card_menu_and_delete(self):
        """Меню макета (кнопка «⋯» и правая кнопка): открыть, метки, перенос, копия, дубль, путь, удаление; окно удаления
        с именем макета (владелец 08.11.2026)."""
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        result, dom = self.dump(service, "/#open=menu&file=zakaz.json", "fh-result")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["menu"], ["Открыть", "Открыть в новой вкладке", "Метки...", "Переместить в...",
                                          "Копировать в...", "Дублировать", "Скопировать путь к файлу", "Удалить..."])
        result, dom = self.dump(service, "/#open=delete&file=zakaz.json", "fh-result")
        self.assertEqual(result["dialog"], "Удалить макет")
        self.assertIn("zakaz.json", dom)
        # «Дублировать» - копия рядом со свободным именем
        status, created, _ = service.request("POST", "/models", {"file": "spiski/spisok.json", "copyFrom": "spiski/spisok.json"})
        self.assertEqual((status, created["file"]), (201, "spiski/spisok-2.json"))

    def test_projects_block(self):
        """Папка проектов на странице: конфигурации - переключателем, ее расширения - флажками."""
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        projects = edt_workspace(self)
        status, info, _ = service.request("PUT", "/settings", {"projects": str(projects)})
        base = [item["src"] for item in info["projects"]["items"] if item["name"] == "Основа"][0]
        extension = [item["src"] for item in info["projects"]["items"] if item["extension"]][0]
        service.request("PUT", "/settings", {"projects": str(projects), "configuration": base, "extensions": [extension]})
        result, dom = self.dump(service, "/", "fh-result")
        self.assertEqual(result["errors"], [])
        self.assertEqual(sorted(result["choices"]), sorted([base, extension]))
        self.assertEqual(dom.count('<label class="fh-project'), 3, "две конфигурации, расширение - под своей основой")
        self.assertFalse(result["overflow"])
        # Конфигурация с расширениями - формы под своим проектом верхним уровнем дерева (у основы фикстуры форм нет)
        result, dom = self.dump(service, "/#open=config", "fh-result")
        projects = re.findall(r'<button class="[^"]*fh-tree-project"[^>]*>.*?<span class="fh-tree-text">([^<]*)</span>', dom)
        self.assertEqual(projects, ["Расширение"])
        result, dom = self.dump(service, "/#open=config&find=" + quote("Партнеры"), "fh-result")
        self.assertIn(">ФормаЭлемента<", dom)

    def test_editor_opens_model_by_file(self):
        folder = models_folder(self)
        service = ServiceServer(self, folder)
        dom = render.run_chrome(CHROME, ["--window-size=1600,1000", "--virtual-time-budget=8000", "--dump-dom",
                                         f"http://127.0.0.1:{service.port}/edit?file=spiski%2Fspisok.json#do="])
        found = re.findall(r'<pre id="fe-result"[^>]*>(.*?)</pre>', dom, re.S)
        self.assertTrue(found and found[-1].strip())
        result = json.loads(html.unescape(found[-1]))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["model"]["form"]["formKind"], "ListForm")
        self.assertIn('class="fe-home"', dom)


if __name__ == "__main__":
    unittest.main()
