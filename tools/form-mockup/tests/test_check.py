"""Проверка модели `check`: фикстура на правило, примеры чистые."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import SCHEMA_PATH  # noqa: E402
from fmlib.model import check, load_model  # noqa: E402
from fmlib.schema import SchemaError, SchemaValidator  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "check"
EXAMPLES = ROOT / "examples"
CLI = ROOT / "formmockup.py"

# Фикстура → (правило, число замечаний). Фикстура ловит только своё правило.
EXPECTED = {
    "schema": ("schema", 6),
    "foreign-property": ("foreign-property", 1),
    "duplicate-name": ("duplicate-name", 1),
    "empty-container": ("empty-container", 2),
    "single-page": ("single-page", 1),
    "table-no-columns": ("table-no-columns", 1),
    "current-page": ("current-page", 1),
    "too-many-items": ("too-many-items", 1),
    "group-depth": ("group-depth", 1),
    "data-path": ("data-path", 4),
    "style-color": ("style-color", 3),
}


class CheckRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = SchemaValidator.from_file(SCHEMA_PATH)

    def issues(self, path: Path):
        return check(load_model(path), self.validator)

    def test_every_rule_has_fixture(self):
        names = {path.stem for path in FIXTURES.glob("*.json")}
        self.assertEqual(names, set(EXPECTED))

    def test_fixture_catches_only_its_rule(self):
        for name, (code, count) in EXPECTED.items():
            with self.subTest(fixture=name):
                issues = self.issues(FIXTURES / f"{name}.json")
                self.assertEqual({issue.code for issue in issues}, {code})
                self.assertEqual(len(issues), count, [issue.message for issue in issues])

    def test_examples_are_clean(self):
        examples = sorted(EXAMPLES.glob("*.json"))
        self.assertTrue(examples)
        for path in examples:
            with self.subTest(example=path.name):
                self.assertEqual(self.issues(path), [])

    def test_hidden_items_not_counted(self):
        model = json.loads((FIXTURES / "too-many-items.json").read_text(encoding="utf-8"))
        model["form"]["items"][0]["visible"] = False
        self.assertEqual(check(model, self.validator), [])

    def test_data_path_silent_without_attributes(self):
        """Модель без `attributes` - без замечаний о путях, как в ранних версиях модели."""
        model = json.loads((FIXTURES / "data-path.json").read_text(encoding="utf-8"))
        del model["attributes"]
        self.assertEqual(check(model, self.validator), [])

    def test_type_not_string_does_not_crash(self):
        model = {"version": 1, "form": {"items": [
            {"type": {"a": 1}, "name": "Объект"},
            {"type": ["UsualGroup"], "name": "Массив", "items": []},
        ]}}
        issues = check(model, self.validator)
        self.assertEqual([issue.code for issue in issues], ["schema", "schema"])
        self.assertTrue(all("строка" in issue.message for issue in issues))

    def test_unsupported_schema_keyword_rejected(self):
        with self.assertRaises(SchemaError):
            SchemaValidator({"type": "object", "patternProperties": {}})


class CheckCommandTest(unittest.TestCase):
    def run_check(self, path: Path):
        return subprocess.run([sys.executable, str(CLI), "check", str(path)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_exit_codes(self):
        self.assertEqual(self.run_check(EXAMPLES / "zakaz-pokupatelya.json").returncode, 0)
        result = self.run_check(FIXTURES / "duplicate-name.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Группа/Контрагент", result.stdout)

    def test_not_json_is_code_2(self):
        result = self.run_check(Path(__file__))
        self.assertEqual(result.returncode, 2)
        self.assertIn("не JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
