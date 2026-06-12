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
│       ├── bsl-check/                   # Skill проверки синтаксиса 1С по справочнику shcntx_ru
│       └── sync-template/               # Skill обновления переносимых файлов из шаблона (/sync-template)
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
│   ├── bsl-check-setup.md               # Чеклист установки skill bsl-check (зависит от vandalsvq/hbk_md)
│   ├── codepilot1c-reference.md         # Справочник по MCP-серверу codepilot1c
│   ├── mdo-integrity.md
│   ├── model-selection.md
│   └── project-init.md                  # Промпт первичной инициализации проекта (для Claude)
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

Инициализация нового проекта — три шага. Большую часть работы делает Claude по промпту [`docs/project-init.md`](docs/project-init.md).

### Быстрый старт через Claude Code

Создайте пустой каталог под новый проект, запустите в нём Claude Code и дайте ему такую задачу (одна реплика — Claude всё остальное сделает сам):

> Склонируй `https://github.com/vandalsvq/edt1c-ai-template.git` в текущий каталог (`git clone <url> .`) и выполни инструкцию из `docs/project-init.md`.

Если используете свой fork шаблона — подставьте URL fork'а вместо ссылки выше. Каталог должен быть пустым (`git clone <url> .` падает на непустой папке).

После клонирования Claude прочитает `docs/project-init.md` и проведёт по всем шагам — спросит, нужно ли переинициализировать `git`, потребует создать EDT-проект, заполнит `CLAUDE.md` и `README.md` под ваш проект, подключит `bsl-check`, и т.д.

### Детальный вариант (вручную)

Если предпочитаете контролировать каждый шаг:

### 1. Склонируйте шаблон

```bash
cp -r edt1c_ai_template my-project
cd my-project
rm -rf .git && git init
```

Или используйте «Use this template» на GitHub и `git clone <url>`.

### 2. Создайте EDT-проект

В EDT: `File → New → 1C:Enterprise project`. Имя — на латинице (`<Каталог>.<НазваниеПроекта>`), префикс объектов (например, `prj_`), тип (`Configuration` / `Configuration extension` / `Library`), расположение — корень репозитория.

Этот шаг делается через GUI EDT и не автоматизируется промптом — Claude использует созданный каталог, чтобы вытащить имя, префикс и платформу.

### 3. Запустите промпт инициализации

Откройте Claude Code в корне репозитория и скажите:

> Выполни инструкцию из `docs/project-init.md`.

Промпт проведёт через все остальные шаги:

- Заполнит `CLAUDE.md` под проект (имя, тип, префикс, платформа, ветки, коммиты).
- Адаптирует `README.md` (заголовок, описание, ссылки).
- Проверит подключение MCP-сервера `codepilot1c`, при необходимости подскажет команду подключения.
- Подключит skill `bsl-check` (по `docs/bsl-check-setup.md`) или удалит его, если не нужен.
- Создаст `.claude/settings.local.json` из примера.
- Очистит примеры из `planning/examples/`.
- Опционально создаст первый коммит и удалит сам себя.

Подробности — в [`docs/project-init.md`](docs/project-init.md). Промпт идемпотентен: можно запускать повторно.

## Цикл работы (SDD)

1. **Issue → спека → код**, не наоборот.
2. На каждое значимое изменение — папка `specs/<prefix>-<N>/` с `spec.md` + `plan.md` (копируется из `_template/`).
3. Спека согласуется (статус `draft` → `approved`), и только после `approved` начинается код в ветке `feature/<prefix>-<N>`.
4. Расхождение кода и спеки разрешается **обновлением спеки** в том же PR.
5. После merge: статус `done`, папка переносится в `specs/done/<prefix>-<N>/`.

Подробности — в [`specs/README.md`](specs/README.md) и [`CLAUDE.md`](CLAUDE.md) → раздел «Цикл работы над фичей».

## Обновление проектов из шаблона

Шаблон развивается, и проекты могут подтягивать его обновления. В каждом проекте, созданном из шаблона, есть skill [`sync-template`](.claude/skills/sync-template/SKILL.md): команда `/sync-template` (или просьба «подтяни изменения из шаблона») сверяет переносимые файлы — docs со стандартами, скиллы, шаблоны спек — и забирает обновления, не трогая проектное (`CLAUDE.md`, `README.md`, настройки, `planning/examples/`). Нейтральный префикс `prj_` в примерах кода автоматически заменяется на префикс проекта из `CLAUDE.md`. Если локальный файл содержит правки, которых нет в шаблоне, скилл их не затирает, а предлагает отправить в шаблон — поток работает в обе стороны.

В проект, созданный не из шаблона, достаточно скопировать каталог `.claude/skills/sync-template/`.

## Источник

Шаблон сделан на базе репозитория [PrintWizard](https://github.com/vandalsvq/printwizard) — извлечены универсальные части: стандарты BSL, методология SDD, базовая конфигурация Claude Code.
