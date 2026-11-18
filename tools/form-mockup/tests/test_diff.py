"""Сравнение версий модели и таблицы для ТЗ: пары «было / стало».

Дымовой прогон режимов страницы - в headless Chrome, пропускается без него.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import DICTIONARY_PATH, render  # noqa: E402
from fmlib.diff import GHOST_SUFFIX, compare, preorder  # noqa: E402
from fmlib.dictionary import load_dictionary  # noqa: E402
from fmlib.model import load_model  # noqa: E402
from fmlib.tables import changes_table, elements_table  # noqa: E402
from support import temp_dir  # noqa: E402

CLI = ROOT / "formmockup.py"
BEFORE = ROOT / "examples" / "zakaz-pokupatelya.json"
AFTER = ROOT / "examples" / "pravki" / "zakaz-pokupatelya-stalo.json"
DICTIONARY = load_dictionary(DICTIONARY_PATH)
CHROME, _ = render.find_chrome()


def field(name, **props):
    return dict({"type": "InputField", "name": name}, **props)


def group(name, items, **props):
    return dict({"type": "UsualGroup", "name": name, "items": items}, **props)


def model(*items):
    return {"version": 1, "form": {"title": "Форма", "items": list(items)}}


def changes_by_name(diff):
    return {change.name: change for change in diff.changes}


def names(tree):
    return [node.get("name") for node in preorder(tree) if "name" in node]


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.before = model(group("Шапка", [field("Дата"), field("Номер"), field("Сумма")]),
                            group("Подвал", [field("Комментарий")]))

    def compare(self, after):
        return compare(self.before, after, DICTIONARY)

    def test_same_model_no_changes(self):
        diff = self.compare(copy.deepcopy(self.before))
        self.assertEqual(diff.changes, [])
        self.assertEqual(names(diff.tree), names(self.before["form"]))

    def test_added(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"].insert(1, field("Склад", dataType="ref"))
        change = changes_by_name(self.compare(after))["Склад"]
        self.assertEqual(change.ops, ["added"])
        self.assertIn("место: «Шапка», после «Дата»", change.details)
        self.assertIn("Тип значения: Ссылка", change.details)

    def test_added_group_is_one_change(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"].append(group("Доставка", [field("Адрес"), field("Время")]))
        diff = self.compare(after)
        self.assertEqual([change.name for change in diff.changes], ["Доставка"])
        self.assertIn("состав: «Адрес», «Время»", diff.changes[0].details)

    def test_removed_stays_on_old_place(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"].pop(1)
        diff = self.compare(after)
        change = changes_by_name(diff)["Номер"]
        self.assertEqual(change.ops, ["removed"])
        self.assertIsNone(change.after)
        self.assertEqual(names(diff.tree), names(self.before["form"]))

    def test_moved_to_other_parent_leaves_ghost(self):
        after = copy.deepcopy(self.before)
        moved = after["form"]["items"][0]["items"].pop(2)
        after["form"]["items"][1]["items"].append(moved)
        diff = self.compare(after)
        change = changes_by_name(diff)["Сумма"]
        self.assertEqual(change.ops, ["moved"])
        self.assertEqual(change.ghost, "Сумма" + GHOST_SUFFIX)
        self.assertIn("из «Шапка» в «Подвал», после «Комментарий»", change.details)
        self.assertEqual(names(diff.tree), ["Шапка", "Дата", "Номер", "Сумма" + GHOST_SUFFIX,
                                            "Подвал", "Комментарий", "Сумма"])
        # Тень - с прежним заголовком, пометка только в имени
        ghost = next(node for node in preorder(diff.tree) if node.get("name") == change.ghost)
        self.assertEqual(ghost["title"], "Сумма")

    def test_order_move_marks_only_moved(self):
        after = copy.deepcopy(self.before)
        items = after["form"]["items"][0]["items"]
        items.insert(0, items.pop(2))
        diff = self.compare(after)
        self.assertEqual([change.name for change in diff.changes], ["Сумма"])
        self.assertEqual(diff.changes[0].ops, ["moved"])
        self.assertIn("новое место: «Шапка», в начале", diff.changes[0].details)

    def test_insert_does_not_move_neighbours(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"].insert(0, field("Новое"))
        diff = self.compare(after)
        self.assertEqual([(change.name, change.ops) for change in diff.changes], [("Новое", ["added"])])

    def test_changed_property(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"][0].update(title="Дата документа", readOnly=True)
        change = changes_by_name(self.compare(after))["Дата"]
        self.assertEqual(change.ops, ["changed"])
        self.assertIn("Заголовок: не задано → «Дата документа»", change.details)
        self.assertIn("Только просмотр: не задано → Да", change.details)

    def test_enum_value_in_russian(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["group"] = "Horizontal"
        change = changes_by_name(self.compare(after))["Шапка"]
        self.assertIn("Группировка: не задано → Горизонтальная", change.details)

    def test_rename_without_renamed_from(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"][1]["name"] = "НомерДокумента"
        diff = changes_by_name(self.compare(after))
        self.assertEqual(diff["НомерДокумента"].ops, ["added"])
        self.assertEqual(diff["Номер"].ops, ["removed"])

    def test_rename_with_renamed_from(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"][1].update(name="НомерДокумента", renamedFrom="Номер")
        diff = self.compare(after)
        self.assertEqual([change.name for change in diff.changes], ["НомерДокумента"])
        change = diff.changes[0]
        self.assertEqual(change.ops, ["changed"])
        self.assertEqual(change.before, "Номер")
        self.assertIn("Имя: Номер → НомерДокумента", change.details)
        self.assertEqual(diff.warnings, [])

    def test_renamed_from_unknown_warns(self):
        after = copy.deepcopy(self.before)
        after["form"]["items"][0]["items"][1].update(renamedFrom="НетТакого")
        diff = self.compare(after)
        self.assertEqual(diff.changes, [])
        self.assertTrue(any("НетТакого" in warning for warning in diff.warnings))

    def test_moved_and_changed(self):
        after = copy.deepcopy(self.before)
        moved = after["form"]["items"][0]["items"].pop(0)
        moved["title"] = "Дата документа"
        after["form"]["items"][1]["items"].insert(0, moved)
        change = changes_by_name(self.compare(after))["Дата"]
        self.assertEqual(change.ops, ["moved", "changed"])
        self.assertEqual(change.what, "Перенесен, изменен")

    def test_form_property(self):
        after = copy.deepcopy(self.before)
        after["form"]["title"] = "Новая форма"
        change = changes_by_name(self.compare(after))["Форма"]
        self.assertEqual(change.kind, "Form")
        self.assertEqual(change.number, 1)

    def test_numbers_follow_tree(self):
        diff = compare(load_model(BEFORE), load_model(AFTER), DICTIONARY)
        self.assertEqual([change.number for change in diff.changes], list(range(1, len(diff.changes) + 1)))
        order = [change.name for change in diff.changes]
        self.assertEqual(order, ["ПечатьСчет", "Склад", "ДатаОтгрузки", "Предоплата", "СпособОплаты",
                                 "ТоварыЗаполнитьПоОстаткам", "ТоварыСуммаСНДС", "ГруппаДоставка"])


class TablesTest(unittest.TestCase):
    def test_elements_table_in_russian(self):
        text = elements_table(load_model(BEFORE), DICTIONARY)
        lines = text.splitlines()
        # В примере есть примечание - колонка «№» первой
        self.assertEqual(lines[0], "| № | Элемент | Вид | Имя | Путь к данным | Свойства | Комментарий |")
        self.assertIn("|  | Заказ покупателя | Форма |", lines[2])
        row = next(line for line in lines if "`Контрагент`" in line)
        self.assertIn("Поле ввода", row)
        self.assertIn("Кнопка выбора: Да", row)
        self.assertIn("Тип значения: Ссылка", row)
        self.assertNotIn("InputField", text)
        # Вложенность - отступом неразрывными пробелами
        self.assertIn("|       Контрагент |", row)

    def test_note_numbers(self):
        """Номер примечания: элементы с `note` порядком обхода - форма, командная панель, элементы;
        пустое и из пробелов - не примечание; без примечаний колонки «№» нет."""
        source = model(group("Группа", [field("Вложенное", note="второе"), field("Пустое", note="  ")]),
                       field("Последнее", note="третье"))
        source["form"]["note"] = "у формы"
        source["form"]["commandBar"] = {"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель", "items": [
            {"type": "Button", "name": "Кнопка", "commandName": "Form.StandardCommand.Close", "note": "в панели"}]}
        lines = elements_table(source, DICTIONARY).splitlines()
        self.assertTrue(lines[0].startswith("| № | Элемент |"))
        numbers = {line.split("`")[1] if "`" in line else "Форма": line.split("|")[1].strip() for line in lines[2:]}
        self.assertEqual(numbers, {"Форма": "1", "ФормаКоманднаяПанель": "", "Кнопка": "2", "Группа": "",
                                   "Вложенное": "3", "Пустое": "", "Последнее": "4"})
        plain = elements_table(model(field("Поле")), DICTIONARY).splitlines()
        self.assertEqual(plain[0], "| Элемент | Вид | Имя | Путь к данным | Свойства | Комментарий |")

    def test_changes_table(self):
        diff = compare(load_model(BEFORE), load_model(AFTER), DICTIONARY)
        lines = changes_table(diff, DICTIONARY).splitlines()
        self.assertEqual(lines[0], "| № | Элемент | Вид | Что сделано | Подробности |")
        self.assertEqual(len(lines), 2 + len(diff.changes))
        self.assertIn("| 4 | Требуется предоплата (`Предоплата`) | Поле флажка | Удален |", lines[5])
        self.assertIn("Имя: ТоварыСумма → ТоварыСуммаСНДС", lines[8])

    def test_title_by_data_path(self):
        """Элемент без своего заголовка: заголовок реквизита по пути, иначе последнее имя пути,
        стандартный реквизит - русским заголовком; без пути - имя элемента."""
        source = model(field("ПолеКонтрагент", dataPath="Объект.Контрагент"), field("ПолеИНН", dataPath="Объект.ИНН"),
                       field("ПолеНомер", dataPath="Объект.Number"), field("БезПути"))
        source["attributes"] = [{"name": "Объект", "valueType": "DocumentObject.Заказ", "main": True}]
        source["types"] = {"Document.Заказ": {"attributes": [
            {"name": "Контрагент", "title": "Покупатель", "valueType": "CatalogRef.Контрагенты"}]}}
        rows = {line.split("`")[1]: line for line in elements_table(source, DICTIONARY).splitlines() if "`" in line}
        self.assertIn("\u00a0Покупатель |", rows["ПолеКонтрагент"])
        self.assertIn("\u00a0ИНН |", rows["ПолеИНН"])
        self.assertIn("\u00a0Номер |", rows["ПолеНомер"])
        self.assertIn("\u00a0Без пути |", rows["БезПути"])
        # Смена пути без своего заголовка меняет то, что видит пользователь
        after = copy.deepcopy(source)
        after["form"]["items"][1]["dataPath"] = "Объект.Контрагент"
        details = changes_by_name(compare(source, after, DICTIONARY))["ПолеИНН"].details
        self.assertIn("Заголовок: «ИНН» → «Покупатель»", details)

    def test_button_title_by_command(self):
        """Кнопка без своего заголовка - заголовок по команде, как на рисунке (владелец 04.11.2026)."""
        source = model({"type": "Button", "name": "КнопкаА", "commandName": "Form.StandardCommand.Close"},
                       {"type": "Button", "name": "КнопкаБ", "commandName": "CommonCommand.ОтправитьПисьмо"})
        rows = {line.split("`")[1]: line for line in elements_table(source, DICTIONARY).splitlines() if "`" in line}
        self.assertIn("\u00a0Закрыть |", rows["КнопкаА"])
        self.assertIn("\u00a0Отправить письмо |", rows["КнопкаБ"])

    def test_pipe_in_text_escaped(self):
        before = model(field("Поле"))
        after = model(field("Поле", title="А | Б"))
        lines = changes_table(compare(before, after, DICTIONARY), DICTIONARY).splitlines()
        self.assertIn("«А \\| Б»", lines[2])

    def test_cli(self):
        result = subprocess.run([sys.executable, str(CLI), "table", str(AFTER), "--before", str(BEFORE)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| 8 | Доставка (`ГруппаДоставка`) | Обычная группа | Добавлен |", result.stdout)
        result = subprocess.run([sys.executable, str(CLI), "table", str(BEFORE)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("`ГруппаШапка`", result.stdout)

    def test_cli_blocks_broken_before(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "before.json"
            broken.write_text(json.dumps(model(field("Поле"), field("Поле"))), encoding="utf-8")
            result = subprocess.run([sys.executable, str(CLI), "table", str(AFTER), "--before", str(broken)],
                                    capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("было: ", result.stdout)


@unittest.skipUnless(CHROME, "Chrome не найден")
class ChromeDiffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(temp_dir(prefix="formmockup-diff-"))
        before, after = load_model(BEFORE), load_model(AFTER)
        diff = compare(before, after, DICTIONARY)
        cls.html = cls.folder / "pravki.html"
        cls.html.write_text(render.build_html(after, DICTIONARY, "Заказ", None, before, diff), encoding="utf-8")
        # Свернутая группа: щелчок по правке в ней группу разворачивает
        before = model(group("Свертка", [field("Поле")], behavior="Collapsible", collapsed=True), field("Прочее"))
        after = copy.deepcopy(before)
        after["form"]["items"][0]["items"][0]["title"] = "Поле с заголовком"
        cls.collapsed_html = cls.folder / "svertka.html"
        cls.collapsed_html.write_text(render.build_html(after, DICTIONARY, "Свертка", None, before,
                                                        compare(before, after, DICTIONARY)), encoding="utf-8")

    def test_modes(self):
        start = render.measure(CHROME, self.html, expand=False)
        self.assertEqual(start.errors, [])
        self.assertEqual(start.dom["mode"], "diff")
        self.assertIn("Предоплата", start.dom["diffFrames"])
        self.assertIn("СпособОплаты", start.dom["diffFrames"])
        after = render.measure(CHROME, self.html, actions=["mode:after"], expand=False)
        self.assertEqual(after.errors, [])
        self.assertEqual(after.dom["mode"], "after")
        self.assertNotIn("Предоплата", after.dom["diffFrames"])
        before = render.measure(CHROME, self.html, actions=["mode:before"], expand=False)
        self.assertIn("ТоварыСумма", before.dom["diffFrames"])
        self.assertNotIn("СпособОплаты", before.dom["diffFrames"])
        clean = render.measure(CHROME, self.html, flags=["mode=after", "nodiff"])
        self.assertEqual(clean.dom["diffFrames"], [])

    def test_click_opens_page(self):
        layout = render.measure(CHROME, self.html, actions=["diff:8"], expand=False)
        self.assertEqual(layout.errors, [])
        self.assertEqual(layout.dom["activeChange"], 8)
        self.assertEqual(layout.dom["currentPages"]["ГруппаСтраницы"], "ГруппаДополнительно")
        self.assertIn("ГруппаДоставка", layout.dom["diffFrames"])
        self.assertIn("Склад" + GHOST_SUFFIX, layout.dom["diffFrames"])

    def test_click_removed_in_after_shows_before(self):
        layout = render.measure(CHROME, self.html, actions=["mode:after", "diff:4"], expand=False)
        self.assertEqual(layout.errors, [])
        self.assertEqual(layout.dom["mode"], "before")
        self.assertIn("Предоплата", layout.dom["diffFrames"])

    def test_click_expands_collapsed_group(self):
        start = render.measure(CHROME, self.collapsed_html, expand=False)
        self.assertIn("Свертка", start.dom["collapsed"])
        layout = render.measure(CHROME, self.collapsed_html, actions=["diff:1"], expand=False)
        self.assertEqual(layout.errors, [])
        self.assertNotIn("Свертка", layout.dom["collapsed"])
        self.assertIn("Поле", layout.dom["diffFrames"])

    def test_tabs_with_changes(self):
        layout = render.measure(CHROME, self.html, flags=["mode=diff"])
        states = render.tab_states(layout, {}, changed_only=True)
        self.assertEqual([(pages, page) for pages, page, _ in states], [("ГруппаСтраницы", "ГруппаДополнительно")])

    def test_render_cli_png(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(CLI), "render", str(AFTER), "--before", str(BEFORE),
                                     "-o", folder, "--png"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            made = sorted(path.name for path in Path(folder).glob("*.png"))
        stem = AFTER.stem
        # У «стало» есть примечания - снимок с номерами по «стало»
        self.assertEqual(made, sorted([f"{stem}__правки.png", f"{stem}__стало.png", f"{stem}__примечания.png",
                                       f"{stem}__правки__ГруппаСтраницы_ГруппаДополнительно.png"]))


if __name__ == "__main__":
    unittest.main()
