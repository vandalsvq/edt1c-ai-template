"""Рендерер: сборка HTML и дымовой прогон в headless Chrome.

Тесты с Chrome пропускаются, если Chrome не найден (`fmlib.render.find_chrome`).
"""

import base64
import json
import re
import shutil
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import DICTIONARY_PATH, render  # noqa: E402
from fmlib.dictionary import load_dictionary  # noqa: E402
from fmlib.model import load_model  # noqa: E402
from support import temp_dir  # noqa: E402

EXAMPLES = ROOT / "examples"
VITRINA = ROOT / "tests" / "fixtures" / "vitrina.json"
CLI = ROOT / "formmockup.py"
CHROME, _ = render.find_chrome()

# Замечание, заложенное в витрину нарочно: узкая колонка с длинным заголовком расширяется
# по заголовку, и таблица уходит в прокрутку, как в 1С. Длинная кнопка замечания
# не дает: в 1С кнопка растет по тексту (калибровка)
VITRINA_NOTES = {"Товары"}


def build(model_path: Path, folder: Path, pages=None) -> Path:
    model = load_model(model_path)
    html_path = folder / f"{model_path.stem}.html"
    page = render.build_html(model, load_dictionary(DICTIONARY_PATH), model["form"].get("title", ""), pages)
    html_path.write_text(page, encoding="utf-8")
    return html_path


class BuildHtmlTest(unittest.TestCase):
    def test_table_lines_only_in_body(self):
        """Без линий сетки (`horizontalLines` / `verticalLines` = false) - только содержимое таблицы: шапка и подвал
        расчерчены всегда (владелец 07.11.2026)."""
        style = (render.RENDER_DIR / "style.css").read_text(encoding="utf-8")
        rules = [line for line in style.splitlines() if "fm-no-hlines" in line or "fm-no-vlines" in line]
        self.assertTrue(rules)
        for rule in rules:
            self.assertNotRegex(rule, r"fm-no-[hv]lines\s*>\s*\.fm-t[hf]\b", rule)

    def test_self_contained(self):
        model = load_model(EXAMPLES / "zakaz-pokupatelya.json")
        page = render.build_html(model, load_dictionary(DICTIONARY_PATH), "Заказ")
        for placeholder in ("/*FM_STYLE*/", "/*FM_SCRIPT*/", "/*FM_DATA*/", "{{TITLE}}"):
            self.assertNotIn(placeholder, page)
        self.assertNotRegex(page, r"<link\s+rel=")
        self.assertNotIn("<script src", page)

    def test_script_closing_tag_in_text_escaped(self):
        model = {"version": 1, "form": {"title": "</script><b>", "items": []}}
        page = render.build_html(model, {}, "x")
        data = page.split('<script id="fm-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(data)["model"]["form"]["title"], "</script><b>")

    def test_state_hash(self):
        self.assertEqual(render.state_hash(), "static&expand")
        self.assertEqual(render.state_hash(static=False), "")
        self.assertIn("page=", render.state_hash({"Страницы": "Вторая"}))
        self.assertIn("act=", render.state_hash(actions=["toggle:Группа"]))


@unittest.skipUnless(CHROME, "Chrome не найден")
class FindChromeTest(unittest.TestCase):
    """Поиск браузера: установка для пользователя на Windows, запасной Edge."""

    def setUp(self):
        self.folder = Path(temp_dir(prefix="formmockup-find-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))

    def install(self, relative: str) -> Path:
        path = self.folder / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(b"")
        return path

    def find(self, **roots):
        env = {name: "" for name in render.WINDOWS_ROOTS}
        env.update(roots)
        env[render.CHROME_ENV] = ""
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch.object(render, "CHROME_PATHS", []), \
                unittest.mock.patch.object(render, "EDGE_PATHS", []), \
                unittest.mock.patch("fmlib.render.shutil.which", return_value=None):
            return render.find_chrome()

    def test_chrome_for_user(self):
        chrome = self.install(r"user/Google/Chrome/Application/chrome.exe")
        found, searched = self.find(LOCALAPPDATA=str(self.folder / "user"))
        self.assertEqual(Path(found), chrome)
        self.assertFalse(render.is_edge(found))

    def test_chrome_before_edge(self):
        chrome = self.install(r"all/Google/Chrome/Application/chrome.exe")
        self.install(r"x86/Microsoft/Edge/Application/msedge.exe")
        found, _ = self.find(PROGRAMFILES=str(self.folder / "all"), **{"PROGRAMFILES(X86)": str(self.folder / "x86")})
        self.assertEqual(Path(found), chrome)

    def test_edge_fallback(self):
        edge = self.install(r"x86/Microsoft/Edge/Application/msedge.exe")
        found, searched = self.find(**{"PROGRAMFILES(X86)": str(self.folder / "x86")})
        self.assertEqual(Path(found), edge)
        self.assertTrue(render.is_edge(found))

    def test_nothing_found(self):
        found, searched = self.find()
        self.assertIsNone(found)
        self.assertIn("msedge", " ".join(searched), "в списке мест - и Edge")

    @unittest.skipUnless(sys.platform == "win32" and CHROME, "версия из ресурса exe - только Windows")
    def test_version_on_windows(self):
        self.assertRegex(render.browser_version(CHROME), r"^(Google Chrome|Microsoft Edge) \d+\.\d+\.\d+\.\d+$")


class ChromeSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(temp_dir(prefix="formmockup-test-"))

    def test_examples_render_clean(self):
        for path in sorted(EXAMPLES.glob("*.json")):
            with self.subTest(example=path.name):
                layout = render.measure(CHROME, build(path, self.folder))
                self.assertEqual(layout.errors, [])
                self.assertEqual(layout.notes, [])
                self.assertGreater(layout.width, 400)
                self.assertGreater(layout.height, 150)

    def test_vitrina_layout_notes(self):
        layout = render.measure(CHROME, build(VITRINA, self.folder))
        self.assertEqual(layout.errors, [])
        found = {note.split(":", 1)[0] for note in layout.notes}
        self.assertEqual(found, VITRINA_NOTES, layout.notes)

    def test_vitrina_title_wrap(self):
        """Автоперенос заголовков (Г-3) - как на снимках 1С закладок «Заголовки» 1-4 витрины (01.11.2026)."""
        layout = render.measure(CHROME, build(VITRINA, self.folder))
        wrapped = {name[:2] for name in layout.dom["wrappedTitles"] if name.startswith("З")}
        self.assertEqual(wrapped, {"ЗГ", "ЗИ", "ЗР", "ЗС", "ЗУ", "ЗЧ", "ЗЩ", "ЗЯ"})
        # Флажок справа в той же группе - тоже в две строки, как «Начислять↵амортизацию» в 1С
        self.assertIn("ЗИНачислять", layout.dom["wrappedTitles"])

    def test_tabs_and_groups_click(self):
        html_path = build(VITRINA, self.folder)
        start = render.measure(CHROME, html_path, expand=False)
        self.assertEqual(start.dom["currentPages"]["Страницы"], "СтраницаПоля")
        # Страница - как в 1С:Предприятие: свернутая в XML группа свернута (владелец 31.10.2026)
        self.assertIn("ГруппаСвернутая", start.dom["collapsed"])
        self.assertNotIn("ГруппаСвертываемая", start.dom["collapsed"])
        # Снимок для ТЗ - развернута, как предпросмотр конфигуратора
        shot = render.measure(CHROME, html_path)
        self.assertNotIn("ГруппаСвернутая", shot.dom["collapsed"])

        actions = ["tab:Страницы:СтраницаГруппы", "toggle:ГруппаСвертываемая", "toggle:ГруппаСвернутая",
                   "tab:СтраницыСлева:СтраницаСлеваПрочее"]
        after = render.measure(CHROME, html_path, actions=actions, expand=False)
        self.assertEqual(after.errors, [])
        self.assertEqual(after.dom["currentPages"]["Страницы"], "СтраницаГруппы")
        self.assertEqual(after.dom["currentPages"]["СтраницыСлева"], "СтраницаСлеваПрочее")
        self.assertIn("ГруппаСвертываемая", after.dom["collapsed"])
        self.assertNotIn("ГруппаСвернутая", after.dom["collapsed"])

    def test_names_not_clipped_and_apart(self):
        """Бирки имен - слоем поверх формы: панели и таблицы их не обрезают, бирки не лежат друг на друге."""
        plain = render.measure(CHROME, build(VITRINA, self.folder))
        layout = render.measure(CHROME, build(VITRINA, self.folder), flags=["names"])
        self.assertEqual(layout.errors, [])
        boxes = layout.dom["nameLabels"]
        self.assertGreater(len(boxes), 20)
        for index, (left, top, right, bottom) in enumerate(boxes):
            for other in boxes[index + 1:]:
                overlap = left < other[2] and right > other[0] and top < other[3] and bottom > other[1]
                self.assertFalse(overlap, (boxes[index], other))
        # Бирки не шире элементов (не уже 90 px): снимок с именами не раздвигается вширь
        self.assertLessEqual(layout.width, plain.width + 120)

    def test_form_width_below_minimum(self):
        """Ширина формы меньше минимальной - окно по содержимому, как в 1С (форма шириной 10 открывается шире):
        элементы не вылезают за край, замечание называет ширину (владелец)."""
        model = json.loads(EXAMPLES.joinpath("zakaz-pokupatelya.json").read_text(encoding="utf-8"))
        model["form"]["width"] = 10
        path = self.folder / "narrow.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        narrow = render.measure(CHROME, build(path, self.folder))
        self.assertEqual(narrow.errors, [])
        widened = [note for note in narrow.notes if note.startswith("ширина формы 10")]
        self.assertEqual(len(widened), 1, narrow.notes)
        # Не шире окна без ширины формы: выступы при любой ширине (рамка группы с фоном) не расширяют окно до предела
        natural_model = json.loads(json.dumps(model))
        del natural_model["form"]["width"]
        natural_path = self.folder / "natural.json"
        natural_path.write_text(json.dumps(natural_model, ensure_ascii=False), encoding="utf-8")
        natural = render.measure(CHROME, build(natural_path, self.folder))
        self.assertLessEqual(narrow.width, natural.width)
        # Заданная ширина больше минимальной - окно ее ширины, без замечания
        model["form"]["width"] = 120
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        wide = render.measure(CHROME, build(path, self.folder))
        self.assertEqual([note for note in wide.notes if note.startswith("ширина формы")], [])
        self.assertGreater(wide.width, narrow.width)

    def test_form_width_with_overhang(self):
        """Ширина формы шире естественной применяется и у формы с выступом при любой ширине (витрина, импорт
        формы элемента справочника; обкатка: окно оставалось естественным, ширина 150-600 ничего не меняла)."""
        model = json.loads(VITRINA.read_text(encoding="utf-8"))
        widths = {}
        for width in (None, 140, 200):
            if width:
                model["form"]["width"] = width
            else:
                model["form"].pop("width", None)
            path = self.folder / f"overhang-{width}.json"
            path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            layout = render.measure(CHROME, build(path, self.folder))
            self.assertEqual(layout.errors, [])
            widths[width] = layout.width
        self.assertLess(widths[None], widths[140])
        self.assertLess(widths[140], widths[200])

    def test_multiline_vertical_stretch(self):
        """Многострочное поле с «Растягивать по вертикали: Да» делит остаток высоты окна, «Максимальная высота» при
        снятом «авто» - предел в строках; без растягивания поле своей высоты (обкатка: поле не росло,
        свойств высоты у поля ввода не было). Заголовок сверху и слева, вне и внутри группы со сквозным выравниванием."""
        def field(name, **props):
            return dict({"type": "InputField", "name": name, "title": name, "dataPath": "Объект." + name,
                         "dataType": "string", "multiLine": True}, **props)

        cases = {
            "сверху": [field("Поле", titleLocation="Top", verticalStretch=True)],
            "слева": [field("Поле", titleLocation="Left", verticalStretch=True)],
            "группа": [{"type": "UsualGroup", "name": "Группа", "showTitle": False,
                        "items": [field("Код", multiLine=False), field("Поле", titleLocation="Left",
                                                                         verticalStretch=True)]}],
            "предел": [field("Поле", titleLocation="Top", verticalStretch=True, autoMaxHeight=False, maxHeight=5)],
            "без растягивания": [field("Поле", titleLocation="Top")],
        }
        heights = {}
        for case, items in cases.items():
            model = {"version": 1, "form": {"title": "Высота", "width": 60, "height": 20, "items": items}}
            path = self.folder / f"multiline-{len(heights)}.json"
            path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            layout = render.measure(CHROME, build(path, self.folder))
            self.assertEqual(layout.errors, [], case)
            heights[case] = layout.dom["inputHeights"]["Поле"]
        three, five = 3 * 17 + 6, 5 * 17 + 6
        self.assertEqual(heights["без растягивания"], three, heights)
        self.assertEqual(heights["предел"], five, heights)
        for case in ("сверху", "слева", "группа"):
            self.assertGreater(heights[case], five * 2, (case, heights))

    def test_if_possible_column_aligned(self):
        """«Горизонтальная, если возможно», не поместившаяся в строку, - столбец со сквозной колонкой заголовков, как
        вертикальная (обкатка: первое поле стояло по колонке формы, остальные - сразу за заголовком)."""
        fields = [{"type": "InputField", "name": name, "title": name, "dataPath": "Объект." + name, "dataType": "string",
                   "width": 30} for name in ("Поле", "Длинный заголовок поля", "Еще", "Последнее")]
        model = {"version": 1, "form": {"title": "Ряд", "width": 80, "items": [
            {"type": "InputField", "name": "Наименование", "dataPath": "Объект.Description", "dataType": "string"},
            {"type": "UsualGroup", "name": "Ряд", "group": "HorizontalIfPossible", "showTitle": False,
             "items": fields}]}}
        path = self.folder / "if-possible.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        layout = render.measure(CHROME, build(path, self.folder))
        self.assertEqual(layout.errors, [])
        lefts = layout.dom["controlLefts"]
        self.assertEqual(len(lefts), 5, lefts)
        self.assertEqual(len(set(lefts.values())), 1, lefts)

    def test_empty_hyperlink_holds_no_width(self):
        """Пустая ссылка-поле надписи места не держит (реализация БП: «Расчеты» шириной 100), ссылка с текстом -
        не уже своей ширины («Увольнение»)."""
        model = json.loads(EXAMPLES.joinpath("zakaz-pokupatelya.json").read_text(encoding="utf-8"))
        del model["form"]["width"]
        path = self.folder / "hyperlink.json"
        widths = {}
        for sample in (None, "", "Расчеты"):
            probe = json.loads(json.dumps(model))
            if sample is not None:
                probe["form"]["items"].append({"type": "LabelField", "name": "Ссылка", "title": "Расчеты",
                                               "hyperlink": True, "sample": sample, "width": 300})
            path.write_text(json.dumps(probe, ensure_ascii=False), encoding="utf-8")
            widths[sample] = render.measure(CHROME, build(path, self.folder)).width
        self.assertEqual(widths[""], widths[None])
        self.assertGreater(widths["Расчеты"], widths[None])

    def test_command_bar_row_with_right_button(self):
        """Строка с командной панелью и кнопкой «Право» не ужимается по содержимому: панель берет остаток строки,
        кнопки не уходят в «Еще» (ПТУ БП с «Показать скрытые», 02.11.2026)."""
        buttons = [{"type": "Button", "name": f"Кнопка{index}", "title": f"Команда {index}",
                    "commandName": f"Form.Command.Команда{index}"} for index in range(5)]
        model = {"version": 1, "form": {"title": "Панель", "width": 120, "items": [
            {"type": "UsualGroup", "name": "Строка", "group": "AlwaysHorizontal", "items": [
                {"type": "CommandBar", "name": "Панель", "items": buttons},
                {"type": "Button", "name": "Справа", "title": "›", "commandName": "Form.Command.Справа",
                 "groupHorizontalAlign": "Right"}]},
            {"type": "InputField", "name": "Поле"}]}}
        path = self.folder / "panel-row.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        layout = render.measure(CHROME, build(path, self.folder))
        self.assertEqual(layout.errors, [])
        self.assertEqual([note for note in layout.notes if "Еще" in note], [])

    def test_style_colors_from_styles(self):
        """Цвет стиля рисуется значением из `styles`; без значения - без цвета."""
        model = {"version": 1, "styles": {"ГиперссылкаЦвет": "#1C55AE", "FormBackColor": "#FFFFFF"}, "form": {
            "title": "Цвета", "items": [
                {"type": "LabelDecoration", "name": "Стиль", "title": "СтильКонфигурации", "textColor": "style:ГиперссылкаЦвет"},
                {"type": "LabelDecoration", "name": "Пусто", "title": "БезЗначения", "textColor": "style:ReportLineColor"},
                {"type": "LabelDecoration", "name": "Веб", "title": "ВебВнеCSS", "textColor": "cream"},
                {"type": "LabelDecoration", "name": "Разметка", "formatted": True,
                 "title": "<color style:ГиперссылкаЦвет>РазметкаСтиля</>"}]}}
        path = self.folder / "styles.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        url = build(path, self.folder).resolve().as_uri() + "#" + render.state_hash()
        dom = render.run_chrome(CHROME, ["--virtual-time-budget=3000", "--dump-dom", url])

        dom = re.sub(r"<script.*?</script>", "", dom, flags=re.S)

        def color_of(text):
            found = re.search(r"<[^<>]*>" + text + "<", dom)
            self.assertIsNotNone(found, text)
            color = re.search(r"(?<![-\w])color: ?([^;\"]+)", found.group(0))
            return color.group(1).lower() if color else None

        self.assertIn(color_of("СтильКонфигурации"), ("rgb(28, 85, 174)", "#1c55ae"))
        self.assertIn(color_of("РазметкаСтиля"), ("rgb(28, 85, 174)", "#1c55ae"))
        self.assertIn(color_of("ВебВнеCSS"), ("rgb(255, 251, 240)", "#fffbf0"))
        self.assertIsNone(color_of("БезЗначения"))

    def test_stage_2b_properties(self):
        """Свойства оформления: окно без заголовка и крестика, таблица без линий с чередованием, режим выбора из
        списка и время без календаря."""
        model = {"version": 1, "form": {"title": "Окно", "showTitle": False, "showCloseButton": False, "items": [
            {"type": "InputField", "name": "Режим", "dataType": "string", "listChoiceMode": True, "createButton": True},
            {"type": "InputField", "name": "Время", "dataType": "date", "dateFractions": "Time"},
            {"type": "Table", "name": "Строки", "horizontalLines": False, "verticalLines": False,
             "useAlternationRowColor": True, "items": [{"type": "InputField", "name": "Колонка"}],
             "sample": [["а"], ["б"]]}]}}
        path = self.folder / "stage2b.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        url = build(path, self.folder).resolve().as_uri() + "#" + render.state_hash()
        dom = re.sub(r"<script.*?</script>", "", render.run_chrome(CHROME, ["--virtual-time-budget=3000", "--dump-dom", url]),
                     flags=re.S)
        caption = re.search(r'<div class="fm-caption">(.*?)</div>\s*<div class="fm-body', dom, re.S).group(1)
        self.assertNotIn("Окно", caption)
        self.assertEqual(caption.count("fm-caption-icon"), 2, "без навигации и крестика - ссылка и меню")
        self.assertIn("fm-no-hlines", dom)
        self.assertIn("fm-alternate", dom)
        field = re.search(r'data-name="Режим".*?</div></div>', dom, re.S).group(0)
        self.assertEqual(re.findall(r'class="fm-input-btn">([^<]*)<', field), ["▾", "+"])
        time = re.search(r'data-name="Время".*?</div></div>', dom, re.S).group(0)
        self.assertNotIn("fm-input-btn", time, "время - без календаря")

    def dump(self, model: dict, name: str) -> str:
        path = self.folder / f"{name}.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        url = build(path, self.folder).resolve().as_uri() + "#" + render.state_hash()
        dom = render.run_chrome(CHROME, ["--virtual-time-budget=3000", "--dump-dom", url])
        return re.sub(r"<script.*?</script>|<style.*?</style>", "", dom, flags=re.S)

    def element(self, dom: str, name: str) -> str:
        """Разметка элемента: от первого тега с его `data-name` до его бирки имени."""
        found = re.search(r'<[^<>]*data-name="' + name + r'"[^<>]*>.*?fm-name-tag">' + name + "<", dom, re.S)
        self.assertIsNotNone(found, name)
        return found.group(0)

    def test_boolean_input_field(self):
        """Булево поле ввода: «▾» без кнопки выбора, без образца - «Нет», образец и колонка - по
        формату `БИ` / `БЛ`."""
        model = {"version": 1, "form": {"title": "Булево", "items": [
            {"type": "InputField", "name": "Пусто", "dataType": "boolean"},
            {"type": "InputField", "name": "Включено", "dataType": "boolean", "sample": True, "format": "БЛ=Выкл; БИ=Вкл"},
            {"type": "Table", "name": "Строки", "items": [
                {"type": "InputField", "name": "Признак", "dataType": "boolean", "format": "БЛ=Нет; БИ=Ага"}],
             "sample": [[True], [False]]}]}}
        dom = self.dump(model, "boolean")
        empty = self.element(dom, "Пусто")
        self.assertEqual(re.findall(r'class="fm-input-btn">([^<]*)<', empty), ["▾"])
        self.assertIn(">Нет<", empty)
        self.assertIn("fm-droplist", empty)
        self.assertIn(">Вкл<", self.element(dom, "Включено"))
        cells = re.findall(r">(Ага|Нет)<", self.element(dom, "Строки"))
        self.assertEqual(cells[:2], ["Ага", "Нет"])

    def test_choice_list_presentation(self):
        """Список выбора с представлением: пункт рисуется представлением, без него - значением;
        пример значения называет пункт любым из двух."""
        choices = [{"value": "1", "presentation": "Один"}, "2"]
        model = {"version": 1, "form": {"title": "Список", "items": [
            {"type": "RadioButtonField", "name": "Переключатель", "choiceList": choices, "sample": "1"},
            {"type": "InputField", "name": "Поле", "choiceList": choices, "sample": "1"}]}}
        dom = self.dump(model, "choices")
        radio = self.element(dom, "Переключатель")
        self.assertEqual(re.findall(r'fm-radio[^"]*"></span><span>([^<]*)<', radio), ["Один", "2"])
        self.assertIn('fm-radio fm-on"></span><span>Один<', radio)
        self.assertIn(">Один<", self.element(dom, "Поле"))

    def test_title_by_data_path(self):
        """Заголовок без своего: от реквизита по пути, иначе последнее имя пути, без пути - имя."""
        model = {"version": 1, "form": {"title": "Заголовки", "items": [
            {"type": "InputField", "name": "ПолеКонтрагент", "dataPath": "Объект.Контрагент"},
            {"type": "InputField", "name": "ПолеИНН", "dataPath": "Объект.ИНН"},
            {"type": "InputField", "name": "БезПути"}]},
            "attributes": [{"name": "Объект", "valueType": "DocumentObject.Заказ", "main": True}],
            "types": {"Document.Заказ": {"attributes": [
                {"name": "Контрагент", "title": "Покупатель", "valueType": "CatalogRef.Контрагенты"}]}}}
        dom = self.dump(model, "titles")
        for name, title in (("ПолеКонтрагент", "Покупатель"), ("ПолеИНН", "ИНН"), ("БезПути", "Без пути")):
            self.assertIn(">" + title + ":<", self.element(dom, name), name)

    def test_picture_and_label_field_border(self):
        """Рамка полей: поле картинки - одинарная по умолчанию цветом рамки поля, «Без рамки» - нет;
        надпись - без рамки по умолчанию, заданная рамка - заданным цветом."""
        model = {"version": 1, "form": {"title": "Рамки", "items": [
            {"type": "PictureField", "name": "Картинка", "width": 2, "height": 1, "horizontalStretch": False},
            {"type": "PictureField", "name": "БезРамки", "border": "WithoutBorder", "horizontalStretch": False},
            {"type": "LabelField", "name": "Надпись", "sample": "текст"},
            {"type": "LabelField", "name": "НадписьВРамке", "sample": "текст", "border": "Single", "borderColor": "#FF0000"}]}}
        dom = self.dump(model, "borders")
        picture = re.search(r"<[^<>]*>", self.element(dom, "Картинка")).group(0)
        self.assertIn("border: 1px solid var(--border)", picture)
        self.assertIn("width: 20px", picture)
        self.assertNotIn("fm-bordered", self.element(dom, "БезРамки"))
        self.assertNotIn("fm-bordered", self.element(dom, "Надпись"))
        self.assertIn("border: 1px solid rgb(255, 0, 0)", self.element(dom, "НадписьВРамке"))

    def test_values_picture_cell(self):
        """Картинка значений: полоса квадратных ячеек по высоте, значение выбирает ячейку - в поле
        и в колонке таблицы; номер за полосой - пусто."""
        strip = ('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="16">'
                 '<rect width="48" height="16" fill="#0a0"/></svg>')
        uri = "data:image/svg+xml;base64," + base64.b64encode(strip.encode("utf-8")).decode("ascii")
        picture = "CommonPicture.Состояния"
        model = {"version": 1, "form": {"title": "Картинка значений", "items": [
            {"type": "PictureField", "name": "Первая", "valuesPicture": picture, "width": 2, "height": 1},
            {"type": "PictureField", "name": "Третья", "valuesPicture": picture, "sample": "2", "width": 2, "height": 1},
            {"type": "PictureField", "name": "Истина", "valuesPicture": picture, "sample": "true", "width": 2, "height": 1},
            {"type": "PictureField", "name": "ЗаПолосой", "valuesPicture": picture, "sample": "5", "width": 2, "height": 1},
            {"type": "Table", "name": "Список", "items": [
                {"type": "PictureField", "name": "Состояние", "valuesPicture": picture}], "sample": [[1]]}]},
            "pictures": {picture: uri}}
        dom = self.dump(model, "values-picture")

        def window(name):
            found = re.search(r'<span class="fm-values-picture"([^>]*)><img class="fm-img"([^>]*)>', self.element(dom, name))
            self.assertIsNotNone(found, name)
            return found.group(1), found.group(2)

        self.assertIn("margin-left: 0px", window("Первая")[1])
        self.assertIn("height: 16px; width: 16px", window("Первая")[0])
        self.assertIn("margin-left: -32px", window("Третья")[1])
        self.assertIn("margin-left: -16px", window("Истина")[1])
        self.assertIn("visibility: hidden", window("ЗаПолосой")[0])
        self.assertIn("margin-left: -16px", window("Список")[1])

    def test_button_title_by_command(self):
        """Кнопка без своего заголовка (владелец 04.11.2026): стандартная команда формы и таблицы - заголовок
        платформы, общая команда и команда формы вне `commands` - имя команды по словам, а не имя кнопки."""
        model = {"version": 1, "form": {"title": "Кнопки", "items": [
            {"type": "Button", "name": "КнопкаА", "commandName": "Form.StandardCommand.Close"},
            {"type": "Button", "name": "КнопкаБ", "commandName": "Form.Item.Товары.StandardCommand.Add"},
            {"type": "Button", "name": "КнопкаВ", "commandName": "CommonCommand.ОтправитьПисьмо"},
            {"type": "Button", "name": "КнопкаГ", "commandName": "Form.Command.ЗаполнитьПоОстаткам"},
            {"type": "Table", "name": "Товары", "items": [{"type": "InputField", "name": "Колонка"}]}]}}
        dom = self.dump(model, "button-titles")
        for name, title in (("КнопкаА", "Закрыть"), ("КнопкаБ", "Добавить"), ("КнопкаВ", "Отправить письмо"),
                            ("КнопкаГ", "Заполнить по остаткам")):
            self.assertIn('class="fm-button-text">' + title + "<", self.element(dom, name), name)

    def test_font_name_size_strikeout(self):
        """Шрифт: имя и размер абсолютного шрифта, зачеркнутый; размер - от 10 пт «Такси»."""
        model = {"version": 1, "form": {"title": "Шрифты", "items": [
            {"type": "InputField", "name": "Поле", "sample": "ЗначениеПоля",
             "font": {"faceName": "Courier New", "height": 15, "strikeout": True, "underline": True}},
            {"type": "Button", "name": "Кнопка", "title": "ТекстКнопки", "commandName": "Form.Command.Кнопка",
             "font": {"height": 8, "bold": True}}]}}
        dom = self.dump(model, "fonts")
        value = re.search(r'<span class="fm-input-value"[^>]*>ЗначениеПоля<', self.element(dom, "Поле")).group(0)
        self.assertIn("Courier New", value)
        self.assertIn("font-size: calc(var(--font-size) * 1.5)", value)
        self.assertIn("underline line-through", value)
        button = re.search(r"<[^<>]*>", self.element(dom, "Кнопка")).group(0)
        self.assertIn("font-size: calc(var(--font-size) * 0.8)", button)
        self.assertIn("font-weight: bold", button)

    def test_column_header_footer_cells(self):
        """Свойства колонки: шапка, подвал, гиперссылка и автовысота ячейки."""
        model = {"version": 1, "form": {"title": "Колонки", "items": [
            {"type": "Table", "name": "Строки", "footer": True, "items": [
                {"type": "InputField", "name": "Сумма", "title": "ШапкаСумма", "dataType": "number",
                 "headerHorizontalAlign": "Right", "headerBackColor": "#FF0000", "footerText": "ПодвалСумма",
                 "footerPicture": "CommonPicture.Итог", "footerHorizontalAlign": "Center",
                 "footerBackColor": "#00FF00", "footerTextColor": "#0000FF", "footerFont": {"bold": True}},
                {"type": "InputField", "name": "Скрытый", "footerText": "НеВПодвале", "showInFooter": False},
                {"type": "LabelField", "name": "Ссылка", "cellHyperlink": True},
                {"type": "InputField", "name": "Описание", "autoCellHeight": True}],
             "sample": [[1, "а", "ЗначениеСсылкой", "ДлинноеОписание"]]}]}}
        dom = self.dump(model, "columns")
        header = self.element(dom, "Сумма")
        self.assertIn("ШапкаСумма", header)
        self.assertRegex(header, r"background-color: (rgb\(255, 0, 0\)|#ff0000)")
        self.assertIn("text-align: right", header)
        footer = re.search(r'<div class="fm-tf"[^>]*><span class="fm-tf-picture".*?</div>', dom, re.S).group(0)
        self.assertLess(footer.index("fm-picture-stub"), footer.index("ПодвалСумма"), "картинка подвала - перед текстом")
        self.assertIn("text-align: center", footer)
        self.assertRegex(footer, r"(?<![-\w])color: (rgb\(0, 0, 255\)|#0000ff)")
        self.assertRegex(footer, r"background-color: (rgb\(0, 255, 0\)|#00ff00)")
        self.assertIn("font-weight: bold", footer)
        self.assertNotIn("НеВПодвале", dom, "колонка с «Отображать в подвале» = Ложь - пустая ячейка подвала")
        self.assertIn('<span class="fm-hyperlink">ЗначениеСсылкой<', dom)
        self.assertIn('<span class="fm-td-wrap">ДлинноеОписание<', dom)

    def test_button_takes_form_command(self):
        """Кнопка команды формы без своих заголовка, картинки, отображения - от команды."""
        model = {"version": 1, "commands": [
            {"name": "Проверить", "title": "ЗаголовокКоманды", "picture": "CommonPicture.Проверка",
             "representation": "PictureAndText"},
            {"name": "БезЗаголовка"}], "form": {"title": "Команды", "items": [
                {"type": "Button", "name": "КнопкаПроверить", "commandName": "Form.Command.Проверить"},
                {"type": "Button", "name": "КнопкаСвоя", "title": "СвойЗаголовок", "representation": "Text",
                 "commandName": "Form.Command.Проверить"},
                {"type": "Button", "name": "КнопкаБезЗаголовка", "commandName": "Form.Command.БезЗаголовка"}]}}
        dom = self.dump(model, "commands")
        inherited = self.element(dom, "КнопкаПроверить")
        self.assertIn(">ЗаголовокКоманды<", inherited)
        self.assertIn("fm-picture-stub", inherited, "картинка команды")
        own = self.element(dom, "КнопкаСвоя")
        self.assertIn(">СвойЗаголовок<", own)
        self.assertNotIn("fm-picture-stub", own, "отображение кнопки «Текст» сильнее команды")
        # Команда без заголовка - имя команды по словам (model.md, «Команды формы»), а не имя кнопки
        self.assertIn(">Без заголовка<", self.element(dom, "КнопкаБезЗаголовка"))

    def test_unknown_action_is_error(self):
        layout = render.measure(CHROME, build(VITRINA, self.folder), actions=["tab:НетТакой:Закладки"])
        self.assertTrue(layout.errors)

    def test_page_state_and_tabs_list(self):
        html_path = build(VITRINA, self.folder, {"Страницы": "СтраницаТаблицы"})
        layout = render.measure(CHROME, html_path)
        self.assertEqual(layout.dom["currentPages"]["Страницы"], "СтраницаТаблицы")
        states = render.tab_states(layout, {})
        names = {(pages, page) for pages, page, _ in states}
        self.assertIn(("Страницы", "СтраницаПоля"), names)
        nested = [state for pages, page, state in states if page == "СтраницаСлеваПрочее"]
        self.assertEqual(nested, [{"Страницы": "СтраницаГруппы", "СтраницыСлева": "СтраницаСлеваПрочее"}])

    def test_render_command_png(self):
        result = subprocess.run([sys.executable, str(CLI), "render", str(EXAMPLES / "zakaz-pokupatelya.json"),
                                 "-o", str(self.folder / "cli"), "--png"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pngs = sorted(path.name for path in (self.folder / "cli").glob("*.png"))
        # В примере есть примечание (кнопка «Подбор») - еще снимок с номерами
        self.assertEqual(pngs, ["zakaz-pokupatelya.png", "zakaz-pokupatelya__ГруппаСтраницы_ГруппаДополнительно.png",
                                "zakaz-pokupatelya__примечания.png"])
        with open(self.folder / "cli" / "zakaz-pokupatelya.png", "rb") as file:
            self.assertEqual(file.read(8), b"\x89PNG\r\n\x1a\n")


class CellTexts:
    """Тексты ячеек таблицы из DOM страницы: [строка][колонка] - текст и есть ли картинка значений, число ли."""

    CELL = re.compile(r'<div class="(fm-td[^"]*)"[^>]*>(.*?)</div>(?=<div class="fm-td|<div class="fm-t[hf]|</div>)', re.S)

    @classmethod
    def of(cls, html_path: Path, flags: list = None) -> list:
        url = html_path.resolve().as_uri() + "#" + render.state_hash(flags=flags)
        dom = render.run_chrome(CHROME, ["--window-size=2400,3000", "--virtual-time-budget=5000", "--dump-dom", url])
        cells = []
        for classes, inner in cls.CELL.findall(dom):
            text = re.sub(r"<[^>]+>", " ", inner)
            cells.append({"text": " ".join(text.split()), "picture": "fm-values-picture" in inner,
                          "number": "fm-number" in classes.split()})
        return cells


@unittest.skipUnless(CHROME, "Chrome не найден")
class TableCellsTest(unittest.TestCase):
    """Ячейки примера (обкатка): правки не сдвигают значения, картинка «в ячейке» - картинкой."""

    def table(self, items, sample):
        return {"version": 1, "form": {"title": "Ф", "formKind": "DataProcessorForm", "items": [
            {"type": "Table", "name": "Т", "items": items, "sample": sample}]}}

    def test_diff_mode_keeps_cells_in_place(self):
        """Тень перенесенной и удаленная колонка в режиме «Правки» ячейку примера не занимают."""
        from fmlib.diff import compare
        column = lambda name: {"type": "InputField", "name": name}
        before = self.table([column("А"), column("Б"), column("В"), column("Г")], [["а", "б", "в", "г"]])
        # «Б» удалена, «Г» перенесена в начало: в дереве правок на старых местах - удаленная «Б» и тень «Г»
        after = self.table([column("Г"), column("А"), column("В")], [["г", "а", "в"]])
        dictionary = load_dictionary(DICTIONARY_PATH)
        folder = Path(temp_dir(prefix="formmockup-cells-"))
        html_path = folder / "cells.html"
        html_path.write_text(render.build_html(after, dictionary, "Ф", None, before, compare(before, after, dictionary)),
                             encoding="utf-8")
        texts = [cell["text"] for cell in CellTexts.of(html_path, ["mode=diff"])]
        # Колонки дерева правок: Г, А, Б (удалена), В, Г (было) - значения «стало» под своими колонками
        self.assertEqual(texts, ["г", "а", "", "в", ""])
        self.assertEqual([cell["text"] for cell in CellTexts.of(html_path, ["mode=after", "nodiff"])], ["г", "а", "в"])

    def test_picture_in_cell(self):
        """Колонка «в ячейке» с картинкой значений: кадр картинки и текст рядом, выравнивание - по тексту."""
        strip = ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16"><rect width="16" height="16" fill="red"/>'
                 '<rect x="16" width="16" height="16" fill="blue"/></svg>')
        model = self.table([{"type": "ColumnGroup", "name": "Группа", "group": "InCell", "items": [
            {"type": "PictureField", "name": "Вид", "valuesPicture": "CommonPicture.Виды"},
            {"type": "InputField", "name": "Имя"}]}], [["1", "Товары"], ["0", "Услуги"]])
        model["pictures"] = {"CommonPicture.Виды": "data:image/svg+xml;base64," + base64.b64encode(strip.encode()).decode()}
        folder = Path(temp_dir(prefix="formmockup-cells-"))
        html_path = folder / "incell.html"
        html_path.write_text(render.build_html(model, load_dictionary(DICTIONARY_PATH), "Ф"), encoding="utf-8")
        cells = CellTexts.of(html_path)
        self.assertEqual([(cell["text"], cell["picture"], cell["number"]) for cell in cells],
                         [("Товары", True, False), ("Услуги", True, False)], "не «1, Товары» справа, как число")


@unittest.skipUnless(CHROME, "Chrome не найден")
class NotesTest(unittest.TestCase):
    """Номера примечаний: на макете - те же, что в колонке «№» `table`; отдельный снимок `render`."""

    STALO = EXAMPLES / "pravki" / "zakaz-pokupatelya-stalo.json"

    def table_numbers(self, path: Path) -> dict:
        result = subprocess.run([sys.executable, str(CLI), "table", str(path)], capture_output=True, text=True,
                                encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line for line in result.stdout.splitlines()[2:] if line.split("|")[1].strip()]
        return {(row.split("`")[1] if "`" in row else "Форма"): int(row.split("|")[1]) for row in rows}

    def test_numbers_like_table(self):
        folder = Path(temp_dir(prefix="formmockup-notes-"))
        html_path = build(self.STALO, folder)
        shown = render.measure(CHROME, html_path, flags=["notes"])
        self.assertEqual(shown.errors, [])
        self.assertEqual(dict(shown.dom["noteFrames"]), self.table_numbers(self.STALO))
        self.assertEqual(render.measure(CHROME, html_path).dom["noteFrames"], [], "без notes номеров нет")

    def test_form_and_other_page(self):
        """Примечание формы - номер у окна; элемента на другой закладке - номер у ярлыка и отдельный снимок."""
        model = load_model(EXAMPLES / "zakaz-pokupatelya.json")
        model["form"]["note"] = "форма открывается из списка"
        folder = Path(temp_dir(prefix="formmockup-notes-"))
        source = folder / "zakaz.json"

        def find(node, name):
            for child in ([node["commandBar"]] if "commandBar" in node else []) + node.get("items", []):
                if child.get("name") == name:
                    return child
                found = find(child, name)
                if found:
                    return found
            return None

        find(model["form"], "Склад")["note"] = "склад по умолчанию из настроек"
        source.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        numbers = self.table_numbers(source)
        layout = render.measure(CHROME, build(source, folder), flags=["notes"])
        self.assertEqual(layout.errors, [])
        self.assertEqual(dict(layout.dom["noteFrames"]), numbers)
        self.assertEqual(numbers["Форма"], 1)
        out = folder / "out"
        result = subprocess.run([sys.executable, str(CLI), "render", str(source), "-o", str(out), "--png"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        made = sorted(path.name for path in out.glob("*__примечания*.png"))
        self.assertEqual(made, ["zakaz__примечания.png", "zakaz__примечания__ГруппаСтраницы_ГруппаДополнительно.png"])

    def test_no_notes_no_snapshot(self):
        folder = temp_dir(prefix="formmockup-notes-")
        result = subprocess.run([sys.executable, str(CLI), "render", str(EXAMPLES / "spisok-zakazov.json"), "-o", folder,
                                 "--png"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(Path(folder).glob("*__примечания*.png")), [])


class RenderCommandTest(unittest.TestCase):
    def run_render(self, model: Path, *extra, env=None):
        folder = temp_dir(prefix="formmockup-cli-")
        return subprocess.run([sys.executable, str(CLI), "render", str(model), "-o", folder, *extra],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def test_model_issues_block_render(self):
        result = self.run_render(ROOT / "tests" / "fixtures" / "check" / "duplicate-name.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate-name", result.stdout)
        self.assertNotIn("HTML:", result.stdout)

    def test_layout_rules_do_not_block_render(self):
        """Правила вёрстки - замечание, а не запрет: импортированную форму рисуем как есть."""
        env = dict(os.environ, **{render.CHROME_ENV: "/нет/такого/chrome"})
        result = self.run_render(ROOT / "tests" / "fixtures" / "check" / "too-many-items.json", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("too-many-items", result.stdout)
        self.assertIn("HTML:", result.stdout)

    def test_no_chrome_png_is_code_3(self):
        env = dict(os.environ, **{render.CHROME_ENV: "/нет/такого/chrome"})
        result = self.run_render(EXAMPLES / "spisok-zakazov.json", "--png", env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn("HTML:", result.stdout)
        self.assertIn("/нет/такого/chrome", result.stderr)

    def test_no_chrome_without_png_is_ok(self):
        env = dict(os.environ, **{render.CHROME_ENV: "/нет/такого/chrome"})
        result = self.run_render(EXAMPLES / "spisok-zakazov.json", env=env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("не проверены", result.stdout)


@unittest.skipUnless(CHROME, "Chrome не найден")
class CommandBarTest(unittest.TestCase):
    """Командные панели: стандартная команда, поставленная кнопкой, автозаполнением не
    повторяется; кнопка стандартной команды таблицы без своей картинки - со значком кнопки автозаполнения; группа кнопок
    с источником «Таблица» - команды таблицы на панели и в «Еще»."""

    MODEL = {"version": 1, "form": {"formKind": "DocumentObjectForm", "title": "Панели", "commandBar": {
        "type": "AutoCommandBar", "name": "ФормаКоманднаяПанель", "items": [
            {"type": "Button", "name": "СвояЗаписать", "commandName": "Form.StandardCommand.Write", "title": "Сохранить"}]},
        "items": [
            {"type": "CommandBar", "name": "Панель", "items": [
                {"type": "ButtonGroup", "name": "ГруппаТоваров", "commandSource": "Item.Товары"}]},
            {"type": "Table", "name": "Товары", "commandBar": {"type": "AutoCommandBar", "name": "ТоварыПанель", "items": [
                {"type": "Button", "name": "СвояДобавить", "commandName": "Form.Item.Товары.StandardCommand.Add",
                 "title": "Добавить строку"}]},
             "items": [{"type": "InputField", "name": "ТоварыКолонка"}]},
            {"type": "Table", "name": "Строки", "commandBar": {"type": "AutoCommandBar", "name": "СтрокиПанель",
                                                               "autoFill": False, "items": [
                {"type": "Button", "name": "Вверх", "commandName": "Form.Item.Строки.StandardCommand.MoveUp"}]},
             "items": [{"type": "InputField", "name": "СтрокиКолонка"}]}]}}

    def setUp(self):
        self.folder = Path(temp_dir(prefix="formmockup-bars-"))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def dom(self, actions=None) -> str:
        path = self.folder / "bars.json"
        path.write_text(json.dumps(self.MODEL, ensure_ascii=False), encoding="utf-8")
        url = build(path, self.folder).resolve().as_uri() + "#" + render.state_hash(static=False, actions=actions)
        dom = render.run_chrome(CHROME, ["--virtual-time-budget=3000", "--dump-dom", url])
        return re.sub(r"<script.*?</script>|<style.*?</style>", "", dom, flags=re.S)

    def test_placed_standard_command_not_repeated(self):
        dom = self.dom()
        self.assertNotIn('data-command="StandardCommand.Write"', dom, "«Записать» - только своей кнопкой")
        self.assertIn('data-command="StandardCommand.PostAndClose"', dom)
        self.assertEqual(dom.count('data-command="StandardCommand.Add"'), 1,
                         "«Добавить» таблицы - своей кнопкой; автоматическая - только в группе с источником")
        self.assertIn("Добавить строку", dom)

    def test_standard_command_icon(self):
        dom = self.dom()
        button = re.search(r'<span class="([^"]*)" data-command="Form\.Item\.Строки\.StandardCommand\.MoveUp".*?</span>',
                           dom, re.S)
        self.assertIsNotNone(button)
        self.assertIn("fm-icon-only", button.group(1), "в панели при «Авто» - значок, как у кнопки автозаполнения")
        self.assertRegex(button.group(0), r"<svg|<img")

    def test_table_source_group(self):
        dom = self.dom()
        group = re.search(r'data-name="ГруппаТоваров".*?(?=data-name="Товары")', dom, re.S)
        self.assertIsNotNone(group)
        self.assertIn('data-command="StandardCommand.Add"', group.group(0))
        self.assertIn('data-command="StandardCommand.MoveUp"', group.group(0))
        menu = self.dom(["more:Панель"])
        found = re.search(r'class="fm-menu".*', menu, re.S)
        self.assertIsNotNone(found, "у панели с группой источника - «Еще»")
        self.assertIn("Скопировать", found.group(0), "команды таблицы, не поставленные кнопками, - в «Еще»")


@unittest.skipUnless(CHROME, "Chrome не найден")
class RenderFixesTest(unittest.TestCase):
    """Ошибки рендера: найденные на макете закладки «Наборы» и подсказка у флажка (10.11.2026)."""

    def setUp(self):
        self.folder = Path(temp_dir(prefix="formmockup-dev203-"))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def dom(self, model: dict) -> str:
        path = self.folder / "model.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        url = build(path, self.folder).resolve().as_uri() + "#" + render.state_hash()
        dom = render.run_chrome(CHROME, ["--virtual-time-budget=3000", "--dump-dom", url])
        return re.sub(r"<script.*?</script>|<style.*?</style>", "", dom, flags=re.S)

    def test_source_group_skips_commands_of_same_bar(self):
        """Группа с источником «Таблица» не повторяет команды, поставленные кнопками соседней группы той же панели:
        стрелки - один раз."""
        prefix = "Form.Item.Наборы.StandardCommand."
        model = {"version": 1, "form": {"formKind": "DataProcessorForm", "title": "Наборы", "items": [
            {"type": "Table", "name": "Наборы", "commandBar": {"type": "AutoCommandBar", "name": "НаборыПанель",
                                                               "autoFill": False, "items": [
                {"type": "ButtonGroup", "name": "Стрелки", "items": [
                    {"type": "Button", "name": "Вверх", "commandName": prefix + "MoveUp"},
                    {"type": "Button", "name": "Вниз", "commandName": prefix + "MoveDown"}]},
                {"type": "ButtonGroup", "name": "ВсеДействия", "commandSource": "Item.Наборы"}]},
             "items": [{"type": "InputField", "name": "НаборыИмя"}]}]}}
        dom = self.dom(model)
        bar = re.search(r'data-name="НаборыПанель".*?(?=class="fm-table-grid)', dom, re.S)
        self.assertIsNotNone(bar)
        self.assertEqual(len(re.findall(r'data-command="[^"]*StandardCommand\.MoveUp"', bar.group(0))), 1,
                         "«Вверх» - только кнопкой группы «Стрелки»")
        self.assertIn('data-command="StandardCommand.Add"', bar.group(0), "неразмещенное «Добавить» - в группе")

    def test_tree_first_column_holds_indent(self):
        """Первая колонка дерева не уже содержимого с отступом уровня: узкая колонка-флажок не отдает отступ
        соседней колонке."""
        model = {"version": 1, "form": {"formKind": "DataProcessorForm", "title": "Дерево", "items": [
            {"type": "Table", "name": "Дерево", "representation": "Tree", "items": [
                {"type": "CheckBoxField", "name": "ДеревоФлаг", "titleLocation": "None",
                 "headerPicture": "StdPicture.PrintImmediately"},
                {"type": "InputField", "name": "ДеревоИмя"}],
             "sample": [["true", "Родитель"], ["true", "Подчиненный"]]}]}}
        dom = self.dom(model)
        grid = re.search(r'class="fm-table-grid"[^>]*style="[^"]*grid-template-columns: ([^;"]+)', dom)
        self.assertIsNotNone(grid)
        self.assertTrue(grid.group(1).startswith("minmax(max-content,"), grid.group(1))

    def test_checkbox_tooltip_beside_title(self):
        """Подсказка «Отображать снизу / сверху / справа» у флажка: текст не в ширину квадрата, заголовок справа -
        рядом с квадратом, не на тексте подсказки (снимок 1С владельца 10.11.2026: строка «квадрат + заголовок»,
        текст под ней от левого края квадрата)."""
        tip = "При включении флага в мобильном приложении будет отображаться отдельный раздел настроек"

        def flag(name, representation, **extra):
            return dict({"type": "CheckBoxField", "name": name, "title": "Использовать отдельный раздел",
                         "dataPath": name, "toolTip": tip, "toolTipRepresentation": representation}, **extra)

        def alone(item):
            return {"type": "UsualGroup", "name": "Группа" + item["name"], "showTitle": False, "items": [item]}

        model = {"version": 1, "form": {"formKind": "DataProcessorForm", "title": "Подсказка", "items": [
            alone(flag("Снизу", "ShowBottom", titleLocation="Right")),
            alone(flag("Сверху", "ShowTop", titleLocation="Right")),
            alone(flag("Справа", "ShowRight", titleLocation="Right")),
            alone(flag("Слева", "ShowBottom")),
            alone({"type": "RadioButtonField", "name": "Переключатель", "title": "Режим", "dataPath": "Режим",
                   "choiceList": ["Да", "Нет"], "toolTip": tip, "toolTipRepresentation": "ShowBottom"})]}}
        path = self.folder / "tooltip.json"
        path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        layout = render.measure(CHROME, build(path, self.folder))
        self.assertEqual(layout.errors, [])
        found = layout.dom["tooltips"]
        for name in ("Снизу", "Сверху", "Справа", "Слева", "Переключатель"):
            self.assertIn(name, found)
        # Заголовок справа: строка «квадрат + заголовок», заголовок на уровне квадрата
        for name in ("Снизу", "Сверху", "Справа"):
            box, title = found[name]["control"], found[name]["title"]
            self.assertLess(abs((title[1] + title[3]) - (box[1] + box[3])), 6, (name, found[name]))
            self.assertGreater(title[0], box[0], (name, found[name]))
        below, above = found["Снизу"], found["Сверху"]
        self.assertGreaterEqual(below["tip"][1], below["title"][3], below)
        self.assertLessEqual(above["tip"][3], above["title"][1], above)
        for name in ("Снизу", "Сверху"):
            self.assertEqual(found[name]["tip"][0], found[name]["control"][0], found[name])
        right = found["Справа"]
        self.assertGreaterEqual(right["tip"][0], right["title"][2], right)
        # Текст снизу не в ширину квадрата или списка вариантов: строка - не одно слово
        for name in ("Снизу", "Сверху", "Слева", "Переключатель"):
            frame = found[name]["tip"]
            self.assertGreater(frame[2] - frame[0], 250, (name, frame))


if __name__ == "__main__":
    unittest.main()
