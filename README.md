# edt1c-ai-template

Шаблон репозитория для разработки на 1С:Предприятие в EDT с использованием **Claude Code** и методологии **Specification-Driven Development (SDD)**.

## Что внутри

```text
.
├── CLAUDE.md           # Главный документ для Claude Code: соглашения, ссылки на docs/specs
├── README.md           # Этот файл
├── .gitignore          # Игнор для EDT, 1С, macOS, Python, IDE
├── .gitattributes      # *.bin binary — двоичные макеты EDT без конвертации EOL
├── .mcp.json.example   # Пример подключения MCP-серверов (codepilot1c, yaxunit-runner)
├── .claude/
│   ├── settings.json                    # Общие настройки Claude Code (commit'ятся)
│   ├── settings.local.json.example      # Пример локальных permissions (скопировать в settings.local.json)
│   └── skills/
│       ├── bsl-check/                   # Skill проверки синтаксиса 1С по справочнику shcntx_ru
│       ├── close-task/                  # Skill закрытия задачи по SDD (/close-task)
│       ├── sync-template/               # Skill забора переносимых файлов из шаблона (/sync-template)
│       ├── push-to-template/            # Skill подъёма правок обратно в шаблон (/push-to-template)
│       ├── skd-*/  (5 навыков)          # СКД: анализ, генерация, правка, валидация — из cc-1c-skills
│       └── mxl-*/  (4 навыка)           # Табличные документы — из cc-1c-skills
├── licenses/
│   └── cc-1c-skills-LICENSE             # MIT апстрима вендоренных навыков skd-*/mxl-*
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
│   ├── testability.md                   # Проверяемость и автономные headless-прогоны
│   ├── skd-mxl-toolkit.md               # Навыки skd-*/mxl-*: границы применения и нюансы EDT
│   ├── yaxunit-bootstrap.md             # Playbook развёртывания YAxUnit + METR на новом проекте
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

Шаблон развивается, и поток правок идёт в обе стороны: общие правила приезжают из шаблона, а доработки стандартов рождаются в проектах — там реальный код. На это есть пара скиллов:

- [`sync-template`](.claude/skills/sync-template/SKILL.md) — `/sync-template` **забирает** обновления шаблона: сверяет переносимые файлы (docs со стандартами, скиллы, шаблоны спек), не трогая проектное (`CLAUDE.md`, `README.md`, настройки, `.gitignore`, `planning/examples/`). Нейтральный префикс `prj_` и плейсхолдер `<Каталог.Имя>` автоматически заменяются на значения из `CLAUDE.md` проекта. Локальные правки, которых нет в шаблоне, не затираются.
- [`push-to-template`](.claude/skills/push-to-template/SKILL.md) — `/push-to-template` **поднимает** правку обратно в шаблон с обратной генерализацией: префикс проекта → `prj_`, имена проектов → плейсхолдеры, плюс чеклист смысловой чистки (номера задач, пути стенда, имена ролей и подсистем, названия продукта). Работает в клоне шаблона и останавливается на локальном коммите — push и PR остаются за владельцем.

В проект, созданный не из шаблона, достаточно скопировать каталоги `.claude/skills/sync-template/` и `.claude/skills/push-to-template/`.

## Источник

Шаблон сделан на базе репозитория [PrintWizard](https://github.com/vandalsvq/printwizard) — извлечены универсальные части: стандарты BSL, методология SDD, базовая конфигурация Claude Code.

## Благодарности и смежные проекты

- **[ondysss/codepilot1c-edt](https://github.com/ondysss/codepilot1c-edt)** (AGPL-3.0) — плагин для 1C:EDT, вокруг которого построена вся инструментальная часть шаблона. Одновременно расширение IDE и MCP-сервер: даёт агенту типизацию, анализ логики, метаданные, формы, СКД, роли, диагностику, отладчик и профилировщик рантайма, прогон YAxUnit — через понимание модели EDT, а не текстовый разбор файлов. Ставится в EDT через update site `https://ondysss.github.io/codepilot1c-edt/` (Help → Install New Software → «1C Copilot»), поднимает MCP по HTTP на `http://127.0.0.1:8765/mcp`.

  Справочник инструментов со сценариями — [`docs/codepilot1c-reference.md`](docs/codepilot1c-reference.md), подключение — [`.mcp.json.example`](.mcp.json.example).

- **[Nikolay-Shirokov/cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills)** (MIT) — большой набор навыков для AI-агентов под полный цикл разработки на 1С:Предприятие 8.3: внешние обработки и отчёты, управляемые формы, табличные документы, СКД, роли, метаданные, расширения, работа с базами, веб-публикация и тестирование через веб-клиент. Поддерживает не только Claude Code, но и Cursor, Codex, Gemini CLI и другие агенты.

  **Из него вендорены девять навыков** — `skd-*` и `mxl-*` — в [`.claude/skills/`](.claude/skills/), с адаптацией под EDT (рантайм Python, пути `Template.dcs` / `Template.mxlx`, оговорки по кодировке и порядку заведения макета). Границы применения и нюансы — [`docs/skd-mxl-toolkit.md`](docs/skd-mxl-toolkit.md).

  Остальное не берётся: подход апстрима **дополняет** этот шаблон, а не пересекается с ним: `cc-1c-skills` даёт агенту абстракции над XML-форматами и CLI конфигуратора и работает без EDT, а `edt1c-ai-template` строится вокруг EDT, MCP-сервера и методологии SDD. Если работаете в конфигураторе или нужен агент вне Claude Code — смотреть туда в первую очередь.

- **[vandalsvq/hbk_md](https://github.com/vandalsvq/hbk_md)** — распакованный справочник синтаксиса 1С (`shcntx_ru`) в markdown, на котором работает skill `bsl-check` (см. [`docs/bsl-check-setup.md`](docs/bsl-check-setup.md)).
