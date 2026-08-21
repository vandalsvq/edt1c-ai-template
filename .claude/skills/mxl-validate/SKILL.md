---
name: mxl-validate
description: Валидация макета табличного документа (MXL). Используй после создания или модификации макета для проверки корректности
argument-hint: <TemplatePath> [-Detailed] [-MaxErrors 20]
allowed-tools:
  - Bash
  - Read
  - Glob
---
> **Источник:** [Nikolay-Shirokov/cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills) (MIT). Навык адаптирован под EDT-проект: рантайм Python, пути к файлам EDT. Нюансы и ограничения — [`docs/skd-mxl-toolkit.md`](../../../docs/skd-mxl-toolkit.md).

> **В EDT-проекте:** табличный документ лежит в `<Объект>/Templates/<Имя>/Template.mxlx` (в конфигураторном
> формате это `Template.xml` — содержимое то же). Сам макет навык не заводит: в EDT он регистрируется
> блоком `<templates>` в `.mdo` объекта-владельца — создавать через `edt_validate_request` →
> `create_metadata`/`update_metadata` или в EDT. После правки — `mxl-validate` и `edt_diagnostics`.

# /mxl-validate — валидация макета табличного документа (MXL)

Проверяет Template.mxlx на структурные ошибки: индексы, ссылки на палитры, диапазоны именованных областей и объединений, согласованность ячеек-полей ввода.

## Параметры

| Параметр      | Обяз. | Умолч. | Описание                                 |
|---------------|:-----:|---------|--------------------------------------------|
| TemplatePath  | да    | —       | Путь к макету (директория или Template.mxlx) |
| Detailed      | нет   | —       | Подробный вывод (все проверки, включая успешные) |
| MaxErrors     | нет   | 20      | Остановиться после N ошибок                |

## Команда

```bash
python3 .claude/skills/mxl-validate/scripts/mxl-validate.py -TemplatePath "Catalogs/Номенклатура/Templates/Макет"
python3 .claude/skills/mxl-validate/scripts/mxl-validate.py -TemplatePath "src/МояОбработка/Templates/ПечатнаяФорма"
```

