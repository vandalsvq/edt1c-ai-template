#!/usr/bin/env python3
"""Сравнение двух собранных файлов 1С (epf, erf, cfe) по содержимому

Каждый файл выгружается утилитой ibcmd (`infobase config export`) в XML во временной
базе, идентификаторы (uuid) заменяются порядковыми метками в порядке первого
появления, деревья сравниваются пофайлово. Так сборка утилитой (1cedtcli, ibcmd, скрипт
поставки) сверяется с эталоном конфигуратора из тех же исходников: uuid у объектов при каждой
сборке свои, а содержимое должно совпасть.

Работает на Windows, Linux и macOS; нужен Python 3.9+ и установленная платформа
с утилитой ibcmd.

Использование:
    python3 tools/build-diff/build-diff.py A.epf B.epf
    python3 tools/build-diff/build-diff.py A.cfe B.cfe --ibcmd /opt/1cv8/x86_64/8.3.27.2214/ibcmd
    python3 tools/build-diff/build-diff.py A.cfe B.cfe --keep       оставить выгрузки для разбора
    python3 tools/build-diff/build-diff.py --xml КаталогА КаталогБ    сравнить готовые выгрузки

Код возврата: 0 - совпадают, 1 - есть расхождения, 2 - ошибка запуска или выгрузки.
Путь к утилите: ключ --ibcmd, иначе переменная IBCMD, иначе самая новая версия
в стандартных каталогах установки платформы.
"""

import argparse
import difflib
import glob
import itertools
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile

ШАБЛОН_UUID = re.compile(rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
НУЛЕВОЙ_UUID = b"00000000-0000-0000-0000-000000000000"
ТЕКСТОВЫЕ = (".xml", ".bsl", ".txt", ".html", ".json")
# Служебный файл выгрузки: версии объектов меняются при каждой сборке.
ИСКЛЮЧАЕМЫЕ = {"ConfigDumpInfo.xml"}
# Против базы с пользователями утилита бесконечно спрашивает имя - не ждать вечно.
ТАЙМАУТ_СЕКУНД = 600


def каталоги_установки():
    if sys.platform.startswith("win"):
        корни = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        return [os.path.join(корень, "1cv8", "*", "bin", "ibcmd.exe") for корень in корни]
    return ["/opt/1cv8/x86_64/*/ibcmd", "/opt/1cv8/aarch64/*/ibcmd", "/opt/1cv8/*/ibcmd"]


def ключ_версии(путь):
    каталог = os.path.dirname(путь)
    if os.path.basename(каталог).lower() == "bin":
        каталог = os.path.dirname(каталог)
    return [int(часть) if часть.isdigit() else 0 for часть in os.path.basename(каталог).split(".")]


def найти_утилиту(явный_путь):
    путь = явный_путь or os.environ.get("IBCMD")
    if путь:
        return путь
    найденные = [файл for шаблон in каталоги_установки() for файл in glob.glob(шаблон)]
    if not найденные:
        raise RuntimeError("утилита ibcmd не найдена: укажите --ibcmd или IBCMD")
    return max(найденные, key=ключ_версии)


def декодировать(данные):
    # Кодировка вывода утилиты на Windows не выяснена до конца: показываем, какая подошла.
    for кодировка in ("utf-8", "cp866", locale.getpreferredencoding(False)):
        try:
            return данные.decode(кодировка), кодировка
        except UnicodeDecodeError:
            continue
    return данные.decode("utf-8", errors="replace"), "utf-8 с заменой"


def запустить(утилита, *параметры):
    команда = " ".join(itertools.takewhile(lambda параметр: not параметр.startswith("-"), параметры))
    try:
        результат = subprocess.run([утилита, *параметры], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=ТАЙМАУТ_СЕКУНД)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ibcmd {} - не завершилась за {} с".format(команда, ТАЙМАУТ_СЕКУНД))
    текст, кодировка = декодировать(результат.stdout + результат.stderr)
    if результат.returncode != 0:
        raise RuntimeError("ibcmd {} - код {}, вывод ({}):\n{}".format(
            команда, результат.returncode, кодировка, текст.strip()))


def выгрузить(утилита, файл, каталог_данных, каталог, потоки):
    # Для обработки и отчёта утилита пишет корневой файл рядом с каталогом (<путь>.xml),
    # для расширения - Configuration.xml внутрь каталога. Внешний каталог держит оба случая.
    запустить(утилита, "infobase", "config", "export", "--data=" + каталог_данных,
              "--file=" + os.path.abspath(файл), "--threads={}".format(потоки), os.path.join(каталог, "root"))


def прочитать_дерево(корень):
    файлы = {}
    for каталог, _, имена in os.walk(корень):
        for имя in имена:
            if имя in ИСКЛЮЧАЕМЫЕ:
                continue
            полный = os.path.join(каталог, имя)
            with open(полный, "rb") as поток:
                файлы[os.path.relpath(полный, корень).replace(os.sep, "/")] = поток.read()
    return файлы


def нормализовать(файлы):
    метки = {}

    def заменить(совпадение):
        uuid = совпадение.group(0).lower()
        if uuid == НУЛЕВОЙ_UUID:
            return uuid
        if uuid not in метки:
            метки[uuid] = "uuid-{:05d}".format(len(метки) + 1).encode()
        return метки[uuid]

    return {путь: ШАБЛОН_UUID.sub(заменить, данные) if путь.lower().endswith(ТЕКСТОВЫЕ) else данные
            for путь, данные in sorted(файлы.items())}


def сравнить(корень_а, корень_б, строк_на_файл):
    а = нормализовать(прочитать_дерево(корень_а))
    б = нормализовать(прочитать_дерево(корень_б))
    только_а = sorted(set(а) - set(б))
    только_б = sorted(set(б) - set(а))
    разные = [путь for путь in sorted(set(а) & set(б)) if а[путь] != б[путь]]
    for путь in только_а:
        print("только в A: " + путь)
    for путь in только_б:
        print("только в B: " + путь)
    for путь in разные:
        print("различается: " + путь)
        if not путь.lower().endswith(ТЕКСТОВЫЕ):
            continue
        строки_а = а[путь].decode("utf-8-sig", errors="replace").splitlines()
        строки_б = б[путь].decode("utf-8-sig", errors="replace").splitlines()
        разница = list(difflib.unified_diff(строки_а, строки_б, "A/" + путь, "B/" + путь, lineterm="", n=1))
        for строка in разница[:строк_на_файл]:
            print("    " + строка)
        if len(разница) > строк_на_файл:
            print("    ... ещё строк: {}".format(len(разница) - строк_на_файл))
    print("файлов: A {}, B {}; расхождений: {}".format(len(а), len(б), len(только_а) + len(только_б) + len(разные)))
    return 0 if not (только_а or только_б or разные) else 1


def главная():
    разбор = argparse.ArgumentParser(description="Сравнение собранных файлов 1С по содержимому")
    разбор.add_argument("a", help="первый файл (или каталог выгрузки с --xml)")
    разбор.add_argument("b", help="второй файл (или каталог выгрузки с --xml)")
    разбор.add_argument("--xml", action="store_true", help="сравнить готовые выгрузки, без утилиты")
    разбор.add_argument("--ibcmd", help="путь к утилите ibcmd")
    разбор.add_argument("--threads", type=int, default=1, help="потоки выгрузки (по умолчанию 1)")
    разбор.add_argument("--keep", action="store_true", help="не удалять рабочий каталог")
    разбор.add_argument("--lines", type=int, default=40, help="строк разницы на файл")
    параметры = разбор.parse_args()

    if параметры.xml:
        return сравнить(параметры.a, параметры.b, параметры.lines)

    рабочий = tempfile.mkdtemp(prefix="build-diff-")
    try:
        утилита = найти_утилиту(параметры.ibcmd)
        print("утилита: " + утилита)
        данные = os.path.join(рабочий, "data")
        запустить(утилита, "infobase", "create", "--data=" + данные)
        for сторона, файл in (("A", параметры.a), ("B", параметры.b)):
            выгрузить(утилита, файл, данные, os.path.join(рабочий, сторона), параметры.threads)
        return сравнить(os.path.join(рабочий, "A"), os.path.join(рабочий, "B"), параметры.lines)
    except (RuntimeError, OSError) as ошибка:
        print("ошибка: {}".format(ошибка), file=sys.stderr)
        return 2
    finally:
        if параметры.keep:
            print("рабочий каталог: " + рабочий)
        else:
            shutil.rmtree(рабочий, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(главная())
