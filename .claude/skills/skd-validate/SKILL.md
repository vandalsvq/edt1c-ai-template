---
name: skd-validate
description: Валидация схемы компоновки данных 1С (СКД). Используй после создания или модификации СКД для проверки корректности
argument-hint: <TemplatePath> [-Detailed] [-MaxErrors 20]
allowed-tools:
  - Bash
  - Read
  - Glob
---
> **Источник:** [Nikolay-Shirokov/cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills) (MIT). Навык адаптирован под EDT-проект: рантайм Python, пути к файлам EDT. Нюансы и ограничения — [`docs/skd-mxl-toolkit.md`](../../../docs/skd-mxl-toolkit.md).

> **В EDT-проекте:** схема компоновки лежит в `<Объект>/Templates/<Имя>/Template.dcs` (в конфигураторном
> формате это `Template.xml` — содержимое то же). Сам макет навык не заводит: в EDT он регистрируется
> блоком `<templates>` в `.mdo` объекта-владельца — создавать через `edt_validate_request` →
> `create_metadata`/`update_metadata` или в EDT. После правки — `skd-validate` и `edt_diagnostics`.

# /skd-validate — валидация СКД (DataCompositionSchema)

Проверяет структурную корректность Template.dcs схемы компоновки данных. Выявляет ошибки формата, битые ссылки, дубликаты имён.

## Параметры

| Параметр     | Обяз. | Умолч. | Описание                                              |
|--------------|:-----:|---------|---------------------------------------------------------|
| TemplatePath | да    | —       | Путь к Template.dcs или каталогу макета                 |
| Detailed     | нет   | —       | Подробный вывод (все проверки, включая успешные)         |
| MaxErrors    | нет   | 20      | Остановиться после N ошибок                             |
| OutFile      | нет   | —       | Записать результат в файл                               |

## Команда

```bash
python3 .claude/skills/skd-validate/scripts/skd-validate.py -TemplatePath "src/МойОтчёт/Templates/ОсновнаяСхема"
python3 .claude/skills/skd-validate/scripts/skd-validate.py -TemplatePath "Catalogs/Номенклатура/Templates/СКД/Ext/Template.dcs"
```
