/* Рендерер макета формы 1С: модель → DOM в виде «Такси».
   Данные - в <script id="fm-data">: { model, dict, state }. Состояние страницы (закладки,
   свернутые группы, переключатели) можно задать в адресе: #static&expand&names&hidden&page=Панель:Закладка;
   act=tab:Панель:Закладка;toggle:Группа - щелчки после отрисовки (дымовой прогон).
   С прежней версией (data.before, data.diff) - режимы «Правки / Стало / Было» (mode=diff|after|before),
   подсветка правок слоем поверх формы и список правок; nodiff - без подсветки; act=mode:after;diff:3 -
   смена режима и щелчок по правке 3 в списке.
   После раскладки итог - в <pre id="fm-result">: замечания, ошибки, размер, закладки.
   Страница конструктора (data.editor) сама не рисует: editor.js перерисовывает форму по новой
   модели через window.FMRender, закладки и свернутые группы помнятся по именам. */
(function () {
  "use strict";

  var errors = [];
  window.addEventListener("error", function (event) {
    errors.push(String(event.message || event));
  });

  var DATA = JSON.parse(document.getElementById("fm-data").textContent);
  var MODEL = DATA.model;
  var DICT = DATA.dict || { types: {} };
  var FORM = MODEL.form || {};
  var DIFF = DATA.diff || null;          // правки против прежней версии: { tree, changes }
  // Формы режимов: «стало», «было» и объединенное дерево правок (удаленные и тени перенесенных на старых местах)
  var FORMS = { after: FORM, before: DATA.before ? DATA.before.form : null, diff: DIFF ? DIFF.tree : null };
  var PICTURES = MODEL.pictures || {};   // картинки конфигурации из импорта: имя → data URI
  var STYLES = MODEL.styles || {};       // цвета стиля: имя элемента стиля → #RRGGBB
  var EDITOR = !!DATA.editor;            // страница конструктора: рисует editor.js

  var CSS = getComputedStyle(document.documentElement);
  var CH = parseFloat(CSS.getPropertyValue("--ch")) || 10;
  var BUTTON = parseFloat(CSS.getPropertyValue("--input-btn")) || 21;
  var TABLE_MAX = 1400;      // вклад таблицы в ширину окна без заданной ширины формы, px
  var SOFT_MAX = 40;         // строка и ссылка растягиваются до 40 символов (калибровка по витрине)
  var SOFT_MIN = 3;          // и сжимаются в узком окне до 3 символов
  // Строка не длиннее 10 символов не растягивается («Код» 9 на закладке «Ширины» витрины своей ширины
  // при пустом месте справа, строка 12 - до 40; порог между 9 и 12 - гипотеза)
  var SHORT_STRING = 10;

  // Кнопки автозаполнения панели формы: имя стандартной команды и «по умолчанию»
  var STD_FORM_COMMANDS = {
    DocumentObjectForm: [["PostAndClose", true], ["Write"], ["Post"]],
    CatalogObjectForm: [["WriteAndClose", true], ["Write"]],
    ListForm: [],
    ChoiceForm: [],
    DataProcessorForm: []
  };
  // Значок кнопки автозаполнения панели таблицы (своя пиктограмма или стандартная картинка из выгрузки): у явной
  // кнопки той же команды без своей картинки - он же
  var STD_TABLE_ICONS = { MoveUp: "up", MoveDown: "down", Copy: "copy", Change: "edit", SetDeletionMark: "del" };

  // Стандартные команды в меню «Еще»: заголовок и стандартная картинка (снимки 1С). Сочетания
  // клавиш - как в 1С для Windows (на снимках с macOS: Cmd вместо Ctrl, Option вместо Alt)
  var MORE_COMMANDS = {
    Add: ["Добавить", "CreateListItem"], Copy: ["Скопировать", "CloneListItem"], Change: ["Изменить", "Change"],
    Delete: ["Удалить", "Delete"], EndEdit: ["Закончить редактирование", "EndEdit"],
    FindByCurrentValue: ["Найти по текущему значению"], Find: ["Расширенный поиск", "Find"],
    CancelSearch: ["Отменить поиск", "CancelSearch"], SearchHistory: ["История поиска"],
    MoveUp: ["Переместить вверх", "MoveUp"], MoveDown: ["Переместить вниз", "MoveDown"],
    SortListAsc: ["Сортировать по возрастанию", "SortListAsc"], SortListDesc: ["Сортировать по убыванию", "SortListDesc"],
    OutputList: ["Вывести список...", "OutputList"], Create: ["Создать"], Choose: ["Выбрать"],
    SetDeletionMark: ["Пометить на удаление", "MarkToDelete"],
    WriteAndClose: ["Записать и закрыть", "WriteAndClose"], Write: ["Записать", "Write"],
    PostAndClose: ["Провести и закрыть"], Post: ["Провести", "Post"], UndoPosting: ["Отмена проведения", "UndoPosting"],
    Reread: ["Перечитать", "Reread"], ShowInList: ["Показать в списке", "ShowInList"],
    ChangeHistory: ["История изменений", "DataHistory"], CustomizeForm: ["Изменить форму...", "CustomizeForm"],
    Help: ["Справка", "Help"]
  };
  // У команд формы объекта свои картинка и заголовок
  var MORE_FORM_COMMANDS = { Copy: ["Скопировать", "CloneObject"], SetDeletionMark: ["Пометить на удаление / Снять пометку", "MarkToDelete"] };
  var TABLE_KEYS = { Add: "Ins", Copy: "F9", Change: "F2", Delete: "Del", EndEdit: "Shift+F2", FindByCurrentValue: "Ctrl+Alt+F",
    Find: "Alt+F", CancelSearch: "Ctrl+Q", MoveUp: "Ctrl+Shift+Up", MoveDown: "Ctrl+Shift+Down", Create: "Ins" };
  var FORM_KEYS = { Write: "Ctrl+S", Help: "F1" };
  // Стандартный набор «Еще» таблицы по секциям между чертами (снимки «Объекты метаданных», «Поля набора»,
  // «Поля запроса», «Соединения»): без «Изменять состав строк» нет добавления, копирования и удаления, без
  // «Изменять порядок строк» - перемещения и сортировки; снятые в «Составе команд» - `excludedCommands`
  var MORE_TABLE = [["Add", "Copy", "Change", "Delete", "EndEdit", "FindByCurrentValue", "Find", "CancelSearch"],
    ["MoveUp", "MoveDown"], ["SortListAsc", "SortListDesc", "OutputList"]];
  var ROW_SET = ["Add", "Copy", "Delete"];
  var ROW_ORDER = ["MoveUp", "MoveDown", "SortListAsc", "SortListDesc"];
  // У динамического списка - пока только команды панели (снимка меню списка нет)
  var MORE_LIST = ["Create", "Copy", "Change", "SetDeletionMark"];
  // Форма объекта: команды панели и «только в Еще» (снимок формы элемента справочника); «Изменить форму...»
  // и «Справка» - в конце меню любой формы
  var FORM_MORE = ["Reread", "Copy", "SetDeletionMark", "Delete", "ShowInList", "ChangeHistory"];
  var MORE_FORM = {
    DocumentObjectForm: ["PostAndClose", "Write", "Post", "UndoPosting"].concat(FORM_MORE),
    CatalogObjectForm: ["WriteAndClose", "Write"].concat(FORM_MORE)
  };

  // Дата - по дате со временем (закладка «Ширины» витрины: 179 px с календарем); состав даты модель не хранит
  var DEFAULT_WIDTH = { string: 20, number: 12, date: 15, boolean: 6, ref: 24 };
  // Нижняя граница ширины текста подсказки снизу и сверху у флажка и переключателя, символов (допущение)
  var TIP_MIN_WIDTH = 40;
  // Ширина колонки по умолчанию (калибровка: ссылка 30, число 17 символов)
  var COLUMN_WIDTH = { string: 20, number: 17, date: 12, boolean: 6, ref: 30, lineNumber: 4 };
  // Колонка-флажок и колонка-картинка без своей ширины - 35 px и не растягиваются (владелец; снимки
  // 1С: 33-35 px)
  var NARROW_COLUMN = 2.5;

  // Стандартный реквизит «Номер строки» табличной части: колонка фиксированной ширины
  function lineNumber(leaf) {
    return /\.(LineNumber|НомерСтроки)$/.test(String(leaf.dataPath || ""));
  }

  var ICONS = {
    search: '<svg viewBox="0 0 16 16"><circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="#2f5fa8" stroke-width="1.6"/><path d="M10 10l4 4" stroke="#2f5fa8" stroke-width="2"/></svg>',
    calendar: '<svg viewBox="0 0 16 16"><rect x="1.5" y="2.5" width="13" height="12" rx="1" fill="none" stroke="currentColor"/><path d="M1.5 6h13M5 1v3M11 1v3" stroke="currentColor"/></svg>',
    open: '<svg viewBox="0 0 16 16"><rect x="1.5" y="3.5" width="10" height="10" fill="none" stroke="currentColor"/><path d="M8 1.5h6.5V8M14.5 1.5 7 9" fill="none" stroke="currentColor"/></svg>',
    check: '<svg viewBox="0 0 16 16"><path d="M2.5 8.5 6.5 12.5 15 1" fill="none" stroke="#009646" stroke-width="2.4"/></svg>',
    save: '<svg viewBox="0 0 16 16"><path d="M2.5 2.5h9l2 2v9h-11z" fill="#dfe9f5" stroke="#3d6ea8"/><rect x="5" y="2.5" width="5.5" height="3.5" fill="#fff" stroke="#3d6ea8"/><rect x="4.5" y="9" width="7" height="4.5" fill="#fff" stroke="#3d6ea8"/></svg>',
    print: '<svg viewBox="0 0 16 16"><path d="M4 6V1.5h8V6" fill="none" stroke="currentColor"/><rect x="1.5" y="6" width="13" height="6" rx="1" fill="none" stroke="currentColor"/><rect x="4.5" y="10" width="7" height="4.5" fill="#fff" stroke="currentColor"/></svg>',
    picture: '<svg viewBox="0 0 24 24"><rect x="2.5" y="4.5" width="19" height="15" rx="1" fill="none" stroke="currentColor"/><circle cx="8" cy="9.5" r="2" fill="none" stroke="currentColor"/><path d="M3 18l6-6 4 4 3-3 5 5" fill="none" stroke="currentColor"/></svg>',
    unknownPicture: '<svg viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" stroke-dasharray="2 1.5"/></svg>',
    command: '<svg viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" rx="2" fill="none" stroke="currentColor"/><path d="M5.5 8h5M8 5.5v5" stroke="currentColor"/></svg>',
    copy: '<svg viewBox="0 0 16 16"><rect x="4.5" y="4.5" width="9" height="10" fill="none" stroke="currentColor"/><path d="M2.5 11.5v-10h8" fill="none" stroke="currentColor"/></svg>',
    edit: '<svg viewBox="0 0 16 16"><path d="M3 13l1-3.5L11 2.5l2.5 2.5L6.5 12z" fill="none" stroke="currentColor"/></svg>',
    del: '<svg viewBox="0 0 16 16"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="#c0392b" stroke-width="1.6"/></svg>',
    up: '<svg viewBox="0 0 16 16"><path d="M8 1.5 14 8H10.5v6.5h-5V8H2z" fill="#49b2ed" stroke="#2f7fae" stroke-width=".8"/></svg>',
    down: '<svg viewBox="0 0 16 16"><path d="M8 14.5 14 8H10.5V1.5h-5V8H2z" fill="#49b2ed" stroke="#2f7fae" stroke-width=".8"/></svg>',
    calc: '<svg viewBox="0 0 16 16"><rect x="2.5" y="1.5" width="11" height="13" rx="1" fill="none" stroke="currentColor"/><rect x="4.5" y="3.5" width="7" height="2.5" fill="currentColor"/><path d="M5 8.5h1M7.5 8.5h1M10 8.5h1M5 10.5h1M7.5 10.5h1M10 10.5h1M5 12.5h1M7.5 12.5h1M10 12.5h1" stroke="currentColor"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="#333" stroke-width="1.6"/><circle cx="12" cy="7.5" r="1.4" fill="#333"/><path d="M10 10.5h2.6V17M10 17h5" fill="none" stroke="#333" stroke-width="1.8"/></svg>',
    warning: '<svg viewBox="0 0 24 24"><path d="M12 3 22 20H2z" fill="none" stroke="#c98a00" stroke-width="1.6"/><path d="M12 9v6M12 17v1.5" stroke="#c98a00" stroke-width="1.8"/></svg>',
    expanded: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke="#999"/><path d="M3.5 6h5" stroke="#999"/></svg>',
    back: '<svg viewBox="0 0 18 18"><path d="M11 3.5 5.5 9l5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
    forward: '<svg viewBox="0 0 18 18"><path d="M7 3.5 12.5 9 7 14.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
    star: '<svg viewBox="0 0 18 18"><path d="M9 2l2.1 4.4 4.8.6-3.5 3.3.9 4.7L9 12.7 4.7 15l.9-4.7L2.1 7l4.8-.6z" fill="none" stroke="currentColor"/></svg>',
    link: '<svg viewBox="0 0 18 18"><path d="M7.5 10.5l3-3M6 8.5 4.2 10.3a2.4 2.4 0 0 0 3.5 3.5L9.5 12M12 9.5l1.8-1.8a2.4 2.4 0 0 0-3.5-3.5L8.5 6" fill="none" stroke="currentColor" stroke-width="1.3"/></svg>',
    menu: '<svg viewBox="0 0 18 18"><circle cx="9" cy="4" r="1.3" fill="currentColor"/><circle cx="9" cy="9" r="1.3" fill="currentColor"/><circle cx="9" cy="14" r="1.3" fill="currentColor"/></svg>',
    close: '<svg viewBox="0 0 18 18"><path d="M4.5 4.5l9 9M13.5 4.5l-9 9" stroke="currentColor" stroke-width="1.4"/></svg>',
    post: '<svg viewBox="0 0 16 16"><path d="M2.5 1.5h7l3 3v10h-10z" fill="#fff8d6" stroke="#8a7a3a"/><path d="M4.5 5.5h5M4.5 7.5h5" stroke="#8a7a3a"/><path d="M6 11l2.5 2.5L15 7" fill="none" stroke="#2e9b3a" stroke-width="2"/></svg>',
    history: '<svg viewBox="0 0 16 16"><path d="M2 12.5l.8-3L9.5 2.8l2.2 2.2L5 11.7z" fill="#8bc34a" stroke="#4a7a1c" stroke-width=".8"/><circle cx="11" cy="11" r="4" fill="#fff" stroke="#555"/><path d="M11 8.8V11h1.8" fill="none" stroke="#555"/></svg>',
    stub: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="1" fill="none" stroke="currentColor"/><path d="M3.5 9h17M3.5 14.5h17M9 3.5v17M14.5 3.5v17" stroke="currentColor"/></svg>'
  };
  var STD_PICTURES = { "StdPicture.Print": "print", "StdPicture.Write": "save", "StdPicture.Copy": "copy", "StdPicture.Change": "edit",
    "StdPicture.Delete": "del", "StdPicture.MarkToDelete": "del", "StdPicture.MoveUp": "up", "StdPicture.MoveDown": "down",
    "StdPicture.Information": "info", "StdPicture.Warning": "warning", "StdPicture.DialogInformation": "info",
    "StdPicture.DialogExclamation": "warning", "StdPicture.DataHistory": "history",
    "StdPicture.CloneListItem": "copy", "StdPicture.CloneObject": "copy",
    "StdPicture.Post": "post" };

  // Состояние страницы

  var state = parseHash();
  var currentPage = {};      // имя панели → имя закладки
  var pressed = {};          // имя кнопки с пометкой → { model: пометка в модели, on: нажата } - щелчок на макете
  var formWidened = 0;       // ширина формы меньше минимальной: ширина окна по содержимому, px
  var collapsed = {};        // имя группы → свернута
  var rendering = { showHidden: state.hidden, showUser: !state.nouser };
  var mode = DIFF ? (FORMS[state.mode] ? state.mode : "diff") : "after";
  var showDiff = !!DIFF && !state.nodiff;
  var showNotes = state.notes;  // номера примечаний: адрес `notes`, конструктор - всегда
  var activeChange = 0;      // номер правки, выбранной в списке
  FORM = FORMS[mode];

  function parseHash() {
    var defaults = (DATA.state && DATA.state.pages) || {};
    var result = { "static": false, expand: false, names: false, hidden: false, nouser: false, nodiff: false, notes: false, mode: "",
      pages: Object.assign({}, defaults), act: [] };
    location.hash.replace(/^#/, "").split("&").forEach(function (part) {
      if (!part) return;
      var pair = decodeURIComponent(part).split("=");
      if (pair[0] === "page" && pair[1]) {
        pair[1].split(";").forEach(function (item) {
          var names = item.split(":");
          if (names.length === 2) result.pages[names[0]] = names[1];
        });
      } else if (pair[0] === "mode") {
        result.mode = pair[1] || "";
      } else if (pair[0] === "act" && pair[1]) {
        result.act = pair.slice(1).join("=").split(";").filter(Boolean);
      } else if (pair[0] in result) {
        result[pair[0]] = true;
      }
    });
    return result;
  }

  // Помощники

  function h(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  // Значки стандартных команд поля табличного документа (в стандартных картинках платформы их нет):
  // свои пиктограммы по снимку 1С
  var SHEET_ICONS = {
    PasteFromClipboard: '<svg viewBox="0 0 16 16"><rect x="3.5" y="2.5" width="9" height="12" rx="1" fill="#f4f4f4" stroke="#666"/><rect x="6" y="1.5" width="4" height="2.5" fill="#fff" stroke="#666"/><path d="M5.5 7.5h5M5.5 10h5" stroke="#3d6ea8"/></svg>',
    CopyToClipboard: '<svg viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="7" height="9" fill="#fff" stroke="#666"/><rect x="6.5" y="5.5" width="7" height="9" fill="#fff" stroke="#3d6ea8"/></svg>',
    Undo: '<svg viewBox="0 0 16 16"><path d="M5 4 2 7l3 3" fill="none" stroke="#2f7fd0" stroke-width="1.6"/><path d="M2.5 7H10a3.5 3.5 0 0 1 0 7H7" fill="none" stroke="#2f7fd0" stroke-width="1.6"/></svg>',
    Redo: '<svg viewBox="0 0 16 16"><path d="M11 4l3 3-3 3" fill="none" stroke="#2f7fd0" stroke-width="1.6"/><path d="M13.5 7H6a3.5 3.5 0 0 0 0 7h3" fill="none" stroke="#2f7fd0" stroke-width="1.6"/></svg>',
    SetName: '<svg viewBox="0 0 16 16"><rect x="1.5" y="3.5" width="13" height="9" fill="#fff" stroke="#888"/><rect x="3.5" y="5.5" width="5" height="5" fill="#9fc2e8" stroke="#3d6ea8"/><path d="M10 8h3M11.5 6.5v3" stroke="#2e9b3a" stroke-width="1.4"/></svg>',
    RemoveName: '<svg viewBox="0 0 16 16"><rect x="1.5" y="3.5" width="13" height="9" fill="#fff" stroke="#888"/><rect x="3.5" y="5.5" width="5" height="5" fill="#9fc2e8" stroke="#3d6ea8"/><path d="M10 6.5l3 3M13 6.5l-3 3" stroke="#c0392b" stroke-width="1.3"/></svg>',
    PageSetup: '<svg viewBox="0 0 16 16"><path d="M8 1.5v13M1.5 8h13" stroke="#2f7fd0" stroke-width="1.3"/><path d="M8 1.5 6 3.5M8 1.5l2 2M8 14.5l-2-2M8 14.5l2-2M1.5 8l2-2M1.5 8l2 2M14.5 8l-2-2M14.5 8l-2 2" fill="none" stroke="#2f7fd0" stroke-width="1.3"/></svg>',
    Font: '<svg viewBox="0 0 16 16"><text x="8" y="13" font-family="Arial" font-size="13" text-anchor="middle" fill="#333">A</text></svg>',
    Bold: '<svg viewBox="0 0 16 16"><text x="8" y="13" font-family="Arial" font-size="13" font-weight="bold" text-anchor="middle" fill="#222">Ж</text></svg>',
    Italic: '<svg viewBox="0 0 16 16"><text x="8" y="13" font-family="Arial" font-size="13" font-style="italic" text-anchor="middle" fill="#222">К</text></svg>',
    Underline: '<svg viewBox="0 0 16 16"><text x="8" y="12" font-family="Arial" font-size="12" text-anchor="middle" fill="#222">Ч</text><path d="M3.5 14.5h9" stroke="#222"/></svg>',
    AlignLeft: '<svg viewBox="0 0 16 16"><path d="M2 3.5h12M2 6.5h8M2 9.5h12M2 12.5h8" stroke="#444"/></svg>',
    AlignCenter: '<svg viewBox="0 0 16 16"><path d="M2 3.5h12M4 6.5h8M2 9.5h12M4 12.5h8" stroke="#444"/></svg>',
    AlignRight: '<svg viewBox="0 0 16 16"><path d="M2 3.5h12M6 6.5h8M2 9.5h12M6 12.5h8" stroke="#444"/></svg>',
    AlignJustify: '<svg viewBox="0 0 16 16"><path d="M2 3.5h12M2 6.5h12M2 9.5h12M2 12.5h12" stroke="#444"/></svg>',
    BackColor: '<svg viewBox="0 0 16 16"><path d="M3 8 7.5 3.5 12 8l-4.5 4.5z" fill="#fff" stroke="#333"/><path d="M12.5 9.5c0 1 1.5 1 1.5 0l-.75-1.5z" fill="#2f7fd0"/><rect x="2" y="13" width="12" height="2.5" fill="#d0021b"/></svg>',
    TextColor: '<svg viewBox="0 0 16 16"><text x="8" y="11" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle" fill="#2f5fa8">A</text><rect x="2" y="13" width="12" height="2.5" fill="#d0021b"/></svg>',
    BorderColor: '<svg viewBox="0 0 16 16"><path d="M4 11.5 11 4.5l1.5 1.5-7 7H4z" fill="#f2c94c" stroke="#555"/><rect x="2" y="13.5" width="12" height="2" fill="#2f7fd0"/></svg>',
    Merge: '<svg viewBox="0 0 16 16"><rect x="1.5" y="2.5" width="13" height="11" fill="#fff" stroke="#666"/><path d="M1.5 6.5h13M1.5 9.5h13M5.5 2.5v4M10.5 2.5v4M5.5 9.5v4M10.5 9.5v4" stroke="#aaa"/><path d="M4 8h8" stroke="#2f7fd0" stroke-width="1.3"/></svg>'
  };

  // Значки границ: пунктирная сетка ячейки 2×2, нужные линии - сплошные (толстые - шире)
  function borderIcon(lines, width) {
    var path = { left: "M2.5 2v12", top: "M2 2.5h12", right: "M13.5 2v12", bottom: "M2 13.5h12",
      inside: "M8 2v12M2 8h12" };
    var grid = '<path d="M2.5 2v12M13.5 2v12M2 2.5h12M2 13.5h12M8 2v12M2 8h12" stroke="#9a9a9a" stroke-dasharray="1 1"/>';
    var solid = lines.map(function (line) { return path[line]; }).join("");
    return '<svg viewBox="0 0 16 16">' + grid + (solid ? '<path d="' + solid + '" stroke="#222" stroke-width="' + (width || 1) + '"/>' : "") + "</svg>";
  }
  var BORDERS = {
    BorderLeft: [["left"]], BorderTop: [["top"]], BorderRight: [["right"]], BorderBottom: [["bottom"]],
    BorderAll: [["left", "top", "right", "bottom", "inside"]], BorderOutline: [["left", "top", "right", "bottom"]],
    BorderInside: [["inside"]], ThickBorderOutline: [["left", "top", "right", "bottom"], 2],
    ThickBorderTop: [["top"], 2], ThickBorderBottom: [["bottom"], 2], BorderNone: [[]]
  };
  Object.keys(BORDERS).forEach(function (name) { SHEET_ICONS[name] = borderIcon(BORDERS[name][0], BORDERS[name][1]); });

  function sheetIcon(commandName) {
    var found = /\.StandardCommand\.(\w+)$/.exec(commandName || "");
    if (!found || !SHEET_ICONS[found[1]]) return null;
    var span = h("span", "fm-icon");
    span.innerHTML = SHEET_ICONS[found[1]];
    return span.firstChild;
  }

  function icon(name) {
    var span = h("span", "fm-icon");
    span.innerHTML = ICONS[name] || ICONS.command;
    return span.firstChild;
  }

  // Значок, который рендерер рисует сам (кнопка поля, стандартная кнопка таблицы): стандартная картинка
  // из выгрузки платформы, если импорт положил ее в модель, иначе - своя пиктограмма или текст
  var OWN_ICON_PICTURES = { up: "MoveUp", down: "MoveDown", copy: "CloneListItem", edit: "Change", del: "MarkToDelete",
    calendar: "InputFieldCalendar", calc: "InputFieldCalculator", open: "InputFieldOpen" };
  function platformIcon(own) {
    var name = "StdPicture." + (OWN_ICON_PICTURES[own] || own);
    return PICTURES[name] ? pictureNode(name) : icon(own);
  }
  function platformText(stdName, text) {
    return PICTURES["StdPicture." + stdName] ? pictureNode("StdPicture." + stdName) : text;
  }

  // Картинка по имени: из конфигурации или выгрузки платформы (импорт положил в модель), стандартная
  // без выгрузки - своей пиктограммой
  function pictureNode(name) {
    if (PICTURES[name]) {
      var image = h("img", "fm-img");
      image.src = PICTURES[name];
      image.alt = "";
      return image;
    }
    return STD_PICTURES[name] ? icon(STD_PICTURES[name]) : null;
  }

  // Картинка значений поля картинки: коллекция - горизонтальная полоса квадратных ячеек со стороной в
  // высоту картинки (БП: у всех 79 коллекций с манифестом ячейка равна высоте), значение поля выбирает ячейку: число -
  // по номеру с нуля, Ложь - первая, Истина - вторая, без значения - первая; номера за полосой нет - поле пустое.
  // Ширина не кратна высоте - не коллекция, картинка целиком
  function valueIndex(value) {
    if (value === true || /^(true|истина|да)$/i.test(String(value))) return 1;
    var number = parseInt(value, 10);
    return isNaN(number) || number < 0 ? 0 : number;
  }

  function valuesPictureNode(name, value) {
    if (!PICTURES[name]) return pictureOrStub(name);
    var cell = h("span", "fm-values-picture");
    var image = h("img", "fm-img");
    image.alt = "";
    cell.appendChild(image);
    var index = valueIndex(value);
    image.addEventListener("load", function () {
      var height = image.naturalHeight;
      var width = image.naturalWidth;
      if (!height || width % height) {
        cell.classList.add("fm-values-whole");
        return;
      }
      cell.style.width = cell.style.height = px(height);
      if (index >= width / height) cell.style.visibility = "hidden";
      else image.style.marginLeft = px(-index * height);
    });
    image.src = PICTURES[name];
    return cell;
  }

  // Картинка без пиктограммы в макете (стандартная вне набора, общей нет в исходниках) - пунктирный
  // квадрат с именем в подсказке, а не похожий чужой значок; рендер называет ее в замечаниях
  var missingPictures = {};
  function pictureOrStub(name) {
    var found = pictureNode(name);
    if (found) return found;
    missingPictures[name] = true;
    var stub = icon("unknownPicture");
    var wrap = h("span", "fm-picture-stub");
    wrap.title = name;
    wrap.appendChild(stub);
    return wrap;
  }

  function px(value) { return Math.round(value) + "px"; }


  // Ширина элемента в символах модели; у поля ввода к ней прибавляются кнопки
  function chars(value) { return value * CH + 10; }

  function splitName(name) {
    // То же правило, что metadata.split_name: аббревиатура перед словом отделяется (`ИННКонтрагента`)
    var words = String(name || "").replace(/([а-яёa-z0-9])([А-ЯЁA-Z])/g, "$1 $2")
      .replace(/([А-ЯЁA-Z])([А-ЯЁA-Z][а-яёa-z])/g, "$1 $2").split(" ");
    return words.map(function (word, index) {
      if (index === 0 || word.length > 1 && /^[А-ЯЁA-Z0-9]+$/.test(word)) return word;
      return word.toLowerCase();
    }).join(" ");
  }

  // Путь к данным по `attributes` и `types` модели: заголовок элемента без своего заголовка, дерево
  // выбора пути и проверки конструктора (`FMRender.pathTools`)
  var COLLECTION_TYPES = { ValueTable: true, ValueTree: true, ValueList: true, DynamicList: true };
  var TYPE_ROLE = /^([A-Za-z]+?)(Ref|Object|RecordManager|RecordSet)\.([^.]+)$/;
  // Стандартные реквизиты: в пути - английское имя (как пишет EDT), в дереве - русское, как в конфигураторе
  var STANDARD_NAMES = {
    Ref: "Ссылка", Code: "Код", Description: "Наименование", Owner: "Владелец", Parent: "Родитель", IsFolder: "ЭтоГруппа",
    DeletionMark: "ПометкаУдаления", Predefined: "Предопределенный", PredefinedDataName: "ИмяПредопределенныхДанных",
    Number: "Номер", Date: "Дата", Posted: "Проведен", LineNumber: "НомерСтроки", Period: "Период",
    Recorder: "Регистратор", Active: "Активность", Started: "Стартован", Completed: "Завершен", Executed: "Выполнена",
    BusinessProcess: "БизнесПроцесс", RoutePoint: "ТочкаМаршрута", DefaultPicture: "СтандартнаяКартинка"
  };
  // Заголовки стандартных реквизитов, которые не равны имени по словам (`STANDARD` импорта)
  var STANDARD_TITLES = { LineNumber: "N", НомерСтроки: "N", BusinessProcess: "Бизнес-процесс" };

  function typeNames(node) {
    var value = node && node.valueType;
    if (typeof value === "string") return [value];
    return Array.isArray(value) ? value.filter(function (name) { return typeof name === "string"; }) : [];
  }

  // `CatalogRef.Контрагенты` → { key: "Catalog.Контрагенты", role: "Ref" }; перечисление и прочее - null
  function typeOf(name) {
    var found = TYPE_ROLE.exec(name);
    return found && found[1] !== "Enum" ? { key: found[1] + "." + found[3], role: found[2] } : null;
  }

  function isCollection(node) {
    return Array.isArray(node.columns) || !!node.collection || typeNames(node).some(function (name) {
      return COLLECTION_TYPES[name] || (typeOf(name) || {}).role === "RecordSet";
    });
  }

  // Проход пути по модели `model`: узел пути - { name, node, root, rel, path }
  function pathTools(model) {
    function described(key) {
      var types = model && model.types && typeof model.types === "object" ? model.types : {};
      return types[key] && typeof types[key] === "object" ? types[key] : null;
    }

    // Подчиненные узла пути: колонки, дополнительные колонки формы у табличной части, реквизиты и табличные части
    // описанного типа, у динамического списка - реквизиты основной таблицы
    function members(entry) {
      var node = entry.node;
      var list = [];
      var seen = {};
      function add(child, collection) {
        if (!child || typeof child.name !== "string" || seen[child.name]) return;
        seen[child.name] = true;
        list.push({ name: child.name, node: collection ? Object.assign({}, child, { collection: true }) : child,
          root: entry.root || child, rel: entry.root ? (entry.rel ? entry.rel + "." : "") + child.name : "",
          path: entry.path ? entry.path + "." + child.name : child.name });
      }
      // У табличной части первой - НомерСтроки, как в конфигураторе
      if (node.collection && entry.rel) add({ name: "LineNumber", valueType: "Number" });
      (Array.isArray(node.columns) ? node.columns : []).forEach(function (column) { add(column); });
      var extra = entry.root && entry.root.additionalColumns && entry.root.additionalColumns[entry.rel];
      if (entry.rel && Array.isArray(extra) && isCollection(node)) extra.forEach(function (column) { add(column); });
      var names = typeNames(node);
      // У динамического списка первой - СтандартнаяКартинка: самый частый путь картинки строки (БП - 1422 из 2367)
      if (names.indexOf("DynamicList") >= 0) add({ name: "DefaultPicture", valueType: "Picture" });
      if (names.indexOf("DynamicList") >= 0 && typeof node.mainTable === "string") {
        ((described(node.mainTable) || {}).attributes || []).forEach(function (child) { add(child); });
      }
      names.forEach(function (name) {
        var type = typeOf(name);
        var found = type && described(type.key);
        if (!found) return;
        (found.attributes || []).forEach(function (child) { add(child); });
        (found.tabularSections || []).forEach(function (child) { add(child, true); });
      });
      return list;
    }

    function roots() {
      var list = model && Array.isArray(model.attributes) ? model.attributes : [];
      return list.filter(function (node) { return node && typeof node.name === "string"; }).map(function (node) {
        return { name: node.name, node: node, root: node, rel: "", path: node.name };
      });
    }

    function find(entries, path) {
      var parts = path.split(".");
      var current = null;
      var list = entries;
      for (var i = 0; i < parts.length; i++) {
        current = list.filter(function (entry) { return entry.name === parts[i]; })[0];
        if (!current) return null;
        list = members(current);
      }
      return current;
    }

    return { described: described, members: members, roots: roots, find: find };
  }

  // Заголовок по пути к данным, как у импорта (`field_title`): заголовок реквизита по пути, иначе последнее имя пути
  // по словам (стандартный реквизит - русским именем); без пути - undefined
  function pathTitle(model, path) {
    if (typeof path !== "string" || !path) return undefined;
    var tools = pathTools(model);
    var entry = tools.find(tools.roots(), path);
    if (entry && typeof entry.node.title === "string" && entry.node.title) return entry.node.title;
    var last = path.split(".").pop();
    return STANDARD_TITLES[last] || splitName(STANDARD_NAMES[last] || last);
  }

  // Заголовок элемента, как его видит пользователь: свой, у кнопки - от команды, у элемента с путем к данным - от
  // реквизита по пути, иначе имя по словам без префикса владельца. `model` - модель конструктора,
  // если она опередила нарисованную
  function titleOf(node, prefix, model) {
    model = model || MODEL;
    if (typeof node.title === "string") return node.title;
    var byCommand = commandTitle(node, model);
    if (byCommand !== undefined) return byCommand;
    var byPath = pathTitle(model, node.dataPath);
    if (byPath !== undefined) return byPath;
    var name = node.name || "";
    if (prefix && name.indexOf(prefix) === 0 && name.length > prefix.length) name = name.slice(prefix.length);
    return splitName(name);
  }

  // Заголовок кнопки по ее команде: команда формы - заголовок из `commands`, без него - имя команды
  // по словам; стандартная команда формы или таблицы - заголовок платформы, как в меню «Еще»; общая - имя по словам.
  // Не кнопка или команда не задана - undefined
  function commandTitle(node, model) {
    var name = node && node.type === "Button" && typeof node.commandName === "string" ? node.commandName : "";
    if (!name) return undefined;
    var own = formCommand(node, model);
    if (own) return typeof own.title === "string" ? own.title : splitName(own.name);
    var standard = /^Form\.(Item\.[^.]+\.)?StandardCommand\.(\w+)$/.exec(name);
    if (standard) return standardTitle(standard[2], !standard[1]);
    var other = /^(?:Form\.Command|CommonCommand)\.(.+)$/.exec(name);
    return other ? splitName(other[1]) : undefined;
  }

  // Заголовок стандартной команды: у формы объекта свои («Скопировать», «Пометить на удаление / Снять пометку»)
  function standardTitle(command, onForm) {
    var own = onForm && MORE_FORM_COMMANDS[command] || MORE_COMMANDS[command];
    return own ? own[0] : command === "Close" ? "Закрыть" : command;
  }

  // Команда формы кнопки (`commandName: "Form.Command.<Имя>"`) из `commands` модели
  function formCommand(node, model) {
    model = model || MODEL;
    var found = node && node.type === "Button" && /^Form\.Command\.(.+)$/.exec(node.commandName || "");
    var commands = found && Array.isArray(model.commands) ? model.commands : [];
    for (var i = 0; i < commands.length; i++) {
      if (commands[i] && commands[i].name === found[1]) return commands[i];
    }
    return null;
  }

  // Кнопка, как ее рисовать: картинка и отображение, которых у нее нет (отображение «Авто»), - от команды формы;
  // у стандартной команды таблицы - значок ее кнопки автозаполнения, в модель он не пишется
  function faceOf(node) {
    var command = formCommand(node);
    if (!command) {
      var picture = node && node.type === "Button" && !node.picture ? standardPicture(node.commandName) : "";
      return picture ? Object.assign({}, node, { picture: picture }) : node;
    }
    var face = Object.assign({}, node);
    if (!face.picture && command.picture) face.picture = command.picture;
    if ((!face.representation || face.representation === "Auto") && command.representation) {
      face.representation = command.representation;
    }
    return face;
  }

  // Картинка стандартной команды таблицы, как у кнопки автозаполнения: имя стандартной картинки платформы; у команды
  // без значка на панели («Добавить», «Записать») - пусто
  function standardPicture(commandName) {
    var found = /^Form\.Item\.[^.]+\.StandardCommand\.(\w+)$/.exec(commandName || "");
    var own = found && STD_TABLE_ICONS[found[1]];
    return own ? "StdPicture." + (OWN_ICON_PICTURES[own] || own) : "";
  }

  // Унаследованная картинка кнопки (панель свойств конструктора): от команды формы или стандартной команды
  function inheritedPicture(node, model) {
    if (!node || node.type !== "Button") return "";
    var command = formCommand(node, model);
    if (command) return typeof command.picture === "string" ? command.picture : "";
    return standardPicture(node.commandName);
  }

  function kindName(kind) { return (DICT.types && DICT.types[kind]) || kind; }

  // Скрытое: visible = false - по «Показать скрытые»; снятая видимость пользователя (в 1С
  // включается в «Изменить форму») видна по умолчанию, галочка «Показать скрытые пользователем»
  // ее убирает (владелец, 31.10.2026); в адресе - #nouser
  function isShown(node) {
    if (rendering.showHidden) return true;
    return node.visible !== false && (node.userVisible !== false || rendering.showUser);
  }

  function shownItems(node) {
    return (Array.isArray(node.items) ? node.items : []).filter(function (item) {
      return item && typeof item === "object" && isShown(item);
    });
  }

  // Элементы панели на ней самой: кнопки «только в Еще» (положение `InAdditionalSubmenu`) - только в меню
  function barItems(node) {
    return shownItems(node).filter(function (item) { return item.locationInCommandBar !== "InAdditionalSubmenu"; });
  }

  function looksNumber(value) { return /^-?[\d\s ]+([.,]\d+)?%?$/.test(String(value).trim()); }

  function truthy(value) { return value === true || value === 1 || /^(true|1|да|истина)$/i.test(String(value)); }

  // Пометка элемента: имя, вид, подсказка, скрытость, бирка имени
  function mark(node, element, tagHost) {
    element.classList.add("fm-item");
    element.dataset.name = node.name || "";
    element.dataset.kind = node.type || "Form";
    if (node.visible === false) element.classList.add("fm-hidden");
    if (node.userVisible === false) element.classList.add("fm-user-hidden");
    if (node.enabled === false) element.classList.add("fm-disabled");
    var host = tagHost || element;
    if (host !== element) {
      host.dataset.name = element.dataset.name;
      host.dataset.kind = element.dataset.kind;
      host.classList.add("fm-item");
    }
    if (node.type) host.appendChild(h("span", "fm-name-tag", node.name || ""));
    return element;
  }

  function clip(element, what) {
    element.classList.add("fm-clip");
    element.dataset.clip = what;
    return element;
  }

  // Элементы

  // horizontal: элементы идут в строку. Между соседними растягиваемыми элементами 1С рисует
  // разделитель пунктиром: в строке - между группами, в столбец - между растягиваемыми по высоте
  function renderItems(container, items, ctx, horizontal) {
    var previous = null;
    var weighted = horizontal && !!FORM.width && weightedRow(items);
    items.forEach(function (item) {
      if (!item || typeof item !== "object" || !isShown(item)) return;
      var element = renderItem(item, ctx);
      if (!element) return;
      if (weighted && widthStretchable(item)) {
        element.style.width = "";
        // Основа пропорциональна весу: доли при растягивании те же, а без места строка не уже суммы ширин
        // (Ф-8 БП: панель «Заголовок / Значение» контрагента шириной 25 + 15 символов)
        element.style.flex = widthWeight(item) + " 1 " + px(widthWeight(item) * CH);
        element.classList.add("fm-weighted");
      }
      // Группа с шириной в столбце: ширина - предел по месту, окно по ней не раздвигается (процент в значении
      // не дает ширине войти в размер окна) - группа ужимается до своих полей. Контрагент БП: «Основной
      // банковский счет» и «Контактная информация» шириной 1000 - окно 1479 px, как в 1С; договор -
      // «Дополнительные соглашения». В строке ширина - вес, и окно по ней считается (формы-консоли)
      if (!horizontal && item.type === "UsualGroup" && item.width && item.horizontalStretch !== true) {
        element.style.width = "min(" + element.style.width + ", 100%)";
        element.classList.add("fm-width-cap");
      }
      if (heightSplit(item)) element.classList.add("fm-vstretch");
      if (horizontal && widthStretchable(item)) element.classList.add("fm-wstretch");
      // Положение элемента в группе (ГоризонтальноеПоложениеВГруппе): «Право» прижимает к краю
      if (item.groupHorizontalAlign && item.groupHorizontalAlign !== "Auto") element.classList.add("fm-gha-" + item.groupHorizontalAlign);
      if (item.groupVerticalAlign && item.groupVerticalAlign !== "Auto") element.classList.add("fm-gva-" + item.groupVerticalAlign);
      if (previous && (horizontal ? widthSplit(previous) && widthSplit(item) : heightSplit(previous) && heightSplit(item))) {
        var splitter = h("div", horizontal ? "fm-splitter-v" : "fm-splitter-h");
        if (horizontal) dragSplitter(splitter);
        container.appendChild(splitter);
      }
      container.appendChild(element);
      previous = item;
    });
  }

  // Разделитель между колонками строки тянется мышью, как в 1С: соседи меняют ширину, сумма та же
  function dragSplitter(splitter) {
    splitter.addEventListener("pointerdown", function (event) {
      if (!splitter.classList.contains("fm-splitter-v")) return;
      var left = splitter.previousElementSibling;
      var right = splitter.nextElementSibling;
      if (!left || !right) return;
      event.preventDefault();
      splitter.setPointerCapture(event.pointerId);
      var start = event.clientX;
      var leftWidth = left.getBoundingClientRect().width;
      var rightWidth = right.getBoundingClientRect().width;
      // Сторона не уже своего содержимого, как в 1С: поля и заголовки не уезжают за форму и не
      // наезжают друг на друга; таблица в минимум не входит - у нее своя прокрутка
      tableFloor = 120;
      var leftMin = Math.max(60, normalWidth(left));
      var rightMin = Math.max(60, normalWidth(right));
      tableFloor = 0;
      var move = function (moveEvent) {
        var shift = Math.max(Math.min(0, leftMin - leftWidth), Math.min(Math.max(0, rightWidth - rightMin), moveEvent.clientX - start));
        [[left, leftWidth + shift], [right, rightWidth - shift]].forEach(function (pair) {
          pair[0].style.width = "";
          pair[0].style.minWidth = "0";
          pair[0].style.flex = "0 0 " + px(pair[1]);
        });
      };
      var stop = function () {
        splitter.removeEventListener("pointermove", move);
        splitter.removeEventListener("pointerup", stop);
        publish();
      };
      splitter.addEventListener("pointermove", move);
      splitter.addEventListener("pointerup", stop);
    });
  }

  var DOCUMENT_FIELDS = ["SpreadsheetDocumentField", "HTMLDocumentField", "TextDocumentField", "FormattedDocumentField",
    "ChartField", "GanttChartField", "DendrogramField", "PlannerField", "GraphicalSchemaField", "GeographicalSchemaField",
    "PDFDocumentField"];

  // Ширина растягиваемого элемента в 1С - вес, по которому соседи по строке делят ее ширину, а не
  // точный размер (руководство разработчика 8.3.27, 7.7.13.3; снимки 1С: левая и правая
  // части закладок 20:50 и 15:40 делят окно в той же пропорции). Строка с весами - та, где у
  // растягиваемого элемента задана ширина; только при ширине формы - без нее окно по содержимому,
  // а пропорции раздули бы его
  function weightedRow(items) {
    return items.some(function (item) {
      return item && typeof item === "object" && isShown(item) && item.width && widthStretchable(item);
    });
  }

  // Растягивается по ширине: явно; таблица, панель закладок и поле документа - по умолчанию;
  // группа с «Авто» - если растягивается ее содержимое
  function widthStretchable(node) {
    if (node.horizontalStretch === true) return true;
    if (node.horizontalStretch === false) return false;
    if (node.type === "Table" || node.type === "Pages" || DOCUMENT_FIELDS.indexOf(node.type) >= 0) return true;
    if (node.type === "UsualGroup" || node.type === "Page") return shownItems(node).some(widthStretchable);
    return false;
  }

  // Командная панель среди элементов своей ширины не имеет - берет остаток строки: строка с ней не ужимается по
  // содержимому (ПТУ БП с «Показать скрытые»: кнопка «›» с положением «Право» рядом с панелью уводила панель в «Еще»)
  function hasStretchedContent(node) {
    return shownItems(node).some(function (item) {
      if (item.type === "CommandBar" && item.horizontalStretch !== false) return true;
      return widthStretchable(item) || stretched(item) || ((item.type === "UsualGroup" || item.type === "Page") && hasStretchedContent(item));
    });
  }

  function hugsContent(node, behavior) {
    var decorated = !!node.backColor || ["Line", "WeakSeparation", "NormalSeparation", "StrongSeparation"].indexOf(node.representation) >= 0;
    // Строка с элементом «Право» - тоже по содержимому: элемент прижат к краю строки, а не колонки
    // (Г-18 БП: «Склонения» договора стоят сразу за полем «Руководитель»)
    var alignedRow = (node.group || "Vertical") !== "Vertical" && shownItems(node).some(function (item) {
      return item.groupHorizontalAlign === "Right" || item.groupHorizontalAlign === "Center";
    });
    return node.horizontalStretch === undefined && (decorated || alignedRow) && behavior === "Usual" && !node.width && !hasStretchedContent(node);
  }

  // Вес элемента без ширины - его естественная ширина в символах: у таблицы - сумма колонок
  function widthWeight(node) {
    if (node.width) return node.width;
    if (node.type === "Table") {
      return columnsOf(node).columns.reduce(function (sum, column) { return sum + column.width; }, 0) || 20;
    }
    return 20;
  }

  function widthSplit(node) {
    if (node.horizontalStretch === false) return false;
    return node.type === "UsualGroup" || node.type === "Pages" || node.type === "Table" || DOCUMENT_FIELDS.indexOf(node.type) >= 0;
  }

  function heightSplit(node) {
    if (node.verticalStretch === false) return false;
    if (node.type === "Table" || DOCUMENT_FIELDS.indexOf(node.type) >= 0) return true;
    // Многострочное поле ввода - только по явному «Растягивать по вертикали: Да»
    if (node.type === "InputField") return node.verticalStretch === true && inputLines(node) > 1;
    if (node.type === "UsualGroup" || node.type === "Pages" || node.type === "Page") {
      return shownItems(node).some(heightSplit);
    }
    return false;
  }

  function renderItem(node, ctx) {
    switch (node.type) {
      case "UsualGroup": return renderGroup(node, ctx);
      case "Pages": return renderPages(node, ctx);
      case "InputField": return renderInput(node, ctx);
      case "CheckBoxField": return renderCheckBox(node, ctx);
      case "RadioButtonField": return renderRadio(node, ctx);
      case "LabelField": return renderLabelField(node, ctx);
      case "Table": return renderTable(node, ctx);
      case "LabelDecoration": return renderLabel(node);
      case "PictureDecoration": return renderPicture(node);
      case "CommandBar": return bodyCommandBar(node, ctx);
      case "Button": return renderButton(node, "body");
      case "Popup": return renderPopup(node, "body");
      default: return renderStub(node);
    }
  }

  // Поле тянется на всю ширину: явное растягивание или снятая «Авто максимальная ширина»
  function stretched(node) {
    return node.horizontalStretch === true || (node.autoMaxWidth === false && node.horizontalStretch !== false);
  }

  function fieldShell(node, control, autoLocation) {
    var location = node.titleLocation || "Auto";
    if (location === "Auto") location = autoLocation;
    var wrap = h("div", "fm-field fm-tl-" + location);
    if (location !== "None") {
      var colon = location === "Left" || location === "Top" ? ":" : "";
      // Заголовок из пробелов - пустое место без двоеточия (флажки договора БП: «Договор закрыт»)
      var text = titleOf(node).trim() ? titleOf(node) + colon : "";
      var heading = clip(h("span", "fm-field-title", text), "заголовок");
      if (node.titleTextColor) heading.style.color = paint(node.titleTextColor);
      applyFont(heading, node.titleFont);
      // Заголовок в несколько строк: перевод строки в тексте или «Высота заголовка» (Г-2); ширину ставит titleLines
      if (text.indexOf("\n") >= 0 || node.titleHeight > 1) {
        heading.classList.add("fm-title-lines");
        heading.dataset.lines = String(node.titleHeight > 1 ? node.titleHeight : 0);
      }
      wrap.appendChild(heading);
    }
    var host = control;
    // Заголовок справа (флажок): «?» - после заголовка; в обратном ряду это первый элемент
    // Флажок и переключатель уже текста подсказки: текст снизу и сверху переносится по месту, а не по квадрату
    var wide = node.type === "CheckBoxField" || node.type === "RadioButtonField";
    var paired = location === "Right" && tooltipText(node) && node.toolTipRepresentation !== "Button";
    if (location === "Right" && node.toolTipRepresentation === "Button" && tooltipText(node)) {
      wrap.insertBefore(helpButton(node), wrap.firstChild);
    } else if (!paired) {
      control = withTooltip(node, control, wide);
      // Заголовок - на уровне поля, а не по середине поля с подсказкой («По умолчанию» конструктора суммы прописью)
      if (control.classList.contains("fm-xtip-Bottom")) wrap.classList.add("fm-xtip-below");
      if (control.classList.contains("fm-xtip-Top")) wrap.classList.add("fm-xtip-above");
    }
    control.classList.add("fm-control");
    wrap.appendChild(control);
    if (stretched(node)) wrap.classList.add("fm-stretch");
    var item = wrap;
    // Заголовок справа с подсказкой рядом: подсказка - у пары «квадрат + заголовок», как в 1С (снимок владельца
    // 10.11.2026: заголовок рядом с квадратом, текст снизу от левого края квадрата)
    if (paired) {
      item = withTooltip(node, wrap, wide);
      if (item !== wrap && stretched(node)) item.classList.add("fm-stretch");
    }
    if (item.classList.contains("fm-xtip-wide")) item.classList.add("fm-wide-tip");
    else if (control.classList.contains("fm-xtip-wide")) wrap.classList.add("fm-wide-tip");
    return mark(node, item, host);
  }

  function tooltipText(node) {
    return node.extendedTooltip || node.toolTip || "";
  }

  function helpButton(node) {
    var help = h("span", "fm-help-btn", "?");
    help.title = tooltipText(node);
    return help;
  }

  // Подсказка «Кнопка» - «?» после поля; «Отображать сверху / снизу / слева / справа» - текст
  // подсказки рядом с полем. Поле с подсказкой оборачивается: обертка встает на место поля.
  // wide - текст сверху и снизу шире поля: переносится по ширине места, а не поля (флажок, переключатель)
  function withTooltip(node, control, wide) {
    var representation = node.toolTipRepresentation || "Auto";
    if (!tooltipText(node)) return control;
    if (representation === "Button") {
      var row = h("div", "fm-xtip fm-xtip-Button");
      row.appendChild(control);
      row.appendChild(helpButton(node));
      return row;
    }
    var side = { ShowTop: "Top", ShowBottom: "Bottom", ShowLeft: "Left", ShowRight: "Right" }[representation];
    if (!side) return control;
    var box = h("div", "fm-xtip fm-xtip-" + side);
    var tip = h("div", "fm-xtip-text", tooltipText(node));
    // Группа шириной в квадрат флажка - месту текста нижняя граница TIP_MIN_WIDTH символов, иначе по слову в строке.
    // Допущение: снимка одиночного флажка с заголовком слева из 1С нет; у заголовка справа (снимок) 1С переносит
    // текст по ширине формы, а не элемента
    if (wide && (side === "Top" || side === "Bottom")) {
      box.classList.add("fm-xtip-wide");
      tip.style.minWidth = px(chars(TIP_MIN_WIDTH));
    }
    if (node.extendedTooltipTextColor) tip.style.color = paint(node.extendedTooltipTextColor);
    if (side === "Top" || side === "Left") box.appendChild(tip);
    box.appendChild(control);
    if (side === "Bottom" || side === "Right") box.appendChild(tip);
    return box;
  }

  // Ширина поля «по типу» (руководство разработчика 7.7.13.3), закладка «Ширины» витрины: строка известной
  // длины - длина, но не больше 40 (строка 64 с «Растягивать: Нет» - 40); число - разрядность без
  // разделителей и запятой (5 - 58 px, 15,2 - 179 px с калькулятором); ссылка - длина кода, не шире умолчания
  function typeWidth(node, type) {
    var limit = DEFAULT_WIDTH[type] || 20;
    // Состав даты: дата со временем - калибровка (15); только дата - 12 (снимок 1С: «Утверждена от»
    // 150 px с календарем против 179 px), только время - гипотеза
    if (type === "date" && node.dateFractions === "Date") limit = 12;
    if (type === "date" && node.dateFractions === "Time") limit = 8;
    if (type === "string" && node.length > 0) return Math.min(node.length, SOFT_MAX);
    if (type === "ref" && node.length > 0) return Math.min(node.length, limit);
    if (type === "number" && node.digits > 0) return Math.min(node.digits, SOFT_MAX);
    return limit;
  }

  // Параметры строки формата 1С («ЧДЦ=2; ЧРД=,; ЧН=»): имя → значение без кавычек
  function formatParams(text) {
    var result = {};
    String(text || "").replace(/([А-ЯЁа-яёA-Za-z]+)\s*=\s*('[^']*'|"[^"]*"|[^;]*)/g, function (all, key, value) {
      result[key.toUpperCase()] = value.trim().replace(/^(['"])(.*)\1$/, "$2");
      return all;
    });
    return result;
  }

  // Представления булева - по формату (`БИ`, `БЛ`), без формата - «Да» и «Нет» (тумблер, поле ввода)
  function booleanTexts(node) {
    var params = formatParams(node.format);
    return { yes: "БИ" in params ? params["БИ"] : "Да", no: "БЛ" in params ? params["БЛ"] : "Нет" };
  }

  function booleanText(node, value) {
    var texts = booleanTexts(node);
    return truthy(value) ? texts.yes : texts.no;
  }

  // Пункт списка выбора - строка (значение) или `{value, presentation}`; без представления 1С показывает значение
  function choiceValue(item) { return item && typeof item === "object" ? String(item.value) : String(item); }
  function choiceText(item) {
    return item && typeof item === "object" && item.presentation ? item.presentation : choiceValue(item);
  }
  // Пример значения поля называет пункт значением или представлением
  function choiceMatches(item, sample) {
    if (sample === undefined || sample === null) return false;
    return String(sample) === choiceValue(item) || String(sample) === choiceText(item);
  }

  // Список, который раскрывается у поля: список выбора, у булева - «Да» и «Нет», иначе значения перечисления
  function dropValues(node) {
    if (Array.isArray(node.choiceList)) return node.choiceList.map(choiceText);
    if (node.dataType === "boolean") {
      var texts = booleanTexts(node);
      return [texts.yes, texts.no];
    }
    return node.enumValues;
  }

  // Пустое значение так, как его показывает 1С: число - ноль, дробная часть - только по «ЧДЦ» формата,
  // не по разрядности типа (Г-5 БП: «Сумма расходов» с форматом - «0,00», «в т.ч. НДС» без него - «0»);
  // «ЧН» - свое представление нуля, пустое - пустое поле. Дата - маска
  function emptyValue(node, type) {
    // Пустого значения нет в списке выбора - поле пустое (Ф-5 БП: «Оплата в» договора, число со списком)
    if (Array.isArray(node.choiceList) && node.choiceList.length) return "";
    if (type === "number") {
      var params = formatParams(node.format);
      if ("ЧН" in params) return params["ЧН"];
      var fraction = parseInt(params["ЧДЦ"], 10) || 0;
      return "0" + (fraction > 0 ? (params["ЧРД"] || ",") + new Array(fraction + 1).join("0") : "");
    }
    if (type === "date") return node.dateFractions === "Time" ? "\u00a0\u00a0:\u00a0\u00a0:" : "\u00a0.\u00a0\u00a0.";
    // Булево пустым не бывает: Ложь - «Нет» или `БЛ` формата
    if (type === "boolean") return booleanTexts(node).no;
    return "";
  }

  // Шрифт модели (`font`, `titleFont`, `footerFont`): начертание - жирный, наклонный, подчеркнутый, зачеркнутый;
  // у абсолютного шрифта - имя и размер в пунктах, размер - относительно 10 пт шрифта «Такси»
  function applyFont(element, font) {
    if (!element || !font || typeof font !== "object") return;
    if (font.bold) element.style.fontWeight = "bold";
    if (font.italic) element.style.fontStyle = "italic";
    var lines = (font.underline ? ["underline"] : []).concat(font.strikeout ? ["line-through"] : []);
    if (lines.length) element.style.textDecoration = lines.join(" ");
    if (typeof font.faceName === "string" && font.faceName.trim()) {
      element.style.fontFamily = '"' + font.faceName.trim().replace(/["\\]/g, "") + '", var(--font)';
    }
    if (typeof font.height === "number" && font.height >= 1) {
      element.style.fontSize = "calc(var(--font-size) * " + (font.height / 10) + ")";
    }
  }

  // Строк в поле ввода: многострочное без высоты - 3 (владелец: «2 или 3, примерно»); с высотой 1 - как обычное
  function inputLines(node) {
    return node.height || (node.multiLine ? 3 : 1);
  }

  function inputHeight(lines) {
    return lines * 17 + 6;
  }

  function renderInput(node, ctx) {
    var type = node.dataType || "string";
    var box = h("div", "fm-input");
    var lines = inputLines(node);
    var tall = lines > 1;
    var vstretch = tall && heightSplit(node);
    if (tall) {
      box.classList.add("fm-multiline");
      // Растягиваемое по высоте - не ниже своей высоты, остаток окна делит с соседями; «Максимальная высота»
      // при снятом «авто» - предел в строках
      box.style[vstretch ? "minHeight" : "height"] = px(inputHeight(lines));
      // Высота строки поля (.fm-input) растягиванию не дает тянуться
      if (vstretch) box.style.height = "auto";
      if (vstretch && node.autoMaxHeight === false && node.maxHeight > 0) {
        box.style.maxHeight = px(inputHeight(Math.max(node.maxHeight, lines)));
      }
    }
    var width = node.width || (node.multiLine ? 40 : typeWidth(node, type));
    var hasSample = node.sample !== undefined && node.sample !== null && node.sample !== "";
    var shown = hasSample && type === "boolean" ? booleanText(node, node.sample) : node.sample;
    // Значение из списка выбора - его представлением
    var chosen = hasSample && Array.isArray(node.choiceList)
      ? node.choiceList.filter(function (item) { return choiceMatches(item, node.sample); })[0] : undefined;
    if (chosen !== undefined) shown = choiceText(chosen);
    var value = h("span", "fm-input-value", hasSample ? shown : (node.inputHint || emptyValue(node, type)));
    if (!hasSample && node.inputHint) value.classList.add("fm-hint");
    if (type === "number") value.classList.add("fm-number");
    box.appendChild(value);
    var readOnly = node.readOnly === true || ctx.readOnly;
    if (readOnly) box.classList.add("fm-readonly");
    // «Автоотметка незаполненного» сильнее отметки импорта: «Нет» снимает, «Да» ставит
    var incomplete = node.autoMarkIncomplete === false ? false : node.autoMarkIncomplete === true || node.markIncomplete;
    if (incomplete && !hasSample && !readOnly) box.classList.add("fm-incomplete");
    if (node.textColor) value.style.color = paint(node.textColor);
    if (node.borderColor) box.style.borderColor = paint(node.borderColor);
    applyFont(value, node.font);

    // Кнопки - в порядке 1С: список, выбор (у числа - калькулятор, у даты - календарь), очистка, открытие
    var buttons = 0;
    // Ссылка в «Такси» по умолчанию - «▾» (быстрый выбор и история) и «⧉» (открыть), без «…»:
    // так все поля-ссылки на снимках БП; явная кнопка выбора - «…» вместо «▾»
    var ref = type === "ref";
    // «Режим выбора из списка» - только «▾», без «…» и открытия (снимок «Формирование партий ЗЕРНО» БП); «Отображение
    // кнопки выбора: в выпадающем списке» - «▾» вместо «…» (Ф-4 БП); явно заданные кнопки сильнее
    var listMode = node.listChoiceMode === true;
    // Булево - «▾» со списком «Да» / «Нет» (или по формату) без кнопки выбора
    var choiceInList = node.choiceButtonRepresentation === "ShowInDropList";
    // Время - без календаря
    var timeOnly = type === "date" && node.dateFractions === "Time";
    if (!readOnly) {
      var dropList = node.dropListButton !== undefined ? node.dropListButton
        : listMode || choiceInList || Array.isArray(node.choiceList) || type === "boolean" || (ref && node.choiceButton !== true);
      if (dropList) buttons += addInputButton(box, "▾");
      // Калькулятор - у дробного числа и числа без известной разрядности; у целого его нет (поле «Порядок» на снимке 1С)
      var choice = node.choiceButton !== undefined ? node.choiceButton
        : !listMode && !choiceInList && ((type === "date" && !timeOnly) || (type === "number" && node.fractionDigits !== 0));
      if (choice) {
        var custom = node.choiceButtonPicture ? pictureNode(node.choiceButtonPicture) : null;
        buttons += addInputButton(box, custom || (type === "date" ? platformIcon("calendar") : type === "number" ? platformIcon("calc")
          : platformText("InputFieldSelect", "…")));
      }
      // Очистка - после выбора (Ф-3: поле формы-консоли - «… ×»; витрина - «▾ ×»)
      if (node.clearButton) buttons += addInputButton(box, platformText("InputFieldClear", "×"));
      if (node.createButton) buttons += addInputButton(box, "+");
    }
    // Перечисление открыть нельзя: только «▾»
    var open = node.openButton !== undefined ? node.openButton : ref && !listMode && !Array.isArray(node.enumValues);
    if (open) buttons += addInputButton(box, platformIcon("open"));

    // Ширина в 1С - нижняя граница: строка и ссылка тянутся по месту до SOFT_MAX символов,
    // число и дата остаются своей ширины; horizontalStretch - на всю ширину без предела; «Растягивать:
    // Нет» - не шире своей ширины, но в узком окне сжимается, как растягиваемое («Ставка НДС» БП)
    var natural = chars(width) + buttons * BUTTON;
    // Строка тянется до 40 символов при любой длине, кроме короткой (закладка «Ширины» витрины: строки 12,
    // 19, 64 и неограниченная - одной ширины 40); ссылка с представлением кодом - до длины кода (Г-7)
    var shortString = type === "string" && node.length > 0 && node.length <= SHORT_STRING;
    var soft = !tall && !shortString && (type === "string" || type === "ref");
    var softMax = node.horizontalStretch === false ? 0
      : type === "ref" && node.length > 0 ? Math.min(SOFT_MAX, node.length) : SOFT_MAX;
    // «Растягивать: Да» при «Автомаксимальной ширине» - не дальше максимума по типу (руководство, 7.7.13.3):
    // строка и ссылка - как мягкие, до 40 символов, число и дата - своей ширины (договор БП: «Обобщенное
    // наименование товаров для счета-фактуры налогового агента», контрагент: «В группе» - до края соседей)
    var capped = node.horizontalStretch === true && node.autoMaxWidth !== false && !tall;
    var grows = stretched(node) && !capped;
    if (grows) {
      box.style.minWidth = px(chars(Math.min(width, 20)) + buttons * BUTTON);
    } else if (soft) {
      // Нормальная ширина - у значения: по ней окно без ширины формы; в узком окне поле сжимается до
      // нескольких символов, а заголовок остается целым (Г-9, снимки БП: «Введите ИНН или наи…»)
      value.style.width = px(natural - buttons * BUTTON - 2);
      box.style.minWidth = px(chars(SOFT_MIN) + buttons * BUTTON);
      box.style.maxWidth = px(Math.max(natural, chars(softMax)));
      // Кнопки и рамка сверх значения: по ним проход раскладки раскрывает значение до предела (softGrowth)
      box.dataset.chrome = String(buttons * BUTTON + 2);
    } else {
      box.style.width = px(natural);
    }
    // «Максимальная ширина» - предел растягивания (снимок «Формирование партий ЗЕРНО» БП: 28 символов)
    if (node.maxWidth) {
      var limit = chars(node.maxWidth) + buttons * BUTTON;
      box.style.maxWidth = px(box.style.maxWidth ? Math.min(parseFloat(box.style.maxWidth), limit) : limit);
      if (parseFloat(box.style.minWidth) > limit) box.style.minWidth = px(limit);
    }
    // Список выбора поля, «Да» / «Нет» булева или значения перечисления раскрываются щелчком по полю
    var list = dropValues(node);
    if (Array.isArray(list) && list.length && !readOnly) {
      box.classList.add("fm-droplist");
      box.dataset.list = node.name;
    }
    // Фон - только у значения: кнопки поля (список, выбор, открытие) не окрашиваются (владелец)
    if (node.backColor) value.style.backgroundColor = paint(node.backColor);
    // Заголовок «Авто» у многострочного поля - сверху
    var shell = fieldShell(node, box, tall ? "Top" : "Left");
    // Растягиваемое поле с пределом в строке группы тянется только до предела: соседи («кг» у «Массы»
    // ЗЕРНО) остаются рядом
    if (capped) shell.classList.remove("fm-stretch");
    if (node.maxWidth && grows) {
      box.style.width = box.style.maxWidth;
      shell.classList.add("fm-capped");
    }
    if (soft && !grows) {
      shell.classList.add("fm-soft");
      // Заголовок сверху: растет вся обертка, предел - тот же, что у поля
      if (!shell.classList.contains("fm-tl-Left") && !shell.classList.contains("fm-tl-Right")) shell.style.maxWidth = box.style.maxWidth;
    }
    if (tall) shell.classList.add("fm-tall");
    return shell;
  }

  function addInputButton(box, content) {
    var button = h("span", "fm-input-btn");
    if (typeof content === "string") button.textContent = content;
    else button.appendChild(content);
    box.appendChild(button);
    return 1;
  }

  function renderCheckBox(node) {
    var kind = node.checkBoxType || "Auto";
    var on = truthy(node.sample);
    var control;
    if (kind === "Switch") {
      control = h("span", "fm-switch" + (on ? " fm-on" : ""));
    } else if (kind === "Tumbler") {
      control = h("span", "fm-tumbler");
      // Надписи положений - по формату булева (`БИ`, `БЛ`), без формата - «Да» и «Нет»
      var labels = booleanTexts(node);
      control.appendChild(h("span", on ? "fm-on" : "", labels.yes));
      control.appendChild(h("span", on ? "" : "fm-on", labels.no));
    } else {
      control = h("span", "fm-check");
      if (on) control.innerHTML = ICONS.check;
    }
    // Заголовок «Авто» у флажка в 1С - слева, как у остальных полей
    return fieldShell(node, control, "Left");
  }

  function renderRadio(node) {
    var variants = Array.isArray(node.choiceList) && node.choiceList.length ? node.choiceList : ["Вариант 1", "Вариант 2"];
    // Тумблер без значения - ни одна кнопка не нажата (Ф-6 БП: «Расчеты» поступления и списания); у переключателя
    // с кружками отмечен первый вариант (снимок договора: «НДС: В сумме»)
    var tumbler = node.radioButtonType === "Tumbler";
    var selected = node.sample !== undefined ? node.sample : tumbler ? null : choiceValue(variants[0]);
    var control;
    var auto = "Left";
    if (tumbler) {
      control = h("span", "fm-tumbler");
      variants.forEach(function (variant) {
        control.appendChild(h("span", choiceMatches(variant, selected) ? "fm-on" : "", choiceText(variant)));
      });
    } else {
      control = h("div", "fm-radio-list");
      var columns = node.columnsCount || variants.length;
      control.style.gridTemplateColumns = "repeat(" + columns + ", max-content)";
      // Переключатель в несколько строк: заголовок «Авто» - сверху
      if (variants.length > columns) auto = "Top";
      variants.forEach(function (variant) {
        var item = h("span", "fm-radio-item");
        item.appendChild(h("span", "fm-radio" + (choiceMatches(variant, selected) ? " fm-on" : "")));
        item.appendChild(h("span", "", choiceText(variant)));
        control.appendChild(item);
      });
    }
    return fieldShell(node, control, auto);
  }

  // Рамка поля надписи и поля картинки (`border`, `borderColor`) - ТипРамкиЭлементаУправления; цвет не задан - авто,
  // как рамка поля ввода. Умолчание вида: у поля картинки - одинарная (БП: 1104 поля из 1518, остальные - «Без рамки»
  // явно), у надписи - без рамки
  var BORDER_LINES = { Single: "1px solid", Rounded: "1px solid", Double: "3px double", DoubleUnderline: "3px double",
    Underline: "1px solid", Overline: "1px solid", Embossed: "2px outset", Indented: "2px inset" };
  function applyBorder(element, node, fallback) {
    var kind = node.border || fallback;
    if (!BORDER_LINES[kind]) return;
    var line = BORDER_LINES[kind] + " " + (paint(node.borderColor) || "var(--border)");
    if (kind === "Underline" || kind === "DoubleUnderline") element.style.borderBottom = line;
    else if (kind === "Overline") element.style.borderTop = line;
    else element.style.border = line;
    if (kind === "Rounded") element.style.borderRadius = "4px";
    element.classList.add("fm-bordered");
  }

  function renderLabelField(node) {
    // Ссылка без примера значения - текстом заголовка поля, иначе в макете пустое место (`sample: ""` -
    // пустая); текст ссылки не обрезается, ширина - нижняя граница («Увольнение»: «Начислено», «Удержано»).
    // Пустая ссылка места не держит: в 1С от нее виден только заголовок (реализация БП: «Расчеты» шириной
    // 100 не расширяет колонку шапки)
    var text = node.sample !== undefined ? node.sample : (node.hyperlink ? titleOf(node) : "");
    var value = h("span", "fm-label-value", text);
    if (node.textColor) value.style.color = paint(node.textColor);
    if (node.hyperlink) value.classList.add("fm-hyperlink");
    if (node.width && !(node.hyperlink && text === "")) value.style[node.hyperlink ? "minWidth" : "width"] = px(chars(node.width));
    applyBorder(value, node, "WithoutBorder");
    return fieldShell(node, value, "Left");
  }

  function renderLabel(node) {
    var element = h("div", "fm-decoration fm-label");
    // Растягиваемая надпись - распорка: забирает остаток строки (БП прижимает так кнопки вправо)
    if (node.horizontalStretch === true) element.classList.add("fm-grow-item");
    if (node.textColor) element.style.color = paint(node.textColor);
    if (node.backColor) {
      element.classList.add("fm-label-back");
      element.style.backgroundColor = paint(node.backColor);
    }
    var text = titleOf(node);
    if (node.formatted) element.innerHTML = formatted(text);
    else element.textContent = text;
    if (node.hyperlink) element.classList.add("fm-hyperlink");
    if (node.width) element.style.width = px(chars(node.width));
    if (node.height) element.style.minHeight = px(node.height * 17);
    mark(node, element);
    // Подсказка «Кнопка» у надписи - «?» после текста (Г-12 БП: «Ставка налога: 4% ?», «Разбить платеж ?»)
    if (node.toolTipRepresentation === "Button" && tooltipText(node)) {
      var row = withTooltip(node, element);
      // Растягиваемая надпись-распорка: остаток строки забирает обертка, «?» - сразу за текстом
      if (node.horizontalStretch === true) {
        element.classList.remove("fm-grow-item");
        row.classList.add("fm-grow-item");
      }
      return row;
    }
    return element;
  }

  // Web-цвета 1С, которых нет в CSS (таблица инструмента schema/colors-1c.json)
  var WEB_EXTRA = { cream: "#FFFBF0", mediumgreen: "#C0DCC0", lightgoldenrod: "#EEDD82", lightslateblue: "#8470FF",
    mediumgray: "#A0A0A4", violetred: "#D02090" };

  // Цвет модели → цвет CSS: элемент стиля - значением из `styles` (нет значения - без цвета), web-цвет 1С вне CSS -
  // по таблице
  function paint(color) {
    if (typeof color !== "string" || !color) return "";
    if (color.indexOf("style:") === 0) return STYLES[color.slice(6)] || "";
    return WEB_EXTRA[color] || color;
  }

  // Форматированная строка в разметке 1С: <b>, <i>, <u>, <s>, <color X>, <bgcolor X>, <link адрес>,
  // закрытие - </>; цвет - #RRGGBB, web-цвет или элемент стиля `style:Имя` (импорт заменил UUID именем), прочее -
  // без оформления
  function formatted(text) {
    var escaped = String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    var open = [];
    return escaped.replace(/&lt;(\/?)([a-z]*)\s*([^&]*?)&gt;/gi, function (all, closing, tag, argument) {
      if (closing) {
        var last = open.pop();
        return last ? "</" + last + ">" : "";
      }
      tag = tag.toLowerCase();
      var name = { b: "b", i: "i", u: "u", s: "s", link: "a" }[tag] || "span";
      open.push(name);
      if (name === "a") return '<a class="fm-hyperlink">';
      var color = /^(#[0-9a-f]{6}|[a-z]+|style:[A-Za-zА-Яа-яЁё0-9_]+)$/i.test(argument) ? paint(argument) : null;
      if (color && tag === "color") return '<span style="color:' + color + '">';
      if (color && tag === "bgcolor") return '<span style="background-color:' + color + '">';
      return "<" + name + ">";
    }) + open.reverse().map(function (name) { return "</" + name + ">"; }).join("");
  }

  // Стандартная картинка с известной пиктограммой рисуется ею; прочие - заглушкой с именем
  function renderPicture(node) {
    var element = h("div", "fm-picture");
    var known = pictureNode(node.picture);
    // Без размера в 1С картинка своего размера - обычно значок: рисуется значком без подписи
    // Растровая общая картинка без размера элемента - своего размера (Ф-7 БП: «Начните отсюда» контрагента);
    // SVG и стандартные - значком 16 px
    var raster = /^data:image\/(png|gif|jpeg|bmp)/.test(PICTURES[node.picture] || "");
    if (!node.width && !node.height && raster) {
      element.classList.add("fm-picture-natural");
      element.appendChild(known);
      if (node.hyperlink) element.style.cursor = "pointer";
      return mark(node, element);
    }
    if (!node.width && !node.height) {
      element.classList.add("fm-picture-icon");
      element.appendChild(known || icon("picture"));
      if (node.hyperlink) element.style.cursor = "pointer";
      return mark(node, element);
    }
    if (known) {
      element.classList.add("fm-picture-std");
      element.appendChild(known);
    } else {
      element.appendChild(icon("picture"));
      if (node.picture) element.appendChild(h("span", "", node.picture));
    }
    element.style.width = px((node.width || 8) * CH);
    element.style.height = px((node.height || 3) * 23);
    if (node.hyperlink) element.style.cursor = "pointer";
    return mark(node, element);
  }

  // Пустой табличный документ: шапка с номерами колонок, полоса номеров строк, сетка; текущая ячейка - первая
  // (снимок 1С)
  function sheetGrid(element) {
    var corner = h("div", "fm-sheet-corner");
    var columns = h("div", "fm-sheet-columns");
    var rows = h("div", "fm-sheet-rows");
    for (var column = 1; column <= 40; column++) columns.appendChild(h("span", column === 1 ? "fm-sheet-current" : "", String(column)));
    for (var row = 1; row <= 120; row++) rows.appendChild(h("span", row === 1 ? "fm-sheet-current" : "", String(row)));
    element.appendChild(corner);
    element.appendChild(columns);
    element.appendChild(rows);
    element.appendChild(h("div", "fm-sheet-cells"));
  }

  function renderStub(node) {
    var element = h("div", "fm-stub");
    if (node.type === "SpreadsheetDocumentField") {
      element.classList.add("fm-sheet");
      sheetGrid(element);
    } else if (node.type === "PictureField") {
      // Поле картинки без значения в 1С пустое - место своего размера в рамке поля (одинарная по умолчанию; Г-14:
      // справа от «Номер» в документах БП и желтая панель формы-консоли - «Без рамки»); пример значения -
      // имя картинки
      element.classList.add("fm-picture-empty");
      applyBorder(element, node, "Single");
      // С картинкой значений пример - значение (ячейка коллекции), без нее - имя картинки
      var shown = node.valuesPicture ? valuesPictureNode(node.valuesPicture, node.sample)
        : node.sample ? pictureNode(String(node.sample)) : null;
      if (shown) element.appendChild(shown);
    } else if (node.type === "TextDocumentField") {
      // Пустой текстовый документ: белое поле с полосой слева (снимки «Наборы», «Запросы», «События»)
      element.classList.add("fm-textdoc");
      element.appendChild(h("div", "fm-textdoc-gutter"));
    } else {
      element.appendChild(icon("stub"));
      // Нераспознанный импортом элемент - с видом из исходного XML
      element.appendChild(h("span", "", node.type === "Unknown" ? kindName(node.type) + ": " + node.sourceType : kindName(node.type)));
    }
    element.style.width = px((node.width || 40) * CH);
    // Растягиваемое по высоте - не ниже своей высоты, остаток окна делит с соседями
    element.style[heightSplit(node) ? "minHeight" : "height"] = px((node.height || 8) * 23);
    if (node.horizontalStretch !== false) {
      element.style.width = "";
      element.style.minWidth = px(Math.min(node.width || 40, 30) * CH);
      element.classList.add("fm-stretch");
    }
    if (typeof node.title !== "string") return mark(node, element);
    var location = node.titleLocation && node.titleLocation !== "Auto" ? node.titleLocation : "Top";
    var shell = fieldShell(Object.assign({}, node, { titleLocation: location }), element, "Top");
    if (node.horizontalStretch !== false) shell.classList.add("fm-stretch");
    return shell;
  }

  // Группы

  function renderGroup(node, ctx) {
    var direction = node.group || "Vertical";
    var behavior = node.behavior && node.behavior !== "Auto" ? node.behavior : "Usual";
    var hasTitle = node.showTitle !== false && (typeof node.title === "string" || behavior !== "Usual");
    // В 8.3 по умолчанию «Нет»; «Авто» - значение 8.5, рисуется слабым выделением при заголовке
    var representation = node.representation || "None";
    var separation = representation === "Auto" ? (hasTitle ? "Weak" : "None") : representation.replace("Separation", "");

    var group = h("div", "fm-group fm-sep-" + separation);
    if (hasTitle) {
      var heading = clip(h("div", "fm-group-title", titleOf(node)), "заголовок группы");
      if (node.titleTextColor) heading.style.color = paint(node.titleTextColor);
      group.appendChild(heading);
    }

    var horizontal = direction !== "Vertical";
    var content = h("div", "fm-group-content " + (horizontal ? "fm-horizontal" : "fm-vertical"));
    if (direction === "HorizontalIfPossible") content.classList.add("fm-wrap");
    if (direction === "Vertical" && node.throughAlign !== "DontUse") content.classList.add("fm-through");
    // «Если возможно», переключенная в столбец, выравнивается как вертикальная (switchIfPossible)
    if (node.throughAlign === "DontUse") content.dataset.through = "0";
    if (node.childItemsHorizontalAlign && node.childItemsHorizontalAlign !== "Auto") {
      content.classList.add("fm-align-" + node.childItemsHorizontalAlign);
    }
    if (node.childItemsVerticalAlign && node.childItemsVerticalAlign !== "Auto") {
      content.classList.add("fm-valign-" + node.childItemsVerticalAlign);
    }
    renderItems(content, shownItems(node), ctx, horizontal);
    // Подсказка группы «Кнопка» - «?» после содержимого строки (Г-12 БП: «Договор закрыт ?» - подсказка у группы флажка)
    if (horizontal && content.children.length && node.toolTipRepresentation === "Button" && tooltipText(node)) {
      content.appendChild(helpButton(node));
    }
    // Группа без видимого содержимого в 1С не показывается (ее наполняет код - «Дополнительно» БСП)
    if (!content.children.length) return null;
    // В строке групп остаток ширины забирает последняя группа (калибровка: колонки витрины);
    // при выравнивании подчиненных вправо или по центру группа без явного растягивания своей ширины.
    // Всплывающая группа - ссылка своей ширины: остаток берет командная панель, ссылка у правого
    // края (снимок 1С: «Подсказка»)
    var aligned = node.childItemsHorizontalAlign === "Right" || node.childItemsHorizontalAlign === "Center";
    // Растягиваемый по ширине элемент строки (таблица, закладки, группа с ними) забирает остаток сам,
    // соседи - своей нормальной ширины (владелец; снимок 1С: таблица и группа настроек)
    var stretchy = horizontal ? content.querySelectorAll(":scope > .fm-wstretch") : [];
    if (horizontal && !content.querySelector(":scope > .fm-weighted") && stretchy.length) {
      Array.prototype.forEach.call(stretchy, function (element) { element.classList.add("fm-grow"); });
    } else if (horizontal && !content.querySelector(":scope > .fm-weighted")) {
      var groups = content.querySelectorAll(":scope > .fm-group:not(.fm-popup-group):not(.fm-hug), :scope > .fm-pages, :scope > .fm-table");
      var last = groups.length ? groups[groups.length - 1] : null;
      if (last && (!aligned || last.classList.contains("fm-stretch-explicit"))) last.classList.add("fm-grow");
    }
    group.appendChild(content);
    // Подсказка группы «Отображать снизу / сверху» - текстом под или над содержимым (снимок «Увольнение»)
    var tipSide = { ShowBottom: "Bottom", ShowTop: "Top" }[node.toolTipRepresentation];
    if (tipSide && tooltipText(node)) {
      var tip = h("div", "fm-xtip-text", tooltipText(node));
      if (node.extendedTooltipTextColor) tip.style.color = paint(node.extendedTooltipTextColor);
      if (tipSide === "Top") group.insertBefore(tip, content);
      else group.appendChild(tip);
    }

    // Растягивание «Авто» у группы с оформлением (фон, черта, выделение) без растягиваемого содержимого -
    // оформление по наибольшему подчиненному (руководство, 7.7.13.4; группа «Настройки» на снимке 1С)
    if (hugsContent(node, behavior)) group.classList.add("fm-hug");
    else if (node.horizontalStretch !== false) group.classList.add("fm-stretch");
    if (node.horizontalStretch === true) group.classList.add("fm-stretch-explicit");
    // У всплывающей группы фон - у ее окна, ссылка без фона
    if (node.backColor && behavior === "PopUp") content.style.backgroundColor = paint(node.backColor);
    else if (node.backColor) {
      group.classList.add("fm-backcolor");
      group.style.backgroundColor = paint(node.backColor);
    }
    // Явно растягиваемая группа тянется на всю ширину, ее ширина - вес в строке (руководство, 7.7.13.3;
    // «Open Office Document»: «Для просмотра файлов...» при ширине 30)
    if (node.width && node.horizontalStretch !== true) {
      group.style.width = px(chars(node.width));
      // Ширина больше места - по месту: договор БП, «Дополнительные соглашения» шириной 1000 в окне 1480 px
      group.style.maxWidth = "100%";
      // у растягиваемой группы ширина - вес, колонка заголовков к ней не прибавляется
      if (!widthStretchable(node)) group.dataset.width = String(chars(node.width));
    }
    if (behavior === "Collapsible" || behavior === "PopUp") {
      group.classList.add(behavior === "Collapsible" ? "fm-collapsible" : "fm-popup-group");
      // Отображение управления «Картинка» - стрелка перед заголовком вместо гиперссылки
      if (behavior === "Collapsible" && node.controlRepresentation === "Picture") group.classList.add("fm-collapse-picture");
      // Свернутая в XML группа на странице свернута, как в 1С:Предприятие; снимок для ТЗ (`expand`) - развернута,
      // как предпросмотр конфигуратора (решения владельца 31.10.2026)
      var isCollapsed = node.name in collapsed ? collapsed[node.name]
        : behavior === "PopUp" || (node.collapsed === true && !state.expand);
      if (isCollapsed) group.classList.add("fm-collapsed");
      var title = group.firstChild;
      var toggle = function () {
        collapsed[node.name] = !group.classList.contains("fm-collapsed");
        group.classList.toggle("fm-collapsed", collapsed[node.name]);
        // Всплывающее окно открывается в сторону середины формы: у правого края - влево
        if (behavior === "PopUp" && !collapsed[node.name]) {
          var form = document.querySelector(".fm-window").getBoundingClientRect();
          var rect = group.getBoundingClientRect();
          group.classList.toggle("fm-popup-right", rect.left > form.left + form.width / 2);
        }
        stretchRows(document.querySelector(".fm-body"));
        publish();
      };
      if (title && title.classList.contains("fm-group-title")) title.addEventListener("click", toggle);
      // Содержимое всплывающей группы - окном поверх формы с крестиком (снимок владельца, «Подсказка»)
      if (behavior === "PopUp") {
        var close = h("span", "fm-popup-close");
        close.appendChild(icon("close"));
        close.addEventListener("click", toggle);
        content.appendChild(close);
      }
    }
    return mark(node, group);
  }

  function renderPages(node, ctx) {
    var pages = shownItems(node).filter(function (item) { return item.type === "Page"; });
    var representation = node.pagesRepresentation || "Auto";
    var element = h("div", "fm-pages");
    if (representation === "TabsOnBottom") element.classList.add("fm-tabs-bottom");
    if (representation === "TabsOnLeftHorizontal") element.classList.add("fm-tabs-side");
    if (representation === "TabsOnRightHorizontal") element.classList.add("fm-tabs-side", "fm-tabs-right");
    if (representation === "None") element.classList.add("fm-tabs-none");

    var names = pages.map(function (page) { return page.name; });
    var current = currentPage[node.name];
    if (names.indexOf(current) < 0) current = names.indexOf(state.pages[node.name]) >= 0 ? state.pages[node.name] : null;
    if (!current) current = names.indexOf(node.currentPage) >= 0 ? node.currentPage : names[0];
    currentPage[node.name] = current;

    var tabs = h("div", "fm-tabs");
    element.appendChild(tabs);
    pages.forEach(function (page) {
      var tab = clip(h("div", "fm-tab", titleOf(page)), "заголовок закладки");
      if (page.picture) tab.insertBefore(pictureOrStub(page.picture), tab.firstChild);
      tab.dataset.page = page.name;
      var body = h("div", "fm-page fm-group-content " + childrenClass(page.group));
      body.dataset.page = page.name;
      mark(page, body);
      renderItems(body, shownItems(page), ctx, !!page.group && page.group !== "Vertical");
      if (page.name === current) {
        tab.classList.add("fm-current");
        body.classList.add("fm-current");
      }
      tab.addEventListener("click", function () { selectPage(element, node.name, page.name); });
      tabs.appendChild(tab);
      element.appendChild(body);
    });
    return mark(node, element);
  }

  // Группировка подчиненных у формы и закладки: не указана - вертикальная со сквозным выравниванием
  function childrenClass(direction) {
    if (!direction || direction === "Vertical") return "fm-vertical fm-through";
    return "fm-horizontal" + (direction === "HorizontalIfPossible" ? " fm-wrap" : "");
  }

  function selectPage(element, pagesName, pageName) {
    currentPage[pagesName] = pageName;
    Array.prototype.forEach.call(element.children, function (child) {
      if (child.classList.contains("fm-tabs")) {
        Array.prototype.forEach.call(child.children, function (tab) {
          tab.classList.toggle("fm-current", tab.dataset.page === pageName);
        });
      } else if (child.classList.contains("fm-page")) {
        child.classList.toggle("fm-current", child.dataset.page === pageName);
      }
    });
    publish();
  }

  // Командные панели

  function renderCommandBar(node, ctx, options) {
    var bar = h("div", "fm-cmdbar");
    var align = node.horizontalAlign;
    if (align && align !== "Auto" && align !== "Left") bar.classList.add("fm-align-" + align);
    var items = h("div", "fm-cmdbar-items");
    var autoFill = node.type === "AutoCommandBar" ? node.autoFill !== false : node.autoFill === true;
    if (autoFill) bar.dataset.autofill = "1";
    if (autoFill) {
      // Стандартная команда, поставленная кнопкой, автозаполнением не повторяется
      var placed = placedCommands(node);
      standardFaces((options.standard || []).filter(function (command) { return !placed[command.name]; }))
        .forEach(function (face) {
          var button = standardButton(face);
          button.classList.add("fm-auto");
          items.appendChild(button);
        });
    }
    barItems(node).forEach(function (item) {
      var element = renderCommandItem(item, options.place);
      if (element) items.appendChild(element);
    });
    bar.appendChild(items);
    if (options.tail) {
      var tail = h("div", "fm-cmdbar-tail");
      if (options.search) tail.appendChild(searchField());
      var more = h("span", "fm-popup fm-more");
      more.appendChild(h("span", "fm-button-text", "Еще"));
      tail.appendChild(more);
      if (options.help) {
        var help = h("span", "fm-button fm-help");
        help.appendChild(h("span", "fm-button-text", "?"));
        tail.appendChild(help);
      }
      bar.appendChild(tail);
    }
    if (!items.childNodes.length && !options.tail) return null;
    return mark(node, bar);
  }

  // Командная панель среди элементов; `horizontalStretch: false` - своей ширины, а не на остаток строки.
  // Группа с источником команд «Форма» внутри - панель формы: в ней «Еще» и «?» (снимок ПТУ БП)
  // У панели среди элементов «Еще» есть и тогда, когда в ней есть кнопки «только в Еще» (снимок 1С:
  // панель текста запроса с группой команд таблицы «Поля»)
  function bodyCommandBar(node, ctx) {
    var formSource = hasFormSource(node);
    var tail = formSource || hasMoreOnly(node) || hasTableSource(node);
    var bar = renderCommandBar(node, ctx, { standard: [], tail: tail, help: formSource && FORM.help === true });
    if (bar && node.horizontalStretch === false) bar.classList.add("fm-fixed");
    return bar;
  }

  // Подменю всех действий своего «Еще» заменяет: кнопки «только в Еще» уходят в него
  function hasMoreOnly(node) {
    var items = shownItems(node);
    if (items.some(allActions)) return false;
    return items.some(function (item) {
      return item.locationInCommandBar === "InAdditionalSubmenu" || (item.type === "ButtonGroup" && hasMoreOnly(item));
    });
  }

  // Подменю с источником команд - полем документа (не таблицей): все действия поля
  function allActions(node) {
    var source = node.type === "Popup" && /^Item\.(.+)$/.exec(node.commandSource || "");
    var field = source ? findNode(source[1], FORM) : null;
    return !!field && DOCUMENT_FIELDS.indexOf(field.type) >= 0;
  }

  function hasFormSource(node) {
    return node.commandSource === "Form" || (Array.isArray(node.items) ? node.items : []).some(hasFormSource);
  }

  // Кнопки автозаполнения панели формы (`table` нет) или таблицы - по порядку на панели, без снятых в «Составе команд»
  // и запрещенных флагами таблицы: `{name, title, icon, default, joined}`; `joined` - кнопки вплотную (стрелки).
  // Тот же список берет конструктор для «Заполнить стандартными командами»
  function autoCommands(table) {
    if (!table) {
      var formExcluded = Array.isArray(FORM.excludedCommands) ? FORM.excludedCommands : [];
      return (STD_FORM_COMMANDS[FORM.formKind] || []).filter(function (pair) {
        return formExcluded.indexOf(pair[0]) < 0;
      }).map(function (pair) {
        return { name: pair[0], title: standardTitle(pair[0], true), "default": pair[1] === true };
      });
    }
    var excluded = table.excludedCommands || [];
    var isList = (FORM.formKind === "ListForm" || FORM.formKind === "ChoiceForm") &&
      String(table.dataPath || table.name).indexOf("Объект.") !== 0;
    var names = isList ? (FORM.formKind === "ChoiceForm" ? ["Choose", "Create"] : ["Create"])
      .concat(["Copy", "Change", "SetDeletionMark"]) : (table.changeRowSet === false ? [] : ["Add"]);
    // Снятая `ShowRowRearrangement` убирает стрелки с панели (договор БП, «Дополнительные соглашения»)
    var moves = !isList && table.changeRowOrder !== false && excluded.indexOf("ShowRowRearrangement") < 0;
    if (moves) names = names.concat(["MoveUp", "MoveDown"]);
    return names.filter(function (name) { return excluded.indexOf(name) < 0; }).map(function (name) {
      var title = name === "Choose" ? "Выбрать" : name === "Create" ? "Создать" : MORE_COMMANDS[name][0];
      return { name: name, title: title, icon: STD_TABLE_ICONS[name] || "",
        "default": isList && name === (FORM.formKind === "ChoiceForm" ? "Choose" : "Create"),
        joined: name === "MoveUp" || name === "MoveDown" };
    });
  }

  // Вид кнопок автозаполнения для `standardButton`: соседние `joined` - одной группой вплотную
  function standardFaces(commands) {
    var faces = [];
    commands.forEach(function (command) {
      var face = { name: command.name, text: command.icon ? "icon:" + command.icon : command.title,
        "default": command["default"], tip: command.icon ? command.title : "" };
      var last = faces[faces.length - 1];
      if (command.joined && last && last.joined) last.items.push(face);
      else faces.push(command.joined ? { joined: true, items: [face] } : face);
    });
    return faces;
  }

  function standardButton(command) {
    // command: {name, text, default, tip} - текст или «icon:<значок>» с подсказкой; группа вплотную - {joined, items}
    if (command.joined) {
      var group = h("span", "fm-button-group fm-joined");
      command.items.forEach(function (item) { group.appendChild(standardButton(item)); });
      return group;
    }
    var button = h("span", "fm-button fm-std");
    button.dataset.command = "StandardCommand." + command.name;
    if (command.text.indexOf("icon:") === 0) {
      button.classList.add("fm-icon-only");
      button.appendChild(platformIcon(command.text.slice(5)));
      button.title = command.tip || "";
    } else {
      button.appendChild(h("span", "fm-button-text", command.text));
    }
    if (command["default"]) button.classList.add("fm-default");
    return button;
  }

  function searchField() {
    var search = h("span", "fm-search");
    search.appendChild(h("span", "fm-search-text", "Поиск (Ctrl+F)"));
    search.appendChild(h("span", "fm-input-btn", "×"));
    return search;
  }

  // Дополнение таблицы в панели: строка поиска - поле поиска на своем месте (у правого края, как в
  // 1С), управление поиском - кнопка «лупа ▾»; состояние просмотра в макете не рисуется
  function renderAddition(node) {
    if (node.additionType === "SearchControlAddition") {
      var control = h("span", "fm-popup fm-search-control fm-icon-only");
      control.appendChild(icon("search"));
      control.title = "Управление поиском";
      return mark(node, control);
    }
    if (node.additionType === "ViewStatusAddition") return null;
    var search = searchField();
    search.classList.add("fm-search-placed");
    return mark(node, search);
  }

  function hasSearchAddition(node) {
    return shownItems(node).some(function (item) {
      return (item.type === "Addition" && (item.additionType || "SearchStringAddition") === "SearchStringAddition") ||
        ((item.type === "ButtonGroup" || item.type === "Popup") && hasSearchAddition(item));
    });
  }

  function renderCommandItem(node, place) {
    if (node.type === "ButtonGroup") {
      // Компактная группа - кнопки вплотную, без промежутка (перемещение строк вверх и вниз)
      var group = h("span", "fm-button-group" + (node.representation === "Compact" ? " fm-joined" : ""));
      // Источник команд «Таблица»: на панели - команды, что у таблицы дает автозаполнение
      // («Добавить» и стрелки), кроме поставленных кнопками всей панели; остальные - в «Еще» (как пишет импорт).
      // Явные кнопки соседней группы той же панели - тоже поставленные (стрелки рисовались дважды)
      var table = sourceTable(node);
      var placed = table ? placedCommands(barOf(node) || node) : {};
      standardFaces(table ? autoCommands(table).filter(function (command) { return !placed[command.name]; }) : [])
        .forEach(function (face) {
          var button = standardButton(face);
          button.classList.add("fm-auto");
          group.appendChild(button);
        });
      barItems(node).forEach(function (item) {
        var element = renderCommandItem(item, place);
        if (element) group.appendChild(element);
      });
      if (!group.querySelector(".fm-button, .fm-popup, .fm-button-link")) return null;
      return mark(node, group);
    }
    if (node.type === "Popup") return renderPopup(node, place);
    if (node.type === "Addition") return renderAddition(node);
    return renderButton(node, place);
  }

  function buttonFace(node, element, place) {
    node = faceOf(node);
    var representation = node.representation || "Auto";
    var picture = node.picture ? pictureOrStub(node.picture) : (representation === "Picture" ? sheetIcon(node.commandName) : null);
    var showPicture = picture && representation !== "Text";
    // «Авто» с картинкой в командной панели - только картинка (снимок ПТУ БП: «Связанные документы»);
    // у подменю - картинка и текст (снимок 1С: «Разработка», «Загрузить»)
    var showText = representation !== "Picture" &&
      !(representation === "Auto" && picture && place !== "body" && node.type !== "Popup");
    if (showPicture) element.appendChild(picture);
    // Текст кнопки не обрезается: в 1С кнопка растет по тексту, ширина - нижняя граница
    if (showText || !showPicture) element.appendChild(h("span", "fm-button-text", titleOf(node)));
    else element.classList.add("fm-icon-only");
  }

  function renderButton(node, place) {
    if (node.buttonType === "Hyperlink" || node.buttonType === "CommandBarHyperlink") {
      var link = h("span", "fm-button-link fm-hyperlink", titleOf(node));
      var face = faceOf(node);
      // Картинка команды перед текстом ссылки («Вопрос в поддержку»)
      if (face.picture && face.representation !== "Text") link.insertBefore(pictureOrStub(face.picture), link.firstChild);
      return mark(node, link);
    }
    var button = h("span", "fm-button");
    if (/\.StandardCommand\./.test(node.commandName || "")) button.classList.add("fm-std");
    button.dataset.command = node.commandName || "";
    buttonFace(node, button, place);
    if (node.defaultButton) button.classList.add("fm-default");
    // Пометка: кнопка-переключатель, нажатая - «вдавлена»; щелчок - обработчик pressButton
    if (typeof node.check === "boolean") {
      button.classList.add("fm-checkable");
      if (checkedOf(node)) button.classList.add("fm-checked");
    }
    if (node.borderColor) button.style.borderColor = paint(node.borderColor);
    if (node.shape === "Oval") button.classList.add("fm-oval");
    applyFont(button, node.font);
    if (node.width) button.style.minWidth = px(chars(node.width));
    return mark(node, button);
  }

  // Нажата ли кнопка с пометкой: щелчок на макете важнее модели, пока пометку в модели не поменяли
  function checkedOf(node) {
    var state = pressed[node.name];
    return state && state.model === node.check ? state.on : node.check === true;
  }

  // Щелчок по кнопке с пометкой нажимает и отжимает ее, как обработчик команды в 1С; модель не меняется.
  // Через всплытие: кнопки панели перерисовываются при подгонке ширины
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("#fm-root .fm-button.fm-checkable[data-name]");
    if (!button) return;
    var node = findNode(button.dataset.name, FORM);
    if (!node || typeof node.check !== "boolean") return;
    var on = !button.classList.contains("fm-checked");
    pressed[node.name] = { model: node.check, on: on };
    button.classList.toggle("fm-checked", on);
  });

  // Есть ли в подменю или группе кнопок видимая команда: пустое подменю 1С не показывает
  function hasCommands(node) {
    return shownItems(node).some(function (item) {
      return item.type === "Button" || ((item.type === "ButtonGroup" || item.type === "Popup") && hasCommands(item));
    });
  }

  function renderPopup(node, place) {
    // Подменю с источником команд - полем документа (не таблицей): все действия поля, в 1С - «Еще» у
    // правого края панели (снимок 1С: «Таблица» над табличным документом)
    if (allActions(node)) {
      var more = h("span", "fm-popup fm-more fm-all-actions");
      more.appendChild(h("span", "fm-button-text", "Еще"));
      return mark(node, more);
    }
    // Подменю без команд в 1С не видно (так у типовых «Печать», «Заполнить» до заполнения кодом)
    if (!hasCommands(node)) return null;
    var popup = h("span", "fm-popup");
    buttonFace(node, popup, place);
    return mark(node, popup);
  }

  // Раскрытие подменю щелчком, как в 1С: список команд с картинками, группы кнопок - между чертами,
  // вложенное подменю - справа по наведению. «Еще» показывает то, что в нее ушло из панели. Меню -
  // поверх формы (панель обрезает свое содержимое), закрывается щелчком мимо
  function closeMenus() {
    document.querySelectorAll("body > .fm-menu").forEach(function (menu) { menu.remove(); });
    document.querySelectorAll(".fm-popup.fm-open").forEach(function (popup) { popup.classList.remove("fm-open"); });
  }

  // Стандартная команда без кнопки в модели - пункт меню «Еще» (автозаполнение, подменю поиска)
  function stdCommand(command, prefix) {
    var own = prefix === "Form.StandardCommand." && MORE_FORM_COMMANDS[command] || MORE_COMMANDS[command] || [command];
    return { type: "Button", title: own[0], commandName: prefix + command };
  }

  // Стандартная картинка пункта меню по команде, если у кнопки своей нет
  function menuPicture(node) {
    var found = /^Form\.(Item\.[^.]+\.)?StandardCommand\.(\w+)$/.exec(node.commandName || "");
    if (!found) return sheetIcon(node.commandName);
    var own = !found[1] && MORE_FORM_COMMANDS[found[2]] || MORE_COMMANDS[found[2]];
    return own && own[1] ? pictureNode("StdPicture." + own[1]) : sheetIcon(node.commandName);
  }

  function menuKey(node) {
    var found = /^Form\.(Item\.[^.]+\.)?StandardCommand\.(\w+)$/.exec(node.commandName || "");
    if (!found) return "";
    return (found[1] ? TABLE_KEYS : FORM_KEYS)[found[2]] || "";
  }

  function menuRow(node) {
    var row = h("div", "fm-menu-item");
    var face = faceOf(node);
    var picture = face.picture ? pictureOrStub(face.picture) : menuPicture(node);
    var slot = h("span", "fm-menu-picture");
    if (picture) slot.appendChild(picture);
    row.appendChild(slot);
    row.appendChild(h("span", "fm-menu-text", titleOf(node)));
    var key = menuKey(node);
    if (key) row.appendChild(h("span", "fm-menu-key", key));
    if (node.disabled) row.classList.add("fm-menu-disabled");
    if (node.type === "Popup") {
      row.classList.add("fm-menu-sub");
      row.appendChild(menuOf(shownItems(node)));
    }
    // Нажатая кнопка в меню - отметка на месте картинки, с картинкой - картинка в рамке
    if (node.type === "Button" && typeof node.check === "boolean" && checkedOf(node)) {
      row.classList.add("fm-menu-checked");
      if (!picture) slot.innerHTML = ICONS.check;
    }
    return row;
  }

  // Выпадающий список поля: пункты списка выбора или значения перечисления, текущее значение отмечено
  function listMenu(node, box) {
    var menu = h("div", "fm-menu fm-list-menu");
    var list = (node && dropValues(node)) || [];
    var items = node && Array.isArray(node.choiceList) ? node.choiceList : list;
    // Текущее у булева - по представлению образца, без образца - Ложь
    var current = node && node.dataType === "boolean" ? booleanText(node, node.sample) : node && node.sample;
    items.forEach(function (item) {
      var row = h("div", "fm-menu-item", choiceText(item));
      if (choiceMatches(item, current)) row.classList.add("fm-menu-current");
      menu.appendChild(row);
    });
    menu.style.minWidth = px(box.getBoundingClientRect().width);
    return menu;
  }

  // Подменю «Управление поиском» таблицы (снимок 1С)
  function searchItems(table) {
    var prefix = "Form.Item." + table + ".StandardCommand.";
    var history = stdCommand("SearchHistory", prefix);
    history.disabled = true;
    return [stdCommand("FindByCurrentValue", prefix), stdCommand("Find", prefix), history, stdCommand("CancelSearch", prefix)];
  }

  // Группа кнопок - между чертами, вложенная тоже (снимок «Соединения»: «Соединение», «Поле» отделены от
  // «Скопировать»); дополнение «Управление поиском» - подменю, строка поиска и состояние просмотра в меню
  // не попадают
  function menuOf(items) {
    var menu = h("div", "fm-menu");
    var separate = function () {
      if (menu.lastChild && !menu.lastChild.classList.contains("fm-menu-sep")) menu.appendChild(h("div", "fm-menu-sep"));
    };
    var add = function (list) {
      list.forEach(function (item) {
        if (item.type === "ButtonGroup") {
          separate();
          add(shownItems(item));
          separate();
        } else if (item.type === "Button" || item.type === "Popup") {
          menu.appendChild(menuRow(item));
        } else if (item.type === "Addition" && item.additionType === "SearchControlAddition") {
          menu.appendChild(menuRow({ type: "Popup", title: "Управление поиском", picture: "StdPicture.SearchControl",
            items: searchItems(item.additionSource || "") }));
        }
      });
    };
    add(items);
    while (menu.lastChild && menu.lastChild.classList.contains("fm-menu-sep")) menu.lastChild.remove();
    while (menu.firstChild && menu.firstChild.classList && menu.firstChild.classList.contains("fm-menu-sep")) menu.firstChild.remove();
    if (!menu.childNodes.length) menu.appendChild(h("div", "fm-menu-empty", "Нет команд"));
    return menu;
  }

  // «Еще» панели над табличным документом: кнопки «только в Еще» и то, что не поместилось, - элементами
  // модели по именам; поиск и безымянные - строкой
  function overflowMenu(more) {
    var bar = more.closest(".fm-cmdbar");
    var barNode = bar && bar.dataset.name ? findNode(bar.dataset.name) : null;
    var items = [];
    (function collect(node) {
      shownItems(node || {}).forEach(function (item) {
        if (item.locationInCommandBar === "InAdditionalSubmenu") items.push(item);
        else if (item.type === "ButtonGroup") collect(item);
      });
    })(barNode);
    (bar ? bar.querySelectorAll("[data-overflow]") : []).forEach(function (element) {
      if (element.parentElement && element.parentElement.closest("[data-overflow]")) return;
      var node = element.dataset.name ? findNode(element.dataset.name) : null;
      if (node) items.push(node);
      else if (element.classList.contains("fm-search")) items.push({ type: "Button", title: "Поиск" });
      else items.push({ type: "Button", title: element.textContent.trim() || element.title || "Команда" });
    });
    return menuOf(items);
  }

  // Стандартные команды «Еще» при автозаполнении: таблицы - по секциям, формы объекта - подряд; команды,
  // уже стоящие в панели кнопками, не повторяются
  function placedCommands(barNode) {
    var placed = {};
    (function collect(node) {
      (node && Array.isArray(node.items) ? node.items : []).forEach(function (item) {
        var found = /\.StandardCommand\.(\w+)$/.exec(item.commandName || "");
        if (found) placed[found[1]] = true;
        collect(item);
      });
    })(barNode);
    return placed;
  }

  function autoMoreItems(table, barNode) {
    var placed = placedCommands(barNode);
    if (!table) {
      var formExcluded = Array.isArray(FORM.excludedCommands) ? FORM.excludedCommands : [];
      return (MORE_FORM[FORM.formKind] || []).filter(function (command) {
        return !placed[command] && formExcluded.indexOf(command) < 0;
      })
        .map(function (command) { return stdCommand(command, "Form.StandardCommand."); });
    }
    var excluded = table.excludedCommands || [];
    var prefix = "Form.Item." + table.name + ".StandardCommand.";
    var isList = (FORM.formKind === "ListForm" || FORM.formKind === "ChoiceForm") &&
      String(table.dataPath || table.name).indexOf("Объект.") !== 0;
    var sections = isList ? [(FORM.formKind === "ChoiceForm" ? ["Choose"] : []).concat(MORE_LIST)] : MORE_TABLE;
    return sections.map(function (section) {
      var commands = section.filter(function (command) {
        return !placed[command] && excluded.indexOf(command) < 0 &&
          (isList || ((table.changeRowSet !== false || ROW_SET.indexOf(command) < 0) &&
            (table.changeRowOrder !== false || ROW_ORDER.indexOf(command) < 0)));
      });
      return { type: "ButtonGroup", items: commands.map(function (command) { return stdCommand(command, prefix); }) };
    });
  }

  // Элементы панели для «Еще»: все, кроме кнопок «только на панели» (`InCommandBar`), если они не ушли
  // в «Еще» от нехватки места
  // Группа кнопок с источником команд «Таблица»: в «Еще» - ее кнопки и стандартные команды таблицы,
  // не поставленные кнопками панели `barNode`
  function moreOf(items, overflowed, barNode) {
    return items.filter(function (item) {
      return item.locationInCommandBar !== "InCommandBar" || overflowed[item.name];
    }).map(function (item) {
      if (item.type !== "ButtonGroup") return item;
      return Object.assign({}, item, { items: moreOf(shownItems(item), overflowed, barNode).concat(sourceCommands(item, barNode)) });
    });
  }

  // Командная панель, в которой стоит элемент (по имени: узлы панели при выводе бывают копиями)
  function barOf(target) {
    var found = null;
    (function walk(node, bar) {
      if (!node || found) return;
      if (node !== FORM && node.name === target.name) {
        found = bar;
        return;
      }
      var here = node.type === "AutoCommandBar" || node.type === "CommandBar" ? node : bar;
      if (node.commandBar) walk(node.commandBar, node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(function (item) { walk(item, here); });
    })(FORM, null);
    return found;
  }

  function sourceTable(node) {
    var source = node.type === "ButtonGroup" && /^Item\.(.+)$/.exec(node.commandSource || "");
    var table = source ? findNode(source[1], FORM) : null;
    return table && table.type === "Table" ? table : null;
  }

  function sourceCommands(group, barNode) {
    var table = sourceTable(group);
    if (!table) return [];
    return [].concat.apply([], autoMoreItems(table, barNode).map(function (section) { return section.items; }));
  }

  function hasTableSource(node) {
    return (Array.isArray(node.items) ? node.items : []).some(function (item) {
      return !!sourceTable(item) || hasTableSource(item);
    });
  }

  // Меню «Еще» панели таблицы или формы, как в 1С: стандартные команды автозаполнения, затем элементы панели
  // в ее порядке (и видимые на панели, и «только в Еще»); у формы в конце - «Изменить форму...» и «Справка»
  function moreMenu(more) {
    var bar = more.closest(".fm-cmdbar");
    var barNode = bar && bar.dataset.name ? findNode(bar.dataset.name) : null;
    var host = bar && bar.parentElement ? bar.parentElement.closest("[data-name]") : null;
    var table = host ? findNode(host.dataset.name) : null;
    if (table && table.type !== "Table") table = null;
    var overflowed = {};
    (bar ? bar.querySelectorAll("[data-overflow][data-name]") : []).forEach(function (element) {
      overflowed[element.dataset.name] = true;
    });
    var items = bar && bar.dataset.autofill ? autoMoreItems(table, barNode) : [];
    if (barNode) items = items.concat(moreOf(shownItems(barNode), overflowed, barNode));
    var formBar = !table && (!barNode || barNode === FORM.commandBar || hasFormSource(barNode));
    var placed = placedCommands(barNode);
    if (formBar) {
      var excludedHere = Array.isArray(FORM.excludedCommands) ? FORM.excludedCommands : [];
      ["CustomizeForm", "Help"].forEach(function (command) {
        if (!placed[command] && excludedHere.indexOf(command) < 0) items.push(stdCommand(command, "Form.StandardCommand."));
      });
    }
    return menuOf(items);
  }

  document.addEventListener("click", function (event) {
    var popup = event.target.closest && event.target.closest(".fm-popup, .fm-droplist");
    if (event.target.closest && event.target.closest("body > .fm-menu")) return;
    var wasOpen = popup && popup.classList.contains("fm-open");
    closeMenus();
    if (!popup || wasOpen) return;
    openMenu(popup);
  });

  // Открытое меню переживает перерисовку: после переноса в подменю или из него, правки
  // свойства и отмены меню открывается заново у того же элемента со свежим составом. Ключ - имя подменю или поля
  // списка, у «Еще» - панель
  function openMenuKey() {
    var popup = document.querySelector(".fm-popup.fm-open, .fm-droplist.fm-open");
    return popup ? menuKeyOf(popup) : null;
  }

  function menuKeyOf(popup) {
    var bar = popup.closest(".fm-cmdbar");
    return [popup.dataset.name || "", popup.dataset.list || "", bar && bar.dataset.name || "",
      popup.classList.contains("fm-more"), popup.classList.contains("fm-all-actions")].join("|");
  }

  function reopenMenu(key) {
    var popups = document.querySelectorAll(".fm-popup, .fm-droplist");
    for (var i = 0; i < popups.length; i++) {
      // Подменю, ушедшее в «Еще» или на скрытую закладку, не раскрывается
      if (menuKeyOf(popups[i]) === key && popups[i].getClientRects().length) {
        openMenu(popups[i]);
        return;
      }
    }
  }

  function openMenu(popup) {
    var node = popup.dataset.name ? findNode(popup.dataset.name) : null;
    var menu = popup.classList.contains("fm-droplist") ? listMenu(findNode(popup.dataset.list), popup)
      : popup.classList.contains("fm-all-actions") ? overflowMenu(popup)
      : popup.classList.contains("fm-more") ? moreMenu(popup)
      : node && node.type === "Addition" ? menuOf(searchItems(node.additionSource || ""))
      : menuOf(node ? shownItems(node) : []);
    var rect = popup.getBoundingClientRect();
    menu.style.left = px(rect.left + window.scrollX);
    menu.style.top = px(rect.bottom + window.scrollY + 2);
    document.body.appendChild(menu);
    popup.classList.add("fm-open");
    // у правого края окна меню открывается влево
    var overflow = menu.getBoundingClientRect().right - document.documentElement.clientWidth;
    if (overflow > 0) menu.style.left = px(rect.right + window.scrollX - menu.getBoundingClientRect().width);
  }

  function formCommandBar() {
    var location = FORM.commandBarLocation || "Auto";
    if (location === "None") return null;
    var node = FORM.commandBar || { type: "AutoCommandBar", name: "ФормаКоманднаяПанель" };
    // Автозаполнение выключено и кнопок нет - в 1С панели нет совсем (так ее и убирают)
    if (node.autoFill === false && !shownItems(node).length) return null;
    // Снятые в «Составе команд» формы (`excludedCommands`) - нет и на панели
    var bar = renderCommandBar(node, {}, { standard: autoCommands(null), tail: true, place: "form", help: FORM.help === true });
    return bar ? { bar: bar, bottom: location === "Bottom" } : null;
  }

  // Таблица

  function columnsOf(table) {
    var columns = [];
    var bands = [];
    var prefix = table.name;

    function leavesOf(items) {
      var result = [];
      items.forEach(function (item) {
        if (item.type === "ColumnGroup") result = result.concat(leavesOf(shownItems(item)));
        else result.push(item);
      });
      return result;
    }

    // Строки вертикальной группы: вложенная горизонтальная группа - одна строка из нескольких
    // колонок (снимок 1С: «Имя» и «Тип данных» в строку, «Описание» под ними)
    function linesOf(items) {
      var result = [];
      items.forEach(function (item) {
        if (item.type !== "ColumnGroup") result.push([item]);
        else if ((item.group || "Horizontal") === "Vertical") result = result.concat(linesOf(shownItems(item)));
        else result.push(leavesOf(shownItems(item)));
      });
      return result.filter(function (line) { return line.length; });
    }

    // Скрытое в группе колонок скрывает и ее колонки: пометка колонки - по ней и по группам над ней
    function hiddenness(item, inherited) {
      return { user: inherited.user || item.userVisible === false, hidden: inherited.hidden || item.visible === false };
    }

    // fix - фиксация колонки в таблице (`fixingInTable`), у группы колонок - для всех ее колонок
    function walk(items, depth, inherited, hiddenBy) {
      items.forEach(function (item) {
        var fix = item.fixingInTable && item.fixingInTable !== "None" ? item.fixingInTable : inherited;
        var hide = hiddenness(item, hiddenBy);
        if (item.type !== "ColumnGroup") {
          columns.push({ leaves: [item], mode: "single", depth: depth, node: item, fix: fix, hide: hide });
          return;
        }
        var direction = item.group || "Horizontal";
        if (direction === "Horizontal") {
          var start = columns.length;
          var showBand = item.showInHeader === true && typeof item.title === "string";
          walk(shownItems(item), depth + (showBand ? 1 : 0), fix, hide);
          if (showBand && columns.length > start) bands.push({ node: item, start: start, end: columns.length, depth: depth, fix: fix });
        } else {
          var lines = direction === "Vertical" ? linesOf(shownItems(item)) : [leavesOf(shownItems(item))];
          var leaves = [].concat.apply([], lines);
          var mode = direction === "Vertical" ? "vertical" : "incell";
          if (leaves.length) columns.push({ leaves: leaves, lines: lines, mode: mode, depth: depth, node: item, fix: fix, hide: hide });
        }
      });
    }

    walk(shownItems(table), 0, null, { user: false, hidden: false });
    columns.forEach(function (column) {
      if (column.mode !== "vertical") {
        column.width = column.leaves.reduce(function (width, leaf) {
          return column.mode === "incell" ? width + leafWidth(leaf) : Math.max(width, leafWidth(leaf));
        }, 0);
        return;
      }
      column.width = column.lines.reduce(function (width, line) {
        return Math.max(width, line.reduce(function (sum, leaf) { return sum + leafWidth(leaf); }, 0));
      }, 0);
    });
    return { columns: columns, bands: bands, prefix: prefix };
  }

  // Флажок и картинка в колонке - узкие; номер строки - своей ширины
  function leafWidth(leaf) {
    return leaf.width || (lineNumber(leaf) ? COLUMN_WIDTH.lineNumber
      : narrowLeaf(leaf) ? NARROW_COLUMN : COLUMN_WIDTH[leaf.dataType || "string"]);
  }

  // Строка вертикальной группы из нескольких колонок - ячейки в ряд, доли - по ширинам колонок
  function splitLines(column) {
    return column.mode === "vertical" && column.lines.some(function (line) { return line.length > 1; });
  }

  function lineBox(parent, cls, count) {
    if (count < 2) return parent;
    var box = h("div", cls);
    parent.appendChild(box);
    return box;
  }

  function narrowLeaf(leaf) {
    return leaf.type === "CheckBoxField" || leaf.type === "PictureField";
  }

  function renderTable(node, ctx) {
    var wrap = h("div", "fm-table");
    if (node.horizontalStretch !== false) wrap.classList.add("fm-stretch");
    // Нерастягиваемая таблица с шириной - своей ширины, не больше места (договор БП, «Дополнительные
    // соглашения» шириной 100: 1000 px); без этого ее сжимает до колонки
    else if (node.width) {
      wrap.style.width = px(chars(node.width));
      wrap.style.maxWidth = "100%";
    }
    var location = node.titleLocation || "Auto";
    if (location !== "None" && location !== "Auto" && typeof node.title === "string") {
      var tableTitle = clip(h("div", "fm-field-title", titleOf(node) + ":"), "заголовок");
      applyFont(tableTitle, node.titleFont);
      wrap.appendChild(tableTitle);
    }

    var isList = (FORM.formKind === "ListForm" || FORM.formKind === "ChoiceForm") &&
      String(node.dataPath || node.name).indexOf("Объект.") !== 0;
    var barLocation = node.commandBarLocation || "Auto";
    var barNode = node.commandBar || { type: "AutoCommandBar", name: node.name + "КоманднаяПанель" };
    // Как у формы: без автозаполнения и без кнопок панели нет
    if (barNode.autoFill === false && !shownItems(barNode).length) barLocation = "None";
    var bar = null;
    if (barLocation !== "None") {
      // Команды, снятые в «Составе команд» таблицы, на панели не рисуются
      var standard = autoCommands(node);
      // Поле поиска справа - только при автозаполнении панели; без него - только явное дополнение
      // «Строка поиска» на своем месте (владелец: «Области макета» без поиска, «Поля набора» - с ним)
      // У дерева значений поля поиска нет (Ф-2: дерево формы-консоли; на снимках поиск - только у списков)
      var autoSearch = barNode.autoFill !== false && !hasSearchAddition(barNode) &&
        ["None", "PullFromTop"].indexOf(node.searchStringLocation) < 0 && (isList || node.representation !== "Tree");
      bar = renderCommandBar(barNode, ctx, { standard: standard, tail: true, search: autoSearch, place: "table" });
    }
    if (bar && barLocation !== "Bottom") wrap.appendChild(bar);

    var layout = columnsOf(node);
    var grid = h("div", "fm-table-grid");
    var columns = layout.columns;
    if (!columns.length) columns = [{ leaves: [], mode: "single", depth: 0, width: 20 }];
    // Ширина колонки в 1С - нижняя граница, и колонка не уже своего заголовка; не поместились -
    // горизонтальная прокрутка (замечание раскладки)
    // Дерево: отступ уровня и значок раскрытия - в первой колонке, и она не уже своего содержимого вместе с ними
    // (узкая колонка-флажок отдавала отступ соседней колонке - флажок наезжал на имя)
    grid.style.gridTemplateColumns = columns.map(function (column, index) {
      var track = columnTrack(column);
      return index === 0 && node.representation === "Tree" ? track.replace(/^minmax\([^,]+,/, "minmax(max-content,") : track;
    }).join(" ");

    function columnTrack(column) {
      var min = node.header === false ? px(chars(column.width)) : "auto";
      // Колонка-картинка, флажок без своей ширины и номер строки не растягиваются (в 1С - узкие)
      var picture = column.leaves.length && column.leaves.every(function (leaf) {
        return leaf.type === "PictureField" || (leaf.type === "CheckBoxField" && !leaf.width) ||
          (lineNumber(leaf) && !leaf.horizontalStretch);
      });
      // Флажок с текстом в шапке - не уже заголовка (договор БП, «Подписано»)
      var titled = column.leaves.some(function (leaf) {
        return leaf.type === "CheckBoxField" && !leaf.headerPicture && leaf.showInHeader !== false && !!titleOf(leaf);
      });
      if (picture) return "minmax(" + (titled && node.header !== false ? "max-content" : min) + ", " + px(chars(column.width)) + ")";
      // Колонка с «Растягивать: Нет» держит свою ширину, остаток забирают растягиваемые (договор БП:
      // «Номер», «Дата» своей ширины, «Комментарий» - остаток)
      var fixed = column.leaves.length && column.leaves.every(function (leaf) { return leaf.horizontalStretch === false; });
      if (fixed) return "minmax(" + min + ", " + px(chars(column.width)) + ")";
      return "minmax(" + min + ", " + column.width + "fr)";
    }
    var naturalWidth = columns.reduce(function (sum, column) { return sum + chars(column.width); }, 0);
    // Колонки держат естественную ширину, таблица прокручивается в своей области; окну таблица
    // отдает не больше TABLE_MAX (распорка), как в 1С: окно не растет по колонкам (ПТУ БП - 28)
    grid.style.minWidth = px(naturalWidth);

    var headerRows = 1 + layout.bands.reduce(function (depth, band) { return Math.max(depth, band.depth + 1); }, 0);
    var row = 1;
    // Шапка в 1С: заголовки слева и сверху; у группы колонок «В ячейке» - заголовки через запятую,
    // у вертикальной - строками одна под другой
    if (node.header !== false) {
      var headed = columns.map(function (column) {
        return column.leaves.some(function (leaf) { return leaf.showInHeader !== false; });
      });
      var covered = {};
      layout.bands.forEach(function (band) {
        var cell = h("div", "fm-th fm-th-band");
        var bandTitle = clip(h("span", band.node.headerPicture ? "fm-th-picture" : "", titleOf(band.node)), "заголовок колонки");
        if (band.node.headerPicture) bandTitle.insertBefore(pictureOrStub(band.node.headerPicture), bandTitle.firstChild);
        cell.appendChild(bandTitle);
        // «Горизонтальное положение в шапке» группы колонок («Служебная», «Информация» на снимке 1С - по центру)
        if (band.node.headerHorizontalAlign === "Center" || band.node.headerHorizontalAlign === "Right") {
          cell.style.justifyContent = band.node.headerHorizontalAlign === "Center" ? "center" : "flex-end";
          cell.style.textAlign = band.node.headerHorizontalAlign.toLowerCase();
        }
        if (band.node.headerBackColor) cell.style.backgroundColor = paint(band.node.headerBackColor);
        cell.style.gridColumn = (band.start + 1) + " / " + (band.end + 1);
        // У колонок под полосой нет своих заголовков - полоса на всю высоту шапки
        var inner = layout.bands.some(function (other) {
          return other !== band && other.depth > band.depth && other.start >= band.start && other.end <= band.end;
        });
        var empty = !inner && !headed.slice(band.start, band.end).some(Boolean);
        cell.style.gridRow = empty ? (band.depth + 1) + " / " + (headerRows + 1) : String(band.depth + 1);
        if (empty) for (var i = band.start; i < band.end; i++) covered[i] = true;
        if (band.fix) cell.dataset.fix = band.fix;
        grid.appendChild(mark(band.node, cell));
      });
      columns.forEach(function (column, index) {
        if (covered[index]) return;
        var cell = h("div", "fm-th");
        // Колонка с «Отображать в шапке» = Ложь заголовка в шапке не дает (ПТУ БП: у вертикальной
        // группы «Цена» в шапке только «Цена», без «по документу» и «отклонение»)
        // Заголовок колонки с положением «Нет» в шапке не пишется; картинка шапки - перед ним
        var headed = column.leaves.filter(function (leaf) { return leaf.showInHeader !== false; });
        var titles = headed.map(function (leaf) { return leaf.titleLocation === "None" ? "" : titleOf(leaf, layout.prefix); });
        var pictures = headed.map(function (leaf) { return leaf.headerPicture || null; });
        // Колонки группы без заголовков в шапке, сама группа с «Отображать в шапке» - в шапке заголовок группы
        // (Г-13 БП: «Договор / Статья расходов» списания и поступления)
        // У таблицы без колонок колонка-заглушка без узла (отбор компоновщика)
        var groupHeaded = !headed.length && !!column.node && column.node.type === "ColumnGroup" && column.node.showInHeader === true
          && typeof column.node.title === "string";
        // Оформление заголовка в шапке: положение и цвет фона - колонки или группы колонок
        var looks = headed.slice();
        if (groupHeaded) { titles = [titleOf(column.node)]; pictures = [column.node.headerPicture || null]; looks = [column.node]; }
        if (!titles.length) { titles = [""]; pictures = [null]; looks = [null]; }
        if (column.mode === "incell") {
          titles = [titles.filter(Boolean).join(", ")];
          pictures = [pictures.filter(Boolean)[0] || null];
          looks = [looks[0] || null];
        }
        var headerSpan = function (title, picture, look) {
          var span = clip(h("span", picture ? "fm-th-picture" : "", title), "заголовок колонки");
          // Одна картинка без текста - по центру колонки (владелец; снимки: в первой строке шапки)
          if (picture && !title) span.classList.add("fm-th-icon");
          if (picture) span.insertBefore(pictureOrStub(picture), span.firstChild);
          if (look) alignCell(span, look.headerHorizontalAlign);
          if (look && look.headerBackColor) span.style.backgroundColor = paint(look.headerBackColor);
          return span;
        };
        // Группа колонок закрашивает всю ячейку шапки, колонка одна в ячейке - тоже
        var cellLook = column.mode === "single" ? column.leaves[0] : column.node;
        if (cellLook && cellLook.headerBackColor) cell.style.backgroundColor = paint(cellLook.headerBackColor);
        if (splitLines(column) && !groupHeaded) {
          column.lines.forEach(function (line) {
            var shown = line.filter(function (leaf) { return leaf.showInHeader !== false; });
            var box = lineBox(cell, "fm-th-line", shown.length);
            shown.forEach(function (leaf) {
              var span = headerSpan(leaf.titleLocation === "None" ? "" : titleOf(leaf, layout.prefix), leaf.headerPicture || null, leaf);
              if (box !== cell) span.style.flex = leafWidth(leaf) + " 1 0px";
              else span.style.minWidth = px(chars(column.width));
              box.appendChild(span);
            });
          });
        } else {
          titles.forEach(function (title, i) {
            var span = headerSpan(title, pictures[i], looks[i]);
            span.style.minWidth = px(chars(column.width));
            cell.appendChild(span);
          });
        }
        cell.style.gridColumn = String(index + 1);
        cell.style.gridRow = (column.depth + 1) + " / " + (headerRows + 1);
        if (column.fix) cell.dataset.fix = column.fix;
        grid.appendChild(markColumn(column, cell));
      });
      row = headerRows + 1;
    }

    var sample = Array.isArray(node.sample) ? node.sample : [];
    var tree = node.representation === "Tree";
    // Режим «Правки»: пример строк - из «стало», тень перенесенной и удаленная колонка в нем места не занимают -
    // иначе значения правее съезжают на колонку (обкатка 06.11.2026)
    var marks = mode === "diff" ? diffMarks() : {};
    sample.forEach(function (values, r) {
      values = Array.isArray(values) ? values : [];
      var leafIndex = 0;
      columns.forEach(function (column, index) {
        var cell = h("div", "fm-td");
        if (r === 0) cell.classList.add("fm-current-row");
        if (r % 2 === 1) cell.classList.add("fm-even-row");
        var parts = column.leaves.map(function (leaf) {
          var found = marks[leaf.name];
          if (found && (found.op === "ghost" || found.op === "removed")) return { leaf: leaf, value: "" };
          var value = values[leafIndex++];
          return { leaf: leaf, value: value === undefined || value === null ? "" : value };
        });
        if (column.mode === "incell") {
          // Картинка и флажок в ячейке - собой, текст соседних колонок подряд через запятую (обкатка: пиктограмма
          // вида перед именем)
          var texts = [];
          var flush = function () {
            var text = texts.filter(Boolean).join(", ");
            if (text) cell.appendChild(h("span", "", text));
            texts = [];
          };
          parts.forEach(function (part) {
            if (!pictureLeaf(part.leaf)) {
              texts.push(cellText(part.leaf, part.value));
              return;
            }
            flush();
            cell.appendChild(cellValue(part.leaf, part.value));
          });
          flush();
          if (parts.length > 1 && parts.some(function (part) { return pictureLeaf(part.leaf); })) cell.classList.add("fm-td-incell");
        } else if (splitLines(column)) {
          var next = 0;
          column.lines.forEach(function (line) {
            var box = lineBox(cell, "fm-td-line", line.length);
            line.forEach(function () {
              var part = parts[next++];
              var value = cellValue(part.leaf, part.value);
              if (box !== cell) value.style.flex = leafWidth(part.leaf) + " 1 0px";
              box.appendChild(value);
            });
          });
        } else {
          parts.forEach(function (part) { cell.appendChild(cellValue(part.leaf, part.value)); });
        }
        // Дерево: пример без уровней - первая строка раскрытый родитель, остальные - его подчиненные
        if (index === 0 && tree && cell.firstChild) {
          if (r === 0) cell.firstChild.insertBefore(icon("expanded"), cell.firstChild.firstChild);
          else cell.classList.add("fm-tree-child");
        }
        // У группы «в ячейке» выравнивание - по первой текстовой колонке: число в картинке значений - не число ячейки
        var lead = column.mode === "incell" ? parts.filter(function (part) { return !pictureLeaf(part.leaf); })[0] : parts[0];
        if (lead && numericPart(lead)) cell.classList.add("fm-number");
        cell.style.gridColumn = String(index + 1);
        cell.style.gridRow = String(row);
        if (column.fix) cell.dataset.fix = column.fix;
        grid.appendChild(cell);
      });
      row++;
    });
    // Свободное место таблицы - без линий сетки, как в 1С
    var emptyRows = Math.max(0, (node.heightInTableRows || (sample.length ? 0 : 5)) - sample.length);
    if (emptyRows) {
      var filler = h("div", "fm-table-empty");
      filler.style.gridColumn = "1 / " + (columns.length + 1);
      filler.style.gridRow = String(row);
      filler.style.height = "calc(var(--table-row) * " + emptyRows + ")";
      grid.appendChild(filler);
      row++;
    }

    if (node.footer) {
      columns.forEach(function (column, index) {
        var cell = h("div", "fm-tf");
        column.leaves.forEach(function (leaf) { cell.appendChild(footerSpan(leaf)); });
        // Колонка одна в ячейке - цвет фона подвала на всю ячейку
        if (column.leaves.length === 1 && column.leaves[0].showInFooter !== false && column.leaves[0].footerBackColor) {
          cell.style.backgroundColor = paint(column.leaves[0].footerBackColor);
        }
        cell.style.gridColumn = String(index + 1);
        cell.style.gridRow = String(row);
        if (column.fix) cell.dataset.fix = column.fix;
        grid.appendChild(cell);
      });
    }

    // Оформление таблицы: линии сетки, чередование строк, цвета, шрифт строк и заголовка
    if (node.horizontalLines === false) grid.classList.add("fm-no-hlines");
    if (node.verticalLines === false) grid.classList.add("fm-no-vlines");
    if (node.useAlternationRowColor) grid.classList.add("fm-alternate");
    if (node.backColor) grid.style.backgroundColor = paint(node.backColor);
    if (node.textColor) grid.style.color = paint(node.textColor);
    applyFont(grid, node.font);
    var view = h("div", "fm-table-view");
    if (node.borderColor) view.style.borderColor = paint(node.borderColor);
    view.appendChild(grid);
    wrap.appendChild(view);
    if (!FORM.width) {
      var spacer = h("div", "fm-table-spacer");
      spacer.style.width = px(Math.min(naturalWidth + 2, TABLE_MAX));
      wrap.appendChild(spacer);
    }
    var scroll = h("div", "fm-table-hscroll");
    scroll.appendChild(h("div", "fm-table-hscroll-thumb"));
    wrap.appendChild(scroll);
    tableScroll(view, grid, scroll);
    if (bar && barLocation === "Bottom") wrap.appendChild(bar);
    // Нормальная ширина для «Горизонтально, если возможно» - колонки целиком
    wrap.dataset.normal = String(node.width ? chars(node.width) : naturalWidth + 2);
    return mark(node, wrap);
  }

  // Положение текста в ячейке шапки или подвала: «Центр», «Право», «Лево»; «Авто» - как есть
  function alignCell(element, align) {
    var side = { Left: "left", Center: "center", Right: "right" }[align];
    if (!side) return;
    element.style.textAlign = side;
    element.style.justifyContent = { left: "flex-start", center: "center", right: "flex-end" }[side];
  }

  // Ячейка подвала колонки: «Отображать в подвале» = Ложь - пустая; картинка подвала - перед текстом,
  // положение, цвета и шрифт подвала
  function footerSpan(leaf) {
    var span = h("span", "");
    if (leaf.showInFooter === false) return span;
    if (leaf.footerPicture) {
      span.className = "fm-tf-picture";
      span.appendChild(pictureOrStub(leaf.footerPicture));
    }
    span.appendChild(document.createTextNode(leaf.footerText || ""));
    alignCell(span, leaf.footerHorizontalAlign);
    if (leaf.footerBackColor) span.style.backgroundColor = paint(leaf.footerBackColor);
    if (leaf.footerTextColor) span.style.color = paint(leaf.footerTextColor);
    applyFont(span, leaf.footerFont);
    return span;
  }

  // Прокрутка таблицы в HTML: колесом, тачпадом и полосой; закрепленные колонки стоят на месте.
  // Смещение закрепленной колонки мерится при первой прокрутке - тогда таблица точно видна
  function tableScroll(view, grid, scroll) {
    var thumb = scroll.firstChild;
    var pinned = false;
    function pin() {
      if (pinned) return;
      pinned = true;
      var width = grid.scrollWidth;
      grid.querySelectorAll("[data-fix]").forEach(function (cell) {
        cell.classList.add("fm-fixed-col");
        if (cell.dataset.fix === "Right") cell.style.right = px(width - cell.offsetLeft - cell.offsetWidth);
        else cell.style.left = px(cell.offsetLeft);
      });
    }
    view.addEventListener("scroll", function () {
      pin();
      var track = scroll.clientWidth - 32;
      thumb.style.marginLeft = px(track * view.scrollLeft / Math.max(1, view.scrollWidth));
    });
    scroll.addEventListener("mousedown", function (event) {
      var start = event.clientX;
      var origin = view.scrollLeft;
      var ratio = view.scrollWidth / Math.max(1, scroll.clientWidth - 32);
      function move(next) { view.scrollLeft = origin + (next.clientX - start) * ratio; }
      function up() {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      }
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
      event.preventDefault();
    });
  }

  function pictureLeaf(leaf) { return leaf.type === "PictureField" || leaf.type === "CheckBoxField"; }

  // Число в ячейке: колонка числового типа или без типа (поле надписи) с числом в примере
  function numericPart(part) {
    if (part.leaf.dataType) return part.leaf.dataType === "number";
    return part.value !== "" && looksNumber(part.value);
  }

  // Колонка, скрытая сама или группой над ней, помечена в шапке, как скрытые элементы формы
  function markColumn(column, cell) {
    var node = column.mode === "single" ? column.leaves[0] : column.node;
    if (!node) return cell;
    mark(node, cell);
    if (column.hide && column.hide.user) cell.classList.add("fm-user-hidden");
    if (column.hide && column.hide.hidden) cell.classList.add("fm-hidden");
    return cell;
  }

  // Булево поле ввода в таблице 1С показывает «Да» / «Нет» (или по формату); флажок - только у поля флажка
  function cellText(leaf, value) {
    if (leaf.dataType === "boolean" && value !== "") return booleanText(leaf, value);
    return String(value);
  }

  function cellValue(leaf, value) {
    // Ячейка коллекции - внутри своей обертки: отступы ячейки таблицы не расширяют окно ячейки (как у флажка)
    if (leaf.type === "PictureField" && leaf.valuesPicture) {
      var holder = h("span", "");
      holder.appendChild(valuesPictureNode(leaf.valuesPicture, value));
      return holder;
    }
    if (leaf.type === "CheckBoxField") {
      var box = h("span", "");
      var check = h("span", "fm-check");
      if (truthy(value)) check.innerHTML = ICONS.check;
      box.appendChild(check);
      return box;
    }
    // «Гиперссылка ячейки» - значение ссылкой; «Автовысота ячейки» - длинное значение по словам
    var span = h("span", leaf.hyperlink || leaf.cellHyperlink ? "fm-hyperlink" : "", cellText(leaf, value));
    if (leaf.autoCellHeight) span.classList.add("fm-td-wrap");
    return span;
  }

  // Форма

  // Ширина формы меньше минимальной - окно минимальной ширины, как в 1С (форма шириной 10 открывается по
  // содержимому): поиск делением пополам между заданной шириной и естественной (окно без ширины формы) - шире
  // естественной окно не становится. «Помещается» - вылезает не больше, чем в естественной ширине: выступы, которые
  // есть при любой ширине (рамка группы с цветом фона), не в счет. Прямо на величину вылезания не расширить: в более
  // широком окне поля снова растут
  // Заданная ширина не уже естественной или вылезает не больше нее - окно заданной ширины (обкатка:
  // у формы с выступом при любой ширине окно оставалось естественным, и ширина 150-600 ничего не меняла)
  function renderForm() {
    var menuKey = openMenuKey();
    closeMenus();
    formWidened = 0;
    var asked = FORM.width ? chars(FORM.width) + 14 : 0;
    var body = layoutForm(asked);
    var over = FORM.width ? formOverflow(body) : 0;
    if (over > 0) {
      var low = document.querySelector(".fm-window").getBoundingClientRect().width;
      var natural = formOverflow(layoutForm(0));
      var high = Math.ceil(document.querySelector(".fm-window").getBoundingClientRect().width);
      if (high > low && over > natural + 1) {
        while (high - low > 4) {
          var middle = Math.round((low + high) / 2);
          if (formOverflow(layoutForm(middle)) <= natural + 1) high = middle;
          else low = middle;
        }
        formWidened = high;
        body = layoutForm(formWidened);
      } else {
        body = layoutForm(asked);
      }
    }
    publish();
    // Без высоты формы доли строк - естественные высоты; полосы прокрутки таблиц расставляет
    // publish, после них высоты другие - перемерить
    if (!FORM.height) {
      stretchRows(body);
      publish();
    }
    if (menuKey) reopenMenu(menuKey);
  }

  // Раскладка окна формы без замечаний; `width` - ширина окна, px (0 - по содержимому)
  function layoutForm(width) {
    var root = document.getElementById("fm-root");
    root.innerHTML = "";
    renderLegend(root);
    var win = h("div", "fm-window");
    if (width) win.style.width = px(width);

    // «Отображать заголовок: Нет» - без заголовка и кнопок навигации; «Отображать кнопку закрытия: Нет» - без крестика
    var titled = FORM.showTitle !== false;
    var caption = h("div", "fm-caption");
    if (titled) {
      ["back", "forward", "star"].forEach(function (name) {
        var item = icon(name);
        item.classList.add("fm-caption-icon");
        caption.appendChild(item);
      });
    }
    caption.appendChild(h("div", "fm-caption-title", titled ? FORM.title || "Форма" : ""));
    ["link", "menu", "close"].filter(function (name) { return name !== "close" || FORM.showCloseButton !== false; })
      .forEach(function (name) {
        var item = icon(name);
        item.classList.add("fm-caption-icon");
        caption.appendChild(item);
      });
    win.appendChild(caption);

    var body = h("div", "fm-body fm-group-content fm-vertical fm-through");
    // Высота формы - в строках (17 px): окно не ниже нее, растягиваемые по высоте делят остаток
    // (снимки 1С: 47 строк - 800 px под заголовком окна)
    if (FORM.height) body.style.minHeight = px(FORM.height * 17);
    var command = formCommandBar();
    if (command && !command.bottom) body.appendChild(command.bar);
    var content = body;
    if (FORM.group && FORM.group !== "Vertical") {
      content = h("div", "fm-group-content " + childrenClass(FORM.group));
      body.appendChild(content);
    }
    renderItems(content, Array.isArray(FORM.items) ? FORM.items : [], {}, content !== body);
    if (command && command.bottom) body.appendChild(command.bar);
    win.appendChild(body);
    mark({ name: "Форма", type: "Form" }, win);
    root.appendChild(win);
    applyDiff();
    titleLines(body);
    alignThrough(body);
    groupWidths(body);
    if (switchIfPossible(body)) alignThrough(body);
    softGrowth(body);
    stretchRows(body);
    pagesHeight();
    fixFormHeight(body);
    return body;
  }

  // Насколько элементы вылезают за правый край формы или наезжают на соседа по строке - на всех закладках.
  // Командные панели не в счет: лишние кнопки уходят в «Еще»; таблица сжимается со своей прокруткой -
  // меряется сама, а не колонки
  function formOverflow(body) {
    var box = body.getBoundingClientRect();
    var limit = box.right - parseFloat(getComputedStyle(body).paddingRight);
    var over = 0;
    var measure = function () {
      body.querySelectorAll(".fm-item").forEach(function (element) {
        if (!element.offsetParent || element.parentElement.closest(".fm-cmdbar, .fm-table")) return;
        over = Math.max(over, element.getBoundingClientRect().right - limit);
      });
      // Элемент уже своего содержимого - текст наезжает на соседа; в узком окне 1С так не бывает
      // (реализация БП шириной 20). Значение поля ввода обрезается само, флажок и
      // переключатель - рисунок своего размера: не в счет
      body.querySelectorAll(".fm-item:not(.fm-input):not(.fm-control)").forEach(function (element) {
        if (!element.offsetParent || element.closest(".fm-cmdbar, .fm-table")) return;
        over = Math.max(over, element.scrollWidth - element.clientWidth);
      });
    };
    measure();
    document.querySelectorAll(".fm-pages").forEach(function (element) {
      var current = currentPage[element.dataset.name];
      element.querySelectorAll(":scope > .fm-page").forEach(function (page) {
        setPageSilently(element, page.dataset.page);
        measure();
      });
      setPageSilently(element, current);
    });
    return over > 1 ? over : 0;
  }

  // Без высоты формы закладки одной высоты - самой высокой: форма не прыгает при переключении (Г-11 БП, шесть
  // закладок «Принятия к учету ОС»). Вложенные панели - первыми; лишнее место - внизу закладки
  function pagesHeight() {
    if (FORM.height) return;
    var panels = Array.prototype.slice.call(document.querySelectorAll(".fm-pages")).reverse();
    panels.forEach(function (element) {
      var current = currentPage[element.dataset.name];
      var pages = element.querySelectorAll(":scope > .fm-page");
      if (pages.length < 2) return;
      var height = 0;
      Array.prototype.forEach.call(pages, function (page) {
        page.style.minHeight = "";
        setPageSilently(element, page.dataset.page);
        height = Math.max(height, page.getBoundingClientRect().height);
      });
      setPageSilently(element, current);
      Array.prototype.forEach.call(pages, function (page) { page.style.minHeight = px(height); });
    });
  }

  // Высота тела формы - точная: при одной минимальной Chrome отдает остаток обычным строкам
  // сетки, а не растягиваемой. Не ниже содержимого самой высокой закладки - окно 1С одно на все
  function fixFormHeight(body) {
    if (!FORM.height) return;
    var height = body.offsetHeight;
    document.querySelectorAll(".fm-pages").forEach(function (element) {
      var current = currentPage[element.dataset.name];
      element.querySelectorAll(":scope > .fm-page").forEach(function (page) {
        setPageSilently(element, page.dataset.page);
        height = Math.max(height, body.offsetHeight);
      });
      setPageSilently(element, current);
    });
    body.style.height = px(height);
  }

  // Сетка сквозного выравнивания: строка растягиваемого по высоте элемента забирает остаток
  // высоты. Строка сетки - поле с заголовком слева (две ячейки) или элемент на всю ширину.
  // При высоте формы растягиваемые строки делят остаток поровну. Без нее доля строки - ее
  // естественная высота: несколько строк `1fr` в сетке без заданной высоты выровнялись бы по самой
  // высокой, а так без лишнего места строки своей высоты, лишнее место (соседняя колонка выше)
  // делится по росту. Видимые сетки меряются как есть (предку закладок - высота открытой), сетки
  // на скрытых закладках - при показанных закладках
  function stretchRows(body) {
    var grids = [body].concat(Array.prototype.slice.call(body.querySelectorAll(".fm-through")));
    grids.forEach(function (grid) { grid.style.gridTemplateRows = ""; });
    var templates = grids.map(function (grid) { return grid.offsetParent || grid === body ? rowsOf(grid) : null; });
    document.body.classList.add("fm-pages-pass");
    templates = templates.map(function (template, index) { return template === null ? rowsOf(grids[index]) : template; });
    document.body.classList.remove("fm-pages-pass");
    grids.forEach(function (grid, index) { grid.style.gridTemplateRows = templates[index]; });

    function rowsOf(grid) {
      var rows = [];
      Array.prototype.forEach.call(grid.children, function (child) {
        if (child.classList.contains("fm-name-tag") || child.classList.contains("fm-measure")) return;
        if (child.classList.contains("fm-popup-close")) return;
        if (getComputedStyle(child).display === "none") return;
        var grows = child.classList.contains("fm-vstretch") && !child.classList.contains("fm-collapsed") &&
          !child.classList.contains("fm-popup-group");
        var share = FORM.height ? 1 : Math.max(1, Math.round(child.getBoundingClientRect().height));
        rows.push(grows ? "minmax(min-content, " + share + "fr)" : "auto");
      });
      return rows.every(function (row) { return row === "auto"; }) ? "" : rows.join(" ");
    }
  }

  // Ширина группы в 1С - ширина ее полей, колонка заголовков сверх нее, как у поля ввода (снимок 1С:
  // группа настроек при ширине 30 - заголовки 107 px и поля 320 px до одного края)
  function groupWidths(body) {
    var measurer = h("span", "fm-field-title fm-measure");
    body.appendChild(measurer);
    // Меряются и скрытые закладки, и свернутые группы
    document.body.classList.add("fm-layout-pass");
    body.querySelectorAll(".fm-group[data-width]").forEach(function (group) {
      if (group.classList.contains("fm-weighted")) return;
      // Первая сетка с полями: заголовки бывают во вложенной группе (группа настроек)
      var grids = group.querySelectorAll(".fm-through");
      for (var i = 0; i < grids.length; i++) {
        var titles = grids[i].querySelectorAll(":scope > .fm-field.fm-tl-Left > .fm-field-title");
        if (!titles.length) continue;
        var widest = Array.prototype.reduce.call(titles, function (max, title) {
          if (title.dataset.width) return Math.max(max, parseFloat(title.dataset.width));
          measurer.textContent = title.textContent;
          return Math.max(max, measurer.getBoundingClientRect().width);
        }, 0);
        var gap = parseFloat(getComputedStyle(grids[i]).columnGap) || 0;
        // отступ сетки от края группы (свертываемая группа сдвигает содержимое)
        var indent = grids[i].getBoundingClientRect().left - group.getBoundingClientRect().left + boxPadding(grids[i]);
        var full = px(parseFloat(group.dataset.width) + Math.ceil(widest) + gap + Math.max(0, indent));
        group.style.width = group.classList.contains("fm-width-cap") ? "min(" + full + ", 100%)" : full;
        return;
      }
    });
    document.body.classList.remove("fm-layout-pass");
    measurer.remove();
  }

  // Строка и ссылка тянутся по месту до своего предела и в столбце, и в строке группы (закладка «Ширины»
  // витрины: строки 12-150 - 40 символов, рядом с флажком тоже). Группа с оформлением без растягиваемого
  // содержимого растягивается «в тех же пределах», что наибольший подчиненный (7.7.13.4), поле в строке
  // группы - не дальше заголовка с полем на пределе: предел каждого - ширина с полями, раскрытыми до
  // предела. Нормальные ширины (окно без ширины формы, «если возможно») остаются прежними
  function softGrowth(body) {
    var targets = Array.prototype.filter.call(body.querySelectorAll(".fm-group.fm-hug, .fm-horizontal > .fm-field.fm-soft"),
      function (element) { return element.matches(".fm-field") || element.querySelector(".fm-input[data-chrome]"); });
    if (!targets.length) return;
    document.body.classList.add("fm-layout-pass");
    var values = Array.prototype.map.call(body.querySelectorAll(".fm-input[data-chrome]"), function (box) {
      var value = box.querySelector(":scope > .fm-input-value");
      var saved = value.style.width;
      value.style.width = px(parseFloat(box.style.maxWidth) - parseFloat(box.dataset.chrome));
      return [value, saved];
    });
    var saved = targets.map(function (element) {
      var width = element.style.width;
      element.style.width = "max-content";
      return width;
    });
    var widths = targets.map(function (element) { return Math.ceil(element.getBoundingClientRect().width); });
    targets.forEach(function (element, index) { element.style.width = saved[index]; });
    values.forEach(function (pair) { pair[0].style.width = pair[1]; });
    targets.forEach(function (element, index) {
      element.style.maxWidth = px(widths[index]);
      element.classList.add("fm-soft-grow");
    });
    document.body.classList.remove("fm-layout-pass");
  }

  // «Горизонтально, если возможно»: группа в строку, если нормальные ширины всех подчиненных с
  // интервалами помещаются в ширину, которую дает ей родитель, иначе вся группа в столбец -
  // частичного переноса нет (руководство разработчика 8.3.27, 7.7.13.2). Решается после
  // раскладки сверху вниз: перестройка внешней группы меняет ширину внутренних. На время прохода
  // показаны все закладки и свернутые группы - решение не зависит от того, что открыто.
  // Группа без заголовка в столбце - как вертикальная: входит в сквозную колонку заголовков (без этого
  // заголовки ее полей стояли каждый сам по себе, а первое поле - по колонке строки);
  // итог - сколько таких групп: колонку тогда надо пересчитать. Группа с заголовком - по-прежнему своей
  // раскладкой: снимка 1С такой группы в столбце нет (на витрине «Ширины» 1С держит ее строкой)
  function switchIfPossible(body) {
    var joined = 0;
    document.body.classList.add("fm-layout-pass");
    body.querySelectorAll(".fm-group-content.fm-wrap").forEach(function (content) {
      var children = flowChildren(content);
      if (children.length < 2) return;
      if (contentNormal(content) <= content.clientWidth + 1) return;
      content.classList.remove("fm-horizontal", "fm-wrap");
      content.classList.add("fm-vertical");
      var titled = content.parentElement && content.parentElement.querySelector(":scope > .fm-group-title");
      if (content.dataset.through !== "0" && !titled) {
        content.classList.add("fm-through");
        joined++;
      }
      Array.prototype.forEach.call(content.children, function (child) {
        if (child.classList.contains("fm-splitter-v")) child.className = "fm-splitter-h";
        if (child.classList.contains("fm-weighted")) {
          child.style.flex = "";
          child.classList.remove("fm-weighted");
        }
      });
    });
    document.body.classList.remove("fm-layout-pass");
    return joined;
  }

  function flowChildren(content) {
    return Array.prototype.filter.call(content.children, function (child) {
      if (child.classList.contains("fm-name-tag") || child.classList.contains("fm-popup-close")) return false;
      if (/fm-splitter/.test(child.className)) return false;
      return getComputedStyle(child).display !== "none";
    });
  }

  // Нормальная ширина элемента: таблица - по колонкам, группа и закладки - по подчиненным,
  // остальное - по содержимому без растягивания
  // Для разделителя таблица считается узкой (tableFloor): у нее своя прокрутка
  var tableFloor = 0;
  function normalWidth(element) {
    if (element.dataset.normal) return tableFloor || parseFloat(element.dataset.normal);
    if (element.classList.contains("fm-pages")) {
      var pages = element.querySelectorAll(":scope > .fm-page");
      return Array.prototype.reduce.call(pages, function (max, page) {
        return Math.max(max, contentNormal(page) + page.offsetWidth - page.clientWidth + boxPadding(page));
      }, 0);
    }
    // Всплывающая группа на форме - только ссылка-заголовок, содержимое во всплывающем окне
    if (element.classList.contains("fm-popup-group")) {
      var link = element.querySelector(":scope > .fm-group-title");
      return link ? contentWidth(link) : 0;
    }
    var content = element.classList.contains("fm-group") ? element.querySelector(":scope > .fm-group-content") : null;
    if (content) {
      var title = element.querySelector(":scope > .fm-group-title");
      return Math.max(contentNormal(content) + boxPadding(content), title ? contentWidth(title) : 0);
    }
    return contentWidth(element);
  }

  function contentNormal(content) {
    var children = flowChildren(content);
    var style = getComputedStyle(content);
    if (content.classList.contains("fm-horizontal")) {
      var gap = parseFloat(style.columnGap) || 0;
      return children.reduce(function (sum, child) { return sum + normalWidth(child); }, 0) + gap * Math.max(0, children.length - 1);
    }
    // Сквозное выравнивание: поле с заголовком слева раскладывается в две колонки сетки
    var titles = 0;
    var controls = 0;
    var whole = 0;
    children.forEach(function (child) {
      if (getComputedStyle(child).display !== "contents") {
        whole = Math.max(whole, normalWidth(child));
        return;
      }
      Array.prototype.forEach.call(child.children, function (part) {
        if (part.classList.contains("fm-name-tag")) return;
        if (part.classList.contains("fm-field-title")) titles = Math.max(titles, contentWidth(part));
        else controls = Math.max(controls, contentWidth(part));
      });
    });
    var pair = controls ? titles + (parseFloat(style.columnGap) || 0) + controls : 0;
    return Math.max(whole, pair);
  }

  function contentWidth(element) {
    var saved = element.style.cssText;
    element.style.flex = "none";
    element.style.width = "min-content";
    var width = element.getBoundingClientRect().width;
    element.style.cssText = saved;
    return width;
  }

  function boxPadding(element) {
    var style = getComputedStyle(element);
    return (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  }

  // Заголовок в несколько строк (Г-2). Перевод строки в тексте - ширина по самой длинной строке. «Высота
  // заголовка» N - самая узкая ширина, при которой текст ложится в N строк: 1С делит его примерно поровну и
  // тогда, когда он помещается в одну строку (БП: «Назначение↵платежа», «Содержание↵записи КУДиР»).
  // Мерится вне раскладки - и на скрытых закладках
  function titleLines(body) {
    var measurer = h("div", "fm-field-title fm-measure fm-title-lines");
    body.appendChild(measurer);
    body.querySelectorAll(".fm-field-title.fm-title-lines").forEach(function (title) {
      if (title === measurer) return;
      var best = linesWidth(measurer, title.textContent, parseInt(title.dataset.lines, 10) || 0);
      title.style.width = px(best);
      title.dataset.width = String(best);
    });
    measurer.remove();
  }

  // Самая узкая ширина, при которой текст ложится в lines строк (0 - по переводам строк);
  // measurer - блок заголовка с переносом по словам, уже в документе
  function linesWidth(measurer, text, lines) {
    measurer.textContent = text;
    measurer.style.width = "max-content";
    var full = measurer.getBoundingClientRect().width;
    if (lines <= 1) return Math.ceil(full);
    measurer.textContent = "X";
    var line = measurer.getBoundingClientRect().height;
    measurer.textContent = text;
    var low = 0;
    var high = Math.ceil(full);
    while (high - low > 1) {
      var middle = Math.floor((low + high) / 2);
      measurer.style.width = px(middle);
      // Слово шире строки не переносится - выходит за край: такая ширина мала
      if (measurer.scrollWidth <= middle + 1 && measurer.getBoundingClientRect().height <= line * lines + 1) high = middle;
      else low = middle;
    }
    measurer.style.width = "max-content";
    return high;
  }

  // Сквозное выравнивание: в 1С колонка заголовков одна на всю форму - проходит сквозь вложенные
  // обычные группы: строку из полей (первое поле строки) и столбец полей.
  // Ширина - по самому широкому заголовку; мерится вне раскладки, поэтому и на скрытых закладках
  function alignThrough(body) {
    var measurer = h("span", "fm-field-title fm-measure");
    body.appendChild(measurer);
    var handled = [];

    function width(title) {
      if (title.dataset.width) return parseFloat(title.dataset.width);
      measurer.textContent = title.textContent;
      return measurer.getBoundingClientRect().width;
    }
    function emptyLabel(element) {
      if (element.dataset.kind !== "LabelDecoration") return false;
      return !Array.prototype.some.call(element.childNodes, function (child) {
        return !(child.classList && child.classList.contains("fm-name-tag")) && child.textContent.trim();
      });
    }
    // Колонку продолжает обычная группа: без заголовка и вертикальная с заголовком («Отражение в УСН» БП).
    // Горизонтальная с заголовком - нет (витрина: «Горизонтальная, если возможно»); своя колонка - у закладки,
    // сворачиваемой и всплывающей группы (Г-1: контрагент «Основной банковский счет», группы договора)
    function joinedContent(element) {
      if (!element.classList.contains("fm-group") || element.matches(".fm-collapsible, .fm-popup-group")) return null;
      var content = element.querySelector(":scope > .fm-group-content");
      if (content && element.querySelector(":scope > .fm-group-title") && !content.classList.contains("fm-through")) return null;
      return content;
    }
    // Ведущий заголовок строки: первое поле, в том числе во вложенной строке
    // single - строка из одного поля: ее заголовок - основание автопереноса (wrapColumn)
    function rowLead(element, found, part, single) {
      if (element.matches(".fm-field.fm-tl-Left")) {
        var title = element.querySelector(":scope > .fm-field-title");
        found.titles.push(title);
        if (title) {
          part.titles.push(title);
          if (single) part.base.push(title);
        }
        return;
      }
      var content = joinedContent(element);
      if (!content) return;
      if (content.classList.contains("fm-horizontal")) {
        // Пустая надпись-отступ в начале строки не занимает колонку заголовков (РТУ БП:
        // «ОтступШапка» перед реквизитами правой колонки) - ведущий элемент следующий за ней
        var first = content.firstElementChild;
        while (first && emptyLabel(first)) first = first.nextElementSibling;
        if (first) rowLead(first, found, part, single && content.querySelectorAll(":scope > .fm-field").length <= 1);
      } else if (content.classList.contains("fm-through")) {
        collect(content, found, part);
      }
    }
    // Часть колонки - столбец полей (тело, закладка, вертикальная группа): свои поля и ведущие
    // заголовки строк; вложенный столбец - своя часть с родителем
    function collect(container, found, parent) {
      var part = { container: container, parent: parent, base: [], titles: [] };
      found.parts.push(part);
      found.grids.push(container);
      handled.push(container);
      Array.prototype.forEach.call(container.children, function (child) {
        if (child.matches(".fm-field.fm-tl-Left")) {
          var title = child.querySelector(":scope > .fm-field-title");
          found.direct.push(title);
          if (title) {
            part.base.push(title);
            part.titles.push(title);
          }
        } else {
          rowLead(child, found, part, true);
        }
      });
    }

    // Корни колонок: тело формы (одна колонка на всю форму, Г-1), затем то, что в нее не вошло
    var roots = [body].concat(Array.prototype.slice.call(body.querySelectorAll(".fm-through")));
    roots.forEach(function (container) {
      if (handled.indexOf(container) >= 0) return;
      var found = { grids: [], direct: [], titles: [], parts: [] };
      collect(container, found, null);
      // Простой столбец без строк и вложенных групп ровняет сетка сама - кроме автопереноса
      var wrapped = wrapColumn(found, width, measurer);
      if (!wrapped && !found.titles.length && found.grids.length === 1) return;
      var all = found.direct.concat(found.titles);
      var max = all.reduce(function (result, title) { return title ? Math.max(result, width(title)) : result; }, 0);
      if (!max) return;
      if (wrapped) max = wrapped;
      found.grids.forEach(function (grid) { grid.style.gridTemplateColumns = px(Math.ceil(max)) + " minmax(0, 1fr)"; });
      found.titles.forEach(function (title) {
        if (title) title.style.minWidth = px(Math.ceil(max));
      });
    });
    measurer.remove();
  }

  // Автоперенос заголовков колонки (Г-3, витрина «Заголовки» 1-4, 01.11.2026). Без высоты заголовка
  // 1С переносит заголовки части колонки, когда:
  // - в самой части самый длинный заголовок в TITLE_WRAP раз шире самого длинного из остальных ее полей
  //   (4-4-41 и 10-10-40 переносит, 18-18-40 и 17-23-41 нет; контрагент - «Наименование нерезидента
  //   в русской транскрипции» при «Головной контрагент»). Строка из нескольких полей в основание не идет:
  //   у контрагента «Государственный орган» + «Код», в шапке ОС «Номер» + «от»; строка из одного поля
  //   идет («Вид операции» ОС - «Местонахождение ОС» в строку);
  // - во вложенной группе заголовок числового поля в TITLE_WRAP раз шире самого длинного заголовка полей
  //   родителя над ней, по тем же правилам основания (ОС «Бухгалтерский учет»: «Срок полезного использования (в месяцах)» при «Порядок
  //   учета»; строки, узкие счета и флажки перенос не включают, верхние 18-21 и 26-28 - тоже).
  // Колонка тогда - по самой длинной строке деления этого заголовка на две (минимум самой длинной
  // строки), но не уже заголовков других частей; заголовки шире переносятся, заголовки флажков
  // справа в той же части - в две строки
  var TITLE_WRAP = 2.3;

  function wrapColumn(found, width, measurer) {
    var widest = function (titles) {
      return titles.reduce(function (best, title) { return !best || width(title) > width(best) ? title : best; }, null);
    };
    var number = function (title) { return !!title.parentElement.querySelector(".fm-number"); };
    var plan = null;
    found.parts.some(function (part) {
      var lead = widest(part.titles);
      if (!lead) return false;
      var others = part.base.filter(function (title) { return title !== lead; });
      var base = widest(others);
      if (base && width(lead) >= TITLE_WRAP * width(base)) {
        plan = { part: part, lead: lead };
        return true;
      }
      var top = part.parent && widest(part.parent.base);
      var numeric = widest(part.titles.filter(number));
      if (top && numeric && width(numeric) >= TITLE_WRAP * width(top)) {
        plan = { part: part, lead: numeric };
        return true;
      }
      return false;
    });
    if (!plan) return 0;

    var block = h("div", "fm-field-title fm-measure fm-title-wrap");
    measurer.parentNode.appendChild(block);
    var column = linesWidth(block, plan.lead.textContent, 2);
    found.parts.forEach(function (part) {
      if (part === plan.part) return;
      part.titles.forEach(function (title) { column = Math.max(column, width(title)); });
    });
    plan.part.titles.forEach(function (title) {
      if (width(title) <= column) return;
      title.classList.add("fm-title-wrap");
      title.style.width = px(column);
      title.style.maxWidth = px(column);
    });
    plan.part.container.querySelectorAll(".fm-field.fm-tl-Right > .fm-field-title").forEach(function (title) {
      var narrow = linesWidth(block, title.textContent, 2);
      title.classList.add("fm-title-wrap");
      title.style.width = px(narrow);
    });
    block.remove();
    return column;
  }

  // Панель инструментов страницы и подсказка

  function renderToolbar() {
    var toolbar = h("div", "fm-toolbar");
    if (DIFF) {
      var modes = h("span", "fm-modes");
      MODE_TITLES.forEach(function (item) {
        var label = h("label");
        var input = h("input");
        input.type = "radio";
        input.name = "fm-mode";
        input.checked = mode === item[0];
        input.addEventListener("change", function () { if (input.checked) setMode(item[0]); });
        modeInputs[item[0]] = input;
        label.appendChild(input);
        label.appendChild(document.createTextNode(item[1]));
        modes.appendChild(label);
      });
      toolbar.appendChild(modes);
      toolbar.appendChild(toggle("Показать правки", showDiff, setShowDiff));
    }
    if (noteList(FORMS.after).length) {
      toolbar.appendChild(toggle("Показать примечания", showNotes, function (on) {
        showNotes = on;
        drawDiff();
      }));
    }
    toolbar.appendChild(toggle("Показать имена", state.names, function (on) {
      document.body.classList.toggle("fm-show-names", on);
      drawDiff();
    }));
    toolbar.appendChild(toggle("Показать скрытые пользователем", !state.nouser, function (on) {
      rendering.showUser = on;
      renderForm();
    }));
    var hidden = toggle("Показать скрытые", state.hidden, function (on) {
      setShowHidden(on);
      renderForm();
    });
    hiddenInput = hidden.querySelector("input");
    toolbar.appendChild(hidden);
    document.body.insertBefore(toolbar, document.body.firstChild);
  }

  function setShowHidden(on) {
    rendering.showHidden = on;
    document.body.classList.toggle("fm-show-hidden", on);
    if (hiddenInput) hiddenInput.checked = on;
  }

  function toggle(text, on, handler) {
    var label = h("label");
    var input = h("input");
    input.type = "checkbox";
    input.checked = on;
    input.addEventListener("change", function () { handler(input.checked); });
    label.appendChild(input);
    label.appendChild(document.createTextNode(text));
    return label;
  }

  function findNode(name, node) {
    node = node || FORM;
    if (node.name === name) return node;
    var nested = [];
    if (node.commandBar) nested.push(node.commandBar);
    if (Array.isArray(node.items)) nested = nested.concat(node.items);
    for (var i = 0; i < nested.length; i++) {
      if (!nested[i] || typeof nested[i] !== "object") continue;
      var found = findNode(name, nested[i]);
      if (found) return found;
    }
    return null;
  }

  function setupTooltip() {
    var tip = document.getElementById("fm-tip");
    var hovered = null;
    document.addEventListener("mousemove", function (event) {
      var target = event.target.closest ? event.target.closest(".fm-item") : null;
      if (target !== hovered) {
        if (hovered) hovered.classList.remove("fm-hover");
        hovered = target;
        if (!target || target.dataset.kind === "Form") {
          tip.style.display = "none";
          hovered = null;
          return;
        }
        target.classList.add("fm-hover");
        tip.innerHTML = "";
        var node = findNode(target.dataset.name) || {};
        tip.appendChild(h("b", "", target.dataset.name));
        tip.appendChild(document.createTextNode(" - " + kindName(target.dataset.kind)));
        if (node.dataPath) tip.appendChild(line("Путь к данным: " + node.dataPath));
        if (node.toolTip) tip.appendChild(line("Подсказка: " + node.toolTip));
        if (node.visible === false) tip.appendChild(line("Скрыт (visible = false)"));
        if (node.note) {
          var note = line(node.note);
          note.className = "fm-tip-note";
          tip.appendChild(note);
        }
        var change = showDiff ? changeOf(target.dataset.name || "") : null;
        if (change) {
          var head = line(change.n + ". " + (diffMarks()[target.dataset.name].op === "ghost" ? "Прежнее место: " : "") + change.what);
          head.className = "fm-tip-diff";
          tip.appendChild(head);
          change.details.forEach(function (detail) { tip.appendChild(line(detail)); });
        }
        tip.style.display = "block";
      }
      if (hovered) {
        tip.style.left = px(Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8));
        tip.style.top = px(event.clientY + 16);
      }
    });
  }

  function line(text) { return h("div", "", text); }

  // Слой поверх формы: бирки имен и правки - подсветка, легенда, список правок, переход к элементу.
  // Слой не обрезают панели и таблицы (`overflow: hidden`), и он не меняет раскладку

  var layer = null;          // слой бирок имен, рамок и номеров правок
  var drawn = [];            // нарисованные рамки - для итога раскладки
  var notesDrawn = [];       // элементы с нарисованным номером примечания - для итога раскладки
  var nameLabels = [];       // нарисованные бирки имен (left, top, right, bottom) - для итога раскладки
  var DIFF_LEGEND = [["added", "Добавлено"], ["changed", "Изменено"], ["moved", "Перенесено"], ["removed", "Удалено"]];
  var MODE_TITLES = [["diff", "Правки"], ["after", "Стало"], ["before", "Было"]];
  var modeInputs = {};
  var hiddenInput = null;

  // Имя элемента правки в форме режима: удаленного нет в «Стало», добавленного - в «Было»
  function nameIn(modeName, change) {
    if (modeName === "after") return change.after;
    if (modeName === "before") return change.before;
    return change.op === "removed" ? change.before : change.after;
  }

  // Имя → отметка правки в текущем режиме; тень перенесенного - только в «Правках»
  function diffMarks() {
    var marks = {};
    if (!DIFF) return marks;
    DIFF.changes.forEach(function (change) {
      var name = nameIn(mode, change);
      if (name) marks[name] = { n: change.n, op: change.op };
      if (mode === "diff" && change.ghost) marks[change.ghost] = { n: change.n, op: "ghost" };
    });
    return marks;
  }

  function changeOf(name) {
    var found = diffMarks()[name];
    if (!found) return null;
    return DIFF.changes.filter(function (change) { return change.n === found.n; })[0] || null;
  }

  // Поле в сквозной сетке заголовков - `display: contents`: своей рамки нет, рамка и стиль - у его частей
  function partsOf(element) {
    if (getComputedStyle(element).display !== "contents") return [element];
    return Array.prototype.filter.call(element.children, function (child) {
      return !child.classList.contains("fm-name-tag");
    });
  }

  // Удаленное зачеркнуто, тень перенесенного бледная (только при «Показать правки» - правила CSS)
  function applyDiff() {
    if (!DIFF) return;
    var marks = diffMarks();
    document.querySelectorAll("#fm-root .fm-item[data-name], #fm-root .fm-tab[data-page]").forEach(function (element) {
      var found = marks[element.dataset.name || element.dataset.page];
      if (!found || (found.op !== "removed" && found.op !== "ghost")) return;
      partsOf(element).forEach(function (part) { part.classList.add("fm-diff-" + found.op + "-el"); });
    });
  }

  function renderLegend(root) {
    if (!DIFF) return;
    var legend = h("div", "fm-diff-legend");
    DIFF_LEGEND.forEach(function (item) {
      var entry = h("span", "fm-diff-legend-item");
      entry.appendChild(h("span", "fm-diff-swatch fm-diff-" + item[0]));
      entry.appendChild(document.createTextNode(item[1]));
      legend.appendChild(entry);
    });
    root.appendChild(legend);
  }

  // Видимая часть элемента: пересечение с областями прокрутки и обрезки предков. Содержимое, выступающее за
  // коробку элемента (текст флажка шире поля), - тоже его: иначе край рамки правки ложится поверх букв (обкатка
  // обкатка: «Неиспользуетс» на `__правки.png`). Элемент, который сам обрезает содержимое, - по коробке
  function visibleRect(element) {
    var rects = partsOf(element).map(function (part) {
      var rect = part.getBoundingClientRect();
      var style = getComputedStyle(part);
      var right = rect.right;
      var bottom = rect.bottom;
      if (style.overflowX === "visible") right = Math.max(right, rect.left + part.scrollWidth);
      if (style.overflowY === "visible") bottom = Math.max(bottom, rect.top + part.scrollHeight);
      return { left: rect.left, top: rect.top, right: right, bottom: bottom, width: right - rect.left, height: bottom - rect.top };
    }).filter(function (rect) { return rect.width > 0 || rect.height > 0; });
    if (!rects.length) return null;
    var box = {
      left: Math.min.apply(null, rects.map(function (rect) { return rect.left; })),
      top: Math.min.apply(null, rects.map(function (rect) { return rect.top; })),
      right: Math.max.apply(null, rects.map(function (rect) { return rect.right; })),
      bottom: Math.max.apply(null, rects.map(function (rect) { return rect.bottom; }))
    };
    for (var parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      var style = getComputedStyle(parent);
      if (style.overflowX === "visible" && style.overflowY === "visible") continue;
      var clipRect = parent.getBoundingClientRect();
      box.left = Math.max(box.left, clipRect.left);
      box.top = Math.max(box.top, clipRect.top);
      box.right = Math.min(box.right, clipRect.right);
      box.bottom = Math.min(box.bottom, clipRect.bottom);
    }
    return box.right > box.left && box.bottom > box.top ? box : null;
  }

  function drawFrame(element, found, badge) {
    var rect = visibleRect(element);
    if (!rect) return false;
    var x = window.scrollX;
    var y = window.scrollY;
    var active = found.op !== "note" && found.n === activeChange;
    var frame = h("div", "fm-diff-frame fm-diff-" + found.op + (active ? " fm-diff-active" : ""));
    // Слева и справа - зазор 4 px между рамкой (2 px) и элементом: при 1 px край рамки задевал последнюю букву
    // подписи, текст которой кончается вровень с полем (обкатка: «Неиспользуетс» на `__правки.png`)
    frame.style.left = px(rect.left + x - 6);
    frame.style.top = px(rect.top + y - 3);
    frame.style.width = px(rect.right - rect.left + 12);
    frame.style.height = px(rect.bottom - rect.top + 6);
    layer.appendChild(frame);
    if (badge) {
      var number = h("div", "fm-diff-badge fm-diff-" + found.op, found.n);
      number.style.left = px(rect.right + x - 7);
      number.style.top = px(rect.top + y - 11);
      layer.appendChild(number);
    }
    return true;
  }

  // Слой - по раскладке; перерисовка после каждой раскладки, прокрутки и изменения окна
  function drawDiff() {
    drawn = [];
    notesDrawn = [];
    nameLabels = [];
    if (!layer) return;
    layer.innerHTML = "";
    // Номера правок - поверх бирок имен; номера примечаний - только без правок: две нумерации путаются
    drawNames();
    if (DIFF && showDiff) drawMarks(diffMarks(), drawn);
    else if (showNotes && mode === "after") drawMarks(noteMarks(), notesDrawn);
    if (api && api.onDraw) api.onDraw(layer);
  }

  // Примечания: элементы с `note` порядком обхода дерева - форма, ее командная панель, элементы;
  // так же нумерует `table` (`fmlib.diff.note_numbers`). Номер - кружком своего цвета, как номер правки
  function noteList(form) {
    var list = [];
    (function visit(node, isForm) {
      if (typeof node.note === "string" && node.note.trim()) {
        list.push({ n: list.length + 1, name: isForm ? "Форма" : node.name, text: node.note });
      }
      if (node.commandBar && typeof node.commandBar === "object") visit(node.commandBar, false);
      (Array.isArray(node.items) ? node.items : []).forEach(function (item) {
        if (item && typeof item === "object") visit(item, false);
      });
    })(form || {}, true);
    return list;
  }

  function noteMarks() {
    var marks = {};
    noteList(FORMS.after).forEach(function (entry) { marks[entry.name] = { n: entry.n, op: "note" }; });
    return marks;
  }

  // Бирка имени - над левым верхним углом элемента, не шире элемента (но не уже 90 px): длинное имя обрезается с
  // начала - в БП различает хвост (`ГруппаКнопкиКоманднойПанелиPostAndClose`), полное имя - в подсказке.
  // Бирки с одного угла (вложенные группы) - в ряд от внешнего к вложенному, без места в ряду - строкой ниже
  var NAME_MIN = 90;
  function drawNames() {
    if (!document.body.classList.contains("fm-show-names")) return;
    var placed = [];
    // Бирка добавляется в элемент после его детей - порядок по самим элементам: внешний раньше вложенного
    var sources = Array.prototype.slice.call(document.querySelectorAll("#fm-root .fm-name-tag"));
    sources.sort(function (left, right) {
      return left.parentElement.compareDocumentPosition(right.parentElement) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });
    sources.forEach(function (source) {
      var rect = visibleRect(source.parentElement);
      if (!rect) return;
      var name = source.textContent;
      var tag = h("div", "fm-name-label", name);
      layer.appendChild(tag);
      var limit = Math.max(rect.right - rect.left, NAME_MIN);
      if (tag.offsetWidth > limit) {
        var low = 0;
        var high = name.length;
        while (low < high) {
          var middle = Math.floor((low + high) / 2);
          tag.textContent = "…" + name.slice(middle);
          if (tag.offsetWidth > limit) low = middle + 1;
          else high = middle;
        }
        tag.textContent = "…" + name.slice(low);
      }
      var width = tag.offsetWidth;
      var height = tag.offsetHeight;
      var left = rect.left + window.scrollX;
      var x = left;
      var y = rect.top + window.scrollY - 7;
      for (var i = 0; i < placed.length; i++) {
        var other = placed[i];
        if (x < other.right && x + width > other.left && y < other.bottom && y + height > other.top) {
          x = other.right + 2;
          if (x + width > left + limit) {
            x = left;
            y = other.bottom + 1;
          }
          i = -1;
        }
      }
      tag.style.left = px(x);
      tag.style.top = px(y);
      placed.push({ left: x, top: y, right: x + width, bottom: y + height });
    });
    nameLabels = placed;
  }

  // Номер правки или примечания - у первого видимого вхождения: у колонки - в шапке, у закладки - на ярлыке.
  // `list` - имена с рамкой, для итога раскладки
  function drawMarks(marks, list) {
    var badged = {};
    // Примечание самой формы - номером за текстом заголовка окна, без рамки вокруг всего окна
    var formNote = marks["Форма"] && marks["Форма"].op === "note";
    var title = formNote ? document.querySelector("#fm-root .fm-window .fm-caption-title") : null;
    if (title) {
      var range = document.createRange();
      range.selectNodeContents(title);
      var textRect = range.getBoundingClientRect();
      var titleRect = title.getBoundingClientRect();
      var winBadge = h("div", "fm-diff-badge fm-diff-note", marks["Форма"].n);
      winBadge.style.left = px((textRect.width ? textRect.right : titleRect.left) + window.scrollX + 6);
      winBadge.style.top = px(titleRect.top + titleRect.height / 2 + window.scrollY - 9);
      layer.appendChild(winBadge);
      badged["Форма"] = true;
      list.push("Форма");
    }
    document.querySelectorAll("#fm-root .fm-tab[data-page]").forEach(function (tab) {
      var found = marks[tab.dataset.page];
      if (found && drawFrame(tab, found, !badged[tab.dataset.page])) {
        badged[tab.dataset.page] = true;
        list.push(tab.dataset.page);
      }
    });
    document.querySelectorAll("#fm-root .fm-item[data-name]").forEach(function (element) {
      var name = element.dataset.name;
      var found = marks[name];
      if (!found || formNote && name === "Форма") return;
      // Хост пометки внутри своего же элемента (поле и его значение) - рамка одна, у внешнего
      var outer = element.parentElement && element.parentElement.closest(".fm-item[data-name]");
      if (outer && outer.dataset.name === name) return;
      if (drawFrame(element, found, !badged[name])) {
        badged[name] = true;
        if (list.indexOf(name) < 0) list.push(name);
      }
    });
    // Не видно на форме (кнопка в подменю или в «Еще», элемент свернутой группы) - номер у ближайшего видимого
    // предка, несколько номеров - в ряд
    var shared = {};
    Object.keys(marks).forEach(function (name) {
      if (badged[name] || marks[name].op === "ghost") return;
      var path = pathTo(FORM, name) || [];
      for (var i = path.length - 2; i >= 0; i--) {
        var holder = findElement(path[i] === FORM ? "Форма" : path[i].name, path[i]);
        var rect = holder ? visibleRect(holder) : null;
        if (!rect) continue;
        var key = path[i] === FORM ? "Форма" : path[i].name;
        var shift = (shared[key] || 0) * 22;
        shared[key] = (shared[key] || 0) + 1;
        var number = h("div", "fm-diff-badge fm-diff-hidden-badge fm-diff-" + marks[name].op, marks[name].n);
        number.title = name;
        number.style.left = px(rect.right + window.scrollX - 10 - shift);
        number.style.top = px(rect.bottom + window.scrollY - 9);
        layer.appendChild(number);
        badged[name] = true;
        // Примечание на другой закладке, в подменю - тоже на снимке: номером у предка
        if (marks[name].op === "note") list.push(name);
        break;
      }
    });
  }

  var redrawQueued = false;
  function queueRedraw() {
    if (redrawQueued || !layer) return;
    redrawQueued = true;
    requestAnimationFrame(function () {
      redrawQueued = false;
      drawDiff();
    });
  }

  function renderChanges() {
    var aside = document.querySelector(".fm-changes");
    if (!aside) return;
    aside.innerHTML = "";
    aside.appendChild(h("div", "fm-changes-title", "Правки: " + DIFF.changes.length));
    if (!DIFF.changes.length) aside.appendChild(h("div", "fm-change-detail", "Формы не различаются"));
    DIFF.changes.forEach(function (change) {
      var item = h("div", "fm-change");
      if (change.n === activeChange) item.classList.add("fm-change-active");
      // Элемента нет в форме режима - щелчок переключит режим
      if (!nameIn(mode, change)) item.classList.add("fm-change-absent");
      var head = h("div", "fm-change-head");
      head.appendChild(h("span", "fm-diff-badge fm-diff-" + change.op, change.n));
      head.appendChild(h("span", "fm-change-title", change.title));
      head.appendChild(h("span", "fm-change-what", change.what));
      item.appendChild(head);
      item.appendChild(h("div", "fm-change-name", (change.op === "removed" ? change.before : change.after) + " - " + kindName(change.kind)));
      change.details.forEach(function (detail) { item.appendChild(h("div", "fm-change-detail", detail)); });
      item.addEventListener("click", function () { activate(change.n); });
      aside.appendChild(item);
    });
  }

  function setMode(value) {
    if (!FORMS[value]) throw new Error("нет режима " + value);
    mode = value;
    FORM = FORMS[value];
    Object.keys(modeInputs).forEach(function (key) { modeInputs[key].checked = key === value; });
    renderForm();
    renderChanges();
  }

  function setShowDiff(on) {
    showDiff = on;
    document.body.classList.toggle("fm-diff-on", on);
    drawDiff();
  }

  function pathTo(node, name, trail) {
    trail = (trail || []).concat([node]);
    if (node === FORM ? name === "Форма" : node.name === name) return trail;
    var nested = [];
    if (node.commandBar) nested.push(node.commandBar);
    if (Array.isArray(node.items)) nested = nested.concat(node.items);
    for (var i = 0; i < nested.length; i++) {
      if (!nested[i] || typeof nested[i] !== "object") continue;
      var found = pathTo(nested[i], name, trail);
      if (found) return found;
    }
    return null;
  }

  function findElement(name, node) {
    if (name === "Форма") return document.querySelector(".fm-window");
    var selector = node && node.type === "Page" ? "#fm-root .fm-tab[data-page]" : "#fm-root .fm-item[data-name]";
    var candidates = Array.prototype.filter.call(document.querySelectorAll(selector), function (element) {
      return (element.dataset.name || element.dataset.page) === name;
    });
    return candidates.filter(function (element) { return visibleRect(element); })[0] || candidates[0] || null;
  }

  // Щелчок по правке: режим, где элемент есть («Было» - для удаленного, когда его нет в текущем), закладки и
  // свернутые группы на пути открыты, скрытый показан; прокрутка к элементу и выделение рамки
  function activate(number) {
    var change = DIFF.changes.filter(function (item) { return item.n === number; })[0];
    if (!change) throw new Error("нет правки " + number);
    if (!nameIn(mode, change)) setMode(change.op === "removed" ? "before" : "diff");
    var name = nameIn(mode, change);
    var path = pathTo(FORM, name) || [];
    openPath(path);
    activeChange = number;
    if (!showDiff) setShowDiff(true);
    renderForm();
    renderChanges();
    var element = findElement(name, path[path.length - 1]);
    if (element) partsOf(element)[0].scrollIntoView({ block: "center", inline: "nearest" });
    drawDiff();
    publish();
  }

  // Путь к элементу открыт, как это сделал бы пользователь: закладки переключены, свернутые группы развернуты,
  // скрытый показан. Итог - изменилось ли состояние (форму надо перерисовать)
  function openPath(path) {
    var changed = false;
    path.forEach(function (node, index) {
      var parent = path[index - 1];
      if (parent && parent.type === "Pages" && node.type === "Page" && currentPage[parent.name] !== node.name) {
        currentPage[parent.name] = node.name;
        changed = true;
      }
      var folding = node.type === "UsualGroup" && (node.behavior === "Collapsible" || node.behavior === "PopUp");
      if (folding && index < path.length - 1 && collapsed[node.name] !== false) {
        collapsed[node.name] = false;
        changed = true;
      }
      if (node !== FORM && !isShown(node)) {
        setShowHidden(true);
        changed = true;
      }
    });
    return changed;
  }

  function countMarks(node, marks) {
    var count = node.name in marks ? 1 : 0;
    if (node.commandBar) count += countMarks(node.commandBar, marks);
    (Array.isArray(node.items) ? node.items : []).forEach(function (item) {
      if (item && typeof item === "object") count += countMarks(item, marks);
    });
    return count;
  }

  function setupLayer() {
    layer = h("div", "fm-diff-layer");
    document.body.appendChild(layer);
    document.addEventListener("scroll", queueRedraw, true);
    window.addEventListener("resize", queueRedraw);
    document.addEventListener("pointerup", queueRedraw);
  }

  function setupDiff() {
    if (!DIFF) return;
    var root = document.getElementById("fm-root");
    var stage = h("div", "fm-stage");
    root.parentNode.insertBefore(stage, root);
    stage.appendChild(root);
    stage.appendChild(h("aside", "fm-changes"));
    document.body.classList.toggle("fm-diff-on", showDiff);
    renderChanges();
  }

  // Итог раскладки: замечания, размер, закладки - для formmockup.py

  function clippedNotes(notes, seen) {
    document.querySelectorAll(".fm-clip").forEach(function (element) {
      if (!element.offsetParent || element.scrollWidth <= element.clientWidth + 1) return;
      var owner = element.closest("[data-name]");
      var name = owner ? owner.dataset.name : "";
      var text = name + ": " + element.dataset.clip + " «" + element.textContent + "» не помещается";
      if (!seen[text]) {
        seen[text] = true;
        notes.push(text);
      }
    });
  }

  // Колонки шире таблицы: полоса прокрутки на макете и замечание, как прокрутка в 1С
  function tableNotes(notes, seen) {
    document.querySelectorAll(".fm-table-view").forEach(function (grid) {
      if (!grid.offsetParent) return;
      // Распорка - по фактической ширине колонок (заголовки бывают шире расчета), не больше TABLE_MAX
      var spacer = grid.parentElement.querySelector(":scope > .fm-table-spacer");
      // и не уже стандартных кнопок панели с поиском и «Еще»: узкая таблица в 1С их не прячет (ГИСМ, «Номера КиЗ»)
      // (рамка области - сверх ширины колонок)
      var frame = grid.offsetWidth - grid.clientWidth;
      if (spacer) spacer.style.width = px(Math.min(Math.max(grid.scrollWidth + frame, standardBarWidth(grid.parentElement)), TABLE_MAX));
      var scroll = grid.parentElement.querySelector(":scope > .fm-table-hscroll");
      var overflow = grid.scrollWidth > grid.clientWidth + 1;
      scroll.classList.toggle("fm-shown", overflow);
      if (!overflow) return;
      scroll.firstChild.style.width = Math.round(100 * grid.clientWidth / grid.scrollWidth) + "%";
      var owner = grid.closest("[data-name]");
      var text = (owner ? owner.dataset.name : "") + ": колонки не помещаются по ширине - горизонтальная прокрутка";
      if (!seen[text]) {
        seen[text] = true;
        notes.push(text);
      }
    });
  }

  function standardBarWidth(table) {
    var bar = table.querySelector(":scope > .fm-cmdbar");
    if (!bar) return 0;
    var standard = bar.querySelectorAll(":scope > .fm-cmdbar-items > .fm-std, :scope > .fm-cmdbar-items > .fm-button-group:has(> .fm-std)");
    var more = bar.querySelector(".fm-more");
    if (!standard.length || !more) return 0;
    var left = bar.getBoundingClientRect().left;
    var search = bar.querySelector(".fm-search");
    var searchWidth = search ? parseFloat(getComputedStyle(search).minWidth) + 9 : 0;
    return standard[standard.length - 1].getBoundingClientRect().right - left + 18 + searchWidth + more.getBoundingClientRect().width;
  }

  // Что не поместилось в панель, уходит в «Еще». Панель таблицы - по правилу 1С (владелец): сначала
  // пользовательские кнопки, затем общие команды, затем стандартные (перемещение и т.п.), затем
  // «Добавить», затем сама «Еще»; поле поиска остается последним. Внутри ступени - с конца. Панель
  // формы - с конца, «Еще» на месте. Убранное прежним проходом возвращается: места могло стать
  // больше (разделитель)
  function overflowNotes(notes, seen) {
    document.querySelectorAll(".fm-cmdbar-items").forEach(function (items) {
      var bar = items.parentElement;
      bar.querySelectorAll("[data-overflow]").forEach(function (element) {
        element.style.display = "";
        delete element.dataset.overflow;
      });
      var added = items.querySelector(":scope > .fm-overflow-more");
      if (added) added.remove();
      if (!items.offsetParent) return;
      var children = Array.prototype.slice.call(items.children).filter(function (child) {
        return !child.classList.contains("fm-name-tag");
      });
      var tail = bar.querySelector(":scope > .fm-cmdbar-tail");
      // У панели без «Еще» (командная панель над табличным документом) «Еще» появляется, когда кнопки
      // не помещаются, и они уходят в нее справа налево (владелец)
      if (!tail && !items.querySelector(":scope > .fm-all-actions")) {
        var last = children[children.length - 1];
        if (last && last.getBoundingClientRect().right > items.getBoundingClientRect().right + 1) {
          var extra = h("span", "fm-popup fm-more fm-all-actions fm-overflow-more");
          extra.appendChild(h("span", "fm-button-text", "Еще"));
          items.appendChild(extra);
          children.push(extra);
        }
      }
      var search = tail ? tail.querySelector(":scope > .fm-search") : null;
      // Не scrollWidth: бирки имен выступают за кнопки и дали бы ложное переполнение
      var overflows = function () {
        var visible = children.filter(function (child) { return child.style.display !== "none"; });
        var last = visible[visible.length - 1];
        if (last && last.getBoundingClientRect().right > items.getBoundingClientRect().right + 1) return true;
        // хвост (поиск, «Еще») сжимается, а содержимое вылезает за него - меряется последний элемент
        var ends = tail ? Array.prototype.filter.call(tail.children, function (child) {
          return !child.classList.contains("fm-name-tag") && child.style.display !== "none";
        }) : [];
        var end = ends[ends.length - 1];
        return !!end && end.getBoundingClientRect().right > bar.getBoundingClientRect().right + 1;
      };
      // «Еще» подменю всех действий поля не уходит - в него уходят остальные. Обычная группа кнопок
      // уходит по кнопкам (в 1С «Форматирование текста» теряет хвост, а не исчезает), слитная - целиком
      var units = function (list) {
        var result = [];
        list.forEach(function (element) {
          if (element.classList.contains("fm-button-group") && !element.classList.contains("fm-joined")) {
            result = result.concat(units(Array.prototype.filter.call(element.children, function (child) {
              return !child.classList.contains("fm-name-tag");
            })));
          } else {
            result.push(element);
          }
        });
        return result;
      };
      var order = units(children.filter(function (child) { return !child.classList.contains("fm-all-actions"); })).reverse();
      if (bar.closest(".fm-table")) {
        var step = function (element) {
          var command = element.dataset.command || (element.querySelector("[data-command]") || element).dataset.command || "";
          if (/StandardCommand\.Add$/.test(command)) return 3;
          if (/StandardCommand\./.test(command) || element.classList.contains("fm-std") || element.querySelector(".fm-std")) return 2;
          if (/^CommonCommand\./.test(command)) return 1;
          return 0;
        };
        // сортировка устойчивая: внутри ступени остается порядок «с конца»
        order = order.map(function (element, index) { return { element: element, index: index, step: step(element) }; })
          .sort(function (a, b) { return a.step - b.step || a.index - b.index; })
          .map(function (entry) { return entry.element; });
        var more = tail ? tail.querySelector(":scope > .fm-more") : null;
        if (more) order.push(more);
      }
      // Поле поиска - последним, после «Еще» (владелец)
      order = order.filter(function (element) { return !element.classList.contains("fm-search"); })
        .concat(order.filter(function (element) { return element.classList.contains("fm-search"); }));
      var hidden = [];
      for (var i = 0; i < order.length && overflows(); i++) {
        order[i].style.display = "none";
        order[i].dataset.overflow = "1";
        // опустевшая группа уходит сама: ее отступы не держат место
        for (var group = order[i].parentElement; group && group !== items; group = group.parentElement) {
          var left = Array.prototype.some.call(group.children, function (child) {
            return !child.classList.contains("fm-name-tag") && child.style.display !== "none";
          });
          if (left) break;
          group.style.display = "none";
          group.dataset.overflow = "1";
        }
        // слитная пара стандартных кнопок без имени - по подсказкам кнопок («Переместить вверх/вниз»)
        var label = order[i].dataset.name || order[i].textContent.trim() ||
          Array.prototype.map.call(order[i].querySelectorAll("[title]"), function (item) { return item.title; }).join(" / ");
        hidden.push(order[i] === search ? "поиск" : label);
      }
      if (!hidden.length) return;
      var owner = items.closest("[data-name]");
      var text = (owner ? owner.dataset.name : "") + ": в «Еще» ушли: " + hidden.join(", ");
      if (!seen[text]) {
        seen[text] = true;
        notes.push(text);
      }
    });
  }

  function pagesList() {
    var result = [];
    var marks = diffMarks();
    var notes = noteMarks();
    function walk(node, chain) {
      (Array.isArray(node.items) ? node.items : []).forEach(function (item) {
        if (!item || typeof item !== "object" || !isShown(item)) return;
        if (item.type === "Pages") {
          var pages = shownItems(item).filter(function (page) { return page.type === "Page"; });
          pages.forEach(function (page) {
            result.push({ pages: item.name, page: page.name, current: currentPage[item.name] === page.name, chain: chain.slice(),
              changes: countMarks(page, marks), notes: countMarks(page, notes) });
            walk(page, chain.concat([item.name + ":" + page.name]));
          });
        } else {
          walk(item, chain);
        }
      });
    }
    walk(FORM, []);
    return result;
  }

  function publish() {
    var notes = [];
    var seen = {};
    var saved = {};
    Object.keys(currentPage).forEach(function (key) { saved[key] = currentPage[key]; });
    // Замечания - по всем закладкам: каждую закладку показываем и меряем
    var pagesElements = document.querySelectorAll(".fm-pages");
    clippedNotes(notes, seen);
    tableNotes(notes, seen);
    pagesElements.forEach(function (element) {
      var name = element.dataset.name;
      element.querySelectorAll(":scope > .fm-page").forEach(function (page) {
        if (page.classList.contains("fm-current")) return;
        setPageSilently(element, page.dataset.page);
        clippedNotes(notes, seen);
        tableNotes(notes, seen);
      });
      setPageSilently(element, saved[name]);
    });
    overflowNotes(notes, seen);
    if (formWidened) {
      notes.push("ширина формы " + FORM.width + " меньше минимальной: окно по содержимому, около " +
        Math.round((formWidened - 14) / CH) + " символов - как в 1С");
    }
    Object.keys(missingPictures).forEach(function (name) {
      notes.push("картинка " + name + " нарисована заглушкой: нет пиктограммы в макете и в pictures модели");
    });
    drawDiff();
    var win = document.querySelector(".fm-window");
    var rect = win ? win.getBoundingClientRect() : { right: 0, bottom: 0 };
    var padding = state["static"] ? 8 : 16;
    // Номера правок выходят за край окна - снимок их не обрезает
    var right = rect.right;
    var bottom = rect.bottom;
    if (layer) {
      Array.prototype.forEach.call(layer.children, function (child) {
        var box = child.getBoundingClientRect();
        right = Math.max(right, box.right);
        bottom = Math.max(bottom, box.bottom);
      });
    }
    var result = {
      notes: notes,
      errors: errors,
      width: Math.ceil(right + padding),
      height: Math.ceil(bottom + padding),
      pages: pagesList(),
      dom: {
        mode: mode,
        diffFrames: drawn.slice(),
        // Номера примечаний на макете: [имя, номер] - сверка с колонкой «№» таблицы
        noteFrames: notesDrawn.map(function (name) { return [name, noteMarks()[name].n]; }),
        activeChange: activeChange,
        nameLabels: nameLabels.map(function (box) { return [box.left, box.top, box.right, box.bottom]; }),
        currentPages: saved,
        collapsed: Array.prototype.map.call(document.querySelectorAll(".fm-collapsed"), function (element) {
          return element.dataset.name;
        }),
        // Поля с автопереносом заголовка (Г-3) - для проверки по витрине
        wrappedTitles: Array.prototype.map.call(document.querySelectorAll(".fm-title-wrap"), function (title) {
          var field = title.closest(".fm-item");
          return field ? field.dataset.name : "";
        }),
        // Левый край поля у полей с заголовком слева - проверка колонки заголовков
        controlLefts: Array.prototype.reduce.call(document.querySelectorAll(".fm-field.fm-tl-Left[data-name]"),
          function (found, field) {
            var control = field.querySelector(":scope > .fm-control");
            if (control) found[field.dataset.name] = Math.round(control.getBoundingClientRect().left);
            return found;
          }, {}),
        // Высота многострочных полей ввода - проверка растягивания по вертикали и максимальной высоты
        inputHeights: Array.prototype.reduce.call(document.querySelectorAll(".fm-field.fm-tall[data-name]"),
          function (found, field) {
            var input = field.querySelector(".fm-input");
            if (input) found[field.dataset.name] = Math.round(input.getBoundingClientRect().height);
            return found;
          }, {}),
        // Подсказка рядом с полем: рамки текста подсказки, заголовка и поля - проверка раскладки флажка
        tooltips: Array.prototype.reduce.call(document.querySelectorAll(".fm-item[data-name]"),
          function (found, item) {
            var tip = item.querySelector(".fm-xtip-text");
            if (!tip || tip.closest(".fm-item") !== item) return found;
            var frame = function (element) {
              if (!element) return null;
              var box = element.getBoundingClientRect();
              return [Math.round(box.left), Math.round(box.top), Math.round(box.right), Math.round(box.bottom)];
            };
            found[item.dataset.name] = { tip: frame(tip), title: frame(item.querySelector(".fm-field-title")),
              control: frame(item.querySelector(".fm-check, .fm-radio-list, .fm-input")) };
            return found;
          }, {})
      }
    };
    document.getElementById("fm-result").textContent = JSON.stringify(result);
  }

  function setPageSilently(element, pageName) {
    Array.prototype.forEach.call(element.children, function (child) {
      if (child.classList.contains("fm-tabs")) {
        Array.prototype.forEach.call(child.children, function (tab) {
          tab.classList.toggle("fm-current", tab.dataset.page === pageName);
        });
      } else if (child.classList.contains("fm-page")) {
        child.classList.toggle("fm-current", child.dataset.page === pageName);
      }
    });
  }

  // Щелчки из адреса - настоящие события по элементам страницы
  function runActions(actions) {
    actions.forEach(function (action) {
      var parts = action.split(":");
      var target = null;
      if (parts[0] === "tab") {
        target = document.querySelector('.fm-pages[data-name="' + parts[1] + '"] > .fm-tabs > .fm-tab[data-page="' + parts[2] + '"]');
      } else if (parts[0] === "toggle") {
        target = document.querySelector('.fm-group[data-name="' + parts[1] + '"] > .fm-group-title');
      } else if (parts[0] === "more") {
        // Меню «Еще» командной панели (тесты: что в него попало)
        target = document.querySelector('.fm-cmdbar[data-name="' + parts[1] + '"] > .fm-cmdbar-tail > .fm-more');
      } else if (parts[0] === "mode" && DIFF) {
        target = modeInputs[parts[1]];
        if (target) {
          target.checked = true;
          target.dispatchEvent(new Event("change", { bubbles: true }));
          return;
        }
      } else if (parts[0] === "diff" && DIFF) {
        target = Array.prototype.filter.call(document.querySelectorAll(".fm-change"), function (item, index) {
          return DIFF.changes[index] && String(DIFF.changes[index].n) === parts[1];
        })[0];
      }
      if (!target) throw new Error("действие не нашло элемент: " + action);
      target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }

  // Конструктор: перерисовка той же страницы по новой модели. Закладки и свернутые группы
  // помнятся по именам (`currentPage`, `collapsed`); выбор и его рамку рисует editor.js в `onDraw` - слой
  // перерисовывается после каждой раскладки, прокрутки и изменения окна
  var api = null;
  if (EDITOR) {
    api = window.FMRender = {
      // `pictures` - стандартные картинки, которых нет в модели (сервер добирает их, как `render`). `diff` - правки
      // против «было»: `{changes, tree}` - режим «Правки» по объединенному дереву; без `tree` (сервер еще не
      // пересчитал после правки) - форма модели с отметками по именам; `null` - без правок
      update: function (model, pictures, diff) {
        MODEL = model;
        FORMS.after = MODEL.form || {};
        DIFF = diff || null;
        FORMS.diff = DIFF && DIFF.tree ? DIFF.tree : null;
        mode = FORMS.diff ? "diff" : "after";
        FORM = FORMS[mode];
        showDiff = !!DIFF;
        document.body.classList.toggle("fm-diff-on", showDiff);
        if (!DIFF) activeChange = 0;
        PICTURES = Object.assign({}, pictures || {}, MODEL.pictures || {});
        STYLES = MODEL.styles || {};
        missingPictures = {};
        renderForm();
      },
      // Правка, выбранная в списке конструктора: рамка с подсветкой
      setActiveChange: function (number) {
        activeChange = number || 0;
        drawDiff();
      },
      clear: function () {
        document.getElementById("fm-root").innerHTML = "";
        drawDiff();
      },
      // Показать элемент: закладки, свернутые группы, скрытые; итог - пришлось ли перерисовать
      // `keepHidden` - не включать «Скрытые» ради скрытого элемента: такой элемент не показывается вовсе, макет не
      // меняется (конструктор, владелец 04.11.2026)
      reveal: function (name, keepHidden) {
        var path = pathTo(FORM, name) || [];
        if (keepHidden && path.some(function (node) { return node !== FORM && !isShown(node); })) return false;
        var changed = openPath(path);
        if (changed) renderForm();
        return changed;
      },
      element: function (name) {
        return findElement(name, name === "Форма" ? FORM : findNode(name));
      },
      visibleRect: visibleRect,
      partsOf: partsOf,
      showHidden: function () { return rendering.showHidden; },
      setShowHidden: function (on) {
        setShowHidden(on);
        renderForm();
      },
      setShowNames: function (on) {
        document.body.classList.toggle("fm-show-names", on);
        drawDiff();
      },
      // Номера примечаний: при включенных правках не рисуются
      setShowNotes: function (on) {
        showNotes = on;
        drawDiff();
      },
      noteList: noteList,
      redraw: queueRedraw,
      // Перерисовка слоя сразу, без ожидания кадра - для итога прогона действий (editor.js)
      drawNow: drawDiff,
      titleOf: function (node, model) { return titleOf(node, undefined, model); },
      commandTitle: commandTitle,
      splitName: splitName,
      // Путь к данным по модели конструктора (она может опередить ту, что нарисована)
      STANDARD_NAMES: STANDARD_NAMES,
      typeNames: typeNames,
      typeOf: typeOf,
      isCollection: isCollection,
      pathTools: pathTools,
      pathTitle: pathTitle,
      // Стандартные команды таблицы, как их знает рендерер (меню «Еще» таблицы или списка): окно исключенных
      // команд конструктора
      // Стандартные команды формы (панель, «Еще», «Изменить форму...», «Справка»): «Состав команд» формы и выбор команды
      formCommands: function () {
        var names = (MORE_FORM[FORM.formKind] || []).concat(["Close", "CustomizeForm", "Help"]);
        return names.map(function (name) { return { name: name, title: standardTitle(name, true) }; });
      },
      // Кнопки автозаполнения панели формы (`table` нет) или таблицы по форме конструктора `form`
      autoCommands: function (table, form) {
        var drawn = FORM;
        FORM = form || FORM;
        try {
          return autoCommands(table || null);
        } finally {
          FORM = drawn;
        }
      },
      inheritedPicture: inheritedPicture,
      tableCommands: function (table) {
        var isList = (FORM.formKind === "ListForm" || FORM.formKind === "ChoiceForm") &&
          String(table.dataPath || table.name).indexOf("Объект.") !== 0;
        var names = isList ? (FORM.formKind === "ChoiceForm" ? ["Choose"] : []).concat(MORE_LIST)
          : [].concat.apply([], MORE_TABLE);
        return names.map(function (name) { return { name: name, title: MORE_COMMANDS[name][0] }; });
      },
      errors: errors,
      onDraw: null
    };
  }

  try {
    if (state["static"]) document.body.classList.add("fm-static");
    if (state.names) document.body.classList.add("fm-show-names");
    if (state.hidden) document.body.classList.add("fm-show-hidden");
    if (!EDITOR) renderToolbar();
    setupLayer();
    setupDiff();
    setupTooltip();
    if (!EDITOR) {
      renderForm();
      runActions(state.act);
    }
  } catch (error) {
    errors.push(String(error && error.stack || error));
    document.getElementById("fm-result").textContent = JSON.stringify({ notes: [], errors: errors, width: 0, height: 0, pages: [] });
  }
})();
