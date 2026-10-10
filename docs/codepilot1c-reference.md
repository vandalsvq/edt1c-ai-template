# MCP codepilot1c - справочник инструментов

MCP-сервер `codepilot1c` предоставляет около сотни инструментов для работы с EDT-проектом
1C:Enterprise. Инструменты понимают структуру EDT и работают через BM API - в отличие от
стандартных Read/Edit/Write.

`tools/list` отдаёт **103** инструмента: 33 доступны всегда, ещё 70 раскрываются через
`discover_tools`. Всего категорий восемь и в них 71 инструмент (bsl 14, metadata 22, forms 4,
extensions 5, dcs 1, qa 7, diagnostics 10, workspace 8) - на единицу больше, чем видно в
`tools/list`, из-за закрытого `get_infobase_credentials`.

Сервер - плагин 1C:EDT [ondysss/codepilot1c-edt](https://github.com/ondysss/codepilot1c-edt) (AGPL-3.0),
update site `https://ondysss.github.io/codepilot1c-edt/`.

Справочник сверен с живым сервером **2026-10-04** (плагин `1.3.9.20261003-0831`, EDT `1.35.3`,
MCP Host `1.3.0`, Windows-воркспейс). Транспорт - HTTP: `http://127.0.0.1:8765/mcp` (порт -
`mcp.host.http.port` в настройках плагина, у каждой машины может быть свой, см. «Политика
изменяющих вызовов»). Сверка 2026-10-04 - `initialize` и сырой `tools/list` новой
сборки, сравнение тегов upstream `0925-1004...1003-0831` и пробные вызовы. Полная сверка
2026-09-30 (`0925-1004`, macOS) шла против снимка `20260915-1537` с байткодом двух jar из
`~/.p2/pool/plugins` и заметками релизов upstream.

> `get_infobase_credentials` числится в категории `diagnostics`, но **вызвать его нельзя**:
> в `tools/list` его нет, а прямой вызов после `discover_tools` отвечает
> `Tool is not exposed` (проверено 2026-09-20).

**Что изменилось с прошлой сверки (2026-09-30, плагин `1.3.9.20260925-1004`):**

Один релиз upstream и в нём один коммит `e509367d` - хотфикс
[#95](https://github.com/ondysss/codepilot1c-edt/issues/95). Состав инструментов и схемы
прежние (103 = 33 + 70).

- **Изменяющие инструменты без `validation_token` в контракте стали вызываемыми**:
  `workspace_import_project`, `write_file`, `git_mutate`, `connect_infobase`,
  `import_project_from_infobase`. Раньше хост отказывал им при любых настройках
  (`confirmation_unavailable_tool_policy`). Правило «токен перед мутацией» для остальных
  инструментов прежнее - «Политика изменяющих вызовов»;
- **`workspace_import_project(refresh=true)` на открытом проекте** - штатное обновление
  проекта, то же, что F5 в EDT («Импорт проектов»);
- **на Windows модель EDT подхватывает правки мимо MCP сама** - BSL и XML `.form`, проверено
  пробами («`workspace_copy_transform` - перенос модуля с заменами»).

**Ранее (2026-09-30, `0915-1537` → `0925-1004`):** четыре хотфикса upstream, из схем поменялась
только `mutate_form_model` - командные панели форм (раздел «Формы» → «Командные панели»):
`commandBars[]` в `inspect_form_layout`, операции `set_auto_command_bar` и
`set_excluded_commands`, `shortcut` и `picture` у `add_command` (**`picture` ломает форму**,
SU113), `add_button` без родителя встаёт в командную панель формы, с `parent_item_id` таблицы -
в панель таблицы. Старые отказы BM API на кнопках командной панели остались (`set_item` /
`remove_item` их не находят). `edt_diagnostics(command="metadata_smoke")` на проекте внешнего
отчёта/обработки пропускает мутирующую часть с кодом `SKIPPED_EXTERNAL_PROJECT`.

**Установка обновления может не дойти до EDT** (2026-09-30, macOS): p2 записал новую сборку в
профиль, а `bundles.info` оставил на старой - EDT после рестарта поднял прежнюю версию. На
Windows 2026-10-04 обновление `0915-1537` → `1003-0831` встало с первого рестарта. Как
проверить и чем лечить - «Проверка живости сервера».

Не пересверялись вживую: поведение `update_infobase`, сценарии QA, `add_event_handler` в
смешанном батче и формы, созданные `create_form` (issue #80 upstream открыт).

Состав инструментов между сборками меняется в обе стороны: `get_diagnostics` пропадал в сборке
`20260820-1223` и вернулся к 2026-09-05. Сверять состав `tools/list`, а не полагаться на прошлые
записи справочника, в том числе на эту.

---

## Содержание

1. [Ключевые правила](#ключевые-правила)
2. [BSL - чтение и анализ кода](#bsl--чтение-и-анализ-кода)
3. [Навигация по коду и запросам](#навигация-по-коду-и-запросам)
4. [Метаданные](#метаданные)
5. [Макеты](#макеты)
6. [Формы](#формы)
7. [Роли](#роли)
8. [СКД](#скд)
9. [Расширения и внешние объекты](#расширения-и-внешние-объекты)
10. [QA - тестирование](#qa--тестирование)
11. [Отладка и профилирование](#отладка-и-профилирование)
12. [Диагностика](#диагностика)
13. [Runtime, инфобаза и веб-клиент](#runtime-инфобаза-и-веб-клиент)
14. [Workspace и Git](#workspace-и-git)
15. [Вспомогательные инструменты](#вспомогательные-инструменты)
16. [Skills сервера](#skills-сервера)
17. [GSD - фазовая машина сервера](#gsd--фазовая-машина-сервера)
18. [Типовые сценарии](#типовые-сценарии)

---

## Ключевые правила

### 1. Validation token - обязателен перед любой мутацией

Перед каждой мутирующей операцией нужно получить одноразовый токен:

```text
edt_validate_request → validation_token → передать в мутирующий инструмент
```

`edt_validate_request` принимает три параметра:

- `project` - имя EDT-проекта
- `operation` - точное имя мутирующего инструмента (enum):
  `create_metadata`, `add_metadata_child`, `update_metadata`, `delete_metadata`,
  `ensure_module_artifact`, `create_form`, `mutate_form_model`, `apply_form_recipe`,
  `mutate_role_rights`, `render_template`,
  `dcs_manage`, `extension_manage`, `external_manage`,
  и явные подкоманды (`dcs_create_main_schema`, `dcs_upsert_query_dataset`,
  `dcs_upsert_parameter`, `dcs_upsert_calculated_field`,
  `extension_create_project`, `extension_adopt_object`, `extension_set_property_state`,
  `external_create_report`, `external_create_processing`)
- `payload` - те же аргументы, что потом будут переданы в мутирующий инструмент
  (без `validation_token`); для composite-инструментов обязательно включает `command`

Токен одноразовый - для каждой мутации отдельный вызов.
Не нужен для read-only инструментов.

```text
edt_validate_request(
  project = "<Каталог.Имя>",
  operation = "create_metadata",
  payload = {kind: "Catalog", name: "prj_Новый"}
) → validation_token
```

### 2. Порядок создания/редактирования модуля

```text
edt_validate_request(operation="ensure_module_artifact", ...) → token
ensure_module_artifact(..., validation_token=token) → путь к .bsl
edit_file(...)
```

`ensure_module_artifact` теперь требует `validation_token`.
Создаёт `.bsl`-файл, если его ещё нет, и возвращает путь для дальнейшего `edit_file`.

### 3. Предпочтение инструментов для файлов

- `read_file`, `write_file`, `edit_file` - предпочтительны перед стандартными Read/Write/Edit:
  понимают контекст EDT. Контракт каждого - в разделе «Вспомогательные инструменты».
- `edit_file` запрещает редактировать `.mdo` (только через `allow_metadata_descriptor_edit=true`
  как аварийный override; обычно метаданные правятся через BM API).
- `glob` и `grep` (MCP) в общем случае уступают стандартным Glob/Grep - те богаче (output modes,
  count, multiline) и экономнее по токенам. **Исключение - поиск сразу по хосту и расширению:**
  у MCP-`grep` есть `project`, а `include_extensions` (по умолчанию `true`) добавляет к нему
  проекты `<project>.<extension>`. Одним вызовом накрывается то, для чего стандартному Grep
  нужны два прохода по разным каталогам.

### 3.1. Имя проекта передавать явно

`projectName` / `project` стал необязательным у `scan_metadata_index`, `inspect_role_rights`,
`resolve_web_client_url`, `get_diagnostics`: без него берётся проект активного редактора либо
единственный открытый. В нашем воркспейсе открыто **два** проекта - хост `<ХостПроект>` и
расширение `<Каталог.Имя>`, - поэтому пропуск параметра молча уводит запрос
не туда. Всегда передавать явно; единственное штатное исключение - `update_infobase` (см.
«Диагностика»), где нужен именно хост.

### 4. Идентификация модулей и объектов

BSL-инструменты идентифицируют модуль парой `projectName` + `filePath` (путь относительно `src/`),
а не FQN модуля.

```text
projectName = "<Каталог.Имя>"
filePath    = "CommonModules/prj_Ядро/Module.bsl"
```

Метаданные идентифицируются через FQN (`Catalog.prj_Шаблоны`, `Document.X.Form.Y`,
`Catalog.X.Template.Y` и т.п.).

---

## BSL - чтение и анализ кода

| Инструмент | Назначение |
| --- | --- |
| `bsl_module_context` | Контекст модуля: владелец, вид, прагмы, число методов |
| `bsl_list_methods` | Список процедур/функций модуля с сигнатурами и диапазонами строк (фильтры, пагинация) |
| `bsl_module_exports` | Только экспортные методы модуля (фильтры, пагинация) |
| `bsl_get_method_body` | Тело конкретного метода с точным диапазоном строк |
| `bsl_analyze_method` | Анализ метода: сложность, вызовы, неиспользуемые параметры, рискованные ветки |
| `bsl_scope_members` | Методы, свойства и доступные элементы в текущей области видимости |
| `bsl_symbol_at_position` | Семантический символ в позиции: вид, имя, владелец |
| `bsl_type_at_position` | Выведенный тип выражения в указанной позиции |
| `edt_content_assist` | Варианты автодополнения для позиции в BSL |
| `edt_find_references` | Семантические ссылки на объект метаданных через модель проекта |

### Параметры, общие для большинства BSL-инструментов

- `projectName` - имя EDT-проекта
- `filePath` - путь к модулю относительно `src/` (например, `CommonModules/prj_Ядро/Module.bsl`)
- Списочные инструменты (`bsl_list_methods`, `bsl_module_exports`, `bsl_scope_members`,
  `edt_content_assist`) поддерживают `limit`, `offset`, `name_contains`/`contains`
- `kind` (`bsl_list_methods`, `bsl_get_method_body`, `bsl_analyze_method`) принимает
  `any` (по умолчанию), `procedure`, `function`
- `bsl_scope_members` дополнительно понимает `language` (`ru`/`en`) - язык имён членов и типов,
  `edt_content_assist` - `extendedDocumentation=true` (расширенное описание предложений)

### Паттерны использования

**Прочитать реализацию метода перед правкой:**

```text
bsl_get_method_body(
  projectName = "<Каталог.Имя>",
  filePath    = "CommonModules/prj_Ядро/Module.bsl",
  name        = "ИмяМетода",
  context_lines = 0     # опционально: вернуть пару строк контекста до/после
)
```

При коллизии имён уточнять `start_line` или `kind` (`procedure`/`function`).

**Найти все экспортные методы модуля:**

```text
bsl_module_exports(
  projectName    = "<Каталог.Имя>",
  filePath       = "CommonModules/prj_СхемаКлиентСервер/Module.bsl",
  name_contains  = "Создать"   # опциональный фильтр
)
```

**Узнать тип переменной в конкретной позиции:**

```text
bsl_type_at_position(
  projectName = "...",
  filePath    = "...",
  line        = 42,
  column      = 15
)
```

**Найти все вхождения объекта метаданных:**

```text
edt_find_references(
  projectName = "<Каталог.Имя>",
  objectFqn   = "Catalog.prj_Шаблоны",
  limit       = 100
)
```

> `edt_find_references` принимает FQN объекта метаданных, а не «prj_Ядро.МойМетод».
> Для вызовов конкретного метода - `edt_get_method_call_hierarchy` (см. следующий раздел),
> `Grep` - как быстрый запасной вариант.

---

## Навигация по коду и запросам

| Инструмент | Назначение |
| --- | --- |
| `edt_get_method_call_hierarchy` | Иерархия вызовов метода: `direction` = `callers`/`callees`/`both`, `depth` (по умолчанию 1) |
| `edt_get_project_call_graph` | Граф прямых вызовов BSL по всему проекту или одному модулю (`modulePath`) |
| `edt_go_to_definition` | Определение символа по `symbolFqn` или по `position` (`fileUri`+`line`+`column`) |
| `edt_get_symbol_info` | Детальная информация о символе (те же способы адресации) |
| `edt_list_modules` | Все BSL-модули проекта с владельцем и путём; фильтр `objectType` |
| `edt_get_module_structure` | Области, методы и экспортные процедуры модуля; `full=true` - с местами вызова |
| `edt_search_in_code` | Поиск по коду: `searchType` = `text`/`regex`, `scope` = `all`/`modules`/**`queries`** |
| `validate_query` | Проверка текста запроса по метаданным проекта; `dcsMode=true` - для запросов СКД |
| `get_tasks` | Маркеры TODO/FIXME/XXX проекта: файл, строка, сообщение, приоритет |
| `get_bookmarks` | Закладки Eclipse/EDT проекта |
| `edt_get_problem_summary` | Быстрая сводка проблем валидации проекта (числа + список) |

### `edt_get_project_call_graph` - граф вызовов проекта

Появился в сборке `1.3.9.20260820-1223`. Отдаёт детерминированный граф **прямых** вызовов BSL;
методы отождествляются по пути файла, а не по имени, - одноимённые методы разных модулей
не сливаются.

| Параметр | Назначение |
| --- | --- |
| `projectName` | имя EDT-проекта (обязательный) |
| `modulePath` | путь модуля-источника относительно `src/`; без него - весь проект |

```text
# Граф по одному модулю
edt_get_project_call_graph(projectName="<Каталог.Имя>",
                           modulePath="CommonModules/prj_Ядро/Module.bsl")
```

Отличие от `edt_get_method_call_hierarchy`: тот отвечает на вопрос про **один метод** (кто зовёт,
кого зовёт, на заданную глубину), этот отдаёт связи разом. Полезен для оценки связности перед
рефакторингом и для проверки архитектурных ограничений (см. `CLAUDE.md`): по графу видно
фактические зависимости, а не задекларированные. По всему проекту ответ объёмный - начинать
с `modulePath`.

### `validate_query` - обязательный шаг перед вставкой запроса

Резолвит имена таблиц и полей по метаданным конфигурации **и расширения**:

```text
validate_query(
  projectName = "<Каталог.Имя>",
  queryText   = "ВЫБРАТЬ Макеты.Ссылка КАК Ссылка ИЗ Справочник.prj_Макеты КАК Макеты"
)
→ Найдены ошибки в запросе. (errors: 1, ...)
  [ERROR] line 3:9 - Поле 'Макеты.НесуществующееПоле' не найдено
```

Дешевле, чем ловить ту же ошибку на исполнении. Для запросов в макете СКД - `dcsMode=true`
(разрешает `{...}`-блоки и поля набора данных).

### Найти всех вызывающих метод

```text
edt_get_method_call_hierarchy(
  projectName = "<Каталог.Имя>",
  methodFqn   = "CommonModule.prj_СхемаКлиентСервер.СоздатьСхему",
  direction   = "callers",
  depth       = 2
)
```

---

## Метаданные

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `scan_metadata_index` | Индекс верхнеуровневых объектов по проекту с фильтрами | R |
| `edt_metadata_details` | Детальные сведения об объектах: свойства, дети, формы, модули | R |
| `edt_field_type_candidates` | Допустимые EDT-типы для поля существующего объекта | R |
| `inspect_platform_reference` | Сигнатуры методов и свойств типов платформы (Query, DocumentObject и др.) - без текстовых описаний, см. ниже | R |
| `edt_get_configuration_properties` | Свойства конфигурации проекта | R |
| `edt_get_tags` | Теги EDT-проекта и число объектов по каждому (во многих проектах теги не используются) | R |
| `edt_get_objects_by_tags` | Объекты метаданных с указанными тегами | R |
| `edt_validate_request` | Получить validation_token перед мутацией | R |
| `create_metadata` | Создать новый верхнеуровневый объект метаданных | **W** |
| `add_metadata_child` | Создать дочерний объект под существующим владельцем | **W** |
| `update_metadata` | Обновить свойства существующего объекта | **W** |
| `delete_metadata` | Удалить объект или дочерний элемент | **W** |
| `ensure_module_artifact` | Материализовать `.bsl`-файл для объекта (требует validation_token) | **W** |

### Параметры

- `scan_metadata_index(projectName, scope?, nameContains?, language?, limit?, includeModules?)`
- `edt_metadata_details(projectName, objectFqns[], full?, language?)` - массив FQN
- `edt_field_type_candidates(project, target_fqn, field, limit?)`
- `inspect_platform_reference(project, type_name?, contains?, member_filter?, language?, limit?, offset?)`
- `create_metadata(project, kind, name, validation_token, properties?, synonym?, comment?)`
- `add_metadata_child(project, parent_fqn, child_kind, name, validation_token, ...)`
- `update_metadata(project, target_fqn, changes, validation_token)` -
  `changes` имеет формат `{set: {...}, unset: [...], children_ops: [...]}`
- `delete_metadata(project, target_fqn, validation_token, recursive?, force?)`
- `ensure_module_artifact(project, object_fqn, validation_token, module_kind?, create_if_missing?, initial_content?)` -
  `module_kind` принимает `auto` (по умолчанию), `object`, `manager`, `module`, `form`
  и их варианты написания (`object_module`, `objectmodule`, `manager_module`, `form_module`, …),
  регистр не важен

### `inspect_platform_reference` - что даёт и чего не даёт

Проверено на живом сервере 2026-08-14, поведение сверено с исходниками плагина
(`GetPlatformDocumentationTool` / `EdtPlatformDocumentationService`). В разговорах автора
инструмент может называться «get doc» - это имя Java-класса, в MCP он называется
`inspect_platform_reference`.

**Даёт:**

- резолв имени типа ru↔en (`Запрос` → `Query`, `ЧтениеXML` → `XMLReader`); при неточном имени - список `candidates`
- методы: типы возвращаемого значения, все наборы параметров (`paramSets` - перегрузки),
  типы параметров, наличие значения по умолчанию
- свойства: типы, `readable` / `writable`
- пагинация `limit`/`offset` + флаги `hasMoreMethods` / `hasMoreProperties`

**Не даёт:**

- **текста документации.** Поле `help` в ответе всегда пустое (`{}`). Инструмент читает
  `Help.getPages()` из mcore-модели EDT, а она у платформенных типов не заполнена, - то есть
  это сигнатуры из семантического слоя, а не статьи синтакс-помощника. Ни описания метода,
  ни примеров, ни доступности «клиент/сервер», ни версии платформы, с которой метод появился
- **глобального контекста.** Типы `ГлобальныйКонтекст` / `GlobalContext` в индексе отсутствуют,
  поэтому глобальные функции (`ПоказатьВопросПользователю`, `СтрНайти`, `ТекущаяДатаСеанса`)
  через инструмент недоступны в принципе - только члены типов

**Как искать метод, когда тип неизвестен:** не через `contains`, а через `type_name`.
`contains` без `type_name` не работает вовсе (запрос завершается раньше фильтрации и отдаёт
алфавитный список типов с начала). Зато если в `type_name` передать имя метода или свойства,
сервис сам ищет владеющий тип и подставляет запрос как фильтр:
`type_name="ВыполнитьПакетСПромежуточнымиДанными"` → `Query`/`Запрос` с одним этим методом.

> **Ловушка:** владеющий тип берётся **первый по алфавиту** из всех подходящих. Для
> распространённых имён это даёт мусор: `type_name="Добавить"` возвращает
> `РегистрБухгалтерииНаборЗаписейИмяРегистраБухгалтерии`, а не то, что имелось в виду.
> Приём годится только для достаточно уникальных имён.

Отсюда правило выбора: «есть ли у типа такой метод и какая у него сигнатура» -
`inspect_platform_reference`; «что метод делает, где доступен, пример», а также любые
вопросы про глобальные функции - skill `bsl-check` (локальный hbk-справочник).

### `create_metadata.kind` - допустимые виды

`Catalog`, `Document`, `InformationRegister`, `AccumulationRegister`, `AccountingRegister`,
`CalculationRegister`, `CommonModule`, `CommonAttribute`, `Enum`, `Report`, `DataProcessor`,
`Constant`, `CommandGroup`, `Interface`, `Language`, `Style`, `StyleItem`, `SessionParameter`,
`SettingsStorage`, `XDTOPackage`, `WSReference`, `Role`, `Subsystem`, `ExchangePlan`,
`ChartOfAccounts`, `ChartOfCharacteristicTypes`, `ChartOfCalculationTypes`, `BusinessProcess`,
`Task`, `CommonForm`, `CommonCommand`, `CommonTemplate`, `CommonPicture`, `ScheduledJob`,
`FilterCriterion`, `DefinedType`, `Sequence`, `DocumentJournal`, `DocumentNumerator`,
`EventSubscription`, `FunctionalOption`, `FunctionalOptionsParameter`, `WebService`,
`HTTPService`, `ExternalDataSource`, `IntegrationService`, `Bot`, `WebSocketClient`.

### `add_metadata_child.child_kind` - допустимые виды детей

`Attribute`, `Tabular_Section`, `Command`, `Form`, `Template`, `Dimension`, `Resource`,
`Requisite`, **`EnumValue`**, `URLTemplate`, `HTTPMethod`.

Последние два - дети `HTTPService`: шаблон URL и метод в нём. У `HTTPMethod` есть свой
`http_method` (`GET`/`POST`/`PUT`/`DELETE`/`PATCH`/`MERGE`/`OPTIONS`/`TRACE`/`CONNECT`,
WebDAV-набор и `ANY`).

При `child_kind=Form` дополнительно: `form_usage` (`OBJECT`/`LIST`/`CHOICE`/`AUXILIARY`),
`set_as_default`, `wait_ms`. При `child_kind=Template` - `template_type`
(`spreadsheet`/`html`/`text`/`binary`/`dcs`/`active_document`).

**`EnumValue` (появился к 2026-08-20)** - единственный способ добавить значение в существующее
перечисление: `create_metadata` создаёт сам `Enum`, но значения в него класть не умеет.
`parent_fqn` - FQN перечисления, `name` - имя значения.

**Batch.** `properties.children=[{name, synonym, comment}, …]` создаёт пачку детей одним вызовом;
при этом top-level `name` не передавать. Числовой тип задаётся как `Number(15,3)` через
`properties` + `scale=3`.

### Паттерн: добавить реквизит к справочнику

```text
1. edt_field_type_candidates(
     project    = "<Каталог.Имя>",
     target_fqn = "Catalog.prj_Шаблоны",
     field      = "type"
   )

2. edt_validate_request(
     project   = "<Каталог.Имя>",
     operation = "add_metadata_child",
     payload   = {parent_fqn: "Catalog.prj_Шаблоны", child_kind: "Attribute", name: "prj_Описание"}
   ) → token

3. add_metadata_child(
     project           = "<Каталог.Имя>",
     parent_fqn        = "Catalog.prj_Шаблоны",
     child_kind        = "Attribute",
     name              = "prj_Описание",
     properties        = {type: "String", length: 150},
     validation_token  = token
   )
```

**Строка без ограничения длины так не создаётся:** на `properties.length = 0` валидация
отвечает успехом, а в `.mdo` уезжает `String(150)` (реквизит табличной части, ресурс
регистра). Неограниченная строка - вторым шагом: `update_metadata` с
`set.type = {types: [String], stringQualifiers: {length: 0}}`, после чего в `.mdo` должен
стоять пустой `<stringQualifiers/>`. Выбор длины - по таблице раздела «Строковый реквизит
формы».

### Паттерн: создать новый объект метаданных

```text
1. edt_validate_request(
     project   = "<Каталог.Имя>",
     operation = "create_metadata",
     payload   = {kind: "Catalog", name: "prj_НовыйСправочник"}
   ) → token

2. create_metadata(
     project          = "<Каталог.Имя>",
     kind             = "Catalog",
     name             = "prj_НовыйСправочник",
     validation_token = token
   )
```

> После `delete_metadata` обязательно проверить `edt_get_problem_summary` и `edt_find_references` -
> инструмент предупреждает о влиянии на формы и другие объекты.

### Удаление общего модуля

`delete_metadata` на общем модуле без `force` отвечает `METADATA_DELETE_CONFLICT` со списком
ссылок. Если после этого убрать регистрации из `Configuration.mdo` руками, BM-модель теряет
объект, и повтор с `force` даёт `METADATA_NOT_FOUND`. Надёжный порядок:

1. убрать регистрации вручную - `Configuration.mdo` (`content` и `commonModules`) и состав
   подсистем;
2. удалить каталог модуля;
3. дать EDT перечитать проект (`workspace_copy_transform` с `refresh_workspace`) и проектной
   диагностикой убедиться, что ссылок на модуль не осталось.

---

## Макеты

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `inspect_template` | Прочитать содержимое макета: ячейки, параметры, именованные области | R |
| `render_template` | Сгенерировать макет из секционного JSON - полная замена `.mxl`-файла | **W** |

`render_template` требует `validation_token` (получить через `edt_validate_request`,
`operation` для composite-сценариев - точная команда инструмента; обычно достаточно общего токена).

Поддерживаемые секции: `Шапка`, `ШапкаТаблицы`, `СтрокаТаблицы`, `Подвал`, `Заголовок`.
Стили строк: `default`, `title`, `table-header`, `table-row`, `total-row`, `signature`.

```text
# Прочитать текущий макет
inspect_template(
  project      = "<Каталог.Имя>",
  template_fqn = "Catalog.prj_Макеты.Template.ПечатнаяФорма"
)

# Сгенерировать макет
edt_validate_request(...) → token
render_template(
  project      = "<Каталог.Имя>",
  template_fqn = "Catalog.prj_Макеты.Template.ПечатнаяФорма",
  sections = [
    {name: "Шапка",         rows: [["Организация", "[Организация]"]]},
    {name: "СтрокаТаблицы", style: "table-row", rows: [["[Номенклатура]", "[Количество]"]]}
  ],
  validation_token = token
)
```

---

## Формы

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `inspect_form_layout` | Дерево элементов формы, dataPath, команды, свойства, командные панели (`commandBars[]`) | R |
| `create_form` | Создать новую управляемую форму для объекта метаданных | **W** |
| `mutate_form_model` | Точечные изменения модели существующей формы | **W** |
| `apply_form_recipe` | Применить декларативный recipe: создание, поиск, атрибуты, layout | **W** |

### Параметры инструментов форм

- `inspect_form_layout(project, form_fqn, include_invisible?, include_properties?, include_titles?, max_depth?, max_items?)`
- `create_form(project, owner_fqn, name, validation_token, usage?, synonym?, comment?, set_as_default?, managed?, wait_ms?)`
- `mutate_form_model(project, form_fqn, operations[], validation_token)`
- `apply_form_recipe(project, validation_token, form_fqn?, owner_fqn?, name?, attributes[]?, layout[]?, usage?, mode?, set_as_default?, ...)`

### `mutate_form_model.operations` - допустимые `op`

`set_form_props`, `add_group`, `add_field`, `add_table`, `add_command`, `add_button`, `set_item`,
`remove_item`, `move_item`, `set_auto_command_bar`, `set_excluded_commands`, `add_event_handler`,
`set_event_handler`, `remove_event_handler`.

- `add_field` - нужны `name` + `data_path` + `field_type`; **привязывает** UI-поле к уже
  существующему реквизиту формы, сам реквизит не создаёт (реквизиты - через `apply_form_recipe`)
- `add_table` - создаёт таблицу и с `data_path` на ValueTable/ValueTree **сам генерирует колонки**
- `add_command` - нужны `name` + `action` (обработчик) + `title`; необязательные `shortcut`
  (пишется как у дизайнера, `<shortcut>Ctrl+F9</shortcut>`) и `picture` - **не использовать**,
  см. «Командные панели». Заглушку обработчика дописывает в конец модуля, вне областей (SU48) -
  перенести в `ОбработчикиКомандФормы`
- `add_button` - нужны `name` + `command_name`. Без родителя кнопка встаёт в командную панель
  формы, с `parent_item_id` / `parent_item_name` таблицы - в командную панель этой таблицы, с
  родителем-группой - в группу. Имя кнопки сохраняется (до `0925-1004` EDT подменял его именем
  команды, а кнопка без родителя уезжала в корневые `items[]`)
- `add_command` и `add_button` подаются одним батчем (проверено 2026-09-30)
- `set_item` / `remove_item` / `move_item` - цель строго `item_id` (число) или `item_name` (строка),
  не `id`/`name`; родитель - `parent_item_id` / `parent_item_name`
- `set_auto_command_bar`, `set_excluded_commands` - встроенная командная панель формы или
  таблицы, подробности ниже

### Командные панели (с 2026-09-30, сборка `0925-1004`)

Встроенная командная панель (`autoCommandBar`) формы и каждой таблицы живёт вне дерева
`items[]`. `inspect_form_layout` отдаёт её отдельным массивом `commandBars[]`:

| Поле | Что в нём |
| --- | --- |
| `ownerKind` | `FORM` или вид элемента-владельца (`Table`); у таблицы ещё `ownerItemId` / `ownerItemName` |
| `kind` | `AUTO_COMMAND_BAR` |
| `autoFill` | заполнять ли панель стандартными командами |
| `excludedCommands` | скрытые стандартные команды |
| `availableCommands` | допустимые имена для `excludedCommands` (у формы - `Help`, `Close`, `OK`...; у таблицы - `Add`, `Delete`, `SortListAsc`, `Find`...) |
| `items` | кнопки панели с `id` и `commandRef` |

Операции (цель - `item_id` / `item_name` таблицы либо `target: "form"`):

```text
{op: "set_auto_command_bar",  item_name: "СписокТипов", auto_fill: true}
{op: "set_excluded_commands", item_name: "СписокТипов",
 excluded_commands: ["SortListAsc", "SortListDesc"], mode: "add"}   # replace (по умолчанию) | add | remove
```

`excluded_commands` обязателен и должен быть массивом; очистка списка - явный `[]` с
`mode: "replace"`. `set_form_props` / `set_item` эти свойства не пишут (отказ «unsupported
reference update»), `add_group` с видом командной панели не создавать - панель уже есть.

**Проверено вживую 2026-09-30** на форме обработки с таблицей:
`set_excluded_commands` и `set_auto_command_bar` дали ровно по строке `<excludedCommands>` у
таблицы и `<autoFill>true</autoFill>` в её панели - как у дизайнера, без замечаний EDT.

Чего по-прежнему нет:

- **кнопки панели не правятся и не удаляются.** `inspect_form_layout` показывает их в
  `commandBars[].items` с `id`, но `set_item` / `remove_item` отвечают `METADATA_NOT_FOUND` и по
  `item_id`, и по `item_name` (проверено 2026-09-30 на существующей кнопке и на только что
  созданной). Команды формы по-прежнему только создаются
- **`add_command.picture` пишет картинку не как дизайнер:** вложенный
  `<picture xsi:type="platform:PlatformPicture">` с `nameRu` = английское имя и новым
  пространством имён `platform` в корне формы, тогда как во всех формах проекта -
  ссылка `<picture xsi:type="core:PictureRef"><picture>StdPicture.X</picture></picture>`.
  EDT отвечает ошибкой **SU113 «This field can be only reference»**. Команда с одним
  `shortcut` проходит чисто - значит, дело именно в картинке. Картинку команды ставить в
  дизайнере

### Что инструменты форм молча делают по-своему (проверено 2026-08-16)

- `apply_form_recipe` с `type: "String"` создаёт реквизит **`String(150)`**, а не строку неограниченной
  длины. Для путей к файлам и текстов сообщений это тихое обрезание - длину задавать явно
  (`String(1024)`) либо править `stringQualifiers` в `.form` после создания
- `add_group` **игнорирует `title` из `set`** (группа остаётся без заголовка) и создаёт её
  `HorizontalIfPossible` c `WeakSeparation` и видимым заголовком. `set_item` заголовок группы
  ставит, а ориентацию, отображение и показ заголовка - нет (`Unknown form property: group`,
  `representation`); их дописывать в `.form` руками - порядок ниже
- `add_field` **тоже игнорирует `title` и прочие свойства из `set`** - заголовок,
  `listChoiceMode`, `multiLine` доезжают только вторым проходом `set_item`. Вторым проходом
  проходят также `toolTip` и `inputHint` (`{ru, en}`), `toolTipRepresentation`, `width`,
  `maxWidth`, `autoMaxWidth`, `choiceButton`, `openButton`, `spinButton`, `dropListButton`
  (проверено 2026-09-27)
- многоязычное свойство элемента (`toolTip`, `title`) снимается пустыми строками по каждому
  языку - `{"ru": "", "en": ""}`; пустой объект `{}` ничего не меняет. Подсказку реквизита
  метаданных ставит `update_metadata` с `set.toolTip = {ru, en}`
- позиция нового элемента в родителе задаётся ключом `index` операции `add_field` / `add_group`
  (с нуля); без него элемент встаёт последним
- `add_event_handler` на собственной форме расширения (не заимствованной) работает, но заглушку
  процедуры дописывает **в конец модуля**, вне областей - перенести в нужную область
- **Ручная правка `.form` затирается следующей записью формы через MCP**, если модель EDT её
  не перечитала: инструмент сериализует свою копию формы целиком. Порядок: правка XML →
  обновление проекта (`workspace_copy_transform` любого `.bsl` проекта с `refresh_workspace`; сам
  `.form` этим инструментом не копируется - `STRUCTURED_EDT_ARTIFACT_BLOCKED`) → проверка, что
  модель видит правку (временная метка в заголовке и `inspect_form_layout`) → любая запись
  формы моделью, которая эту метку убирает; после неё сверить `.form` (проверено 2026-09-27)
- **Откат формы через `git checkout` модель тоже не перечитывает** (проверено 2026-09-30):
  файл на диске уже прежний, а `inspect_form_layout` продолжает показывать откаченные команды
  и кнопки - следующая запись формы через MCP вернула бы их в файл. После отката -
  `workspace_copy_transform` любого `.bsl` проекта в `sync-bridge.txt` с
  `refresh_workspace=true`, затем удалить `sync-bridge.txt` и убедиться по
  `inspect_form_layout`, что модель совпала с файлом. Это же единственный способ убрать
  пробные команды и кнопки панели: удалять их MCP не умеет
- **id элементов при ручной правке `.form` не брать «максимум плюс один»**: счётчик id формы -
  состояние модели EDT, ручная правка XML его не двигает, и следующий элемент из дизайнера
  получит тот же id - замечание `form-invalid-item-id`. Структуру формы вести дизайнером или
  MCP, руками - только то, что они не умеют (динамический `choiceList`, сохраняемые данные
  формы). Тогда id проверять на уникальность по каждому пространству отдельно (`items`,
  `attributes`, `formCommands`) и быть готовым, что следующая правка в дизайнере их
  переиграет. Достоверная проверка - `get_diagnostics` на уровне проекта: проверки формы на
  уровне файла и модуля этого не видят
- `create_form` пишет в `.form` свойства уровня формы `<group>Auto</group>` и
  `<showTitle>auto</showTitle>`. EDT их принимает, **платформа при выгрузке в конфигуратор -
  нет**: обновление информационной базы падает с `Исключение XDTO … Несоответствие свойства
  и элемента данных XDTO: Свойство: 'Group'` и указывает на `Ext/Form.xml`. Лечится
  `set_form_props` с `group: "Vertical"` и `showTitle: true` - как у прочих форм проекта.
  Проверять сразу после создания формы: до первого обновления базы ошибка ничем себя не
  выдаёт, диагностика EDT показывает ноль (проверено 2026-09-15)
- поэтому после любой пачки мутаций форму стоит открыть `inspect_form_layout` и сверить
  заголовки и раскладку, а не полагаться на успешный ответ инструмента

### Строковый реквизит формы: длина и многострочность - всегда осознанно

Оба свойства инструменты выставляют по умолчанию, и оба умеют испортить поле молча.
Перед мутацией решить, что за текст в реквизите, и после мутации **проверить в `.form`**:

| Что за текст | Длина (`stringQualifiers`) | Поле |
| --- | --- | --- |
| Ответ инструмента, лог, трассировка, текст запроса | пустой тег - без ограничения | `multiLine` + `wrap` + `height` (10-20) + `verticalStretch` |
| Заголовок, имя, ключ, путь к файлу | явная (`300`, `1024`) | однострочное |

Строка **без ограничения** в поле выбора или в коротком реквизите - тоже дефект: платформа
рисует такое поле многострочным. Правило симметрично: неограниченная длина только там,
где поле сознательно сделано многострочным.

Проверка после мутации - по `.form`, не по ответу инструмента: `stringQualifiers` у реквизита,
`multiLine` / `height` / `verticalStretch` в `InputFieldExtInfo`, `title` у элемента.

### Обработчики событий формы

```text
# событие формы
{op: "add_event_handler", target: "form", event: "ПриОткрытии", handler_name: "ПриОткрытии"}

# событие элемента
{op: "add_event_handler", item_name: "БазовыйURL", event: "ПриИзменении"}
```

`event` принимается на русском и английском, проверяется по списку допустимых событий элемента.
Без `handler_name` имя генерируется детерминированно (`{Элемент}{СобытиеEn}`).
`set_event_handler` - upsert той же пары (target, event), `remove_event_handler` - удаление.

**`call_type` - только для расширений**: `BEFORE` (по умолчанию), `AFTER`, `OVERRIDE`,
`CHANGE_AND_VALIDATE`. Это способ повесить обработчик на форму расширения средствами BM API.

### Динамические списки - только дизайнером (проверено 2026-08-04)

`apply_form_recipe` создаёт реквизит типа `DynamicList` **без `DynamicListExtInfo`**
(`mainTable` и `dynamicDataRead` в `set` отклоняются: *Unknown form property* /
*dynamicDataRead is supported only for attributes with DynamicListExtInfo*).
Дописывать `extInfo` руками в `.form` **нельзя**: получается неполный комплект
(нет группы пользовательских настроек компоновщика, у таблицы - своей `extInfo`),
и конвертация `Form.form` → `Form.xml` при загрузке в ИБ падает:

```text
Исключение XDTO произошло при чтении файла- zip:///.../Form.xml
Несоответствие свойства и элемента данных XDTO: Свойство: 'Group'
```

Коварство в том, что **`get_diagnostics` при этом чист** - ошибка вылезает только
при обновлении конфигурации ИБ. Динамический список (как и другие элементы с
компоновщиком настроек) добавлять в дизайнере EDT, MCP - для остального.

### Новая форма из BM API не собирается под режим совместимости 8.3.14

**Симптом** (проверено 2026-08-04): конфигурация не загружается в ИБ, при этом
`get_diagnostics` чист:

```text
Исключение XDTO произошло при чтении файла- zip:///…/Forms/<Форма>/Ext/Form.xml
Несоответствие свойства и элемента данных XDTO: Свойство: 'Group'
```

**Причина.** `create_form` / `apply_form_recipe` пишут в `.form` свойства и значения
по рантайму проекта (`DT-INF/PROJECT.PMF`, `Runtime-Version: 8.3.27`), не сверяясь с
`configurationExtensionCompatibilityMode` расширения (`8.3.14`). При выгрузке в
`Form.xml` схема 8.3.14 этих свойств не знает. **Дизайнер EDT так не делает** - формы,
правленные вручную при том же рантайме, чисты; то есть это дефект инструмента, а не
настройка проекта (вероятно, та же природа, что и `versionSupport is null` у
`add_event_handler` ниже). Параметра версии у MCP-инструментов форм нет.
Конкретно всплыли:

| Свойство / значение | Чинится на |
| --- | --- |
| `<textSize>Normal</textSize>` | удалить |
| `<autoMaxCardHeight>true</autoMaxCardHeight>` | удалить |
| `<showCommandBarNeedDereferenced>true</showCommandBarNeedDereferenced>` | удалить |
| `<rowSelectionMode>Auto</rowSelectionMode>` | удалить |
| `<pagesRepresentation>Auto</pagesRepresentation>` | `TabsOnTop` |
| `<group>Auto</group>` (уровень формы) | `Vertical` (`set_form_props{group:"VERTICAL"}`) |

**Как ловить.** Сравнить свойства новой формы со всеми формами проекта: то, что
встречается **только** в новой, и есть кандидат. Разовый скрипт: собрать
`<tag>value</tag>` регуляркой по всем `**/Form.form`, вычесть множества.

**Профилактика.** После сборки формы MCP-инструментами прогнать такую сверку
до первой загрузки в ИБ - `get_diagnostics` этот класс проблем не видит.

**Статус в upstream:** [ondysss/codepilot1c-edt#80](https://github.com/ondysss/codepilot1c-edt/issues/80)
(заведён 2026-08-04 на сборке `1.0.0.20260804-0436`) - там же описано падение
`add_event_handler`, вероятно общей природы.

### Известные отказы BM API (2026-08-04)

- `add_event_handler` на форме расширения падает с
  `EDT_TRANSACTION_FAILED: … IRuntimeVersionSupport.getRuntimeVersion … versionSupport is null`
  (upstream - [#80](https://github.com/ondysss/codepilot1c-edt/issues/80)).
  Обходной путь - обработчик формы дописать в `.form` (блок `<handlers>` рядом с
  `</autoCommandBar>`): элементы при этом не создаются, счётчик `id` не двигается
- Смешанный батч `add_command` + `add_button` + `add_event_handler` в одном вызове
  падает так же - обработчики событий подавать отдельным вызовом. Пара `add_command` +
  `add_button` с 2026-09-30 проходит одним батчем (так её подаёт и сам upstream)
- Элементы внутри `autoCommandBar` (кнопки формы) `set_item`/`remove_item` **не
  находят** - ни по `item_name`, ни по `item_id` (`METADATA_NOT_FOUND`; перепроверено
  2026-09-30 на сборке `0925-1004`, хотя `inspect_form_layout` их `id` теперь показывает).
  Команды формы (`formCommands`) им тоже недоступны: `add_command` только создаёт.
  Переименование команд/кнопок и правка их заголовков - дизайнером либо точечной
  правкой `.form` (согласовать 4 места: `formCommands.name`,
  `action/handler/name`, `items.name` и `items.commandName` кнопки)
- Реквизиты формы, наоборот, переименовываются штатно:
  `apply_form_recipe(attributes:[{action:"update", name:"Старое", set:{name:"Новое"}}])`,
  а следом `set_item{name, dataPath}` на связанный элемент - иначе `dataPath`
  останется висеть на старом имени
- `edt_diagnostics(command="update_infobase")` возвращает `UPDATE_FAILED` через
  2-3 с, хотя загрузка в ИБ реально стартует (видно в `.metadata/.log`:
  «Загрузка N объектов конфигурации»). Итог обновления проверять по логу или у
  владельца в EDT, не по коду возврата инструмента. Успех выглядит как цепочка
  «Загрузка N объектов…» → «Обновление конфигурации базы данных…» без `!ENTRY … 4 0`
  после неё; провал - `ConfigurationLoadException` с текстом причины от конфигуратора
  (`grep -n "ConfigurationLoadException" .metadata/.log`, дальше читать соседние
  строки: сам стектрейс бесполезен, причина - в двух строках над ним).
  Ошибки формата файлов конфигуратор выдаёт уже после EDT-валидации, поэтому чистые
  диагностики ничего не гарантируют - см. [`mdo-integrity.md`](mdo-integrity.md)
- **Мутация формы может задеть соседние артефакты того же объекта-владельца.**
  2026-08-09: после серии `mutate_form_model` / `apply_form_recipe` по форме
  `prj_Ассистент.Диагностика` у соседней формы `Настройки` обнулился `Module.bsl`
  (0 байт), а два текстовых макета обработки (`Templates/*/Template.txt`)
  оказались удалены. Диагностики при этом чистые - пустой модуль формы EDT
  замечаний не даёт. Предшествовал импорт правок из конфигуратора, так что
  виновата связка «новая EDT + BM API», а не конкретная операция.
  **После каждой формо-мутации смотреть `git status`** на посторонние `D` и
  обнулённые файлы; лечится `git checkout HEAD -- <пути>` (EDT перечитывает файл
  сам, проверка - `bsl_list_methods`), после чего повторить `update_infobase`:
  в базу мог уехать уже испорченный объект

### Правила, которые проверяет платформа

- Boolean-колонка внутри таблицы - только `field_type="INPUT_FIELD"` (флажок платформа рисует
  сама); `CHECK_BOX_FIELD`/`RADIO_BUTTON_FIELD`/`PROGRESS_BAR_FIELD`/`TRACK_BAR_FIELD` в таблице
  отклоняются диагностикой SU107
- Новую группу командной панели не создавать - CommandBar на форме уже есть; её
  заполнение и скрытые команды - операциями из «Командные панели»
- `set_item` со скаляром, равным значению по умолчанию (например `titleHeight: 0`), убирает
  свойство из `.form` - это штатный способ отката точечной правки

### Паттерн: добавить элемент на форму

```text
1. inspect_form_layout(
     project  = "<Каталог.Имя>",
     form_fqn = "DataProcessor.prj_Схема.Form.ОсновнаяФорма",
     include_properties = true
   )

2. edt_validate_request(operation="mutate_form_model", payload={...}) → token

3. mutate_form_model(
     project          = "<Каталог.Имя>",
     form_fqn         = "DataProcessor.prj_Схема.Form.ОсновнаяФорма",
     operations       = [{op: "add_button", name: "prj_Экспорт", command_name: "...", parent_item_id: "..."}],
     validation_token = token
   )
```

### `apply_form_recipe` vs `mutate_form_model`

- `mutate_form_model` - точечные операции (добавить элемент, изменить свойство)
- `apply_form_recipe` - декларативный подход: описываем желаемое состояние (`attributes` + `layout`),
  инструмент сам определяет нужные операции (создать/найти/обновить).
  Удобен для составных изменений из нескольких шагов

`attributes[i].action` (case-insensitive): `add`/`create`/`new`, `update`/`set`/`patch`/`modify`,
`upsert`/`ensure`/`apply`/`merge`, `remove`/`delete`/`drop`.

### Формы правятся только MCP-инструментами

XML `Form.form` - внутренний формат BM API: ручной `Edit` ломает индексы и связи
(dataPath, привязки команд), даже когда diff выглядит безобидно. Порядок:
`inspect_form_layout` → `edt_validate_request` → `mutate_form_model` /
`apply_form_recipe`. `Module.bsl` формы правится обычным `Edit` - ограничение
касается только `.form`.

**Формы расширения - тоже через MCP** (изменение с 2026-08-04). Раньше BM-инструменты их не
резолвили (`METADATA_NOT_FOUND`) и приходилось править XML руками. Проверено на
`DataProcessor.prj_Ассистент.Form.Настройки`: `inspect_form_layout` читает дерево,
`edt_validate_request` выдаёт токен, `mutate_form_model` пишет точечно - правка `set_item`
добавила ровно одну строку в `.form`, обратная правка вернула файл к исходному состоянию
(`git diff` пуст, диагностик 0). Прямой XML остаётся аварийным вариантом: если инструмент вернул
`METADATA_NOT_FOUND` - сначала перепроверить FQN, и только потом править руками с `xmllint` +
`edt_extension_smoke` + `edt_diagnostics`, явно отметив это в ответе владельцу.

---

## Роли

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `inspect_role_rights` | Права роли по объектам (`Set`/`Unset`/`Provided`), RLS, флаги по умолчанию | R |
| `mutate_role_rights` | Изменение прав роли через модель прав EDT (RLS - отдельно) | **W** |

- `inspect_role_rights(role, project?, object_filter?)` - `role` принимает `prj_Печать` или
  `Role.prj_Печать`. **`object_filter` практически обязателен**: без него ответ по роли
  крупный проект - десятки тысяч символов и обрезается.
- `mutate_role_rights(project, role, operations[], validation_token)`; `op`: `set_right`,
  `set_config_right`, `set_flags`, `clear_object`. Право пишется по-русски или по-английски
  (`Read`/`Чтение`, `Update`/`Изменение`, `View`/`Просмотр`…), `value` - `set`/`allow` либо
  `unset`/`deny`. Зависимости прав (`Изменение` требует `Чтение`) достраиваются сами.
- `op="set_flags"` меняет флаги роли по умолчанию тремя булевыми параметрами операции:
  `set_for_new_objects` (права новым объектам), `set_for_attributes_by_default` (права
  реквизитам и табличным частям), `independent_rights_of_child_objects` (самостоятельные права
  подчинённых объектов). `op="clear_object"` снимает все права по одному `object_fqn`.

> Ограничение вывода: у дочерних объектов `objectFqn` не детализируется - реквизиты и табличные
> части показываются как FQN владельца (`Catalog.prj_Макеты` + `objectKind:
> TabularSectionAttribute`), понять из ответа, о каком именно реквизите речь, нельзя. Для точечной
> работы с правами реквизитов сверяться с `.mdo`-описанием роли.

---

## СКД

| Инструмент | Назначение |
| --- | --- |
| `dcs_manage` | Читать/создавать/обновлять схему компоновки данных |

**Команды (изменились):**

| Команда | Назначение |
| --- | --- |
| `get_summary` | Сводка по схеме компоновки |
| `list_nodes` | Список узлов: `dataset`, `parameter`, `calculated`, `variant` (фильтры, пагинация) |
| `create_schema` | Связать DCS-макет с владельцем |
| `upsert_dataset` | Создать/обновить набор данных (запрос) |
| `upsert_param` | Создать/обновить параметр |
| `upsert_field` | Создать/обновить вычисляемое поле |

**Обязательные параметры:** `command`, `project`, `owner_fqn` (например, `Report.prj_ОтчётПечати`).

> ВНИМАНИЕ: `owner_fqn` - это FQN владельца (`Report.X` / `Catalog.X`), **не** Template FQN.

**Параметры по командам:**

| Команда | Параметры |
| --- | --- |
| `list_nodes` | `node_kind` (`all`/`dataset`/`parameter`/`calculated`/`variant`), `name_contains`, `limit` (1..1000, по умолчанию 100), `offset` |
| `create_schema` | `template_name` - имя DCS-макета, `force_replace` - заменить привязку, если схема уже есть |
| `upsert_dataset` | `dataset_name`, `query`, `data_source`, `auto_fill_available_fields`, `use_query_group_if_possible` |
| `upsert_param` | `parameter_name`, `expression`, `available_as_field`, `value_list_allowed`, `deny_incomplete_values`, `use_restriction` |
| `upsert_field` | `expression`, `data_path`, `presentation_expression` |

`validation_token` обязателен для `create_schema` и всех `upsert_*`; read-only `get_summary`
и `list_nodes` обходятся без него.

### Порядок создания DCS

```text
1. add_metadata_child(child_kind="Template", template_type="dcs", ...) → создаём DCS-макет
2. dcs_manage(command="upsert_dataset", query="ВЫБРАТЬ ...", validation_token=...)
   → набор данных с непустым запросом (пустой query вешает редактор EDT)
3. dcs_manage(command="create_schema", validation_token=...)
   → связываем макет с владельцем
```

```text
# Прочитать сводку
dcs_manage(
  command   = "get_summary",
  project   = "<Каталог.Имя>",
  owner_fqn = "Report.prj_ОтчётПечати"
)

# Добавить параметр
edt_validate_request(operation="dcs_manage", payload={command:"upsert_param", ...}) → token
dcs_manage(
  command          = "upsert_param",
  project          = "<Каталог.Имя>",
  owner_fqn        = "Report.prj_ОтчётПечати",
  parameter_name   = "Период",
  expression       = "&Период",
  validation_token = token
)
```

---

## Расширения и внешние объекты

### Расширения конфигурации

| Инструмент | Команды |
| --- | --- |
| `extension_manage` | `list_projects`, `list_objects`, `create`, `adopt`, `set_state` |
| `edt_extension_smoke` | E2E smoke runtime расширений (create → list → adopt → set_property_state → cleanup) |

`set_state` - состояние свойства: `NONE`, `CHECKED`, `EXTENDED`, `NOTIFY`.
`create` принимает `purpose` (`ADD_ON`/`CUSTOMIZATION`/`PATCH`), `compatibility_mode`, `version`,
`configuration_name`, `project_path`.

**Два имени проекта.** `extension_project` - проект расширения (обязателен для `list_objects`,
`create`, `adopt`, `set_state`), `project` / `base_project` - проект базовой конфигурации, которому
принадлежит `source_object_fqn`. Для мутирующих команд `project` и `base_project`, если заданы оба,
**обязаны совпадать** - `project` служит областью валидации токена.

- `adopt` - `source_object_fqn` + `update_if_exists=true`, чтобы повторное заимствование обновляло
  уже заимствованный объект, а не падало
- `set_state` - `source_object_fqn` + `property_name` + `state`
- `list_objects` - фильтры `type_filter`, `name_contains`, пагинация `limit` (1..1000) / `offset`

`edt_extension_smoke(project, extension_project?, source_object_fqn?, property_name?, state?,
cleanup_created?)` - без необязательных параметров сам создаёт временный проект расширения,
подбирает объект и свойство, а `cleanup_created` (по умолчанию `true`) убирает созданное за собой.

### Внешние отчёты и обработки

| Инструмент | Команды |
| --- | --- |
| `external_manage` | `list_projects`, `list_objects`, `details`, `create_report`, `create_processing` |
| `edt_external_smoke` | E2E smoke runtime внешних объектов |

`external_manage(command, project, …)`: `project` - базовый EDT-проект, `external_project` -
проект внешнего объекта; `object_fqn` для `details` (полный FQN вида
`ExternalDataProcessor.МояОбработка`), `name` + `project_path` + `version` + `synonym` + `comment`
для `create_report` / `create_processing` (эти две команды требуют `validation_token`),
`type_filter` / `name_contains` / `limit` / `offset` для списков.

`edt_external_smoke(project, external_project?, kind?, name?, cleanup_created?)` - `kind` =
`report` (по умолчанию) или `processing`; без `external_project` создаёт временный проект и
удаляет его при `cleanup_created=true`.

> `edt_extension_smoke` и `edt_external_smoke` - для проверки инфраструктуры,
> не для обычной разработки.

---

## QA - тестирование

### YAxUnit (unit/integration на встроенном языке)

| Инструмент | Назначение |
| --- | --- |
| `author_yaxunit_tests` | Создать/обновить общий модуль с тестами, синхронизировать ИсполняемыеСценарии |
| `run_yaxunit_tests` | Запустить тесты, разобрать JUnit XML, вернуть сводку в Markdown |
| `debug_yaxunit_tests` | Запустить тесты в режиме отладки - для остановки на точках останова |

`run_yaxunit_tests(project_name, filters?, update_database?, keep_connected?, junit_xml_path?,
timeout_s?)` - отчёт кладётся в `.codepilot/runs/yaxunit/`.
`debug_yaxunit_tests(project_name, filters?, wait_for_debugger?, launch_config_name?)` -
связка с разделом «Отладка и профилирование».

> Если фреймворк YAxUnit в проекте не подключён - запуск заработает только после интеграции (см. [`yaxunit-bootstrap.md`](yaxunit-bootstrap.md)).

**Параметры:** `project`, плюс `feature` или `module_name` (одно из), `tests[]`, `replace_all?`,
`remove_tests[]?`, `default_data_setup?`, `subsystem_name?`, `subsystem_synonym?`,
`module_synonym?`, `module_comment?`, `diagnostics_max_items?`, `diagnostics_wait_ms?`.

Каждый тест: `name`, `arrange?`, `act?`, `assert?`, `data_setup?`, `description?`, `enabled?`.
Тесты обязаны использовать helper `ЮТДанные`.

```text
author_yaxunit_tests(
  project = "<Каталог.Имя>",
  feature = "Ядро",
  tests = [
    {
      name      = "ТестМетодаXxx",
      arrange   = "...",
      act       = "...",
      assert    = "ЮТест.ОжидаетЧто(...).Равно(...);",
      data_setup= "ЮТДанные.СоздатьЭлемент(...);"
    }
  ]
)
```

### Vanessa Automation (BDD / E2E сценарии)

| Инструмент | Шаг | Команды/Назначение |
| --- | --- | --- |
| `qa_inspect` | 0 | `explain_config`, `status`, `steps_search` |
| `qa_prepare_form_context` | 1 | Подготовить форму (создать default при необходимости) |
| `qa_plan_scenario` | 2 | Построить structured plan из цели - без ручного Gherkin |
| `qa_generate` | 3 | Команды: `init_config`, `migrate_config`, `compile_feature` |
| `qa_validate_feature` | 4 | Preflight feature по каталогу шагов Vanessa |
| `qa_run` | 5 | Запуск E2E |

`qa_run` ключевые опции: `features[]`, `scenarios[]`, `tags_include[]`, `tags_exclude[]`,
`unknown_steps_mode` (`off`/`warn`/`strict`), `dry_run`, `update_db`, `use_edt_runtime`,
`use_test_manager`, `timeout_s`, `clear_steps_cache`.

Остальные параметры `qa_run`: `config_path` (путь к `qa-config.json`), `project_name` - проект
для привязки к инфобазе, `use_project_infobase_for_clients` (по умолчанию `true` при
`use_edt_runtime` - подменяет пути тест-клиентов на инфобазу проекта), `platform_version`
(версия платформы для запуска через EDT runtime), `skip_status_check` - пропустить обязательный
`qa_inspect(command="status")` перед запуском (обычно оставлять `false`), `allow_unknown_steps` -
устаревший флаг совместимости, вместо него `unknown_steps_mode`.

`qa_plan_scenario` кроме `goal` принимает структурное описание сценария, чтобы не писать Gherkin
руками: `scenario_title`, `object_name` / `object_type`, `section_name` (раздел навигации),
`table_name`, `text_fields[{field, value}]`, `pick_fields[]`, `table_actions[{action, table,
field, value}]`, `recipe_id`, `tags[]`, `context`, а также `close_current_window` и
`close_test_client` - явные шаги закрытия окна и тест-клиента в конце сценария.

`qa_prepare_form_context(project, owner_fqn, usage, …)`: `form_name` - явное имя формы (иначе
вычисляется по `usage` и владельцу), `auto_create=true` - создать форму по умолчанию, если её нет,
`set_as_default`, `wait_ms`, плюс те же фильтры дерева, что у `inspect_form_layout`
(`include_properties`, `include_titles`, `include_invisible`, `max_depth`, `max_items`).
`qa_validate_feature(feature_file, config_path?, unknown_steps_mode?)` - `config_path` по умолчанию
`tests/qa/qa-config.json`.

```text
qa_inspect(command="status")
qa_prepare_form_context(
  project   = "<Каталог.Имя>",
  owner_fqn = "DataProcessor.prj_Схема",
  usage     = "OBJECT"
)
qa_plan_scenario(
  goal         = "Пользователь создаёт новую схему печати",
  project_name = "<Каталог.Имя>",
  object_type  = "DataProcessor",
  object_name  = "prj_Схема"
)
qa_generate(command = "compile_feature", ...)
qa_validate_feature(feature_file = "prj_Схема.feature", unknown_steps_mode = "warn")
qa_run(
  features         = ["prj_Схема.feature"],
  use_edt_runtime  = true,
  unknown_steps_mode = "warn"
)
```

---

## Отладка и профилирование

Полноценный отладчик 1С через MCP: точки останова, пошаговое исполнение, чтение переменных и
вычисление выражений в текущем кадре стека. Все инструменты адресуют модуль парой
`projectName` + `filePath` (путь относительно `src/`).

| Инструмент | Назначение |
| --- | --- |
| `debug_status` | Состояние отладки: запуски, цели, число точек останова |
| `set_breakpoint` | Точка останова: `filePath` + `line`, опционально `condition`, `enabled` |
| `list_breakpoints` | Список точек останова воркспейса или проекта |
| `remove_breakpoint` | Удалить по `breakpointId` или по `filePath` + `line` |
| `wait_for_break` | Ждать остановки потока (`timeoutMs`) |
| `get_variables` | Переменные текущего кадра (`threadId`, `frameId` - опционально) |
| `evaluate_expression` | Вычислить выражение в текущем кадре |
| `step` | Шаг `into` / `over` / `out` |
| `resume` | Продолжить поток или цель |
| `start_profiling` | Включить/выключить профилирование активной цели отладки |
| `get_profiling_results` | Результаты: модули, строки, вызовы, тайминги, покрытие |

### Петля отладки

```text
1. set_breakpoint(projectName="<Каталог.Имя>",
                  filePath="CommonModules/prj_АдаптерOpenAIКлиентСервер/Module.bsl",
                  line=120, condition="Не ПустаяСтрока(ТекстОтвета)")
2. (запустить сценарий в приложении - вручную или debug_yaxunit_tests)
3. wait_for_break(projectName="...", timeoutMs=60000)
4. get_variables(projectName="...")            → состояние кадра
   evaluate_expression(projectName="...", expression="ОтветСервера.КодСостояния")
5. step(projectName="...", kind="over") / resume(projectName="...")
6. remove_breakpoint(projectName="...", filePath="...", line=120)
```

`get_profiling_results(moduleFilter?, minFrequency?, maxLinesPerModule?)` - снимать после того,
как код отработал под включённым профилированием; `maxLinesPerModule` по умолчанию 200, максимум
1000. `start_profiling(applicationId?)` - идентификатор нужен, только если активных целей отладки
несколько; при одной цели параметр опускается.

> Отладчик - прямой способ увидеть фактический запрос и ответ там, где логирование пришлось бы
> дописывать (диагностика ассистента, HTTP-сервисы).

---

## Диагностика

| Инструмент | Назначение |
| --- | --- |
| `edt_diagnostics` | EDT диагностика и runtime-команды (CLI/headless) |
| `get_diagnostics` | Live-диагностики из UI workbench (по проекту, файлу или активному редактору) |

### `edt_diagnostics.command` (переименовано)

| Команда | Назначение |
| --- | --- |
| `metadata_smoke` | Headless-проверка метаданных (раньше `smoke`); на проекте внешнего отчёта/обработки мутирующая часть пропускается - `SKIPPED_EXTERNAL_PROJECT` (с `0923-0718`) |
| `trace_export` | Диагностика проблем экспорта |
| `analyze_error` | Разбор конкретного error payload (раньше `parse_errors`) |
| `update_infobase` | Обновить инфобазу |
| `launch_app` | Запустить приложение (раньше `run_app`) |

Имя проекта передаётся двумя взаимозаменяемыми параметрами: `project` - для `metadata_smoke`
и `trace_export`, `project_name` - для `update_infobase` и `launch_app`; каждый принимается как
алиас другого. `analyze_error` требует `tool_result` - объект с ответом или ошибкой инструмента,
который нужно разобрать.

**`update_infobase`** вызывается с `project_name="<ХостПроект>"` - имя
**хост-проекта** в воркспейсе EDT, не расширения (ИБ ассоциирована с хостом; с именем
расширения - `INFOBASE_ASSOCIATION_NOT_FOUND`). Это исключение из общего правила
«имя проекта = <Каталог.Имя>». На файловой ИБ `async=true`
игнорируется: ответ синхронный, `status: "updated"`, без `job_id` -
`update_infobase_status` после него не нужен.

### `get_diagnostics`

| Параметр | Назначение |
| --- | --- |
| `scope` | `project` / `file` / `module` / `active_editor` / `all` |
| `project_name` | для `scope=project` |
| `path` | workspace-относительный путь для `scope=file`/`module` |
| `file` | алиас `path` |
| `object` | сузить `scope=project` до одного объекта или модуля по имени/пути |
| `severity` | `error` / `warning` / `info` (по умолчанию `info`) |
| `max_items` | 0 = без ограничений (значение по умолчанию) |
| `wait_ms` | ожидание пересчёта (0-2000 мс) |
| `include_runtime_markers` | подключать маркеры EDT marker manager (по умолчанию `true`) |

```text
# Live-диагностика проекта
get_diagnostics(scope="project", project_name="<Каталог.Имя>", severity="warning")

# Только по одному объекту - чтобы он не утонул в обрезанном ответе по всему проекту
get_diagnostics(scope="project", project_name="<Каталог.Имя>",
                object="prj_Ядро", severity="error")

# Live-диагностика конкретного файла
get_diagnostics(scope="file", path="src/CommonModules/prj_Ядро/Module.bsl", wait_ms=500)

# Headless smoke (если UI недоступен)
edt_diagnostics(command="metadata_smoke")
```

`object` появился к 2026-08-20 и решает ровно нашу проблему: в проекте расширения полный ответ
`scope=project` обрезается по объёму, и замечания по нужному объекту в него могут не попасть.
Проверять «чисто ли после правки» дешевле точечно, а не полным списком.

Видит и ошибки строгой типизации (`SU24`, `SU70`, `SU83`), и предупреждения (`SU30`, `SU64`),
которых нет в сводке `edt_get_problem_summary`: та отдаёт только маркеры платформенных проверок.

**Проект передаётся параметром `project_name`**, а не `projectName`, как у BSL-инструментов.
Сервер незнакомые параметры молча отбрасывает, и вызов с `projectName` уходит в проект по
умолчанию - в воркспейсе с хостом это хост-проект: ответ «0 ошибок» приходит по чужому проекту
(проверено 2026-09-30 сырым вызовом). Смотреть на заголовок ответа - `Диагностики: /<проект>`.
`object` принимает и имя объекта, и имя формы (`ФормаЭлемента`).

**Маркеры отстают на один запрос.** Первый вызов после правки файла отдаёт состояние **до**
неё - и «чисто» на сломанном модуле, и старую ошибку на починенном. Запрашивать диагностику
дважды подряд и верить второму ответу; иначе правка либо кажется сломавшей то, что цело, либо
считается принятой, когда ошибка на месте.

> Инструмент пропадал из сборки `1.3.9.20260820-1223` и вернулся 2026-09-05. Серверные skills
> `review`, `validator` и `architect` в той сборке продолжали объявлять его в своём
> `allowed-tools` - верить составу `tools/list` и `discover_tools`, а не спискам внутри skill'ов.

### `edt_get_problem_summary`

Сводка проблем валидации проекта: числа по уровням плюс список. **На вопрос «чисто ли после
правки» не отвечает:** 2026-09-30 она вернула `total_problems: 0` по расширению, пока
`get_diagnostics` показывал по одной обработке 33 ошибки SU103 и 24 предупреждения - проверки
EDT (SU*) и строгую типизацию сводка не видит. Проверка после правки - `get_diagnostics`,
сводка - только грубый сигнал «проект вообще собирается».

---

## Runtime, инфобаза и веб-клиент

| Инструмент | Назначение |
| --- | --- |
| `get_standalone_server_status` | Состояние автономного сервера EDT: процессы, порты, блокировки, последние ошибки |
| `resolve_web_client_url` | URL веб-клиента (и конфигуратора) инфобазы проекта - для проверки UI в браузере |
| `get_infobase_credentials` | Логин ИБ из хранилища EDT и сведения о способах аутентификации. **С 2026-09-20 не вызывается вовсе** - см. ниже |
| `connect_infobase` | Подключить ИБ к проекту: `kind` = `file`/`standalone`, `database_path`, `set_primary`, `force`, `runtime_version`, `server_port`, `login`/`password` |
| `get_1c_processes` | Процессы 1С/EDT: PID, родитель, командная строка; `include_ports`, `include_open_files` - детали по портам и открытым файлам |
| `get_infobase_locks` | Блокировки файловой ИБ и удерживающие их процессы; `path_or_connection` обязателен, `include_evidence` добавляет подтверждающие данные |
| `tail_edt_logs` | Хвост логов EDT и CodePilot с фильтрами `project`, `op_id`, `pid`, `infobase`, `errors_only`, `since`, `max_lines` |
| `update_infobase_status` | Статус фонового обновления ИБ по `job_id` |

### `get_infobase_credentials` - сначала без пароля, теперь совсем закрыт

Две ступени одного движения:

- **к 2026-08-20** инструмент перестал отдавать сохранённый пароль - остались имя пользователя
  и метаданные доступности аутентификации, ключи и секреты переехали в Eclipse Secure Storage;
- **к 2026-09-20** он закрыт политикой `exposedTools` целиком: в `tools/list` его нет, в списке
  категории `diagnostics` он числится, но прямой вызов отвечает `Tool is not exposed`.

Практический вывод не изменился, только стал жёстче: автономный вход в веб-клиент через MCP
невозможен - логин и пароль даёт владелец, либо вход идёт под ОС-аутентификацией.

Порядок проверки изменения в живом веб-клиенте:

```text
edt_diagnostics(command="update_infobase", project_name="<ХостПроект>")   # имя ХОСТ-проекта
resolve_web_client_url(projectName="<Каталог.Имя>")
→ дальше браузерный MCP: вход под ОС-аутентификацией или логин с паролем от владельца;
  готовые сценарии - skills verify-web-client / web-e2e-qa
```

`connect_infobase` принимает `login` и `password` при подключении ИБ (пустой логин = ОС-аутентификация);
пароль в ответе не отражается. `force=true` нужен, чтобы заменить уже назначенную основную ИБ
при `set_primary=true`.

На 2026-09-20 автономный сервер по-прежнему не поднят (`get_standalone_server_status` →
`servers: []`), отладка неактивна (`debug_status` → `state: inactive`) - инструменты отвечают,
окружение просто не запущено.

---

## Workspace и Git

| Инструмент | Назначение |
| --- | --- |
| `git_inspect` | Read-only: `status`, `branch_list`, `remote_list`, `log`, `diff_summary` |
| `git_mutate` | Разрешённые мутации (см. ниже) |
| `workspace_import_project` | Импортировать существующий локальный EDT-проект в workspace |
| `git_clone_and_import_project` | Клонировать репозиторий и сразу импортировать проект |
| `import_project_from_infobase` | Создать EDT-проект из связанной инфобазы (сначала `dry_run`) |
| `workspace_copy_transform` | Копия текстового файла с заменами (plain + regex), `dry_run`, обновление воркспейса |
| `workspace_copy_transform_batch` | То же пакетом: общие замены + список `operations` |
| `migrate_to_extension_native` | Dry-run план переноса объектов базы в расширение; удаление источника не делает |

### `workspace_copy_transform` - перенос модуля с заменами

Целевой инструмент для копий BSL-модулей: копирует файл, применяя `replacements`
(точные строки) и `regex_replacements` (синтаксис Java Pattern), с `dry_run`, `overwrite`,
`create_dirs` и `refresh_workspace`. Ложится на наши паттерны сборки - копии `prj_Ядро` в
`Templates/` у `prj_Исполнитель*` и инлайн `prj_СхемаКлиентСервер` в `prj_Схема*`.
Перед записью всегда сначала `dry_run=true`.

**Он же - способ заставить EDT перечитать файл, изменённый мимо MCP** (правкой через
Bash или скриптом): копия «туда-обратно» с `refresh_workspace=true` обновляет модель.
Без неё `get_diagnostics` отдаёт маркеры по прежнему содержимому - и это видно по тому,
что позиции ошибок не сдвигаются после правок выше по файлу. `scope=file` в таком состоянии
отдаёт пустой список - это «не считал», а не «чисто». Точечная правка через MCP `edit_file`
рабочую копию обновляет (`bsl_list_methods` уже видит новую версию), но маркеры не
пересчитывает - синхронизация нужна и после неё. Копия «туда-обратно» дешевле `write_file`:
содержимое модуля не проходит через контекст, и значимые символы (en-dash в ключах платформы)
не перевираются.

Промежуточный файл класть **не с расширением `.bsl`**: EDT подхватит его как модуль вне
структуры проекта и завалит сводку ошибками вида «Переменная не определена [Сервер]»,
причём маркеры переживут удаление файла. Безопасно - `sync-bridge.txt` в корне проекта.
Проверять результат - `get_diagnostics` с `object`, дважды подряд (маркеры отстают на запрос);
для формы - ещё и `inspect_form_layout`, совпала ли модель с файлом.

**На Windows залипание не воспроизводится** (2026-10-04, плагин `1003-0831`). EDT включает
автообновление воркспейса по умолчанию (`org.eclipse.core.resources/refresh.enabled=true` в
`plugin_customization.ini` продукта), и правка мимо MCP видна модели сразу, без всякой
синхронизации:

- процедура с ошибкой, дописанная в конец модуля через Bash, - маркер в `get_diagnostics`;
- две строки, вставленные выше по файлу обычным Edit, - позиция ошибки сдвинулась на две строки;
- заголовок формы, изменённый в XML `.form` через `sed`, - новый заголовок в
  `inspect_form_layout`; после возврата файла - снова прежний.

Залипание наблюдалось 2026-09-16 (BSL, этот раздел), 2026-09-27 и 2026-09-30 (формы, раздел
«Формы»); сверка 2026-09-30 точно шла на macOS. Почему там иначе, не выяснено (возможно, на macOS автообновление работает
опросом, а не событиями файловой системы). Пока не выяснено - на macOS синхронизировать
по-прежнему, на Windows достаточно проверить результат.

**Обновление сразу после правки мимо EDT увозит не всё - лечится повтором, а не полной
загрузкой.** 2026-10-08 (Windows) семь модулей форм правились скриптом мимо EDT,
`Configuration.mdo` (версия) - через `sed`. Обновление базы увезло только версию, модули форм
доехали после полной загрузки, и оттуда вывели правило «после правок мимо EDT - полная
загрузка». Вывод неверный. EDT грузит в базу то, что успела заметить к моменту вызова, а файл,
записанный мимо неё, замечает с задержкой. Грузить по изменениям или целиком, EDT решает сама:
2026-10-10 после перезапуска она догрузила расширение по изменениям («Загрузка 6 объектов»), а
тестовое расширение - целиком («Загрузка конфигурации в информационную базу», без числа
объектов). Полная загрузка большой конфигурации - час и больше, как средство она не нужна.

Опыт 2026-10-10 (macOS): скрипт дописал строку в два модуля форм и общий модуль,
`update_infobase` ушёл следом. В логе - «Загрузка 4 объектов» через 2 с после правки, но это
были правки, замеченные раньше; трёх свежих в базе нет. Тот же `update_infobase` через 45 с -
«Загрузка 3 объектов», все три в базе. Ни число N, ни время строки загрузки правку не
подтверждают.

После правок мимо EDT порядок тот же, что при прогоне тестов в рабочей базе
([`yaxunit-bootstrap.md`](yaxunit-bootstrap.md) §6.1): пауза (полминуты) → `update_infobase` →
строка «Загрузка N объектов» после своего `op_id`; нет строки - пауза и повтор. Сомнение, всё ли
доехало, снимает ещё один обычный `update_infobase`: загрузил что-то - предыдущий был неполным,
строки загрузки нет - база совпадает с тем, что видит EDT. На гейте проверять поведение: версия
в базе ничего не доказывает, `Configuration.mdo` мог доехать раньше модулей.

**Что лежит в базе, а не в модели**, показывает выгрузка объектов из базы. Живую файловую
базу держит агент конфигуратора EDT, и `ibcmd config export` получает «Ошибка блокировки
информационной базы для конфигурирования», поэтому выгружать с копии файла базы (на APFS
`cp -c` - мгновенный клон, оригинал не трогается):

```bash
cp -c "<каталог базы>/1Cv8.1CD" "$tmp/ib/1Cv8.1CD"
ibcmd config export objects --db-path="$tmp/ib" --user=... --password=... \
  --extension=<ИмяРасширения> -o "$tmp/exp" \
  CommonModule.prj_Модуль DataProcessor.prj_Обработка.Form.Форма
```

Модуль формы ложится в `Forms/<Форма>/Ext/Form/Module.bsl`, модуль объекта - в
`<Объект>/Ext/ObjectModule.bsl`; сверять с деревом без учёта BOM.

**Штатная замена копии «туда-обратно»** с `1003-0831` - `workspace_import_project(path=<каталог
проекта>, open=false, refresh=true)`: для открытого проекта это `refreshLocal(DEPTH_INFINITE)`,
то же, что F5 в EDT (подробнее - «Импорт проектов»). Снимает ли он залипание на macOS, не
проверено: на Windows лечить нечего. До такой проверки рабочим способом остаётся копия.

### `migrate_to_extension_native`

`migrate_to_extension_native(source_project, extension_project, source_fqns[], mode)` -
`mode="dry_run"` выдаёт план клонирования объектов (`Catalog.X`, `Role.X`, `Bot.X`) из базовой
конфигурации в расширение; `apply` требует `validation_token` и делается только после разбора плана.

### Импорт проектов

- `workspace_import_project(path, open?, refresh?)` - каталог уже должен содержать `.project`.
  Проект с тем же именем уже есть в воркспейсе - не создаётся заново: закрытый открывается
  (`open`, по умолчанию `true`), затем `refreshLocal(DEPTH_INFINITE)` (`refresh`, по умолчанию
  `true`). Ответ на открытом проекте - `"created": false, "opened": false, "refreshed": true`
  (проверено 2026-10-04). До `1003-0831` вызов отклонял хост - «Политика изменяющих вызовов»
- `git_clone_and_import_project(remote_url, repo_path, branch?, project_subpath?, open?, refresh?)` -
  `project_subpath` указывает подкаталог с `.project` внутри склонированного репозитория
- `import_project_from_infobase(source_project_name, target_project_name, …)` - экспорт
  конфигурации из ИБ, связанной с исходным проектом, в новый EDT-проект: `project_path`
  (обязан заканчиваться на `target_project_name`), `version`, `base_project_name`,
  `start_server` (по умолчанию `true`), `cluster_port` (1541), `cluster_registry_directory`,
  `publication_path`, `diagnostics_wait_ms` / `diagnostics_max_items`. Начинать с `dry_run=true`:
  он проверяет разрешение runtime и ИБ и показывает пути, ничего не экспортируя

### Git

`git_inspect.operation`: `status`, `branch_list`, `remote_list`, `log` (`limit`),
`diff_summary` (`base_ref` + `head_ref`).

`git_mutate.operation`: `init`, `create`, `create_repo`, `clone`, `remote_add`, `remote_set_url`,
`fetch`, `pull`, `push`, `checkout`, `create_branch`, `add`, `commit`. Параметры по операциям:
`remote_name` (по умолчанию `origin`) и `remote_url` - для `clone`/`remote_add`/`remote_set_url`,
`branch` - для `checkout`/`create_branch`, `start_point` и `checkout=true` - для `create_branch`,
`initial_branch` - для `init`, `set_upstream` - для `push`, `paths[]` - для `add`,
`message` - для `commit`.

> Для git-операций в EDT-проекте предпочтительно передавать `project_name`, а не `repo_path` -
> инструмент сам определит нужный путь. `repo_path` обязателен только для `init`/`create`/`clone`.
>
> Рекомендуется вести git обычным `Bash`-инструментом: коммиты по нашему формату, состав правок
> и `push` - решение владельца (CLAUDE.md). `git_mutate` - запасной путь, когда репозиторий
> находится внутри воркспейса EDT, но вне рабочего каталога.

---

## Вспомогательные инструменты

| Инструмент | Назначение |
| --- | --- |
| `read_file` | Прочитать файл целиком или диапазон `start_line`-`end_line` |
| `write_file` | Полная перезапись существующего файла (`overwrite=true`) |
| `edit_file` | Точечное редактирование: `old_text`+`new_text`, SEARCH/REPLACE-блоки или полная замена |
| `list_files` | Обзор файлов и папок workspace (`pattern?`, `recursive?`) |
| `glob` | Поиск файлов по паттерну (`max_results` ≤ 500, `include_hidden`) - **предпочитать стандартный Glob** |
| `grep` | Поиск по содержимому - стандартный Grep предпочтительнее, **кроме поиска сразу по хосту и расширению** |
| `discover_tools` | Раскрыть инструменты категории (`bsl`/`metadata`/`forms`/`extensions`/`dcs`/`qa`/`diagnostics`/`workspace`) |
| `skill` | Загрузить специализированный workflow (без аргумента - список skills) |
| `task` | Запустить подагента; `profile`: `auto`/`explore`/`plan`/`init`/`build`/`code`/`metadata`/`qa`/`dcs`/`extension`/`recovery`/`orchestrator` |
| `delegate_to_agent` | Делегировать задачу профильному агенту; `agentType`: `auto`/`init`/`code`/`metadata`/`qa`/`dcs`/`extension`/`recovery`/`plan`/`explore`/`orchestrator` |
| `remember_fact` | Сохранить факт в долгосрочную память сервера; `category`: `FACT`/`ARCHITECTURE`/`DECISION`/`PATTERN`/`BUG`, `domain` - подсистема |
| `inspect_platform_reference` | Сигнатуры типов встроенного языка платформы (без текстов справки - см. «Метаданные») |

### Контракт файловых инструментов

`edit_file(path, …)` принимает три взаимоисключающие формы правки:

| Форма | Когда |
| --- | --- |
| `old_text` + `new_text` | одна точечная замена |
| `edits` | несколько точных правок за вызов (payload из SEARCH/REPLACE-блоков) |
| `content` | полная замена содержимого; игнорируется, если задан `old_text`/`new_text` или `edits` |

`create` объявлен устаревшим - остался только для создания `Code.md` в корне проекта.
`allow_metadata_descriptor_edit=true` - аварийный override для прямой правки `.mdo`.

`write_file(path, content, overwrite=true)` перезаписывает существующие файлы, а **создать**
новый может только для `Code.md` в корне проекта и документации (`*.md`, `*.txt`).
Чтобы записать пустоту поверх непустого файла, нужен `allow_empty=true`.

Оба инструмента не пишут `.mdo`, `.form`, `.mxl` и артефакты СКД - для них есть семантические
инструменты (`update_metadata`, `mutate_form_model`, `render_template`, `dcs_manage`).

### Поиск по хосту и расширению одним вызовом

```text
grep(
  pattern            = "ОбщегоНазначения.СообщитьПользователю",
  project            = "<ХостПроект>",      # хост
  include_extensions = true,                # + <Каталог.Имя> (по умолчанию)
  file_pattern       = "*.bsl",
  context_lines      = 2
)
```

Ещё параметры: `path` (workspace-относительный подкаталог), `regex`, `case_sensitive`.

### Почему инструментов бывает видно меньше

Сервер сам прячет часть инструментов в зависимости от состояния воркспейса (`ToolContextGate`,
результат кэшируется на 5 минут):

- нет ни одного **открытого** проекта → скрыты все EDT-инструменты (метаданные, BSL, формы,
  диагностика, импорт), а также DCS/расширения/внешние объекты/QA
- в проектах нет ни одной схемы компоновки → скрыт `dcs_manage`
- нет QA-конфигурации → скрыты `qa_*`, `*_yaxunit_tests` (кроме инициализации)

Поэтому «инструмент пропал» - обычно не сбой сервера, а закрытый в EDT проект.
После открытия проекта поверхность возвращается в течение ~5 минут (или сразу после
переподключения клиента).

Точечно закрыть инструмент можно самим сервером: в `-Dcodepilot.mcp.host.policy.exposedTools`
поддерживается запрет через минус - `*,-delete_metadata` открывает всё, кроме перечисленного.
Так закрыт `get_infobase_credentials`: в `tools/list` его нет никогда, а с 2026-09-20 не помогает
и `discover_tools(category="diagnostics")` - инструмент в списке категории виден, но вызов
отвечает `Tool is not exposed`. Отсюда правило: «виден в `discover_tools`» не равно «вызывается».

### Политика изменяющих вызовов

Настройки хоста лежат в воркспейсе EDT:
`<воркспейс>/.metadata/.plugins/org.eclipse.core.runtime/.settings/com.codepilot1c.core.prefs`.
Ключи: `mcp.host.http.port` (порт HTTP), `mcp.host.policy.defaultMutationDecision` (`ALLOW` -
изменяющие вызовы разрешены), `mcp.host.policy.exposedTools` (`*` - все инструменты). Ниже
описано поведение с `defaultMutationDecision=ALLOW`, `exposedTools=*` и без профиля сессии.

С `1003-0831` (upstream [#95](https://github.com/ondysss/codepilot1c-edt/issues/95)) хост
считает подтверждение полученным, если встроенный изменяющий инструмент уже разрешён
`defaultMutationDecision=ALLOW` или явным правилом `allow` профиля. Правила профиля
`ASK` / `DENY` по-прежнему отказывают, динамическим (не встроенным) изменяющим инструментам
токен нужен как раньше.

- **Инструменты без токена в контракте** (`workspace_import_project`, `write_file`,
  `git_mutate`, `connect_infobase`, `import_project_from_infobase`) до `1003-0831` отклонялись
  при любых настройках: `Инструмент запрещен политикой профиля: <имя> (profile=,
  reason_code=confirmation_unavailable_tool_policy, layer=tool)` (проверено на `0915-1537`).
  Теперь вызов доходит до самого инструмента. `edit_file` под этот запрет не попадал и раньше
- **Инструменты с токеном в контракте** (`update_metadata`, `mutate_form_model` и т.п.) по коду
  хоста проверяют и гасят токен сами - `edt_validate_request` перед мутацией обязателен, как и был
- **`git_mutate` (включая `push`) вызывается без подтверждения.** Запрет на `push` без просьбы
  владельца держится только на правилах CLAUDE.md; git ведём Bash. Если понадобится запрет
  на стороне сервера - `exposedTools=*,-git_mutate`

### Проверка живости сервера

Сервер - HTTP MCP Host на `http://127.0.0.1:8765/mcp`. Ответ на `initialize` несёт блок
`experimental.codepilot` - самый быстрый способ понять, с чем именно разговариваем:

```json
{"contractVersion": 1, "pluginVersion": "1.3.9.20261003-0831", "edtVersion": "1.35.3",
 "mode": "gui", "workspace": "<путь к EDT-воркспейсу>",
 "readiness": {"services": "ready",
               "projects": [{"name": "<ХостПроект>", "state": "ready"},
                            {"name": "<Каталог.Имя>", "state": "ready"}],
               "status": "ready", "ready": true}}
```

Практика:

- **Инструменты не появились в сессии** - почти всегда потому, что EDT (или плагин) поднялся
  позже клиента: список инструментов забирается при подключении. Лечится перезапуском сессии
  клиента, а не сервера. Проверить, что сервер при этом жив, можно сырым `initialize`
  (`GET` на `/mcp` отвечает `405` - это нормально, эндпоинт принимает только `POST`).
  Для `tools/list` одного `POST` мало: сервер отвечает `{"error":"session_required"}`, пока
  не передан `Mcp-Session-Id` из заголовков ответа на `initialize`, а сам ответ приходит
  в формате SSE (строка `data: {...}`), а не голым JSON
- **`readiness.projects` заполняется не всегда.** 2026-09-20 в нём пришли оба проекта со
  `state: ready`, а 2026-08-20 список был пуст при `status: ready`, хотя
  `get_diagnostics(scope="project", …)` по расширению отвечал штатно. Пустой список закрытых
  проектов не означает - судить об открытых проектах по этому полю нельзя
- `codepilot://state/session` (см. ниже) отличает «сервер занят» (`status: BUSY`) от
  «сервер не отвечает»
- **После обновления плагина сверять `pluginVersion`**, а не дату jar в пуле. 2026-09-30
  установка `0925-1004` дописала новую сборку в `~/.p2/pool` и в профиль p2, но не в
  `bundles.info` - EDT дважды перезапускался и оба раза поднимал `0915-1537`. След в
  `.metadata/.log` воркспейса: предупреждение p2 `Не удалось найти настроенный КомплектИнфо
  для: [R]com.codepilot1c.core <старая версия>` в момент установки. Лечение: сохранить копию
  `bundles.info` (`<EDT>/1cedt.app/Contents/Eclipse/configuration/org.eclipse.equinox.simpleconfigurator/`),
  заменить в двух строках `com.codepilot1c.core` и `com.codepilot1c.ui` версию и имя jar на
  новые (jar уже лежат в пуле), перезапустить EDT и проверить `pluginVersion`
- **На Windows плагин стоит не в `~/.p2/pool`**, а в пользовательской области конфигурации
  Eclipse: `%USERPROFILE%\.eclipse\org.eclipse.platform_4.30.0_<хэш>_win32_win32_x86_64\plugins`
  (рядом лежат старые сборки в соседних каталогах с другим хэшем). 2026-10-04 обновление встало
  с первого рестарта, `pluginVersion` сразу показал `1003-0831`
- После рестарта EDT клиент теряет сервер (`ECONNREFUSED`) и через некоторое время
  переподключается сам; до этого инструменты можно звать сырым `tools/call` в сессии,
  открытой через `initialize`

### MCP-ресурсы сервера

Кроме инструментов хост отдаёт ресурсы (`ListMcpResourcesTool` / `ReadMcpResourceTool`,
сервер `codepilot1c`):

| URI | Что внутри |
| --- | --- |
| `codepilot://state/diagnostics` | маркеры воркспейса (ошибки/предупреждения) в JSON |
| `codepilot://state/session` | состояние плагина: `status`, `message`, `sessionId` |
| `codepilot://workspace/tree` | верхнеуровневые записи воркспейса |
| `codepilot://workspace/file?path=<путь>` | чтение файла воркспейса |

Практика: `state/diagnostics` - дешёвая проверка «в воркспейсе чисто?» без запуска
`edt_diagnostics`; `state/session` отличает «сервер занят» от «сервер не отвечает».
Для чтения файлов проекта штатные `Read`/`Grep` удобнее - ресурс нужен, только если
интересует файл вне репозитория, но внутри воркспейса EDT.

---

## Skills сервера

`skill(list=true)` - список, `skill(name="...")` - загрузить инструкцию.

| Skill | Назначение |
| --- | --- |
| `review` | Ревью BSL/метаданных: баги, регрессии, соответствие спеке, качество кода |
| `refactor` | Рефакторинг с сохранением поведения и минимальным диффом |
| `architect` | Разбор задачи на атомарные шаги с EDT-инструментами |
| `validator` | Валидация метаданных, форм и модулей через диагностику EDT |
| `verify-web-client` | Проверка одного изменения в живом веб-клиенте: обновить ИБ → URL → браузер → PASS/WARN/FAIL |
| `web-e2e-qa` | Полный E2E + UX/UI аудит новых объектов в браузере (скриншоты, консоль, сеть) |

**Skill `explain` больше не существует** (проверено 2026-08-20): `skill(name="explain")` отвечает
`Skill not found or unavailable for current provider selection`, хотя описание самого инструмента
`skill` его всё ещё рекомендует. Формулировка ответа намекает, что набор skills зависит от
выбранного в плагине LLM-провайдера, - при расхождении верить `skill(list=true)`, а не описанию.

Каждый skill объявляет свой `allowed-tools`, то есть заодно служит готовым списком инструментов
под задачу (например, `review` - read-only набор: `read_file`, `bsl_*`, `edt_find_references`,
`inspect_platform_reference`, `git_inspect`).

Проектные правила (CLAUDE.md, `docs/bsl-*.md`, SDD) имеют приоритет над инструкциями skill'ов
сервера: они написаны без знания наших ограничений по зависимостям и порядку работы.

---

## GSD - фазовая машина сервера

Восемь инструментов (`gsd_create_plan`, `gsd_get_state`, `gsd_update_task`, `gsd_transition`,
`gsd_record_decision`, `gsd_record_evidence`, `gsd_record_shipment`,
`gsd_record_verification_outcome`) ведут состояние работы по проекту: фазы
`DISCOVERY → PLANNING → EXECUTING → VERIFYING → SHIPPING → CLOSED` (откат из `VERIFYING`
или `SHIPPING` - с обязательной причиной), задачи с `execution_kind`
(`READ_ONLY`/`FILE_MUTATION`/`EDT_MUTATION`/`GIT_MUTATION`) и зависимостями, волны, решения с
обоснованием и альтернативами, доказательства с происхождением
(`OBSERVED`/`TESTED`/`USER_ACCEPTED`/`INFERRED`). Все мутации - с `expected_revision`
(оптимистичная блокировка). Добавленные к 2026-09-20 `gsd_record_verification_outcome`
(`PASSED`/`FAILED` по одному критерию приёмки) и `gsd_record_shipment`
(`IN_PROGRESS`/`COMPLETED`/`FAILED`, у `COMPLETED` обязателен `completed_at`) закрывают
фазу `SHIPPING`.

**Не применяется.** Тот же контур закрыт методологией SDD: `specs/<prefix>-<N>/spec.md`
(контракт) + `plan.md` (этапы, решения), и это состояние лежит в git, а не в служебном хранилище
сервера. Вопрос о пробном применении GSD на одной задаче остаётся открытым.

---

## Типовые сценарии

### Сценарий A: изучить незнакомый модуль

```text
bsl_module_context(projectName="...", filePath="CommonModules/prj_Ядро/Module.bsl")
bsl_list_methods(   projectName="...", filePath="CommonModules/prj_Ядро/Module.bsl")
bsl_module_exports( projectName="...", filePath="CommonModules/prj_Ядро/Module.bsl")
bsl_get_method_body(projectName="...", filePath="CommonModules/prj_Ядро/Module.bsl", name="НужныйМетод")
```

### Сценарий B: добавить новый метод в существующий модуль

```text
1. bsl_get_method_body(...)         → читаем соседние методы для контекста
2. edt_validate_request(operation="ensure_module_artifact", payload={object_fqn:"..."}) → token
3. ensure_module_artifact(..., validation_token=token) → путь
4. edit_file(...)                   → вносим изменения
5. get_diagnostics(scope="project", project_name="...", object="...") → дважды, верить второму
```

### Сценарий C: создать объект метаданных с формой и тестом

```text
1. edt_validate_request(operation="create_metadata",      payload={kind:"Catalog", name:"prj_Новый"})
2. create_metadata(kind="Catalog", name="prj_Новый", validation_token=...)
3. edt_validate_request(operation="create_form",          payload={owner_fqn:"Catalog.prj_Новый", name:"ФормаЭлемента"})
4. create_form(owner_fqn="Catalog.prj_Новый", name="ФормаЭлемента", usage="OBJECT", set_as_default=true, validation_token=...)
5. inspect_form_layout(form_fqn="Catalog.prj_Новый.Form.ФормаЭлемента", include_properties=true)
6. author_yaxunit_tests(project="...", feature="prj_Новый", tests=[...])
7. get_diagnostics(scope="project", project_name="...", object="prj_Новый")   # дважды
```

### Сценарий D: рефакторинг - найти все использования объекта метаданных

```text
edt_find_references(projectName="...", objectFqn="Catalog.prj_УстаревшийСправочник")
→ список мест → для каждого read_file/edit_file
```

> Для вызовов конкретного метода BSL - `edt_get_method_call_hierarchy`
> (`direction="callers"`), а не `edt_find_references`: последний работает только по объектам
> метаданных. `Grep` - быстрый запасной вариант.

### Сценарий F: найти причину неверного поведения в рантайме

```text
1. set_breakpoint(projectName="...", filePath="CommonModules/prj_X/Module.bsl", line=N,
                  condition="УсловиеИнтересногоСлучая")
2. edt_diagnostics(command="update_infobase", project_name="<ХостПроект>")  # хост-проект
3. edt_diagnostics(command="launch_app")   # либо debug_yaxunit_tests для тестов
4. wait_for_break(...) → get_variables(...) / evaluate_expression(...)
5. step(kind="over") … resume(...)
6. remove_breakpoint(...)
```

### Сценарий G: проверить изменение в живом веб-клиенте

```text
edt_diagnostics(command="update_infobase", project_name="<ХостПроект>")
resolve_web_client_url(projectName="<Каталог.Имя>")
→ браузерный MCP; вход - ОС-аутентификация либо логин и пароль от владельца
  (get_infobase_credentials закрыт, хотя skill verify-web-client его ещё объявляет)
→ готовый сценарий - skill(name="verify-web-client")
```

### Сценарий E: написать BDD-тест для формы

```text
qa_inspect(command="status")
qa_prepare_form_context(project="...", owner_fqn="DataProcessor.prj_Схема", usage="OBJECT")
qa_plan_scenario(goal="...", project_name="...", object_type="DataProcessor", object_name="prj_Схема")
qa_generate(command="compile_feature", ...)
qa_validate_feature(feature_file="...")
qa_run(features=["..."], use_edt_runtime=true)
```

---

## Ограничения и предостережения

| Ситуация | Рекомендация |
| --- | --- |
| `delete_metadata` | После удаления - `get_diagnostics` и `edt_find_references` |
| Изменение `prj_Ядро` | Не добавлять внешних зависимостей - нарушит изоляцию |
| Изменение `prj_Схема*` | Только `prj_СхемаКлиентСервер` и `prj_Ядро` как зависимости |
| Изменение `prj_Исполнитель`, `prj_ИсполнительDOCX` | Только `prj_Ядро` как зависимость |
| Множественные мутации | Каждая требует отдельного `edt_validate_request` |
| `ensure_module_artifact` | Теперь требует `validation_token` |
| `dcs_manage.upsert_dataset` | Пустой `query` вешает DCS-редактор EDT - всегда непустой |
| `edit_file` `.mdo` | Через override `allow_metadata_descriptor_edit=true`; обычно - BM API |
| `edt_extension_smoke`, `edt_external_smoke` | Только для проверки инфраструктуры |
| `inspect_role_rights` | Без `object_filter` ответ обрезается по объёму; дочерние объекты показываются под FQN владельца |
| `get_infobase_credentials` | Закрыт (`Tool is not exposed`) - автономный вход в веб-клиент невозможен, логин и пароль даёт владелец |
| Необязательный `projectName` | Всегда передавать явно: иначе берётся активный редактор, а в воркспейсе два проекта - хост и расширение |
| Диагностика по большому проекту | `get_diagnostics` с `project_name` (не `projectName` - иначе молча уйдёт в хост) и сужением по `object`; маркеры отстают на один запрос - спрашивать дважды. Сводка `edt_get_problem_summary` проверки SU* и строгую типизацию не показывает |
| Командная панель формы / таблицы | `set_auto_command_bar`, `set_excluded_commands`; не `set_form_props`/`set_item` и не `add_group` |
| `add_command.picture` | Не использовать - ошибка SU113; картинку команды ставить в дизайнере |
| Кнопки в `autoCommandBar` | Создаются `add_button`, но не правятся и не удаляются (`METADATA_NOT_FOUND`) |
| Откат `.form` через `git checkout` | Модель может не перечитать файл (наблюдалось, на Windows не воспроизводится) - обновить проект (`workspace_copy_transform` + `refresh_workspace`; кандидат на замену - `workspace_import_project(refresh=true)`) и сверить `inspect_form_layout` |
| `git_mutate`, `write_file`, `workspace_import_project` | С `1003-0831` вызываются без подтверждения; git ведём Bash, `push` - только по просьбе владельца |
| Обновление плагина | Проверять `pluginVersion` в ответе на `initialize`: p2 может не записать `bundles.info` |
| Список skills сервера | Верить `skill(list=true)`, а не описанию инструмента: `explain` из набора исчез |
| `workspace_copy_transform*` | Сначала `dry_run=true`, потом запись |
| `migrate_to_extension_native` | `apply` - только после разбора dry-run плана |
| Мутация формы расширения | Работает через BM API (с 2026-08-04); прямой XML - аварийный путь |
| Инструкции skill'ов сервера | Ниже приоритетом, чем CLAUDE.md, `docs/bsl-*.md` и SDD |
