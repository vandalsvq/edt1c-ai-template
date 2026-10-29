#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Аудит форм по правилам docs/bsl-form-design-8.3.md (раздел 10) и docs/form-layout-rules.md

Разбирает `.form` и `Module.bsl` форм и печатает находки по кодам проверок.
Ничего не меняет. Запуск из корня репозитория:

    python3 tools/form-audit/form-audit.py                  # все формы проекта
    python3 tools/form-audit/form-audit.py --форма CommonForms/prj_Настройки
    python3 tools/form-audit/form-audit.py --сводка          # только счётчики по формам
    python3 tools/form-audit/form-audit.py --проверка EN,ЦВЕТ
    python3 tools/form-audit/form-audit.py --src <Каталог.Имя>/src

Перед первым запуском заполнить блок «Настройка под проект» ниже. Находки - повод
посмотреть форму, а не приговор: образцы и сознательные отклонения проекта записываются в
документе форм проекта, если он ведётся.

Коды проверок:
    EN            представление с `ru` без `en` (заголовки, подсказки, команды, реквизиты);
                  по умолчанию только в двуязычном проекте (ДВУЯЗЫЧНЫЙ_ПРОЕКТ)
    ГРУППА-ИМЯ    обычная группа с техническим именем или автозаголовком «Группа ...»
    ДЕКОРАЦИЯ-ИМЯ декорация или группа с именем вида Декорация1, Группа18, Разрыв2
    ПОДСКАЗКА     подсказка длиннее 255 знаков
    ПОДСКАЗКА-ПОЛЕ подсказка поля ввода показывается только при наведении («Авто»)
    ЗАГОЛОВКИ     в шапке формы заголовки полей и слева, и сверху
    ВЫДЕЛЕНИЕ     группа с сильным выделением (StrongSeparation)
    ЦВЕТ          цвет `Web.*` или абсолютный `#RRGGBB` в свойствах и форматированных строках;
                  по умолчанию только при стилевых цветах (ЦВЕТА_ЗНАЧЕНИЯМИ = False)
    КНОПКА        завершающая команда без кнопки по умолчанию
    ПАРАМЕТРЫ     `Параметры.Свойство(` в модуле формы
    ИЗМЕНЯЕТ      команда формы объекта без признака «Изменяет данные»
    ЭКСПОРТ       экспортный метод модуля формы, не обработчик оповещения и не Подключаемый_
    АКТИВИЗАЦИЯ   серверный вызов прямо в обработчике ПриАктивизацииСтроки
    МОДУЛЬ        Сообщить(, ПолучитьФорму(, ЭтаФорма, синхронные Предупреждение(/Вопрос(
    МОДИФИЦИРОВАННОСТЬ  `Модифицированность = Ложь` в форме объекта
    КЛАВИШИ       зарезервированное сочетание клавиш (std430)
    HTML          поле HTML-документа в форме (информационно: сверить с правилами интерфейса проекта)
"""
import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

# --- Настройка под проект ---------------------------------------------------
# Каталог исходников EDT-проекта от корня репозитория («<Каталог.Имя>/src»)
КАТАЛОГ_ИСХОДНИКОВ = '<Каталог.Имя>/src'
# Проект ведёт представления на двух языках (ru и en): проверка EN включена по умолчанию
ДВУЯЗЫЧНЫЙ_ПРОЕКТ = False
# Параметр проекта «Цвета в формах» = «значения» (CLAUDE.md): WebЦвета и абсолютные цвета
# разрешены, проверка ЦВЕТ по умолчанию выключена
ЦВЕТА_ЗНАЧЕНИЯМИ = False
# -----------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, КАТАЛОГ_ИСХОДНИКОВ)
XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'
RESERVED_KEYS = {'Ctrl+Shift+F', 'F7', 'F8', 'F11', 'F12', 'Ctrl+A', 'Ctrl+C', 'Ctrl+V', 'Ctrl+X',
                 'Ctrl+F', 'Ctrl+H', 'Ctrl+P', 'Ctrl+O', 'Ctrl+N', 'Ctrl+Y', 'Ctrl+Z', 'Ctrl+E',
                 'Ctrl+G', 'Ctrl+L', 'Ctrl+T', 'Ctrl+U', 'Ctrl+W', 'Ctrl+B', 'Ctrl+I'}
FINISH_CMD = re.compile(r'ИЗакрыть$|^Далее$|^ШагВперед$|^Печать$|^ОК$')
TECH_GROUP_NAME = re.compile(r'(Горизонтальн|Вертикальн|ЛеваяСторона|ПраваяСторона|Колонка\d|^Группа\d+$|^Группа$)')
AUTO_TITLE = re.compile(r'^Группа( |\d|$)')
NUMBERED_NAME = re.compile(r'^(Декорация|Группа|Разрыв|Внимание|Надпись|Картинка)\d+$')
NOTIFY_EXPORT = re.compile(r'(После|При[А-ЯЁ]|Завершение|ПродолжитьВыполнение|Подключаемый_|Оповещени)')
OBJECT_TYPES = ('CatalogObject', 'DocumentObject', 'InformationRegisterRecordManager', 'ChartOfCharacteristicTypesObject')


def strip(tag):
    return tag.split('}', 1)[1] if '}' in tag else tag


def text(el, name):
    ch = el.find(name)
    return ch.text if ch is not None else None


def langs(el, name):
    d = {}
    for ch in el.findall(name):
        k = ch.find('key')
        v = ch.find('value')
        if k is not None:
            d[k.text] = (v.text or '') if v is not None else ''
    return d


class Form:
    def __init__(self, path):
        self.path = path
        self.dir = os.path.dirname(path)
        self.rel = os.path.relpath(self.dir, SRC).replace('\\', '/').replace('/Forms/', '/')
        self.root = ET.parse(path).getroot()
        for el in self.root.iter():
            el.tag = strip(el.tag)
        self.items = []
        self._walk(self.root, 'form')
        acb = self.root.find('autoCommandBar')
        if acb is not None:
            self._walk(acb, 'form')
        self.commands = self.root.findall('formCommands')
        self.attributes = self.root.findall('attributes')
        self.params = self.root.findall('parameters')
        mod = os.path.join(self.dir, 'Module.bsl')
        self.module = open(mod, encoding='utf-8-sig').read() if os.path.exists(mod) else ''
        self.raw = open(path, encoding='utf-8').read()
        self.is_object_form = any(text(a, 'main') == 'true' and any(t.text and t.text.startswith(OBJECT_TYPES) for t in a.findall('valueType/types')) for a in self.attributes)

    def _walk(self, parent, parent_name):
        for el in list(parent.findall('items')) + list(parent.findall('columns')):
            kind = el.get(XSI, '').replace('form:', '')
            name = text(el, 'name') or ''
            ext = el.find('extInfo')
            rec = {'el': el, 'kind': kind, 'name': name, 'parent': parent_name, 'type': text(el, 'type'),
                   'title': langs(el, 'title'), 'toolTip': langs(el, 'toolTip'),
                   'titleLocation': text(el, 'titleLocation') or 'Auto',
                   'toolTipRepresentation': text(el, 'toolTipRepresentation') or 'Auto',
                   'representation': (text(ext, 'representation') if ext is not None else None) or text(el, 'representation'),
                   'defaultButton': text(el, 'defaultButton'), 'commandName': text(el, 'commandName'),
                   'inputHint': langs(el, 'inputHint'), 'extTitle': {}, 'choice': []}
            et = el.find('extendedTooltip')
            if et is not None:
                rec['extTitle'] = langs(et, 'title')
            for c in el.findall('choiceList'):
                rec['choice'].append(langs(c, 'presentation'))
            self.items.append(rec)
            self._walk(el, name)
            for sub in ('autoCommandBar', 'contextMenu'):
                s = el.find(sub)
                if s is not None:
                    self._walk(s, name)


def check_en(f):
    out = []
    def need(d, where):
        if d.get('ru') and not d.get('en'):
            out.append(where)
    for i in f.items:
        need(i['title'], i['name'] + '.Заголовок')
        need(i['toolTip'], i['name'] + '.Подсказка')
        need(i['inputHint'], i['name'] + '.ПодсказкаВвода')
        need(i['extTitle'], i['name'] + '.РасширеннаяПодсказка')
        for c in i['choice']:
            need(c, i['name'] + '.СписокВыбора')
    for c in f.commands:
        need(langs(c, 'title'), 'Команда.' + (text(c, 'name') or ''))
        need(langs(c, 'toolTip'), 'Команда.' + (text(c, 'name') or '') + '.Подсказка')
    for a in f.attributes:
        need(langs(a, 'title'), 'Реквизит.' + (text(a, 'name') or ''))
    need(langs(f.root, 'title'), 'Форма.Заголовок')
    return out


def check_group_names(f):
    return [i['name'] + ' («' + (i['title'].get('ru') or '') + '»)' for i in f.items
            if i['kind'] == 'FormGroup' and i['type'] == 'UsualGroup'
            and (TECH_GROUP_NAME.search(i['name']) or AUTO_TITLE.match(i['title'].get('ru') or '') or not i['title'].get('ru'))]


def check_numbered_names(f):
    return [i['name'] for i in f.items if NUMBERED_NAME.match(i['name'])]


def check_tooltip_len(f):
    return ['%s (%d)' % (i['name'], len(i['toolTip']['ru'])) for i in f.items if len(i['toolTip'].get('ru') or '') > 255]


def check_tooltip_field(f):
    return [i['name'] for i in f.items if i['kind'] == 'FormField' and i['type'] == 'InputField'
            and i['toolTip'].get('ru') and i['toolTipRepresentation'] == 'Auto']


def check_title_location(f):
    locs = {i['titleLocation'] for i in f.items if i['kind'] == 'FormField' and i['type'] == 'InputField'
            and not any(p['name'] == i['parent'] and p['kind'] == 'Table' for p in f.items)}
    return ['слева и сверху в одной форме'] if {'Left', 'Top'} <= locs else []


def check_separation(f):
    return [i['name'] for i in f.items if i['kind'] == 'FormGroup' and i['representation'] == 'StrongSeparation']


def check_colors(f):
    out = []
    n = len(re.findall(r'<color>Web\.', f.raw))
    if n:
        out.append('Web-цвета: %d' % n)
    abs_colors = re.findall(r'<color>#?[0-9A-Fa-f]{6}<|<color #[0-9A-Fa-f]{6}>', f.raw)
    if abs_colors:
        out.append('абсолютные цвета: %d' % len(abs_colors))
    return out


def check_default_button(f):
    finishing = [text(c, 'name') for c in f.commands if FINISH_CMD.search(text(c, 'name') or '')]
    has_default = any(i['defaultButton'] == 'true' for i in f.items)
    return ['команды %s без кнопки по умолчанию' % ', '.join(finishing)] if finishing and not has_default else []


def check_parameters(f):
    n = f.module.count('Параметры.Свойство(')
    return ['%d вызовов, объявлено параметров: %d' % (n, len(f.params))] if n else []


def check_modifies(f):
    if not f.is_object_form:
        return []
    names = [text(c, 'name') for c in f.commands if text(c, 'modifiesData') != 'true']
    return ['%d команд без признака «Изменяет данные»' % len(names)] if names else []


def check_exports(f):
    out = []
    for m in re.finditer(r'^(?:Процедура|Функция)\s+([\wА-Яа-яЁё]+)\s*\([^)]*\)\s*Экспорт', f.module, re.M):
        if not NOTIFY_EXPORT.search(m.group(1)):
            out.append(m.group(1))
    return out


def check_row_activation(f):
    out = []
    for m in re.finditer(r'^Процедура\s+([\wА-Яа-яЁё]+ПриАктивизацииСтроки)\s*\(.*?^КонецПроцедуры', f.module, re.M | re.S):
        body = m.group(0)
        if re.search(r'[\wА-Яа-яЁё]+НаСервере(БезКонтекста)?\s*\(', body) and 'ПодключитьОбработчикОжидания' not in body:
            out.append(m.group(1))
    return out


def check_module(f):
    out = []
    code = '\n'.join(l for l in f.module.splitlines() if not l.strip().startswith('//'))
    for pat, label in ((r'(?<![\wА-Яа-яЁё\.])Сообщить\s*\(', 'Сообщить('), (r'ПолучитьФорму\s*\(', 'ПолучитьФорму('),
                       (r'(?<![\wА-Яа-яЁё])ЭтаФорма(?![\wА-Яа-яЁё])', 'ЭтаФорма'),
                       (r'(?<![\wА-Яа-яЁё\.])(Предупреждение|Вопрос|ОткрытьФормуМодально|ВвестиЗначение|ВвестиСтроку|ВвестиЧисло|ВвестиДату)\s*\(', 'синхронный диалог')):
        n = len(re.findall(pat, code))
        if n:
            out.append('%s: %d' % (label, n))
    return out


def check_modified(f):
    if not f.is_object_form:
        return []
    n = f.module.count('Модифицированность = Ложь')
    return ['%d присваиваний' % n] if n else []


def check_shortcuts(f):
    out = []
    for c in f.commands:
        sc = text(c, 'shortcut')
        if sc and sc in RESERVED_KEYS:
            out.append('%s: %s' % (text(c, 'name'), sc))
    return out


def check_html(f):
    return [i['name'] for i in f.items if i['type'] == 'HTMLDocumentField']


CHECKS = [
    ('EN', check_en), ('ГРУППА-ИМЯ', check_group_names), ('ДЕКОРАЦИЯ-ИМЯ', check_numbered_names),
    ('ПОДСКАЗКА', check_tooltip_len), ('ПОДСКАЗКА-ПОЛЕ', check_tooltip_field), ('ЗАГОЛОВКИ', check_title_location),
    ('ВЫДЕЛЕНИЕ', check_separation), ('ЦВЕТ', check_colors), ('КНОПКА', check_default_button),
    ('ПАРАМЕТРЫ', check_parameters), ('ИЗМЕНЯЕТ', check_modifies), ('ЭКСПОРТ', check_exports),
    ('АКТИВИЗАЦИЯ', check_row_activation), ('МОДУЛЬ', check_module), ('МОДИФИЦИРОВАННОСТЬ', check_modified),
    ('КЛАВИШИ', check_shortcuts), ('HTML', check_html),
]
LIST_LIMIT = 8


def main():
    global SRC
    ap = argparse.ArgumentParser(description='Аудит форм по docs/bsl-form-design-8.3.md')
    ap.add_argument('--src', help='каталог исходников EDT-проекта вместо КАТАЛОГ_ИСХОДНИКОВ')
    ap.add_argument('--форма', help='путь формы относительно src, например CommonForms/prj_Настройки или DataProcessors/prj_Обработка/Forms/Форма')
    ap.add_argument('--проверка', help='коды проверок через запятую')
    ap.add_argument('--сводка', action='store_true', help='только счётчики по формам')
    ap.add_argument('--все', action='store_true', help='не сокращать списки находок')
    args = ap.parse_args()
    if args.src:
        SRC = os.path.abspath(args.src)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    pattern = os.path.join(SRC, args.форма, '**', 'Form.form') if args.форма else os.path.join(SRC, '**', 'Form.form')
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        print('Формы не найдены:', pattern)
        return 2
    if args.проверка:
        codes = [c.strip() for c in args.проверка.split(',')]
    else:
        codes = [c for c, _ in CHECKS
                 if (c != 'EN' or ДВУЯЗЫЧНЫЙ_ПРОЕКТ) and (c != 'ЦВЕТ' or not ЦВЕТА_ЗНАЧЕНИЯМИ)]
    total = 0
    for path in files:
        f = Form(path)
        results = [(code, fn(f)) for code, fn in CHECKS if code in codes]
        results = [(c, r) for c, r in results if r]
        if not results:
            continue
        total += sum(len(r) for _, r in results)
        if args.сводка:
            print('%-55s %s' % (f.rel, '  '.join('%s=%d' % (c, len(r)) for c, r in results)))
            continue
        print('== %s%s' % (f.rel, ' (форма объекта)' if f.is_object_form else ''))
        for code, r in results:
            shown = r if args.все or len(r) <= LIST_LIMIT else r[:LIST_LIMIT] + ['... ещё %d' % (len(r) - LIST_LIMIT)]
            print('  %-18s %d: %s' % (code, len(r), '; '.join(shown)))
    print('Итого находок: %d в %d формах' % (total, len(files)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
