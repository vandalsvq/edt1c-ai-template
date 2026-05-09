# Установка skill `bsl-check`

Чеклист первичной настройки skill для проверки синтаксиса 1С по локальному справочнику.

Skill — это обёртка над Python-скриптом `1c-syntax-check.py`, который ищет методы и свойства в индексе `shcntx_ru_v*/search-index-ru.json`. Скрипт и справочники живут в отдельном публичном репозитории — этот шаблон только регистрирует skill в Claude Code и подставляет путь к ним.

## Зависимости

| Что | Где взять | Зачем |
| --- | --- | --- |
| Python 3.8+ | `python3 --version` | Запуск `1c-syntax-check.py` |
| git | `git --version` | Клонирование справочника |
| Репозиторий `vandalsvq/hbk_md` | <https://github.com/vandalsvq/hbk_md> | Содержит скрипт `1c-syntax-check.py` (`.claude/`) + справочники `shcntx_ru_v*` (~40 MB на версию) |

В этой инструкции в качестве примера используется путь `~/Repository/hbk_md` — подставьте свой, если клонируете в другое место.

## Шаг 1. Склонировать `hbk_md`

```bash
git clone https://github.com/vandalsvq/hbk_md.git ~/Repository/hbk_md
```

Если репозиторий уже склонирован — обновите его:

```bash
git -C ~/Repository/hbk_md pull
```

После клонирования в каталоге будут только инструменты — `.claude/1c-syntax-check.py` (skill-runner) и `process_hbk_complete.py` (разборщик). **Сам справочник** (`*.hbk` и распакованные `shcntx_ru_v*/` ~80 MB) **в репозиторий не коммитится** — его готовит каждый разработчик у себя.

## Шаг 2. Подготовить справочник (распаковать `.hbk`)

Сначала проверьте, не подготовлен ли он уже:

```bash
ls ~/Repository/hbk_md/shcntx_ru_v*/search-index-ru.json 2>/dev/null
```

Если файл нашёлся — справочник готов, переходите к Шагу 3.

Если нет — нужно один раз его подготовить:

1. Получите файл справочника платформы `*.hbk`. Обычно он находится в дистрибутиве платформы 1С (`shcntx_ru.hbk` рядом с `1cv8.exe` / в каталоге шаблонов конфигурации) или на диске ИТС.
2. Скопируйте `.hbk` в корень `~/Repository/hbk_md/`, переименовав в формат версии `X.X.X.X.hbk`:

   ```bash
   cp /path/to/shcntx_ru.hbk ~/Repository/hbk_md/8.5.1.1302.hbk
   ```

3. Запустите утилиту разбора:

   ```bash
   cd ~/Repository/hbk_md
   python3 process_hbk_complete.py
   ```

4. По завершении в `~/Repository/hbk_md/` появится `shcntx_ru_v8.5.1.1302/` с индексом `search-index-ru.json`. Это и есть готовый справочник.

Разбор нужен один раз на каждую новую версию платформы. Скрипт `1c-syntax-check.py` автоматически выбирает самую свежую папку `shcntx_ru_v*` рядом с собой — отдельно версию указывать не нужно.

## Шаг 3. Подставить путь в `SKILL.md`

В файле [`.claude/skills/bsl-check/SKILL.md`](../.claude/skills/bsl-check/SKILL.md) замените плейсхолдер `<PATH_TO>` на абсолютный путь к каталогу, где лежит `1c-syntax-check.py`.

Было:

```bash
python3 <PATH_TO>/1c-syntax-check.py $ARGUMENTS
```

Стало (пример для `~/Repository/hbk_md`):

```bash
python3 /Users/<имя-пользователя>/Repository/hbk_md/.claude/1c-syntax-check.py $ARGUMENTS
```

> Используйте именно абсолютный путь — Claude Code запускает skill из произвольного рабочего каталога, и `~` в shell-команде раскроется не всегда.

## Шаг 4. Дописать permission в `.claude/settings.local.json`

Чтобы Claude Code не запрашивал подтверждение на каждый запуск skill, добавьте правило в `permissions.allow` локальных настроек:

```bash
# если файла ещё нет — скопируйте пример
cp .claude/settings.local.json.example .claude/settings.local.json
```

Откройте `.claude/settings.local.json` и добавьте в массив `permissions.allow` строку (с тем же абсолютным путём, что и в шаге 2):

```json
"Bash(python3 /Users/<имя-пользователя>/Repository/hbk_md/.claude/1c-syntax-check.py:*)"
```

Файл `.claude/settings.local.json` находится в `.gitignore` — он у каждого разработчика свой.

## Шаг 5. Проверка

Из корня шаблона:

```bash
python3 ~/Repository/hbk_md/.claude/1c-syntax-check.py Структура.Вставить
# Ожидаемый вывод:
# ✓ Структура.Вставить (Structure.Insert)
```

В Claude Code:

```text
/bsl-check Структура.Вставить
/bsl-check -m Массив
/bsl-check -p Строка
```

Если первая команда вернула результат, а вторая — нет, перезапустите Claude Code (skill подхватывается при старте сессии).

## Обновление

**Обновить скрипты `hbk_md`:**

```bash
git -C ~/Repository/hbk_md pull
```

**Добавить новую версию платформы:** скопируйте новый `.hbk` в `~/Repository/hbk_md/`, переименуйте в формат `X.X.X.X.hbk` и запустите `python3 process_hbk_complete.py` (Шаг 2). Старые версии можно удалить — скрипт автоматически выбирает самую свежую папку `shcntx_ru_v*` по имени, менять `SKILL.md` повторно не нужно.

## Если skill не нужен

Удалите каталог [`.claude/skills/bsl-check/`](../.claude/skills/bsl-check/) — Claude Code перестанет регистрировать команду `/bsl-check`. Также можно убрать упоминания skill из `CLAUDE.md` и `README.md`, если они мешают.

## Troubleshooting

**`/bsl-check` не появляется в списке skill.**
Проверьте, что путь к каталогу проекта корректный, файл `.claude/skills/bsl-check/SKILL.md` существует, и перезапустите Claude Code.

**`❌ Справочник не найден: .../shcntx_ru_md`.**
Скрипт не нашёл `shcntx_ru_v*` рядом с собой. Это значит, что разбор `.hbk` ещё не выполнен — публичный репо не содержит готовых справочников. Вернитесь к Шагу 2 и подготовьте справочник из `.hbk` файла платформы.

**`Bash(python3 ...) — permission denied` или промт согласия каждый раз.**
В `permissions.allow` запись путь-в-путь должна совпадать с тем, что фактически вызывается. Сравните строку из `SKILL.md` (шаг 2) и строку правила (шаг 3) — они должны указывать на один и тот же абсолютный путь.

**Skill вызывается, но возвращает ошибку Python.**
Проверьте версию: `python3 --version` (нужно 3.8+). Если используете `pyenv`/`aspenv`, убедитесь, что `python3` из `PATH` — тот, что нужен.
