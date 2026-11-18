"""Чтение `Form.xml` выгрузки конфигуратора в нейтральный вид импорта.

Выгрузка пишет только значения, отличные от умолчаний платформы, - а они другие, чем
у модели EDT: элемент без `<Visible>` виден, группа без `<ShowTitle>` показывает
заголовок, обычная группа без `<Group>` - «Горизонтальная, если возможно», без
`<Representation>` - «Слабое выделение». Умолчания выведены из корпуса выгрузок: значение,
которое ни разу не записано при всех остальных записанных, и есть умолчание. Одна и та же
форма из EDT и из выгрузки дает одну модель (тест на парах).
"""

from __future__ import annotations

from .importer_raw import FormRaw, Raw, font_props
from .metadata import V8, XR, XSI_TYPE, Attribute, clean_path, command_representation, designer_qualifiers, designer_text

LF = "{http://v8.1c.ru/8.3/xcf/logform}"

FIELDS = {
    "InputField", "CheckBoxField", "RadioButtonField", "LabelField", "PictureField", "HTMLDocumentField",
    "TextDocumentField", "FormattedDocumentField", "ChartField", "GanttChartField", "DendrogramField",
    "PlannerField", "CalendarField", "ProgressBarField", "TrackBarField", "GraphicalSchemaField",
    "GeographicalSchemaField", "PeriodField", "PDFDocumentField",
}
# Теги выгрузки, которые расходятся с именем вида платформы
RENAMED = {"SpreadSheetDocumentField": "SpreadsheetDocumentField"}
CONTAINERS = {"UsualGroup", "Pages", "Page", "ColumnGroup", "CommandBar", "Popup", "ButtonGroup", "Table"}
SKIPPED = {"ContextMenu", "ExtendedTooltip"}
# Дополнение таблицы, вынесенное в панель или форму (`ChildItems`): вид - по тегу
ADDITIONS = {"SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"}
CHECK_BOX_TYPES = {"Switcher": "Switch"}
RADIO_TYPES = {"RadioButtons": "RadioButton"}
# Умолчания платформы у полей-заглушек: выгрузка их не пишет, EDT пишет явно
# (сверено парами одних форм в EDT и в выгрузке)
DOCUMENT = {"width": 50, "height": 10, "horizontalStretch": True, "verticalStretch": True}
STUB_DEFAULTS = {
    "SpreadsheetDocumentField": DOCUMENT, "TextDocumentField": DOCUMENT, "HTMLDocumentField": DOCUMENT,
    "FormattedDocumentField": DOCUMENT, "ChartField": DOCUMENT, "GanttChartField": DOCUMENT,
    "DendrogramField": DOCUMENT, "PlannerField": DOCUMENT, "PDFDocumentField": DOCUMENT,
    "GraphicalSchemaField": {"horizontalStretch": True, "verticalStretch": True},
    "GeographicalSchemaField": {"horizontalStretch": True, "verticalStretch": True},
    "CalendarField": {"width": 16, "height": 9, "horizontalStretch": True, "verticalStretch": True},
    "PictureField": {"horizontalStretch": True, "verticalStretch": True},
    "ProgressBarField": {"width": 32, "height": 1, "horizontalStretch": True, "verticalStretch": False},
    "TrackBarField": {"height": 2, "horizontalStretch": True, "verticalStretch": False},
}


class Element:
    def __init__(self, node):
        self.node = node

    def text(self, tag, default=None):
        found = self.node.find(LF + tag)
        return found.text if found is not None and found.text is not None else default

    def flag(self, tag, default: bool) -> bool:
        value = self.text(tag)
        return default if value is None else value == "true"

    def option(self, tag):
        value = self.text(tag)
        return None if value is None else value == "true"

    def number(self, tag) -> int:
        try:
            return int(self.text(tag, "0"))
        except ValueError:
            return 0

    def local(self, tag):
        return designer_text(self.node.find(LF + tag))

    def picture(self):
        found = self.node.find(LF + "Picture")
        if found is None:
            return None
        return found.findtext(XR + "Ref") or None


def tag_of(node) -> str:
    return node.tag.replace(LF, "")


def read(root) -> FormRaw:
    form = Element(root)
    result = FormRaw(edt=False)
    result.title = form.local("Title")
    result.width = form.number("Width")
    result.height = form.number("Height")
    result.group = form.text("Group", "Vertical")
    result.command_bar_location = form.text("CommandBarLocation", "Auto")
    result.auto_title = form.flag("AutoTitle", True)
    result.show_title = form.flag("ShowTitle", True)
    result.show_close = form.flag("ShowCloseButton", True)
    bar = root.find(LF + "AutoCommandBar")
    result.bar = command_bar(bar) if bar is not None else None
    result.items = items(root)
    attributes = root.find(LF + "Attributes")
    for node in attributes.findall(LF + "Attribute") if attributes is not None else []:
        attribute = Attribute(node.get("name") or "", designer_text(node.find(LF + "Title")),
                              types_of(node.find(LF + "Type")),
                              fill_check=node.findtext(LF + "FillCheck") == "ShowError",
                              qualifiers=designer_qualifiers(node.find(LF + "Type")))
        columns = node.find(LF + "Columns")
        for column in columns.findall(LF + "Column") if columns is not None else []:
            attribute.columns[column.get("name") or ""] = Attribute(
                column.get("name") or "", designer_text(column.find(LF + "Title")), types_of(column.find(LF + "Type")),
                qualifiers=designer_qualifiers(column.find(LF + "Type")))
        # Дополнительные колонки формы у табличной части объекта: `<AdditionalColumns table="Объект.Товары">`
        for extra in columns.findall(LF + "AdditionalColumns") if columns is not None else []:
            owner, _, rest = (extra.get("table") or "").partition(".")
            if owner != attribute.name:
                continue
            # Путь - сам реквизит (набор записей): это его колонки
            (attribute.additional.setdefault(rest, {}) if rest else attribute.columns).update({
                    column.get("name") or "": Attribute(
                        column.get("name") or "", designer_text(column.find(LF + "Title")),
                        types_of(column.find(LF + "Type")), qualifiers=designer_qualifiers(column.find(LF + "Type")))
                    for column in extra.findall(LF + "Column")})
        settings = node.find(LF + "Settings")
        if settings is not None:
            attribute.main_table = settings.findtext(LF + "MainTable")
        result.attributes[attribute.name] = attribute
        if node.findtext(LF + "MainAttribute") == "true":
            result.main_attribute = attribute.name
    result.excluded = excluded(root)
    commands = root.find(LF + "Commands")
    for node in commands.findall(LF + "Command") if commands is not None else []:
        command = Element(node)
        result.commands[node.get("name") or ""] = {
            "title": command.local("Title"), "toolTip": command.local("ToolTip"),
            "action": (command.text("Action") or "").strip() or None, "picture": command.picture(),
            "representation": command_representation(command.text("Representation"))}
    # Командный интерфейс формы: `<Visible><xr:Common>false` - скрыта видимостью пользователя. Место в группе 0
    # выгрузка не пишет, EDT пишет `<index>0</index>` (письмо БСП): группа без места - 0
    for node in root.findall(f"{LF}CommandInterface/{LF}CommandBar/{LF}Item"):
        index = node.findtext(LF + "Index")
        group = node.findtext(LF + "CommandGroup")
        result.interface[node.findtext(LF + "Command") or ""] = (
            group, int(index) if index else 0 if group else None,
            node.findtext(f"{LF}Visible/{XR}Common") != "false")
    return result


def excluded(node) -> set:
    """Исключенные стандартные команды формы или таблицы: `<CommandSet><ExcludedCommand>`."""
    commands = node.find(LF + "CommandSet")
    if commands is None:
        return set()
    return {item.text for item in commands.findall(LF + "ExcludedCommand") if item.text}


def types_of(element):
    if element is None:
        return []
    return [item.text for item in element.findall(V8 + "Type") + element.findall(V8 + "TypeSet") if item.text]


def items(parent) -> list:
    children = parent.find(LF + "ChildItems")
    if children is None:
        return []
    return [item(node, parent) for node in children if isinstance(node.tag, str)]


def item(node, parent) -> Raw:
    tag = tag_of(node)
    name = node.get("name") or ""
    if tag in SKIPPED:
        return Raw("skip", name, source=tag)
    kind = "Addition" if tag in ADDITIONS else RENAMED.get(tag, tag)
    known = kind in FIELDS or kind in READERS or kind in RENAMED.values()
    raw = Raw(kind if known else "?", name, source=tag)
    element = Element(node)
    common(element, raw)
    reader = READERS.get(kind)
    if reader:
        reader(element, raw, parent)
    elif known:
        stretch(element, raw)
        for key, value in STUB_DEFAULTS.get(kind, {}).items():
            if not raw.props.get(key) and raw.props.get(key) is not False:
                raw.props[key] = value
    if kind in CONTAINERS:
        raw.items = items(node)
    return raw


def common(element: Element, raw: Raw):
    props = raw.props
    user = element.node.find(LF + "UserVisible")
    user_hidden = user is not None and user.findtext(XR + "Common") == "false"
    props["visible"] = element.flag("Visible", True)
    props["userVisible"] = not user_hidden
    props["enabled"] = element.flag("Enabled", True)
    props["title"] = element.local("Title")
    props["toolTip"] = element.local("ToolTip")
    props["toolTipRepresentation"] = element.text("ToolTipRepresentation", "Auto")
    tip = element.node.find(LF + "ExtendedTooltip")
    if tip is not None:
        title = tip.find(LF + "Title")
        props["extendedTooltip"] = designer_text(title)
        props["extendedTooltipFormatted"] = title is not None and title.get("formatted") == "true"
        props["extendedTooltipTextColor"] = tip.findtext(LF + "TextColor")
    path = clean_path(element.text("DataPath"))
    if path:
        props["dataPath"] = path
    props["width"] = element.number("Width")
    props["height"] = element.number("Height")
    props["readOnly"] = element.flag("ReadOnly", False)
    props["titleLocation"] = element.text("TitleLocation", "Auto")
    props["titleHeight"] = element.number("TitleHeight")
    props["showInHeader"] = element.flag("ShowInHeader", True)
    props["fixingInTable"] = element.text("FixingInTable", "None")
    props["groupHorizontalAlign"] = element.text("GroupHorizontalAlign", "Auto")
    props["groupVerticalAlign"] = element.text("GroupVerticalAlign", "Auto")
    props["textColor"] = element.text("TextColor")
    props["titleTextColor"] = element.text("TitleTextColor")
    props["backColor"] = element.text("BackColor")
    header = element.node.find(LF + "HeaderPicture")
    props["headerPicture"] = (header.findtext(XR + "Ref") or None) if header is not None else None
    column(element, raw)


def column(element: Element, raw: Raw):
    """Свойства колонки таблицы: умолчания платформы - положение в шапке «Лево», в подвале «Авто»,
    «Отображать в подвале» - Истина."""
    props = raw.props
    props["headerHorizontalAlign"] = element.text("HeaderHorizontalAlign", "Left")
    props["headerBackColor"] = element.text("HeaderBackColor")
    props["showInFooter"] = element.flag("ShowInFooter", True)
    props["footerPicture"] = picture_of(element.node.find(LF + "FooterPicture"))
    props["footerHorizontalAlign"] = element.text("FooterHorizontalAlign", "Auto")
    props["footerBackColor"] = element.text("FooterBackColor")
    props["footerTextColor"] = element.text("FooterTextColor")
    props["footerFont"] = font_of(element.node.find(LF + "FooterFont"))
    props["cellHyperlink"] = element.flag("CellHyperlink", False)
    props["autoCellHeight"] = element.flag("AutoCellHeight", False)


def usual_group(element: Element, raw: Raw, parent):
    props = raw.props
    props["group"] = element.text("Group", "HorizontalIfPossible")
    props["representation"] = element.text("Representation", "WeakSeparation")
    props["behavior"] = element.text("Behavior", "Auto")
    props["showTitle"] = element.flag("ShowTitle", True)
    props["collapsed"] = element.flag("Collapsed", False)
    props["throughAlign"] = element.text("ThroughAlign", "Auto")
    props["childItemsHorizontalAlign"] = element.text("HorizontalAlign", "Auto")
    props["childItemsVerticalAlign"] = element.text("VerticalAlign", "Auto")
    props["controlRepresentation"] = element.text("ControlRepresentation", "TitleHyperlink")
    props["backColor"] = element.text("BackColor")
    props["titleTextColor"] = element.text("TitleTextColor")
    stretch(element, raw)


def page(element: Element, raw: Raw, parent):
    raw.props["group"] = element.text("Group", "Vertical")
    raw.props["showTitle"] = element.flag("ShowTitle", True)
    raw.props["picture"] = element.picture()


def pages(element: Element, raw: Raw, parent):
    raw.props["pagesRepresentation"] = element.text("PagesRepresentation", "Auto")
    stretch(element, raw)


def column_group(element: Element, raw: Raw, parent):
    raw.props["group"] = element.text("Group", "Vertical")
    raw.props["showTitle"] = element.flag("ShowTitle", True)
    raw.props["showInHeader"] = element.flag("ShowInHeader", False)
    raw.props["headerHorizontalAlign"] = element.text("HeaderHorizontalAlign", "Left")


def command_group(element: Element, raw: Raw, parent):
    # У командной панели среди элементов положение - HorizontalLocation, у прочих - HorizontalAlign
    raw.props["horizontalAlign"] = element.text("HorizontalLocation") or element.text("HorizontalAlign", "Left")
    raw.props["picture"] = element.picture()
    raw.props["representation"] = element.text("Representation", "Auto")
    raw.props["commandSource"] = element.text("CommandSource")
    stretch(element, raw)


def input_field(element: Element, raw: Raw, parent):
    props = raw.props
    for tag in ("ChoiceButton", "ClearButton", "OpenButton", "DropListButton", "MultiLine", "PasswordMode"):
        props[tag[0].lower() + tag[1:]] = element.option(tag)
    props["markIncomplete"] = element.option("AutoMarkIncomplete")
    props["inputHint"] = element.local("InputHint")
    props["footerText"] = element.local("FooterText")
    props["format"] = element.local("EditFormat") or element.local("Format")
    props["choiceList"] = choice_list(element)
    props["autoMaxWidth"] = element.flag("AutoMaxWidth", True)
    props["maxWidth"] = element.number("MaxWidth")
    props["autoMaxHeight"] = element.flag("AutoMaxHeight", True)
    props["maxHeight"] = element.number("MaxHeight")
    props["listChoiceMode"] = element.flag("ListChoiceMode", False)
    props["choiceButtonRepresentation"] = element.text("ChoiceButtonRepresentation", "Auto")
    props["createButton"] = element.option("CreateButton")
    props["choiceButtonPicture"] = picture_of(element.node.find(LF + "ChoiceButtonPicture"))
    props["borderColor"] = element.text("BorderColor")
    props["font"] = font_of(element.node.find(LF + "Font"))
    props["titleFont"] = font_of(element.node.find(LF + "TitleFont"))
    stretch(element, raw)


def check_box(element: Element, raw: Raw, parent):
    kind = element.text("CheckBoxType", "Auto")
    raw.props["checkBoxType"] = CHECK_BOX_TYPES.get(kind, kind)
    field_look(element, raw)


def field_look(element: Element, raw: Raw):
    """Оформление полей надписи, флажка, картинки; «Авто максимальная высота» - умолчание
    Истина, как ширина. Рамка - `<Border width="1"><v8ui:style>Single</v8ui:style></Border>`."""
    props = raw.props
    props["font"] = font_of(element.node.find(LF + "Font"))
    props["titleFont"] = font_of(element.node.find(LF + "TitleFont"))
    props["borderColor"] = element.text("BorderColor")
    border = element.node.find(LF + "Border")
    style = None
    if border is not None:
        style = next((child.text for child in border.iter() if child.tag.rsplit("}", 1)[-1] == "style" and child.text), None)
    props["border"] = style
    props["autoMaxHeight"] = element.flag("AutoMaxHeight", True)
    props["maxWidth"] = element.number("MaxWidth")
    props["maxHeight"] = element.number("MaxHeight")
    props["horizontalAlign"] = element.text("HorizontalAlign", "Auto")
    props["verticalAlign"] = element.text("VerticalAlign", "Auto")


def picture_field(element: Element, raw: Raw, parent):
    raw.props["valuesPicture"] = picture_of(element.node.find(LF + "ValuesPicture"))
    raw.props["pictureSize"] = element.text("PictureSize")
    raw.props["hyperlink"] = element.flag("Hyperlink", False)
    raw.props["autoMaxWidth"] = element.flag("AutoMaxWidth", True)
    field_look(element, raw)
    stretch(element, raw)
    for key, value in STUB_DEFAULTS["PictureField"].items():
        if raw.props.get(key) is None:
            raw.props[key] = value


def radio(element: Element, raw: Raw, parent):
    kind = element.text("RadioButtonType", "Auto")
    raw.props["radioButtonType"] = RADIO_TYPES.get(kind, kind)
    raw.props["columnsCount"] = element.number("ColumnsCount")
    raw.props["choiceList"] = choice_list(element)


def label_field(element: Element, raw: Raw, parent):
    # Выгрузка пишет гиперссылку поля надписи как Hiperlink (так в платформе)
    raw.props["hyperlink"] = element.flag("Hiperlink", element.flag("Hyperlink", False))
    raw.props["footerText"] = element.local("FooterText")
    raw.props["autoMaxWidth"] = element.flag("AutoMaxWidth", True)
    field_look(element, raw)
    stretch(element, raw)


def table(element: Element, raw: Raw, parent):
    props = raw.props
    props["titleLocation"] = element.text("TitleLocation", "None")
    props["representation"] = element.text("Representation", "HierarchicalList")
    props["header"] = element.flag("Header", True)
    props["footer"] = element.flag("Footer", False)
    props["heightInTableRows"] = element.number("HeightInTableRows")
    props["commandBarLocation"] = element.text("CommandBarLocation", "Auto")
    props["searchStringLocation"] = element.text("SearchStringLocation", "Auto")
    props["changeRowSet"] = element.flag("ChangeRowSet", True)
    props["changeRowOrder"] = element.flag("ChangeRowOrder", True)
    props["viewStatusLocation"] = element.text("ViewStatusLocation", "Auto")
    props["searchControlLocation"] = element.text("SearchControlLocation", "Auto")
    props["multipleChoice"] = element.flag("MultipleChoice", False)
    props["rowPictureDataPath"] = clean_path(element.text("RowPictureDataPath"))
    props["rowsPicture"] = picture_of(element.node.find(LF + "RowsPicture"))
    props["horizontalLines"] = element.flag("HorizontalLines", True)
    props["verticalLines"] = element.flag("VerticalLines", True)
    props["useAlternationRowColor"] = element.flag("UseAlternationRowColor", False)
    props["borderColor"] = element.text("BorderColor")
    props["font"] = font_of(element.node.find(LF + "Font"))
    props["titleFont"] = font_of(element.node.find(LF + "TitleFont"))
    props["horizontalStretch"] = element.flag("HorizontalStretch", True)
    props["verticalStretch"] = element.flag("VerticalStretch", True)
    props["excluded"] = excluded(element.node)
    bar = element.node.find(LF + "AutoCommandBar")
    raw.bar = command_bar(bar) if bar is not None else None


def label(element: Element, raw: Raw, parent):
    title = element.node.find(LF + "Title")
    raw.props["formatted"] = title is not None and title.get("formatted") == "true"
    raw.props["hyperlink"] = element.flag("Hyperlink", False)
    stretch(element, raw)


def picture(element: Element, raw: Raw, parent):
    raw.props["picture"] = element.picture()
    raw.props["hyperlink"] = element.flag("Hyperlink", False)


def button(element: Element, raw: Raw, parent):
    props = raw.props
    in_bar = tag_of(parent) in ("AutoCommandBar", "CommandBar", "ButtonGroup", "Popup")
    props["buttonType"] = element.text("Type", "CommandBarButton" if in_bar else "UsualButton")
    props["commandName"] = element.text("CommandName")
    props["picture"] = element.picture()
    props["representation"] = element.text("Representation", "Auto")
    props["defaultButton"] = element.flag("DefaultButton", False)
    props["check"] = element.flag("Check", False)
    props["locationInCommandBar"] = element.text("LocationInCommandBar", "Auto")
    props["borderColor"] = element.text("BorderColor")
    props["shape"] = element.text("Shape")
    props["font"] = font_of(element.node.find(LF + "Font"))


def font_of(font):
    """Шрифт выгрузки (`<Font ref="style:..." faceName="Arial" height="10" bold="true" .../>`): имя и размер,
    если заданы, и начертание; шрифт стиля без своих имени и размера - только начертание."""
    if font is None:
        return None
    return font_props(font.get("faceName"), font.get("height"),
                      {key: font.get(key) == "true" for key in ("bold", "italic", "underline", "strikeout")})


def picture_of(node):
    """Картинка свойства выгрузки (`<ChoiceButtonPicture><xr:Ref>StdPicture.Имя</xr:Ref>`)."""
    if node is None:
        return None
    for child in node.iter():
        if child.tag.rsplit("}", 1)[-1] == "Ref" and child.text:
            return child.text.strip()
    return None


def addition(element: Element, raw: Raw, parent):
    raw.props["additionType"] = tag_of(element.node)
    # Источник дополнения в выгрузке - `<AdditionSource><Item>Таблица</Item><Type>...</Type></AdditionSource>`
    source = element.node.find(LF + "AdditionSource")
    item = source.findtext(LF + "Item") if source is not None else None
    raw.props["source"] = (item or "").strip() or None


def stretch(element: Element, raw: Raw):
    for tag in ("HorizontalStretch", "VerticalStretch"):
        raw.props[tag[0].lower() + tag[1:]] = element.option(tag)


# Вид значения пункта списка выбора: `xsi:type` выгрузки → вид импорта (`importer.choice_list`)
CHOICE_KINDS = {"string": "string", "decimal": "number", "boolean": "boolean", "DesignTimeRef": "ref", "dateTime": "date"}


def choice_list(element: Element):
    """Пункты списка выбора: (представление, вид значения, значение текстом)."""
    found = []
    choices = element.node.find(LF + "ChoiceList")
    for entry in choices.findall(XR + "Item") if choices is not None else []:
        value = entry.find(XR + "Value")
        if value is None:
            continue
        raw = value.find(LF + "Value")
        kind = (raw.get(XSI_TYPE) or "").split(":")[-1] if raw is not None else ""
        found.append((designer_text(value.find(LF + "Presentation")), CHOICE_KINDS.get(kind, "string"),
                      (raw.text if raw is not None else None) or ""))
    return found or None


def command_bar(node) -> Raw:
    element = Element(node)
    raw = Raw("AutoCommandBar", node.get("name") or "", source="AutoCommandBar")
    raw.props["autoFill"] = element.flag("Autofill", True)
    raw.props["horizontalAlign"] = element.text("HorizontalAlign", "Left")
    raw.props["visible"] = True
    raw.items = items(node)
    return raw


READERS = {
    "UsualGroup": usual_group, "Page": page, "Pages": pages, "ColumnGroup": column_group,
    "CommandBar": command_group, "Popup": command_group, "ButtonGroup": command_group,
    "InputField": input_field, "CheckBoxField": check_box, "RadioButtonField": radio,
    "LabelField": label_field, "Table": table, "LabelDecoration": label, "PictureDecoration": picture,
    "Button": button, "Addition": addition, "PictureField": picture_field,
}
