"""Картинки для макета: имя → data URI.

Импорт кладет в модель картинки, на которые ссылаются элементы (`pictures`), чтобы HTML
макета оставался одним файлом. Общие картинки - из исходников конфигурации: из нескольких
вариантов (`Picture.zip` с манифестом) берется вариант «Такси» для масштаба 100 %: плотность
`ldpi`, без `interfaceVariant`. Стандартные - из выгрузки платформы (код
`1c/ВыгрузитьСтандартныеКартинки.bsl`, файл `<Имя>.<формат>`): по умолчанию архив
`std-pictures.zip` рядом с инструментом, указанный каталог или архив его заменяет; картинки
нет в выгрузке - рендерер рисует ее своим значком или заглушкой.
"""

from __future__ import annotations

import base64
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

MIME = {".png": "image/png", ".svg": "image/svg+xml", ".gif": "image/gif", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".bmp": "image/bmp", ".ico": "image/x-icon"}
PREFIX = "CommonPicture."
STD_PREFIX = "StdPicture."
# Выгрузка по умолчанию: стандартные картинки платформы 8.3 (выгрузка владельца 31.10.2026)
BUNDLED = Path(__file__).resolve().parent.parent / "std-pictures.zip"
# Стандартные картинки, которые рендерер рисует сам: кнопки поля ввода и стандартные кнопки таблиц
RENDER_STD = ("InputFieldSelect", "InputFieldCalendar", "InputFieldCalculator", "InputFieldOpen",
              "InputFieldClear", "MoveUp", "MoveDown", "Change", "MarkToDelete", "CloneListItem",
              # пункты меню «Еще» таблицы и формы, которые рендерер добавляет при автозаполнении
              "CreateListItem", "Delete", "EndEdit", "Find", "CancelSearch", "SortListAsc", "SortListDesc", "OutputList",
              "SearchControl", "WriteAndClose", "Write", "Post", "UndoPosting", "Reread", "CloneObject", "ShowInList",
              "DataHistory", "CustomizeForm", "Help")
# Сигнатуры форматов: выгрузка пишет неопознанный формат с расширением .bin
SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF8", "image/gif"), (b"\xff\xd8", "image/jpeg"),
              (b"BM", "image/bmp"), (b"\x00\x00\x01\x00", "image/x-icon"))
LIMIT = 64 * 1024          # крупнее - не значок: в модель не кладется, рисуется заглушкой


def folder_of(src: Path, edt: bool, name: str) -> Path:
    base = src / "CommonPictures" / name
    return base if edt else base / "Ext" / "Picture"


def data_uri(name: str, content: bytes):
    mime = MIME.get(Path(name).suffix.lower())
    if not mime or not content or len(content) > LIMIT:
        return None
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


def from_zip(path: Path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            chosen = None
            if "manifest.xml" in names:
                manifest = ET.fromstring(archive.read("manifest.xml"))
                variants = [item for item in manifest.iter("PictureVariant") if not item.get("interfaceVariant")]
                for density in ("ldpi", "bldpi", "aldpi", "mdpi"):
                    chosen = next((item.get("name") for item in variants if item.get("screenDensity") == density), None)
                    if chosen:
                        break
                if not chosen and variants:
                    chosen = variants[0].get("name")
            if not chosen:
                chosen = next((item for item in names if Path(item).suffix.lower() in MIME), None)
            if not chosen or chosen not in names:
                return None
            return data_uri(chosen, archive.read(chosen))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError):
        return None


def load(src: Path | None, edt: bool, picture: str):
    """`CommonPicture.Имя` → data URI или None (картинки нет в исходниках или она не значок)."""
    if not src or not picture.startswith(PREFIX):
        return None
    folder = folder_of(src, edt, picture[len(PREFIX):])
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir()):
        if path.name.startswith("Picture."):
            if path.suffix.lower() == ".zip":
                return from_zip(path)
            if path.suffix.lower() in MIME:
                return data_uri(path.name, path.read_bytes())
    return None


def sniff(content: bytes):
    """MIME по содержимому файла; None - не картинка."""
    for signature, mime in SIGNATURES:
        if content.startswith(signature):
            return mime
    head = content[:512].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in content[:2048]):
        return "image/svg+xml"
    return None


def std_files(source: Path | None) -> dict:
    """Выгрузка стандартных картинок - каталог или zip-архив: имя картинки → функция чтения файла."""
    if not source:
        return {}
    if source.is_dir():
        return {path.stem: path.read_bytes for path in sorted(source.iterdir()) if path.is_file()}
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError):
        return {}
    return {Path(name).stem: (lambda name=name: archive.read(name))
            for name in archive.namelist() if not name.endswith("/") and "/" not in name}


def load_std(files: dict, picture: str):
    """`StdPicture.Имя` → data URI из выгрузки (`std_files`) или None."""
    if not picture.startswith(STD_PREFIX):
        return None
    read = files.get(picture[len(STD_PREFIX):])
    if read is None:
        return None
    content = read()
    mime = sniff(content)
    if mime and len(content) <= LIMIT:
        return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
    return None


def std_source(explicit: str | None = None):
    """Выгрузка стандартных картинок: параметр, иначе FORMMOCKUP_STD_PICTURES, иначе архив инструмента."""
    import os
    value = explicit or os.environ.get("FORMMOCKUP_STD_PICTURES")
    if value:
        return Path(value)
    return BUNDLED if BUNDLED.is_file() else None


def add_std(found: dict, form: dict, source: Path | None):
    """Дописывает в `found` стандартные картинки `form` (форма или `referencing` модели) и те, что рендерер рисует сам
    (кнопки поля, таблиц, меню «Еще»); уже имеющиеся не трогает. Итог - (найдено, всего)."""
    if not source:
        return 0, 0
    standard = used(form, set(), (STD_PREFIX,)) | {STD_PREFIX + name for name in RENDER_STD}
    files = std_files(source)
    loaded = {name: load_std(files, name) for name in sorted(standard) if not found.get(name)}
    found.update({name: uri for name, uri in loaded.items() if uri})
    return sum(1 for uri in loaded.values() if uri), len(loaded)


def referencing(model: dict) -> dict:
    """Части модели со ссылками на картинки: элементы формы и команды формы."""
    return {"form": model.get("form"), "commands": model.get("commands")}


def used(node, found: set, prefixes=(PREFIX,)):
    """Имена картинок с одним из префиксов, на которые ссылается модель."""
    if isinstance(node, dict):
        for key in ("picture", "headerPicture", "footerPicture", "choiceButtonPicture", "rowsPicture"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith(prefixes):
                found.add(value)
        for item in node.values():
            used(item, found, prefixes)
    elif isinstance(node, list):
        for item in node:
            used(item, found, prefixes)
    return found
