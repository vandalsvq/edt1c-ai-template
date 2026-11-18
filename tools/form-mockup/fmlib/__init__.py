"""Библиотека инструмента макетов форм 1С: модель, проверка, словарь."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "form-model.schema.json"
DICTIONARY_PATH = ROOT / "schema" / "dictionary-ru.json"


def write_text_lf(path: Path, text: str):
    """Текст в UTF-8 с концами строк LF на любой ОС. Байтами: `write_text(newline=)` появился только в Python 3.10,
    а инструмент работает с 3.9."""
    path.write_bytes(text.encode("utf-8"))
