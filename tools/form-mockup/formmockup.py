#!/usr/bin/env python3
"""Макеты управляемых форм 1С для технических заданий.

Модель формы - JSON-дерево элементов с именами видов и свойств как в платформе;
схема - `schema/form-model.schema.json`, справочник - `schema/model.md`, русские
названия - `schema/dictionary-ru.json`. Справочник модели - `schema/model.md`.

Использование:
    python3 tools/form-mockup/formmockup.py import <Form.form | Form.xml> -o model.json [--std-pictures <каталог>]
        модель по XML формы (EDT или выгрузка конфигуратора) и отчет импорта: откуда
        заголовки, заглушки, нераспознанное; код 2 - файл не XML формы. Стандартные картинки
        платформы - из архива std-pictures.zip; своя выгрузка (1c/ВыгрузитьСтандартныеКартинки.bsl,
        каталог или zip) - параметром или FORMMOCKUP_STD_PICTURES
    python3 tools/form-mockup/formmockup.py check model.json
        проверка модели: схема и правила вёрстки; код 1 при замечаниях, 2 - файл не JSON
    python3 tools/form-mockup/formmockup.py render model.json -o <каталог> [--before before.json] [--png] [--state Панель:Закладка]
        HTML макета (+ PNG через headless Chrome), замечания раскладки браузера; модель с
        нарушением схемы или повтором имени не рисуется, остальные замечания правил
        печатаются, но не мешают рисовать. С --before - правки против прежней версии:
        режимы страницы «Правки / Стало / Было», список правок, PNG `<имя>__правки.png`,
        `<имя>__стало.png` и закладки с правками `<имя>__правки__<панель>_<закладка>.png`.
        В модели есть примечания (`note`) - еще PNG с их номерами `<имя>__примечания.png` и
        закладки с примечаниями `<имя>__примечания__<панель>_<закладка>.png` (с --before - по «стало»);
        код 1 при замечаниях модели или раскладки, 3 - Chrome не найден, а нужен PNG
    python3 tools/form-mockup/formmockup.py table model.json [--before before.json]
        таблица для ТЗ в Markdown русскими названиями: элементов формы (с примечаниями - колонка
        «№», номер как на снимке примечаний) или, с --before, изменений (номер - как на рисунке
        правок); код 1 - модель с нарушением схемы
    python3 tools/form-mockup/formmockup.py compare <макет.json> <Form.form | Form.xml | модель.json>
        сверка собранной формы с макетом: XML формы импортируется, как у import, без записи файла; Markdown
        тремя разделами - «Отличия» (таблица изменений «макет → форма», как у table --before), «Заполняется
        кодом» (что сверка пропустила по отметке generated макета и что в форме на этом месте), «Уточнения»
        (свойства формы, которых нет у элемента в макете). Не сравниваются свойства только для ТЗ (note,
        sample); список выбора - по представлениям, состав команд - без порядка, умолчание платформы равно
        незаданному свойству. Код 0 - отличий нет (места кода и уточнения не в счет), 1 - есть,
        2 - файл не открыть, не модель или не XML формы, модель с нарушением схемы
    python3 tools/form-mockup/formmockup.py ru titleLocation "Поле ввода" titleLocation=None
        перевод по словарю в обе стороны; у свойства вне платформы - пометка «нет в 1С» или
        «в 1С не напрямую» с пояснением; код 1, если слово не найдено
    python3 tools/form-mockup/formmockup.py serve <папка|model.json> [--port N] [--no-browser] [--new [--kind <formKind>]] [--src <src>] [--before <было.json>]
        сервис макетов в браузере: папка - стартовая страница со списком макетов папки и
        подкаталогов, новая форма, импорт из 1С, выбор папки и исходников; файл - сервис на его папку
        и сразу конструктор этого макета: дерево элементов, макет, панель свойств; сохранение
        с проверкой, слежение за файлом. Порт по умолчанию 8190, занят - следующий; --new создает
        пустую модель, если файла нет; --src - исходники конфигурации (EDT `src` или каталог выгрузки
        конфигуратора) на этот запуск, иначе - из настроек папки `.form-mockup.json`; --before - «было»
        для правок (без него - файл на запуске). Код 2 - файл или папку не открыть, порт занят или
        --src не исходники; Ctrl+C - остановка

Вывод - UTF-8 на любой ОС. Windows, PowerShell: перед командами
`[Console]::OutputEncoding = [Text.Encoding]::UTF8`, иначе PowerShell прочтет вывод в кодировке консоли (OEM 866).

Тесты: python3 -m unittest discover -s tools/form-mockup/tests
    на Windows - `python -X utf8 -m unittest ...`: иначе сообщения самого раннера идут в кодировке консоли
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fmlib import DICTIONARY_PATH, SCHEMA_PATH, write_text_lf  # noqa: E402
from fmlib import launch, pictures, render, splash  # noqa: E402
from fmlib.diff import compare, note_numbers  # noqa: E402
from fmlib.dictionary import load_dictionary, translate  # noqa: E402
from fmlib.importer import ImportFailure, import_form  # noqa: E402
from fmlib.model import BLOCKING_CODES, ModelLoadError, check, load_model, name_chain  # noqa: E402
from fmlib.schema import SchemaValidator, format_path  # noqa: E402
from fmlib.server import (FORM_KINDS, Editor, Lifetime, ServeError, Sources, Workspace, dump, empty_model,  # noqa: E402
                          make_server)
from fmlib.workspace import WorkspaceError, last_folder, remember_folder, settings_sources, user_dir  # noqa: E402
from fmlib.tables import changes_table, elements_table  # noqa: E402
from fmlib.reconcile import reconcile, report  # noqa: E402


def command_import(args) -> int:
    try:
        std_pictures = pictures.std_source(args.std_pictures)
        if std_pictures and not std_pictures.exists():
            raise ImportFailure(f"выгрузка стандартных картинок не найдена: {std_pictures}")
        model, report = import_form(Path(args.form), std_pictures)
    except ImportFailure as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(output, json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    print(f"Модель: {output}")
    for line in report.lines():
        print(line)
    return 0


def command_check(args) -> int:
    try:
        model = load_model(Path(args.model))
    except ModelLoadError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    validator = SchemaValidator.from_file(SCHEMA_PATH)
    issues = check(model, validator)
    print_issues(model, issues)
    if issues:
        print(f"Замечаний: {len(issues)}")
        return 1
    print("Замечаний нет")
    return 0


def print_issues(model, issues, prefix=""):
    for issue in issues:
        names = name_chain(model, issue.path)
        where = f"{names} ({format_path(issue.path)})" if names else format_path(issue.path)
        print(f"{prefix}{where}: {issue.message} [{issue.code}]")


def blocked_before(before, validator) -> bool:
    """Прежняя версия рисуется и сравнивается без замечаний схемы и повторов имен; правила вёрстки не важны."""
    issues = [issue for issue in check(before, validator) if issue.code in BLOCKING_CODES]
    print_issues(before, issues, "было: ")
    if issues:
        print(f"Замечаний прежней версии: {len(issues)} - сравниваю после исправления (formmockup.py check)")
    return bool(issues)


def print_warnings(diff):
    for warning in diff.warnings:
        print(f"Сравнение: {warning}", file=sys.stderr)


def parse_state(text: str) -> dict:
    """`Панель:Закладка;Панель2:Закладка2` → {панель: закладка}."""
    pages = {}
    for part in filter(None, (text or "").split(";")):
        if ":" not in part:
            raise ValueError(f"--state: ожидается Панель:Закладка, получено {part!r}")
        key, value = part.split(":", 1)
        pages[key.strip()] = value.strip()
    return pages


def command_render(args) -> int:
    try:
        model = load_model(Path(args.model))
        before = load_model(Path(args.before)) if args.before else None
        pages = parse_state(args.state)
    except (ModelLoadError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    validator = SchemaValidator.from_file(SCHEMA_PATH)
    issues = check(model, validator)
    print_issues(model, issues)
    if any(issue.code in BLOCKING_CODES for issue in issues):
        print(f"Замечаний модели: {len(issues)} - рисую после исправления (formmockup.py check)")
        return 1
    if before is not None and blocked_before(before, validator):
        return 1
    if issues:
        # Правила вёрстки не мешают рисовать: импортированная форма бывает и с 40
        # элементами на закладке - ее надо показать как есть
        print(f"Замечаний модели: {len(issues)} - рисую как есть")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stem = Path(args.model).stem
    html_path = output / f"{stem}.html"
    title = model["form"].get("title") or stem
    # Модель, написанная руками, стандартных картинок не несет: рендер добирает их из выгрузки
    # (архив инструмента или своя), файл модели не меняется
    std = pictures.std_source(args.std_pictures)
    if std and not std.exists():
        print(f"Ошибка: выгрузка стандартных картинок не найдена: {std}", file=sys.stderr)
        return 2
    found = dict(before.get("pictures") or {}) if before else {}
    found.update(model.get("pictures") or {})
    for version in (model, before) if before else (model,):
        pictures.add_std(found, pictures.referencing(version), std)
    if found:
        model = dict(model, pictures=found)
    dictionary = load_dictionary(DICTIONARY_PATH)
    diff = None
    if before is not None:
        diff = compare(before, model, dictionary)
        print_warnings(diff)
        print(f"Правок: {len(diff.changes)}")
    write_text_lf(html_path, render.build_html(model, dictionary, title, pages, before, diff))
    print(f"HTML: {html_path}")

    chrome, searched = render.find_chrome()
    if not chrome:
        where = "; ".join(searched)
        if args.png:
            print(f"Chrome не найден, PNG не создан. Искали: {where}. Путь можно задать в {render.CHROME_ENV}",
                  file=sys.stderr)
            return 3
        print(f"Замечания раскладки не проверены: Chrome не найден (искали: {where})")
        return 1 if issues else 0

    try:
        if diff is None:
            layout, shots = shoot(chrome, html_path, output, stem, pages, args.png)
        else:
            layout, shots = shoot_diff(chrome, html_path, output, stem, pages, args.png)
        if args.png and note_numbers(model["form"]):
            # Номера примечаний - отдельным снимком: основной снимок для ТЗ остается без них
            shots += shoot_notes(chrome, html_path, output, stem, pages, [] if diff is None else ["mode=after", "nodiff"])
    except render.ChromeError as error:
        print(f"Ошибка Chrome: {error}", file=sys.stderr)
        return 2

    for path in shots:
        print(f"PNG: {path}")
    for error in layout.errors:
        print(f"Ошибка JS: {error} [js]")
    for note in layout.notes:
        print(f"{note} [layout]")
    if layout.notes or layout.errors:
        print(f"Замечаний раскладки: {len(layout.notes) + len(layout.errors)}")
        return 1
    print("Замечаний раскладки нет")
    return 1 if issues else 0


def shoot(chrome, html_path, output, stem, pages, png):
    """Замер и снимки формы: вся форма и каждая закладка не по умолчанию."""
    layout = render.measure(chrome, html_path, pages)
    shots = []
    if png:
        path = output / f"{stem}.png"
        render.screenshot(chrome, html_path, path, layout, pages)
        shots.append(path)
        for pages_name, page_name, state in render.tab_states(layout, pages):
            tab_layout = render.measure(chrome, html_path, state)
            path = output / f"{stem}__{pages_name}_{page_name}.png"
            render.screenshot(chrome, html_path, path, tab_layout, state)
            shots.append(path)
    return layout, shots


def shoot_diff(chrome, html_path, output, stem, pages, png):
    """Правки: замечания раскладки - по новой форме; снимки «Правки», «Стало» и закладок с правками."""
    after = ["mode=after", "nodiff"]
    layout = render.measure(chrome, html_path, pages, flags=after)
    shots = []
    if png:
        changes = ["mode=diff"]
        diff_layout = render.measure(chrome, html_path, pages, flags=changes)
        path = output / f"{stem}__правки.png"
        render.screenshot(chrome, html_path, path, diff_layout, pages, changes)
        shots.append(path)
        path = output / f"{stem}__стало.png"
        render.screenshot(chrome, html_path, path, layout, pages, after)
        shots.append(path)
        for pages_name, page_name, state in render.tab_states(diff_layout, pages, changed_only=True):
            tab_layout = render.measure(chrome, html_path, state, flags=changes)
            path = output / f"{stem}__правки__{pages_name}_{page_name}.png"
            render.screenshot(chrome, html_path, path, tab_layout, state, changes)
            shots.append(path)
    return layout, shots


def shoot_notes(chrome, html_path, output, stem, pages, flags):
    """Номера примечаний: форма и закладки с примечаниями, не показанные по умолчанию; `flags` - режим страницы
    (с --before - «стало» без правок)."""
    flags = flags + ["notes"]
    layout = render.measure(chrome, html_path, pages, flags=flags)
    path = output / f"{stem}__примечания.png"
    render.screenshot(chrome, html_path, path, layout, pages, flags)
    shots = [path]
    for pages_name, page_name, state in render.tab_states(layout, pages, noted_only=True):
        tab_layout = render.measure(chrome, html_path, state, flags=flags)
        path = output / f"{stem}__примечания__{pages_name}_{page_name}.png"
        render.screenshot(chrome, html_path, path, tab_layout, state, flags)
        shots.append(path)
    return shots


def command_table(args) -> int:
    try:
        model = load_model(Path(args.model))
        before = load_model(Path(args.before)) if args.before else None
    except ModelLoadError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    validator = SchemaValidator.from_file(SCHEMA_PATH)
    issues = [issue for issue in check(model, validator) if issue.code in BLOCKING_CODES]
    print_issues(model, issues)
    if issues:
        print(f"Замечаний модели: {len(issues)} - таблица после исправления (formmockup.py check)")
        return 1
    if before is not None and blocked_before(before, validator):
        return 1
    dictionary = load_dictionary(DICTIONARY_PATH)
    if before is None:
        print(elements_table(model, dictionary), end="")
        return 0
    diff = compare(before, model, dictionary)
    print_warnings(diff)
    print(changes_table(diff, dictionary), end="")
    return 0


def command_compare(args) -> int:
    validator = SchemaValidator.from_file(SCHEMA_PATH)
    try:
        mockup = load_model(Path(args.mockup))
        source = Path(args.form)
        if source.suffix.lower() == ".json":
            form = load_model(source)
        else:
            form, _ = import_form(source)
    except (ModelLoadError, ImportFailure) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    for label, model in (("макет", mockup), ("форма", form)):
        issues = [issue for issue in check(model, validator) if issue.code in BLOCKING_CODES]
        print_issues(model, issues, f"{label}: ")
        if issues:
            print(f"Ошибка: {label} с нарушением схемы ({len(issues)}) - сверка после исправления "
                  f"(formmockup.py check)", file=sys.stderr)
            return 2
    dictionary = load_dictionary(DICTIONARY_PATH)
    result = reconcile(mockup, form, dictionary)
    print_warnings(result.diff)
    print(report(result, dictionary), end="")
    return 1 if result.changes else 0


def command_ru(args) -> int:
    dictionary = load_dictionary(DICTIONARY_PATH)
    validator = SchemaValidator.from_file(SCHEMA_PATH)
    result = 0
    for word in args.words:
        lines = translate(dictionary, word, validator.platform_mark)
        if not lines:
            print(f"{word} - нет в словаре")
            result = 1
        for line in lines:
            print(line)
    return result


def command_serve(args) -> int:
    if args.model is None and not args.shortcut:
        print("Ошибка: не указана папка макетов или файл модели", file=sys.stderr)
        return 2
    if args.model is None:
        # Ярлык без аргумента: последняя папка, а нет ее - выбор папки на странице
        last = last_folder()
        args.model = str(last or user_dir())
        if last is None:
            user_dir().mkdir(exist_ok=True)
            args.open = args.open or "folder"
    path = Path(args.model)
    if args.kind and not args.new:
        print("Ошибка: --kind - только вместе с --new", file=sys.stderr)
        return 2
    if path.is_dir() and (args.new or args.before):
        print("Ошибка: --new и --before - только с файлом модели, не с папкой", file=sys.stderr)
        return 2
    if not path.exists() and not args.new:
        print(f"Ошибка: папка или файл не найдены: {path}", file=sys.stderr)
        return 2
    if not args.detached and running(args, path):
        return 0
    if args.shortcut:
        return launch.spawn(serve_arguments(args, path))
    if path.is_dir():
        return serve_workspace(args, path.resolve(), None)
    if args.new and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, dump(empty_model(args.kind or "DataProcessorForm")))
        print(f"Создана пустая модель: {path}")
    elif args.new:
        print(f"Файл уже есть - открываю как есть: {path}")
    base_file = Path(args.before) if args.before else None
    try:
        model = load_model(path)
        # «Было» для правок конструктора: файл --before или модель на запуске
        base = load_model(base_file) if base_file else model
    except ModelLoadError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return serve_workspace(args, path.resolve().parent, (path.resolve(), base, base_file))


def running(args, path: Path) -> bool:
    """Сервис на эту папку уже запущен: открыть его страницу, второй сервер не поднимать. Запуск с
    `--port`, `--src`, `--new`, `--before` - всегда свой сервер: у него свои условия."""
    if args.port or args.src or args.new or args.before:
        return False
    found = launch.find_service(path.resolve())
    if found is None:
        return False
    url, folder = found
    if path.is_file():
        url += "edit?file=" + quote(Path(os.path.realpath(path)).relative_to(folder).as_posix())
    elif args.open:
        url += "#open=" + args.open
    print(f"Сервис на эту папку уже запущен: {url}", flush=True)
    if not args.no_browser:
        launch.open_window(url)
    return True


def serve_arguments(args, path: Path) -> list:
    """Аргументы `serve` для процесса сервиса без окна (ярлык): путь - полный, остальное - как задано."""
    result = [str(path.resolve())]
    if args.no_browser:
        result.append("--no-browser")
    if args.port:
        result += ["--port", str(args.port)]
    for option in ("src", "before", "kind", "open"):
        value = getattr(args, option)
        if value:
            result += [f"--{option}", str(Path(value).resolve()) if option in ("src", "before") else value]
    if args.new:
        result.append("--new")
    return result


def serve_workspace(args, root: Path, start) -> int:
    """Сервис на папку макетов; `start` - (файл, «было», файл «было») макета запуска или None.
    Исходники - `--src` на этот запуск, иначе из настроек папки. Останавливается сам: код 0."""
    std = pictures.std_source()
    try:
        projects, src, extensions = (None, Path(args.src).resolve(), []) if args.src else settings_sources(root)
        sources = Sources(std if std and std.exists() else None, src, extensions)
        editor = None
        if start:
            file, base, base_file = start
            editor = Editor(file, base=base, base_file=base_file.resolve() if base_file else None, sources=sources)
        workspace = Workspace(root, sources, editor, pinned_src=bool(args.src), projects=projects)
        server = make_server(workspace, args.port, Lifetime.from_env())
    except (ServeError, WorkspaceError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    if args.detached and root != user_dir().resolve():
        # Последняя папка - только ярлыка: `serve` агента на свой каталог не меняет, что откроет ярлык человека
        remember_folder(root)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    browser = None
    if not args.no_browser:
        browser = render.find_chrome()[0]
        if browser is None:
            print(launch.NO_BROWSER_NOTE, flush=True)
    if start:
        url += "edit?file=" + quote(workspace.default)
        print(f"Конструктор: {url} - файл {start[0]}; остановка - «Завершить» на странице или Ctrl+C", flush=True)
    else:
        if args.open:
            url += "#open=" + args.open
        print(f"Макеты: {url} - папка {root}; остановка - «Завершить» на странице или Ctrl+C", flush=True)
    if args.detached:
        launch.detach_output()
    if not args.no_browser:
        launch.open_window(url, browser)
    server.lifetime.watch(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Сервис остановлен: Ctrl+C")
    else:
        print(f"Сервис остановлен: {server.lifetime.reason}")
    finally:
        server.server_close()
    return 0


def main() -> int:
    # Вывод - всегда UTF-8: под агентом на Windows он идет в канал, и Python до 3.15 без PYTHONUTF8 писал бы его
    # в cp1251 - «→» роняет `table`, кириллица доходит кракозябрами
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:              # у оконного `pythonw` (заставка ярлыка) вывода нет
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Макеты форм 1С для ТЗ")
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser("import", help="модель по XML формы")
    import_parser.add_argument("form", help="Form.form (EDT) или Form.xml (выгрузка конфигуратора)")
    import_parser.add_argument("-o", "--output", required=True, help="model.json")
    import_parser.add_argument("--std-pictures", help="выгрузка стандартных картинок платформы - каталог или zip "
                               "(1c/ВыгрузитьСтандартныеКартинки.bsl); по умолчанию FORMMOCKUP_STD_PICTURES, "
                               "нет и ее - архив std-pictures.zip инструмента")
    import_parser.set_defaults(handler=command_import)

    check_parser = commands.add_parser("check", help="проверка модели формы")
    check_parser.add_argument("model", help="model.json")
    check_parser.set_defaults(handler=command_check)

    render_parser = commands.add_parser("render", help="HTML и PNG макета")
    render_parser.add_argument("model", help="model.json")
    render_parser.add_argument("-o", "--output", required=True, help="каталог для HTML и PNG")
    render_parser.add_argument("--before", help="прежняя версия модели: правки, режимы «Правки / Стало / Было»")
    render_parser.add_argument("--png", action="store_true", help="снимки PNG: форма и каждая закладка не по умолчанию")
    render_parser.add_argument("--state", help="закладки по умолчанию: Панель:Закладка[;Панель:Закладка]")
    render_parser.add_argument("--std-pictures", help="выгрузка стандартных картинок для тех, которых нет в модели; "
                               "по умолчанию - как у import")
    render_parser.set_defaults(handler=command_render)

    table_parser = commands.add_parser("table", help="таблица элементов или изменений для ТЗ")
    table_parser.add_argument("model", help="model.json")
    table_parser.add_argument("--before", help="прежняя версия модели: таблица изменений")
    table_parser.set_defaults(handler=command_table)

    compare_parser = commands.add_parser("compare", help="сверка собранной формы с макетом")
    compare_parser.add_argument("mockup", help="макет - модель JSON")
    compare_parser.add_argument("form", help="собранная форма: Form.form (EDT), Form.xml (выгрузка конфигуратора) "
                                "или модель JSON")
    compare_parser.set_defaults(handler=command_compare)

    ru_parser = commands.add_parser("ru", help="перевод по словарю в обе стороны")
    ru_parser.add_argument("words", nargs="+", help="вид, свойство, значение или свойство=значение")
    ru_parser.set_defaults(handler=command_ru)

    serve_parser = commands.add_parser("serve", help="сервис макетов и конструктор в браузере")
    serve_parser.add_argument("model", metavar="папка|model.json", nargs="?",
                              help="папка макетов - стартовая страница со списком; файл - сразу конструктор этого макета")
    serve_parser.add_argument("--port", type=int, help="порт; по умолчанию 8190, занят - следующий свободный")
    serve_parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    serve_parser.add_argument("--new", action="store_true", help="файла нет - создать пустую модель")
    serve_parser.add_argument("--kind", choices=FORM_KINDS, help="вид новой формы (с --new); по умолчанию DataProcessorForm")
    serve_parser.add_argument("--src", help="исходники конфигурации - EDT `src` или каталог выгрузки конфигуратора: "
                              "общие картинки и ссылочные типы для окон выбора конструктора; на этот запуск важнее "
                              "настроек папки (.form-mockup.json)")
    serve_parser.add_argument("--before", help="прежняя версия модели - «было» для правок конструктора; "
                              "по умолчанию - файл модели на запуске")
    # Служебные: ярлык запуска - без аргумента последняя папка, сервис без окна консоли, ошибки без
    # трассировки; `--detached` - сам этот сервис; `--open` - окно стартовой страницы сразу (тесты, снимки README)
    serve_parser.add_argument("--shortcut", action="store_true", help=argparse.SUPPRESS)
    serve_parser.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)
    serve_parser.add_argument("--open", choices=["new", "import", "config", "folder", "src"], help=argparse.SUPPRESS)
    serve_parser.add_argument("--splash", action="store_true", help=argparse.SUPPRESS)
    serve_parser.set_defaults(handler=command_serve)

    args = parser.parse_args()
    if getattr(args, "shortcut", False) and not args.splash and splash.available():
        # Ярлык на Windows: дальше - окно-заставка без консоли, консоль ярлыка закрывается сразу
        splash.start(sys.argv[1:])
        return 0
    if getattr(args, "shortcut", False) or getattr(args, "detached", False):
        # Человеку - текст ошибки, трассировка - в журнал
        def guarded() -> int:
            try:
                return args.handler(args)
            except Exception as error:  # noqa: BLE001 - любая ошибка запуска ярлыка
                import traceback
                launch.log(traceback.format_exc())
                print(f"Ошибка: {error}", file=sys.stderr)
                print(f"Подробности - в журнале {launch.log_path()}", file=sys.stderr)
                return 2
        return splash.run(guarded) if getattr(args, "splash", False) else guarded()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
