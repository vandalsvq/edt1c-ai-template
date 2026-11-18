"""Эталон снимков `render`: переделка рендерера под конструктор не меняет PNG.

Эталон - хеши снимков примеров, витрины и правок в `fixtures/baseline-<ОС>.json` (`darwin`,
`win32`), снятые до переделки рендерера. У каждой ОС свой эталон: та же версия Chrome на
Windows сглаживает шрифты иначе, чем на Mac, и снятый там эталон не должен затирать маковский. Снимок Chrome одной версии повторяется байт в байт; хеш разошелся -
снимок сверяется с эталоном по пикселям (другой кодировщик PNG при тех же пикселях не
ошибка), сам снимок остается во временном каталоге для разбора.

Эталон привязан к версии Chrome: на другой версии тест пропускается с подсказкой; на Edge
(запасной движок, если Chrome нет) - тоже пропускается. Снять
эталон заново (новый Chrome или осознанная правка вида):

    FORMMOCKUP_BASELINE=update python3 -m unittest discover -s tools/form-mockup/tests -p test_baseline.py

Снятый эталон кладет в `fixtures/baseline-<ОС>/` и сами снимки (каталог в .gitignore) - для
сверки по пикселям на этой машине.
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmlib import render  # noqa: E402
from support import temp_dir  # noqa: E402

CLI = ROOT / "formmockup.py"
MANIFEST = ROOT / "tests" / "fixtures" / f"baseline-{sys.platform}.json"
SHOTS = ROOT / "tests" / "fixtures" / f"baseline-{sys.platform}"
CHROME, _ = render.find_chrome()

# Каталог снимков → аргументы `render` после модели
CASES = {
    "zakaz": ["examples/zakaz-pokupatelya.json"],
    "spisok": ["examples/spisok-zakazov.json"],
    "vitrina": ["tests/fixtures/vitrina.json"],
    "pravki": ["examples/pravki/zakaz-pokupatelya-stalo.json", "--before", "examples/zakaz-pokupatelya.json"],
}


def shoot(folder: Path) -> dict:
    """Снимки всех случаев: относительное имя → путь."""
    shots = {}
    for case, arguments in CASES.items():
        output = folder / case
        command = [sys.executable, str(CLI), "render", str(ROOT / arguments[0]), "-o", str(output), "--png"]
        command += [str(ROOT / item) if item.endswith(".json") else item for item in arguments[1:]]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode not in (0, 1):
            raise AssertionError(f"render {case}: код {result.returncode}\n{result.stdout}{result.stderr}")
        for path in sorted(output.glob("*.png")):
            # Снимки примечаний - не эталон: основной вид не меняется, номера проверяет NotesTest
            if "__примечания" not in path.name:
                shots[f"{case}/{path.name}"] = path
    return shots


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(path: Path):
    """Размер и строки пикселей PNG (8 бит, без чересстрочности) - декодер на стандартной библиотеке."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: не PNG")
    position = 8
    header = None
    chunks = []
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or interlace:
        raise ValueError(f"{path}: глубина {depth}, чересстрочность {interlace} - декодер не умеет")
    step = {2: 3, 6: 4, 0: 1, 4: 2}[color]
    raw = zlib.decompress(b"".join(chunks))
    stride = width * step
    rows = []
    previous = bytearray(stride)
    for index in range(height):
        start = index * (stride + 1)
        kind = raw[start]
        line = bytearray(raw[start + 1:start + 1 + stride])
        for x in range(stride):
            left = line[x - step] if x >= step else 0
            up = previous[x]
            corner = previous[x - step] if x >= step else 0
            if kind == 1:
                line[x] = (line[x] + left) & 255
            elif kind == 2:
                line[x] = (line[x] + up) & 255
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min((abs(guess - left), 0, left), (abs(guess - up), 1, up), (abs(guess - corner), 2, corner))
                line[x] = (line[x] + near[2]) & 255
        rows.append(bytes(line))
        previous = line
    return (width, height, step), rows


@unittest.skipUnless(CHROME, "Chrome не найден")
class BaselineTest(unittest.TestCase):
    def test_render_matches_baseline(self):
        if render.is_edge(CHROME):
            self.skipTest(f"снимки рисует Edge ({CHROME}), эталон снят на Chrome")
        version = render.browser_version(CHROME)
        self.assertTrue(version, f"версия браузера не прочиталась: {CHROME}")
        folder = Path(temp_dir(prefix="formmockup-baseline-"))
        shots = shoot(folder)
        if os.environ.get("FORMMOCKUP_BASELINE") == "update":
            MANIFEST.write_text(json.dumps({"chrome": version, "shots": {name: digest(path) for name, path in shots.items()}},
                                           ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            shutil.rmtree(SHOTS, ignore_errors=True)
            for name, path in shots.items():
                (SHOTS / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(path, SHOTS / name)
            self.skipTest(f"эталон снят заново: {len(shots)} снимков, {version}")
        if not MANIFEST.is_file():
            self.skipTest(f"эталона для {sys.platform} нет - снять (FORMMOCKUP_BASELINE=update)")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest["chrome"] != version:
            self.skipTest(f"эталон снят на {manifest['chrome']}, здесь {version} - снять заново (FORMMOCKUP_BASELINE=update)")
        self.assertEqual(sorted(shots), sorted(manifest["shots"]), "состав снимков разошелся с эталоном")
        broken = []
        for name, path in shots.items():
            if digest(path) == manifest["shots"][name]:
                continue
            reference = SHOTS / name
            if reference.is_file() and digest(reference) == manifest["shots"][name] and pixels(reference) == pixels(path):
                continue
            broken.append(f"{name}: {path}")
        self.assertEqual(broken, [], f"снимки разошлись с эталоном (сравнить с {SHOTS})")
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
