"""Сверка собранной формы с макетом (`compare`): нормализация, умолчания, уточнения, отметка «заполняется кодом».

Фикстуры - нейтральные модели в коде теста и форма EDT `fixtures/import/edt` (ВитринаЭлементов).
"""

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import DICTIONARY_PATH, SCHEMA_PATH  # noqa: E402
from fmlib.dictionary import load_dictionary  # noqa: E402
from fmlib.importer import import_form  # noqa: E402
from fmlib.model import check  # noqa: E402
from fmlib.reconcile import reconcile, report  # noqa: E402
from fmlib.schema import SchemaValidator  # noqa: E402
from fmlib.tables import elements_table  # noqa: E402
from support import temp_dir  # noqa: E402

CLI = ROOT / "formmockup.py"
VITRINA = ROOT / "tests" / "fixtures" / "import" / "edt" / "DataProcessors" / "ВитринаЭлементов" / "Forms" / "Форма" / \
    "Form.form"
DICTIONARY = load_dictionary(DICTIONARY_PATH)
VALIDATOR = SchemaValidator.from_file(SCHEMA_PATH)


def field(name, **props):
    return dict({"type": "InputField", "name": name}, **props)


def radio(name, **props):
    return dict({"type": "RadioButtonField", "name": name}, **props)


def group(name, items, **props):
    return dict({"type": "UsualGroup", "name": name, "items": items}, **props)


def table(name, columns, **props):
    return dict({"type": "Table", "name": name, "dataPath": name, "items": columns}, **props)


def model(*items, **form):
    return {"version": 1, "form": dict({"title": "Заявка", "items": list(items)}, **form)}


def run(mockup, form):
    return reconcile(mockup, form, DICTIONARY)


def details(result) -> list:
    return [(change.name, change.what, change.details) for change in result.changes]


class NormalizationTest(unittest.TestCase):
    """Шум, который не отличие: свойства ТЗ, запись одного и того же по-разному."""

    def test_same_form_no_changes(self):
        mockup = model(field("Номер", title="Номер заявки"))
        result = run(mockup, copy.deepcopy(mockup))
        self.assertEqual(result.changes, [])
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.refinements, [])

    def test_note_and_sample_not_compared(self):
        mockup = model(field("Номер", sample="0001", note="номер присваивает система"), note="форма заявки")
        result = run(mockup, model(field("Номер")))
        self.assertEqual(details(result), [])

    def test_choice_list_by_presentation(self):
        mockup = model(radio("Срочность", choiceList=["Обычная", "Срочная"]))
        form = model(radio("Срочность", choiceList=[{"value": "Обычная", "presentation": "Обычная"},
                                                    {"value": "Срочно", "presentation": "Срочная"}]))
        self.assertEqual(details(run(mockup, form)), [])
        # Другое представление - отличие
        form["form"]["items"][0]["choiceList"][1]["presentation"] = "Очень срочная"
        self.assertEqual([name for name, _, _ in details(run(mockup, form))], ["Срочность"])

    def test_choice_list_value_without_presentation(self):
        mockup = model(radio("Срочность", choiceList=["Обычная"]))
        form = model(radio("Срочность", choiceList=[{"value": "Обычная"}]))
        self.assertEqual(details(run(mockup, form)), [])

    def test_excluded_commands_without_order(self):
        mockup = model(table("Товары", [field("ТоварыНоменклатура")], excludedCommands=["Add", "Copy"]))
        form = model(table("Товары", [field("ТоварыНоменклатура")], excludedCommands=["Copy", "Add"]))
        self.assertEqual(details(run(mockup, form)), [])

    def test_title_by_name_equals_own_title(self):
        """Заголовок, как его видит пользователь: имя по словам в макете и тот же текст своим заголовком в форме."""
        mockup = model(field("СрокИсполнения"))
        form = model(field("СрокИсполнения", title="Срок исполнения"))
        result = run(mockup, form)
        self.assertEqual(details(result), [])
        self.assertEqual(result.refinements, [])

    def test_inputs_not_changed(self):
        mockup = model(field("Номер", note="примечание", generated="title", title="Пример"))
        form = model(field("Номер", toolTip="подсказка"))
        before = json.dumps([mockup, form], ensure_ascii=False, sort_keys=True)
        run(mockup, form)
        self.assertEqual(json.dumps([mockup, form], ensure_ascii=False, sort_keys=True), before)


class DefaultsTest(unittest.TestCase):
    """Умолчание платформы - таблица `defaults` в `property-groups.json`."""

    def test_explicit_default_equals_missing(self):
        mockup = model(group("Шапка", [field("Номер")], group="Vertical"),
                       commandBar={"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель", "autoFill": True})
        form = model(group("Шапка", [field("Номер")]),
                     commandBar={"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель"})
        self.assertEqual(details(run(mockup, form)), [])
        # И наоборот: умолчание, записанное в форме, - ни отличие, ни уточнение
        result = run(form, mockup)
        self.assertEqual(details(result), [])
        self.assertEqual(result.refinements, [])

    def test_default_against_other_value_is_change(self):
        mockup = model(commandBar={"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель", "autoFill": True})
        form = model(commandBar={"type": "AutoCommandBar", "name": "ФормаКоманднаяПанель", "autoFill": False})
        changes = details(run(mockup, form))
        self.assertEqual(changes, [("ФормаКоманднаяПанель", "Изменен", ["Автозаполнение: Да → Нет"])])

    def test_not_default_missing_in_form_is_change(self):
        mockup = model(table("Товары", [field("ТоварыНоменклатура")], heightInTableRows=6))
        form = model(table("Товары", [field("ТоварыНоменклатура")]))
        changes = details(run(mockup, form))
        self.assertEqual(changes, [("Товары", "Изменен", ["Высота в строках таблицы: 6 → не задано"])])


class RefinementTest(unittest.TestCase):
    """Уточнение - свойство формы, которого нет у пары в макете."""

    def test_form_only_property_is_refinement(self):
        mockup = model(field("Номер"))
        form = model(field("Номер", toolTip="Номер по журналу", inputHint="Новый"))
        result = run(mockup, form)
        self.assertEqual(details(result), [])
        self.assertEqual([(item.name, item.props) for item in result.refinements],
                         [("Номер", ["Подсказка: «Номер по журналу»", "Подсказка ввода: «Новый»"])])

    def test_form_root_refinement(self):
        result = run(model(), model(autoTitle=False))
        self.assertEqual([(item.name, item.props) for item in result.refinements], [("Форма", ["Авто заголовок: Нет"])])

    def test_mockup_property_missing_in_form_is_change(self):
        mockup = model(field("Номер", readOnly=True))
        result = run(mockup, model(field("Номер")))
        self.assertEqual(details(result), [("Номер", "Изменен", ["Только просмотр: Да → не задано"])])
        self.assertEqual(result.refinements, [])

    def test_different_value_is_change_not_refinement(self):
        result = run(model(field("Номер", toolTip="Номер")), model(field("Номер", toolTip="Номер заявки")))
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.refinements, [])


class PairsTest(unittest.TestCase):
    """Пары - по имени и `renamedFrom`; добавленный, удаленный и перенесенный элементы - отличия."""

    def test_added_removed_moved(self):
        mockup = model(group("Шапка", [field("Номер"), field("Дата")]), field("Комментарий"))
        form = model(group("Шапка", [field("Номер")]), field("Дата"), field("Ответственный"))
        whats = {name: what for name, what, _ in details(run(mockup, form))}
        self.assertEqual(whats, {"Дата": "Перенесен", "Ответственный": "Добавлен", "Комментарий": "Удален"})

    def test_renamed_from(self):
        mockup = model(field("Описание"))
        form = model(field("Комментарий", renamedFrom="Описание", title="Описание"))
        self.assertEqual(details(run(mockup, form)), [("Комментарий", "Изменен", ["Имя: Описание → Комментарий"])])


class GeneratedTest(unittest.TestCase):
    """Отметка `generated`: элемент целиком и заголовок, которые заполняет код."""

    def test_element_missing_in_form(self):
        mockup = model(table("Товары", [field("ТоварыНоменклатура"), field("ТоварыСклад", generated="element")]))
        form = model(table("Товары", [field("ТоварыНоменклатура")]))
        result = run(mockup, form)
        self.assertEqual(details(result), [])
        self.assertEqual([(item.name, item.what, item.found) for item in result.skipped],
                         [("ТоварыСклад", "element", "нет")])

    def test_element_present_in_form_without_changes(self):
        mockup = model(field("Отбор", generated="element", width=20), field("Номер"))
        form = model(field("Номер"), field("Отбор", width=40, toolTip="отбор"))
        result = run(mockup, form)
        self.assertEqual(details(result), [])
        self.assertEqual(result.refinements, [])
        self.assertEqual([(item.name, item.found) for item in result.skipped], [("Отбор", "есть")])

    def test_element_with_children(self):
        """Группа кода целиком: ее элементы не ищутся отдельно и не попадают в отличия."""
        mockup = model(group("Отбор", [field("ОтборАвтор"), field("ОтборДата", generated="element")],
                             generated="element"))
        result = run(mockup, model())
        self.assertEqual(details(result), [])
        self.assertEqual([item.name for item in result.skipped], ["Отбор"])

    def test_without_mark_missing_is_change(self):
        mockup = model(table("Товары", [field("ТоварыНоменклатура"), field("ТоварыСклад")]))
        form = model(table("Товары", [field("ТоварыНоменклатура")]))
        self.assertEqual([(name, what) for name, what, _ in details(run(mockup, form))], [("ТоварыСклад", "Удален")])

    def test_unmarked_added_is_change(self):
        mockup = model(field("Номер"))
        form = model(field("Номер"), field("Склад"))
        self.assertEqual([(name, what) for name, what, _ in details(run(mockup, form))], [("Склад", "Добавлен")])

    def test_title_not_compared(self):
        mockup = model({"type": "LabelDecoration", "name": "Состояние", "title": "Заявка отправлена 05.11",
                        "generated": "title", "hyperlink": True})
        form = model({"type": "LabelDecoration", "name": "Состояние", "title": "Состояние заявки"})
        result = run(mockup, form)
        # Прочие свойства сравниваются как обычно
        self.assertEqual(details(result), [("Состояние", "Изменен", ["Гиперссылка: Да → не задано"])])
        self.assertEqual([(item.what, item.sample, item.found) for item in result.skipped],
                         [("title", "Заявка отправлена 05.11", "Состояние заявки")])

    def test_form_title(self):
        mockup = model(title="Заявка: срочная", generated="title")
        result = run(mockup, model(title="Заявка"))
        self.assertEqual(details(result), [])
        self.assertEqual([(item.name, item.what) for item in result.skipped], [("Форма", "title")])

    def test_report_sections(self):
        mockup = model(field("Номер", generated="title", title="0001"), field("Склад", generated="element"))
        form = model(field("Номер", toolTip="номер"), field("Автор"))
        text = report(run(mockup, form), DICTIONARY)
        sections = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(sections, ["## Отличия", "## Заполняется кодом", "## Уточнения"])
        self.assertIn("| 1 | Автор (`Автор`) | Поле ввода | Добавлен |", text)
        self.assertIn("| Номер (`Номер`) | Поле ввода | заголовок «0001» | «Номер» |", text)
        self.assertIn("| Склад (`Склад`) | Поле ввода | элемент | нет |", text)
        self.assertIn("| Номер (`Номер`) | Поле ввода | Подсказка: «номер» |", text)

    def test_report_empty_sections(self):
        text = report(run(model(field("Номер")), model(field("Номер"))), DICTIONARY)
        self.assertIn("Изменений нет", text)
        self.assertEqual(text.count("\nНет\n"), 2)


class MarkModelTest(unittest.TestCase):
    """Отметка - свойство модели вне платформы: схема, словарь, таблица элементов."""

    def codes(self, data):
        return [issue.code for issue in check(data, VALIDATOR)]

    def test_check_accepts_values(self):
        self.assertEqual(self.codes(model(field("Номер", generated="element"), field("Дата", generated="title"),
                                          generated="title")), [])

    def test_check_rejects_others(self):
        self.assertEqual(self.codes(model(field("Номер", generated="code"))), ["schema"])
        # Корень формы - только заголовок: форму целиком код не создает
        self.assertEqual(self.codes(model(generated="element")), ["schema"])

    def test_platform_registry(self):
        self.assertTrue(VALIDATOR.platform_mark("generated").startswith("нет в 1С"))

    def test_table_shows_mark(self):
        text = elements_table(model(field("Номер", generated="element")), DICTIONARY)
        self.assertIn("Заполняется кодом: Элемент", text)

    def test_ru(self):
        result = subprocess.run([sys.executable, str(CLI), "ru", "generated=title", "Заполняется кодом"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("generated=title - Заполняется кодом = Заголовок", result.stdout)
        self.assertIn("generated - Заполняется кодом (свойство; нет в 1С", result.stdout)


class CliTest(unittest.TestCase):
    """Команда `compare`: XML формы и модель JSON вторым аргументом, коды 0 / 1 / 2."""

    @classmethod
    def setUpClass(cls):
        cls.folder = temp_dir()
        cls.mockup, _ = import_form(VITRINA)
        cls.same = cls.folder / "vitrina.json"
        cls.same.write_text(json.dumps(cls.mockup, ensure_ascii=False), encoding="utf-8")

    def compare(self, *paths):
        return subprocess.run([sys.executable, str(CLI), "compare", *map(str, paths)],
                              capture_output=True, text=True, encoding="utf-8")

    def write(self, name, data):
        path = self.folder / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_form_xml_same_as_mockup(self):
        result = self.compare(self.same, VITRINA)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Изменений нет", result.stdout)

    def test_changes_code_1(self):
        changed = copy.deepcopy(self.mockup)
        changed["form"]["title"] = "Другой заголовок"
        result = self.compare(self.write("changed.json", changed), VITRINA)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Заголовок: «Другой заголовок» →", result.stdout)

    def test_model_json_as_form(self):
        result = self.compare(self.write("a.json", model(field("Номер"))), self.write("b.json", model(field("Номер"))))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_errors_code_2(self):
        not_form = ROOT / "tests" / "fixtures" / "import" / "not-form.xml"
        self.assertEqual(self.compare(self.same, not_form).returncode, 2)
        self.assertEqual(self.compare(self.folder / "missing.json", VITRINA).returncode, 2)
        broken = self.write("broken.json", model(field("Номер"), field("Номер")))
        result = self.compare(broken, VITRINA)
        self.assertEqual(result.returncode, 2)
        self.assertIn("макет: ", result.stdout)


if __name__ == "__main__":
    unittest.main()
