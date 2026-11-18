"""Нейтральный вид формы для импорта: оба формата XML читаются в него, модель строит один сборщик.

Свойства `Raw.props` - имена свойств модели, значения с уже подставленными умолчаниями
своего формата; None - «Авто» (свойство не задано).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Raw:
    kind: str                     # вид модели; "skip" - не рисуется; "?" - не распознан
    name: str
    props: dict = field(default_factory=dict)
    items: list = field(default_factory=list)
    bar: "Raw | None" = None      # командная панель таблицы
    source: str = ""              # вид в исходном XML - для отчета


@dataclass
class FormRaw:
    edt: bool
    title: str | None = None
    width: int = 0
    height: int = 0
    group: str = "Vertical"
    command_bar_location: str = "Auto"
    bar: Raw | None = None
    items: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)   # имя → metadata.Attribute
    main_attribute: str | None = None
    commands: dict = field(default_factory=dict)     # имя → {title, toolTip, action, picture, representation}
    excluded: set = field(default_factory=set)       # исключенные стандартные команды формы
    auto_title: bool = True                           # «Автозаголовок»
    show_title: bool = True                           # «Отображать заголовок»
    show_close: bool = True                           # «Отображать кнопку закрытия»
    # Командный интерфейс формы, командная панель: команда → (группа, индекс, видима пользователю)
    interface: dict = field(default_factory=dict)
    ext_kind: str | None = None


def font_props(face, height, style: dict):
    """Шрифт модели из прочитанного: имя, размер в пунктах (целый - целым), начертание `true`; пусто - None."""
    result = {}
    if face and face.strip():
        result["faceName"] = face.strip()
    try:
        size = float(height) if height else 0
    except ValueError:
        size = 0
    # Шрифт стиля пишет высоту 1 (БП: `Style.NormalTextFont`) - это не размер: меньше 6 пт не переносится
    if size >= 6:
        result["height"] = int(size) if size.is_integer() else size
    result.update({key: True for key, value in style.items() if value})
    return result or None
