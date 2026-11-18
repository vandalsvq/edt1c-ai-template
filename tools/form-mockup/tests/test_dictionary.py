"""Словарь русских названий и справочник модели."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import DICTIONARY_PATH, SCHEMA_PATH  # noqa: E402
from fmlib.dictionary import load_dictionary, missing_terms, schema_terms, translate  # noqa: E402
from fmlib.schema import SchemaError, SchemaValidator  # noqa: E402

MODEL_MD = ROOT / "schema" / "model.md"
CLI = ROOT / "formmockup.py"


class DictionaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = SchemaValidator.from_file(SCHEMA_PATH)
        cls.dictionary = load_dictionary(DICTIONARY_PATH)

    def test_dictionary_is_complete(self):
        self.assertEqual(missing_terms(self.validator, self.dictionary), [])

    def test_dictionary_has_no_stale_terms(self):
        kinds, properties, values = schema_terms(self.validator)
        self.assertEqual(set(self.dictionary["types"]) - kinds, set())
        self.assertEqual(set(self.dictionary["properties"]) - properties, set())
        for prop, mapping in self.dictionary["values"].items():
            self.assertEqual(set(mapping) - values.get(prop, set()), set(), prop)

    def test_english_to_russian(self):
        self.assertIn("titleLocation - Положение заголовка (свойство)",
                      translate(self.dictionary, "titleLocation"))
        self.assertIn("InputField - Поле ввода (вид)", translate(self.dictionary, "InputField"))
        self.assertIn("titleLocation=None - Положение заголовка = Нет",
                      translate(self.dictionary, "titleLocation=None"))

    def test_russian_to_english(self):
        self.assertIn("InputField - Поле ввода (вид)", translate(self.dictionary, "поле ввода"))
        self.assertIn("group=Horizontal - Группировка = Горизонтальная",
                      translate(self.dictionary, "Группировка=Горизонтальная"))

    def test_value_lists_all_properties(self):
        lines = translate(self.dictionary, "None")
        self.assertTrue(any("titleLocation" in line and "representation" in line for line in lines), lines)

    def test_platform_mark(self):
        lines = translate(self.dictionary, "note", self.validator.platform_mark)
        self.assertEqual(len(lines), 1)
        self.assertIn("(свойство; нет в 1С: ", lines[0])
        lines = translate(self.dictionary, "Свернута", self.validator.platform_mark)
        self.assertIn("в 1С не напрямую: ", lines[0])
        self.assertIn("collapsed - Свернута (свойство)",
                      translate(self.dictionary, "collapsed"))
        self.assertIn("title - Заголовок (свойство)",
                      translate(self.dictionary, "title", self.validator.platform_mark))

    def test_unknown_word(self):
        self.assertEqual(translate(self.dictionary, "НетТакогоСлова"), [])

    def test_ru_command(self):
        ok = subprocess.run([sys.executable, str(CLI), "ru", "titleLocation", "Поле ввода"],
                            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(ok.returncode, 0)
        self.assertIn("Положение заголовка", ok.stdout)
        self.assertIn("InputField", ok.stdout)
        missing = subprocess.run([sys.executable, str(CLI), "ru", "НетТакогоСлова"],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(missing.returncode, 1)


class PlatformRegistryTest(unittest.TestCase):
    """Реестр `x-platform`: только свойства схемы, каждое в одной группе, с пояснением."""

    def schema(self, registry):
        return {"properties": {"note": {"type": "string"}, "title": {"type": "string"}},
                "x-platform": registry}

    def test_registry_loads(self):
        validator = SchemaValidator(self.schema({"model": {"note": "для ТЗ"}}))
        self.assertEqual(validator.platform_mark("note"), "нет в 1С: для ТЗ")
        self.assertEqual(validator.platform_mark("title"), "")

    def test_registry_errors(self):
        bad = [
            {"other": {}},
            {"model": ["note"]},
            {"model": {"nosuch": "текст"}},
            {"model": {"note": "а"}, "indirect": {"note": "б"}},
            {"model": {"note": ""}},
        ]
        for registry in bad:
            with self.subTest(registry=registry), self.assertRaises(SchemaError):
                SchemaValidator(self.schema(registry))

    def test_registry_only_at_root(self):
        with self.assertRaises(SchemaError):
            SchemaValidator({"$defs": {"a": {"x-platform": {}}}})


class ModelReferenceTest(unittest.TestCase):
    """Справочник `model.md` называет каждый вид и свойство схемы."""

    def test_reference_covers_schema(self):
        kinds, properties, _ = schema_terms(SchemaValidator.from_file(SCHEMA_PATH))
        mentioned = set(re.findall(r"`([A-Za-z]+)`", MODEL_MD.read_text(encoding="utf-8")))
        self.assertEqual(sorted(kinds - mentioned), [])
        self.assertEqual(sorted(properties - mentioned), [])

    def test_reference_lists_platform_registry(self):
        """Раздел «Свойства вне платформы» - ровно реестр `x-platform`, по группам."""
        text = MODEL_MD.read_text(encoding="utf-8")
        section = text.split("## Свойства вне платформы", 1)[1].split("\n## ", 1)[0]
        model_part, indirect_part = section.split("**В 1С не напрямую**", 1)
        listed = {
            "model": set(re.findall(r"^\| `(\w+)` \|", model_part, re.M)),
            "indirect": set(re.findall(r"^\| `(\w+)` \|", indirect_part, re.M)),
        }
        registry = SchemaValidator.from_file(SCHEMA_PATH).platform
        for group in listed:
            expected = {prop for prop, (where, _) in registry.items() if where == group}
            self.assertEqual(listed[group], expected, group)


if __name__ == "__main__":
    unittest.main()
