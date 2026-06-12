# MCP codepilot1c — справочник инструментов

MCP-сервер `codepilot1c` предоставляет 83 инструмента для работы с EDT-проектом 1C:Enterprise.
Инструменты понимают структуру EDT и работают через BM API — в отличие от стандартных Read/Edit/Write.

> **Обновление сервера (проверка 2026-05-30):** добавлено 27 инструментов (56 → 83) и целые новые семейства —
> live-отладчик и профилировщик рантайма 1С, прогон YAxUnit (`run_yaxunit_tests`/`debug_yaxunit_tests`),
> семантическая навигация по коду (EDT LSP: go-to-definition, иерархия вызовов, структура модулей),
> теги/закладки/задачи, подключение инфобазы. См. новые разделы ниже.

---

## Содержание

1. [Ключевые правила](#ключевые-правила)
2. [BSL — чтение и анализ кода](#bsl--чтение-и-анализ-кода)
3. [Навигация и анализ кода (EDT LSP)](#навигация-и-анализ-кода-edt-lsp)
4. [Теги, закладки, задачи](#теги-закладки-задачи)
5. [Метаданные](#метаданные)
6. [Макеты](#макеты)
7. [Формы](#формы)
8. [СКД](#скд)
9. [Расширения и внешние объекты](#расширения-и-внешние-объекты)
10. [QA — тестирование](#qa--тестирование)
11. [Диагностика](#диагностика)
12. [Отладка и профилирование](#отладка-и-профилирование)
13. [Workspace и Git](#workspace-и-git)
14. [Вспомогательные инструменты](#вспомогательные-инструменты)
15. [Типовые сценарии](#типовые-сценарии)

---

## Ключевые правила

### 1. Validation token — обязателен перед любой мутацией

Перед каждой мутирующей операцией нужно получить одноразовый токен:

```text
edt_validate_request → validation_token → передать в мутирующий инструмент
```

`edt_validate_request` принимает три параметра:

- `project` — имя EDT-проекта
- `operation` — точное имя мутирующего инструмента (enum):
  `create_metadata`, `add_metadata_child`, `update_metadata`, `delete_metadata`,
  `ensure_module_artifact`, `create_form`, `mutate_form_model`, `apply_form_recipe`,
  `dcs_manage`, `extension_manage`, `external_manage`,
  и явные подкоманды (`dcs_create_main_schema`, `dcs_upsert_query_dataset`,
  `dcs_upsert_parameter`, `dcs_upsert_calculated_field`,
  `extension_create_project`, `extension_adopt_object`, `extension_set_property_state`,
  `external_create_report`, `external_create_processing`)
- `payload` — те же аргументы, что потом будут переданы в мутирующий инструмент
  (без `validation_token`); для composite-инструментов обязательно включает `command`

Токен одноразовый — для каждой мутации отдельный вызов.
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

- `read_file`, `write_file`, `edit_file` — предпочтительны перед стандартными Read/Write/Edit:
  понимают контекст EDT.
- `edit_file` запрещает редактировать `.mdo` (только через `allow_metadata_descriptor_edit=true`
  как аварийный override; обычно метаданные правятся через BM API).
- `glob` и `grep` (MCP) функционально совпадают со стандартными Glob/Grep,
  но **стандартные предпочтительнее**: богаче (output modes, count, multiline, контекст строк)
  и экономнее по токенам. MCP-версии — только если стандартные недоступны.

### 4. Идентификация модулей и объектов

BSL-инструменты идентифицируют модуль парой `projectName` + `filePath` (путь относительно `src/`),
а не FQN модуля.

```text
projectName = "<Каталог.Имя>"
filePath    = "CommonModules/prj_СхемаКлиентСервер/Module.bsl"
```

Метаданные идентифицируются через FQN (`Catalog.prj_Шаблоны`, `Document.X.Form.Y`,
`Catalog.X.Template.Y` и т.п.).

---

## BSL — чтение и анализ кода

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

- `projectName` — имя EDT-проекта
- `filePath` — путь к модулю относительно `src/` (например, `CommonModules/prj_Ядро/Module.bsl`)
- Списочные инструменты (`bsl_list_methods`, `bsl_module_exports`, `bsl_scope_members`,
  `edt_content_assist`) поддерживают `limit`, `offset`, `name_contains`/`contains`

### Паттерны использования

**Прочитать реализацию метода перед правкой:**

```text
bsl_get_method_body(
  projectName = "<Каталог.Имя>",
  filePath    = "CommonModules/prj_СхемаКлиентСервер/Module.bsl",
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
> Для поиска вызовов конкретного метода — `edt_get_method_call_hierarchy` (семантически)
> или стандартный `Grep` (по тексту).

---

## Навигация и анализ кода (EDT LSP)

Семантическая навигация поверх модели EDT (аналог LSP). Идентификация:
символы — по FQN (`symbolFqn`) или позиции (`position` = `fileUri`+`line`+`column`);
модули — по FQN **с суффиксом `.Module`** или по пути относительно `src/`.

| Инструмент | Назначение |
| --- | --- |
| `edt_list_modules` | Список всех BSL-модулей проекта: FQN, владелец, путь файла. Фильтр `objectType` (`CommonModule`, `DataProcessor`, ...) |
| `edt_get_module_structure` | Структура модуля: области, методы, экспортные (`full=true` — со call sites) |
| `edt_go_to_definition` | Определение символа по FQN или позиции |
| `edt_get_symbol_info` | Детальная информация о символе по FQN или позиции |
| `edt_get_method_call_hierarchy` | Иерархия вызовов метода: `direction` = `callers`/`callees`/`both`, `depth` |
| `edt_search_in_code` | Текст/regex-поиск по коду: `scope` = `all`/`modules`/`queries`, `searchType` = `text`/`regex` |
| `edt_get_configuration_properties` | Свойства конфигурации: name, version, vendor, счётчики коллекций |
| `edt_get_problem_summary` | Сводка проблем валидации: `total_errors`/`total_warnings`/`total_infos` + список |

Идентификация модуля — обе формы валидны:

```text
moduleFqn = "CommonModule.prj_СхемаКлиентСервер.Module"      # FQN с суффиксом .Module
moduleFqn = "CommonModules/prj_СхемаКлиентСервер/Module.bsl" # путь относительно src/
```

> Не путать обработки с общими модулями: модуль обработки лежит в
> `DataProcessors/<Имя>/ObjectModule.bsl`, а не `CommonModules/<Имя>/Module.bsl`.
> `edt_get_module_structure` резолвит модуль, но на части модулей возвращает пустые
> `methods/exports` — для надёжного списка методов используй `bsl_list_methods`/`bsl_module_exports`.

```text
# Кто вызывает метод (семантически, замена ручного Grep)
edt_get_method_call_hierarchy(
  projectName = "<Каталог.Имя>",
  methodFqn   = "CommonModule.prj_СхемаКлиентСервер.СоздатьСхему",
  direction   = "callers",
  depth       = 2
)

# Regex-поиск только по текстам запросов
edt_search_in_code(
  projectName = "<Каталог.Имя>",
  query       = "ВЫБРАТЬ.*ПЕРВЫЕ",
  scope       = "queries",
  searchType  = "regex"
)

# Список модулей-обработок
edt_list_modules(projectName = "<Каталог.Имя>", objectType = "DataProcessor")
```

---

## Теги, закладки, задачи

Read-only маркеры из модели EDT/Eclipse.

| Инструмент | Назначение |
| --- | --- |
| `edt_get_tags` | Список тегов проекта + число объектов по каждому тегу |
| `edt_get_objects_by_tags` | Объекты метаданных с указанными тегами (`tags[]`) |
| `get_bookmarks` | Закладки Eclipse/EDT: файл, строка, сообщение, тип, приоритет (`limit` 1..1000) |
| `get_tasks` | Маркеры TODO/FIXME/XXX: файл, строка, сообщение, приоритет (`limit` 1..1000) |

```text
get_tasks(projectName = "<Каталог.Имя>", limit = 50)
# → {total, hasMore, markers: [{resource: "src/.../Module.bsl", line: 1259,
#                               markerType: "TODO", message: "...", priority: "P_NORMAL"}, ...]}
```

---

## Метаданные

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `scan_metadata_index` | Индекс верхнеуровневых объектов по проекту с фильтрами | R |
| `edt_metadata_details` | Детальные сведения об объектах: свойства, дети, формы, модули | R |
| `edt_field_type_candidates` | Допустимые EDT-типы для поля существующего объекта | R |
| `inspect_platform_reference` | Встроенная справка по типам платформы (Query, DocumentObject и др.) | R |
| `edt_validate_request` | Получить validation_token перед мутацией | R |
| `create_metadata` | Создать новый верхнеуровневый объект метаданных | **W** |
| `add_metadata_child` | Создать дочерний объект под существующим владельцем | **W** |
| `update_metadata` | Обновить свойства существующего объекта | **W** |
| `delete_metadata` | Удалить объект или дочерний элемент | **W** |
| `ensure_module_artifact` | Материализовать `.bsl`-файл для объекта (требует validation_token) | **W** |

### Параметры инструментов метаданных

- `scan_metadata_index(projectName, scope?, nameContains?, language?, limit?, includeModules?)`
- `edt_metadata_details(projectName, objectFqns[], full?, language?)` — массив FQN
- `edt_field_type_candidates(project, target_fqn, field, limit?)`
- `inspect_platform_reference(project, type_name?, contains?, member_filter?, language?, limit?, offset?)`
- `create_metadata(project, kind, name, validation_token, properties?, synonym?, comment?)`
- `add_metadata_child(project, parent_fqn, child_kind, name, validation_token, ...)`
- `update_metadata(project, target_fqn, changes, validation_token)` —
  `changes` имеет формат `{set: {...}, unset: [...], children_ops: [...]}`
- `delete_metadata(project, target_fqn, validation_token, recursive?, force?)`
- `ensure_module_artifact(project, object_fqn, validation_token, module_kind?, create_if_missing?, initial_content?)`

### `create_metadata.kind` — допустимые виды

`Catalog`, `Document`, `InformationRegister`, `AccumulationRegister`, `AccountingRegister`,
`CalculationRegister`, `CommonModule`, `CommonAttribute`, `Enum`, `Report`, `DataProcessor`,
`Constant`, `CommandGroup`, `Interface`, `Language`, `Style`, `StyleItem`, `SessionParameter`,
`SettingsStorage`, `XDTOPackage`, `WSReference`, `Role`, `Subsystem`, `ExchangePlan`,
`ChartOfAccounts`, `ChartOfCharacteristicTypes`, `ChartOfCalculationTypes`, `BusinessProcess`,
`Task`, `CommonForm`, `CommonCommand`, `CommonTemplate`, `CommonPicture`, `ScheduledJob`,
`FilterCriterion`, `DefinedType`, `Sequence`, `DocumentJournal`, `DocumentNumerator`,
`EventSubscription`, `FunctionalOption`, `FunctionalOptionsParameter`, `WebService`,
`HTTPService`, `ExternalDataSource`, `IntegrationService`, `Bot`, `WebSocketClient`.

### `add_metadata_child.child_kind` — допустимые виды детей

`Attribute`, `Tabular_Section`, `Command`, `Form`, `Template`, `Dimension`, `Resource`, `Requisite`.

При `child_kind=Form` дополнительно: `form_usage` (`OBJECT`/`LIST`/`CHOICE`/`AUXILIARY`),
`set_as_default`, `wait_ms`. При `child_kind=Template` — `template_type`
(`spreadsheet`/`html`/`text`/`binary`/`dcs`/`active_document`).

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

> После `delete_metadata` обязательно проверить `get_diagnostics` и `edt_find_references` —
> инструмент предупреждает о влиянии на формы и другие объекты.

---

## Макеты

| Инструмент | Назначение | Read/Write |
| --- | --- | --- |
| `inspect_template` | Прочитать содержимое макета: ячейки, параметры, именованные области | R |
| `render_template` | Сгенерировать макет из секционного JSON — полная замена `.mxl`-файла | **W** |

`render_template` требует `validation_token` (получить через `edt_validate_request`,
`operation` для composite-сценариев — точная команда инструмента; обычно достаточно общего токена).

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
| `inspect_form_layout` | Дерево элементов формы, dataPath, команды, свойства | R |
| `create_form` | Создать новую управляемую форму для объекта метаданных | **W** |
| `mutate_form_model` | Точечные изменения модели существующей формы | **W** |
| `apply_form_recipe` | Применить декларативный recipe: создание, поиск, атрибуты, layout | **W** |

### Параметры инструментов форм

- `inspect_form_layout(project, form_fqn, include_invisible?, include_properties?, include_titles?, max_depth?, max_items?)`
- `create_form(project, owner_fqn, name, validation_token, usage?, synonym?, comment?, set_as_default?, managed?, wait_ms?)`
- `mutate_form_model(project, form_fqn, operations[], validation_token)`
- `apply_form_recipe(project, validation_token, form_fqn?, owner_fqn?, name?, attributes[]?, layout[]?, usage?, mode?, set_as_default?, ...)`

### `mutate_form_model.operations` — допустимые `op`

`set_form_props`, `add_group`, `add_field`, `add_command`, `add_button`, `set_item`,
`remove_item`, `move_item`.

- `add_command` — нужны `name` + `action` (обработчик)
- `add_button` — нужны `name` + `command_name` + `parent_item_id`

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

- `mutate_form_model` — точечные операции (добавить элемент, изменить свойство)
- `apply_form_recipe` — декларативный подход: описываем желаемое состояние (`attributes` + `layout`),
  инструмент сам определяет нужные операции (создать/найти/обновить).
  Удобен для составных изменений из нескольких шагов

`attributes[i].action` (case-insensitive): `add`/`create`/`new`, `update`/`set`/`patch`/`modify`,
`upsert`/`ensure`/`apply`/`merge`, `remove`/`delete`/`drop`.

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

> ВНИМАНИЕ: `owner_fqn` — это FQN владельца (`Report.X` / `Catalog.X`), **не** Template FQN.

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

`set_state` — состояние свойства: `NONE`, `CHECKED`, `EXTENDED`, `NOTIFY`.
`create` принимает `purpose` (`ADD_ON`/`CUSTOMIZATION`/`PATCH`), `compatibility_mode`, `version`,
`configuration_name`, `project_path`.

### Внешние отчёты и обработки

| Инструмент | Команды |
| --- | --- |
| `external_manage` | `list_projects`, `list_objects`, `details`, `create_report`, `create_processing` |
| `edt_external_smoke` | E2E smoke runtime внешних объектов |

> `edt_extension_smoke` и `edt_external_smoke` — для проверки инфраструктуры,
> не для обычной разработки.

---

## QA — тестирование

### YAxUnit (unit/integration на встроенном языке)

| Инструмент | Назначение |
| --- | --- |
| `author_yaxunit_tests` | Создать/обновить общий модуль с тестами, синхронизировать ИсполняемыеСценарии |

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

#### Прогон и отладка YAxUnit (новое)

| Инструмент | Назначение |
| --- | --- |
| `run_yaxunit_tests` | Запустить YAxUnit, распарсить JUnit XML → Markdown-отчёт. Опции: `filters`, `update_database`, `keep_connected`, `junit_xml_path`, `timeout_s` |
| `debug_yaxunit_tests` | Запустить YAxUnit в режиме **отладки** (под брейкпоинты): `launch_config_name`, `wait_for_debugger`, `filters` |

> `author_yaxunit_tests` **создаёт** тесты, `run_yaxunit_tests` — **исполняет** их.
> Оба требуют подключённой инфобазы (`connect_infobase`) и интеграции YAxUnit.
> `debug_yaxunit_tests` стыкуется с разделом [Отладка и профилирование](#отладка-и-профилирование):
> ставим `set_breakpoint`, запускаем `debug_yaxunit_tests(wait_for_debugger=true)`, далее `wait_for_break` → `get_variables`.

```text
run_yaxunit_tests(
  project_name    = "<Каталог.Имя>",
  filters         = "prj_ЯдроТесты",
  update_database = false
)
```

### Vanessa Automation (BDD / E2E сценарии)

| Инструмент | Шаг | Команды/Назначение |
| --- | --- | --- |
| `qa_inspect` | 0 | `explain_config`, `status`, `steps_search` |
| `qa_prepare_form_context` | 1 | Подготовить форму (создать default при необходимости) |
| `qa_plan_scenario` | 2 | Построить structured plan из цели — без ручного Gherkin |
| `qa_generate` | 3 | Команды: `init_config`, `migrate_config`, `compile_feature` |
| `qa_validate_feature` | 4 | Preflight feature по каталогу шагов Vanessa |
| `qa_run` | 5 | Запуск E2E |

`qa_run` ключевые опции: `features[]`, `scenarios[]`, `tags_include[]`, `tags_exclude[]`,
`unknown_steps_mode` (`off`/`warn`/`strict`), `dry_run`, `update_db`, `use_edt_runtime`,
`use_test_manager`, `timeout_s`, `clear_steps_cache`.

```text
qa_inspect(command="status")
qa_prepare_form_context(
  project   = "<Каталог.Имя>",
  owner_fqn = "DataProcessor.prj_Схема",
  usage     = "OBJECT"
)
qa_plan_scenario(
  goal         = "Пользователь создаёт новую схему",
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

## Диагностика

| Инструмент | Назначение |
| --- | --- |
| `edt_diagnostics` | EDT диагностика и runtime-команды (CLI/headless) |
| `get_diagnostics` | Live-диагностики из UI workbench (по проекту, файлу или активному редактору) |

### `edt_diagnostics.command` (переименовано)

| Команда | Назначение |
| --- | --- |
| `metadata_smoke` | Headless-проверка метаданных (раньше `smoke`) |
| `trace_export` | Диагностика проблем экспорта |
| `analyze_error` | Разбор конкретного error payload (раньше `parse_errors`) |
| `update_infobase` | Обновить инфобазу |
| `launch_app` | Запустить приложение (раньше `run_app`) |

### `get_diagnostics`

| Параметр | Назначение |
| --- | --- |
| `scope` | `project` / `file` / `active_editor` |
| `project_name` | для `scope=project` |
| `path` | workspace-относительный путь для `scope=file` |
| `severity` | `error` / `warning` / `info` |
| `max_items` | 0 = без ограничений |
| `wait_ms` | ожидание пересчёта (0–2000 мс) |
| `include_runtime_markers` | подключать маркеры EDT marker manager |

```text
# Live-диагностика проекта
get_diagnostics(scope="project", project_name="<Каталог.Имя>", severity="warning")

# Live-диагностика конкретного файла
get_diagnostics(scope="file", path="src/CommonModules/prj_Ядро/Module.bsl", wait_ms=500)

# Headless smoke (если UI недоступен)
edt_diagnostics(command="metadata_smoke")
```

---

## Отладка и профилирование

Новое семейство — live-отладчик рантайма 1С и профилировщик поверх EDT debug API.
Требует **активной отладочной сессии** (запуск приложения/тестов в режиме отладки)
и подключённой инфобазы (см. [Инфобаза](#инфобаза)). Все инструменты — top-level,
в `discover_tools` по категориям **не раскрываются** (см. примечание в конце).

### Отладчик

| Инструмент | Назначение |
| --- | --- |
| `debug_status` | Статус: `state`, `suspended`, число launch/target/breakpoint |
| `set_breakpoint` | Точка останова: `filePath` (относительно `src/`) + `line`; опц. `condition`, `enabled` |
| `remove_breakpoint` | Снять по `breakpointId` или паре `filePath`+`line` |
| `list_breakpoints` | Список точек останова в проекте/воркспейсе |
| `wait_for_break` | Ждать приостановки потока (`timeoutMs`) |
| `step` | Шаг потока: `kind` = `into`/`over`/`out` |
| `resume` | Продолжить поток/таргет (опц. `threadId`) |
| `get_variables` | Переменные текущего фрейма стека (опц. `frameId`/`threadId`) |
| `evaluate_expression` | Вычислить выражение в текущем фрейме (`expression`) |

```text
set_breakpoint(
  projectName = "<Каталог.Имя>",
  filePath    = "DataProcessors/prj_Исполнитель/ObjectModule.bsl",
  line        = 120
)
# запустить отладку: edt_diagnostics(command="launch_app") или debug_yaxunit_tests(...)
wait_for_break(projectName = "<Каталог.Имя>", timeoutMs = 60000)
get_variables(projectName = "<Каталог.Имя>")
evaluate_expression(projectName = "<Каталог.Имя>", expression = "Схема.Параметры.Количество()")
step(projectName = "<Каталог.Имя>", kind = "over")
resume(projectName = "<Каталог.Имя>")
```

### Профилирование

| Инструмент | Назначение |
| --- | --- |
| `start_profiling` | Включить/выключить профайлер на активном debug-таргете (`applicationId` — если таргетов несколько) |
| `get_profiling_results` | Результаты: модули, строки, вызовы, тайминг, покрытие. Фильтры `moduleFilter`, `minFrequency`, `maxLinesPerModule` (≤1000) |

```text
start_profiling()                                  # toggle on на единственном таргете
# выполнить целевой сценарий в отлаживаемом приложении
get_profiling_results(moduleFilter = "prj_Исполнитель", minFrequency = 2)
```

> Отладчик и профайлер — для разбора рантайм-поведения (узкие места,
> трудноуловимые баги), не для статического анализа. Для статики — `bsl_analyze_method`
> и навигация EDT LSP.

---

## Workspace и Git

| Инструмент | Назначение |
| --- | --- |
| `git_inspect` | Read-only: `status`, `branch_list`, `remote_list`, `log`, `diff_summary` |
| `git_mutate` | Разрешённые мутации (см. ниже) |
| `workspace_import_project` | Импортировать существующий локальный EDT-проект в workspace |
| `git_clone_and_import_project` | Клонировать репозиторий и сразу импортировать проект |
| `import_project_from_infobase` | Создать EDT-проект из связанной инфобазы |

`git_mutate.operation`: `init`, `create`, `create_repo`, `clone`, `remote_add`, `remote_set_url`,
`fetch`, `pull`, `push`, `checkout`, `create_branch`, `add`, `commit`.

> Для git-операций в EDT-проекте предпочтительно передавать `project_name`, а не `repo_path` —
> инструмент сам определит нужный путь. `repo_path` обязателен только для `init`/`create`/`clone`.

### Инфобаза

| Инструмент | Назначение |
| --- | --- |
| `connect_infobase` | Привязать к проекту файловую (`kind=file`) или standalone (`kind=standalone`) ИБ; `set_primary` делает её основной, `force` заменяет существующую |
| `update_infobase_status` | Опрос статуса фонового обновления ИБ по `job_id` (из `edt_diagnostics(command="update_infobase", async=true)`): state, время, результат/ошибка |

```text
connect_infobase(
  project_name  = "<Каталог.Имя>",
  database_path = "/путь/к/файловой/ИБ",
  kind          = "file",
  set_primary   = true
)
```

> `connect_infobase` — предпосылка для отладки и `run_yaxunit_tests` (нужна подключённая ИБ).
> Параметр `password` в результат не возвращается.

---

## Вспомогательные инструменты

| Инструмент | Назначение |
| --- | --- |
| `read_file` | Прочитать файл (опционально диапазон строк) |
| `write_file` | Полная перезапись существующего файла (`overwrite=true`) |
| `edit_file` | Точечное редактирование (replace, SEARCH/REPLACE, fuzzy) |
| `list_files` | Обзор файлов и папок workspace (`pattern?`, `recursive?`) |
| `glob` | Поиск файлов по паттерну — **предпочитать стандартный Glob** |
| `grep` | Поиск по содержимому — **предпочитать стандартный Grep** |
| `discover_tools` | Раскрыть инструменты категории (`bsl`/`metadata`/`forms`/`extensions`/`dcs`/`qa`/`diagnostics`/`workspace`) |
| `skill` | Загрузить специализированный workflow (без аргумента — список skills) |
| `task` | Запустить подагента; `profile`: `auto`/`explore`/`plan`/`build`/`code`/`metadata`/`qa`/`dcs`/`extension`/`recovery`/`orchestrator` |
| `delegate_to_agent` | Делегировать задачу профильному агенту; `agentType`: `auto`/`code`/`metadata`/`qa`/`dcs`/`extension`/`recovery`/`plan`/`explore`/`orchestrator` |
| `remember_fact` | Сохранить факт в долгосрочную память сервера; `category`: `FACT`/`ARCHITECTURE`/`DECISION`/`PATTERN`/`BUG` |
| `inspect_platform_reference` | Справка по типам встроенного языка платформы |

> **discover_tools и новые семейства.** Enum категорий `discover_tools` не расширяли —
> там по-прежнему `bsl|metadata|forms|extensions|dcs|qa|diagnostics|workspace`.
> Инструменты навигации EDT LSP и тегов распределены по `bsl`/`metadata`/`workspace`,
> а **весь блок отладки и профилирования** (`set_breakpoint`, `step`, `get_variables`,
> `evaluate_expression`, `start_profiling`, ...) **ни в одну категорию не попадает** —
> эти инструменты top-level и раскрываются напрямую (через поиск инструментов), минуя `discover_tools`.

---

## Типовые сценарии

### Сценарий A: изучить незнакомый модуль

```text
bsl_module_context(projectName="...", filePath="CommonModules/prj_СхемаКлиентСервер/Module.bsl")
bsl_list_methods(   projectName="...", filePath="CommonModules/prj_СхемаКлиентСервер/Module.bsl")
bsl_module_exports( projectName="...", filePath="CommonModules/prj_СхемаКлиентСервер/Module.bsl")
bsl_get_method_body(projectName="...", filePath="CommonModules/prj_СхемаКлиентСервер/Module.bsl", name="НужныйМетод")
```

### Сценарий B: добавить новый метод в существующий модуль

```text
1. bsl_get_method_body(...)         → читаем соседние методы для контекста
2. edt_validate_request(operation="ensure_module_artifact", payload={object_fqn:"..."}) → token
3. ensure_module_artifact(..., validation_token=token) → путь
4. edit_file(...)                   → вносим изменения
5. get_diagnostics(scope="file", path=...) → проверяем ошибки
```

### Сценарий C: создать объект метаданных с формой и тестом

```text
1. edt_validate_request(operation="create_metadata",      payload={kind:"Catalog", name:"prj_Новый"})
2. create_metadata(kind="Catalog", name="prj_Новый", validation_token=...)
3. edt_validate_request(operation="create_form",          payload={owner_fqn:"Catalog.prj_Новый", name:"ФормаЭлемента"})
4. create_form(owner_fqn="Catalog.prj_Новый", name="ФормаЭлемента", usage="OBJECT", set_as_default=true, validation_token=...)
5. inspect_form_layout(form_fqn="Catalog.prj_Новый.Form.ФормаЭлемента", include_properties=true)
6. author_yaxunit_tests(project="...", feature="prj_Новый", tests=[...])
7. get_diagnostics(scope="project", project_name="...")
```

### Сценарий D: рефакторинг — найти все использования объекта метаданных

```text
edt_find_references(projectName="...", objectFqn="Catalog.prj_УстаревшийСправочник")
→ список мест → для каждого read_file/edit_file
```

> Для поиска вызовов конкретного метода BSL — **стандартный `Grep`** по `prj_Ядро.МойМетод`,
> а не `edt_find_references` (он работает только по объектам метаданных).

### Сценарий E: написать BDD-тест для формы

```text
qa_inspect(command="status")
qa_prepare_form_context(project="...", owner_fqn="DataProcessor.prj_Схема", usage="OBJECT")
qa_plan_scenario(goal="...", project_name="...", object_type="DataProcessor", object_name="prj_Схема")
qa_generate(command="compile_feature", ...)
qa_validate_feature(feature_file="...")
qa_run(features=["..."], use_edt_runtime=true)
```

### Сценарий F: отладить рантайм-поведение

```text
connect_infobase(project_name="...", database_path="...", kind="file")   # если ИБ ещё не привязана
set_breakpoint(projectName="...", filePath="DataProcessors/prj_Исполнитель/ObjectModule.bsl", line=120)
debug_yaxunit_tests(project_name="...", filters="prj_ИсполнительТесты", wait_for_debugger=true)
wait_for_break(projectName="...", timeoutMs=60000)
get_variables(projectName="...")
evaluate_expression(projectName="...", expression="Область.Параметры.Количество()")
step(projectName="...", kind="over")  →  resume(projectName="...")
```

### Сценарий G: найти узкое место (профилирование)

```text
# приложение запущено в режиме отладки
start_profiling()                                  # toggle on
# выполнить целевой сценарий
get_profiling_results(moduleFilter="prj_Исполнитель", minFrequency=2, maxLinesPerModule=200)
→ строки с наибольшим временем/числом вызовов
```

---

## Ограничения и предостережения

| Ситуация | Рекомендация |
| --- | --- |
| `delete_metadata` | После удаления — `get_diagnostics` и `edt_find_references` |
| Изменение модулей с архитектурными ограничениями | Сверяться с разделом «Архитектурные ограничения» в `CLAUDE.md` — не добавлять запрещённых зависимостей |
| Множественные мутации | Каждая требует отдельного `edt_validate_request` |
| `ensure_module_artifact` | Теперь требует `validation_token` |
| `dcs_manage.upsert_dataset` | Пустой `query` вешает DCS-редактор EDT — всегда непустой |
| `edit_file` `.mdo` | Через override `allow_metadata_descriptor_edit=true`; обычно — BM API |
| `edt_extension_smoke`, `edt_external_smoke` | Только для проверки инфраструктуры |
| Отладчик/профайлер (`set_breakpoint`, `step`, `start_profiling`, ...) | Нужна активная отладочная сессия + подключённая ИБ; в `discover_tools` не раскрываются |
| `run_yaxunit_tests`, `debug_yaxunit_tests` | Нужны `connect_infobase` и интеграция YAxUnit |
| `edt_get_module_structure` | На части модулей возвращает пустые `methods/exports` — для списка методов брать `bsl_list_methods` |
| `moduleFqn` (EDT LSP) | FQN модуля — с суффиксом `.Module` (`CommonModule.X.Module`), либо путь от `src/` |
