"""Импорт формы из XML.

Корпус - формы фикстур `fixtures/import`. Внешние корпуса (типовые и свои конфигурации) -
по переменным окружения, на машине, где они есть:

- `FORMMOCKUP_CORPUS` - корни исходников (`.../src`) через `os.pathsep`: каждая форма
  импортируется без падения, по схеме и без нераспознанного;
- `FORMMOCKUP_PAIRS` - пара `<src EDT><os.pathsep><src выгрузки>` одной конфигурации:
  одна форма из двух форматов дает одну модель (сверка умолчаний форматов).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import DICTIONARY_PATH, SCHEMA_PATH, colors, render  # noqa: E402
from fmlib.dictionary import load_dictionary  # noqa: E402
from fmlib.importer import ImportFailure, import_form  # noqa: E402
from fmlib.import_designer import read as read_designer  # noqa: E402
from fmlib.metadata import clean_path, long_path, split_name  # noqa: E402
from fmlib.model import check  # noqa: E402
from fmlib.schema import SchemaValidator  # noqa: E402
from support import temp_dir  # noqa: E402

CLI = ROOT / "formmockup.py"
FIXTURES = ROOT / "tests" / "fixtures" / "import"
DESIGNER_FORM = FIXTURES / "designer" / "Catalogs" / "Партнеры" / "Forms" / "ФормаЭлемента" / "Ext" / "Form.xml"
# Исходники EDT фикстуры: справочник с формой элемента, витрина элементов, элемент стиля, общие картинки
EDT_SRC = FIXTURES / "edt"
CONTRACT_FORM = EDT_SRC / "Catalogs" / "_ДемоДоговоры" / "Forms" / "ФормаЭлемента" / "Form.form"
VITRINA_FORM = EDT_SRC / "DataProcessors" / "ВитринаЭлементов" / "Forms" / "Форма" / "Form.form"
VITRINA_MODEL = ROOT / "tests" / "fixtures" / "vitrina.json"


def nodes(model: dict) -> dict:
    """Все элементы модели по имени: (элемент, имя родителя)."""
    found = {}

    def walk(node, parent):
        bar = node.get("commandBar")
        if isinstance(bar, dict):
            found[bar["name"]] = (bar, parent)
            walk(bar, bar["name"])
        for item in node.get("items", []):
            found[item["name"]] = (item, parent)
            walk(item, item["name"])

    walk(model["form"], "Форма")
    return found


def corpus(*roots, pattern="Form.form"):
    for root in roots:
        yield from sorted(Path(root).rglob(pattern))


class FormatTest(unittest.TestCase):
    def test_not_xml(self):
        with self.assertRaises(ImportFailure) as error:
            import_form(FIXTURES / "not-xml.form")
        self.assertIn("не XML", str(error.exception))

    def test_not_form(self):
        with self.assertRaises(ImportFailure) as error:
            import_form(FIXTURES / "not-form.xml")
        self.assertIn("не форма 1С", str(error.exception))

    def test_cli_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "model.json"
            ok = subprocess.run([sys.executable, str(CLI), "import", str(DESIGNER_FORM), "-o", str(output)],
                                capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("Не распознано: FutureKindField", ok.stdout)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["form"]["formKind"], "CatalogObjectForm")
            self.assertNotIn(b"\r\n", output.read_bytes(), "модель - с LF на любой ОС")
            bad = subprocess.run([sys.executable, str(CLI), "import", str(FIXTURES / "not-form.xml"), "-o", str(output)],
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(bad.returncode, 2)

    def test_helpers(self):
        self.assertEqual(split_name("ДатаОтгрузки"), "Дата отгрузки")
        self.assertEqual(split_name("ИННКонтрагента"), "ИНН контрагента")
        self.assertEqual(split_name("УчитыватьВКаждойПозиции"), "Учитывать в каждой позиции")
        self.assertEqual(clean_path("~Список.Code~Список.Код"), "Список.Code")
        self.assertIsNone(clean_path("1/0:aea32152-69d4-44fd-8054-ec017c90f549"))


class DesignerTest(unittest.TestCase):
    """Выгрузка конфигуратора: умолчания платформы, метаданные `<Объект>.xml` рядом."""

    @classmethod
    def setUpClass(cls):
        cls.model, cls.report = import_form(DESIGNER_FORM)
        cls.items = nodes(cls.model)

    def item(self, name):
        return self.items[name][0]

    def test_schema(self):
        self.assertEqual(SchemaValidator.from_file(SCHEMA_PATH).validate(self.model), [])

    def test_title_chain(self):
        form = self.model["form"]
        self.assertEqual(form["title"], "Партнер")                                     # представление объекта
        self.assertEqual(self.item("Наименование")["title"], "Рабочее наименование")   # стандартный реквизит
        self.assertEqual(self.item("ИНН")["title"], "ИНН партнера")                    # синоним реквизита
        self.assertEqual(self.item("ОсновнойМенеджер")["title"], "Основной менеджер")  # синоним пуст - по имени
        self.assertEqual(self.item("Активен")["title"], "Партнер активен")             # реквизит формы
        self.assertEqual(self.item("Контакты")["title"], "Контактные лица")            # табличная часть
        self.assertEqual(self.item("КонтактыКонтактноеЛицо")["title"], "Контакт")     # колонка табличной части
        # Кнопка команды формы: заголовок - у команды, в кнопку не пишется
        self.assertNotIn("title", self.item("ОткрытьИсторию"))
        self.assertEqual(self.model["commands"][0]["title"], "Проверить контрагента")
        self.assertEqual(self.report.titles["metadata"], 5)

    def test_types(self):
        self.assertEqual(self.item("ОсновнойМенеджер")["dataType"], "ref")
        self.assertEqual(self.item("ДатаРегистрации")["dataType"], "date")
        self.assertEqual(self.item("КонтактыДоля")["dataType"], "number")
        # Перечисление: значения синонимами по порядку, без синонима - по имени
        self.assertEqual(self.item("ВидПартнера")["enumValues"], ["Покупатель", "Поставщик и покупатель"])

    def test_platform_defaults(self):
        group = self.item("ГруппаШапка")
        self.assertEqual(group["group"], "HorizontalIfPossible")
        self.assertEqual(group["representation"], "WeakSeparation")
        self.assertIs(group["showTitle"], False)
        self.assertIs(self.item("ДатаРегистрации")["visible"], False)
        self.assertNotIn("visible", self.item("ИНН"))
        self.assertNotIn("header", self.item("Контакты"))

    def test_kinds(self):
        self.assertEqual(self.item("Активен")["checkBoxType"], "Switch")
        self.assertIs(self.item("Сайт")["hyperlink"], True)
        label = self.item("Пояснение")
        self.assertEqual(label["title"], "Карточка <b>партнера</>")
        self.assertIs(label["formatted"], True)
        self.assertEqual(self.item("ОткрытьИсторию")["buttonType"], "Hyperlink")

    def test_command_bar(self):
        """«Справка» - только в «Еще», «Записать и закрыть» рендерер ставит сам по виду формы."""
        items = self.model["form"]["commandBar"]["items"]
        self.assertEqual([item["name"] for item in items], ["ФормаСправка", "ФормаПроверить"])
        self.assertEqual(items[0]["locationInCommandBar"], "InAdditionalSubmenu")
        self.assertNotIn("locationInCommandBar", items[1])

    def test_report(self):
        self.assertEqual(self.report.unknown, {"FutureKindField": ["НовыйВидПоля"]})
        self.assertEqual(self.item("НовыйВидПоля")["sourceType"], "FutureKindField")
        # Строка поиска таблицы - не колонка: в модель не попадает
        self.assertNotIn("КонтактыСтрокаПоиска", self.items)

    def test_attributes(self):
        """Реквизиты формы и состав типа основного реквизита: стандартный Ref - ссылка на сам
        объект, табличная часть - с колонками."""
        attributes = {item["name"]: item for item in self.model["attributes"]}
        self.assertEqual(attributes["Объект"], {"name": "Объект", "valueType": "CatalogObject.Партнеры", "main": True})
        self.assertEqual(attributes["Активен"]["title"], "Партнер активен")
        partner = self.model["types"]["Catalog.Партнеры"]
        fields = {item["name"]: item for item in partner["attributes"]}
        self.assertEqual(fields["Ref"]["valueType"], "CatalogRef.Партнеры")
        self.assertEqual(fields["ОсновнойМенеджер"]["valueType"], "CatalogRef.Пользователи")
        self.assertEqual([column["name"] for column in partner["tabularSections"][0]["columns"]], ["КонтактноеЛицо", "Доля"])
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        self.assertEqual([issue for issue in check(self.model, validator) if issue.code == "data-path"], [])


class EdtTest(unittest.TestCase):
    """EDT `Form.form`: умолчания модели EDT, метаданные `.mdo` объекта."""

    def test_vitrina_matches_manual_model(self):
        """Витрина из XML - то же дерево, что ручная модель, сверенная со снимками 1С."""
        model, report = import_form(VITRINA_FORM)
        manual = json.loads(VITRINA_MODEL.read_text(encoding="utf-8"))
        imported, expected = nodes(model), nodes(manual)
        # Командную панель таблицы ручная модель не описывает - она по умолчанию
        imported.pop("ТоварыКоманднаяПанель")
        self.assertEqual(list(imported), list(expected))
        for name, (node, parent) in expected.items():
            with self.subTest(name=name):
                self.assertEqual(imported[name][0]["type"], node["type"])
                self.assertEqual(imported[name][1], parent)
        for name in ("Выключатель", "Тумблер"):
            self.assertEqual(imported[name][0]["checkBoxType"], expected[name][0]["checkBoxType"])
        self.assertEqual(imported["Страницы"][0]["pagesRepresentation"], "TabsOnTop")
        self.assertEqual(report.unrecognized, 0)

    def test_attributes_from_metadata(self):
        """Реквизиты формы и состав типов из .mdo: объект основного реквизита и типы по путям элементов."""
        model, _ = import_form(CONTRACT_FORM)
        main = [item for item in model["attributes"] if item.get("main")]
        self.assertEqual([(item["name"], item["valueType"]) for item in main], [("Объект", "CatalogObject._ДемоДоговоры")])
        # Колонки, добавленные формой к табличной части объекта
        self.assertEqual(main[0]["additionalColumns"], {"Условия": [
            {"name": "Представление", "title": "Представление условия", "valueType": "String", "length": 0}]})
        contract = model["types"]["Catalog._ДемоДоговоры"]
        names = {item["name"] for item in contract["attributes"]}
        self.assertLessEqual({"Ref", "Description", "DeletionMark", "ДатаПодписания", "Вид"}, names)
        self.assertEqual([(section["name"], [column["name"] for column in section["columns"]])
                          for section in contract["tabularSections"]],
                         [("Этапы", ["Наименование", "ТребуетсяСогласование"]), ("Условия", ["Имя"])])
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        self.assertEqual([issue.message for issue in check(model, validator) if issue.code == "data-path"], [])

    def test_titles_from_metadata(self):
        model, report = import_form(CONTRACT_FORM)
        items = nodes(model)
        self.assertEqual(model["form"]["formKind"], "CatalogObjectForm")
        self.assertEqual(model["form"]["title"], "Договор")                                  # представление объекта
        self.assertEqual(items["Наименование"][0]["title"], "Наименование")                 # стандартный реквизит
        self.assertEqual(items["Вид"][0]["title"], "Вид договора")                           # синоним реквизита
        self.assertEqual(items["Этапы"][0]["title"], "Этапы исполнения")                     # табличная часть
        # Поле текущей строки таблицы: путь таблицы + колонка, синоним из .mdo, а не имя
        self.assertEqual(items["ЭтапыТребуетсяСогласование"][0]["title"], "Согласование руководителем перед оплатой")
        self.assertGreater(report.titles["metadata"], 0)


class StyleColorsTest(unittest.TestCase):
    """Цвет стиля в модели: имя в форме, значение в `styles`, основной стиль конфигурации."""

    def test_style_names(self):
        model, report = import_form(CONTRACT_FORM)
        items = {name: node for name, (node, _) in nodes(model).items()}
        # Заголовок группы - цвет стиля платформы именем, а не вычисленным значением
        self.assertEqual(items["ГруппаПодсказка"]["titleTextColor"], "style:ButtonTextColor")
        # Цвет элемента стиля конфигурации - тоже именем, значение - в `styles`
        self.assertEqual(items["ТекстПодсказки"]["textColor"], "style:_ДемоЦветАкцента")
        self.assertEqual(model["styles"], {"ButtonTextColor": "#4D4D4D", "_ДемоЦветАкцента": "#1955AE"})
        # В styles - только цвета, использованные формой: все элементы стиля - у сервера (`config_styles`)
        self.assertEqual(set(model["styles"]), colors.used_styles(model["form"], set()))
        self.assertEqual(report.styles[0], report.styles[1])
        self.assertEqual(colors.config_styles(EDT_SRC, True), [{"name": "_ДемоЦветАкцента", "value": "#1955AE"}])

    def write(self, root: Path, files: dict):
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_main_style_overrides(self):
        """Основной стиль переопределяет элементы конфигурации и платформы; ссылка на сам элемент - его значение."""
        edt_item = ('<mdclass:StyleItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                    'xmlns:core="http://g5.1c.ru/v8/dt/mcore" xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass" '
                    'uuid="{uuid}"><name>{name}</name><value xsi:type="core:ColorValue">{value}</value></mdclass:StyleItem>')
        designer_item = ('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" '
                         'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><StyleItem uuid="{uuid}"><Properties>'
                         '<Name>{name}</Name><Type>{kind}</Type><Value>{value}</Value></Properties></StyleItem></MetaDataObject>')
        with tempfile.TemporaryDirectory() as folder:
            edt, designer = Path(folder) / "edt", Path(folder) / "designer"
            self.write(edt, {
                "Configuration/Configuration.mdo": "<mdclass:Configuration><defaultStyle>Style.Мой</defaultStyle></mdclass:Configuration>",
                "StyleItems/Фон/Фон.mdo": edt_item.format(uuid="11111111-1111-1111-1111-111111111111", name="Фон",
                                                           value='<value xsi:type="core:ColorDef"><red>255</red></value>'),
                "StyleItems/Ссылка/Ссылка.mdo": edt_item.format(uuid="22222222-2222-2222-2222-222222222222", name="Ссылка",
                                                                 value='<value xsi:type="core:ColorRef"><color>Web.Gainsboro</color></value>'),
                "StyleItems/Шрифт/Шрифт.mdo": '<mdclass:StyleItem xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass"><name>Шрифт</name></mdclass:StyleItem>',
                "Styles/Мой/Style.style": (
                    '<style:Style xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:core="http://g5.1c.ru/v8/dt/mcore" '
                    'xmlns:style="http://g5.1c.ru/v8/dt/style">'
                    '<items xsi:type="style:ColorStyleItem"><name>AccentColor</name><color xsi:type="core:ColorDef"><blue>255</blue></color></items>'
                    '<items xsi:type="style:ColorStyleItem"><name>StyleItem.Фон</name><color xsi:type="core:ColorDef"><green>16</green></color></items>'
                    '<items xsi:type="style:ColorStyleItem"><name>StyleItem.Ссылка</name><color xsi:type="core:ColorRef"><color>Style.Ссылка</color></color></items>'
                    '</style:Style>'),
            })
            self.write(designer, {
                "Configuration.xml": "<MetaDataObject><DefaultStyle>Style.Мой</DefaultStyle></MetaDataObject>",
                "StyleItems/Фон.xml": designer_item.format(uuid="11111111-1111-1111-1111-111111111111", name="Фон",
                                                            kind="Color", value="#FF0000"),
                "StyleItems/Ссылка.xml": designer_item.format(uuid="22222222-2222-2222-2222-222222222222", name="Ссылка",
                                                               kind="Color", value="web:Gainsboro"),
                "StyleItems/Шрифт.xml": designer_item.format(uuid="33333333-3333-3333-3333-333333333333", name="Шрифт",
                                                              kind="Font", value="x"),
                "Styles/Мой/Ext/Style.xml": (
                    '<Style xmlns="http://v8.1c.ru/8.3/xcf/extrnprops"><Item name="AccentColor"><Color>#0000FF</Color></Item>'
                    '<Item name="StyleItem.Фон"><Color>#001000</Color></Item>'
                    '<Item name="StyleItem.Ссылка"><Color>style:Ссылка</Color></Item></Style>'),
            })
            used = {"AccentColor", "FormTextColor", "ReportLineColor", "Нет", "Ссылка"}
            # Только использованные формой: «Фон» не использован - его нет
            expected = {"Ссылка": "#DCDCDC", "AccentColor": "#0000FF", "FormTextColor": "#333333"}
            for src, edt_format in ((edt, True), (designer, False)):
                with self.subTest(edt=edt_format):
                    self.assertEqual(colors.styles(src, edt_format, used), expected)
                    # Все цветовые элементы конфигурации, без шрифта - вторая часть «Из стиля» конструктора
                    self.assertEqual(colors.config_styles(src, edt_format),
                                     [{"name": "Ссылка", "value": "#DCDCDC"}, {"name": "Фон", "value": "#001000"}])
                    self.assertEqual(colors.formatted("<colorstyle 0:22222222-2222-2222-2222-222222222222>а</>", src, edt_format),
                                     "<color style:Ссылка>а</>")
        # Без исходников - только стиль платформы по таблице «Такси»
        self.assertEqual(colors.styles(None, True, used), {"AccentColor": "#009646", "FormTextColor": "#333333"})

    def test_resolve(self):
        self.assertEqual(colors.resolve("Style.ЦветТекстаФормы"), "style:FormTextColor")
        self.assertEqual(colors.resolve("style:ГиперссылкаЦвет"), "style:ГиперссылкаЦвет")
        self.assertEqual(colors.resolve("Web.Gainsboro"), "gainsboro")
        self.assertEqual(colors.resolve("#1c55ae"), "#1C55AE")
        self.assertIsNone(colors.resolve("win:ButtonFace"))


class FieldPropertiesTest(unittest.TestCase):
    """Свойства поля, таблицы и формы из XML: как записаны, без свертки в кнопки."""

    def test_properties(self):
        model, _ = import_form(CONTRACT_FORM)
        items = {name: node for name, (node, _) in nodes(model).items()}
        # Состав даты «Дата» записан в реквизите явно, «Дата и время» - умолчание и не пишется
        self.assertEqual(items["ДатаПодписания"]["dateFractions"], "Date")
        # Линий сетки в XML нет - Ложь модели EDT; записанные линии - умолчание модели, не пишутся
        self.assertIs(items["Этапы"]["horizontalLines"], False)
        self.assertIs(items["Этапы"]["verticalLines"], False)
        self.assertFalse({"horizontalLines", "verticalLines"} & set(items["Условия"]))
        self.assertEqual(items["Этапы"]["rowsPicture"], "CommonPicture._ДемоСтатус")
        self.assertTrue(model["pictures"]["CommonPicture._ДемоСтатус"].startswith("data:image/svg+xml;base64,"))
        # Режим выбора из списка - свойством, а не явными кнопками поля
        listed = items["Вид"]
        self.assertIs(listed["listChoiceMode"], True)
        self.assertFalse({"choiceButton", "dropListButton"} & set(listed))
        self.assertEqual(listed["choiceList"], ["С покупателем", "С поставщиком"])
        self.assertIs(items["ДатаПодписания"]["autoMarkIncomplete"], True)
        self.assertNotIn("autoMarkIncomplete", items["Наименование"])


# Одна форма в двух форматах: шрифты, колонка таблицы, команда формы и ее кнопка
EDT_COLUMNS = """<?xml version="1.0" encoding="UTF-8"?>
<form:Form xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:core="http://g5.1c.ru/v8/dt/mcore"
    xmlns:form="http://g5.1c.ru/v8/dt/form">
  <items xsi:type="form:FormField">
    <name>Поле</name><visible>true</visible><type>InputField</type>
    <extInfo xsi:type="form:InputFieldExtInfo">
      <autoMaxWidth>true</autoMaxWidth><autoMaxHeight>true</autoMaxHeight>
      <font xsi:type="core:FontDef"><faceName>Arial</faceName><height>11.0</height><strikeout>true</strikeout></font>
      <titleFont xsi:type="core:FontRef"><font>Style.NormalTextFont</font><bold>true</bold><italic>false</italic>
        <underline>false</underline><strikeout>false</strikeout><scale>100</scale></titleFont>
    </extInfo>
  </items>
  <items xsi:type="form:Table">
    <name>Строки</name><visible>true</visible><footer>true</footer>
    <items xsi:type="form:FormField">
      <name>Сумма</name><visible>true</visible><type>InputField</type><showInHeader>true</showInHeader>
      <headerHorizontalAlign>Right</headerHorizontalAlign>
      <headerBackColor xsi:type="core:ColorRef"><color>Web.Gainsboro</color></headerBackColor>
      <showInFooter>true</showInFooter>
      <footerPicture xsi:type="core:PictureRef"><picture>CommonPicture.Итог</picture></footerPicture>
      <footerHorizontalAlign>Left</footerHorizontalAlign>
      <footerBackColor xsi:type="core:ColorDef"><red>255</red></footerBackColor>
      <footerTextColor xsi:type="core:ColorRef"><color>Style.ЦветТекстаФормы</color></footerTextColor>
      <footerFont xsi:type="core:FontRef"><font>Style.NormalTextFont</font><bold>true</bold><italic>false</italic>
        <underline>false</underline><strikeout>false</strikeout></footerFont>
      <extInfo xsi:type="form:InputFieldExtInfo"><autoMaxWidth>true</autoMaxWidth><autoCellHeight>true</autoCellHeight></extInfo>
    </items>
    <items xsi:type="form:FormField">
      <name>Ссылка</name><visible>true</visible><type>LabelField</type><showInHeader>true</showInHeader>
      <headerHorizontalAlign>Left</headerHorizontalAlign>
      <extInfo xsi:type="form:LabelFieldExtInfo"><autoMaxWidth>true</autoMaxWidth><autoMaxHeight>true</autoMaxHeight><cellHyperlink>true</cellHyperlink></extInfo>
    </items>
  </items>
  <items xsi:type="form:Button">
    <name>КнопкаПроверить</name><visible>true</visible><type>UsualButton</type>
    <commandName>Form.Command.Проверить</commandName><representation>Auto</representation>
  </items>
  <items xsi:type="form:Button">
    <name>КнопкаСвоя</name><visible>true</visible><title><key>ru</key><value>Свой заголовок</value></title>
    <type>UsualButton</type><commandName>Form.Command.Проверить</commandName><representation>Text</representation><check>true</check>
  </items>
  <formCommands>
    <name>Проверить</name>
    <title><key>ru</key><value>Проверить контрагента</value></title>
    <id>1</id>
    <toolTip><key>ru</key><value>Проверка по базе</value></toolTip>
    <use><common>true</common></use>
    <picture xsi:type="core:PictureRef"><picture>StdPicture.Find</picture></picture>
    <action xsi:type="form:FormCommandHandlerContainer"><handler><name>ПроверитьОбработка</name></handler></action>
    <representation>TextPicture</representation>
  </formCommands>
  <formCommands>
    <name>Закрыть</name><title><key>ru</key><value>Закрыть</value></title><id>2</id>
  </formCommands>
</form:Form>
"""
DESIGNER_COLUMNS = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core"
    xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="2.20">
  <ChildItems>
    <InputField name="Поле" id="1">
      <Font faceName="Arial" height="11" strikeout="true" kind="Absolute"/>
      <TitleFont ref="style:NormalTextFont" bold="true" italic="false" underline="false" strikeout="false" kind="StyleItem" scale="100"/>
    </InputField>
    <Table name="Строки" id="2">
      <Footer>true</Footer>
      <ChildItems>
        <InputField name="Сумма" id="3">
          <HeaderHorizontalAlign>Right</HeaderHorizontalAlign>
          <HeaderBackColor>web:Gainsboro</HeaderBackColor>
          <FooterPicture><xr:Ref>CommonPicture.Итог</xr:Ref><xr:LoadTransparent>true</xr:LoadTransparent></FooterPicture>
          <FooterHorizontalAlign>Left</FooterHorizontalAlign>
          <FooterBackColor>#FF0000</FooterBackColor>
          <FooterTextColor>style:FormTextColor</FooterTextColor>
          <FooterFont ref="style:NormalTextFont" bold="true" italic="false" underline="false" strikeout="false" kind="StyleItem"/>
          <AutoCellHeight>true</AutoCellHeight>
        </InputField>
        <LabelField name="Ссылка" id="4">
          <ShowInFooter>false</ShowInFooter>
          <CellHyperlink>true</CellHyperlink>
        </LabelField>
      </ChildItems>
    </Table>
    <Button name="КнопкаПроверить" id="5">
      <Type>UsualButton</Type><CommandName>Form.Command.Проверить</CommandName>
    </Button>
    <Button name="КнопкаСвоя" id="6">
      <Type>UsualButton</Type><CommandName>Form.Command.Проверить</CommandName>
      <Title><v8:item><v8:lang>ru</v8:lang><v8:content>Свой заголовок</v8:content></v8:item></Title>
      <Representation>Text</Representation><Check>true</Check>
    </Button>
  </ChildItems>
  <Commands>
    <Command name="Проверить" id="1">
      <Title><v8:item><v8:lang>ru</v8:lang><v8:content>Проверить контрагента</v8:content></v8:item></Title>
      <ToolTip><v8:item><v8:lang>ru</v8:lang><v8:content>Проверка по базе</v8:content></v8:item></ToolTip>
      <Picture><xr:Ref>StdPicture.Find</xr:Ref><xr:LoadTransparent>true</xr:LoadTransparent></Picture>
      <Representation>TextPicture</Representation>
      <Action>ПроверитьОбработка</Action>
    </Command>
    <Command name="Закрыть" id="2">
      <Title><v8:item><v8:lang>ru</v8:lang><v8:content>Закрыть</v8:content></v8:item></Title>
    </Command>
  </Commands>
</Form>
"""


# Оформление полей надписи, флажка, картинки (владелец 04.11.2026) - одна форма в двух форматах
EDT_LOOK = """<?xml version="1.0" encoding="UTF-8"?>
<form:Form xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:core="http://g5.1c.ru/v8/dt/mcore"
    xmlns:form="http://g5.1c.ru/v8/dt/form">
  <items xsi:type="form:FormField">
    <name>Картинка</name><visible>true</visible><type>PictureField</type>
    <extInfo xsi:type="form:ImageFieldExtInfo">
      <autoMaxWidth>true</autoMaxWidth><autoMaxHeight>true</autoMaxHeight>
      <horizontalStretch>true</horizontalStretch><verticalStretch>true</verticalStretch>
      <pictureSize>Stretch</pictureSize><hyperlink>true</hyperlink>
      <valuesPicture xsi:type="core:PictureRef"><picture>CommonPicture.Важность</picture></valuesPicture>
      <border xsi:type="core:BorderDef"><style>Single</style><width>1</width></border>
    </extInfo>
  </items>
  <items xsi:type="form:FormField">
    <name>Надпись</name><visible>true</visible><type>LabelField</type>
    <backColor xsi:type="core:ColorRef"><color>Web.Gainsboro</color></backColor>
    <extInfo xsi:type="form:LabelFieldExtInfo">
      <autoMaxWidth>true</autoMaxWidth><maxHeight>3</maxHeight>
      <horizontalAlign>Center</horizontalAlign><verticalAlign>Top</verticalAlign>
      <border xsi:type="core:BorderDef"><style>Double</style><width>1</width></border>
    </extInfo>
  </items>
  <items xsi:type="form:FormField">
    <name>Флажок</name><visible>true</visible><type>CheckBoxField</type>
    <titleFont xsi:type="core:FontRef"><font>Style.NormalTextFont</font><bold>true</bold><italic>false</italic>
      <underline>false</underline><strikeout>false</strikeout></titleFont>
    <extInfo xsi:type="form:CheckBoxFieldExtInfo"><verticalAlign>Center</verticalAlign></extInfo>
  </items>
  <items xsi:type="form:FormField">
    <name>Текст</name><visible>true</visible><type>InputField</type>
    <extInfo xsi:type="form:InputFieldExtInfo">
      <autoMaxWidth>true</autoMaxWidth><maxHeight>6</maxHeight><verticalStretch>true</verticalStretch>
      <multiLine>true</multiLine>
    </extInfo>
  </items>
  <items xsi:type="form:FormField">
    <name>Строка</name><visible>true</visible><type>InputField</type>
    <extInfo xsi:type="form:InputFieldExtInfo"><autoMaxWidth>true</autoMaxWidth><autoMaxHeight>true</autoMaxHeight></extInfo>
  </items>
</form:Form>
"""
DESIGNER_LOOK = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core"
    xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.20">
  <ChildItems>
    <PictureField name="Картинка" id="1">
      <PictureSize>Stretch</PictureSize><Hyperlink>true</Hyperlink>
      <ValuesPicture><xr:Ref>CommonPicture.Важность</xr:Ref><xr:LoadTransparent>false</xr:LoadTransparent></ValuesPicture>
      <Border width="1"><v8ui:style xsi:type="v8ui:ControlBorderType">Single</v8ui:style></Border>
    </PictureField>
    <LabelField name="Надпись" id="2">
      <AutoMaxHeight>false</AutoMaxHeight><MaxHeight>3</MaxHeight>
      <HorizontalAlign>Center</HorizontalAlign><VerticalAlign>Top</VerticalAlign>
      <BackColor>web:Gainsboro</BackColor>
      <Border width="1"><v8ui:style xsi:type="v8ui:ControlBorderType">Double</v8ui:style></Border>
    </LabelField>
    <CheckBoxField name="Флажок" id="3">
      <TitleFont ref="style:NormalTextFont" bold="true" italic="false" underline="false" strikeout="false" kind="StyleItem"/>
      <VerticalAlign>Center</VerticalAlign>
    </CheckBoxField>
    <InputField name="Текст" id="4">
      <AutoMaxHeight>false</AutoMaxHeight><MaxHeight>6</MaxHeight><VerticalStretch>true</VerticalStretch>
      <MultiLine>true</MultiLine>
    </InputField>
    <InputField name="Строка" id="5"/>
  </ChildItems>
</Form>
"""


class FieldLookTest(unittest.TestCase):
    """Свойства полей картинки, надписи, флажка - из обоих форматов одинаково."""

    @classmethod
    def setUpClass(cls):
        cls.folder = Path(temp_dir(prefix="formmockup-look-"))
        cls.models = {}
        for name, text in (("Form.form", EDT_LOOK), ("Form.xml", DESIGNER_LOOK)):
            path = cls.folder / name
            path.write_text(text, encoding="utf-8")
            cls.models[name] = import_form(path)[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_look(self):
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        for name, model in self.models.items():
            with self.subTest(format=name):
                self.assertEqual(validator.validate(model), [])
                items = {key: node for key, (node, _) in nodes(model).items()}
                picture = items["Картинка"]
                self.assertEqual((picture["type"], picture["valuesPicture"], picture["pictureSize"], picture["hyperlink"]),
                                 ("PictureField", "CommonPicture.Важность", "Stretch", True))
                self.assertNotIn("border", picture, "одинарная рамка поля картинки - умолчание")
                self.assertNotIn("autoMaxHeight", picture)
                label = items["Надпись"]
                self.assertEqual((label["border"], label["maxHeight"], label["autoMaxHeight"], label["horizontalAlign"],
                                  label["verticalAlign"]), ("Double", 3, False, "Center", "Top"))
                self.assertTrue(label["backColor"])
                flag = items["Флажок"]
                self.assertEqual((flag["titleFont"], flag["verticalAlign"]), ({"bold": True}, "Center"))
                # Предел высоты многострочного поля ввода; «авто» - умолчание, не пишется
                text = items["Текст"]
                self.assertEqual((text["autoMaxHeight"], text["maxHeight"], text["verticalStretch"], text["multiLine"]),
                                 (False, 6, True, True))
                self.assertFalse({"autoMaxHeight", "maxHeight"} & set(items["Строка"]))
        edt, designer = self.models.values()
        for name in ("Картинка", "Надпись", "Флажок", "Текст", "Строка"):
            self.assertEqual(nodes(edt)[name], nodes(designer)[name], name)


# Список выбора - по образцам форм настроек сканирования: булево Ложь EDT пишет пустым
# тегом, выгрузка - `false`; строка с точкой, число, предопределенный, пункт с представлением
EDT_CHOICES = """<?xml version="1.0" encoding="UTF-8"?>
<form:Form xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:core="http://g5.1c.ru/v8/dt/mcore"
    xmlns:form="http://g5.1c.ru/v8/dt/form">
  <items xsi:type="form:FormField">
    <name>Поле</name><visible>true</visible><type>InputField</type>
    <extInfo xsi:type="form:InputFieldExtInfo">
      <choiceList><value xsi:type="core:BooleanValue"/></choiceList>
      <choiceList><presentation><key>ru</key><value>Включено</value></presentation>
        <value xsi:type="core:BooleanValue"><value>true</value></value></choiceList>
      <choiceList><value xsi:type="core:StringValue"><value>в т.ч. НДС</value></value></choiceList>
      <choiceList><presentation><key>ru</key><value>Пять</value></presentation>
        <value xsi:type="core:NumberValue"><value>5</value></value></choiceList>
      <choiceList><value xsi:type="core:ReferenceValue"><value>Catalog.Роли.ТехническийЗаказчик</value></value></choiceList>
    </extInfo>
  </items>
</form:Form>
"""

DESIGNER_CHOICES = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core"
    xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.20">
  <ChildItems>
    <InputField name="Поле" id="1">
      <ChoiceList>
        <xr:Item><xr:Presentation/><xr:CheckState>0</xr:CheckState>
          <xr:Value xsi:type="FormChoiceListDesTimeValue"><Presentation/>
            <Value xsi:type="xs:boolean">false</Value></xr:Value></xr:Item>
        <xr:Item><xr:Presentation/><xr:CheckState>0</xr:CheckState>
          <xr:Value xsi:type="FormChoiceListDesTimeValue">
            <Presentation><v8:item><v8:lang>ru</v8:lang><v8:content>Включено</v8:content></v8:item></Presentation>
            <Value xsi:type="xs:boolean">true</Value></xr:Value></xr:Item>
        <xr:Item><xr:Presentation/><xr:CheckState>0</xr:CheckState>
          <xr:Value xsi:type="FormChoiceListDesTimeValue"><Presentation/>
            <Value xsi:type="xs:string">в т.ч. НДС</Value></xr:Value></xr:Item>
        <xr:Item><xr:Presentation/><xr:CheckState>0</xr:CheckState>
          <xr:Value xsi:type="FormChoiceListDesTimeValue">
            <Presentation><v8:item><v8:lang>ru</v8:lang><v8:content>Пять</v8:content></v8:item></Presentation>
            <Value xsi:type="xs:decimal">5</Value></xr:Value></xr:Item>
        <xr:Item><xr:Presentation/><xr:CheckState>0</xr:CheckState>
          <xr:Value xsi:type="FormChoiceListDesTimeValue"><Presentation/>
            <Value xsi:type="xr:DesignTimeRef">Catalog.Роли.ТехническийЗаказчик</Value></xr:Value></xr:Item>
      </ChoiceList>
    </InputField>
  </ChildItems>
</Form>
"""


class ChoiceListTest(unittest.TestCase):
    """Список выбора - значение и представление, из обоих форматов одинаково."""

    def test_values_and_presentations(self):
        folder = Path(temp_dir(prefix="formmockup-import-"))
        self.addCleanup(shutil.rmtree, folder, True)
        expected = ["Нет", {"value": "Да", "presentation": "Включено"}, "в т.ч. НДС",
                    {"value": "5", "presentation": "Пять"}, "Технический заказчик"]
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        for name, text in (("Form.form", EDT_CHOICES), ("Form.xml", DESIGNER_CHOICES)):
            with self.subTest(format=name):
                path = folder / name
                path.write_text(text, encoding="utf-8")
                model = import_form(path)[0]
                self.assertEqual(validator.validate(model), [])
                self.assertEqual(nodes(model)["Поле"][0]["choiceList"], expected)


class ColumnsCommandsTest(unittest.TestCase):
    """Шрифт с именем и размером, свойства колонки, команды формы и кнопка команды - из обоих форматов."""

    @classmethod
    def setUpClass(cls):
        cls.folder = Path(temp_dir(prefix="formmockup-import-"))
        cls.models = {}
        for name, text in (("Form.form", EDT_COLUMNS), ("Form.xml", DESIGNER_COLUMNS)):
            path = cls.folder / name
            path.write_text(text, encoding="utf-8")
            cls.models[name] = import_form(path)[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def each(self):
        for name, model in self.models.items():
            with self.subTest(format=name):
                yield model, {key: node for key, (node, _) in nodes(model).items()}

    def test_schema_and_same_model(self):
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        for model, _ in self.each():
            self.assertEqual(validator.validate(model), [])
        edt, designer = self.models.values()
        # Колонки и кнопки - одинаково (умолчания самой таблицы в фикстурах не сведены)
        for name in ("Сумма", "Ссылка", "Поле", "КнопкаПроверить", "КнопкаСвоя"):
            self.assertEqual(nodes(edt)[name], nodes(designer)[name], name)
        self.assertEqual(edt["commands"], designer["commands"])

    def test_fonts(self):
        for _, items in self.each():
            # Абсолютный шрифт - имя, размер и зачеркнутый; шрифт стиля без своих имени и размера - начертание
            self.assertEqual(items["Поле"]["font"], {"faceName": "Arial", "height": 11, "strikeout": True})
            self.assertEqual(items["Поле"]["titleFont"], {"bold": True})

    def test_column_properties(self):
        for _, items in self.each():
            self.assertEqual({key: value for key, value in items["Сумма"].items() if key.startswith(("header", "footer"))
                              or key in ("showInFooter", "autoCellHeight")}, {
                "headerHorizontalAlign": "Right", "headerBackColor": "gainsboro", "footerPicture": "CommonPicture.Итог",
                "footerHorizontalAlign": "Left", "footerBackColor": "#FF0000", "footerTextColor": "style:FormTextColor",
                "footerFont": {"bold": True}, "autoCellHeight": True})
            # Умолчания не пишутся: положение «Лево» в шапке, «Отображать в подвале» - только отказ
            link = items["Ссылка"]
            self.assertNotIn("headerHorizontalAlign", link)
            self.assertIs(link["cellHyperlink"], True)
            # Поле вне таблицы свойств колонки не получает
            self.assertFalse({"showInFooter", "headerHorizontalAlign", "cellHyperlink"} & set(items["Поле"]))

    def test_show_in_footer(self):
        edt, designer = self.models.values()
        # EDT: «Отображать в подвале» не записано - Ложь; выгрузка: записано Ложь
        self.assertIs(nodes(edt)["Ссылка"][0]["showInFooter"], False)
        self.assertIs(nodes(designer)["Ссылка"][0]["showInFooter"], False)
        self.assertNotIn("showInFooter", nodes(designer)["Сумма"][0])

    def test_commands(self):
        for model, items in self.each():
            self.assertEqual(model["commands"], [
                {"name": "Проверить", "title": "Проверить контрагента", "toolTip": "Проверка по базе",
                 "action": "ПроверитьОбработка", "picture": "StdPicture.Find", "representation": "PictureAndText"},
                {"name": "Закрыть", "title": "Закрыть"}])
            self.assertEqual(list(model).index("commands"), list(model).index("form") + 1)
            # Картинка команды - в картинках макета (архив стандартных картинок инструмента)
            self.assertIn("StdPicture.Find", model.get("pictures", {}))
            # Кнопка без своих заголовка, картинки и отображения - только команда
            self.assertEqual(items["КнопкаПроверить"], {"type": "Button", "name": "КнопкаПроверить",
                                                        "commandName": "Form.Command.Проверить"})
            own = items["КнопкаСвоя"]
            self.assertEqual((own["title"], own["representation"]), ("Свой заголовок", "Text"))
            self.assertNotIn("picture", own)
            # Пометка: установленная - переносится, не записанная в исходниках - не пишется
            self.assertIs(own["check"], True)
            self.assertNotIn("check", items["КнопкаПроверить"])


DESIGNER_TABLE_BUTTONS = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core"
    xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="2.20">
  <ChildItems>
    <Table name="Строки" id="1">
      <AutoCommandBar name="СтрокиКоманднаяПанель" id="2">
        <Autofill>false</Autofill>
        <ChildItems>
          <Button name="Вверх" id="3">
            <Type>CommandBarButton</Type><CommandName>Form.Item.Строки.StandardCommand.MoveUp</CommandName>
          </Button>
          <Button name="Своя" id="4">
            <Type>CommandBarButton</Type><CommandName>Form.Item.Строки.StandardCommand.Copy</CommandName>
            <Picture><xr:Ref>StdPicture.Print</xr:Ref><xr:LoadTransparent>true</xr:LoadTransparent></Picture>
          </Button>
        </ChildItems>
      </AutoCommandBar>
      <ChildItems>
        <InputField name="Колонка" id="5"/>
      </ChildItems>
    </Table>
  </ChildItems>
</Form>
"""


class TableCommandPictureTest(unittest.TestCase):
    """Значок стандартной команды таблицы рендерер берет сам: импорт его не повторяет, своя
    картинка кнопки остается."""

    def test_inherited_picture_not_written(self):
        with tempfile.TemporaryDirectory(prefix="formmockup-import-") as folder:
            path = Path(folder) / "Form.xml"
            path.write_text(DESIGNER_TABLE_BUTTONS, encoding="utf-8")
            items = {key: node for key, (node, _) in nodes(import_form(path)[0]).items()}
        self.assertNotIn("picture", items["Вверх"])
        self.assertEqual(items["Своя"]["picture"], "StdPicture.Print")


class StdPicturesTest(unittest.TestCase):
    """Стандартные картинки платформы из каталога выгрузки (`1c/ВыгрузитьСтандартныеКартинки.bsl`)."""

    def test_pictures_from_export_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "Change.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            # Формат, не опознанный 1С, выгрузка пишет с .bin: импорт узнает его по содержимому
            Path(folder, "MoveUp.bin").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
            model, report = import_form(CONTRACT_FORM, Path(folder))
        found = model.get("pictures", {})
        self.assertTrue(found["StdPicture.Change"].startswith("data:image/png;base64,"))
        self.assertTrue(found["StdPicture.MoveUp"].startswith("data:image/svg+xml;base64,"))
        self.assertNotIn("StdPicture.MoveDown", found)
        self.assertEqual(report.std_pictures[0], 2)
        self.assertEqual(SchemaValidator.from_file(SCHEMA_PATH).validate(model), [])

    def test_bundled_archive_by_default(self):
        """Без указанной выгрузки - архив инструмента `std-pictures.zip`."""
        model, report = import_form(CONTRACT_FORM)
        found = model.get("pictures", {})
        self.assertTrue(found["StdPicture.MoveUp"].startswith("data:image/png;base64,"))
        self.assertTrue(found["StdPicture.InputFieldOpen"].startswith("data:image/"))
        self.assertEqual(report.std_pictures[0], report.std_pictures[1])


class CorpusTest(unittest.TestCase):
    """Все формы фикстур EDT: без падений, по схеме, без нераспознанного, HTML собирается."""

    def test_fixture_forms(self):
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        dictionary = load_dictionary(DICTIONARY_PATH)
        files = list(corpus(EDT_SRC))
        self.assertEqual([path.parent.name for path in files], ["ФормаЭлемента", "Форма"])
        for path in files:
            with self.subTest(form=str(path.relative_to(EDT_SRC))):
                model, report = import_form(path)
                self.assertEqual(validator.validate(model), [])
                self.assertEqual(report.unrecognized, 0, report.lines())
                # Пути элементов проходятся по реквизитам формы и составу типов
                self.assertEqual([issue.message for issue in check(model, validator) if issue.code == "data-path"], [])
                page = render.build_html(model, dictionary, model["form"]["title"])
                self.assertIn('id="fm-data"', page)

    @unittest.skipUnless(os.environ.get("FORMMOCKUP_CORPUS"), "FORMMOCKUP_CORPUS не задан")
    def test_external_corpus(self):
        validator = SchemaValidator.from_file(SCHEMA_PATH)
        roots = os.environ["FORMMOCKUP_CORPUS"].split(os.pathsep)
        count = 0
        for path in list(corpus(*roots)) + list(corpus(*roots, pattern="Form.xml")):
            count += 1
            model, report = import_form(path)
            self.assertEqual(validator.validate(model), [], str(path))
            self.assertEqual(report.unrecognized, 0, f"{path}: {report.lines()}")
            paths = [issue.message for issue in check(model, validator) if issue.code == "data-path"]
            self.assertEqual(paths, [], str(path))
        self.assertGreater(count, 0)

    @unittest.skipUnless(os.environ.get("FORMMOCKUP_PAIRS"), "FORMMOCKUP_PAIRS не задан")
    def test_format_pairs(self):
        """Одна конфигурация из EDT и из выгрузки той же версии: модель каждой формы - целиком по
        разделам, без допуска; данные окон выбора - те же; формы с путем длиннее 260 символов найдены."""
        from fmlib.server import Sources
        edt, designer = (Path(item) for item in os.environ["FORMMOCKUP_PAIRS"].split(os.pathsep))
        pairs = 0
        for path in corpus(edt):
            other = designer / path.relative_to(edt).parent / "Ext" / "Form.xml"
            if not long_path(other).is_file():
                continue
            pairs += 1
            left, right = import_form(path)[0], import_form(other)[0]
            for section in ("form", "attributes", "commands", "types", "styles", "pictures"):
                with self.subTest(form=str(path.relative_to(edt).parent), section=section):
                    self.assertEqual(left.get(section), right.get(section))
        self.assertGreater(pairs, 0)
        left, right = Sources(None, edt), Sources(None, designer)
        types = left.config_types()
        self.assertEqual(types, right.config_types())
        for entry in types:
            if entry["kind"] in ("Catalog", "Document", "ChartOfCharacteristicTypes", "ChartOfAccounts"):
                with self.subTest(type=entry["key"]):
                    self.assertEqual(left.type_description(entry["key"]), right.type_description(entry["key"]))
        self.assertEqual(left.config_pictures(), right.config_pictures())
        self.assertEqual(left.config_styles(), right.config_styles())
        forms = [[(form["key"], form["kind"]) for form in sources.config_forms()] for sources in (left, right)]
        self.assertEqual(forms[0], forms[1], "формы для импорта, в том числе с длинным путем")


# Одно чтение для EDT и выгрузки: XML-имена типов выгрузки, место команды в группе
DESIGNER_XML_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core"
    xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:dcsset="http://v8.1c.ru/8.1/data-composition-system/settings"
    xmlns:dcscor="http://v8.1c.ru/8.1/data-composition-system/core" version="2.20">
  <Attributes>
    <Attribute name="Документ" id="1"><Type><v8:Type xmlns:mxl="http://v8.1c.ru/8.2/data/spreadsheet">mxl:SpreadsheetDocument</v8:Type></Type></Attribute>
    <Attribute name="Компоновщик" id="2"><Type><v8:Type>dcsset:SettingsComposer</v8:Type></Type></Attribute>
    <Attribute name="Отбор" id="3"><Type><v8:Type>dcsset:Filter</v8:Type></Type></Attribute>
    <Attribute name="Поле" id="4"><Type><v8:Type>dcscor:Field</v8:Type></Type></Attribute>
    <Attribute name="Схема" id="5"><Type><v8:Type xmlns:d5p1="http://v8.1c.ru/8.2/data/graphscheme">d5p1:FlowchartContextType</v8:Type></Type></Attribute>
    <Attribute name="Текст" id="6"><Type><v8:Type xmlns:fd="http://v8.1c.ru/8.2/data/formatted-document">fd:FormattedDocument</v8:Type></Type></Attribute>
  </Attributes>
  <CommandInterface>
    <CommandBar>
      <Item>
        <Command>CommonCommand.Важная</Command><Type>Auto</Type><CommandGroup>FormCommandBarImportant</CommandGroup>
      </Item>
      <Item>
        <Command>CommonCommand.Вторая</Command><Type>Auto</Type><CommandGroup>FormCommandBarImportant</CommandGroup>
        <Index>2</Index>
      </Item>
    </CommandBar>
  </CommandInterface>
</Form>
"""


class OneReadingTest(unittest.TestCase):
    """Малые случаи сравнения EDT и выгрузки на полной БСП."""

    def test_designer_xml_types(self):
        with tempfile.TemporaryDirectory(prefix="formmockup-import-") as folder:
            path = Path(folder) / "Form.xml"
            path.write_text(DESIGNER_XML_TYPES, encoding="utf-8")
            model = import_form(path)[0]
        types = {item["name"]: item["valueType"] for item in model["attributes"]}
        self.assertEqual(types, {"Документ": "SpreadsheetDocument", "Компоновщик": "DataCompositionSettingsComposer",
                                 "Отбор": "DataCompositionFilter", "Поле": "DataCompositionField",
                                 "Схема": "GraphicalSchema", "Текст": "FormattedDocument"})

    def test_designer_interface_index(self):
        """Место 0 в группе выгрузка не пишет, EDT пишет `<index>0</index>`."""
        import xml.etree.ElementTree as ET
        raw = read_designer(ET.fromstring(DESIGNER_XML_TYPES))
        self.assertEqual(raw.interface["CommonCommand.Важная"][:2], ("FormCommandBarImportant", 0))
        self.assertEqual(raw.interface["CommonCommand.Вторая"][:2], ("FormCommandBarImportant", 2))

    def test_edt_account_type_default(self):
        """Первое значение системного перечисления в списке выбора EDT пишет пустым тегом (вид счета «Активный»)."""
        text = """<?xml version="1.0" encoding="UTF-8"?>
<form:Form xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:form="http://g5.1c.ru/v8/dt/form">
  <items xsi:type="form:FormField">
    <name>Вид</name><visible>true</visible><type>RadioButtonField</type>
    <extInfo xsi:type="form:RadioButtonsFieldExtInfo">
      <choiceList><value xsi:type="form:AccountTypeValue"/></choiceList>
      <choiceList><value xsi:type="form:AccountTypeValue"><value>Passive</value></value></choiceList>
    </extInfo>
  </items>
</form:Form>
"""
        with tempfile.TemporaryDirectory(prefix="formmockup-import-") as folder:
            path = Path(folder) / "Form.form"
            path.write_text(text, encoding="utf-8")
            model = import_form(path)[0]
        values = [item if not isinstance(item, dict) else item.get("value") for item in model["form"]["items"][0]["choiceList"]]
        self.assertEqual(values, ["Active", "Passive"])


if __name__ == "__main__":
    unittest.main()
