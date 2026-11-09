# MCP EDT-MCP - справочник

MCP-сервер [EDT-MCP](https://github.com/DitriXNew/EDT-MCP) (DitriXNew, AGPL-3.0) - плагин 1C:EDT,
который отдаёт агенту модель EDT: метаданные, формы, BSL, диагностику, базу, отладчик и
YAxUnit. Работает через API EDT, а не через текст файлов.

Основной MCP-сервер шаблона: параметр проекта «MCP-сервер» = EDT-MCP (`CLAUDE.md`, раздел
«Инструменты»). Сервер поддерживает только EDT 2026.1 и 2026.2 (§1); проект на более старой
EDT работает с codepilot1c - [`codepilot1c-reference.md`](codepilot1c-reference.md), там же
таблица соответствия вызовов.

Справочник сверен с живым сервером **2026-11-04** (плагин `2.22.1`, EDT `2026.1.3.25`, macOS)
на проекте-расширении с хост-конфигурацией БСП. Что сверено на Windows - помечено отдельно; без
пометки - macOS.

Подробности по любому инструменту отдаёт сам сервер: `get_tool_guide(toolName)` - полный текст,
`mode="summary"` - список разделов, `section="#якорь"` - один раздел. Справочник ниже не
повторяет параметры, а фиксирует то, что нарушается молча, и решения проекта.

---

## 1. Подключение

Адрес - `http://127.0.0.1:<порт>/mcp` (порт - в настройках плагина, у каждой машины может быть
свой), имя сервера в Claude Code - `edtmcp`.

Имя сервера одно на всех машинах: от него зависят имена инструментов (`mcp__edtmcp__*`) в
`.claude/settings.json` и в запретах агентов цикла этапа. Подключение -
`claude mcp add --transport http -s local edtmcp http://127.0.0.1:<порт>/mcp` (только этот
проект, в `.mcp.json` не пишется) или по образцу `.mcp.json.example`.

**Установка.** EDT: Справка → Установить новое ПО → сайт `https://ditrixnew.github.io/EDT-MCP/`
→ **EDT MCP Server Feature** → перезапуск. Порт - Настройки → MCP Server → Server Port, затем
**Restart** там же.

**Установка может не дойти до EDT (macOS, 2026-11-04).** Установщик p2 этой установки EDT
записывает плагин в профиль и кладёт jar в `~/.p2/pool/plugins`, но не дописывает
`bundles.info` - EDT после перезапуска плагин не поднимает, страницы MCP Server в настройках нет.
Дефект установки EDT, а не плагина: так же было с прежним MCP-сервером. Лечение - при закрытом
EDT дописать в `bundles.info` строку по образцу соседних (копию файла - рядом,
`bundles.info.bak-<дата>`):

```text
com.ditrix.edt.mcp.server,<версия>,../../../../../../../../../.p2/pool/plugins/com.ditrix.edt.mcp.server_<версия>.jar,4,false
```

Файл - `<установка EDT>/1cedt.app/Contents/Eclipse/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info`;
установку EDT видно по пути процесса `1cedt` (`ps -o command= -p <pid>`). То же - после
каждого обновления плагина: сверить версию в `get_server_status` с последним jar в пуле.

**Проверка живости.** `get_server_status` - `running`, `pluginVersion`, `edtVersion`,
`enabledTools`. Без сессии - сырой `POST /mcp` с `initialize`; в ответе `serverInfo.version`.
В логе EDT (`<воркспейс>/.metadata/.log`) - строка `MCP Server started on port <порт>`.
Инструменты подхватываются только при подключении клиента: если EDT поднялся позже сессии -
`/mcp` и переподключение.

**Версии EDT.** Плагин с `1.27.0` поддерживает только EDT 2026.1 и 2026.2; EDT 2025.2 - до
`1.26.1`; EDT 2024.x не поддерживался никогда.

### Согласие на разрушительные операции

Настройки → MCP Server → General → **Consent level**. Подтверждения человеком в EDT требуют
удаление и переименование метаданных, обновление базы, `evaluate_expression`, завершение
сеансов, `modify_metadata` со сменой типа, запись `project_checks` и `merge_rules`, команды
`git` на запись.

Окно подтверждения ждёт 120 с, а клиент бросает вызов раньше: вызов уходит в таймаут, сервер
затем сам отклоняет операцию, ничего не меняя (в логе EDT - `Destructive-consent gate: ...
auto-rejecting`). Поэтому уровень согласия для работы с агентом - не «Ask always»:

- рекомендуемый - **Allow all**: окон нет, разрушительные операции держит двухфазность ниже;
- допустимо - «Спрашивать, кроме разрешённых» с отмеченными инструментами, которыми агент
  пользуется постоянно (`modify_metadata`, `delete_metadata`, `update_database`).

Двухфазность остаётся в самих инструментах при любом уровне: `delete_metadata`,
`update_database`, `delete_project`, `delete_infobase`, `infobase_sessions(terminate)` без
`confirm=true` только показывают, что будет сделано. Правило агента: сначала вызов без
`confirm`, затем с ним. `evaluate_expression`, `set_variable`, завершение сеансов - только по
прямому поручению. Инструмент `git` выключен по умолчанию и **не включается**: git идёт через
Bash по правилам веток.

---

## 2. Ключевые правила

1. **`projectName` - всегда явно.** Имя EDT-проекта, а не каталога: расширение -
   `<Каталог.Имя>`, проект тестов, хост-конфигурация - свои имена (`CLAUDE.md`, «EDT-воркспейс»).
   Имя параметра одно во всех инструментах.
2. **База - через проект, к которому она привязана.** В воркспейсе расширения это хост:
   `update_database`, `run_yaxunit_tests`, `launch` берут `projectName="<ХостПроект>"` и
   `applicationId` из `get_applications`. С проектом расширения `update_database` отвечает
   «Application not found», хотя `get_applications` по расширению базу находит
   (`inheritedFromProject: <ХостПроект>`).
3. **Адреса объектов - английские FQN** (`DataProcessor.prj_Обработка`,
   `CommonModule.prj_ОбщегоНазначения`, `DataProcessor.X.Form.Форма.Attribute.Реквизит`); имена
   типов в адресе принимаются и по-русски. Путь модуля - от `src/`
   (`CommonModules/prj_Модуль/Module.bsl`).
4. **Ответ на запись несёт свежие замечания EDT** (`markers`, `markerCount`): после
   `create_metadata` / `modify_metadata` / `write_module_source` маркеры уже пересчитаны -
   отставания на запрос нет.
5. **«Project is building: stage ...» - не сбой**, а честный отказ, пока EDT пересобирает
   проект (чаще всего сразу после обновления базы): пауза 20-30 с и повтор.
6. **Неясен параметр - `get_tool_guide(toolName)`**, а не догадка. Ошибки аргументов сервер
   объясняет текстом с подсказкой, что передать.

---

## 3. Карта задач

| Задача | Инструмент | Заметка |
| --- | --- | --- |
| Замечания EDT по объекту | `get_project_errors(projectName, objectFqns=[...])` | §4 |
| Сводка замечаний проекта | `get_problem_summary(projectName)` | числа по важности |
| Объяснение проверки | `get_check_description` | по коду проверки из `get_project_errors` |
| Перечитать правку мимо EDT | `revalidate_objects(projectName, objects=[...])` | §6 |
| Структура модуля | `get_module_structure(projectName, modulePath)` | `responseFormat="detailed"` - с сигнатурами |
| Тело метода / модуля | `read_method_source` / `read_module_source` | для правки обычно хватает `Read` |
| Кто вызывает метод | `get_method_call_hierarchy(direction="callers")` | строка и текст вызова; только статические вызовы |
| Где используется объект | `find_references(objectFqn)` | только объекты верхнего уровня |
| Поиск по коду | `search_in_code` | текстовый; `Grep` дешевле и не хуже |
| Тип и документация символа | `get_symbol_info`, `go_to_definition`, `get_content_assist` | |
| Встроенный тип или функция платформы | `get_platform_documentation` | по умолчанию заголовки, `responseFormat="detailed"` - полно |
| Проверка запроса | `validate_query(projectName, queryText, dcsMode)` | видит объекты основной конфигурации из расширения |
| Метаданные объекта, формы | `get_metadata_details(objectFqns, full=true)` | свойства члена - `assignable=true` |
| Создать объект, реквизит, элемент формы | `create_metadata` | §5 |
| Изменить свойства, тип, права роли, макет | `modify_metadata` | §5 |
| Удалить / переименовать с каскадом | `delete_metadata` / `rename_metadata_object` | двухфазно |
| Заимствовать объект в расширение | `adopt_metadata_object` | |
| Записать модуль | `write_module_source` | проверка синтаксиса, `expectedHash` для правки метода |
| СКД, динамический список, условное оформление формы | `dcs` | сначала `action="get"` |
| Командный интерфейс раздела | `get_metadata_details` / `modify_metadata(commands=...)` | если меню раздела - зона владельца (`CLAUDE.md`), не трогать |
| Проверка структуры формы | `validate_form_model(projectName, formFqn)` | §5, ложные срабатывания |
| Вид печатного макета | `get_template_screenshot` | |
| Обновить базу | `update_database` | §7 |
| YAxUnit | `tools/yaxunit/yaxunit.py` (основной), `run_yaxunit_tests` | §7 |
| Отладка | `set_breakpoint` → `run_yaxunit_tests(debug=true)` / `launch` → `wait_for_break` → `get_variables` / `evaluate_expression` → `resume` | §7 |
| Профилирование | `start_profiling` → прогон → `stop_profiling` → `get_profiling_results` | |
| Журнал регистрации базы | `get_event_log` | только старый текстовый формат журнала |

---

## 4. Диагностика

`get_project_errors` отдаёт тот же набор, что EDT показывает в «Проблемах конфигурации»,
включая проверки строгой типизации (`statement-type-change`, `dynamic-access-method-not-found`
и т.п.). У каждой строки - описание, место в объекте (модуль, форма, условное оформление),
путь модуля, строка, **код проверки** и признак быстрого исправления (`apply_quick_fix`).

- **Фильтр по объекту - `objectFqns`** (точный адрес). Ответ перечисляет `objectsResolved` и
  `objectsNotFound`: ненайденный адрес назван явно, «чисто» по опечатке не бывает. `objects` -
  нестрогий поиск подстроки по месту; одно из двух.
- Фильтры `checkId` (символьный код или `SU23`) и `severity` (точное значение, не порог).
- `limit` по умолчанию 100, до 1000; упёрлись - ответ это говорит.
- Важность у EDT-MCP своя шкала: `ERRORS`, `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `TRIVIAL`.
  Правило «ноль замечаний» изолированных подсистем (`CLAUDE.md`, «Архитектурные ограничения») -
  ноль строк любой важности.
- Маркеры `TODO` в `get_project_errors` не попадают (это не проверка EDT).
- После записи инструментом EDT-MCP маркеры свежие сразу. После правки мимо EDT - сначала
  `revalidate_objects` (§6), иначе ответ - по прежнему содержимому файла.
- Сравнение с codepilot1c (2026-11-04): состав замечаний по объекту совпал на трёх объектах;
  вызов ~0,15 с против нескольких секунд.

---

## 5. Метаданные и формы

Формы собираются инструментами: `create_metadata` на адрес члена формы и `modify_metadata`
на его свойства. Ручная правка `.form` - только когда инструмент свойство не умеет, и затем
`revalidate_objects`.

**Адреса членов формы** - `<Объект>.Form.<Форма>.<Вид>.<Имя>`, виды `Attribute`, `Command`,
`Parameter`, `Group`, `Decoration`, `Field`, `Button`, `Table`. Колонка реквизита-коллекции -
`...Attribute.<Реквизит>.Column.<Колонка>`. Обработчики - `...Form.F.Handler.<Событие>`,
`...Field.<Поле>.Handler.<Событие>`, действие команды - `...Command.<Команда>.Handler.Action`.
Структуру формы целиком показывает `get_metadata_details(objectFqns=["<Объект>.forms.<Форма>"], full=true)`.

**Проверенный порядок сборки (2026-11-04):**

1. Форма: `create_metadata("<Объект>.Form.<Форма>", setAsDefault=true)`.
2. Реквизит: `create_metadata(...Attribute.<Имя>)`, затем тип - `modify_metadata` со свойством
   `valueType` (`{types:[{kind:"ValueTable"}]}`, `{kind:"String", length:100}`,
   `{kind:"Number", precision:15, scale:2}`, ссылка - `{kind:"Ref", ref:"Catalog.X"}`).
3. Колонки коллекции: `create_metadata(...Column.<Имя>)`, тип - `modify_metadata` так же.
4. Таблица: `create_metadata(...Table.<Имя>)` с `dataPath` = имя реквизита - колонки таблицы
   строятся сами по колонкам реквизита, вместе с командной панелью таблицы.
5. Команда: `create_metadata(...Command.<Имя>)`, затем `...Command.<Имя>.Handler.Action`
   (процедура по умолчанию - имя команды).
6. Кнопка: `create_metadata(...Button.<Имя>)` с `command` и `parent`: `AutoCommandBar` -
   командная панель формы, `<Таблица>.AutoCommandBar` - панель таблицы.
7. Обработчик события элемента: `...Field.<Поле>.Handler.OnChange` (событие - по-английски или
   по-русски), `procedure` - имя процедуры.
8. Модуль формы: `write_module_source(objectName, moduleType="FormModule", formName, mode="replace")`.
9. Проверка: `get_project_errors` по объекту, `validate_form_model`, `git status` - посторонних
   изменений нет.

Порядок «сначала привязка обработчика, потом процедура» оставляет до записи модуля два
замечания «метод отсутствует в модуле формы» - они уходят с записью модуля. Привязка к уже
существующей процедуре оставляет `module-unused-method` до `revalidate_objects` по объекту.

Форма, собранная так, загрузилась в базу с режимом совместимости расширения 8.3.18 без
ошибок XDTO (2026-11-04) - класс проблем «новая форма не собирается под режим совместимости»
у codepilot1c здесь не воспроизвёлся. На новой форме - всё равно проверить первым
обновлением базы.

**Что делается не так, как ждёшь:**

- `create_metadata` с двумя синонимами или заголовками (`ru` и `en`) записывает только
  последний и сообщает `localesMissing`. Второй язык - отдельным `modify_metadata` с
  `language`. Второй язык проекта, если он ведётся, ставится этим вторым вызовом.
- Синоним самой формы (объекта метаданных «форма») через `modify_metadata` не адресуется -
  у адреса формы доступны свойства формы (`title`, `excludedCommands` и т.д.), не синоним.
- Тип реквизита формы - свойство `valueType`, у реквизита объекта - `type`.
- `excludedCommands` (форма, таблица, поле) заменяет весь набор, `[]` очищает; имена
  стандартных команд - из `get_metadata_details(assignable=true)`.
- `get_metadata_details` показывает у командной панели `visible: false`, хотя в `.form` она
  такая же, как у форм из дизайнера: EDT пишет в файл только `<visible>true</visible>`,
  отсутствие строки и есть умолчание. Не правка.
- Динамический список - `modify_metadata` со свойствами `queryText` / `customQuery` /
  `mainTable` или `dcs`; голый тип `DynamicList` отклоняется.

**`validate_form_model`** считает по модели сейчас, сразу после правки. Ловит кнопки без
команды, дубли имён и id, путь данных без реквизита, обработчик без процедуры. **Ложные
срабатывания:** путь `Items.<Таблица>.CurrentData.<Поле>` (допустимый в платформе) он
считает несуществующим реквизитом. На проверочной форме (2026-11-04) - 5 настоящих находок
(кнопки контекстного меню без команды, EDT их не помечает) и 3 ложных.

**Строковый реквизит формы**: длина и многострочность - правило компоновки
([`form-layout-rules.md`](form-layout-rules.md), раздел 4); после правки сверять
`get_metadata_details(assignable=true)` у реквизита и поля.

**Удаление члена формы** (`delete_metadata` на адрес члена) убирает его из контейнера без
каскада: ссылки на него (команда у кнопки) остаются - сверить `get_metadata_details`.

---

## 6. Правки мимо EDT

Правка файла `Edit`/`Write`/скриптом - основной путь для BSL (дешевле по токенам). EDT замечает
такую правку сама, но с задержкой: на macOS 10-40 с (2026-11-04). Детерминированно -
**`revalidate_objects(projectName, objects=[...])`** по затронутым объектам: маркеры свежие
за ~6 с. Затем `get_project_errors`.

- `revalidate_objects` без `objects` - весь проект (долго); `clean_project` - полная пересборка
  с диска, отбрасывает несохранённое в модели - крайняя мера.
- `resync_to_disk` - обратное направление: модель → файлы `src/`, когда EDT сообщает «файл
  объекта не существует».
- Ручная правка `.form` - тот же путь: `revalidate_objects` по владельцу формы, затем
  `get_metadata_details` - модель совпала с файлом.
- Промежуточный файл с расширением `.bsl` вне структуры проекта не класть: EDT подхватит его
  как модуль и завалит замечания.

**Обновление базы сразу после правки мимо EDT может увезти не всё.** EDT грузит то, что
успела заметить к моменту вызова. Порядок: `revalidate_objects` по затронутым объектам →
`update_database`. Сомнение, всё ли доехало, снимает ещё один `update_database`: загрузил
что-то - предыдущий был неполным. На гейте проверять поведение, а не версию в базе.

**Что лежит в базе, а не в модели**, показывает выгрузка объектов из базы: живую файловую базу
держит агент конфигуратора EDT, поэтому `ibcmd config export` - с копии файла базы (на APFS
`cp -c`).

---

## 7. База, тесты, отладка

### `update_database`

`get_applications(projectName="<ХостПроект>")` → `applicationId` и `updateState`
(`INCREMENTAL_UPDATE_REQUIRED` и т.п.) → `update_database(projectName="<ХостПроект>",
applicationId)` без `confirm` - предпросмотр (вид обновления, что будет закрыто) → с
`confirm=true` - применение. Ответ синхронный: `stateAfter: "UPDATED"`. Грузит хост, проект
тестов и расширение - что изменилось. Перед применением закрывает клиенты 1С, запущенные этим EDT на
базе (`terminateRunningClients`).

- Итог - по ответу; в сомнении - `.metadata/.log`: строки «Загрузка ... в <база>» и
  `Completed tools/call: update_database ... outcome=ok`, без записей важности 4.
- `externalInfobaseChanges` по умолчанию `override`: правки базы мимо EDT (конфигуратор,
  `ibcmd`) затираются конфигурацией проекта.
- Открытый риск upstream [#712](https://github.com/DitriXNew/EDT-MCP/issues/712): долгая
  загрузка может прерваться по таймауту клиента. Обновления по изменениям (10-14 с) его не
  задевают; полное обновление (`fullUpdate`) - проверять по логу.

### YAxUnit

Основной путь - `python3 tools/yaxunit/yaxunit.py` ([`yaxunit-bootstrap.md`](yaxunit-bootstrap.md)
§6.1): отбор по диффу, сверка свежести базы, вердикт. `run_yaxunit_tests` - запасной и для
отладки тестов: `projectName="<ХостПроект>"`, `applicationId`, `modules=[...]`; короткий прогон возвращает отчёт
в том же вызове, длинный - `jobId` для `get_job_status`. Повторный старт с теми же аргументами
после завершения - новый прогон: опрашивать по `jobId`.

- `updateBeforeLaunch` (по умолчанию `true`) сам обновляет базу перед прогоном; после
  `update_database` - `false`.
- Сразу после обновления базы - «Project is building», ждать и повторять (§2).

### Отладчик

Проверено 2026-11-04: `set_breakpoint(projectName, modulePath, lineNumber)` →
`run_yaxunit_tests(debug=true)` (или `launch`) → `wait_for_break(timeout)` - полный стек с
`frameRef` → `get_variables(frameRef)` / `evaluate_expression(frameRef, expression)` →
`remove_breakpoint` → `resume`.

- **Первый `get_variables` может вернуть заглушку «(вычисление локальных переменных)»** -
  повторить, второй вызов отдаёт значения.
- `evaluate_expression` выполняет код в живой базе - только чтение значений, без
  изменяющих вызовов.
- Точку останова снимать до `resume`, иначе следующий прогон снова встанет.

---

## 8. Что проверено

| Дата | Версия | Что |
| --- | --- | --- |
| 2026-11-04 | 2.22.1, macOS | установка и `bundles.info`; диагностика против codepilot1c; иерархия вызовов; `validate_query` в расширении; сборка формы целиком инструментами; правки мимо EDT и `revalidate_objects`; `update_database`; YAxUnit; отладчик; удаление объекта |

Не проверено: Windows; `dcs`; права ролей; `rename_metadata_object`; `adopt_metadata_object`;
полное обновление базы; `get_template_screenshot`; профилирование.
