# edt1c-ai-template

Шаблон репозитория для разработки на 1С:Предприятие в EDT с использованием **Claude Code** и методологии **Specification-Driven Development (SDD)**.

## Что внутри

```text
.
├── CLAUDE.md           # Главный документ для Claude Code: соглашения, ссылки на docs/specs
├── README.md           # Этот файл
├── .gitignore          # Игнор для EDT, 1С, macOS, Python, IDE
├── .claude/
│   ├── settings.json                    # Общие настройки Claude Code (commit'ятся)
│   ├── settings.local.json.example      # Пример локальных permissions (скопировать в settings.local.json)
│   └── skills/
│       └── bsl-check/                   # Skill проверки синтаксиса 1С по справочнику shcntx_ru
├── docs/               # Стандарты BSL и BSP — справочные документы для Claude
│   ├── bsl-anti-patterns.md
│   ├── bsl-async.md
│   ├── bsl-code-review.md
│   ├── bsl-coding-standards.md
│   ├── bsl-form-module-rules.md
│   ├── bsl-form-reserved-names.md
│   ├── bsl-query-functions.md
│   ├── bsl-query-optimization.md
│   ├── bsl-query-reference.md
│   ├── bsl-refactoring.md
│   ├── bsl-strict-types.md
│   ├── bsp-common-modules.md
│   ├── codepilot1c-reference.md         # Справочник по MCP-серверу codepilot1c
│   ├── mdo-integrity.md
│   └── model-selection.md
├── specs/              # SDD: спецификации фич (источник истины)
│   ├── README.md       # Процесс SDD, статусы, правила именования
│   ├── _template/      # Шаблоны spec.md и plan.md (копировать в specs/<prefix>-<N>/)
│   ├── done/           # Завершённые спеки
│   └── retro/          # Ретро-спеки на существующие подсистемы
└── planning/           # Транзиентные планы и груминг бэклога
    ├── README.md
    └── examples/       # Примеры из реального проекта (заменить своими)
```

## Как использовать

### 1. Скопируйте шаблон под свой проект

```bash
cp -r edt1c_ai_template my-project
cd my-project
rm -rf .git && git init
```

### 2. Заполните CLAUDE.md под свой проект

Откройте [`CLAUDE.md`](CLAUDE.md) и замените все плейсхолдеры `<...>`:

- Название проекта, тип (расширение / конфигурация / библиотека)
- Каталог EDT-проекта
- Префикс объектов (например, `prj_`)
- Платформа 1С:Предприятие
- URL трекера задач
- Если проект состоит из нескольких EDT-проектов — заполните таблицу EDT-воркспейса
- Перечислите ключевые подсистемы, обработки и архитектурные ограничения зависимостей
- Заполните соглашение о ветках, коммитах и инкременте версии
- Перечислите роли доступа

### 3. Подключите MCP-сервер `codepilot1c` (опционально)

Справочник по инструментам — [`docs/codepilot1c-reference.md`](docs/codepilot1c-reference.md). Установка зависит от вашей среды и конфигурации Claude Code.

### 4. Подключите skill `bsl-check` (опционально)

Skill использует Python-скрипт `1c-syntax-check.py`, который читает локальный справочник синтаксиса 1С (`shcntx_ru`). Перед использованием:

1. Скачайте справочник (`shcntx_ru_v<версия>`).
2. Положите его и скрипт `1c-syntax-check.py` в удобное место.
3. Откройте [`.claude/skills/bsl-check/SKILL.md`](.claude/skills/bsl-check/SKILL.md) и замените `<PATH_TO>` на актуальный путь.

Если справочник не нужен — удалите каталог `.claude/skills/bsl-check/`.

### 5. Настройте локальные permissions Claude Code

```bash
cp .claude/settings.local.json.example .claude/settings.local.json
```

Файл `settings.local.json` уже в `.gitignore` — храните в нём личные настройки прав.

### 6. Замените примеры в `planning/examples/` своими

В [`planning/examples/`](planning/examples/) лежат реальные планы из проекта PrintWizard — для понимания формата. Удалите их и положите свои.

### 7. Создайте EDT-проект

Положите EDT-проект (например, `MyConfig.MyProject/`) в корень репозитория. Пути в `CLAUDE.md` обновите соответственно.

## Цикл работы (SDD)

1. **Issue → спека → код**, не наоборот.
2. На каждое значимое изменение — папка `specs/<prefix>-<N>/` с `spec.md` + `plan.md` (копируется из `_template/`).
3. Спека согласуется (статус `draft` → `approved`), и только после `approved` начинается код в ветке `feature/<prefix>-<N>`.
4. Расхождение кода и спеки разрешается **обновлением спеки** в том же PR.
5. После merge: статус `done`, папка переносится в `specs/done/<prefix>-<N>/`.

Подробности — в [`specs/README.md`](specs/README.md) и [`CLAUDE.md`](CLAUDE.md) → раздел «Цикл работы над фичей».

## Источник

Шаблон сделан на базе репозитория [PrintWizard](https://github.com/vandalsvq/printwizard) — извлечены универсальные части: стандарты BSL, методология SDD, базовая конфигурация Claude Code.
