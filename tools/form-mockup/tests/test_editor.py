"""Сценарии страницы конструктора в headless Chrome.

Сервер - в потоке на свободном порту (как в test_server), страница выполняет действия из адреса
(`#do=...`, editor.js) и пишет итог JSON в pre#fe-result. Запись мимо конструктора - подмена
`Editor.version`: на N-м опросе версии тест сам пишет файл, как это сделал бы агент. Без Chrome
тесты пропускаются.
"""

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fmlib import render  # noqa: E402
from fmlib.server import Editor, dump, empty_model  # noqa: E402
from support import temp_dir  # noqa: E402
from test_server import Server  # noqa: E402

EXAMPLE = ROOT / "examples" / "zakaz-pokupatelya.json"
STALO = ROOT / "examples" / "pravki" / "zakaz-pokupatelya-stalo.json"
VITRINA = ROOT / "tests" / "fixtures" / "vitrina.json"
# Исходники EDT фикстуры импорта: элемент стиля конфигурации для закладки «Из стиля»
EDT_SRC = ROOT / "tests" / "fixtures" / "import" / "edt"
CHROME, _ = render.find_chrome()
BUDGET = 8000


def page(server: Server, actions: list, budget: int = BUDGET, size: str = "1600,1000") -> dict:
    url = f"http://127.0.0.1:{server.port}/edit#do=" + quote(";".join(actions))
    dom = render.run_chrome(CHROME, [f"--window-size={size}", f"--virtual-time-budget={budget}", "--dump-dom", url])
    found = re.findall(r'<pre id="fe-result"[^>]*>(.*?)</pre>', dom, re.S)
    if not found or not found[-1].strip():
        raise AssertionError("страница не отдала итог (fe-result пуст)")
    return json.loads(html.unescape(found[-1]))


def find(node: dict, name: str):
    nested = ([node["commandBar"]] if isinstance(node.get("commandBar"), dict) else []) + node.get("items", [])
    for child in nested:
        if child.get("name") == name:
            return child
        found = find(child, name)
        if found:
            return found
    return None


def hooked(writes: dict):
    """Editor, который на N-м опросе версии пишет в файл текст `writes[N]` (или вызывает функцию)."""

    class Hooked(Editor):
        calls = 0

        def version(self):
            Hooked.calls += 1
            action = writes.get(Hooked.calls)
            if callable(action):
                action(self)
            elif action is not None:
                self.path.write_text(action, encoding="utf-8")
            return super().version()

    return Hooked


def changed_title(title: str) -> str:
    model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    model["form"]["title"] = title
    return dump(model)


@unittest.skipUnless(CHROME, "Chrome не найден")
class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.close()

    def open(self, source=EXAMPLE, editor_class=Editor):
        self.server = Server(source, editor_class)
        return self.server

    def test_form_not_squeezed_by_column(self):
        """Макет - тот же вид, что у render: окно формы своей ширины, узкая колонка его не сжимает."""
        server = self.open(ROOT / "examples" / "spisok-zakazov.json")
        wide = page(server, [], size="3200,1000")
        narrow = page(server, [], size="1400,1000")
        self.assertGreater(wide["windowWidth"], 1000)
        self.assertEqual(narrow["windowWidth"], wide["windowWidth"])

    def test_layout_click_selects_tree_node(self):
        result = page(self.open(), ["click:Договор"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["selected"], "Договор")
        self.assertEqual(result["treeSelected"], "Договор")
        self.assertTrue(result["frame"])
        self.assertEqual(result["propsTitle"], "Свойства: Поле ввода")

    def test_tree_selects_on_inactive_page(self):
        result = page(self.open(), ["tree:Склад"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["currentPages"]["ГруппаСтраницы"], "ГруппаДополнительно")
        self.assertTrue(result["frame"])

    def test_tree_selects_hidden_and_collapsed(self):
        server = self.open(VITRINA)
        hidden = page(server, ["tree:СкрытоеПоле"])
        self.assertEqual(hidden["errors"], [])
        self.assertFalse(hidden["hidden"], "выбор скрытого не включает «Скрытые»: макет без скрытых")
        self.assertFalse(hidden["frame"], "скрытый на макете не выделяется")
        self.assertEqual(hidden["selected"], "СкрытоеПоле", "выбран в дереве и свойствах")
        shown = page(server, ["hidden:on", "tree:СкрытоеПоле"])
        self.assertTrue(shown["hidden"])
        self.assertTrue(shown["frame"], "при «Скрытых» - выделен")
        folded = page(server, ["tree:Поле8"])
        self.assertNotIn("ГруппаСвернутая", folded["collapsed"])
        self.assertEqual(folded["currentPages"]["Страницы"], "СтраницаГруппы")
        self.assertTrue(folded["frame"])

    def test_tree_keys_and_form_bar(self):
        result = page(self.open(), ["tree:Форма", "key:ArrowDown"])
        self.assertEqual(result["selected"], "ФормаКоманднаяПанель")
        self.assertEqual(result["treeKeys"][:3], ["Форма", "ФормаКоманднаяПанель", "ПодменюПечать"])
        # Колонки таблицы - после ее командной панели, как в дереве конфигуратора
        keys = result["treeKeys"]
        self.assertLess(keys.index("ТоварыКоманднаяПанель"), keys.index("ТоварыНомерСтроки"))
        result = page(self.server, ["tree:ТоварыНомерСтроки", "key:ArrowLeft"])
        self.assertEqual(result["selected"], "Товары")

    def test_selection_kept_after_edit(self):
        result = page(self.open(), ["tree:Контрагент", "set:title=Покупатель", "set:name=Покупатель"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["selected"], "Покупатель")
        self.assertTrue(result["frame"])


@unittest.skipUnless(CHROME, "Chrome не найден")
class PropertiesTest(unittest.TestCase):
    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def test_groups_like_palette(self):
        result = page(self.server, ["tree:Контрагент"])
        self.assertEqual(result["groups"], ["Основные", "Использование", "Оформление", "Расположение", "Макет"])
        props = [item["prop"] for item in result["props"]]
        self.assertEqual(props[:4], ["name", "title", "type", "dataPath"])
        self.assertLess(props.index("width"), props.index("height"))
        self.assertEqual(props[-4:], ["note", "generated", "sample", "renamedFrom"])
        unset = {item["prop"]: item for item in result["props"] if not item["set"]}
        self.assertEqual(unset["titleLocation"]["value"], "Auto", "незаданное - значением по умолчанию")
        self.assertTrue(unset["visible"]["value"])

    def test_values_change_model_and_layout(self):
        result = page(self.server, ["tree:Контрагент", "set:title=Покупатель", "set:titleLocation=Top",
                                    "set:width=30", "set:choiceButton=false", "set:markIncomplete="])
        self.assertEqual(result["errors"], [])
        node = find(result["model"]["form"], "Контрагент")
        self.assertEqual(node["title"], "Покупатель")
        self.assertEqual(node["titleLocation"], "Top")
        self.assertEqual(node["width"], 30)
        self.assertIs(node["choiceButton"], False)
        self.assertNotIn("markIncomplete", node)
        self.assertIn("Покупатель", result["selectedText"])
        self.assertTrue(result["dirty"])
        self.assertEqual(result["status"], "есть несохранённые правки")
        hidden = page(self.server, ["tree:Контрагент", "set:visible=false"])
        self.assertIs(find(hidden["model"]["form"], "Контрагент")["visible"], False)
        self.assertFalse(hidden["frame"], "скрытый элемент без «Скрытые» на макете не виден")

    def test_invalid_values_not_applied(self):
        result = page(self.server, ["tree:Контрагент", "set:width=-3", "set:titleHeight=abc",
                                    "set:backColor=#12", "set:name=Договор"])
        node = find(result["model"]["form"], "Контрагент")
        self.assertEqual(sorted(result["invalid"]), ["backColor", "name", "titleHeight", "width"])
        self.assertIn("занято", result["invalid"]["name"])
        for prop in ("width", "titleHeight", "backColor"):
            self.assertNotIn(prop, node)
        self.assertFalse(result["dirty"])
        values = {item["prop"]: item.get("value") for item in result["props"]}
        self.assertEqual(values["titleHeight"], "abc", "набранное остается в поле с причиной")
        self.assertEqual(values["name"], "Договор")

    def test_default_removes_property(self):
        result = page(self.server, ["tree:Товары", "set:footer=false", "set:heightInTableRows=5", "set:changeRowSet=false"])
        node = find(result["model"]["form"], "Товары")
        self.assertNotIn("footer", node)
        self.assertNotIn("heightInTableRows", node, "значение по умолчанию в модель не пишется")
        self.assertIs(node["changeRowSet"], False)
        # Новое свойство - до подчиненных, правка в файле рядом с остальными свойствами
        keys = list(node)
        self.assertLess(keys.index("changeRowSet"), keys.index("commandBar"))

    def test_buttons_inside_field(self):
        # У флажка кнопки «по умолчанию» нет: флажок, возвращенный к умолчанию, сам убирает свойство
        result = page(self.server, ["tree:Контрагент", "set:visible=false", "set:title=Покупатель", "set:width=30"])
        self.assertEqual(result["errors"], [])
        self.assertIn("title", result["resets"])
        self.assertIn("width", result["resets"])
        self.assertNotIn("visible", result["resets"])
        self.assertNotIn("markIncomplete", result["resets"], "список «Да / Нет» - тоже без кнопки")
        back = page(self.server, ["tree:Контрагент", "set:visible=false", "set:visible=true"])
        self.assertNotIn("visible", find(back["model"]["form"], "Контрагент"))
        # «+/-» у целого: от заданного, от умолчания или нуля, не ниже границы схемы
        result = page(self.server, ["tree:Контрагент", "set:width=30", "spin:width=up", "spin:width=up",
                                    "spin:height=down", "spin:titleHeight=up"])
        self.assertEqual(result["errors"], [])
        node = find(result["model"]["form"], "Контрагент")
        self.assertEqual(node["width"], 32)
        self.assertNotIn("height", node, "пустое у границы схемы - без правки")
        self.assertEqual(node["titleHeight"], 1, "незаданное без умолчания - от нуля")
        self.assertIn("width", result["spins"])
        self.assertEqual(result["focused"], "titleHeight", "фокус остается в поле после «+/-»")

    def test_props_by_data_type(self):
        """Тип значения поля - из реквизита (владелец): в панели элемента его нет, формат - по типу."""
        props = lambda result: [item["prop"] for item in result["props"]]
        derived = ("dataType", "length", "digits", "fractionDigits", "dateFractions", "enumValues")
        ref = page(self.server, ["tree:Контрагент"])
        for prop in derived + ("format",):
            self.assertNotIn(prop, props(ref), prop + " - не у ссылки")
        number = page(self.server, ["tree:ТоварыЦена"])
        self.assertIn("format", props(number))
        for prop in derived:
            self.assertNotIn(prop, props(number), prop + " - тип правится у реквизита")

    def test_type_follows_data_path(self):
        """Смена пути к данным переносит в поле тип и квалификаторы реквизита."""
        result = page(self.server, ["tree:ТоварыЦена", "set:dataPath=Объект.Товары.Номенклатура"])
        self.assertEqual(result["errors"], [])
        node = find(result["model"]["form"], "ТоварыЦена")
        self.assertEqual(node["dataType"], "ref")
        self.assertNotIn("digits", node)
        self.assertNotIn("fractionDigits", node)
        number = page(self.server, ["tree:Комментарий", "set:dataPath=Объект.СуммаДокумента"])
        node = find(number["model"]["form"], "Комментарий")
        self.assertEqual((node["dataType"], node["digits"], node["fractionDigits"]), ("number", 15, 2))
        unknown = page(self.server, ["tree:Склад", "set:dataPath=Нет.Такого"])
        self.assertEqual(find(unknown["model"]["form"], "Склад")["dataType"], "ref", "путь не найден - данные не трогаются")

    def test_props_by_place(self):
        """Свойства по месту (places): свойства колонки - только у колонки, положение в командной
        панели - у кнопки панели, свойств, которых у вида в 1С нет, панель не показывает."""
        props = lambda result: [item["prop"] for item in result["props"]]
        column_only = ("showInHeader", "fixingInTable", "footerText", "headerPicture")
        body = page(self.server, ["tree:Контрагент"])
        column = page(self.server, ["tree:ТоварыЦена"])
        table = page(self.server, ["tree:Товары"])
        for prop in column_only:
            self.assertNotIn(prop, props(body), prop + " - не у поля вне таблицы")
            self.assertIn(prop, props(column), prop + " - у колонки")
        for prop in ("showInHeader", "fixingInTable", "headerPicture"):
            self.assertNotIn(prop, props(table), prop + " - у таблицы в 1С нет")
        self.assertIn("hyperlink", props(page(self.server, ["tree:СуммаДокумента"])))
        self.assertNotIn("hyperlink", props(page(self.server, ["tree:ТоварыНомерСтроки"])), "в колонке игнорируется")
        button = page(self.server, ["tree:ТоварыПодобрать"])
        self.assertIn("locationInCommandBar", props(button))
        self.assertNotIn("toolTip", props(button), "подсказка кнопки в 1С - у команды")
        check = page(self.server, ["tree:Предоплата"])
        for prop in ("width", "height", "horizontalStretch", "verticalStretch"):
            self.assertNotIn(prop, props(check), prop + " - у поля флажка в 1С нет")
        self.assertNotIn("inputHint", props(page(self.server, ["tree:ТоварыЦена"])), "у числа подсказка ввода не выводится")
        # Записанное в модели видно и вне своего места: его можно сбросить
        moved = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        find(moved["form"], "Контрагент")["showInHeader"] = False
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            path.write_text(dump(moved), encoding="utf-8")
            other = Server(path)
            try:
                self.assertIn("showInHeader", props(page(other, ["tree:Контрагент"])))
            finally:
                other.close()

    def test_rename_sets_renamed_from(self):
        result = page(self.server, ["tree:Договор", "set:name=Договор2", "set:name=ДоговорКонтрагента",
                                    "tree:Склад", "set:name=СкладОтгрузки", "set:name=Склад"])
        contract = find(result["model"]["form"], "ДоговорКонтрагента")
        self.assertEqual(list(contract)[:3], ["type", "name", "renamedFrom"])
        self.assertEqual(contract["renamedFrom"], "Договор", "имя из файла на открытии, а не промежуточное")
        self.assertNotIn("renamedFrom", find(result["model"]["form"], "Склад"), "возврат имени снимает renamedFrom")

    def test_default_command_bar_materialized(self):
        result = page(self.server, ["tree:ТоварыКоманднаяПанель", "set:horizontalAlign=Right"])
        bar = find(result["model"]["form"], "Товары")["commandBar"]
        self.assertEqual(bar["horizontalAlign"], "Right")
        self.assertEqual(bar["name"], "ТоварыКоманднаяПанель")

    def test_extended_tooltip_node(self):
        result = page(self.server, ["tree:Контрагент", "set:extendedTooltip=Покупатель по договору", "tree:@tip:Контрагент"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["treeSelected"], "@tip:Контрагент")
        self.assertEqual(result["propsTitle"], "Свойства: Поле ввода")
        self.assertEqual(result["focused"], "extendedTooltip")
        self.assertTrue(result["frame"], "рамка - у самого элемента")

    def test_search_and_alphabetical(self):
        result = page(self.server, ["tree:Контрагент", "search:кнопка"])
        self.assertEqual([item["prop"] for item in result["props"]],
                         ["dropListButton", "choiceButton", "clearButton", "openButton", "createButton"])
        result = page(self.server, ["tree:Склад", "alpha:on"])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["props"][0]["prop"], "autoMaxWidth")


@unittest.skipUnless(CHROME, "Chrome не найден")
class ChooserTest(unittest.TestCase):
    """Окна выбора: дерево пути к данным по месту элемента, «Добавить реквизит», исключенные команды."""

    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def test_path_in_body_unlimited_by_ref(self):
        deep = "Объект.Контрагент.ГоловнойКонтрагент.ГоловнойКонтрагент.ИНН"
        result = page(self.server, ["tree:Контрагент", "choose:dataPath"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["dialog"]["mode"], "body")
        self.assertEqual(result["dialog"]["chosen"], "Объект.Контрагент", "текущее значение выбрано в дереве")
        result = page(self.server, ["tree:Контрагент", "choose:dataPath", "pick:" + deep, "ok"])
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["dialog"])
        self.assertEqual(find(result["model"]["form"], "Контрагент")["dataPath"], deep)
        # Поле вне таблицы - без табличных частей; тип - по-русски
        rows = page(self.server, ["tree:Контрагент", "choose:dataPath"])
        paths = [row["path"] for row in rows["dialog"]["rows"]]
        self.assertIn("Объект.Контрагент", paths)
        self.assertNotIn("Объект.Товары", paths)
        self.assertIn("ДокументОбъект.ЗаказПокупателя", rows["dialog"]["infos"])

    def test_path_in_column_inside_table(self):
        result = page(self.server, ["tree:ТоварыЦена", "choose:dataPath"])
        self.assertEqual(result["dialog"]["mode"], "column")
        self.assertEqual(result["dialog"]["chosen"], "Объект.Товары.Цена")
        rows = {row["path"]: row["off"] for row in result["dialog"]["rows"]}
        # Ветка своей таблицы раскрыта, родители видны, но не выбираются; прочих реквизитов нет
        self.assertEqual(list(rows)[:3], ["Объект", "Объект.Товары", "Объект.Товары.LineNumber"])
        self.assertTrue(rows["Объект"] and rows["Объект.Товары"])
        self.assertFalse(rows["Объект.Товары.Цена"])
        self.assertNotIn("Объект.Контрагент", rows)
        top = [path for path in rows if path.count(".") == 2]
        self.assertEqual(top, ["Объект.Товары." + name for name in
                               ("LineNumber", "Номенклатура", "Количество", "Цена", "Сумма", "СтавкаНДС", "СуммаНДС")])
        self.assertEqual(result["dialog"]["names"][2], "НомерСтроки", "стандартный реквизит - русским именем")
        result = page(self.server, ["tree:ТоварыЦена", "choose:dataPath", "pick:Объект.Товары.Номенклатура", "ok"])
        self.assertEqual(find(result["model"]["form"], "ТоварыЦена")["dataPath"], "Объект.Товары.Номенклатура")

    def test_path_of_table_only_collections(self):
        result = page(self.server, ["tree:Товары", "choose:dataPath", "pick:Объект.Товары"])
        self.assertEqual(result["dialog"]["mode"], "table")
        rows = {row["path"]: row["off"] for row in result["dialog"]["rows"]}
        self.assertTrue(rows["Объект"], "объект - не коллекция")
        self.assertFalse(rows["Объект.Товары"])
        self.assertNotIn("Объект.Контрагент", rows, "то, что не ведет к коллекции, скрыто")
        self.assertNotIn("Объект.Товары.Номенклатура", rows, "коллекция в дереве таблицы не раскрывается")
        # Через ссылку таблица не предлагается: ссылка не раскрывается
        broken = page(self.server, ["tree:Товары", "choose:dataPath", "pick:Объект.Контрагент.ИНН"])
        self.assertTrue(any("нет строки пути" in error for error in broken["errors"]))

    def test_path_keys_and_no_add_form(self):
        """Реквизиты заводятся в левой колонке: в окне пути формы добавления нет; дерево - стрелками."""
        result = page(self.server, ["tree:Комментарий", "choose:dataPath", "key:ArrowUp"])
        self.assertEqual(result["errors"], [])
        self.assertNotIn("Добавить реквизит", result["dialog"]["names"])
        self.assertEqual(result["dialog"]["chosen"], "Объект.Склад", "вверх - предыдущий реквизит")
        folded = page(self.server, ["tree:Комментарий", "choose:dataPath", "key:ArrowLeft", "key:ArrowLeft"])
        self.assertEqual(folded["dialog"]["cursor"], "Объект", "влево - к родителю")
        self.assertEqual(folded["dialog"]["chosen"], "Объект.Комментарий", "объект - не поле, выбор остается")
        self.assertEqual([row["path"] for row in folded["dialog"]["rows"]], ["Объект"], "влево на родителе - свернуть")
        opened = page(self.server, ["tree:Комментарий", "choose:dataPath", "key:ArrowLeft", "key:ArrowLeft",
                                    "key:ArrowRight", "key:ArrowRight", "key:Enter"])
        self.assertEqual(find(opened["model"]["form"], "Комментарий")["dataPath"], "Объект.Number",
                         "вправо - раскрыть, еще вправо - к первому подчиненному, Enter - выбрать")

    def test_excluded_commands(self):
        before = page(self.server, ["tree:Товары"])
        result = page(self.server, ["tree:Товары", "choose:excludedCommands", "command:Add=false",
                                    "command:SortListAsc=false", "ok"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Товары")["excludedCommands"], ["Add", "SortListAsc"])
        self.assertIn("Добавить", before["selectedText"])
        self.assertNotIn("Добавить", result["selectedText"], "макет перерисовал панель таблицы")
        # Флажок возвращен - команда уходит из исключенных, пустой список - свойство убирается
        back = page(self.server, ["tree:Товары", "choose:excludedCommands", "command:Add=false", "ok",
                                  "choose:excludedCommands", "command:Add=true", "ok"])
        self.assertNotIn("excludedCommands", find(back["model"]["form"], "Товары"))
        opened = page(self.server, ["tree:Товары", "choose:excludedCommands"])
        self.assertIn({"name": "MoveUp", "on": True}, opened["dialog"]["commands"])


@unittest.skipUnless(CHROME, "Chrome не найден")
class ValueChooserTest(unittest.TestCase):
    """Окна выбора значений: цвет, формат, список выбора, картинка."""

    def setUp(self):
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.close()

    def serve(self, change=None):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        if change:
            change(model)
        folder = Path(temp_dir(prefix="formmockup-choosers-"))
        source = folder / "model.json"
        source.write_text(dump(model), encoding="utf-8")
        server = Server(source)
        self.servers.append(server)
        return server

    def test_color_style_web_rgb(self):
        def styled(model):
            model["styles"] = {"ГиперссылкаЦвет": "#1C55AE"}
        server = self.serve(styled)
        opened = page(server, ["tree:Склад", "choose:backColor"])
        self.assertEqual(opened["errors"], [])
        self.assertEqual(opened["dialog"]["tab"], "style")
        self.assertEqual(opened["dialog"]["colorRows"], 28 + 1, "стиль платформы и элемент стиля конфигурации из styles")
        found = page(server, ["tree:Склад", "choose:backColor", "find:подсказ"])
        self.assertEqual(found["dialog"]["colorRows"], 2)
        # Цвет стиля платформы - именем, значение «Такси» - в styles (как у импорта)
        result = page(server, ["tree:Склад", "choose:backColor", "color:style:ToolTipBackColor", "ok"])
        self.assertEqual(find(result["model"]["form"], "Склад")["backColor"], "style:ToolTipBackColor")
        self.assertEqual(result["model"]["styles"], {"ГиперссылкаЦвет": "#1C55AE", "ToolTipBackColor": "#FFFAD9"})
        self.assertEqual([issue for issue in result["issues"] if issue["code"] == "style-color"], [])
        own = page(server, ["tree:Склад", "choose:backColor", "color:style:ГиперссылкаЦвет", "ok"])
        self.assertEqual(find(own["model"]["form"], "Склад")["backColor"], "style:ГиперссылкаЦвет")
        web = page(server, ["tree:Склад", "choose:backColor", "tab:web", "color:gainsboro", "ok"])
        self.assertEqual(find(web["model"]["form"], "Склад")["backColor"], "gainsboro")
        self.assertEqual(page(server, ["tree:Склад", "choose:backColor", "tab:web"])["dialog"]["colorRows"], 146)
        rgb = page(server, ["tree:Склад", "choose:backColor", "rgb:1c55ae", "ok"])
        self.assertEqual(find(rgb["model"]["form"], "Склад")["backColor"], "#1C55AE")
        # Набранное руками имя стиля платформы тоже получает значение
        typed = page(server, ["tree:Склад", "set:backColor=style:AccentColor"])
        self.assertEqual(typed["model"]["styles"]["AccentColor"], "#009646")

    def test_format_constructor(self):
        server = self.serve()
        number = page(server, ["tree:ТоварыЦена", "choose:format", "fmt:ЧДЦ=2", "fmt:ЧГ=0", "sample:-1234.5"])
        self.assertEqual(number["errors"], [])
        self.assertEqual(number["dialog"]["tab"], "number", "закладка по dataType поля")
        self.assertEqual(number["dialog"]["value"], "ЧДЦ = 2; ЧГ = '0'")
        self.assertEqual(number["dialog"]["shown"], "-1234,50")
        applied = page(server, ["tree:ТоварыЦена", "choose:format", "fmt:ЧДЦ=2", "fmt:ЧВН", "fmtoff:ЧВН", "ok"])
        self.assertEqual(find(applied["model"]["form"], "ТоварыЦена")["format"], "ЧДЦ = 2")
        date = page(server, ["tree:ДатаОтгрузки", "choose:format", "fmt:ДЛФ=DD", "sample:2026-11-03T09:05:07"])
        self.assertEqual(date["dialog"]["tab"], "date")
        # Перед «г.» - неразрывный пробел, как у `Формат()` 1С (таблица снята с 1С)
        self.assertEqual(date["dialog"]["shown"], "3 ноября 2026 г.")
        # Закладки - только по типу поля: у даты нет числа и булева
        self.assertEqual(date["dialog"]["tabs"], ["date"])
        self.assertEqual(page(server, ["tree:ТоварыЦена", "choose:format"])["dialog"]["tabs"], ["number"])
        # Формат флажка - только у тумблера, закладка булева: надписи положений на макете
        plain = page(server, ["tree:Предоплата"])
        self.assertNotIn("format", [item["prop"] for item in plain["props"]])
        boolean = page(server, ["tree:Предоплата", "set:checkBoxType=Tumbler", "choose:format", "fmt:БЛ=Выкл",
                                "fmt:БИ=Вкл", "ok"])
        self.assertEqual(boolean["errors"], [])
        self.assertEqual(find(boolean["model"]["form"], "Предоплата")["format"], "БЛ = 'Выкл'; БИ = 'Вкл'")
        self.assertIn("Вкл", boolean["selectedText"])
        # Записанный формат разбирается; пустой ЧН и неизвестный конструктору параметр не теряются
        def formatted(model):
            find(model["form"], "ТоварыЦена")["format"] = "ЧДЦ=2; ЧН=; Л=en"
        reopened = page(self.serve(formatted), ["tree:ТоварыЦена", "choose:format", "sample:0"])
        self.assertEqual(reopened["dialog"]["value"], "ЧДЦ = 2; ЧН = ; Л = 'en'")
        self.assertEqual(reopened["dialog"]["shown"], "0,00")
        cleared = page(server, ["tree:ТоварыЦена", "set:format=ЧДЦ=2", "choose:format", "fmtoff:ЧДЦ", "ok"])
        self.assertNotIn("format", find(cleared["model"]["form"], "ТоварыЦена"))

    def test_command_chooser(self):
        server = self.serve()
        opened = page(server, ["tree:ПечатьСчет", "choose:commandName"])
        self.assertEqual(opened["errors"], [])
        values = opened["dialog"]["values"]
        self.assertIn("Form.StandardCommand.Write", values)
        self.assertIn("Form.Item.Товары.StandardCommand.Add", values)
        self.assertEqual(opened["dialog"]["value"], find(json.loads(EXAMPLE.read_text(encoding="utf-8"))["form"],
                                                         "ПечатьСчет").get("commandName", ""))
        chosen = page(server, ["tree:ПечатьСчет", "choose:commandName", "pick-value:Form.StandardCommand.Write", "ok"])
        self.assertEqual(find(chosen["model"]["form"], "ПечатьСчет")["commandName"], "Form.StandardCommand.Write")
        added = page(server, ["tree:ПечатьСчет", "choose:commandName", "new-command:ПечатьАкта"])
        self.assertEqual(find(added["model"]["form"], "ПечатьСчет")["commandName"], "Form.Command.ПечатьАкта")
        self.assertEqual(added["model"]["commands"], [{"name": "ПечатьАкта"}], "новая команда - в команды формы")
        # Группы сворачиваются: у кнопки панели формы таблицы свернуты, у кнопки таблицы - своя раскрыта
        groups = {group["section"]: group["open"] for group in opened["dialog"]["groups"]}
        self.assertTrue(groups["form"])
        self.assertFalse(groups["table:Товары"])
        inner = page(server, ["tree:ТоварыПодобрать", "choose:commandName"])
        self.assertTrue({group["section"]: group["open"] for group in inner["dialog"]["groups"]}["table:Товары"])
        toggled = page(server, ["tree:ПечатьСчет", "choose:commandName", "section:table:Товары"])
        self.assertTrue({group["section"]: group["open"] for group in toggled["dialog"]["groups"]}["table:Товары"])
        # Лишних нет: снятые в «Составе команд» и запрещенные флагами таблицы не предлагаются
        limited = page(server, ["tree:Товары", "set:changeRowOrder=false", "choose:excludedCommands", "command:Add=false",
                                "ok", "tree:ПечатьСчет", "choose:commandName"])
        values = limited["dialog"]["values"]
        self.assertNotIn("Form.Item.Товары.StandardCommand.Add", values)
        self.assertNotIn("Form.Item.Товары.StandardCommand.MoveUp", values)
        self.assertIn("Form.Item.Товары.StandardCommand.Copy", values)

    def test_form_commands_and_fold_all(self):
        server = self.serve()
        result = page(server, ["tree:Форма", "choose:excludedCommands", "command:Write=false", "ok"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["model"]["form"]["excludedCommands"], ["Write"])
        self.assertNotIn("Записать", result["selectedText"].replace("Записать и закрыть", ""),
                         "снятая команда формы ушла с панели")
        folded = page(server, ["tree:Склад", "fold:all"])
        self.assertEqual(folded["foldedGroups"], folded["groups"], "все группы свернуты")
        unfolded = page(server, ["tree:Склад", "fold:all", "fold:none"])
        self.assertEqual(unfolded["foldedGroups"], [])

    def test_date_fractions_by_type(self):
        """Состав даты - у реквизита с типом «Дата»; поле с путем к нему получает его при правке реквизита."""
        server = self.serve()
        date = page(server, ["left:attributes", "attr-add", "set:valueType=Дата"])
        self.assertIn("dateFractions", [item["prop"] for item in date["props"]])
        self.assertEqual(date["model"]["attributes"][-1]["valueType"], "Date", "русское имя типа - в английское")
        time = page(server, ["left:attributes", "attr-add", "set:valueType=Date", "left:items", "tree:Комментарий",
                             "set:dataPath=Реквизит1", "left:attributes", "attr-pick:Реквизит1", "set:dateFractions=Time"])
        self.assertEqual(time["errors"], [])
        field = find(time["model"]["form"], "Комментарий")
        self.assertEqual((field["dataType"], field["dateFractions"]), ("date", "Time"))
        back = page(server, ["left:attributes", "attr-add", "set:valueType=Date", "set:dateFractions=Time",
                             "set:valueType=String"])
        self.assertNotIn("dateFractions", back["model"]["attributes"][-1], "квалификатор чужого типа убран")

    def test_choice_list(self):
        def with_enum(model):
            find(model["form"], "Склад")["enumValues"] = ["Основной", "Розница"]
            find(model["form"], "Склад")["choiceList"] = ["Розница"]
        server = self.serve(with_enum)
        result = page(server, ["tree:Комментарий", "choose:choiceList", "list:add=Первый", "list:add=Второй", "list:up", "ok"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Комментарий")["choiceList"], ["Второй", "Первый"])
        self.assertTrue(page(server, ["tree:Комментарий", "choose:choiceList"])["dialog"]["fillDisabled"])
        filled = page(server, ["tree:Склад", "choose:choiceList", "list:fill", "row:0", "list:down", "ok"])
        self.assertEqual(find(filled["model"]["form"], "Склад")["choiceList"], ["Основной", "Розница"])
        emptied = page(server, ["tree:Склад", "choose:choiceList", "list:delete", "ok"])
        self.assertNotIn("choiceList", find(emptied["model"]["form"], "Склад"), "пустой список - свойство убирается")
        # Две колонки: представление пишется парой, совпавшее со значением - не пишется
        pairs = page(server, ["tree:Комментарий", "choose:choiceList", "list:add=1|Один", "list:add=2|2", "ok"])
        self.assertEqual(pairs["errors"], [])
        self.assertEqual(find(pairs["model"]["form"], "Комментарий")["choiceList"], [{"value": "1", "presentation": "Один"}, "2"])

    def test_picture_library(self):
        server = self.serve()
        opened = page(server, ["tree:ПодменюПечать", "choose:picture", "picture:StdPicture.Print"])
        self.assertEqual(opened["errors"], [])
        self.assertEqual(opened["dialog"]["value"], "StdPicture.Print")
        self.assertGreater(opened["dialog"]["tiles"], 250, "библиотека стандартных картинок")
        found = page(server, ["tree:ПодменюПечать", "choose:picture", "find:провести"])
        self.assertTrue(0 < found["dialog"]["tiles"] < 10, "поиск по русскому имени")
        result = page(server, ["tree:ПодменюПечать", "choose:picture", "picture:StdPicture.Post", "ok"])
        self.assertEqual(find(result["model"]["form"], "ПодменюПечать")["picture"], "StdPicture.Post")
        self.assertTrue(result["model"]["pictures"]["StdPicture.Post"].startswith("data:image/"),
                        "стандартная картинка из библиотеки - в pictures, как у импорта")
        self.assertEqual(list(result["model"])[-1], "pictures")


@unittest.skipUnless(CHROME, "Chrome не найден")
class AttributesPanelTest(unittest.TestCase):
    """Реквизиты формы в левой колонке: дерево, правка в панели свойств, переименование с путями."""

    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def test_tree_and_read_only_members(self):
        result = page(self.server, ["left:attributes", "attr-pick:Объект.Контрагент"])
        self.assertEqual(result["errors"], [])
        rows = {row["path"]: row["readOnly"] for row in result["attrRows"]}
        self.assertFalse(rows["Объект"], "реквизит формы правится")
        self.assertTrue(rows["Объект.Контрагент"], "состав типа - только просмотр")
        self.assertEqual(result["props"], [], "у состава типа нет полей правки")
        back = page(self.server, ["left:attributes", "click:Контрагент"])
        self.assertEqual(back["leftMode"], "items", "щелчок по макету возвращает к элементам")

    def test_usage_icon_stays_right_in_narrow_column(self):
        """Узкая левая колонка: значок «есть на форме» у правого края строки на одном месте, место отдает
        имя (многоточие, не уже 4 символов), строка за колонку не вылезает - на закладках «Реквизиты» и «Команды»."""
        cases = {
            "attrFit": ["left:attributes", "attr-pick:Объект.Контрагент", "left-width:160"],
            "cmdFit": ["left:commands", "left-width:160"],
        }
        for key, actions in cases.items():
            result = page(self.server, actions)
            self.assertEqual(result["errors"], [], key)
            rows = [row for row in result[key] if row["usageGap"] is not None]
            self.assertTrue(rows, key)
            self.assertEqual({row["usageGap"] for row in rows}, {6}, (key, rows))
            self.assertEqual([row for row in result[key] if row["overflow"]], [], key)
            self.assertTrue(any(row["labelClipped"] for row in rows), (key, rows))
            self.assertTrue(all(row["labelWidth"] >= 20 for row in rows), (key, rows))

    def test_add_edit_delete(self):
        result = page(self.server, ["left:attributes", "attr-add", "set:name=Примечание", "set:valueType=Number",
                                    "set:digits=10", "set:fractionDigits=2"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["model"]["attributes"][-1],
                         {"name": "Примечание", "valueType": "Number", "digits": 10, "fractionDigits": 2})
        props = [item["prop"] for item in result["props"]]
        self.assertIn("digits", props)
        self.assertNotIn("length", props, "квалификаторы - по типу")
        duplicate = page(self.server, ["left:attributes", "attr-add", "set:name=Объект"])
        self.assertIn("name", duplicate["invalid"])
        table = page(self.server, ["left:attributes", "attr-add", "set:valueType=ValueTable", "attr-add:column",
                                   "set:name=Сумма"])
        self.assertEqual(table["model"]["attributes"][-1]["columns"], [{"name": "Сумма", "valueType": "String"}])
        deleted = page(self.server, ["left:attributes", "attr-add", "attr-delete"])
        self.assertEqual([item["name"] for item in deleted["model"]["attributes"]], ["Объект"])

    def test_context_menu(self):
        """Контекстное меню и клавиши закладки (владелец): без похода к кнопкам над деревом."""
        menu = page(self.server, ["left:attributes", "ctx-attr:Объект"])
        self.assertEqual(menu["errors"], [])
        self.assertEqual(menu["attrSelected"], "@attr:Объект", "правая кнопка выбирает строку")
        self.assertEqual(menu["palette"]["actions"], ["add-attr", "add-column-", "delete"])
        self.assertIsNone(menu["palette"]["focused"], "мышью - без фокуса на пункте")
        added = page(self.server, ["left:attributes", "ctx-attr:Объект", "menu:add-attr"])
        self.assertEqual(added["model"]["attributes"][-1], {"name": "Реквизит1", "valueType": "String"})
        self.assertEqual(added["focused"], "name", "после добавления - фокус на имени")
        self.assertIsNone(added["palette"], "после действия меню закрыто")
        empty = page(self.server, ["left:attributes", "attr-pick:Объект", "ctx-attr:*"])
        self.assertIsNone(empty["attrSelected"], "пустое место снимает выбор")
        self.assertEqual(empty["palette"]["actions"], ["add-attr", "add-column-", "delete-"])
        column = page(self.server, ["left:attributes", "attr-add", "set:valueType=ValueTable", "attr-add:column",
                                    "ctx-attr:Реквизит1.Колонка1", "menu:add-column"])
        self.assertEqual([item["name"] for item in column["model"]["attributes"][-1]["columns"]],
                         ["Колонка1", "Колонка2"], "у колонки «Добавить колонку» - в ее таблицу")
        extra = page(self.server, ["left:attributes", "attr-pick:Объект.Товары.Цена", "ctx-attr:Объект.Товары.Цена",
                                   "menu:add-column"])
        self.assertEqual(extra["model"]["attributes"][0]["additionalColumns"],
                         {"Товары": [{"name": "Колонка1", "valueType": "String"}]}, "у колонки табличной части - колонка формы")
        keyboard = page(self.server, ["left:attributes", "attr-pick:Объект", "key:Insert"])
        self.assertEqual(keyboard["palette"]["focused"], "add-attr", "Insert - меню с фокусом на первом пункте")
        shift = page(self.server, ["left:attributes", "attr-pick:Объект", "key:Shift+F10"])
        self.assertEqual(shift["palette"]["focused"], "add-attr")
        removed = page(self.server, ["left:attributes", "attr-add", "key:Delete"])
        self.assertEqual([item["name"] for item in removed["model"]["attributes"]], ["Объект"], "Del удаляет реквизит")
        kept = page(self.server, ["left:attributes", "attr-pick:Объект.Товары", "key:Delete"])
        self.assertEqual(kept["undo"], 0, "состав типа клавишей не удаляется")

    def test_type_chooser(self):
        """Тип реквизита - окном выбора и русскими именами (владелец)."""
        opened = page(self.server, ["left:attributes", "attr-add", "choose:valueType"])
        self.assertEqual(opened["errors"], [])
        self.assertEqual(opened["dialog"]["kind"], "type")
        self.assertIn("Catalog", "".join(opened["dialog"]["values"]))
        self.assertIn("CatalogRef.Контрагенты", opened["dialog"]["values"], "объекты - из types модели")
        single = page(self.server, ["left:attributes", "attr-add", "choose:valueType", "pick-value:Number", "ok"])
        self.assertEqual(single["model"]["attributes"][-1]["valueType"], "Number")
        self.assertEqual({item["prop"]: item.get("value") for item in single["props"]}["valueType"], "Число")
        composite = page(self.server, ["left:attributes", "attr-add", "choose:valueType", "composite:on",
                                       "section:ref:Catalog", "pick-value:CatalogRef.Контрагенты", "ok"])
        self.assertEqual(composite["model"]["attributes"][-1]["valueType"], ["String", "CatalogRef.Контрагенты"])
        typed = page(self.server, ["left:attributes", "attr-add", "set:valueType=СправочникСсылка.Контрагенты, Строка"])
        self.assertEqual(typed["model"]["attributes"][-1]["valueType"], ["CatalogRef.Контрагенты", "String"])
        # Состав - по окну «Редактирование типа данных» конфигуратора (снимок владельца 04.11.2026)
        values = opened["dialog"]["values"]
        for name in ("", "UUID", "FormattedString", "PDFDocument", "Null", "CatalogRef", "BusinessProcessRoutePointRef",
                     "AnyRef", "ConstantsSet", "DataCompositionSettingsComposer", "Planner", "StandardBeginningDate",
                     "AccountType", "DataAnalysisSequentialPatternsOrderType"):
            self.assertIn(name, values)
        self.assertLess(values.index("Number"), values.index("String"), "порядок окна 1С: Число, Строка")
        generic = page(self.server, ["left:attributes", "attr-add", "set:valueType=СправочникСсылка"])
        self.assertEqual(generic["model"]["attributes"][-1]["valueType"], "CatalogRef", "любая ссылка справочника")
        anything = page(self.server, ["left:attributes", "attr-add", "choose:valueType", "pick-value:", "ok"])
        self.assertNotIn("valueType", anything["model"]["attributes"][-1], "«Произвольный» - тип не задан")

    def test_extra_columns_of_object_table(self):
        """Своя колонка табличной части объекта - в `additionalColumns`, без правки метаданных (владелец 04.11.2026)."""
        result = page(self.server, ["left:attributes", "attr-pick:Объект.Товары", "attr-add:column", "set:name=Отметка",
                                    "set:valueType=Boolean"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["model"]["attributes"][0]["additionalColumns"],
                         {"Товары": [{"name": "Отметка", "valueType": "Boolean"}]})
        rows = {row["path"]: row["readOnly"] for row in result["attrRows"]}
        self.assertFalse(rows["Объект.Товары.Отметка"], "своя колонка правится")
        self.assertTrue(rows["Объект.Товары.Цена"], "колонка из метаданных - нет")
        clash = page(self.server, ["left:attributes", "attr-pick:Объект.Товары", "attr-add:column", "set:name=Цена"])
        self.assertIn("name", clash["invalid"], "имя колонки из метаданных занято")
        deleted = page(self.server, ["left:attributes", "attr-pick:Объект.Товары", "attr-add:column", "attr-delete"])
        self.assertNotIn("additionalColumns", deleted["model"]["attributes"][0])

    def test_usage_link(self):
        """Значок «есть на форме» у реквизита и команды: щелчок выбирает элемент."""
        result = page(self.server, ["left:attributes", "attr-pick:Объект.Контрагент"])
        rows = {row["path"]: row["element"] for row in result["attrRows"]}
        self.assertEqual(rows["Объект.Контрагент"], "Контрагент")
        self.assertIsNone(rows["Объект"], "реквизита самого по себе на форме нет")
        jumped = page(self.server, ["left:attributes", "attr-pick:Объект.Контрагент", "usage:@attr:Объект.Контрагент"])
        self.assertEqual((jumped["leftMode"], jumped["selected"]), ("attributes", "Контрагент"),
                         "колонка остается на реквизитах (владелец 04.11)")
        self.assertEqual(jumped["attrSelected"], "@attr:Объект.Контрагент", "строка значка выбрана")
        self.assertEqual(jumped["propsTitle"], "Свойства: Реквизит")
        self.assertTrue(jumped["frame"], "элемент выделен на макете")
        command = page(self.server, ["left:commands", "usage:@cmd:ПечатьСчет"])
        self.assertEqual((command["leftMode"], command["selected"], command["cmdSelected"]),
                         ("commands", "ПечатьСчет", "@cmd:ПечатьСчет"))
        # Кнопка в подменю «Печать» на макете не видна - рамки нет, как и при выборе из дерева элементов

    def test_keys_in_attribute_tree(self):
        result = page(self.server, ["left:attributes", "key:ArrowDown", "key:ArrowRight", "key:ArrowRight"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["attrSelected"], "@attr:Объект.Number", "вправо - раскрыть, еще вправо - к подчиненному")
        back = page(self.server, ["left:attributes", "key:ArrowDown", "key:ArrowRight", "key:ArrowRight", "key:ArrowLeft",
                                  "key:ArrowLeft"])
        self.assertEqual(back["attrSelected"], "@attr:Объект")
        self.assertEqual([row["path"] for row in back["attrRows"]], ["Объект"], "влево на родителе - свернуть")

    def test_rename_rewrites_paths(self):
        result = page(self.server, ["left:attributes", "attr-pick:Объект", "set:name=Документ"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Контрагент")["dataPath"], "Документ.Контрагент")
        self.assertEqual(find(result["model"]["form"], "Товары")["dataPath"], "Документ.Товары")
        self.assertEqual([issue for issue in result["issues"] if issue["code"] == "data-path"], [])


@unittest.skipUnless(CHROME, "Chrome не найден")
class CommandsPanelTest(unittest.TestCase):
    """Команды формы в левой колонке: список, правка, переименование с кнопками."""

    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def test_virtual_commands_and_rename(self):
        result = page(self.server, ["left:commands", "cmd-pick:ПечатьСчет", "set:title=Счет"])
        self.assertEqual(result["errors"], [])
        self.assertIn({"name": "ПечатьЗаказ", "virtual": True, "element": "ПечатьЗаказ"}, result["cmdRows"],
                      "команда кнопки без описания - бледной, со значком «на форме»")
        self.assertEqual(result["model"]["commands"], [{"name": "ПечатьСчет", "title": "Счет"}], "первая правка заводит команду")
        self.assertEqual(list(result["model"])[:4], ["version", "form", "attributes", "commands"])
        renamed = page(self.server, ["left:commands", "cmd-pick:ПечатьСчет", "set:name=ПечатьСчетаНаОплату"])
        self.assertEqual(find(renamed["model"]["form"], "ПечатьСчет")["commandName"], "Form.Command.ПечатьСчетаНаОплату")
        duplicate = page(self.server, ["left:commands", "cmd-pick:ПечатьСчет", "set:name=ПечатьЗаказ"])
        self.assertIn("name", duplicate["invalid"])

    def test_button_check_property_and_press(self):
        """Пометка кнопки: свойство в панели, нажатая кнопка «вдавлена»; щелчок на макете нажимает и отжимает
        ее, модель не меняется; обычная кнопка от щелчка не нажимается."""
        name = "ТоварыПодобрать"
        plain = page(self.server, [f"click:{name}"])
        self.assertEqual(plain["checkedButtons"], [], "кнопка без пометки не нажимается")
        checked = page(self.server, [f"tree:{name}", "set:check=true"])
        self.assertEqual(checked["errors"], [])
        self.assertIn("check", [item["prop"] for item in checked["props"]])
        self.assertIs(find(checked["model"]["form"], name)["check"], True)
        self.assertIn(name, checked["checkedButtons"])
        released = page(self.server, [f"tree:{name}", "set:check=true", f"click:{name}"])
        self.assertNotIn(name, released["checkedButtons"], "щелчок отжимает")
        self.assertIs(find(released["model"]["form"], name)["check"], True, "модель не меняется")
        again = page(self.server, [f"tree:{name}", "set:check=true", f"click:{name}", f"click:{name}"])
        self.assertIn(name, again["checkedButtons"], "повторный щелчок нажимает")
        unchecked = page(self.server, [f"tree:{name}", "set:check=false", f"click:{name}"])
        self.assertIs(find(unchecked["model"]["form"], name)["check"], False, "явная Ложь - кнопка с пометкой")
        self.assertIn(name, unchecked["checkedButtons"], "кнопка с пометкой Ложь нажимается щелчком")

    def test_add_delete(self):
        added = page(self.server, ["left:commands", "cmd-add", "set:name=Заполнить", "set:action=ЗаполнитьОбработка"])
        self.assertEqual(added["errors"], [])
        self.assertEqual(added["model"]["commands"], [{"name": "Заполнить", "action": "ЗаполнитьОбработка"}])
        deleted = page(self.server, ["left:commands", "cmd-add", "cmd-delete"])
        self.assertNotIn("commands", deleted["model"], "пустой список команд убирается")

    def test_context_menu(self):
        """Контекстное меню и клавиши закладки (владелец)."""
        empty = page(self.server, ["left:commands", "ctx-cmd:*"])
        self.assertEqual(empty["errors"], [])
        self.assertEqual(empty["palette"]["actions"], ["add-command", "delete-"])
        added = page(self.server, ["left:commands", "ctx-cmd:*", "menu:add-command"])
        self.assertEqual(added["model"]["commands"], [{"name": "Команда1"}])
        virtual = page(self.server, ["left:commands", "ctx-cmd:ПечатьЗаказ"])
        self.assertEqual(virtual["cmdSelected"], "@cmd:ПечатьЗаказ")
        self.assertEqual(virtual["palette"]["actions"], ["add-command", "delete-"], "команду без описания не удалить")
        deleted = page(self.server, ["left:commands", "cmd-add", "ctx-cmd:Команда1", "menu:delete"])
        self.assertNotIn("commands", deleted["model"])
        keyed = page(self.server, ["left:commands", "cmd-add", "key:Delete"])
        self.assertNotIn("commands", keyed["model"], "Del удаляет команду")
        insert = page(self.server, ["left:commands", "key:Insert"])
        self.assertEqual(insert["palette"]["focused"], "add-command")

    def test_keys(self):
        result = page(self.server, ["left:commands", "key:ArrowDown", "key:ArrowDown"])
        self.assertEqual(result["cmdSelected"], "@cmd:" + result["cmdRows"][1]["name"])


@unittest.skipUnless(CHROME, "Chrome не найден")
class TableColumnsTest(unittest.TestCase):
    """Смена пути к данным таблицы: колонки прежнего пути удаляются, новые - заполнением."""

    def setUp(self):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        model["attributes"].append({"name": "Подбор", "valueType": "ValueTable", "columns": [
            {"name": "Номенклатура", "valueType": "CatalogRef.Номенклатура"},
            {"name": "Отметка", "valueType": "Boolean"}]})
        source = Path(temp_dir(prefix="formmockup-columns-")) / "model.json"
        source.write_text(dump(model), encoding="utf-8")
        self.server = Server(source)

    def tearDown(self):
        self.server.close()

    def test_fill_and_leave_empty(self):
        offered = page(self.server, ["tree:Товары", "set:dataPath=Подбор"])
        self.assertEqual(offered["errors"], [])
        self.assertEqual(offered["dialog"]["kind"], "columns")
        table = find(offered["model"]["form"], "Товары")
        self.assertNotIn("items", table, "колонки прежнего пути удалены")
        self.assertNotIn("sample", table)
        filled = page(self.server, ["tree:Товары", "set:dataPath=Подбор", "ok"])
        columns = find(filled["model"]["form"], "Товары")["items"]
        self.assertEqual([(column["type"], column["name"], column["dataPath"]) for column in columns],
                         [("InputField", "ТоварыНоменклатура", "Подбор.Номенклатура"),
                          ("CheckBoxField", "ТоварыОтметка", "Подбор.Отметка")])
        self.assertEqual(columns[0]["dataType"], "ref")
        self.assertEqual([column["title"] for column in columns], ["Номенклатура", "Отметка"], "заголовок реквизита")
        empty = page(self.server, ["tree:Товары", "set:dataPath=Подбор", "cancel"])
        self.assertNotIn("items", find(empty["model"]["form"], "Товары"))
        self.assertIsNone(empty["dialog"])


@unittest.skipUnless(CHROME, "Chrome не найден")
class FieldKindTest(unittest.TestCase):
    """«Вид» поля (ВидПоляФормы, владелец 04.11.2026): список по типу реквизита и месту, смена вида."""

    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def kind(self, result):
        return next(prop for prop in result["props"] if prop["prop"] == "type")

    def test_list_by_type_and_place(self):
        flag = page(self.server, ["tree:Предоплата"])
        self.assertEqual(flag["errors"], [])
        names = [prop["prop"] for prop in flag["props"]]
        self.assertEqual(names[:4], ["name", "title", "type", "dataPath"], "Вид - над ПутьКДанным")
        self.assertEqual(self.kind(flag)["titles"], ["Поле ввода", "Поле надписи", "Поле флажка", "Поле картинки"],
                         "булево - снимок владельца")
        self.assertEqual(self.kind(flag)["value"], "CheckBoxField")
        self.assertNotIn("type", flag["resets"], "у вида нет «по умолчанию»")
        text = page(self.server, ["tree:Комментарий"])
        self.assertEqual(self.kind(text)["options"], ["InputField", "LabelField", "RadioButtonField", "PictureField",
                                                      "HTMLDocumentField", "TextDocumentField"], "строка - снимок владельца")
        column = page(self.server, ["tree:ТоварыКоличество"])
        self.assertEqual(self.kind(column)["options"], ["InputField", "LabelField", "CheckBoxField", "PictureField"],
                         "число в таблице - без переключателя, индикатора и полосы регулирования")
        # Снимки владельца 04.11.2026: ссылка - ввод и надпись, дата - ввод, надпись, календарь
        self.assertEqual(self.kind(page(self.server, ["tree:Контрагент"]))["options"], ["InputField", "LabelField"])
        self.assertEqual(self.kind(page(self.server, ["tree:ДатаОтгрузки"]))["options"],
                         ["InputField", "LabelField", "CalendarField"])

    def test_object_not_a_field(self):
        """У объекта вида поля нет: в окне пути поля он не выбирается (владелец 04.11.2026)."""
        result = page(self.server, ["tree:Комментарий", "choose:dataPath"])
        rows = {row["path"]: row["off"] for row in result["dialog"]["rows"]}
        self.assertTrue(rows["Объект"], "ДокументОбъект - не поле")
        self.assertFalse(rows["Объект.Комментарий"])

    def test_change_kind(self):
        label = page(self.server, ["tree:Контрагент", "set:type=LabelField"])
        self.assertEqual(label["errors"], [])
        node = find(label["model"]["form"], "Контрагент")
        self.assertEqual(node["type"], "LabelField")
        for prop in ("choiceButton", "openButton", "markIncomplete", "dataType"):
            self.assertNotIn(prop, node, "свойства поля ввода ушли")
        self.assertEqual((node["dataPath"], node["sample"]), ("Объект.Контрагент", "ООО Ромашка"))
        self.assertEqual(label["propsTitle"], "Свойства: Поле надписи")
        self.assertEqual(label["selected"], "Контрагент", "выбор остался на элементе")
        back = page(self.server, ["tree:Контрагент", "set:type=LabelField", "set:type=InputField"])
        self.assertEqual(find(back["model"]["form"], "Контрагент")["dataType"], "ref", "тип - снова из реквизита")
        # Через флажок: пример булево и надписи тумблера уходят, тип поля ввода - из реквизита
        flag = page(self.server, ["tree:Предоплата", "set:type=InputField"])
        node = find(flag["model"]["form"], "Предоплата")
        self.assertEqual((node["type"], node["dataType"], node["title"]), ("InputField", "boolean", "Требуется предоплата"))
        self.assertNotIn("sample", node)


@unittest.skipUnless(CHROME, "Chrome не найден")
class KindPropsTest(unittest.TestCase):
    """Свойства вида при смене вида и «авто» максимума."""

    setUp = ValueChooserTest.setUp
    tearDown = ValueChooserTest.tearDown
    serve = ValueChooserTest.serve

    def test_change_kind_resets_kind_props(self):
        """Смена вида, как в конфигураторе (владелец 04.11.2026): свойства вида (ширина, высота, растягивание, рамка,
        картинка значений) сбрасываются, свойства самого элемента (заголовок, путь, положение) остаются."""
        def picture(model):
            field = find(model["form"], "Предоплата")
            field.clear()
            field.update({"type": "PictureField", "name": "Предоплата", "title": "Подписан", "dataPath": "Объект.Предоплата",
                          "titleLocation": "Right", "groupVerticalAlign": "Center", "width": 3, "height": 1,
                          "horizontalStretch": False, "valuesPicture": "StdPicture.Print", "border": "Double"})
        result = page(self.serve(picture), ["tree:Предоплата", "set:type=CheckBoxField"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Предоплата"), {
            "type": "CheckBoxField", "name": "Предоплата", "title": "Подписан", "dataPath": "Объект.Предоплата",
            "titleLocation": "Right", "groupVerticalAlign": "Center"})

    def test_auto_max_resets_max(self):
        """Включенное «авто» сбрасывает максимум, как в конфигураторе: у поля ввода - ширина, у поля картинки - оба."""
        def limited(model):
            find(model["form"], "Комментарий").update({"autoMaxWidth": False, "maxWidth": 30})
            field = find(model["form"], "Предоплата")
            field.clear()
            field.update({"type": "PictureField", "name": "Предоплата", "autoMaxWidth": False, "maxWidth": 5,
                          "autoMaxHeight": False, "maxHeight": 4})
        server = self.serve(limited)
        for name, actions in (("Комментарий", ["set:autoMaxWidth=true"]),
                              ("Предоплата", ["set:autoMaxWidth=true", "set:autoMaxHeight=true"])):
            result = page(server, ["tree:" + name] + actions)
            self.assertEqual(result["errors"], [], name)
            node = find(result["model"]["form"], name)
            self.assertFalse({"maxWidth", "maxHeight"} & set(node), name)
            props = [entry["prop"] for entry in result["props"]]
            self.assertFalse({"maxWidth", "maxHeight"} & set(props), "поле максимума пропало из панели")

    def test_multiline_max_height(self):
        """Предел высоты - у многострочного поля ввода: «Автомаксимальная высота» в панели, снятая -
        «Максимальная высота»; у однострочного поля обоих нет."""
        server = self.serve()
        single = page(server, ["tree:Контрагент"])
        self.assertFalse({"autoMaxHeight", "maxHeight"} & {entry["prop"] for entry in single["props"]})
        result = page(server, ["tree:Комментарий"])
        props = {entry["prop"]: entry for entry in result["props"]}
        self.assertIn("autoMaxHeight", props)
        self.assertNotIn("maxHeight", props)
        result = page(server, ["tree:Комментарий", "set:autoMaxHeight=false", "set:maxHeight=6", "set:verticalStretch=true"])
        self.assertEqual(result["errors"], [])
        node = find(result["model"]["form"], "Комментарий")
        self.assertEqual((node.get("autoMaxHeight"), node.get("maxHeight"), node.get("verticalStretch")), (False, 6, True))


@unittest.skipUnless(CHROME, "Chrome не найден")
class ButtonTitleTest(unittest.TestCase):
    """Заголовок кнопки от команды (владелец 04.11.2026), как заголовок поля от пути к данным."""

    setUp = ValueChooserTest.setUp
    tearDown = ValueChooserTest.tearDown
    serve = ValueChooserTest.serve

    def test_title_follows_command(self):
        def commands(model):
            model["commands"] = [{"name": "ПечатьСчет", "title": "Счет на оплату"}]
        server = self.serve(commands)
        # Заголовок, равный заголовку прежней команды, - унаследованный: уходит, кнопка берет заголовок новой
        moved = page(server, ["tree:ПечатьСчет", "set:commandName=Form.StandardCommand.Close"])
        self.assertEqual(moved["errors"], [])
        self.assertNotIn("title", find(moved["model"]["form"], "ПечатьСчет"))
        title = next(entry for entry in moved["props"] if entry["prop"] == "title")
        self.assertEqual(title["placeholder"], "Закрыть")
        # Свой заголовок остается («Подбор» - не заголовок команды «Подобрать товары»)
        kept = page(server, ["tree:ТоварыПодобрать", "set:commandName=Form.Item.Товары.StandardCommand.Add"])
        self.assertEqual(find(kept["model"]["form"], "ТоварыПодобрать")["title"], "Подбор")
        # Очищенный заголовок - от команды, а не от имени
        cleared = page(server, ["tree:ТоварыПодобрать", "set:commandName=Form.Item.Товары.StandardCommand.Add",
                                "set:title="])
        title = next(entry for entry in cleared["props"] if entry["prop"] == "title")
        self.assertEqual(title["placeholder"], "Добавить")


@unittest.skipUnless(CHROME, "Chrome не найден")
class KindResetTest(unittest.TestCase):
    """Вид, которого у типа нового реквизита нет, сбрасывается на вид по умолчанию (владелец 04.11.2026)."""

    def setUp(self):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        model["attributes"].append({"name": "Схема", "valueType": "GraphicalSchema"})
        model["form"]["items"].append({"type": "InputField", "name": "ПолеСхемы", "dataPath": "Схема"})
        source = Path(temp_dir(prefix="formmockup-kind-")) / "model.json"
        source.write_text(dump(model), encoding="utf-8")
        self.server = Server(source)

    def tearDown(self):
        self.server.close()

    def kind(self, result):
        return next(prop for prop in result["props"] if prop["prop"] == "type")

    def test_owner_case_path_to_date(self):
        steps = ["tree:ПолеСхемы", "set:type=GraphicalSchemaField"]
        schema = page(self.server, steps)
        self.assertEqual(find(schema["model"]["form"], "ПолеСхемы")["type"], "GraphicalSchemaField")
        dated = page(self.server, steps + ["set:dataPath=Объект.Date"])
        self.assertEqual(dated["errors"], [])
        node = find(dated["model"]["form"], "ПолеСхемы")
        self.assertEqual((node["type"], node["dataType"]), ("InputField", "date"), "сброс на поле ввода")
        self.assertEqual(self.kind(dated)["options"], ["InputField", "LabelField", "CalendarField"],
                         "поля графической схемы в списке больше нет")
        flag = page(self.server, steps + ["set:dataPath=Объект.Предоплата"])
        self.assertEqual(find(flag["model"]["form"], "ПолеСхемы")["type"], "CheckBoxField", "булево - флажок")
        kept = page(self.server, ["tree:ДатаОтгрузки", "set:type=LabelField", "set:dataPath=Объект.Date"])
        self.assertEqual(find(kept["model"]["form"], "ДатаОтгрузки")["type"], "LabelField", "подходящий вид остается")

    def test_attribute_type_change(self):
        result = page(self.server, ["tree:ПолеСхемы", "set:type=GraphicalSchemaField", "left:attributes",
                                    "attr-pick:Схема", "set:valueType=Date"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "ПолеСхемы")["type"], "InputField")


@unittest.skipUnless(CHROME, "Chrome не найден")
class PathTitleTest(unittest.TestCase):
    """Заголовок по пути к данным (владелец 04.11.2026): унаследованный - от нового реквизита, свой - остается."""

    def setUp(self):
        self.server = Server(EXAMPLE)

    def tearDown(self):
        self.server.close()

    def test_owner_case_cleared_then_new_path(self):
        # Булево поле с заголовком реквизита: путь очищен, затем выбран другой - заголовок нового реквизита
        steps = ["tree:Предоплата", "set:title=Предоплата", "set:dataPath="]
        cleared = page(self.server, steps)
        self.assertEqual(cleared["errors"], [])
        node = find(cleared["model"]["form"], "Предоплата")
        self.assertNotIn("dataPath", node)
        self.assertNotIn("title", node, "без пути унаследованного заголовка нет")
        chosen = page(self.server, steps + ["choose:dataPath", "pick:Объект.Date", "ok"])
        node = find(chosen["model"]["form"], "Предоплата")
        self.assertEqual((node["name"], node["dataPath"], node["title"]), ("Предоплата", "Объект.Date", "Дата"),
                         "имя остается, заголовок - синоним нового реквизита")
        named = page(self.server, ["tree:Склад", "set:dataPath=Объект.Контрагент"])
        self.assertEqual(find(named["model"]["form"], "Склад")["title"], "Контрагент", "без синонима - имя по словам")

    def test_own_title_kept(self):
        result = page(self.server, ["tree:ДатаОтгрузки", "set:dataPath=Объект.Date"])
        self.assertEqual(find(result["model"]["form"], "ДатаОтгрузки")["title"], "Отгрузка")


@unittest.skipUnless(CHROME, "Chrome не найден")
class RowPictureTest(unittest.TestCase):
    """Путь к данным картинки строки - колонка своей таблицы, путь целиком (владелец 04.11.2026)."""

    def setUp(self):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        model["attributes"].append({"name": "Список", "valueType": "DynamicList"})
        model["form"]["items"].append({"type": "Table", "name": "Список", "dataPath": "Список", "items": [
            {"type": "InputField", "name": "СписокНомер", "dataPath": "Список.Номер"}]})
        model["form"]["items"].append({"type": "Table", "name": "БезПути", "items": [
            {"type": "InputField", "name": "БезПутиКолонка"}]})
        source = Path(temp_dir(prefix="formmockup-rowpicture-")) / "model.json"
        source.write_text(dump(model), encoding="utf-8")
        self.server = Server(source)

    def tearDown(self):
        self.server.close()

    def test_tabular_section(self):
        result = page(self.server, ["tree:Товары", "choose:rowPictureDataPath"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["dialog"]["mode"], "column")
        rows = {row["path"]: row["off"] for row in result["dialog"]["rows"]}
        self.assertNotIn("Объект.Контрагент", rows, "только ветка своей таблицы")
        self.assertTrue(rows["Объект.Товары"], "сама таблица не выбирается")
        self.assertFalse(rows["Объект.Товары.Номенклатура"])
        chosen = page(self.server, ["tree:Товары", "choose:rowPictureDataPath", "pick:Объект.Товары.СтавкаНДС", "ok"])
        table = find(chosen["model"]["form"], "Товары")
        self.assertEqual(table["rowPictureDataPath"], "Объект.Товары.СтавкаНДС")
        self.assertEqual(table["dataPath"], "Объект.Товары", "путь таблицы не тронут")
        self.assertEqual(len(table["items"]), len(find(result["model"]["form"], "Товары")["items"]), "колонки не тронуты")
        self.assertIsNone(chosen["dialog"], "окна заполнения колонок нет")

    def test_dynamic_list_default_picture(self):
        result = page(self.server, ["tree:Список", "choose:rowPictureDataPath", "pick:Список.DefaultPicture", "ok"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Список")["rowPictureDataPath"], "Список.DefaultPicture")
        opened = page(self.server, ["tree:Список", "choose:rowPictureDataPath"])
        self.assertIn("СтандартнаяКартинка", opened["dialog"]["names"])
        # СтандартнаяКартинка - путь картинки строки, колонкой таблицу не заполняет
        moved = page(self.server, ["tree:Товары", "set:dataPath=Список"])
        self.assertIsNone(moved["dialog"])

    def test_table_without_path(self):
        result = page(self.server, ["tree:БезПути", "choose:rowPictureDataPath"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["dialog"]["rows"], [], "без пути таблицы колонок нет")


@unittest.skipUnless(CHROME, "Chrome не найден")
class FontAndSourceTest(unittest.TestCase):
    """Окно шрифта и источник команд списком."""

    def setUp(self):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        model["form"].setdefault("commandBar", {"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель"})
        model["form"]["commandBar"].setdefault("items", []).append(
            {"type": "Popup", "name": "ПодменюТовары", "title": "Товары"})
        source = Path(temp_dir(prefix="formmockup-font-")) / "model.json"
        source.write_text(dump(model), encoding="utf-8")
        self.server = Server(source)

    def tearDown(self):
        self.server.close()

    def test_font_dialog(self):
        result = page(self.server, ["tree:Склад", "choose:font", "dlg-set:.fe-font-face=Arial",
                                    "dlg-set:.fe-font-height=12", 'dlg-set:input[data-key="strikeout"]=true',
                                    'dlg-set:input[data-key="bold"]=true'])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["dialog"]["font"], {"faceName": "Arial", "height": 12, "bold": True, "strikeout": True})
        stepped = page(self.server, ["tree:Склад", "choose:font", "dlg-set:.fe-font-height=12", "dlg-click:.fe-font-size .fe-up",
                                     "dlg-click:.fe-font-size .fe-up", "dlg-click:.fe-font-size .fe-down"])
        self.assertEqual(stepped["dialog"]["font"], {"height": 13}, "кнопки «+/-» - шаг 1 пт")
        start = page(self.server, ["tree:Склад", "choose:font", "dlg-click:.fe-font-size .fe-down"])
        self.assertEqual(start["dialog"]["font"], {"height": 9}, "без размера - от 10 пт шрифта формы")
        saved = page(self.server, ["tree:Склад", "choose:font", "dlg-set:.fe-font-face=Arial", "dlg-set:.fe-font-height=12",
                                   "ok"])
        self.assertEqual(find(saved["model"]["form"], "Склад")["font"], {"faceName": "Arial", "height": 12})
        # Начертание кнопкой «Ж» не теряет имя и размер
        bold = page(self.server, ["tree:Склад", "choose:font", "dlg-set:.fe-font-face=Arial", "ok",
                                  'panel-set:.fe-font[data-prop="font"] input[data-key="bold"]=true'])
        self.assertEqual(bold["errors"], [])
        self.assertEqual(find(bold["model"]["form"], "Склад")["font"], {"faceName": "Arial", "bold": True})

    def test_command_source_list(self):
        result = page(self.server, ["tree:ПодменюТовары", "set:commandSource=Item.Товары"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "ПодменюТовары")["commandSource"], "Item.Товары")
        self.assertEqual({item["prop"]: item.get("value") for item in result["props"]}["commandSource"], "Item.Товары")


@unittest.skipUnless(CHROME, "Chrome не найден")
class FormatTest(unittest.TestCase):
    """format.js: сборка строки по образцу конструктора форматной строки и свой Формат() против таблицы `format-1c.json`."""

    # Параметры → строка конструктора форматной строки (постоянный порядок параметров,
    # «КЛЮЧ = значение», строка в кавычках, флажок - «Истина», пустое пропускается, кроме ЧГ)
    BUILD = [
        ({"ЧЦ": "10", "ЧДЦ": "2", "ЧРД": ".", "ЧВН": True, "ЧГ": ""}, "ЧЦ = 10; ЧДЦ = 2; ЧРД = '.'; ЧВН = Истина; ЧГ = "),
        ({"ЧГ": "0", "ЧО": "1", "ЧФ": "Ч руб."}, "ЧГ = '0'; ЧО = '1'; ЧФ = 'Ч руб.'"),
        ({"БИ": "Да", "ДФ": "dd.MM.yyyy", "ЧС": "3"}, "ЧС = 3; ДФ = 'dd.MM.yyyy'; БИ = 'Да'"),
        ({"ЧРД": "", "ДП": "", "БЛ": ""}, ""),
        ({"ЧС": "0", "ДЛФ": "DD"}, "ЧС = 0; ДЛФ = 'DD'"),
    ]

    def test_build_and_format(self):
        table = json.loads((ROOT / "tests" / "fixtures" / "format-1c.json").read_text(encoding="utf-8"))
        script = (ROOT / "render" / "format.js").read_text(encoding="utf-8")
        runner = """
          var F = window.FMFormat, T = %s, B = %s, out = { build: [], cases: [] };
          B.forEach(function (pair) { out.build.push(F.build(pair[0])); });
          T.cases.forEach(function (c) {
            var p = F.parse(c.format), v = c.value;
            if (c.type === "date") {
              var m = /^(\\d+)-(\\d+)-(\\d+)T(\\d+):(\\d+):(\\d+)/.exec(v);
              v = Number(m[1]) <= 1 ? null : new Date(Number(m[1]), m[2] - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]));
            }
            out.cases.push(c.type === "number" ? F.number(v, p) : c.type === "date" ? F.date(v, p) : F.boolean(v, p));
          });
          document.getElementById("out").textContent = JSON.stringify(out);
        """ % (json.dumps(table, ensure_ascii=False), json.dumps(self.BUILD, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "format.html"
            path.write_text('<!DOCTYPE html><meta charset="utf-8"><pre id="out"></pre><script>' + script +
                            "</script><script>" + runner + "</script>", encoding="utf-8")
            dom = render.run_chrome(CHROME, ["--dump-dom", path.as_uri()])
        out = json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', dom, re.S).group(1)))
        self.assertEqual(out["build"], [expected for _, expected in self.BUILD])
        for case, got in zip(table["cases"], out["cases"]):
            with self.subTest(format=case["format"], value=case["value"]):
                self.assertEqual(got, case["expected"])


def names(node: dict) -> list:
    return [child["name"] for child in node.get("items", [])]


def text(model) -> str:
    """Модель как ее держит страница (JSON.stringify): порядок ключей и массивов - байт в байт."""
    return json.dumps(model, ensure_ascii=False, separators=(",", ":"))


@unittest.skipUnless(CHROME, "Chrome не найден")
class ChangesPageTest(unittest.TestCase):
    """Правки против «было»: дерево, панель, список, переключатель, renamedFrom по «было»."""

    def test_before_file(self):
        server = Server(STALO, before=EXAMPLE)
        try:
            opened = page(server, ["check"])
            self.assertEqual(opened["errors"], [])
            diff = opened["diff"]
            self.assertTrue(diff["on"], "с --before правки включены")
            self.assertEqual(diff["label"], "Правки (8)")
            self.assertEqual(diff["base"], "zakaz-pokupatelya.json")
            self.assertIn(["ПечатьСчет", 1], diff["tree"])
            self.assertIn(["-Предоплата", 4], diff["tree"], "удаленный - строкой на старом месте")
            self.assertIn(["ГруппаДоставка", 8], diff["tree"])
            self.assertIn("СпособОплаты", diff["frames"], "рамки правок на макете")
            self.assertIn("Предоплата", diff["frames"], "удаленный - на старом месте")
            self.assertEqual(diff["mode"], "diff", "макет - по объединенному дереву")
            changed = page(server, ["check", "tree:ДатаОтгрузки"])["diff"]
            self.assertEqual(changed["props"], ["title"])
            self.assertIn("Изменен", changed["header"])
            reverted = page(server, ["check", "tree:ДатаОтгрузки", "revert:title", "check"])
            self.assertEqual(find(reverted["model"]["form"], "ДатаОтгрузки")["title"], "Отгрузка")
            self.assertEqual(reverted["diff"]["label"], "Правки (7)")
            self.assertEqual(reverted["diff"]["props"], [], "после возврата свойство без отметки")
            renamed = page(server, ["check", "tree:ТоварыСуммаСНДС", "revert:name", "check"])
            back = find(renamed["model"]["form"], "ТоварыСумма")
            self.assertIsNotNone(back, "имя - как было")
            self.assertNotIn("renamedFrom", back, "возврат имени снимает renamedFrom")
            listed = page(server, ["check", "right:changes", "change:3"])
            self.assertEqual(listed["diff"]["list"], list(range(1, 9)))
            self.assertEqual(listed["selected"], "ДатаОтгрузки", "щелчок по правке выбирает элемент")
            self.assertEqual(listed["diff"]["tab"], "changes", "список остается открытым")
            removed = page(server, ["check", "removed:Предоплата"])
            self.assertEqual((removed["diff"]["tab"], removed["diff"]["active"]), ("changes", 4),
                             "удаленный в дереве показывает свою правку")
            off = page(server, ["check", "tree:ДатаОтгрузки", "diff:off"])["diff"]
            self.assertEqual((off["tree"], off["props"], off["frames"], off["tab"]), ([], [], [], None))
            self.assertEqual(off["label"], "Правки (8)", "счетчик виден и при выключенных")
        finally:
            server.close()

    def test_base_at_start(self):
        server = Server()
        try:
            opened = page(server, ["check"])["diff"]
            self.assertFalse(opened["on"], "без --before правки выключены")
            self.assertEqual(opened["label"], "Правки (0)")
            edited = page(server, ["diff:on", "tree:Контрагент", "set:title=Покупатель", "check"])
            self.assertEqual(edited["errors"], [])
            self.assertEqual(edited["diff"]["changes"], [{"n": 1, "op": "changed", "after": "Контрагент", "before": "Контрагент"}])
            self.assertEqual(edited["diff"]["tree"], [["Контрагент", 1]])
            self.assertEqual(edited["diff"]["props"], ["title"])
            renamed = page(server, ["tree:Контрагент", "set:name=Клиент", "check"])
            self.assertEqual(find(renamed["model"]["form"], "Клиент")["renamedFrom"], "Контрагент", "renamedFrom по «было»")
            self.assertEqual(renamed["diff"]["changes"][0]["before"], "Контрагент")
            saved = page(server, ["tree:Контрагент", "set:title=Покупатель", "save", "check"])
            self.assertEqual(saved["diff"]["label"], "Правки (1)", "сохранение «было» не меняет")
            again = page(server, ["check"])
            self.assertEqual(again["diff"]["label"], "Правки (1)", "перечитанный файл - против «было» на запуске")
        finally:
            server.close()


@unittest.skipUnless(CHROME, "Chrome не найден")
class NotesPageTest(unittest.TestCase):
    """Примечания: номера на макете и в списке - как в колонке «№» `table`, правка в списке и из меню."""

    def setUp(self):
        self.server = Server(STALO)

    def tearDown(self):
        self.server.close()

    def table_numbers(self, model: dict) -> dict:
        from fmlib.tables import elements_table
        from fmlib.dictionary import load_dictionary
        from fmlib import DICTIONARY_PATH
        lines = elements_table(model, load_dictionary(DICTIONARY_PATH)).splitlines()[2:]
        return {(line.split("`")[1] if "`" in line else "Форма"): int(line.split("|")[1])
                for line in lines if line.split("|")[1].strip()}

    def test_numbers_like_table(self):
        result = page(self.server, ["right:notes"])
        self.assertEqual(result["errors"], [])
        numbers = self.table_numbers(result["model"])
        self.assertEqual(numbers, {"СпособОплаты": 1, "ТоварыПодобрать": 2, "ТоварыЗаполнитьПоОстаткам": 3})
        notes = result["notes"]
        self.assertEqual(notes["tab"], "notes")
        self.assertEqual(notes["label"], "Примечания (3)")
        self.assertEqual({row["key"]: int(row["n"]) for row in notes["rows"]}, numbers)
        self.assertEqual(dict(notes["frames"]), numbers, "номера на макете - те же")
        chosen = page(self.server, ["right:notes", "note-row:ТоварыПодобрать"])
        self.assertEqual(chosen["selected"], "ТоварыПодобрать", "щелчок по строке выбирает элемент")
        self.assertEqual(chosen["notes"]["tab"], "notes", "список остается открытым")

    def test_edit_in_list_and_panel(self):
        changed = page(self.server, ["right:notes", "note-set:ТоварыПодобрать=подбор по остаткам склада"])
        self.assertEqual(changed["errors"], [])
        self.assertEqual(find(changed["model"]["form"], "ТоварыПодобрать")["note"], "подбор по остаткам склада")
        removed = page(self.server, ["right:notes", "note-set:СпособОплаты=", "undo"])
        self.assertEqual(find(removed["model"]["form"], "СпособОплаты")["note"], "предложение", "отмена возвращает")
        cleared = page(self.server, ["right:notes", "note-set:СпособОплаты="])
        self.assertNotIn("note", find(cleared["model"]["form"], "СпособОплаты"), "пустой текст снимает примечание")
        self.assertEqual([row["n"] for row in cleared["notes"]["rows"]], ["1", "2"], "номера сдвинулись")
        self.assertEqual(dict(cleared["notes"]["frames"]), self.table_numbers(cleared["model"]))
        panel = page(self.server, ["tree:Контрагент", "set:note=из договора", "right:notes"])
        self.assertEqual([row["key"] for row in panel["notes"]["rows"]][0], "Контрагент", "порядок дерева")
        self.assertEqual(dict(panel["notes"]["frames"])["Контрагент"], 1)

    def test_context_menu_note(self):
        opened = page(self.server, ["ctx:Склад", "menu:note"])
        self.assertEqual(opened["errors"], [])
        self.assertEqual(opened["notes"]["tab"], "notes")
        self.assertEqual(opened["notes"]["focused"], "Склад", "фокус в тексте строки элемента")
        draft = [row for row in opened["notes"]["rows"] if row["key"] == "Склад"]
        self.assertEqual(draft, [{"key": "Склад", "n": "+", "text": ""}], "без примечания - пустая строка без номера")
        written = page(self.server, ["ctx:Склад", "menu:note", "note-set:Склад=склад из настроек"])
        self.assertEqual(find(written["model"]["form"], "Склад")["note"], "склад из настроек")
        numbers = self.table_numbers(written["model"])
        self.assertEqual({row["key"]: int(row["n"]) for row in written["notes"]["rows"]}, numbers)
        self.assertEqual(numbers["Склад"], 1, "Склад в шапке - раньше прочих примечаний")
        empty = page(self.server, ["ctx:Склад", "menu:note", "right:props", "right:notes"])
        self.assertNotIn("Склад", [row["key"] for row in empty["notes"]["rows"]], "пустая строка без текста уходит")
        layout = page(self.server, ["ctx-layout:Контрагент", "menu:note"])
        self.assertEqual(layout["notes"]["focused"], "Контрагент", "меню на макете - то же")

    def test_hidden_with_changes(self):
        """Номера примечаний при включенных «Правках» не рисуются: две нумерации путаются."""
        server = Server(STALO, before=EXAMPLE)
        try:
            result = page(server, ["check", "right:notes"])
            self.assertEqual(result["errors"], [])
            self.assertTrue(result["diff"]["on"])
            self.assertEqual(result["notes"]["frames"], [])
            self.assertEqual(len(result["notes"]["rows"]), 3, "список примечаний - есть")
            off = page(server, ["check", "right:notes", "diff:off"])
            self.assertEqual(len(off["notes"]["frames"]), 3)
            self.assertEqual(off["notes"]["tab"], "notes", "выключение правок не уводит с закладки")
        finally:
            server.close()


@unittest.skipUnless(CHROME, "Chrome не найден")
class StyleSourceTest(unittest.TestCase):
    """Закладка «Из стиля»: элементы стиля конфигурации - с сервера при `--src`, в модель - выбранный."""

    def test_config_styles_from_server(self):
        server = Server(EXAMPLE, src=EDT_SRC)
        try:
            opened = page(server, ["tree:Склад", "choose:backColor", "find:_Демо"])
            self.assertEqual(opened["errors"], [])
            self.assertGreaterEqual(opened["dialog"]["colorRows"], 1, "элемент стиля конфигурации из исходников")
            chosen = page(server, ["tree:Склад", "choose:backColor", "find:_Демо", "color:style:_ДемоЦветАкцента", "ok"])
            self.assertEqual(find(chosen["model"]["form"], "Склад")["backColor"], "style:_ДемоЦветАкцента")
            self.assertEqual(chosen["model"]["styles"], {"_ДемоЦветАкцента": "#1955AE"}, "значение - в styles модели")
            self.assertEqual([issue for issue in chosen["issues"] if issue["code"] == "style-color"], [])
        finally:
            server.close()


@unittest.skipUnless(CHROME, "Chrome не найден")
class RoundTripTest(unittest.TestCase):
    """Круг «конструктор → агент»: правки руками на примере, сохранение; файл проходит `check`, рисуется
    `render`, правки `render --before` / `table --before` - те же, что показал конструктор."""

    def test_round_trip(self):
        from fmlib import DICTIONARY_PATH, SCHEMA_PATH
        from fmlib.diff import compare
        from fmlib.dictionary import load_dictionary
        from fmlib.model import check
        from fmlib.schema import SchemaValidator
        server = Server(EXAMPLE)
        try:
            result = page(server, ["tree:Договор", "set:name=ДоговорКонтрагента",
                                   "drag:Склад>Контрагент@after",
                                   "tree:ДатаОтгрузки", "set:title=Дата отгрузки товара",
                                   "tree:ДоговорКонтрагента", "add:CheckBoxField",
                                   "save", "check"])
            self.assertEqual(result["errors"], [])
            self.assertFalse(result["dirty"], "сохранено")
            saved = json.loads(server.path.read_text(encoding="utf-8"))
            original = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            self.assertEqual(find(saved["form"], "ДоговорКонтрагента")["renamedFrom"], "Договор")
            self.assertEqual(check(saved, SchemaValidator.from_file(SCHEMA_PATH)), [], "check чистый")
            diff = compare(original, saved, load_dictionary(DICTIONARY_PATH))
            expected = [(change.number, change.op, change.after or None, change.before or None)
                        for change in diff.changes]
            shown = [(change["n"], change["op"], change["after"], change["before"]) for change in result["diff"]["changes"]]
            self.assertEqual(shown, expected, "правки конструктора - те же, что у render --before")
            self.assertEqual({op for _, op, _, _ in expected}, {"added", "changed", "moved"})
            folder = Path(temp_dir(prefix="formmockup-round-"))
            before = folder / "было.json"
            before.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            cli = ROOT / "formmockup.py"
            rendered = subprocess.run([sys.executable, str(cli), "render", str(server.path), "--before", str(before),
                                       "-o", str(folder / "out")], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            self.assertIn(f"Правок: {len(expected)}", rendered.stdout)
            table = subprocess.run([sys.executable, str(cli), "table", str(server.path), "--before", str(before)],
                                   capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(table.returncode, 0, table.stderr)
            self.assertEqual(len([line for line in table.stdout.splitlines()[2:] if line.strip()]), len(expected))
        finally:
            server.close()


@unittest.skipUnless(CHROME, "Chrome не найден")
class StructureTest(unittest.TestCase):
    """Правка структуры: палитра по месту, имена, перенос, удаление, отмена и повтор."""

    def setUp(self):
        self.server = Server(EXAMPLE)
        self.original = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def tearDown(self):
        self.server.close()

    def test_palette_by_place(self):
        body = page(self.server, ["tree:Договор", "palette"])
        self.assertEqual(body["errors"], [])
        self.assertEqual(body["palette"]["note"], "после «Договор»")
        kinds = body["palette"]["kinds"]
        self.assertEqual(kinds[:5], ["InputField", "LabelField", "CheckBoxField", "RadioButtonField", "PictureField"])
        for kind in ("UsualGroup", "Pages", "Table", "LabelDecoration", "Button", "CommandBar", "Popup", "PlannerField"):
            self.assertIn(kind, kinds)
        for kind in ("Page", "ColumnGroup", "ButtonGroup", "Addition", "Unknown"):
            self.assertNotIn(kind, kinds)
        column = page(self.server, ["tree:Товары", "palette"])["palette"]
        self.assertEqual(column["note"], "в «Товары»", "развернутая таблица - вставка внутрь")
        self.assertIn("ColumnGroup", column["kinds"])
        for kind in ("RadioButtonField", "UsualGroup", "Button", "CalendarField"):
            self.assertNotIn(kind, column["kinds"], "в колонке - без видов, недоступных в таблице")
        self.assertEqual(page(self.server, ["tree:ГруппаСтраницы", "palette"])["palette"]["kinds"], ["Page"])
        self.assertEqual(page(self.server, ["tree:ФормаКоманднаяПанель", "palette"])["palette"]["kinds"],
                         ["ButtonGroup", "Popup", "Button"])

    def test_add_names_place_and_check(self):
        result = page(self.server, ["tree:Договор", "add:UsualGroup", "add:InputField", "add:UsualGroup",
                                    "tree:Поле1", "add:Pages", "tree:Поле1", "add:Table", "check"])
        self.assertEqual(result["errors"], [])
        left = find(result["model"]["form"], "ГруппаШапкаЛево")
        self.assertEqual(names(left), ["Контрагент", "Договор", "Группа1"], "после выбранного")
        group = find(result["model"]["form"], "Группа1")
        self.assertEqual(names(group), ["Поле1", "Таблица1", "Группа3", "Группа2"],
                         "в пустой контейнер, затем после выбранного; имена по виду с номером, без повторов")
        inside = page(self.server, ["tree:ГруппаСтраницы", "add:Page"])
        self.assertEqual(names(find(inside["model"]["form"], "ГруппаСтраницы"))[-1], "Страница1",
                         "развернутый контейнер - внутрь, в конец")
        self.assertEqual(group["items"][0], {"type": "InputField", "name": "Поле1"})
        self.assertEqual(find(result["model"]["form"], "Группа3"),
                         {"type": "Pages", "name": "Группа3", "items": [{"type": "Page", "name": "Страница1"}]})
        self.assertEqual(find(result["model"]["form"], "Таблица1")["items"], [{"type": "InputField", "name": "Поле2"}])
        self.assertEqual(result["selected"], "Таблица1", "новый элемент выбран")
        codes = {(issue["code"], issue.get("name")) for issue in result["issues"]}
        self.assertIn(("empty-container", "Группа2"), codes, "замечания пересчитаны после правки")

    def test_add_into_command_bar_of_new_form(self):
        source = Path(temp_dir(prefix="formmockup-source-")) / "new.json"
        source.write_text(dump(empty_model("DataProcessorForm")), encoding="utf-8")
        server = Server(source)
        try:
            result = page(server, ["tree:ФормаКоманднаяПанель", "add:Button", "tree:Форма", "add:InputField", "save"])
        finally:
            written = json.loads(server.path.read_text(encoding="utf-8"))
            server.close()
        self.assertEqual(result["errors"], [])
        self.assertEqual(written["form"]["commandBar"], {"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель",
                                                         "items": [{"type": "Button", "name": "Кнопка1",
                                                                    "buttonType": "CommandBarButton"}]})
        self.assertEqual(written["form"]["items"], [{"type": "InputField", "name": "Поле1"}])

    def test_open_popup_follows_changes(self):
        """Раскрытое на макете подменю перерисовывается после переноса в него, из него и отмены (обкатка:
        оставалось прежним до закрытия и повторного открытия)."""
        result = page(self.server, ["click:ПодменюПечать", "drag:СоздатьРеализацию>ПечатьЗаказ@after"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["openMenu"], ["Счет на оплату", "Заказ покупателя", "Реализация товаров"])
        result = page(self.server, ["click:ПодменюПечать", "drag:ПечатьСчет>ПодменюСоздатьНаОсновании@inside"])
        self.assertEqual(result["openMenu"], ["Заказ покупателя"])
        # Отмена клавишами (кнопка «Отменить» - щелчок мимо меню, он меню закрывает)
        result = page(self.server, ["click:ПодменюПечать", "drag:ПечатьСчет>ПодменюСоздатьНаОсновании@inside",
                                    "hotkey:KeyZ"])
        self.assertEqual(result["openMenu"], ["Счет на оплату", "Заказ покупателя"])

    def test_drag(self):
        moved = page(self.server, ["drag:Договор>ГруппаШапкаПраво@inside", "drag:Контрагент>Предоплата@before"])
        self.assertEqual(moved["errors"], [])
        self.assertTrue(moved["dropAccepted"])
        form = moved["model"]["form"]
        self.assertNotIn("items", find(form, "ГруппаШапкаЛево"), "пустой items уходит из модели")
        self.assertEqual(names(find(form, "ГруппаШапкаПраво")), ["ДатаОтгрузки", "Контрагент", "Предоплата", "Договор"])
        self.assertEqual(moved["selected"], "Контрагент")
        column = page(self.server, ["drag:Склад>ТоварыСумма@after"])
        columns = names(find(column["model"]["form"], "Товары"))
        self.assertEqual(columns.index("Склад"), columns.index("ТоварыСумма") + 1, "поле формы - колонкой таблицы")
        for action in ("drag:ГруппаДополнительно>ГруппаШапка@inside",   # страница вне «Страниц»
                       "drag:Договор>ФормаКоманднаяПанель@inside",       # поле в командную панель
                       "drag:ГруппаШапка>ГруппаШапкаЛево@inside",        # в свой подчиненный
                       "drag:ПечатьСчет>ГруппаШапка@inside"):            # кнопка командной панели - в тело формы можно
            result = page(self.server, [action])
            self.assertEqual(result["errors"], [], action)
            if action.startswith("drag:ПечатьСчет"):
                self.assertTrue(result["dropAccepted"], action)
                continue
            self.assertFalse(result["dropAccepted"], action)
            self.assertEqual(text(result["model"]), text(self.original), action)

    def test_move_among_siblings(self):
        result = page(self.server, ["tree:Контрагент", "move:down", "alt:ArrowDown"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(names(find(result["model"]["form"], "ГруппаШапкаЛево")), ["Договор", "Контрагент"])
        self.assertEqual(result["tools"], {"add": True, "delete": True, "up": True, "down": False},
                         "у последнего «Вниз» недоступно, за край не уходит")
        self.assertEqual(result["undo"], 1)
        root = page(self.server, ["tree:Форма"])
        self.assertEqual(root["tools"], {"add": True, "delete": False, "up": False, "down": False})
        self.assertFalse(page(self.server, ["tree:ТоварыКоманднаяПанель"])["tools"]["delete"])

    def test_context_menu(self):
        menu = page(self.server, ["tree:Склад", "ctx:Контрагент"])
        self.assertEqual(menu["errors"], [])
        self.assertEqual(menu["selected"], "Контрагент", "правая кнопка выбирает строку")
        self.assertEqual(menu["palette"]["actions"], ["delete", "up-", "down", "note"], "у первого «Вверх» недоступно")
        self.assertEqual(menu["palette"]["note"], "Добавить после «Контрагент»")
        self.assertIn("UsualGroup", menu["palette"]["kinds"])
        self.assertIsNone(menu["palette"]["focused"], "мышью - без фокуса на пункте")
        added = page(self.server, ["ctx:Контрагент", "add:UsualGroup"])
        self.assertEqual(names(find(added["model"]["form"], "ГруппаШапкаЛево")), ["Контрагент", "Группа1", "Договор"])
        moved = page(self.server, ["ctx:Контрагент", "menu:down"])
        self.assertEqual(names(find(moved["model"]["form"], "ГруппаШапкаЛево")), ["Договор", "Контрагент"])
        self.assertIsNone(moved["palette"], "после действия меню закрыто")
        removed = page(self.server, ["ctx:Склад", "menu:delete"])
        self.assertIsNone(find(removed["model"]["form"], "Склад"))
        layout = page(self.server, ["ctx-layout:Договор"])
        self.assertEqual(layout["selected"], "Договор", "с макета - тот же выбор и меню")
        self.assertEqual(layout["palette"]["note"], "Добавить после «Договор»")
        root = page(self.server, ["ctx:Форма"])
        self.assertEqual(root["palette"]["actions"], ["delete-", "up-", "down-", "note"], "примечание бывает и у формы")
        self.assertEqual(root["palette"]["note"], "Добавить в «Форма»")
        keyboard = page(self.server, ["tree:Договор", "ctx:"])
        self.assertEqual(keyboard["selected"], "Договор")
        self.assertEqual(keyboard["palette"]["focused"], "delete", "с клавиатуры - фокус на первом пункте")
        shift = page(self.server, ["tree:Склад", "key:Shift+F10"])
        self.assertEqual(shift["palette"]["note"], "Добавить после «Склад»")
        self.assertEqual(shift["palette"]["focused"], "delete")
        insert = page(self.server, ["tree:Договор", "key:Insert"])
        self.assertEqual(insert["palette"]["actions"], [], "Insert - только палитра")
        self.assertEqual(insert["palette"]["focused"], "InputField")

    def test_delete(self):
        asked = page(self.server, ["tree:ГруппаШапка", "delete"])
        self.assertEqual(asked["dialog"]["kind"], "delete")
        self.assertIn("(6)", asked["dialog"]["text"])
        kept = page(self.server, ["tree:ГруппаШапка", "delete", "cancel"])
        self.assertEqual(text(kept["model"]), text(self.original))
        done = page(self.server, ["tree:ГруппаШапка", "delete", "ok"])
        self.assertIsNone(find(done["model"]["form"], "ГруппаШапка"))
        self.assertIsNone(find(done["model"]["form"], "Договор"), "с подчиненными")
        self.assertEqual(done["selected"], "ГруппаСтраницы", "выбран следующий сосед")
        leaf = page(self.server, ["tree:Склад", "key:Delete"])
        self.assertIsNone(leaf["dialog"], "без подчиненных - без вопроса")
        self.assertEqual(names(find(leaf["model"]["form"], "ГруппаДополнительно")), ["Комментарий"])
        self.assertEqual(leaf["selected"], "Комментарий")
        page_gone = page(self.server, ["tree:ГруппаТовары", "delete", "ok"])
        pages = find(page_gone["model"]["form"], "ГруппаСтраницы")
        self.assertNotIn("currentPage", pages, "удаленная текущая закладка не остается в currentPage")
        root = page(self.server, ["tree:Форма", "key:Delete"])
        self.assertEqual(text(root["model"]), text(self.original), "корень не удаляется")

    def test_undo_redo_byte_exact(self):
        edits = ["tree:Договор", "add:UsualGroup", "drag:Склад>Группа1@inside", "tree:ГруппаПодвал", "delete", "ok",
                 "tree:Контрагент", "alt:ArrowDown", "set:title=Покупатель", "left:attributes", "attr-add", "left:items"]
        after = page(self.server, edits)
        self.assertEqual(after["errors"], [])
        self.assertEqual(after["undo"], 6)
        undone = page(self.server, edits + ["undo"] * 4 + ["hotkey:KeyZ", "hotkey:KeyZ"])
        self.assertEqual(undone["errors"], [])
        self.assertEqual(text(undone["model"]), text(self.original), "отмена возвращает модель байт в байт")
        self.assertEqual((undone["undo"], undone["redo"]), (0, 6))
        self.assertFalse(undone["dirty"])
        redone = page(self.server, edits + ["undo"] * 6 + ["redo"] * 5 + ["hotkey:Shift+KeyZ"])
        self.assertEqual(text(redone["model"]), text(after["model"]), "повтор - тоже байт в байт")
        self.assertEqual((redone["undo"], redone["redo"]), (6, 0))
        branch = page(self.server, edits[:2] + ["undo", "tree:Склад", "move:down"])
        self.assertEqual((branch["undo"], branch["redo"]), (1, 0), "новая правка после отмены сбрасывает повтор")

    def test_history_survives_save(self):
        result = page(self.server, ["tree:Договор", "add:LabelDecoration", "save", "undo"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["redo"], 1)
        self.assertTrue(result["dirty"], "после отмены сохраненной правки файл и страница расходятся")
        self.assertIsNotNone(find(json.loads(self.server.path.read_text(encoding="utf-8"))["form"], "Декорация1"))


@unittest.skipUnless(CHROME, "Chrome не найден")
class FormBarTest(unittest.TestCase):
    def test_new_model_form_bar(self):
        source = Path(temp_dir(prefix="formmockup-source-")) / "empty-model.json"
        source.write_text(dump(empty_model("DocumentObjectForm")), encoding="utf-8")
        server = Server(source)
        result = page(server, ["tree:ФормаКоманднаяПанель", "set:autoFill=false", "tree:Форма", "set:title=Новая", "save"])
        written = json.loads(server.path.read_text(encoding="utf-8"))
        server.close()
        self.assertEqual(result["errors"], [])
        self.assertEqual(list(written["form"]), ["formKind", "title", "commandBar", "items"])
        self.assertEqual(written["form"]["commandBar"], {"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель",
                                                         "autoFill": False})


@unittest.skipUnless(CHROME, "Chrome не найден")
class FileTest(unittest.TestCase):
    """Сохранение и слежение за файлом, сломанная модель и нечитаемый файл."""

    def tearDown(self):
        self.server.close()

    def test_save(self):
        self.server = Server(EXAMPLE)
        result = page(self.server, ["tree:Форма", "set:title=Заказ клиента", "save"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["dirty"])
        self.assertEqual(result["status"], "сохранено")
        self.assertEqual(json.loads(self.server.path.read_text(encoding="utf-8"))["form"]["title"], "Заказ клиента")

    def test_external_write_reloads_clean_page(self):
        self.server = Server(EXAMPLE, hooked({2: changed_title("Агент")}))
        result = page(self.server, ["wait:4000"])
        self.assertEqual(result["model"]["form"]["title"], "Агент")
        self.assertTrue(result["fileUpdated"])
        self.assertFalse(result["conflict"])
        self.assertIn("файл обновлён", result["status"])

    def test_external_write_with_edits_shows_banner(self):
        self.server = Server(EXAMPLE, hooked({2: changed_title("Агент")}))
        result = page(self.server, ["tree:Форма", "set:title=Мой", "wait:4000", "save"])
        self.assertTrue(result["conflict"])
        self.assertEqual(result["model"]["form"]["title"], "Мой", "правки страницы не пропадают")
        self.assertIn("не сохранено", result["saveError"])
        self.assertEqual(json.loads(self.server.path.read_text(encoding="utf-8"))["form"]["title"], "Агент")

    def test_folder_switch_stops_saving(self):
        """Сервис переключили на другую папку, пока вкладка открыта: вкладка не пишет одноименный файл новой
        папки, показывает «папка макетов сменилась», правки страницы не пропадают; файлы обеих папок не тронуты."""
        other = Path(temp_dir(prefix="formmockup-other-"))
        self.addCleanup(shutil.rmtree, other, True)
        shutil.copy(EXAMPLE, other / "model.json")
        holder = {}
        self.server = Server(EXAMPLE, hooked({2: lambda editor: holder["workspace"].open_folder(other)}))
        holder["workspace"] = self.server.server.RequestHandlerClass.workspace
        mine, theirs = self.server.path.read_bytes(), (other / "model.json").read_bytes()
        result = page(self.server, ["wait:4000", "tree:Форма", "set:title=Мой", "save"])
        self.assertEqual(result["errors"], [])
        self.assertIn("папка макетов сменилась", result["status"])
        self.assertFalse(result["conflict"], "не «файл изменён»: «Оставить мои» записало бы чужой файл")
        self.assertEqual(result["model"]["form"]["title"], "Мой", "правки страницы не пропадают")
        self.assertEqual(self.server.path.read_bytes(), mine)
        self.assertEqual((other / "model.json").read_bytes(), theirs)

    def test_keep_mine_overwrites(self):
        self.server = Server(EXAMPLE, hooked({2: changed_title("Агент")}))
        result = page(self.server, ["tree:Форма", "set:title=Мой", "wait:4000", "keep", "save"])
        self.assertFalse(result["conflict"])
        self.assertEqual(result["status"], "сохранено")
        self.assertEqual(json.loads(self.server.path.read_text(encoding="utf-8"))["form"]["title"], "Мой")

    def test_reread_drops_edits(self):
        self.server = Server(EXAMPLE, hooked({2: changed_title("Агент")}))
        result = page(self.server, ["tree:Форма", "set:title=Мой", "wait:4000", "reread"])
        self.assertFalse(result["conflict"])
        self.assertFalse(result["dirty"])
        self.assertEqual(result["model"]["form"]["title"], "Агент")

    def test_unreadable_file_keeps_model(self):
        self.server = Server(EXAMPLE, hooked({2: '{"version": 1, "form": {', 5: changed_title("Агент")}))
        broken = page(self.server, ["wait:3500"])
        self.assertIn("не читается", broken["status"])
        self.assertEqual(broken["model"]["form"]["title"], "Заказ покупателя")
        self.assertTrue(broken["layoutShown"])
        self.server.close()
        self.server = Server(EXAMPLE, hooked({2: '{"version": 1, "form": {', 5: changed_title("Агент")}))
        fixed = page(self.server, ["wait:7000"], budget=10000)
        self.assertEqual(fixed["unreadable"], "")
        self.assertEqual(fixed["model"]["form"]["title"], "Агент")

    def test_server_stopped(self):
        def stop(editor):
            threading.Thread(target=self.server.server.shutdown).start()
            self.server.server.socket.close()

        self.server = Server(EXAMPLE, hooked({2: stop}))
        result = page(self.server, ["tree:Форма", "set:title=Мой", "wait:4000"])
        self.assertFalse(result["online"])
        self.assertEqual(result["status"], "нет связи с сервером")
        self.assertTrue(result["saveDisabled"])
        self.assertEqual(result["model"]["form"]["title"], "Мой", "правки на странице живут")

    def test_blocking_model_opens(self):
        model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        find(model["form"], "Склад")["name"] = "Договор"
        source = Path(temp_dir(prefix="formmockup-source-")) / "duplicate-model.json"
        source.write_text(dump(model), encoding="utf-8")
        self.server = Server(source)
        broken = page(self.server, [])
        self.assertTrue(broken["blocked"])
        self.assertFalse(broken["layoutShown"])
        self.assertIn("ГруппаДополнительно", broken["treeKeys"], "дерево работает")
        # Второй «Договор» - на закладке «Дополнительно»: ключ дерева занят первым, правим через вид
        fixed = page(self.server, ["tree:ГруппаДополнительно", "key:ArrowDown", "set:name=Склад", "check"])
        self.assertEqual(fixed["errors"], [])
        self.assertFalse(fixed["blocked"])
        self.assertTrue(fixed["layoutShown"])


def tuning_model() -> dict:
    """Пример заказа и реквизиты формы каждого вида для переноса с закладки."""
    model = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    model["attributes"] += [
        {"name": "Флаг", "valueType": "Boolean"},
        {"name": "Текст", "valueType": "String"},
        {"name": "АдресКартинки", "valueType": "String"},
        {"name": "Строки", "valueType": "ValueTable", "columns": [
            {"name": "Колонка", "valueType": "String"}, {"name": "Отметка", "valueType": "Boolean"}]},
    ]
    model["commands"] = [{"name": "Проверить", "title": "Проверить заказ"}]
    return model


@unittest.skipUnless(CHROME, "Chrome не найден")
class TuningTest(unittest.TestCase):
    """Доводка конструктора по обкатке: перенос с закладок, кнопки автозаполнения в модель, вид новой
    кнопки, картинка стандартной команды, окна выбора."""

    def setUp(self):
        self.folder = Path(temp_dir(prefix="formmockup-tuning-"))
        self.original = tuning_model()
        source = self.folder / "model.json"
        source.write_text(dump(self.original), encoding="utf-8")
        self.server = Server(source)

    def tearDown(self):
        self.server.close()
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_multi_select_delete(self):
        """Ctrl - добавить к выделению, Delete - удалить всех одним шагом отмены."""
        result = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctrl-tree:Предоплата"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["picked"], ["Контрагент", "Договор", "Предоплата"])
        self.assertEqual(result["frames"], 3, "рамка у каждого выделенного")
        self.assertFalse(result["tools"]["up"], "перенос нескольких - не сейчас")
        removed = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctrl-tree:Предоплата", "key:Delete"])
        form = removed["model"]["form"]
        self.assertEqual([find(form, name) for name in ("Контрагент", "Договор", "Предоплата")], [None, None, None])
        self.assertEqual(removed["undo"], 1)
        self.assertEqual(len(removed["picked"]), 1, "после удаления - один выбранный")
        undone = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctrl-tree:Предоплата", "key:Delete", "undo"])
        self.assertEqual(text(undone["model"]), text(self.original))
        # Ctrl по выделенному - снять; щелчок без Ctrl - снова один
        toggled = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctrl-tree:Контрагент"])
        self.assertEqual(toggled["picked"], ["Договор"])
        single = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "tree:Склад"])
        self.assertEqual(single["picked"], ["Склад"])

    def test_multi_select_range_and_layout(self):
        """Shift - диапазон видимых строк; вложенный в выделенную группу уходит вместе с ней (одно подтверждение);
        Ctrl по макету - тоже выделение."""
        ranged = page(self.server, ["tree:Контрагент", "shift-tree:ДатаОтгрузки"])
        self.assertEqual(ranged["picked"], ["Контрагент", "Договор", "ГруппаШапкаПраво", "ДатаОтгрузки"])
        asked = page(self.server, ["tree:Контрагент", "shift-tree:ДатаОтгрузки", "key:Delete"])
        self.assertEqual(asked["dialog"]["kind"], "delete")
        done = page(self.server, ["tree:Контрагент", "shift-tree:ДатаОтгрузки", "key:Delete", "ok"])
        self.assertEqual(names(find(done["model"]["form"], "ГруппаШапка")), ["ГруппаШапкаЛево"])
        self.assertEqual(done["undo"], 1)
        # Shift+стрелки - конец диапазона на соседнюю строку; стрелка без Shift - снова один, от конца диапазона
        keys = page(self.server, ["tree:Контрагент", "key:Shift+ArrowDown", "key:Shift+ArrowDown"])
        self.assertEqual(keys["picked"], ["Контрагент", "Договор", "ГруппаШапкаПраво"])
        back = page(self.server, ["tree:Контрагент", "key:Shift+ArrowDown", "key:Shift+ArrowDown", "key:Shift+ArrowUp"])
        self.assertEqual(back["picked"], ["Контрагент", "Договор"])
        up = page(self.server, ["tree:Договор", "key:Shift+ArrowUp", "key:Shift+ArrowUp"])
        self.assertEqual(up["picked"], ["Договор", "ГруппаШапкаЛево", "Контрагент"], "вверх - так же (порядок дерева)")
        plain = page(self.server, ["tree:Контрагент", "key:Shift+ArrowDown", "key:Shift+ArrowDown", "key:ArrowDown"])
        self.assertEqual(plain["picked"], ["ДатаОтгрузки"])
        # Правая кнопка по одному из выделенных - выделение остается, в меню удаление всех, остальное - у одного
        menu = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctx:Договор"])
        self.assertEqual(menu["picked"], ["Контрагент", "Договор"])
        self.assertEqual(menu["palette"]["actions"], ["delete", "up-", "down-", "note-"])
        self.assertEqual(menu["palette"]["kinds"], [], "добавление - у одного выделенного")
        gone = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctx-layout:Договор", "menu:delete"])
        self.assertIsNone(find(gone["model"]["form"], "Контрагент"))
        self.assertIsNone(find(gone["model"]["form"], "Договор"))
        other = page(self.server, ["tree:Контрагент", "ctrl-tree:Договор", "ctx:Склад"])
        self.assertEqual(other["picked"], ["Склад"], "мимо выделения - выбор одного, как раньше")
        on_layout = page(self.server, ["tree:Контрагент", "ctrl-click:Склад"])
        self.assertEqual(on_layout["picked"], ["Контрагент", "Склад"])
        self.assertFalse(page(self.server, ["tree:Форма", "ctrl-tree:Договор"])["picked"] == ["Форма", "Договор"],
                         "форма в выделение нескольких не входит")

    def test_multi_select_properties(self):
        """Общие свойства: имя и путь - «недоступно», разные значения - отметкой, правка - всем одним шагом."""
        both = page(self.server, ["tree:Контрагент", "ctrl-tree:Предоплата"])
        self.assertEqual(both["errors"], [])
        self.assertTrue(both["propsTitle"].startswith("Свойства: 2 элемента ("), both["propsTitle"])
        self.assertLessEqual({"name", "dataPath"}, set(both["unavailableProps"]))
        hidden = page(self.server, ["tree:Контрагент", "ctrl-tree:Предоплата", "set:visible=false"])
        form = hidden["model"]["form"]
        self.assertEqual((find(form, "Контрагент").get("visible"), find(form, "Предоплата").get("visible")), (False, False))
        self.assertEqual(hidden["undo"], 1)
        self.assertEqual(hidden["picked"], ["Контрагент", "Предоплата"], "выделение остается после правки")
        mixed = page(self.server, ["tree:Контрагент", "set:title=Клиент", "tree:Контрагент", "ctrl-tree:Договор"])
        self.assertIn("title", mixed["mixedProps"])
        same = page(self.server, ["tree:Контрагент", "set:title=Клиент", "tree:Контрагент", "ctrl-tree:Договор",
                                  "set:title=Сторона"])
        form = same["model"]["form"]
        self.assertEqual((find(form, "Контрагент")["title"], find(form, "Договор")["title"]), ("Сторона", "Сторона"))
        self.assertNotIn("title", same["mixedProps"])
        self.assertEqual(same["undo"], 2)

    def test_drop_attribute_by_kind(self):
        result = page(self.server, [
            "drag-new:attr:Флаг>ГруппаПодвал@inside", "drag-new:attr:Текст>ГруппаПодвал@inside",
            "drag-new:attr:АдресКартинки>ГруппаПодвал@inside", "drag-new:attr:Объект.Контрагент>ГруппаПодвал@inside",
            "drag-new:attr:Объект.Товары.Количество>ТоварыСумма@after"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["dropAccepted"])
        self.assertEqual(result["leftMode"], "items", "над «Элементы» открылось дерево")
        footer = find(result["model"]["form"], "ГруппаПодвал")["items"]
        self.assertEqual([(node["type"], node["name"], node["dataPath"]) for node in footer[1:]], [
            ("CheckBoxField", "Флаг", "Флаг"), ("InputField", "Текст", "Текст"),
            ("PictureField", "АдресКартинки", "АдресКартинки"),
            ("InputField", "Контрагент1", "Объект.Контрагент")], "вид по типу, имя занято - с номером")
        self.assertEqual(footer[2]["dataType"], "string", "поле ввода - тип из реквизита")
        columns = names(find(result["model"]["form"], "Товары"))
        self.assertEqual(columns[columns.index("ТоварыСумма") + 1], "ТоварыКоличество1", "колонка - в свою таблицу")
        self.assertEqual(find(result["model"]["form"], "ТоварыКоличество1")["dataPath"], "Объект.Товары.Количество")
        self.assertEqual(result["selected"], "ТоварыКоличество1")

    def test_drop_on_layout(self):
        """Реквизит и команда бросаются прямо на макет - место по элементу под курсором и оси его ряда."""
        result = page(self.server, [
            "drop-canvas:attr:Флаг>Договор@before",                          # колонка полей - по оси Y
            "drop-canvas:attr:Текст>ГруппаПодвал@inside",                    # середина контейнера - внутрь
            "drop-canvas:attr:АдресКартинки>ГруппаШапкаПраво@after",          # кромка группы в ряду - после нее
            "drop-canvas:attr:Объект.Товары.Количество>ТоварыСумма@after",   # колонка таблицы - по оси X
            "drop-canvas:cmd:Проверить>ФормаКоманднаяПанель@inside"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["dropAccepted"])
        self.assertEqual(result["leftMode"], "commands", "закладка источника остается - можно бросать дальше")
        form = result["model"]["form"]
        self.assertEqual(names(find(form, "ГруппаШапкаЛево")), ["Контрагент", "Флаг", "Договор"])
        self.assertEqual(names(find(form, "ГруппаПодвал")), ["СуммаДокумента", "Текст"])
        self.assertEqual(names(find(form, "ГруппаШапка")), ["ГруппаШапкаЛево", "ГруппаШапкаПраво", "АдресКартинки"])
        columns = names(find(form, "Товары"))
        self.assertEqual(columns[columns.index("ТоварыСумма") + 1], "ТоварыКоличество1")
        self.assertEqual(find(form, "Проверить")["buttonType"], "CommandBarButton")
        refused = page(self.server, ["drop-canvas:attr:Текст>ФормаКоманднаяПанель@inside"])
        self.assertEqual(refused["errors"], [])
        self.assertFalse(refused["dropAccepted"], "поле - не в командную панель")
        self.assertEqual(text(refused["model"]), text(self.original))
        tail = page(self.server, ["drop-canvas:attr:Текст>Форма@inside"])
        self.assertEqual(names(tail["model"]["form"])[-1], "Текст", "окно формы мимо элементов - в конец формы")

    def test_drop_table_offers_columns(self):
        offered = page(self.server, ["drag-new:attr:Строки>ГруппаПодвал@inside"])
        self.assertEqual(offered["errors"], [])
        self.assertEqual(offered["dialog"]["kind"], "columns")
        filled = page(self.server, ["drag-new:attr:Строки>ГруппаПодвал@inside", "ok"])
        table = find(filled["model"]["form"], "Строки")
        self.assertEqual((table["type"], table["dataPath"]), ("Table", "Строки"))
        self.assertEqual([(node["type"], node["name"]) for node in table["items"]],
                         [("InputField", "СтрокиКолонка"), ("CheckBoxField", "СтрокиОтметка")])
        column = page(self.server, ["drag-new:attr:Строки>ГруппаПодвал@inside", "ok",
                                    "drag-new:attr:Строки.Отметка>СтрокиКолонка@before"])
        self.assertTrue(column["dropAccepted"])
        self.assertEqual(names(find(column["model"]["form"], "Строки"))[0], "СтрокиОтметка1")

    def test_drop_refused(self):
        for action in ("drag-new:attr:Объект.Товары.Цена>ГруппаПодвал@inside",   # колонка вне своей таблицы
                       "drag-new:attr:Флаг>ТоварыСумма@after",                     # реквизит формы - не колонкой
                       "drag-new:attr:Строки.Колонка>ТоварыСумма@after",           # колонка чужой таблицы
                       "drag-new:attr:Объект>ГруппаПодвал@inside",                 # объект - вида поля нет
                       "drag-new:cmd:Проверить>ТоварыСумма@after",                 # кнопка - не колонка
                       "drag-new:attr:Текст>ФормаКоманднаяПанель@inside"):         # поле - не в командную панель
            result = page(self.server, [action])
            self.assertEqual(result["errors"], [], action)
            self.assertFalse(result["dropAccepted"], action)
            self.assertEqual(text(result["model"]), text(self.original), action)

    def test_drop_command(self):
        result = page(self.server, ["drag-new:cmd:Проверить>ГруппаПодвал@inside",
                                    "drag-new:cmd:Проверить>ФормаКоманднаяПанель@inside",
                                    "drag-new:cmd:ПечатьСчет>ПечатьЗаказ@after"])
        self.assertEqual(result["errors"], [])
        form = result["model"]["form"]
        self.assertEqual(find(form, "Проверить"), {"type": "Button", "name": "Проверить", "buttonType": "UsualButton",
                                                   "commandName": "Form.Command.Проверить"})
        self.assertEqual(find(form, "Проверить1")["buttonType"], "CommandBarButton")
        self.assertEqual(names(find(form, "ПодменюПечать")), ["ПечатьСчет", "ПечатьЗаказ", "ПечатьСчет1"],
                         "в подменю панели - кнопка панели, имя занято - с номером")
        self.assertEqual(find(form, "ПечатьСчет1")["buttonType"], "CommandBarButton")
        undone = page(self.server, ["drag-new:cmd:Проверить>ГруппаПодвал@inside", "undo"])
        self.assertEqual(text(undone["model"]), text(self.original))
        titled = page(self.server, ["drag-new:cmd:Проверить>ГруппаПодвал@inside"])
        self.assertIn("Проверить заказ", titled["selectedText"] or "", "заголовок - от команды")

    def test_new_button_kind(self):
        result = page(self.server, ["tree:ГруппаПодвал", "add:Button"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(find(result["model"]["form"], "Кнопка1")["buttonType"], "UsualButton")
        self.assertEqual({item["prop"]: item.get("value") for item in result["props"]}["buttonType"], "UsualButton",
                         "вид виден в панели сразу")
        bar = page(self.server, ["tree:ПодменюПечать", "add:Button"])
        self.assertEqual(find(bar["model"]["form"], "Кнопка1")["buttonType"], "CommandBarButton")

    def test_fill_standard_commands(self):
        form_bar = page(self.server, ["ctx:ФормаКоманднаяПанель", "menu:fill"])
        self.assertEqual(form_bar["errors"], [])
        items = form_bar["model"]["form"]["commandBar"]["items"]
        self.assertEqual([(node["name"], node.get("commandName")) for node in items[:3]], [
            ("ФормаПровестиИЗакрыть", "Form.StandardCommand.PostAndClose"),
            ("ФормаЗаписать", "Form.StandardCommand.Write"), ("ФормаПровести", "Form.StandardCommand.Post")])
        self.assertTrue(items[0]["defaultButton"])
        self.assertEqual(items[3]["name"], "ПодменюПечать", "свои кнопки - после стандартных")
        self.assertEqual({node["buttonType"] for node in items[:3]}, {"CommandBarButton"})
        # Панель таблицы: кнопка у флажка, исключенные не создаются, повтор не дублирует
        table = page(self.server, ["tree:Товары", "choose:excludedCommands", "command:MoveDown=false", "ok",
                                   "tree:ТоварыКоманднаяПанель", "panel-click:.fe-fill-standard"])
        bar = find(table["model"]["form"], "Товары")["commandBar"]["items"]
        self.assertEqual([node["commandName"] for node in bar], [
            "Form.Item.Товары.StandardCommand.Add", "Form.Item.Товары.StandardCommand.MoveUp",
            "Form.Command.ПодобратьТовары"])
        self.assertFalse(table["fillStandard"], "все уже кнопками - действие недоступно")
        menu = page(self.server, ["tree:Товары", "choose:excludedCommands", "command:MoveDown=false", "ok",
                                  "tree:ТоварыКоманднаяПанель", "panel-click:.fe-fill-standard", "ctx:ТоварыКоманднаяПанель"])
        self.assertIn("fill-", menu["palette"]["actions"])

    def test_unchecked_autofill_offers_buttons(self):
        offered = page(self.server, ["tree:ТоварыКоманднаяПанель", "set:autoFill=false"])
        self.assertEqual(offered["errors"], [])
        self.assertEqual(offered["dialog"]["kind"], "autofill")
        self.assertEqual(offered["dialog"]["values"], ["Form.Item.Товары.StandardCommand.Add",
                                                       "Form.Item.Товары.StandardCommand.MoveUp",
                                                       "Form.Item.Товары.StandardCommand.MoveDown"])
        filled = page(self.server, ["tree:ТоварыКоманднаяПанель", "set:autoFill=false", "ok"])
        bar = find(filled["model"]["form"], "Товары")["commandBar"]
        self.assertFalse(bar["autoFill"])
        self.assertEqual(names(bar)[:3], ["ТоварыДобавить", "ТоварыПереместитьВверх", "ТоварыПереместитьВниз"])
        self.assertEqual(filled["undo"], 1, "снятие флажка и кнопки - одним шагом")
        undone = page(self.server, ["tree:ТоварыКоманднаяПанель", "set:autoFill=false", "ok", "undo"])
        self.assertEqual(text(undone["model"]), text(self.original))
        refused = page(self.server, ["tree:ТоварыКоманднаяПанель", "set:autoFill=false", "cancel"])
        self.assertEqual(names(find(refused["model"]["form"], "Товары")["commandBar"]), ["ТоварыПодобрать"])

    def test_standard_command_picture(self):
        result = page(self.server, ["tree:ТоварыКоманднаяПанель", "add:Button",
                                    "set:commandName=Form.Item.Товары.StandardCommand.MoveUp"])
        self.assertEqual(result["errors"], [])
        node = find(result["model"]["form"], "Кнопка1")
        self.assertNotIn("picture", node, "картинка в модель не пишется")
        picture = [item for item in result["props"] if item["prop"] == "picture"][0]
        self.assertEqual(picture["placeholder"], "StdPicture.MoveUp", "унаследованная - серым")
        self.assertFalse(picture["set"])

    def test_choosers_double_click(self):
        cases = [
            (["tree:ПечатьСчет", "choose:commandName", 'dbl:.fe-pick-row[data-value="Form.StandardCommand.Write"]'],
             "ПечатьСчет", "commandName", "Form.StandardCommand.Write"),
            (["tree:Склад", "choose:dataPath", 'dbl:.fe-pick-row[data-path="Объект.Комментарий"]'],
             "Склад", "dataPath", "Объект.Комментарий"),
            (["tree:Склад", "choose:backColor", "tab:web", 'dbl:.fe-color-row[data-color="gainsboro"]'],
             "Склад", "backColor", "gainsboro"),
            (["tree:ПодменюПечать", "choose:picture", "find:провести",
              'dbl:.fe-picture-tile[data-picture="StdPicture.Post"]'],
             "ПодменюПечать", "picture", "StdPicture.Post"),
        ]
        for actions, name, prop, value in cases:
            result = page(self.server, actions)
            self.assertEqual(result["errors"], [], prop)
            self.assertTrue(result["dblSame"], prop + ": щелчок не подменил строку")
            self.assertIsNone(result["dialog"], prop + ": окно закрыто")
            self.assertEqual(find(result["model"]["form"], name)[prop], value)
        typed = page(self.server, ["left:attributes", "attr-pick:Текст", "choose:valueType",
                                   'dbl:.fe-type-list .fe-pick-row[data-value="Number"]'])
        self.assertEqual(typed["errors"], [])
        self.assertTrue(typed["dblSame"])
        self.assertIsNone(typed["dialog"])
        own = [node for node in typed["model"]["attributes"] if node["name"] == "Текст"][0]
        self.assertEqual(own["valueType"], "Number")


if __name__ == "__main__":
    unittest.main()
