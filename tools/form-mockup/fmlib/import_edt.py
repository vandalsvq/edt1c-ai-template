"""Чтение `Form.form` EDT в нейтральный вид импорта.

EDT пишет в файл только значения, отличные от умолчания своей модели (`Form.xcore`):
у булева свойства умолчание - Ложь, у перечисления - первое значение, у `Boolean`
(с заглавной) отсутствие - «Авто». Поэтому здесь умолчания модели EDT, а не
платформы: группа без `<group>` - горизонтальная, панель закладок без
`<pagesRepresentation>` - «Нет», элемент без `<visible>` - скрыт.
"""

from __future__ import annotations

from . import colors
from .importer_raw import FormRaw, Raw, font_props
from .metadata import XSI_TYPE, Attribute, clean_path, command_representation, edt_qualifiers, edt_text, edt_types

GROUP_KINDS = {
    "ButtonGroup": "ButtonGroup", "ColumnGroup": "ColumnGroup", "CommandBar": "CommandBar",
    "UsualGroup": "UsualGroup", "Popup": "Popup", "Page": "Page", "Pages": "Pages",
}
CHECK_BOX_TYPES = {"Switcher": "Switch"}
RADIO_TYPES = {"RadioButtons": "RadioButton"}
SKIPPED = {}


class Element:
    """Свойства элемента EDT: сам элемент и его `extInfo` - одно пространство имен свойств."""

    def __init__(self, node):
        self.node = node
        self.ext = node.find("extInfo")

    def child(self, tag):
        found = self.node.find(tag)
        if found is None and self.ext is not None:
            found = self.ext.find(tag)
        return found

    def text(self, tag, default=None):
        found = self.child(tag)
        return found.text if found is not None and found.text is not None else default

    def flag(self, tag) -> bool:
        """`boolean` модели EDT: нет в файле - Ложь."""
        return self.text(tag) == "true"

    def option(self, tag):
        """`Boolean` модели EDT: нет в файле - «Авто» (None)."""
        value = self.text(tag)
        return None if value is None else value == "true"

    def number(self, tag) -> int:
        try:
            return int(self.text(tag, "0"))
        except ValueError:
            return 0

    def local(self, tag):
        """Многоязычная строка: в элементе или в `extInfo`."""
        value = edt_text(self.node, tag)
        if value is None and self.ext is not None:
            value = edt_text(self.ext, tag)
        return value

    def picture(self):
        found = self.child("picture")
        if found is None:
            return None
        return found.findtext("picture") or None


def read(root) -> FormRaw:
    form = Element(root)
    result = FormRaw(edt=True)
    result.title = form.local("title")
    result.width = form.number("width")
    result.height = form.number("height")
    result.group = form.text("group", "Horizontal")
    result.command_bar_location = form.text("commandBarLocation", "Auto")
    # boolean модели EDT: нет в файле - Ложь (БП: «Отображать заголовок» и кнопку закрытия пишет явно)
    result.auto_title = form.flag("autoTitle")
    result.show_title = form.flag("showTitle")
    result.show_close = form.flag("showCloseButton")
    bar = root.find("autoCommandBar")
    result.bar = command_bar(bar) if bar is not None else None
    result.items = items(root)
    result.ext_kind = (root.find("extInfo").get(XSI_TYPE) if root.find("extInfo") is not None else None)
    for node in root.findall("attributes"):
        attribute = Attribute(node.findtext("name") or "", edt_text(node, "title"), edt_types(node.find("valueType")),
                              fill_check=node.findtext("fillChecking") == "ShowError",
                              qualifiers=edt_qualifiers(node.find("valueType")))
        for column in node.findall("columns"):
            attribute.columns[column.findtext("name") or ""] = Attribute(
                column.findtext("name") or "", edt_text(column, "title"), edt_types(column.find("valueType")),
                qualifiers=edt_qualifiers(column.find("valueType")))
        # Дополнительные колонки формы у табличной части объекта: `Объект.Товары` → колонки
        for extra in node.findall("additionalColumns"):
            table = ".".join(item.text for item in extra.findall("tablePath/segments") if item.text)
            owner, _, rest = table.partition(".")
            if owner != attribute.name:
                continue
            # Путь - сам реквизит (набор записей): это его колонки
            (attribute.additional.setdefault(rest, {}) if rest else attribute.columns).update({
                    column.findtext("name") or "": Attribute(
                        column.findtext("name") or "", edt_text(column, "title"), edt_types(column.find("valueType")),
                        qualifiers=edt_qualifiers(column.find("valueType")))
                    for column in extra.findall("columns")})
        ext = node.find("extInfo")
        if ext is not None:
            attribute.main_table = ext.findtext("mainTable")
        result.attributes[attribute.name] = attribute
        if node.findtext("main") == "true":
            result.main_attribute = attribute.name
    result.excluded = {node.text for node in root.findall("excludedCommands") if node.text}
    for node in root.findall("formCommands"):
        command = Element(node)
        result.commands[node.findtext("name") or ""] = {
            "title": command.local("title"), "toolTip": command.local("toolTip"),
            "action": node.findtext("action/handler/name"), "picture": command.picture(),
            "representation": command_representation(node.findtext("representation"))}
    # Командный интерфейс формы: `<userVisible/>` без `common` = true - скрыта видимостью пользователя
    for node in root.findall("commandInterface/commandBar/cmiFragmentRecord"):
        index = node.findtext("index")
        result.interface[node.findtext("command") or ""] = (
            node.findtext("group"), int(index) if index else None,
            node.find("userVisible") is None or node.findtext("userVisible/common") == "true")
    return result


def items(parent) -> list:
    return [item(node) for node in parent.findall("items")]


def item(node) -> Raw:
    element = Element(node)
    xsi = node.get(XSI_TYPE) or ""
    kind_text = node.findtext("type")
    name = node.findtext("name") or ""
    if xsi in SKIPPED:
        return Raw("skip", name, source=SKIPPED[xsi])
    if xsi == "form:FormGroup":
        kind = GROUP_KINDS.get(kind_text or "ButtonGroup")
    elif xsi == "form:FormField":
        kind = kind_text if kind_text and kind_text != "None" else None
    elif xsi == "form:Table":
        kind = "Table"
    elif xsi == "form:Decoration":
        kind = "LabelDecoration" if kind_text == "Label" else "PictureDecoration"
    elif xsi == "form:Button":
        kind = "Button"
    elif xsi == "form:Addition":
        kind = "Addition"
    else:
        kind = None
    source = f"{xsi.replace('form:', '')}/{kind_text}" if kind_text else xsi.replace("form:", "")
    raw = Raw(kind or "?", name, source=source)
    common(element, raw)
    reader = READERS.get(kind)
    if reader:
        reader(element, raw)
    elif kind:
        stub(element, raw)
    if kind in ("UsualGroup", "Page", "Pages", "ColumnGroup", "CommandBar", "Popup", "ButtonGroup", "Table"):
        raw.items = items(node)
    return raw


def common(element: Element, raw: Raw):
    props = raw.props
    user = element.node.find("userVisible")
    user_hidden = user is not None and user.findtext("common") != "true"
    props["visible"] = element.flag("visible")
    props["userVisible"] = not user_hidden
    props["enabled"] = element.text("enabled") != "false"
    props["title"] = element.local("title")
    props["toolTip"] = element.local("toolTip")
    props["toolTipRepresentation"] = element.text("toolTipRepresentation", "Auto")
    tip = element.node.find("extendedTooltip")
    if tip is not None:
        props["extendedTooltip"] = edt_text(tip, "title")
        props["extendedTooltipFormatted"] = tip.findtext("formatted") == "true"
        props["extendedTooltipTextColor"] = colors.edt_value(tip.find("textColor"))
    path = element.node.find("dataPath")
    if path is not None:
        props["dataPath"] = clean_path(".".join(segment.text for segment in path.findall("segments") if segment.text))
    props["width"] = element.number("width")
    props["height"] = element.number("height")
    props["readOnly"] = element.flag("readOnly")
    props["titleLocation"] = element.text("titleLocation", "Auto")
    props["titleHeight"] = element.number("titleHeight")
    props["showInHeader"] = element.flag("showInHeader")
    props["fixingInTable"] = element.text("fixingInTable", "None")
    props["groupHorizontalAlign"] = element.text("groupHorizontalAlign", "Auto")
    props["groupVerticalAlign"] = element.text("groupVerticalAlign", "Auto")
    props["textColor"] = colors.edt_value(element.child("textColor"))
    props["titleTextColor"] = colors.edt_value(element.child("titleTextColor"))
    props["backColor"] = colors.edt_value(element.child("backColor"))
    header = element.child("headerPicture")
    props["headerPicture"] = (header.findtext("picture") or None) if header is not None else None
    column(element, raw)


def column(element: Element, raw: Raw):
    """Свойства колонки таблицы: шапка, подвал, ячейки. EDT пишет «Горизонтальное положение в
    шапке» у каждого поля (`Left`), нет в файле - «Авто»; «Отображать в подвале» - boolean: нет в файле - Ложь."""
    props = raw.props
    props["headerHorizontalAlign"] = element.text("headerHorizontalAlign", "Auto")
    props["headerBackColor"] = colors.edt_value(element.child("headerBackColor"))
    props["showInFooter"] = element.flag("showInFooter")
    props["footerPicture"] = picture_of(element.child("footerPicture"))
    props["footerHorizontalAlign"] = element.text("footerHorizontalAlign", "Auto")
    props["footerBackColor"] = colors.edt_value(element.child("footerBackColor"))
    props["footerTextColor"] = colors.edt_value(element.child("footerTextColor"))
    props["footerFont"] = edt_font(element.child("footerFont"))
    props["cellHyperlink"] = element.flag("cellHyperlink")
    props["autoCellHeight"] = element.flag("autoCellHeight")


def usual_group(element: Element, raw: Raw):
    props = raw.props
    props["group"] = element.text("group", "Horizontal")
    props["representation"] = element.text("representation", "None")
    props["behavior"] = element.text("behavior", "Usual")
    props["showTitle"] = element.flag("showTitle")
    props["collapsed"] = element.flag("collapsed")
    props["throughAlign"] = element.text("throughAlign", "Use")
    props["childItemsHorizontalAlign"] = element.text("horizontalAlign", "Auto")
    props["childItemsVerticalAlign"] = element.text("verticalAlign", "Auto")
    props["controlRepresentation"] = element.text("controlRepresentation", "TitleHyperlink")
    props["backColor"] = colors.edt_value(element.child("backColor"))
    props["titleTextColor"] = colors.edt_value(element.child("titleTextColor"))
    stretch(element, raw, nullable=True)


def page(element: Element, raw: Raw):
    raw.props["group"] = element.text("group", "Horizontal")
    raw.props["showTitle"] = element.flag("showTitle")
    raw.props["picture"] = element.picture()


def pages(element: Element, raw: Raw):
    raw.props["pagesRepresentation"] = element.text("pagesRepresentation", "None")
    stretch(element, raw, nullable=True)


def column_group(element: Element, raw: Raw):
    raw.props["group"] = element.text("group", "Horizontal")
    raw.props["showTitle"] = element.flag("showTitle")
    raw.props["showInHeader"] = element.flag("showInHeader")
    raw.props["headerHorizontalAlign"] = element.text("headerHorizontalAlign", "Left")


def command_group(element: Element, raw: Raw):
    raw.props["horizontalAlign"] = element.text("horizontalAlign", "Auto")
    raw.props["picture"] = element.picture()
    # Первое значение ButtonRepresentation в модели EDT - «Текст»: «Авто» EDT пишет явно;
    # у группы кнопок свое перечисление (Авто, Обычное, Компактное) - первое «Авто»
    raw.props["representation"] = element.text("representation", "Auto" if raw.kind == "ButtonGroup" else "Text")
    raw.props["commandSource"] = element.text("commandSource")
    stretch(element, raw, nullable=True)


def input_field(element: Element, raw: Raw):
    props = raw.props
    for tag in ("choiceButton", "clearButton", "openButton", "dropListButton", "multiLine", "passwordMode"):
        props[tag] = element.option(tag)
    props["markIncomplete"] = element.option("autoMarkIncomplete")
    props["inputHint"] = element.local("inputHint")
    props["footerText"] = element.local("footerText")
    props["format"] = element.local("editFormat") or element.local("format")
    props["choiceList"] = choice_list(element)
    # «Авто максимальная ширина» - boolean модели EDT: нет в файле - Ложь (поле тянется без предела)
    props["autoMaxWidth"] = element.flag("autoMaxWidth")
    props["maxWidth"] = element.number("maxWidth")
    # Предел высоты многострочного поля: «авто» - как ширина, нет в файле - Ложь
    props["autoMaxHeight"] = element.flag("autoMaxHeight")
    props["maxHeight"] = element.number("maxHeight")
    props["listChoiceMode"] = element.flag("listChoiceMode")
    props["choiceButtonRepresentation"] = element.text("choiceButtonRepresentation", "Auto")
    props["createButton"] = element.option("createButton")
    props["choiceButtonPicture"] = picture_of(element.child("choiceButtonPicture"))
    props["borderColor"] = colors.edt_value(element.child("borderColor"))
    props["font"] = edt_font(element.child("font"))
    props["titleFont"] = edt_font(element.child("titleFont"))
    stretch(element, raw, nullable=True)


def check_box(element: Element, raw: Raw):
    kind = element.text("checkBoxType", "Auto")
    raw.props["checkBoxType"] = CHECK_BOX_TYPES.get(kind, kind)
    field_look(element, raw)


def field_look(element: Element, raw: Raw):
    """Оформление полей надписи, флажка, картинки: шрифты, рамка, положение, максимумы.
    «Авто максимальная высота» - boolean модели EDT, как ширина: нет в файле - Ложь."""
    props = raw.props
    props["font"] = edt_font(element.child("font"))
    props["titleFont"] = edt_font(element.child("titleFont"))
    props["borderColor"] = colors.edt_value(element.child("borderColor"))
    # Стиль рамки «Без рамки» - умолчание перечисления в модели EDT: `<border>` без `<style>` (EDT не пишет его
    # явно ни разу: БП - 417 рамок без стиля, другая конфигурация - 28, в выгрузке у них `WithoutBorder`)
    border = element.child("border")
    props["border"] = (border.findtext("style") or "WithoutBorder") if border is not None else None
    props["autoMaxHeight"] = element.flag("autoMaxHeight")
    props["maxWidth"] = element.number("maxWidth")
    props["maxHeight"] = element.number("maxHeight")
    props["horizontalAlign"] = element.text("horizontalAlign", "Auto")
    props["verticalAlign"] = element.text("verticalAlign", "Auto")


def picture_field(element: Element, raw: Raw):
    raw.props["valuesPicture"] = picture_of(element.child("valuesPicture"))
    raw.props["pictureSize"] = element.text("pictureSize")
    raw.props["hyperlink"] = element.flag("hyperlink")
    raw.props["autoMaxWidth"] = element.flag("autoMaxWidth")
    field_look(element, raw)
    stretch(element, raw, nullable=False)


def radio(element: Element, raw: Raw):
    kind = element.text("radioButtonsType", "Auto")
    raw.props["radioButtonType"] = RADIO_TYPES.get(kind, kind)
    raw.props["columnsCount"] = element.number("columnsCount")
    raw.props["choiceList"] = choice_list(element)


def label_field(element: Element, raw: Raw):
    raw.props["hyperlink"] = element.flag("hyperlink")
    raw.props["footerText"] = element.local("footerText")
    # Как у поля ввода: нет в файле - Ложь, поле тянется (по снимку формы с полем подсказок запроса)
    raw.props["autoMaxWidth"] = element.flag("autoMaxWidth")
    field_look(element, raw)
    stretch(element, raw, nullable=True)


def table(element: Element, raw: Raw):
    props = raw.props
    props["representation"] = element.text("representation", "List")
    props["header"] = element.flag("header")
    props["footer"] = element.flag("footer")
    props["heightInTableRows"] = element.number("heightInTableRows")
    props["commandBarLocation"] = element.text("commandBarLocation", "Auto")
    # «Изменять состав / порядок строк» - boolean модели EDT: нет в файле - Ложь
    props["changeRowSet"] = element.flag("changeRowSet")
    props["changeRowOrder"] = element.flag("changeRowOrder")
    props["searchStringLocation"] = element.text("searchStringLocation", "Auto")
    props["viewStatusLocation"] = element.text("viewStatusLocation", "Auto")
    props["searchControlLocation"] = element.text("searchControlLocation", "Auto")
    props["multipleChoice"] = element.flag("multipleChoice")
    path = element.node.find("rowPictureDataPath")
    if path is not None:
        props["rowPictureDataPath"] = clean_path(".".join(item.text for item in path.findall("segments") if item.text))
    props["rowsPicture"] = picture_of(element.child("rowsPicture"))
    # Линии и чередование - boolean модели EDT: нет в файле - Ложь (в БП «Да» записано явно)
    props["horizontalLines"] = element.flag("horizontalLines")
    props["verticalLines"] = element.flag("verticalLines")
    props["useAlternationRowColor"] = element.flag("useAlternationRowColor")
    props["borderColor"] = colors.edt_value(element.child("borderColor"))
    props["font"] = edt_font(element.child("font"))
    props["titleFont"] = edt_font(element.child("titleFont"))
    stretch(element, raw, nullable=False)
    props["excluded"] = {node.text for node in element.node.findall("excludedCommands") if node.text}
    bar = element.node.find("autoCommandBar")
    raw.bar = command_bar(bar) if bar is not None else None


def label(element: Element, raw: Raw):
    raw.props["formatted"] = element.flag("formatted")
    raw.props["hyperlink"] = element.flag("hyperlink")
    stretch(element, raw, nullable=True)


def picture(element: Element, raw: Raw):
    raw.props["picture"] = element.picture()
    raw.props["hyperlink"] = element.flag("hyperlink")


def button(element: Element, raw: Raw):
    props = raw.props
    props["buttonType"] = element.text("type", "CommandBarButton")
    props["commandName"] = element.text("commandName")
    props["picture"] = element.picture()
    props["representation"] = element.text("representation", "Text")
    props["defaultButton"] = element.flag("defaultButton")
    props["check"] = element.flag("check")
    props["locationInCommandBar"] = element.text("locationInCommandBar", "Auto")
    props["borderColor"] = colors.edt_value(element.child("borderColor"))
    props["shape"] = element.text("shape")
    props["font"] = edt_font(element.child("font"))


def picture_of(node):
    """Картинка свойства EDT (`<choiceButtonPicture><picture>StdPicture.Имя</picture>`)."""
    return (node.findtext("picture") or None) if node is not None else None


def edt_font(node):
    """Шрифт: имя и размер, если заданы (абсолютный шрифт `FontDef` или шрифт стиля со своими), и начертание.
    Шрифт стиля без своих имени и размера - только начертание; масштаб (`scale`) не переносится."""
    if node is None:
        return None
    return font_props(node.findtext("faceName"), node.findtext("height"),
                      {key: node.findtext(key) == "true" for key in ("bold", "italic", "underline", "strikeout")})


def addition(element: Element, raw: Raw):
    # Дополнение таблицы, вынесенное в командную панель или форму: строка поиска, управление поиском,
    # состояние просмотра; вид по умолчанию - строка поиска
    raw.props["additionType"] = element.text("type", "SearchStringAddition")
    raw.props["source"] = element.text("source")


def stub(element: Element, raw: Raw):
    # У полей документов, картинки, диаграмм растягивание - `boolean`: нет в файле - Ложь
    stretch(element, raw, nullable=False)


def stretch(element: Element, raw: Raw, nullable: bool):
    for tag in ("horizontalStretch", "verticalStretch"):
        raw.props[tag] = element.option(tag) if nullable else element.flag(tag)


# Вид значения пункта списка выбора: `core:<Вид>Value` → вид импорта (`importer.choice_list`)
CHOICE_KINDS = {"StringValue": "string", "NumberValue": "number", "BooleanValue": "boolean", "ReferenceValue": "ref",
                "DateValue": "date"}
# Системное перечисление: первое значение EDT не пишет (пустой тег), выгрузка - пишет (вид плана счетов БСП)
CHOICE_DEFAULTS = {"AccountTypeValue": "Active", "AccumulationRecordTypeValue": "Receipt",
                   "AccountingRecordTypeValue": "Debit"}


def choice_list(element: Element):
    """Пункты списка выбора: (представление, вид значения, значение текстом). Булево Ложь EDT пишет пустым тегом."""
    found = []
    for entry in element.ext.findall("choiceList") if element.ext is not None else []:
        value = entry.find("value")
        kind = (value.get(XSI_TYPE) or "").split(":")[-1] if value is not None else ""
        text = (value.findtext("value") if value is not None else None) or CHOICE_DEFAULTS.get(kind, "")
        found.append((edt_text(entry, "presentation"), CHOICE_KINDS.get(kind, "string"), text))
    return found or None


def command_bar(node) -> Raw:
    element = Element(node)
    raw = Raw("AutoCommandBar", node.findtext("name") or "", source="AutoCommandBar")
    raw.props["autoFill"] = element.flag("autoFill")
    raw.props["horizontalAlign"] = element.text("horizontalAlign", "Auto")
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
