/* Конструктор макета формы: дерево элементов, макет рендерера, панель свойств.
   Модель - у сервера `formmockup.py serve`: GET /model - модель и версия файла (ETag), POST /check -
   замечания, PUT /model - запись по версии (If-Match), GET /version раз в секунду - слежение за файлом.
   Рендерер перерисовывает ту же страницу по новой модели (window.FMRender), выбор рисуется рамкой в его слое.
   Действия сценариев теста - в адресе: #do=tree:Имя;click:Имя;key:ArrowDown;set:свойство=значение;
   reset:свойство;spin:свойство=up|down;save;check;wait:мс;hidden:on;names:on;reread;keep; окна выбора -
   choose:свойство;pick:путь;command:Имя=true|false;tab:закладка;color:значение;rgb:RRGGBB;
   fmt:КЛЮЧ=значение;fmtoff:КЛЮЧ;sample:значение;list:add=текст|delete|up|down|fill;row:N;find:текст;picture:Имя;ok;cancel;
   composite:on;section:группа;dlg-set|panel-set:селектор=значение; левая колонка - left:items|attributes|commands;attr-pick:путь;
   attr-add[:column];attr-delete;cmd-pick:Имя;cmd-add;cmd-delete;usage:ключ строки;left-width:px; правка структуры - palette;
   add:Вид;delete;move:up|down;alt:ArrowUp;drag:Источник>Цель@before|after|inside;undo;redo;hotkey:[Shift+]KeyZ -
   итог JSON в pre#fe-result. */
(function () {
  "use strict";

  var R = window.FMRender;
  if (!R) return;
  var DATA = JSON.parse(document.getElementById("fm-data").textContent);
  var ED = DATA.editor;
  // Макет в сервисе по папке: страница `/edit?file=<путь>`, запросы макета - с тем же `file`;
  // без него - макет запуска (`serve model.json`)
  // и с папкой, из которой открыта страница: после «Другой папки» сервер ответит 409, а не запишет
  // одноименный файл новой папки
  var FILE_QUERY = (function () {
    var file = new URLSearchParams(location.search).get("file");
    var parts = [];
    if (file) parts.push("file=" + encodeURIComponent(file));
    if (ED.folder) parts.push("folder=" + encodeURIComponent(ED.folder));
    return parts.join("&");
  })();
  function modelUrl(path) {
    return FILE_QUERY ? path + (path.indexOf("?") >= 0 ? "&" : "?") + FILE_QUERY : path;
  }
  var DICT = ED.dictionary;
  var KINDS = ED.kinds;
  var GROUPS = ED.groups;
  var PLATFORM = ED.platform;

  var FORM_KEY = "Форма";       // ключ корня дерева - как имя окна формы у рендерера
  var TIP_PREFIX = "@tip:";      // узел «Расширенная подсказка» элемента
  var POLL_MS = 1000;
  var CHECK_DELAY = 150;
  var MULTILINE = { note: true, title: true, toolTip: true, extendedTooltip: true };
  // Пустая строка значима: заголовок без текста, пустой пример (поле надписи без значения)
  var KEEP_EMPTY = { title: true, sample: true };
  var NUMBER = /^-?(0|[1-9]\d*)(\.\d+)?$/;
  var NAME_1C = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;
  var errors = R.errors;

  // Состояние

  var model = null;            // модель на странице
  var savedText = "";          // модель последнего чтения или записи: «есть правки» - сравнением
  var baseEtag = null;         // версия файла, от которой идут правки страницы
  var diskEtag = null;         // последняя увиденная версия файла
  var keepEtag = null;         // «Оставить мои» для этой версии: баннер не показывать
  var issues = [];
  var pictures = {};           // стандартные картинки от сервера - только для рисования
  var baseNames = null;        // имена элементов «было» - для renamedFrom; null - еще не загружены
  var baseFile = null;         // файл «было» (`serve --before`); null - «было» = файл на запуске сервера
  var addedNames = {};         // добавленные в конструкторе: им renamedFrom не ставится
  // Правки против «было»: считает сервер при проверке; объединенное дерево - для рисования, пока
  // модель та же, по которой оно посчитано (`diffText`)
  var diffOn = false;          // переключатель «Правки»
  var changes = null;          // правки от сервера; null - не посчитаны (блокирующие замечания)
  var diffTree = null;
  var diffText = null;
  var activeChange = 0;        // правка, выбранная в списке или щелчком по удаленному
  var rightTab = "props";      // закладка правой колонки: props | notes | changes
  var noteDraft = null;        // ключ элемента без примечания, которому пункт меню «Примечание» открыл пустую строку
  var propsDiffShown = "";     // отметки правок, нарисованные в панели свойств
  var shownDiffs = {};         // измененные свойства элемента в панели: свойство → { before }
  var selected = FORM_KEY;
  var folded = {};             // свернутые узлы дерева
  var foldedGroups = {};       // свернутые группы панели свойств
  var alphabetical = false;
  var search = "";
  var entries = {};            // ключ дерева → узел дерева
  var tree = null;
  var online = true;
  var unreadable = "";         // файл на диске не читается: текст причины
  var fileUpdated = false;     // модель перечитана сама после записи мимо конструктора
  var conflict = false;        // баннер «Файл изменён на диске»
  var movedFolder = "";        // сервис переключен на другую папку макетов - ее путь; сохранение выключено
  var saveError = "";
  var blocked = false;         // блокирующие замечания: вместо макета - список
  var invalid = {};            // свойство → причина: значение не применено
  var invalidText = {};        // свойство → набранный текст недопустимого значения: остается в поле
  var focusProp = null;        // поле свойства, куда вернуть фокус после перерисовки панели
  var frameShown = false;
  var picked = [];             // еще выделенные (Ctrl, Shift) кроме `selected` - ключи дерева
  var pickEnd = null;          // конец диапазона Shift: от него Shift+стрелки идут дальше
  var batching = false;        // правка нескольких элементов: перестройка - одна, в конце
  var batchChanged = false;
  var renderMs = 0;
  var ui = {};

  // Помощники

  function h(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function px(value) { return Math.round(value) + "px"; }

  function has(node, prop) { return Object.prototype.hasOwnProperty.call(node, prop); }

  function textOf(value) { return JSON.stringify(value); }

  function dirty() { return model !== null && textOf(model) !== savedText; }
  // Окно закрывается по «Завершить» на списке - вопрос браузера о несохраненных правках не нужен
  var quitting = false;

  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function kindTitle(kind) {
    return kind === "Form" ? "Форма" : kind === "Attribute" ? "Реквизит" : kind === "Command" ? "Команда" : (DICT.types[kind] || kind);
  }

  // Название свойства платформы - слитно, как в палитре конфигуратора; свойства вне платформы - как в словаре
  function propTitle(prop) {
    if (prop === "type") return "Вид";
    var russian = DICT.properties[prop] || prop;
    if (PLATFORM[prop]) return russian;
    return russian.split(/\s+/).map(function (word) { return word.charAt(0).toUpperCase() + word.slice(1); }).join("");
  }

  function valueTitle(prop, value) {
    var values = DICT.values[prop] || {};
    return values[value] || String(value);
  }

  function defaultOf(kind, prop) {
    var own = GROUPS.defaults[kind] || {};
    if (has(own, prop)) return own[prop];
    return has(GROUPS.defaults["*"], prop) ? GROUPS.defaults["*"][prop] : undefined;
  }

  // Новое свойство - перед подчиненными (`commandBar`, `items`), `after` - сразу за указанным: правка
  // в файле там, где ее ждет читатель, а не после дерева элементов
  function setProp(node, prop, value, after) {
    if (has(node, prop)) {
      node[prop] = value;
      return;
    }
    var keys = Object.keys(node);
    var index = after && keys.indexOf(after) >= 0 ? keys.indexOf(after) + 1
      : keys.findIndex(function (key) { return key === "commandBar" || key === "items" || key === "columns" || key === "additionalColumns"; });
    if (index < 0) {
      node[prop] = value;
      return;
    }
    var tail = {};
    keys.slice(index).forEach(function (key) {
      tail[key] = node[key];
      delete node[key];
    });
    node[prop] = value;
    Object.keys(tail).forEach(function (key) { node[key] = tail[key]; });
  }

  function collectNames(node, names) {
    names = names || {};
    if (!node || typeof node !== "object") return names;
    if (typeof node.name === "string") names[node.name] = true;
    if (node.commandBar) collectNames(node.commandBar, names);
    (Array.isArray(node.items) ? node.items : []).forEach(function (item) { collectNames(item, names); });
    return names;
  }

  function formOf(value) {
    return value && typeof value === "object" && value.form && typeof value.form === "object" ? value.form : {};
  }

  // Дерево элементов: корень «Форма», первой - командная панель формы, у таблицы - своя панель и
  // колонки, заданная расширенная подсказка - подчиненным узлом своего элемента

  function buildTree() {
    entries = {};
    var form = formOf(model);
    tree = entry(FORM_KEY, form, "Form", "Форма", null);
    tree.children.push(barEntry(form, "ФормаКоманднаяПанель", tree));
    addItems(tree, form);
  }

  // Ключ узла - имя элемента; повтор имени (сломанная модель) - с номером, чтобы узел оставался выбираемым
  function entry(key, node, kind, label, parent) {
    var unique = key;
    for (var n = 2; has(entries, unique); n++) unique = key + "#" + n;
    var item = { key: unique, node: node, kind: kind, label: label, parent: parent, children: [] };
    entries[unique] = item;
    return item;
  }

  function keyOf(node, tip) {
    var keys = Object.keys(entries);
    for (var i = 0; i < keys.length; i++) {
      if (entries[keys[i]].node === node && !!entries[keys[i]].tip === !!tip) return keys[i];
    }
    return null;
  }

  // Командной панели нет в модели - узел по умолчанию с именем, как рисует рендерер; первая правка ее заводит
  function barEntry(owner, defaultName, parent) {
    var bar = owner.commandBar && typeof owner.commandBar === "object" ? owner.commandBar : null;
    var node = bar || { type: "AutoCommandBar", name: defaultName };
    var item = entry(node.name || defaultName, node, "AutoCommandBar", "Командная панель", parent);
    item.owner = owner;
    item.virtual = !bar;
    addItems(item, node);
    return item;
  }

  function addItems(parent, node) {
    (Array.isArray(node.items) ? node.items : []).forEach(function (child, index) {
      if (!child || typeof child !== "object") return;
      var name = typeof child.name === "string" ? child.name : "(без имени " + parent.key + "/" + index + ")";
      var item = entry(name, child, child.type, name, parent);
      parent.children.push(item);
      if (child.extendedTooltip) {
        var tip = entry(TIP_PREFIX + name, child, child.type, "Расширенная подсказка", item);
        tip.tip = true;
        item.children.push(tip);
      }
      if (child.type === "Table") item.children.push(barEntry(child, name + "КоманднаяПанель", item));
      addItems(item, child);
    });
  }

  // Имя элемента на макете: у узла подсказки - имя его элемента
  function elementName(key) {
    var item = entries[key];
    if (!item || item.kind === "Form") return FORM_KEY;
    return item.tip ? item.parent.node.name : item.node.name;
  }

  var ICONS = {
    form: '<rect x="1.5" y="2.5" width="13" height="11" fill="#fff" stroke="#3d6ea8"/><path d="M1.5 5.5h13" stroke="#3d6ea8"/><path d="M3.5 8h4M3.5 10.5h6" stroke="#9ab0c8"/>',
    folder: '<path d="M1.5 4.5v8.5h13V5.5H7.5L6 3.5H1.5z" fill="#f6d77a" stroke="#c9a33a"/>',
    bar: '<rect x="1.5" y="5.5" width="13" height="5" fill="#eee" stroke="#888"/><path d="M5.5 5.5v5M9.5 5.5v5" stroke="#888"/>',
    field: '<rect x="2" y="7" width="11" height="3" rx="1" fill="#e2463a"/>',
    check: '<rect x="3.5" y="3.5" width="9" height="9" fill="#fff" stroke="#666"/><path d="M5 8l2 2 4-4" stroke="#2e9b3a" stroke-width="1.6" fill="none"/>',
    radio: '<circle cx="8" cy="8" r="4.5" fill="#fff" stroke="#666"/><circle cx="8" cy="8" r="2" fill="#2e9b3a"/>',
    table: '<rect x="1.5" y="2.5" width="13" height="11" fill="#fff" stroke="#3d6ea8"/><path d="M1.5 5.5h13M1.5 8.5h13M1.5 11h13M6 2.5v11" stroke="#3d6ea8"/>',
    button: '<rect x="1.5" y="4.5" width="13" height="8" rx="1.5" fill="#fbe9d0" stroke="#c98a3a"/><text x="8" y="10.8" font-size="5.5" text-anchor="middle" fill="#a0601a" font-family="Arial" font-weight="bold">OK</text>',
    label: '<text x="8" y="12.5" font-size="11" text-anchor="middle" fill="#3d6ea8" font-family="Arial" font-weight="bold">A</text>',
    picture: '<rect x="1.5" y="3.5" width="13" height="10" fill="#fff" stroke="#3d6ea8"/><circle cx="5.5" cy="7" r="1.3" fill="#e0a800"/><path d="M2 13l4-4 3 3 2-2 3.5 3.5" fill="none" stroke="#2e9b3a"/>',
    attribute: '<rect x="2.5" y="6.5" width="11" height="3" rx="1" fill="#8aa0bf" stroke="#5f7aa3"/>',
    tip: '<rect x="2.5" y="3.5" width="11" height="8" fill="#fff" stroke="#c0392b"/><path d="M4.5 6h7M4.5 8.5h5" stroke="#3d6ea8"/>',
    unknown: '<rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="#888" stroke-dasharray="2 1.5"/>'
  };
  var KIND_ICONS = {
    Form: "form", UsualGroup: "folder", Pages: "folder", Page: "folder", ColumnGroup: "folder", ButtonGroup: "folder",
    Popup: "folder", CommandBar: "bar", AutoCommandBar: "bar", CheckBoxField: "check", RadioButtonField: "radio",
    Table: "table", Button: "button", LabelDecoration: "label", PictureDecoration: "picture", Unknown: "unknown"
  };

  function treeIcon(item) {
    var span = h("span", "fe-icon");
    span.innerHTML = '<svg viewBox="0 0 16 16">' + ICONS[item.tip ? "tip" : KIND_ICONS[item.kind] || "field"] + "</svg>";
    return span;
  }

  // Стрелка раскрытия узла - галочкой, как у групп свойств (рисует CSS)
  function twistyOf(expandable, open) {
    return h("span", "fe-twisty" + (expandable ? " fe-twisty-on" + (open ? " fe-open" : "") : ""));
  }

  function renderTree() {
    var box = ui.tree;
    box.innerHTML = "";
    if (!tree) return;
    var gone = removedPlaces();
    (function visit(item, depth) {
      var row = h("div", "fe-row");
      row.dataset.key = item.key;
      row.style.paddingLeft = px(4 + depth * 16);
      if (item.key === selected || picked.indexOf(item.key) >= 0) row.classList.add("fe-selected");
      if (!item.tip && item.node.visible === false) row.classList.add("fe-pale");
      if (movable(item)) row.draggable = true;
      var removedHere = (!item.tip && gone[item.key]) || [];
      var twisty = twistyOf(item.children.length > 0, !folded[item.key]);
      row.appendChild(twisty);
      row.appendChild(treeIcon(item));
      row.appendChild(h("span", "fe-label", item.label));
      // Правка против «было»: цвет и номер у правого края
      var change = changeOfItem(item);
      if (change) {
        row.classList.add("fe-diff-" + change.op);
        row.dataset.change = change.n;
        row.appendChild(diffBadge(change));
      }
      box.appendChild(row);
      if (folded[item.key]) return;
      // Удаленные - на старых местах: после соседа, который был выше, или первыми
      var shown = {};
      var removedAfter = function (key) {
        removedHere.forEach(function (place) {
          if (place.after !== key || shown[place.change.n]) return;
          shown[place.change.n] = true;
          box.appendChild(removedRow(place, depth + 1));
        });
      };
      removedAfter(null);
      item.children.forEach(function (child) {
        visit(child, depth + 1);
        removedAfter(child.key);
      });
      removedHere.forEach(function (place) {
        if (shown[place.change.n]) return;
        shown[place.change.n] = true;
        box.appendChild(removedRow(place, depth + 1));
      });
    })(tree, 0);
    var current = box.querySelector(".fe-selected");
    if (current) current.scrollIntoView({ block: "nearest", inline: "nearest" });
    renderItemTools();
  }

  function unfoldTo(key) {
    for (var item = entries[key] && entries[key].parent; item; item = item.parent) delete folded[item.key];
  }

  function visibleKeys() {
    return Array.prototype.map.call(ui.tree.querySelectorAll(".fe-row[data-key]"), function (row) { return row.dataset.key; });
  }

  // Стрелки в дереве, как в конфигураторе: вверх-вниз - соседняя строка, вправо - раскрыть или к первому
  // подчиненному, влево - свернуть или к родителю. `tree` - { keys, current, children(key), open(key),
  // setOpen(key, on), parent(key), select(key) }; итог - обработана ли клавиша
  function treeNavigate(event, tree) {
    var keys = tree.keys;
    var current = tree.current;
    var index = keys.indexOf(current);
    var children = current === null || current === undefined ? [] : tree.children(current);
    var next = null;
    if (event.key === "ArrowDown") next = index < 0 ? keys[0] : keys[index + 1];
    else if (event.key === "ArrowUp") next = index < 0 ? keys[keys.length - 1] : keys[index - 1];
    else if (event.key === "Home") next = keys[0];
    else if (event.key === "End") next = keys[keys.length - 1];
    else if (event.key === "ArrowRight") {
      if (!children.length) return true;
      if (!tree.open(current)) tree.setOpen(current, true);
      else next = children[0];
    } else if (event.key === "ArrowLeft") {
      if (children.length && tree.open(current)) tree.setOpen(current, false);
      else next = tree.parent(current);
    } else {
      return false;
    }
    if (next !== null && next !== undefined) tree.select(next);
    return true;
  }

  function treeKey(event) {
    if (!entries[selected]) return;
    if (event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey &&
        (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      extendPick(event.key === "ArrowUp" ? -1 : 1);
      return;
    }
    // Правка структуры с клавиатуры: Alt+стрелки - среди соседей, Del - удаление
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      moveSibling(event.key === "ArrowUp" ? -1 : 1);
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelected();
      return;
    }
    // Shift+F10 - контекстное меню: на macOS браузер сам его не открывает
    if (event.key === "F10" && event.shiftKey) {
      event.preventDefault();
      openContext(selected, null, false);
      return;
    }
    // Insert - палитра у выбранной строки, как «Добавить» в конфигураторе
    if (event.key === "Insert") {
      event.preventDefault();
      var row = ui.tree.querySelector(".fe-selected");
      var rect = row ? row.getBoundingClientRect() : null;
      openPalette({ at: rect ? { x: rect.left + 24, y: rect.bottom } : null, focus: true });
      return;
    }
    var done = treeNavigate(event, {
      // После Shift+стрелок стрелка без Shift идет от конца диапазона, как в проводнике
      keys: visibleKeys(), current: picked.length && entries[pickEnd] ? pickEnd : selected,
      children: function (key) { return entries[key].children.map(function (child) { return child.key; }); },
      open: function (key) { return !folded[key]; },
      setOpen: function (key, on) {
        if (on) delete folded[key];
        else folded[key] = true;
        renderTree();
      },
      parent: function (key) { return entries[key].parent ? entries[key].parent.key : null; },
      select: function (key) { select(key); }
    });
    if (done) event.preventDefault();
  }

  // Выбор: из дерева - элемент показан на макете (закладка, свернутые группы) и обведен рамкой; скрытый при
  // снятых «Скрытых» - только в дереве и свойствах, макет не меняется (владелец 04.11.2026); с макета - выбран
  // узел дерева и свойства

  function select(key, fromLayout) {
    picked = [];
    pickEnd = null;
    if (!entries[key]) key = FORM_KEY;
    if (elementName(key) !== elementName(selected)) {
      invalid = {};
      invalidText = {};
    }
    selected = key;
    unfoldTo(key);
    renderTree();
    renderProps();
    var item = entries[key];
    if (!fromLayout && !blocked) {
      // Панели нет в модели - показать ее владельца (таблицу)
      var target = item.virtual ? elementName(item.parent.key) : elementName(key);
      R.reveal(target, true);
      var element = R.element(elementName(key));
      if (element) R.partsOf(element)[0].scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    if (item.tip) focusField("extendedTooltip");
    // Рамка скрытого пропадает сразу, не дожидаясь перерисовки слоя
    if (hiddenOnLayout(key)) frameShown = false;
    R.redraw();
  }

  function layoutClick(event) {
    if (!model) return;
    var tab = event.target.closest(".fm-tab[data-page]");
    var element = tab || event.target.closest("#fm-root .fm-item[data-name]");
    if (!element) return;
    var key = tab ? tab.dataset.page : element.dataset.name;
    if (!entries[key]) {
      // Удаленный или тень перенесенного - его правка в списке
      var change = diffOn && (changes || []).filter(function (one) {
        return one.op === "removed" && one.before === key || one.ghost === key;
      })[0];
      if (change) showChange(change.n, true);
      return;
    }
    if (leftMode !== "items") setLeftMode("items");
    if (event.ctrlKey || event.metaKey || event.shiftKey) togglePick(key);
    else select(key, true);
    ui.tree.focus();
  }

  // Несколько выделенных: Ctrl (Cmd) - добавить или убрать элемент, Shift в дереве -
  // диапазон видимых строк от выбранного. Выделяются элементы формы: не форма, не подсказка, не панель вне модели.
  // Удаление и общие свойства - у всех сразу, одним шагом отмены; перенос - по одному
  function pickable(item) { return !!item && !item.tip && !item.virtual && item.kind !== "Form"; }

  function selection() {
    return [selected].concat(picked.filter(function (key) { return key !== selected && entries[key]; }));
  }

  function multiSelected() { return leftMode === "items" && picked.length > 0; }

  function togglePick(key) {
    pickEnd = null;
    if (!pickable(entries[key]) || !pickable(entries[selected])) {
      select(key);
      return;
    }
    if (key === selected) {
      if (!picked.length) return;
      selected = picked.shift();
    } else if (picked.indexOf(key) >= 0) {
      picked.splice(picked.indexOf(key), 1);
    } else {
      picked.push(key);
    }
    showPicked();
  }

  function rangePick(key) {
    var keys = visibleKeys();
    var from = keys.indexOf(selected);
    var to = keys.indexOf(key);
    if (from < 0 || to < 0 || !pickable(entries[key])) {
      select(key);
      return;
    }
    var range = keys.slice(Math.min(from, to), Math.max(from, to) + 1).filter(function (one) {
      return pickable(entries[one]);
    });
    if (!pickable(entries[selected])) selected = range[0];
    picked = range.filter(function (one) { return one !== selected; });
    pickEnd = key;
    showPicked();
  }

  // Shift+стрелки в дереве (владелец 07.11.2026): конец диапазона - на соседнюю строку, начало - выбранный.
  // Строки, которые не выделяются (форма, панель вне модели), проходятся насквозь
  function extendPick(delta) {
    var keys = visibleKeys();
    var at = keys.indexOf(pickEnd && keys.indexOf(pickEnd) >= 0 ? pickEnd : selected);
    for (at += delta; at >= 0 && at < keys.length; at += delta) {
      if (!pickable(entries[keys[at]])) continue;
      rangePick(keys[at]);
      var row = ui.tree.querySelector('.fe-row[data-key="' + CSS.escape(keys[at]) + '"]');
      if (row) row.scrollIntoView({ block: "nearest", inline: "nearest" });
      return;
    }
  }

  function showPicked() {
    invalid = {};
    invalidText = {};
    renderTree();
    renderProps();
    R.redraw();
  }

  // Правая кнопка по элементу макета - выбор и контекстное меню; мимо элементов - меню браузера
  function layoutContext(event) {
    if (!model || blocked) return;
    var tab = event.target.closest(".fm-tab[data-page]");
    var element = tab || event.target.closest("#fm-root .fm-item[data-name]");
    var key = element ? (tab ? tab.dataset.page : element.dataset.name) : null;
    if (!key || !entries[key]) return;
    event.preventDefault();
    openContext(key, pointOf(event), true);
  }

  // Элемент или его группа скрыты (`visible: false`), а «Скрытые» сняты: на макете его нет - рамки тоже
  function hiddenOnLayout(key) {
    if (R.showHidden()) return false;
    for (var item = entries[key]; item && item.kind !== "Form"; item = item.parent) {
      if (!item.tip && item.node.visible === false) return true;
    }
    return false;
  }

  function drawSelection(layer) {
    frameShown = false;
    if (!model || blocked) return;
    (leftMode === "items" ? selection() : [selected]).forEach(function (key) {
      if (hiddenOnLayout(key)) return;
      var element = R.element(elementName(key));
      var rect = element ? R.visibleRect(element) : null;
      if (!rect) return;
      var frame = h("div", "fe-frame");
      frame.style.left = px(rect.left + window.scrollX - 3);
      frame.style.top = px(rect.top + window.scrollY - 3);
      frame.style.width = px(rect.right - rect.left + 6);
      frame.style.height = px(rect.bottom - rect.top + 6);
      layer.appendChild(frame);
      if (key === selected) frameShown = true;
    });
  }

  // Панель свойств: все свойства вида по схеме, группами и в порядке property-groups.json

  function currentItem() {
    if (leftMode === "attributes") return attrEntries[attrSelected] || null;
    if (leftMode === "commands") return cmdEntries[cmdSelected] || null;
    return entries[selected] || tree;
  }

  function propGroups(kind, specs) {
    var layout = GROUPS.kinds[kind] || GROUPS["default"];
    var listed = {};
    var groups = layout.map(function (group) {
      var blocks = group.blocks.map(function (block) {
        return block.filter(function (prop) { return has(specs, prop); });
      }).filter(function (block) { return block.length; });
      blocks.forEach(function (block) { block.forEach(function (prop) { listed[prop] = true; }); });
      return { group: group.group, blocks: blocks };
    }).filter(function (group) { return group.blocks.length; });
    // Свойство вида вне групп - в «Прочие» (тест следит, чтобы таких не было)
    var rest = Object.keys(specs).filter(function (prop) { return !listed[prop]; });
    if (rest.length) groups.push({ group: "Прочие", blocks: [rest] });
    if (alphabetical) {
      var all = Object.keys(specs).sort(function (a, b) { return propTitle(a).localeCompare(propTitle(b), "ru"); });
      groups = [{ group: null, blocks: [all] }];
    }
    var query = search.trim().toLowerCase();
    if (query) {
      groups = groups.map(function (group) {
        return { group: group.group, blocks: group.blocks.map(function (block) {
          return block.filter(function (prop) {
            return propTitle(prop).toLowerCase().indexOf(query) >= 0 || prop.toLowerCase().indexOf(query) >= 0 ||
              (DICT.properties[prop] || "").toLowerCase().indexOf(query) >= 0;
          });
        }).filter(function (block) { return block.length; }) };
      }).filter(function (group) { return group.blocks.length; });
    }
    return groups;
  }

  // Свойства по типу значения поля (тип - из реквизита, `dataType` в модели): формат у числа, даты и булева. Тип не
  // задан или свойство уже в модели - показывается: панель не прячет записанное
  // Подсказка ввода у числа и даты не выводится (справочник синтаксиса: РасширениеПоляФормыДляПоляВвода.ПодсказкаВвода)
  var BY_DATA_TYPE = { format: ["number", "date", "boolean"], inputHint: ["string", "ref", "boolean"] };
  var COMMAND_CONTAINERS = { AutoCommandBar: true, CommandBar: true, ButtonGroup: true, Popup: true };

  // Место элемента для применимости свойств (places в property-groups.json): колонка таблицы, кнопка в командной
  // панели, кнопка среди элементов формы, остальное - вне таблицы
  function placeOf(item) {
    // Узел «Расширенная подсказка» - место своего элемента
    if (item.tip) item = item.parent;
    for (var up = item.parent; up; up = up.parent) {
      if (COMMAND_CONTAINERS[up.kind]) return "commandBar";
      if (up.kind === "Table") return "column";
    }
    return item.kind === "Button" || item.kind === "Popup" ? "form" : "body";
  }

  function placeAllowed(kind, prop, place) {
    var own = (GROUPS.places[kind] || {})[prop] || (GROUPS.places["*"] || {})[prop];
    return !own || own.indexOf(place) >= 0;
  }

  var MAX_OF = { maxWidth: "autoMaxWidth", maxHeight: "autoMaxHeight" };
  // Включенное «авто» сбрасывает максимум, как в конфигураторе: поле максимума пропадает из панели
  var AUTO_MAX = { autoMaxWidth: "maxWidth", autoMaxHeight: "maxHeight" };
  var HEIGHT_MAX = { autoMaxHeight: true, maxHeight: true };

  function applicable(item, specs) {
    var type = item.node.dataType;
    var typed = item.kind === "InputField" && typeof type === "string";
    var place = placeOf(item);
    var shown = {};
    Object.keys(specs).forEach(function (prop) {
      var byType = !typed || !has(BY_DATA_TYPE, prop) || BY_DATA_TYPE[prop].indexOf(type) >= 0;
      // Формат у поля флажка - только у тумблера (надписи положений)
      if (item.kind === "CheckBoxField" && prop === "format") byType = item.node.checkBoxType === "Tumbler";
      // Предел высоты поля ввода - у многострочного: однострочное по высоте не растет
      if (item.kind === "InputField" && HEIGHT_MAX[prop]) byType = byType && (item.node.multiLine === true || item.node.height > 1);
      // Максимальные ширина и высота - при снятом «авто», как в палитре (владелец 04.11.2026)
      if (has(MAX_OF, prop)) byType = byType && item.node[MAX_OF[prop]] === false;
      if (byType && placeAllowed(item.kind, prop, place) || isSet(item, prop)) shown[prop] = specs[prop];
    });
    return shown;
  }

  // Свойства нескольких выделенных: сводный элемент - общие свойства (есть у каждого, ввод того же
  // вида); значение - у всех одно (заданное или одинаковое по умолчанию), иначе «разные значения». Правка
  // применяется ко всем (apply → applyMany). Имя, вид и то, что правится окном выбора или списком, - «недоступно»
  var MULTI_OFF = { name: true, type: true, dataPath: true, commandName: true, currentPage: true, commandSource: true,
    autoFill: true };
  var MULTI_OFF_INPUTS = { list: true, rows: true, choices: true, font: true, type: true, color: true };

  function multiItem() {
    var items = selection().map(function (key) { return entries[key]; });
    var all = items.map(function (one) { return applicable(one, KINDS[one.kind] || KINDS.Unknown); });
    var specs = {};
    Object.keys(all[0]).forEach(function (prop) {
      var same = all.every(function (own) { return has(own, prop) && own[prop].input === all[0][prop].input; });
      if (same) specs[prop] = all[0][prop];
    });
    var node = {};
    var mixed = {};
    Object.keys(specs).forEach(function (prop) {
      var values = items.map(function (one) {
        return JSON.stringify(isSet(one, prop) ? ["set", one.node[prop]] : ["default", defaultOf(one.kind, prop)]);
      });
      if (values.some(function (value) { return value !== values[0]; })) mixed[prop] = true;
      else if (isSet(items[0], prop)) node[prop] = items[0].node[prop];
    });
    return { multi: items, kind: items[0].kind, node: node, mixed: mixed, specs: specs, key: selected, children: [] };
  }

  function multiTitle(items) {
    var kinds = [];
    items.forEach(function (one) {
      var title = kindTitle(one.kind);
      if (kinds.indexOf(title) < 0) kinds.push(title);
    });
    var count = items.length;
    var word = count % 10 === 1 && count % 100 !== 11 ? "элемент"
      : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 10 || count % 100 >= 20) ? "элемента" : "элементов";
    return "Свойства: " + count + " " + word + " (" + kinds.join(", ") + ")";
  }

  function multiEditable(prop, spec) {
    return !MULTI_OFF[prop] && !MULTI_OFF_INPUTS[spec.input] && !chooserOf(prop, spec) &&
      GROUPS.locked.indexOf(prop) < 0;
  }

  // Разные значения у выделенных: пустое поле с серой надписью, флажок - в промежуточном положении, список - пункт
  // «разные значения» (выбрать его нельзя)
  function markMixed(field) {
    var input = field.classList.contains("fe-input") ? field : field.querySelector(".fe-input");
    if (!input) return;
    input.classList.add("fe-mixed");
    input.classList.remove("fe-default");
    if (input.tagName === "SELECT") {
      var mixed = option("", "разные значения");
      mixed.disabled = true;
      mixed.className = "fe-mixed-option";
      input.insertBefore(mixed, input.firstChild);
      input.selectedIndex = 0;
    } else if (input.type === "checkbox") {
      input.indeterminate = true;
    } else {
      input.value = "";
      input.placeholder = "разные значения";
    }
  }

  // Правка сводного элемента - каждому выделенному; перестройка и шаг отмены - один. Значение не прошло проверку
  // у первого - остальным не применяется (проверка от значения, у всех одна)
  function applyMany(proxy, prop, value, text) {
    batching = true;
    batchChanged = false;
    try {
      for (var i = 0; i < proxy.multi.length; i++) {
        apply(proxy.multi[i], prop, value, text);
        if (has(invalid, prop)) break;
      }
    } finally {
      batching = false;
    }
    if (batchChanged) {
      batchChanged = false;
      changed();
    } else if (has(invalid, prop)) {
      renderProps();
    }
  }

  function renderProps() {
    var item = multiSelected() ? multiItem() : currentItem();
    shownDiffs = {};
    propsDiffShown = "";
    if (leftMode === "attributes" && (!item || !item.editable)) {
      renderAttrInfo(item);
      return;
    }
    if (leftMode === "commands" && !item) {
      ui.propsTitle.textContent = "Свойства: Команда";
      ui.propsBody.innerHTML = "";
      ui.propsBody.appendChild(h("div", "fe-props-note", "Выберите команду формы в списке слева или добавьте новую"));
      return;
    }
    if (!item) return;
    var kind = item.kind;
    var specs = item.multi ? item.specs : kind === "Attribute" ? attrApplicable(item, KINDS.Attribute)
      : kind === "Command" ? KINDS.Command : applicable(item, KINDS[kind] || KINDS.Unknown);
    ui.propsTitle.textContent = item.multi ? multiTitle(item.multi) : "Свойства: " + kindTitle(kind);
    var body = ui.propsBody;
    body.innerHTML = "";
    // Правка элемента против «было»: номер и вид под заголовком, отметки у свойств
    var change = item.multi ? null : changeOfItem(item);
    shownDiffs = item.multi ? {} : propDiffs(item);
    propsDiffShown = item.multi ? "" : propsDiffKey(item);
    if (change) {
      var line = h("div", "fe-props-change fe-diff-" + change.op);
      line.appendChild(diffBadge(change));
      line.appendChild(h("span", "", change.what));
      line.title = change.details.join("\n");
      line.addEventListener("click", function () { showChange(change.n, true); });
      body.appendChild(line);
    }
    propGroups(kind, specs).forEach(function (group) {
      var section = h("div", "fe-group");
      if (group.group) {
        var head = h("div", "fe-group-head", group.group);
        head.dataset.group = group.group;
        if (foldedGroups[group.group]) section.classList.add("fe-folded");
        head.tabIndex = 0;
        head.addEventListener("click", function () { foldGroup(section, group.group, !foldedGroups[group.group]); });
        head.addEventListener("keydown", function (event) { groupKey(event, section, group.group); });
        section.appendChild(head);
      }
      group.blocks.forEach(function (block) {
        var box = h("div", "fe-block");
        for (var i = 0; i < block.length; i++) {
          // «Ширина» и «Высота» - в одной строке, как в палитре
          if (block[i] === "width" && block[i + 1] === "height") {
            box.appendChild(sizeRow(item, kind, specs));
            i++;
          } else {
            box.appendChild(propRow(item, kind, block[i], specs[block[i]]));
          }
        }
        section.appendChild(box);
      });
      body.appendChild(section);
    });
    if (focusProp) {
      focusField(focusProp);
      focusProp = null;
    }
  }

  function foldGroup(section, name, on) {
    foldedGroups[name] = on;
    section.classList.toggle("fe-folded", on);
  }

  // Заголовок группы свойств с клавиатуры: влево - свернуть, вправо - развернуть, пробел и Enter - переключить,
  // вверх-вниз - соседний заголовок
  function groupKey(event, section, name) {
    var heads = Array.prototype.slice.call(ui.propsBody.querySelectorAll(".fe-group-head"));
    var index = heads.indexOf(event.currentTarget);
    if (event.key === "ArrowLeft") foldGroup(section, name, true);
    else if (event.key === "ArrowRight") foldGroup(section, name, false);
    else if (event.key === "Enter" || event.key === " ") foldGroup(section, name, !foldedGroups[name]);
    else if (event.key === "ArrowDown" && heads[index + 1]) heads[index + 1].focus();
    else if (event.key === "ArrowUp" && heads[index - 1]) heads[index - 1].focus();
    else return;
    event.preventDefault();
  }

  function propLabel(prop) {
    var label = h("span", "fe-prop-name", propTitle(prop));
    label.title = prop + (PLATFORM[prop] ? " - " + PLATFORM[prop] : "");
    return label;
  }

  // Измененное против «было» свойство: отметка цвета правки у строки, «было» - в подсказке названия
  function diffLabel(label, prop, row) {
    if (!has(shownDiffs, prop)) return label;
    var entry = shownDiffs[prop];
    row.classList.add("fe-prop-diff");
    label.title += "\nБыло: " + (has(entry, "before") ? valueText(entry.before) : "не задано");
    return label;
  }

  function isSet(item, prop) {
    if (item.multi) return item.multi.some(function (one) { return isSet(one, prop); });
    return !item.virtual && has(item.node, prop);
  }

  function resetButton(item, prop) {
    var button = h("button", "fe-in fe-reset", "×");
    button.type = "button";
    button.tabIndex = -1;
    button.title = "По умолчанию: убрать свойство из модели";
    button.dataset.prop = prop;
    // Без ухода фокуса из поля: набранный текст не применяется перед сбросом
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () { apply(item, prop, undefined); });
    return button;
  }

  // Кнопки «+/-» числа: шаг от набранного, заданного или умолчания, не ниже границы схемы
  function spinButtons(item, prop, spec, input) {
    var spin = h("span", "fe-spin");
    [["fe-up", 1, "Увеличить"], ["fe-down", -1, "Уменьшить"]].forEach(function (part) {
      var button = h("button", "fe-in " + part[0]);
      button.type = "button";
      button.tabIndex = -1;
      button.title = part[2];
      button.dataset.prop = prop;
      button.addEventListener("mousedown", function (event) { event.preventDefault(); });
      button.addEventListener("click", function () { step(item, prop, spec, input, part[1]); });
      spin.appendChild(button);
    });
    return spin;
  }

  function step(item, prop, spec, input, delta) {
    var text = input.value.trim();
    var base = /^-?\d+$/.test(text) ? Number(text) : Number(input.placeholder) || 0;
    var next = base + delta;
    if (typeof spec.minimum === "number" && next < spec.minimum) next = spec.minimum;
    // Уперлось в границу: не писать в модель границу вместо пустого
    if (next === base) return;
    focusProp = prop;
    apply(item, prop, next, String(next));
  }

  // Поле с кнопками внутри своей рамки, как у поля 1С: «+/-» у целого числа, «по умолчанию» у заданного. У булева
  // кнопки нет: флажок, возвращенный к умолчанию, сам убирает свойство из модели, у списка «Да / Нет» это пустое
  function boxed(item, kind, prop, spec) {
    var field = control(item, kind, prop, spec);
    if (item.multi && !multiEditable(prop, spec)) return field;
    var input = field.classList.contains("fe-input") ? field : field.querySelector(".fe-input");
    var locked = GROUPS.locked.indexOf(prop) >= 0;
    var diff = has(shownDiffs, prop) ? shownDiffs[prop] : null;
    if (locked || spec.input === "boolean" || input.classList.contains("fe-font")) {
      if (!diff || locked) return field;
      // Флажок и шрифт - без рамки поля: «вернуть как было» рядом
      var plain = h("span", "fe-box-plain");
      plain.appendChild(field);
      plain.appendChild(revertButton(item, prop, diff));
      return plain;
    }
    var buttons = [];
    if (diff) buttons.push(revertButton(item, prop, diff));
    if (chooserOf(prop, spec)) buttons.push(chooseButton(item, prop, spec));
    if (isSet(item, prop) && prop !== "name" && prop !== "type") buttons.push(resetButton(item, prop));
    if (spec.input === "integer") buttons.push(spinButtons(item, prop, spec, input));
    if (!buttons.length) return field;
    var box = h("span", "fe-box" + (input.tagName === "TEXTAREA" ? " fe-box-top" : ""));
    if (input.parentNode) input.parentNode.replaceChild(box, input);
    box.appendChild(input);
    buttons.forEach(function (button) { box.appendChild(button); });
    if (spec.input === "integer") {
      input.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        step(item, prop, spec, input, event.key === "ArrowUp" ? 1 : -1);
      });
    }
    return field === input ? box : field;
  }

  function propRow(item, kind, prop, spec) {
    var row = h("div", "fe-prop");
    row.dataset.prop = prop;
    if (isSet(item, prop)) row.classList.add("fe-set");
    row.appendChild(diffLabel(propLabel(prop), prop, row));
    var cell = h("div", "fe-value");
    cell.appendChild(boxed(item, kind, prop, spec));
    if (prop === "autoFill" && fillable(item)) {
      var fill = button("Заполнить стандартными", function () { fillStandard(item); }, "fe-dialog-button fe-fill-standard");
      fill.title = "Заполнить стандартными командами: кнопки команд, которые показывает автозаполнение";
      fill.disabled = !standardFill(item).length;
      cell.appendChild(fill);
    }
    row.appendChild(cell);
    if (invalid[prop]) {
      row.classList.add("fe-invalid");
      row.appendChild(h("div", "fe-reason", invalid[prop]));
    }
    return row;
  }

  function sizeRow(item, kind, specs) {
    var row = h("div", "fe-prop fe-size");
    ["width", "height"].forEach(function (prop) {
      var part = h("span", "fe-size-part");
      if (isSet(item, prop)) part.classList.add("fe-set");
      part.appendChild(diffLabel(propLabel(prop), prop, part));
      part.appendChild(boxed(item, kind, prop, specs[prop]));
      row.appendChild(part);
      if (invalid[prop]) {
        row.classList.add("fe-invalid");
        row.appendChild(h("div", "fe-reason", invalid[prop]));
      }
    });
    return row;
  }

  function focusField(prop) {
    var field = ui.propsBody.querySelector('.fe-input[data-prop="' + prop + '"]');
    if (!field) return;
    var group = field.closest(".fe-group");
    if (group && group.classList.contains("fe-folded")) {
      group.classList.remove("fe-folded");
      delete foldedGroups[group.firstChild.dataset.group];
    }
    field.focus();
    field.scrollIntoView({ block: "nearest" });
  }

  // Поле ввода значения - по типу в схеме

  function control(item, kind, prop, spec) {
    if (item.multi && !multiEditable(prop, spec)) return mark(h("span", "fe-locked fe-unavailable", "недоступно"), prop);
    if (item.multi && item.mixed[prop]) {
      var field = control(Object.assign({}, item, { multi: item.multi, mixed: {} }), kind, prop, spec);
      markMixed(field);
      return field;
    }
    var node = item.node;
    var set = isSet(item, prop);
    var value = set ? node[prop] : undefined;
    var fallback = defaultOf(kind, prop);
    var locked = GROUPS.locked.indexOf(prop) >= 0;
    if (prop === "currentPage") {
      spec = { input: "enum", values: (node.items || []).filter(function (page) { return page && page.type === "Page"; })
        .map(function (page) { return page.name; }) };
    }
    if (prop === "commandSource") spec = { input: "enum", values: commandSources(node) };
    if (prop === "type") {
      spec = { input: "enum", values: fieldKinds(item) };
      fallback = node.type;
    }
    var field;
    if (locked) field = mark(h("span", "fe-locked", set ? String(value) : ""), prop);
    else switch (spec.input) {
      case "enum": field = enumField(item, prop, spec, value, set, fallback); break;
      case "boolean": field = fallback === undefined ? triField(item, prop, value, set) : checkField(item, prop, value, set, fallback); break;
      case "integer": field = numberField(item, prop, spec, value, fallback); break;
      case "list": case "rows": field = linesField(item, prop, spec, value); break;
      case "choices": field = choicesField(item, prop, value); break;
      case "font": field = fontField(item, prop, spec, value); break;
      case "color": field = colorField(item, prop, spec, value); break;
      case "type": field = typeField(item, prop, spec, value); break;
      default: field = textField(item, prop, spec, value);
    }
    // Незаданное - серым значением по умолчанию; отметка - у самого поля (у цвета поле внутри обертки)
    var input = field.classList.contains("fe-input") ? field : field.querySelector(".fe-input");
    if (!set) input.classList.add("fe-default");
    if (has(invalidText, prop) && "value" in input && input.type !== "checkbox") input.value = invalidText[prop];
    return field;
  }

  // «Вид» поля (ВидПоляФормы): список - по типу реквизита по пути к данным, как в палитре конфигуратора. Строка,
  // число, дата, ссылка, булево - по снимкам владельца 04.11.2026; форматированная строка, форматированный документ,
  // документ PDF, таблица и список значений - по его словам; прочие - гипотеза (план). Объект, набор записей и т.п. -
  // вида поля нет. В колонке таблицы - без видов с оговоркой справочника «недоступен для полей, расположенных в
  // таблице». Текущий вид в списке всегда
  var FIELD_KIND_ORDER = ["InputField", "LabelField", "CheckBoxField", "RadioButtonField", "PictureField",
    "HTMLDocumentField", "TextDocumentField", "ProgressBarField", "TrackBarField", "CalendarField", "PeriodField"];
  var FIELD_KINDS_BY_TYPE = {
    Boolean: ["InputField", "LabelField", "CheckBoxField", "PictureField"],
    String: ["InputField", "LabelField", "RadioButtonField", "PictureField", "HTMLDocumentField", "TextDocumentField"],
    Number: ["InputField", "LabelField", "CheckBoxField", "RadioButtonField", "PictureField", "ProgressBarField",
      "TrackBarField"],
    Date: ["InputField", "LabelField", "CalendarField"],
    FormattedString: ["LabelField"],
    FormattedDocument: ["FormattedDocumentField"], PDFDocument: ["PDFDocumentField"],
    ValueTable: ["InputField", "LabelField"], ValueList: ["InputField", "LabelField"],
    StandardPeriod: ["InputField", "LabelField", "PeriodField"],
    SpreadsheetDocument: ["SpreadsheetDocumentField"], TextDocument: ["TextDocumentField"], Picture: ["PictureField"],
    Planner: ["PlannerField"], Chart: ["ChartField"], GanttChart: ["GanttChartField"], Dendrogram: ["DendrogramField"],
    GraphicalSchema: ["GraphicalSchemaField"], GeographicalSchema: ["GeographicalSchemaField"]
  };
  // Ссылка, УИД, системное перечисление, цвет, шрифт и прочие значения - ввод и надпись (снимок ссылки)
  var FIELD_KINDS_VALUE = ["InputField", "LabelField"];
  var FIELD_KINDS_ANY = ["InputField", "LabelField", "CheckBoxField", "RadioButtonField", "PictureField",
    "HTMLDocumentField", "TextDocumentField"];
  var SIMPLE_TYPE_NAMES = { string: "String", number: "Number", date: "Date", boolean: "Boolean" };
  var NOT_IN_TABLE = { RadioButtonField: true, HTMLDocumentField: true, TextDocumentField: true, CalendarField: true,
    ChartField: true, GanttChartField: true, DendrogramField: true, FormattedDocumentField: true, PeriodField: true,
    GeographicalSchemaField: true, GraphicalSchemaField: true, ProgressBarField: true, SpreadsheetDocumentField: true,
    TrackBarField: true };

  // Тип, у которого вида поля нет: объект, набор записей, менеджер записи, набор констант, компоновщик, дерево и
  // динамический список (только таблица)
  function noFieldType(name) {
    return /^[A-Za-z]+(Object|RecordSet|RecordManager)(\.|$)/.test(name) || name === "ConstantsSet" ||
      name === "DataCompositionSettingsComposer" || name === "ValueTree" || name === "DynamicList";
  }

  function kindsOfType(name) {
    if (FIELD_KINDS_BY_TYPE[name]) return FIELD_KINDS_BY_TYPE[name];
    return noFieldType(name) ? [] : FIELD_KINDS_VALUE;
  }

  function fieldKinds(item) {
    var list = allowedKinds(item.node, placeOf(item) === "column");
    if (list.indexOf(item.node.type) < 0) list.push(item.node.type);
    return sortKinds(list);
  }

  // Виды поля по типу реквизита по пути и месту - без текущего вида
  function allowedKinds(node, inColumn) {
    var names = fieldTypeNames(node);
    var list = null;
    names.forEach(function (name) {
      var own = kindsOfType(name);
      // Составной тип - виды, общие для всех его типов
      list = list ? list.filter(function (kind) { return own.indexOf(kind) >= 0; }) : own.slice();
    });
    if (!list) list = FIELD_KINDS_ANY.slice();
    if (inColumn) list = list.filter(function (kind) { return !NOT_IN_TABLE[kind]; });
    return sortKinds(list);
  }

  function fieldTypeNames(node) {
    var entry = typeof node.dataPath === "string" && node.dataPath ? findEntry(attributeRoots(), node.dataPath) : null;
    var names = entry ? typeNames(entry.node) : [];
    if (!names.length && typeof node.dataType === "string") names = [SIMPLE_TYPE_NAMES[node.dataType] || "AnyRef"];
    return names;
  }

  function sortKinds(list) {
    var rank = function (kind) { var at = FIELD_KIND_ORDER.indexOf(kind); return at < 0 ? FIELD_KIND_ORDER.length : at; };
    return list.sort(function (a, b) { return rank(a) - rank(b); });
  }

  // Путь к данным или тип реквизита сменились (владелец 04.11.2026): вид, которого у нового типа нет, сбрасывается
  // на вид по умолчанию - флажок у булева, иначе первый в списке (поле ввода, у особых типов - свое поле)
  function resetKind(node, inColumn) {
    if (!(KINDS[node.type] || {}).type) return;
    var list = allowedKinds(node, inColumn);
    if (!list.length || list.indexOf(node.type) >= 0) return;
    var names = fieldTypeNames(node);
    var flag = names.length && names.every(function (name) { return name === "Boolean"; }) && list.indexOf("CheckBoxField") >= 0;
    changeKind(node, flag ? "CheckBoxField" : list[0]);
  }

  // Смена вида поля, как в конфигураторе (владелец 04.11.2026): остаются свойства самого элемента (`element`
  // property-groups.json - в EDT вне extInfo), если они есть у нового вида; свойства вида (ширина, высота, растягивание,
  // максимумы, рамка, кнопки...) сбрасываются; пример у флажка другого смысла (булево) - уходит при переходе через
  // флажок; поле ввода берет тип и квалификаторы из реквизита
  var ELEMENT_PROPS = GROUPS.element || [];

  function changeKind(node, kind) {
    var keep = KINDS[kind] || KINDS.Unknown;
    var acrossCheckBox = (node.type === "CheckBoxField") !== (kind === "CheckBoxField");
    Object.keys(node).forEach(function (prop) {
      if (prop === "type" || prop === "name") return;
      var derived = DERIVED.indexOf(prop) >= 0;
      var stays = has(keep, prop) && ELEMENT_PROPS.indexOf(prop) >= 0 && !(acrossCheckBox && prop === "sample");
      if (derived ? kind !== "InputField" : !stays) delete node[prop];
    });
    node.type = kind;
    if (kind === "InputField") mirrorField(node);
  }

  // Источник команд группы кнопок, подменю, командной панели: форма, глобальные команды панели формы, таблицы
  function commandSources(node) {
    var list = ["Form", "FormCommandPanelGlobalCommands"].concat(tablesOf(formOf(model), []).map(function (table) {
      return "Item." + table.name;
    }));
    if (typeof node.commandSource === "string" && list.indexOf(node.commandSource) < 0) list.push(node.commandSource);
    return list;
  }

  function sourceTitle(value) {
    if (value === "Form") return "Форма";
    if (value === "FormCommandPanelGlobalCommands") return "Глобальные команды командной панели формы";
    return /^Item\./.test(value) ? "Таблица " + value.slice(5) : value;
  }

  function mark(field, prop) {
    field.classList.add("fe-input");
    field.dataset.prop = prop;
    return field;
  }

  function enumField(item, prop, spec, value, set, fallback) {
    var select = mark(h("select"), prop);
    if (fallback === undefined) select.appendChild(option("", ""));
    spec.values.forEach(function (one) {
      var text = prop === "currentPage" ? one : prop === "commandSource" ? sourceTitle(one)
        : prop === "type" ? kindTitle(one) : valueTitle(prop, one);
      select.appendChild(option(one, text));
    });
    select.value = set ? value : (fallback === undefined ? "" : fallback);
    select.addEventListener("change", function () { apply(item, prop, select.value === "" ? undefined : select.value); });
    return select;
  }

  function option(value, text) {
    var item = h("option", "", text);
    item.value = value;
    return item;
  }

  function checkField(item, prop, value, set, fallback) {
    var input = mark(h("input"), prop);
    input.type = "checkbox";
    input.checked = set ? value === true : fallback === true;
    input.addEventListener("change", function () { apply(item, prop, input.checked); });
    return input;
  }

  // Булево без известного умолчания («Авто» платформы): пусто, «Да», «Нет»
  function triField(item, prop, value, set) {
    var select = mark(h("select"), prop);
    select.appendChild(option("", ""));
    select.appendChild(option("true", "Да"));
    select.appendChild(option("false", "Нет"));
    select.value = set ? String(value) : "";
    select.addEventListener("change", function () {
      apply(item, prop, select.value === "" ? undefined : select.value === "true");
    });
    return select;
  }

  // Строковое поле: применение по Enter (в многострочном - Shift+Enter перенос) и по уходу из поля, Esc - отмена
  function editable(field, item, prop, read, multiline) {
    var initial = field.value;
    field.addEventListener("change", function () { apply(item, prop, read(field.value), field.value); });
    field.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        field.value = initial;
        field.blur();
      } else if (event.key === "Enter" && (!multiline || multiline === "enter" && !event.shiftKey || event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        focusProp = prop;
        apply(item, prop, read(field.value), field.value);
      }
    });
    return field;
  }

  function parseError(message) { return { error: message }; }

  function textField(item, prop, spec, value) {
    var field = mark(h(MULTILINE[prop] ? "textarea" : "input"), prop);
    if (MULTILINE[prop]) field.rows = String(value || "").split("\n").length > 1 ? 3 : 2;
    field.value = value === undefined ? "" : String(value);
    // Серый очищенный заголовок - как на макете: у кнопки от команды, от реквизита по пути к данным, иначе имя по словам
    if (prop === "title" && item.kind !== "Form" && !item.multi) field.placeholder = R.titleOf(Object.assign({}, item.node, { title: undefined }), model);
    // Картинка кнопки без своей - от команды формы или стандартной команды таблицы
    if (prop === "picture" && item.kind === "Button" && !item.multi) field.placeholder = R.inheritedPicture(item.node, model) || "";
    return editable(field, item, prop, function (text) {
      if (text === "" && !KEEP_EMPTY[prop]) return undefined;
      // Пример значения поля: число - числом, как пишет агент
      if (spec.input === "simple" && NUMBER.test(text)) return Number(text);
      return text;
    }, MULTILINE[prop] ? "enter" : false);
  }

  function numberField(item, prop, spec, value, fallback) {
    var field = mark(h("input"), prop);
    field.inputMode = "numeric";
    field.value = value === undefined ? "" : String(value);
    if (fallback !== undefined) field.placeholder = String(fallback);
    return editable(field, item, prop, function (text) {
      text = text.trim();
      if (text === "") return undefined;
      if (!/^-?\d+$/.test(text)) return parseError("ожидается целое число");
      return Number(text);
    });
  }

  function colorField(item, prop, spec, value) {
    var wrap = h("span", "fe-color");
    var swatch = h("span", "fe-swatch");
    var shown = cssColor(value);
    if (shown) swatch.style.background = shown;
    else if (value) swatch.classList.add("fe-swatch-none");
    var field = mark(h("input"), prop);
    field.value = value || "";
    field.placeholder = "#RRGGBB, web-цвет или style:Имя";
    editable(field, item, prop, function (text) {
      text = text.trim();
      if (text === "") return undefined;
      if (/^style:/i.test(text)) return "style:" + text.slice(6).trim();
      return /^#[0-9a-f]{6}$/i.test(text) ? text.toUpperCase() : text.toLowerCase();
    });
    wrap.appendChild(swatch);
    wrap.appendChild(field);
    return wrap;
  }

  // Список строк (список выбора, значения перечисления, исключенные команды) - строка на значение; строки
  // примера таблицы - строка на строку, значения колонок через « | »
  function linesField(item, prop, spec, value) {
    var field = mark(h("textarea"), prop);
    var rows = spec.input === "rows";
    var lines = Array.isArray(value) ? value.map(function (line) {
      return rows && Array.isArray(line) ? line.join(" | ") : String(line);
    }) : [];
    field.rows = Math.min(Math.max(lines.length, 2), 8);
    field.value = lines.join("\n");
    return editable(field, item, prop, function (text) {
      var list = text.split("\n").map(function (line) { return line.trim(); }).filter(Boolean);
      if (!list.length) return undefined;
      if (!rows) return list;
      return list.map(function (line) {
        return line.split("|").map(function (cell) {
          cell = cell.trim();
          if (cell === "true" || cell === "false") return cell === "true";
          return NUMBER.test(cell) ? Number(cell) : cell;
        });
      });
    }, "lines");
  }

  // Список выбора в панели: строка - пункт, «значение | представление» - пункт с представлением (окно «...» -
  // те же две колонки)
  function choiceItem(value, presentation) {
    value = String(value || "").trim();
    presentation = String(presentation || "").trim();
    return presentation && presentation !== value ? { value: value, presentation: presentation } : value;
  }

  function choicesField(item, prop, value) {
    var field = mark(h("textarea"), prop);
    var lines = Array.isArray(value) ? value.map(function (entry) {
      return entry && typeof entry === "object" ? entry.value + (entry.presentation ? " | " + entry.presentation : "")
        : String(entry);
    }) : [];
    field.rows = Math.min(Math.max(lines.length, 2), 8);
    field.value = lines.join("\n");
    return editable(field, item, prop, function (text) {
      var list = text.split("\n").filter(function (line) { return line.trim(); }).map(function (line) {
        var at = line.indexOf("|");
        return at < 0 ? choiceItem(line) : choiceItem(line.slice(0, at), line.slice(at + 1));
      });
      return list.length ? list : undefined;
    }, "lines");
  }

  // Шрифт: начертание - кнопками «Ж К Ч» в строке, имя, размер и зачеркивание - окном «Шрифт»
  function fontField(item, prop, spec, value) {
    var wrap = mark(h("span", "fe-font"), prop);
    var titles = { bold: ["Ж", "Жирный"], italic: ["К", "Наклонный"], underline: ["Ч", "Подчеркнутый"] };
    var current = value && typeof value === "object" ? value : {};
    ["bold", "italic", "underline"].forEach(function (key) {
      var label = h("label", "fe-font-" + key);
      label.title = titles[key][1];
      var input = h("input");
      input.type = "checkbox";
      input.dataset.key = key;
      input.checked = !!current[key];
      input.addEventListener("change", function () {
        var font = Object.assign({}, current);
        if (input.checked) font[key] = true;
        else delete font[key];
        apply(item, prop, fontValue(font));
      });
      label.appendChild(input);
      label.appendChild(document.createTextNode(titles[key][0]));
      wrap.appendChild(label);
    });
    var summary = h("span", "fe-font-summary", fontSummary(current));
    wrap.appendChild(summary);
    var choose = h("button", "fe-in fe-choose", "…");
    choose.type = "button";
    choose.title = "Выбрать шрифт";
    choose.dataset.prop = prop;
    choose.addEventListener("click", function () { openFontChooser(item, prop); });
    wrap.appendChild(choose);
    if (isSet(item, prop)) wrap.appendChild(resetButton(item, prop));
    return wrap;
  }

  function fontSummary(font) {
    var parts = [];
    if (font.faceName) parts.push(font.faceName);
    if (font.height) parts.push(String(font.height));
    if (font.strikeout) parts.push("зачеркнутый");
    return parts.join(", ");
  }

  // Пустые поля шрифта не пишутся; шрифт без единого поля - свойство убирается
  function fontValue(font) {
    var result = {};
    ["faceName", "height", "bold", "italic", "underline", "strikeout"].forEach(function (key) {
      if (font[key] !== undefined && font[key] !== "" && font[key] !== false && font[key] !== null) result[key] = font[key];
    });
    return Object.keys(result).length ? result : undefined;
  }

  var FONT_FACES = ["Arial", "Calibri", "Courier New", "Georgia", "Microsoft Sans Serif", "Segoe UI", "Tahoma",
    "Times New Roman", "Trebuchet MS", "Verdana"];

  function openFontChooser(item, prop) {
    var value = isSet(item, prop) && item.node[prop] && typeof item.node[prop] === "object" ? item.node[prop] : {};
    dialog = { kind: "font", item: item, prop: prop, font: Object.assign({}, value) };
    renderDialog();
  }

  function renderFont(body) {
    var font = dialog.font;
    var grid = h("div", "fe-font-grid");
    grid.appendChild(h("span", "fe-font-label", "Шрифт"));
    var face = h("select", "fe-font-face");
    face.appendChild(option("", "Шрифт формы (по умолчанию)"));
    var faces = FONT_FACES.slice();
    if (font.faceName && faces.indexOf(font.faceName) < 0) faces.unshift(font.faceName);
    faces.forEach(function (name) { face.appendChild(option(name, name)); });
    face.value = font.faceName || "";
    face.addEventListener("change", function () {
      font.faceName = face.value || undefined;
      renderDialog();
    });
    grid.appendChild(face);
    grid.appendChild(h("span", "fe-font-label", "Размер"));
    // Размер: набором, кнопками «+/-» и стрелками вверх-вниз - шаг 1 пт от заданного или 10 пт шрифта формы
    var sizeBox = h("span", "fe-box fe-font-size");
    var size = h("input", "fe-input fe-font-height");
    size.inputMode = "decimal";
    size.placeholder = "10";
    size.value = font.height ? String(font.height) : "";
    function setHeight(number) {
      font.height = number >= 1 ? number : undefined;
      renderDialog();
      ui.dialogBox.querySelector(".fe-font-height").focus();
    }
    function stepHeight(delta) {
      var number = Number(size.value.replace(",", ".")) || font.height || 10;
      setHeight(Math.max(1, Math.round(number) + delta));
    }
    size.addEventListener("change", function () {
      var number = Number(size.value.replace(",", "."));
      setHeight(size.value.trim() ? number : 0);
    });
    size.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      stepHeight(event.key === "ArrowUp" ? 1 : -1);
    });
    sizeBox.appendChild(size);
    var spin = h("span", "fe-spin");
    [["fe-up", 1, "Увеличить"], ["fe-down", -1, "Уменьшить"]].forEach(function (part) {
      var step = h("button", "fe-in " + part[0]);
      step.type = "button";
      step.tabIndex = -1;
      step.title = part[2];
      step.addEventListener("mousedown", function (event) { event.preventDefault(); });
      step.addEventListener("click", function () { stepHeight(part[1]); });
      spin.appendChild(step);
    });
    sizeBox.appendChild(spin);
    grid.appendChild(sizeBox);
    grid.appendChild(h("span", "fe-font-label", "Начертание"));
    var styles = h("span", "fe-font-styles");
    [["bold", "Жирный"], ["italic", "Наклонный"], ["underline", "Подчеркнутый"], ["strikeout", "Зачеркнутый"]].forEach(function (pair) {
      var label = h("label", "fe-font-style");
      var box = h("input");
      box.type = "checkbox";
      box.dataset.key = pair[0];
      box.checked = !!font[pair[0]];
      box.addEventListener("change", function () {
        font[pair[0]] = box.checked || undefined;
        renderDialog();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(pair[1]));
      styles.appendChild(label);
    });
    grid.appendChild(styles);
    body.appendChild(grid);
    var sample = h("div", "fe-font-sample", "Пример текста: Заказ покупателя № 125 от 04.11.2026");
    if (font.faceName) sample.style.fontFamily = '"' + font.faceName + '"';
    sample.style.fontSize = (font.height || 10) * 1.2 + "px";
    if (font.bold) sample.style.fontWeight = "bold";
    if (font.italic) sample.style.fontStyle = "italic";
    sample.style.textDecoration = [font.underline ? "underline" : "", font.strikeout ? "line-through" : ""].join(" ").trim() || "none";
    body.appendChild(sample);
  }

  // Окна выбора: кнопка «...» в поле свойства. Путь к данным - дерево реквизитов формы (`attributes`) и
  // состава типов (`types`) по месту элемента; исключенные команды - флажки стандартных команд таблицы

  var CHOOSERS = {
    dataPath: { open: openPathChooser, title: "Выбрать путь к данным" },
    rowPictureDataPath: { open: openPathChooser, title: "Выбрать колонку картинки строки" },
    excludedCommands: { open: openCommandsChooser, title: "Выбрать команды" },
    format: { open: openFormatChooser, title: "Конструктор форматной строки" },
    choiceList: { open: openListChooser, title: "Изменить список выбора" },
    picture: { open: openPictureChooser, title: "Выбрать картинку" },
    headerPicture: { open: openPictureChooser, title: "Выбрать картинку" },
    choiceButtonPicture: { open: openPictureChooser, title: "Выбрать картинку" },
    rowsPicture: { open: openPictureChooser, title: "Выбрать картинку" },
    valuesPicture: { open: openPictureChooser, title: "Выбрать картинку" },
    footerPicture: { open: openPictureChooser, title: "Выбрать картинку" },
    commandName: { open: openCommandChooser, title: "Выбрать команду" },
    valueType: { open: openTypeChooser, title: "Выбрать тип" }
  };
  var PRIMITIVES = { String: true, Number: true, Date: true, Boolean: true };
  // Стандартные реквизиты: в пути - английское имя (как пишет EDT), в дереве - русское, как в конфигураторе
  var STANDARD_NAMES = R.STANDARD_NAMES;
  var dialog = null;           // открытое окно выбора: { kind, item, prop, ... }

  function chooseButton(item, prop, spec) {
    var chooser = chooserOf(prop, spec);
    var button = h("button", "fe-in fe-choose", "…");
    button.type = "button";
    button.tabIndex = -1;
    button.title = chooser.title;
    button.dataset.prop = prop;
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () { chooser.open(item, prop); });
    return button;
  }

  // Окно выбора свойства: по имени свойства, цвет - по виду поля схемы
  function chooserOf(prop, spec) {
    if (spec && spec.input === "color") return { open: openColorChooser, title: "Выбрать цвет" };
    return CHOOSERS[prop] || null;
  }

  // Имя типа платформы по-русски, как в конфигураторе: String → Строка, CatalogRef.Банки → СправочникСсылка.Банки
  var TYPE_TITLES = {
    String: "Строка", Number: "Число", Date: "Дата", Boolean: "Булево", ValueTable: "ТаблицаЗначений",
    ValueTree: "ДеревоЗначений", ValueList: "СписокЗначений", DynamicList: "ДинамическийСписок",
    UUID: "УникальныйИдентификатор", ValueStorage: "ХранилищеЗначения", Type: "Тип", AnyRef: "ЛюбаяСсылка",
    FormattedString: "ФорматированнаяСтрока", SpreadsheetDocument: "ТабличныйДокумент", Picture: "Картинка",
    TypeDescription: "ОписаниеТипов", StandardPeriod: "СтандартныйПериод", FormattedDocument: "ФорматированныйДокумент",
    TextDocument: "ТекстовыйДокумент", PDFDocument: "ДокументPDF", Null: "Null", ConstantsSet: "КонстантыНабор",
    DataCompositionSettingsComposer: "КомпоновщикНастроекКомпоновкиДанных", GraphicalSchema: "ГрафическаяСхема",
    GeographicalSchema: "ГеографическаяСхема", Chart: "Диаграмма", GanttChart: "ДиаграммаГанта", Dendrogram: "Дендрограмма",
    Planner: "Планировщик", Color: "Цвет", Font: "Шрифт", StandardBeginningDate: "СтандартнаяДатаНачала",
    AccumulationRecordType: "ВидДвиженияНакопления", AccountType: "ВидСчета", AccountingRecordType: "ВидДвиженияБухгалтерии",
    HorizontalAlign: "ГоризонтальноеПоложение", VerticalAlign: "ВертикальноеПоложение", SizeChangeMode: "РежимИзмененияРазмера",
    AnalysisDataType: "ВидДанныхАнализа", ClusterizationMethod: "МетодКластеризации",
    DataAnalysisTimeIntervalUnitType: "ТипЕдиницыИнтервалаВремениАнализаДанных",
    DataAnalysisResultTableFillType: "ТипЗаполненияТаблицыРезультатаАнализаДанных",
    DataAnalysisNumericValueUseType: "ТипИспользованияЧисловыхЗначенийАнализаДанных",
    AssociationRulesDataSourceType: "ТипИсточникаДанныхПоискаАссоциаций",
    DataAnalysisColumnTypeDecisionTree: "ТипКолонкиАнализаДанныхДеревоРешений",
    DataAnalysisColumnTypeClusterization: "ТипКолонкиАнализаДанныхКластеризация",
    DataAnalysisColumnTypeSummaryStatistics: "ТипКолонкиАнализаДанныхОбщаяСтатистика",
    DataAnalysisColumnTypeAssociationRules: "ТипКолонкиАнализаДанныхПоискАссоциаций",
    DataAnalysisColumnTypeSequentialPatterns: "ТипКолонкиАнализаДанныхПоискПоследовательностей",
    PredictionModelColumnType: "ТипКолонкиМоделиПрогноза", DataAnalysisDistanceMetricType: "ТипМерыРасстоянияАнализаДанных",
    AssociationRulesPruneType: "ТипОтсеченияПравилАссоциации", DataAnalysisStandardizationType: "ТипСтандартизацииАнализаДанных",
    DecisionTreeSimplificationType: "ТипУпрощенияДереваРешений",
    DataAnalysisAssociationRulesOrderType: "ТипУпорядочиванияПравилАссоциацииАнализаДанных",
    DataAnalysisSequentialPatternsOrderType: "ТипУпорядочиванияШаблоновПоследовательностейАнализаДанных"
  };
  var KIND_TITLES = {
    Catalog: "Справочник", Document: "Документ", Enum: "Перечисление", ChartOfCharacteristicTypes: "ПланВидовХарактеристик",
    ChartOfAccounts: "ПланСчетов", ChartOfCalculationTypes: "ПланВидовРасчета", ExchangePlan: "ПланОбмена",
    BusinessProcess: "БизнесПроцесс", Task: "Задача", DataProcessor: "Обработка", Report: "Отчет",
    InformationRegister: "РегистрСведений", AccumulationRegister: "РегистрНакопления",
    AccountingRegister: "РегистрБухгалтерии", CalculationRegister: "РегистрРасчета", DocumentJournal: "ЖурналДокументов",
    Constants: "Константы", BusinessProcessRoutePoint: "ТочкаМаршрутаБизнесПроцесса", Characteristic: "Характеристика",
    DefinedType: "ОпределяемыйТип"
  };
  var ROLE_TITLES = { Ref: "Ссылка", Object: "Объект", RecordSet: "НаборЗаписей", RecordManager: "МенеджерЗаписи",
    List: "Список", Manager: "Менеджер", Selection: "Выборка" };

  function typeTitle(name) {
    if (TYPE_TITLES[name]) return TYPE_TITLES[name];
    var generic = /^([A-Za-z]+?)(Ref|Object|RecordSet|RecordManager)$/.exec(name);
    if (generic && KIND_TITLES[generic[1]]) return KIND_TITLES[generic[1]] + ROLE_TITLES[generic[2]];
    var own = /^(Characteristic|DefinedType)\.(.+)$/.exec(name);
    if (own) return KIND_TITLES[own[1]] + "." + own[2];
    var found = /^([A-Za-z]+?)(Ref|Object|RecordSet|RecordManager|List|Manager|Selection)\.(.+)$/.exec(name);
    if (found && KIND_TITLES[found[1]]) return KIND_TITLES[found[1]] + ROLE_TITLES[found[2]] + "." + found[3];
    return name;
  }

  function invert(map) {
    var result = {};
    Object.keys(map).forEach(function (key) { result[map[key]] = key; });
    return result;
  }
  var TYPE_NAMES = invert(TYPE_TITLES);
  var KIND_NAMES = invert(KIND_TITLES);
  var ROLE_NAMES = invert(ROLE_TITLES);

  // Обратно: «СправочникСсылка.Банки» → CatalogRef.Банки, «Строка» → String; английское имя - как есть
  function typeName(title) {
    if (TYPE_NAMES[title]) return TYPE_NAMES[title];
    var dot = title.indexOf(".");
    var head = dot < 0 ? title : title.slice(0, dot);
    for (var kind in KIND_NAMES) {
      if (head.indexOf(kind) !== 0) continue;
      // «Характеристика.Х», «ОпределяемыйТип.Х» - без роли
      if (head === kind && dot > 0 && /^(Characteristic|DefinedType)$/.test(KIND_NAMES[kind])) return KIND_NAMES[kind] + title.slice(dot);
      var role = ROLE_NAMES[head.slice(kind.length)];
      // Без точки - общий тип вида: «СправочникСсылка» - любая ссылка справочника (CatalogRef)
      if (role) return KIND_NAMES[kind] + role + (dot > 0 ? title.slice(dot) : "");
    }
    return title;
  }

  // Проход пути к данным по `attributes` и `types` модели - общий с рисунком (`FMRender.pathTools`): модель
  // страницы передается явно, рендерер ее мог еще не получить
  var typeNames = R.typeNames;
  var typeOf = R.typeOf;
  var isCollection = R.isCollection;
  function described(key) { return R.pathTools(model).described(key); }
  function pathMembers(entry) { return R.pathTools(model).members(entry); }
  function attributeRoots() { return R.pathTools(model).roots(); }
  function findEntry(entries, path) { return R.pathTools(model).find(entries, path); }

  function isStructure(node) {
    return typeNames(node).some(function (name) { return /^(Object|RecordManager)$/.test((typeOf(name) || {}).role); });
  }

  // Место элемента для дерева пути: таблица - только коллекции (через ссылку не предлагается), колонка - внутри
  // пути своей таблицы, остальное - все реквизиты; по ссылке - вглубь без предела (опыт в EDT)
  function pathMode(item, prop) {
    // Картинка строки - колонка самой таблицы, путь целиком: `Список.DefaultPicture`, `Объект.Товары.Картинка`
    if (prop === "rowPictureDataPath") {
      var ownPath = typeof item.node.dataPath === "string" ? item.node.dataPath : "";
      return { mode: "column", prefix: ownPath && findEntry(attributeRoots(), ownPath) ? ownPath : "", rowPicture: true };
    }
    if (item.kind === "Table") return { mode: "table" };
    for (var up = item.parent; up; up = up.parent) {
      if (up.kind !== "Table") continue;
      var tablePath = typeof up.node.dataPath === "string" ? up.node.dataPath : "";
      if (tablePath && findEntry(attributeRoots(), tablePath)) return { mode: "column", prefix: tablePath };
      break;
    }
    return { mode: "body" };
  }

  // Дерево сужено местом (владелец): поле вне таблицы - без табличных частей и таблиц, таблица - только
  // коллекции и то, что к ним ведет, колонка - только ветка своей таблицы
  // Таблица и список значений - реквизит формы, который бывает и полем (владелец 04.11.2026): в дереве поля - листом
  function fieldCollection(entry) {
    return entry.node === entry.root && !entry.node.collection && typeNames(entry.node).length > 0 &&
      typeNames(entry.node).every(function (name) { return name === "ValueTable" || name === "ValueList"; });
  }

  function shownEntry(entry) {
    if (dialog.mode === "body") return !isCollection(entry.node) || fieldCollection(entry);
    if (dialog.mode === "table") return isCollection(entry.node) || leadsToCollection(entry);
    var prefix = dialog.prefix;
    return prefix === entry.path || prefix.indexOf(entry.path + ".") === 0 || entry.path.indexOf(prefix + ".") === 0;
  }

  function leadsToCollection(entry) {
    return (entry.node === entry.root || isStructure(entry.node)) &&
      pathMembers(entry).some(function (member) { return isCollection(member.node); });
  }

  function expandable(entry) {
    if (dialog.mode === "table") return !isCollection(entry.node) && leadsToCollection(entry);
    if (dialog.mode === "body" && fieldCollection(entry)) return false;
    return pathMembers(entry).some(shownEntry);
  }

  function selectable(entry) {
    if (dialog.mode === "table") return isCollection(entry.node);
    // Поле: у объекта, набора записей и т.п. вида поля нет (владелец 04.11.2026)
    var names = typeNames(entry.node);
    if (dialog.mode === "body" && names.length && names.every(noFieldType)) return false;
    if (dialog.mode === "column") return entry.path.indexOf(dialog.prefix + ".") === 0;
    return true;
  }

  function openPathChooser(item, prop) {
    var place = pathMode(item, prop);
    var value = isSet(item, prop) ? String(item.node[prop]) : "";
    dialog = { kind: "path", item: item, prop: prop, mode: place.mode, prefix: place.prefix || "", roots: attributeRoots(),
      rowPicture: !!place.rowPicture, open: {}, chosen: null, error: "" };
    openTo(dialog.prefix, true);
    if (value && findEntry(dialog.roots, value)) {
      openTo(value, false);
      dialog.chosen = value;
    }
    renderDialog();
  }

  // Раскрыть родителей пути (и сам путь - у ветки таблицы колонки)
  function openTo(path, self) {
    if (!path) return;
    var parts = path.split(".");
    for (var i = 1; i < parts.length + (self ? 1 : 0); i++) dialog.open[parts.slice(0, i).join(".")] = true;
  }

  function openCommandsChooser(item, prop) {
    var excluded = Array.isArray(item.node.excludedCommands) ? item.node.excludedCommands : [];
    var commands = item.kind === "Form" ? R.formCommands() : R.tableCommands(item.node);
    var known = {};
    commands.forEach(function (command) { known[command.name] = true; });
    // Снятые команды, которых рендерер не знает, - в конце: флажок можно вернуть
    excluded.forEach(function (name) { if (!known[name]) commands.push({ name: name, title: name }); });
    var off = {};
    excluded.forEach(function (name) { off[name] = true; });
    dialog = { kind: "commands", item: item, prop: prop, commands: commands, off: off };
    renderDialog();
  }

  function closeDialog() {
    dialog = null;
    if (ui.dialog) ui.dialog.hidden = true;
  }

  function dialogButton(text, handler, cls) {
    var item = button(text, handler, "fe-dialog-button " + (cls || ""));
    return item;
  }

  var DIALOG_TITLES = { path: "Путь к данным", commands: "Состав команд", command: "Выбор команды", color: "Выбор цвета",
    format: "Конструктор форматной строки", list: "Список выбора", picture: "Выбор картинки", type: "Выбор типа",
    columns: "Колонки таблицы", font: "Шрифт", "delete": "Удаление", autofill: "Стандартные команды" };
  var DIALOG_BODIES = { path: renderPathTree, commands: renderCommands, command: renderCommandList, color: renderColors,
    format: renderFormat, list: renderList, picture: renderPictures, type: renderTypes, columns: renderColumnsOffer,
    font: renderFont, "delete": renderDeleteConfirm, autofill: renderAutofillOffer };
  var DIALOG_WIDE = { color: true, format: true, picture: true, type: true };
  // Кнопки окна, где «Выбрать / Отмена» не подходят
  var DIALOG_ACTIONS = { columns: ["Заполнить колонками", "Оставить пустой"], "delete": ["Удалить", "Отмена"],
    autofill: ["Заполнить", "Не нужно"] };

  function renderDialog() {
    var box = ui.dialogBox;
    box.innerHTML = "";
    box.className = "fe-dialog" + (DIALOG_WIDE[dialog.kind] ? " fe-dialog-wide" : dialog.kind === "delete" ? " fe-dialog-compact" : "");
    ui.dialog.hidden = false;
    var title = DIALOG_TITLES[dialog.kind];
    var head = h("div", "fe-dialog-head");
    head.appendChild(h("span", "fe-dialog-title", title));
    head.appendChild(h("span", "fe-dialog-sub", (dialog.item.node.name || "Форма") +
      (dialog.prop ? " · " + propTitle(dialog.prop) : "")));
    var close = button("×", closeDialog, "fe-dialog-close");
    close.title = "Закрыть (Esc)";
    head.appendChild(close);
    box.appendChild(head);
    var body = h("div", "fe-dialog-body");
    box.appendChild(body);
    DIALOG_BODIES[dialog.kind](body);
    var foot = h("div", "fe-dialog-foot");
    var actions = h("div", "fe-dialog-actions");
    var texts = DIALOG_ACTIONS[dialog.kind] || ["Выбрать", "Отмена"];
    actions.appendChild(dialogButton(texts[0], confirmDialog, "fe-dialog-ok"));
    actions.appendChild(dialogButton(texts[1], closeDialog, "fe-dialog-cancel"));
    foot.appendChild(actions);
    box.appendChild(foot);
    var chosen = body.querySelector(".fe-color-row.fe-pick-chosen, .fe-picture-tile.fe-pick-chosen, .fe-command-list .fe-pick-chosen");
    if (chosen) chosen.scrollIntoView({ block: "nearest" });
    // Клавиши окна (Esc, стрелки дерева пути) - фокус в окне
    if (!box.contains(document.activeElement)) box.focus();
  }

  function renderPathTree(body) {
    var note = dialog.rowPicture ? (dialog.prefix ? "Картинка строки - колонка таблицы " + dialog.prefix
        : "Сначала задайте таблице путь к данным: картинка строки - ее колонка")
      : dialog.mode === "table" ? "Таблица - только коллекции: табличные части, таблицы и деревья значений, списки"
      : dialog.mode === "column" ? "Колонка - реквизиты таблицы " + dialog.prefix
      : "Реквизиты формы без табличных частей; ссылки раскрываются, если их тип описан в модели (types)";
    body.appendChild(h("div", "fe-dialog-note", note));
    var list = h("div", "fe-pick");
    if (dialog.rowPicture && !dialog.prefix) list.appendChild(h("div", "fe-pick-empty", "Колонок нет"));
    else if (!dialog.roots.length) list.appendChild(h("div", "fe-pick-empty", "Реквизитов нет - заведите их в левой колонке, «Реквизиты»"));
    dialog.nodes = {};
    (function visit(entries, depth, rel, parent) {
      entries.filter(shownEntry).forEach(function (entry) {
        var key = rel ? rel + "." + entry.name : entry.name;
        dialog.nodes[key] = { entry: entry, parent: rel || null };
        var row = h("div", "fe-pick-row");
        row.dataset.path = key;
        row.style.paddingLeft = px(4 + depth * 16);
        var open = expandable(entry);
        var twisty = twistyOf(open, !!dialog.open[key]);
        twisty.addEventListener("click", function (event) {
          event.stopPropagation();
          if (!open) return;
          dialog.open[key] = !dialog.open[key];
          renderDialog();
        });
        row.appendChild(twisty);
        var icon = h("span", "fe-icon");
        // Табличная часть и ее колонки - значком таблицы, реквизит - чертой, как в окне выбора конфигуратора
        var tabular = isCollection(entry.node) || !!parent && isCollection(parent.node);
        icon.innerHTML = '<svg viewBox="0 0 16 16">' + (tabular ? ICONS.table : ICONS.attribute) + "</svg>";
        row.appendChild(icon);
        var standard = STANDARD_NAMES[entry.name];
        row.appendChild(h("span", "fe-pick-name", standard || entry.name));
        var info = [standard ? "" : entry.node.title, typeNames(entry.node).map(typeTitle).join(", ")].filter(Boolean).join(" - ");
        if (info) row.appendChild(h("span", "fe-pick-info", info));
        if (!selectable(entry)) row.classList.add("fe-pick-off");
        if (dialog.chosen === key) row.classList.add("fe-pick-chosen");
        if (dialog.cursor === key && dialog.chosen !== key) row.classList.add("fe-pick-cursor");
        row.addEventListener("click", function () {
          dialog.cursor = key;
          if (selectable(entry)) dialog.chosen = key;
          markPath();
        });
        row.addEventListener("dblclick", function () {
          if (!selectable(entry)) return;
          dialog.chosen = key;
          confirmDialog();
        });
        list.appendChild(row);
        if (open && dialog.open[key]) visit(pathMembers(entry), depth + 1, key, entry);
      });
    })(dialog.roots, 0, "", null);
    body.appendChild(list);
  }

  // Отметка и курсор дерева пути - на месте, без перерисовки окна
  function markPath() {
    ui.dialogBox.querySelectorAll(".fe-pick-row[data-path]").forEach(function (row) {
      var key = row.dataset.path;
      row.classList.toggle("fe-pick-chosen", dialog.chosen === key);
      row.classList.toggle("fe-pick-cursor", dialog.cursor === key && dialog.chosen !== key);
    });
  }

  // Дерево пути с клавиатуры: стрелки - как в дереве элементов, Enter - выбрать
  function pathKey(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      confirmDialog();
      return;
    }
    var current = dialog.cursor || dialog.chosen || null;
    var done = treeNavigate(event, {
      keys: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-row[data-path]"), function (row) { return row.dataset.path; }),
      current: dialog.nodes[current] ? current : null,
      children: function (key) {
        var node = dialog.nodes[key];
        return node && expandable(node.entry) ? pathMembers(node.entry).filter(shownEntry).map(function (entry) { return key + "." + entry.name; }) : [];
      },
      open: function (key) { return !!dialog.open[key]; },
      setOpen: function (key, on) {
        dialog.open[key] = on;
        renderDialog();
      },
      parent: function (key) { return dialog.nodes[key] ? dialog.nodes[key].parent : null; },
      select: function (key) {
        dialog.cursor = key;
        if (selectable(dialog.nodes[key].entry)) dialog.chosen = key;
        renderDialog();
        var row = ui.dialogBox.querySelector('.fe-pick-row[data-path="' + key + '"]');
        if (row) row.scrollIntoView({ block: "nearest" });
      }
    });
    if (done) event.preventDefault();
  }

  function renderCommands(body) {
    body.appendChild(h("div", "fe-dialog-note", "Снятый флажок - команды нет на панели и в «Еще»"));
    var list = h("div", "fe-pick");
    dialog.commands.forEach(function (command) {
      var label = h("label", "fe-command");
      var input = h("input");
      input.type = "checkbox";
      input.dataset.command = command.name;
      input.checked = !dialog.off[command.name];
      input.addEventListener("change", function () {
        if (input.checked) delete dialog.off[command.name];
        else dialog.off[command.name] = true;
      });
      label.appendChild(input);
      label.appendChild(h("span", "", command.title));
      label.appendChild(h("span", "fe-pick-info", command.name));
      list.appendChild(label);
    });
    body.appendChild(list);
  }

  // Свойство корня модели - на свое место в порядке импорта: реквизиты, команды, типы, картинки, цвета стиля
  var ROOT_ORDER = ["version", "form", "attributes", "commands", "types", "pictures", "styles"];

  function setRootProp(prop, value) {
    var rank = ROOT_ORDER.indexOf(prop);
    var keys = Object.keys(model);
    var index = keys.findIndex(function (key) { return ROOT_ORDER.indexOf(key) > rank; });
    var tail = {};
    (index < 0 ? [] : keys.slice(index)).forEach(function (key) {
      tail[key] = model[key];
      delete model[key];
    });
    model[prop] = value;
    Object.keys(tail).forEach(function (key) { model[key] = tail[key]; });
  }

  function confirmDialog() {
    var current = dialog;
    if (current.kind === "type") {
      if (!current.chosen.length) {
        current.error = "выберите тип";
        renderDialog();
        return;
      }
      closeDialog();
      // «Произвольный» - тип не задан: свойство уходит из модели
      if (current.chosen[0] === "") {
        apply(current.item, current.prop, undefined);
        return;
      }
      describeTypes(current.chosen).then(function () {
        apply(current.item, current.prop, current.chosen.length === 1 ? current.chosen[0] : current.chosen.slice());
      });
      return;
    }
    if (current.kind === "columns") {
      closeDialog();
      fillColumns(current.item, current.path);
      return;
    }
    if (current.kind === "delete") {
      closeDialog();
      if (current.items) removeItems(current.items);
      else removeItem(current.item);
      return;
    }
    if (current.kind === "autofill") {
      closeDialog();
      if (current.merge) joinLastStep();
      fillStandard(current.item);
      return;
    }
    if (current.kind === "font") {
      closeDialog();
      apply(current.item, current.prop, fontValue(current.font));
      return;
    }
    if (/^(color|format|list|picture|command)$/.test(current.kind)) {
      var value = current.kind === "format" ? formatText() : current.kind === "list" ? listValue() : current.value;
      if (current.kind === "picture" && value) addPicture(value);
      closeDialog();
      apply(current.item, current.prop, value || undefined);
      return;
    }
    if (current.kind === "path") {
      if (!current.chosen) return;
      closeDialog();
      apply(current.item, current.prop, current.chosen);
      return;
    }
    var excluded = current.commands.map(function (command) { return command.name; })
      .filter(function (name) { return current.off[name]; });
    closeDialog();
    apply(current.item, current.prop, excluded.length ? excluded : undefined);
  }

  // Словари корня модели `types`, `styles` и `pictures` (данные для рисования, *нет в 1С*): создаются при первой
  // записи, на своем месте - как пишет импорт
  function rootDict(prop) {
    if (model[prop] && typeof model[prop] === "object" && !Array.isArray(model[prop])) return model[prop];
    setRootProp(prop, {});
    return model[prop];
  }

  // Цвет стиля платформы без значения в `styles` - значение из таблицы «Такси»: как у импорта
  function addStyle(value) {
    if (typeof value !== "string" || value.indexOf("style:") !== 0) return;
    var name = value.slice(6);
    var own = model.styles && typeof model.styles === "object" ? model.styles : {};
    if (has(own, name)) return;
    var row = PLATFORM_STYLES[name] || configStyle(name);
    if (row && row.value) rootDict("styles")[name] = row.value;
  }

  // Элемент стиля конфигурации от сервера (`serve --src`, `GET /config-styles`): { name, value } или null
  function configStyle(name) {
    return (configStyles || []).filter(function (row) { return row.name === name; })[0] || null;
  }

  // Стандартная картинка из библиотеки, которой нет в `pictures`, - туда, как делает импорт
  function addPicture(name) {
    var own = model.pictures && typeof model.pictures === "object" ? model.pictures : {};
    if (has(own, name)) return;
    var found = (stdLibrary || []).concat(configLibrary || []).filter(function (entry) { return entry.name === name; })[0];
    if (found) rootDict("pictures")[name] = found.uri;
  }

  // Цвет модели → цвет CSS для образца: стиль - из `styles` модели или таблицы платформы, web - по таблице 1С
  function cssColor(value) {
    if (typeof value !== "string" || !value) return "";
    if (/^#[0-9A-Fa-f]{6}$/.test(value)) return value;
    if (value.indexOf("style:") === 0) {
      var name = value.slice(6);
      var own = model && model.styles && typeof model.styles === "object" ? model.styles : {};
      return own[name] || (PLATFORM_STYLES[name] || configStyle(name) || {}).value || "";
    }
    return (WEB_COLORS[value.toLowerCase()] || {}).value || "";
  }

  // Цвет: закладки «Из стиля» (стиль платформы и элементы стиля конфигурации из `styles`) и «Web», рядом -
  // конструктор RGB; закладки «Windows» нет (владелец 03.11.2026)

  var COLORS = ED.colors || { platform: [], web: [] };
  // Элементы стиля конфигурации - с сервера при `serve --src` (в `styles` модели - только использованные);
  // загружаются при первом окне цвета
  var configStyles = null;
  var PLATFORM_STYLES = {};
  COLORS.platform.forEach(function (row) { PLATFORM_STYLES[row.name] = row; });
  var WEB_COLORS = {};
  COLORS.web.forEach(function (row) { WEB_COLORS[row.name.toLowerCase()] = row; });

  function openColorChooser(item, prop) {
    var value = isSet(item, prop) ? String(item.node[prop]) : "";
    var web = value && value.indexOf("style:") !== 0 && value.charAt(0) !== "#";
    dialog = { kind: "color", item: item, prop: prop, value: value, tab: web ? "web" : "style", filter: "",
      loading: !!ED.source && configStyles === null };
    renderDialog();
    if (!dialog.loading) return;
    loadLibrary("/config-styles", "styles").then(function (found) {
      configStyles = found;
      if (dialog && dialog.kind === "color") {
        dialog.loading = false;
        renderDialog();
      }
    });
  }

  function dialogTabs(body, tabs) {
    var bar = h("div", "fe-tabs");
    tabs.forEach(function (tab) {
      var button = h("button", "fe-tab" + (dialog.tab === tab[0] ? " fe-tab-on" : ""), tab[1]);
      button.type = "button";
      button.dataset.tab = tab[0];
      button.addEventListener("click", function () {
        dialog.tab = tab[0];
        renderDialog();
      });
      bar.appendChild(button);
    });
    body.appendChild(bar);
  }

  function swatchOf(color) {
    var swatch = h("span", "fe-swatch");
    if (color) swatch.style.background = color;
    else swatch.classList.add("fe-swatch-none");
    return swatch;
  }

  // Строки списка гаснут по поиску без перерисовки окна: фокус остается в поле поиска
  // `refresh` - своя раскладка списка после поиска (группы окна команды); без нее - строки по совпадению
  function filterBox(list, selector, refresh) {
    var input = h("input", "fe-filter");
    input.placeholder = "Поиск";
    input.value = dialog.filter;
    input.addEventListener("input", function () {
      dialog.filter = input.value;
      if (refresh) {
        refresh(list);
        return;
      }
      var text = input.value.trim().toLowerCase();
      list.querySelectorAll(selector).forEach(function (row) {
        row.hidden = !!text && row.dataset.search.indexOf(text) < 0;
      });
    });
    return input;
  }

  function colorRow(value, title, info, color) {
    var row = h("div", "fe-pick-row fe-color-row" + (dialog.value === value ? " fe-pick-chosen" : ""));
    row.dataset.color = value;
    row.dataset.search = (title + " " + info).toLowerCase();
    if (dialog.filter && row.dataset.search.indexOf(dialog.filter.trim().toLowerCase()) < 0) row.hidden = true;
    row.appendChild(swatchOf(color));
    row.appendChild(h("span", "fe-pick-name", title));
    if (info) row.appendChild(h("span", "fe-pick-info", info));
    row.addEventListener("click", function () {
      dialog.value = value;
      markChosen(row);
      var panel = ui.dialogBox.querySelector(".fe-color-make");
      if (panel) panel.parentNode.replaceChild(colorConstructor(), panel);
    });
    row.addEventListener("dblclick", function () {
      dialog.value = value;
      confirmDialog();
    });
    return row;
  }

  // Окна выбора: щелчок только переставляет отметку - строка та же, и второй щелчок дает
  // двойной (перерисовка окна подменяла строку под курсором, и «двойной щелчок - выбрать» не срабатывал)
  function markChosen(row) {
    ui.dialogBox.querySelectorAll(".fe-pick-chosen").forEach(function (other) {
      if (other !== row) other.classList.remove("fe-pick-chosen");
    });
    row.classList.add("fe-pick-chosen");
  }

  function renderColors(body) {
    var columns = h("div", "fe-color-chooser");
    var left = h("div", "fe-color-lists");
    dialogTabs(left, [["style", "Из стиля"], ["web", "Web"]]);
    var list = h("div", "fe-pick fe-color-list");
    left.appendChild(filterBox(list, ".fe-color-row"));
    if (dialog.tab === "web") {
      COLORS.web.forEach(function (row) {
        list.appendChild(colorRow(row.name.toLowerCase(), row.title + " (" + row.name + ")", "", row.value));
      });
    } else {
      list.appendChild(h("div", "fe-pick-section", "Стиль платформы"));
      COLORS.platform.forEach(function (row) {
        list.appendChild(colorRow("style:" + row.name, row.title, row.ru, cssColor("style:" + row.name)));
      });
      // Стиль конфигурации: с исходниками - все элементы от сервера, без них - те, что есть в `styles` модели
      var values = {};
      (configStyles || []).forEach(function (row) { values[row.name] = row.value; });
      var modelStyles = model.styles && typeof model.styles === "object" ? model.styles : {};
      Object.keys(modelStyles).forEach(function (name) { if (!PLATFORM_STYLES[name]) values[name] = modelStyles[name]; });
      var own = Object.keys(values).sort(function (a, b) { return a.localeCompare(b, "ru"); });
      list.appendChild(h("div", "fe-pick-section", "Стиль конфигурации"));
      if (dialog.loading) list.appendChild(h("div", "fe-pick-empty", "Загрузка элементов стиля из исходников..."));
      else if (!own.length) {
        list.appendChild(h("div", "fe-pick-empty", ED.source ? "Нет цветовых элементов стиля в конфигурации"
          : "Только из styles модели: все элементы стиля конфигурации - при запуске serve --src <исходники>"));
      }
      own.forEach(function (name) { list.appendChild(colorRow("style:" + name, name, "", values[name])); });
    }
    left.appendChild(list);
    columns.appendChild(left);
    columns.appendChild(colorConstructor());
    body.appendChild(columns);
  }

  // Конструктор цвета: образец, красный, зеленый, синий, #RRGGBB и палитра браузера; правка дает абсолютный цвет
  function colorConstructor() {
    var panel = h("div", "fe-color-make");
    var current = cssColor(dialog.value);
    var preview = swatchOf(current);
    preview.classList.add("fe-color-preview");
    panel.appendChild(preview);
    panel.appendChild(h("div", "fe-color-value", dialog.value ? colorTitle(dialog.value) : "не задан"));
    var hex = /^#[0-9A-Fa-f]{6}$/.test(current) ? current.toUpperCase() : "#FFFFFF";
    var parts = [1, 3, 5].map(function (at) { return parseInt(hex.slice(at, at + 2), 16); });
    function setHex(text) {
      if (!/^#?[0-9A-Fa-f]{6}$/.test(text)) return;
      dialog.value = "#" + text.replace("#", "").toUpperCase();
      renderDialog();
    }
    ["Красный", "Зеленый", "Синий"].forEach(function (label, index) {
      var row = h("label", "fe-color-part", label);
      var input = h("input");
      input.type = "number";
      input.min = 0;
      input.max = 255;
      input.value = parts[index];
      input.dataset.part = String(index);
      input.addEventListener("change", function () {
        var next = parts.slice();
        next[index] = Math.max(0, Math.min(255, parseInt(input.value, 10) || 0));
        setHex(next.map(function (part) { return (part < 16 ? "0" : "") + part.toString(16); }).join(""));
      });
      row.appendChild(input);
      panel.appendChild(row);
    });
    var hexRow = h("label", "fe-color-part", "#");
    var hexInput = h("input", "fe-color-hex");
    hexInput.value = hex.slice(1);
    hexInput.addEventListener("change", function () { setHex(hexInput.value.trim()); });
    hexRow.appendChild(hexInput);
    panel.appendChild(hexRow);
    var picker = h("input", "fe-color-picker");
    picker.type = "color";
    picker.value = hex.toLowerCase();
    picker.title = "Палитра";
    picker.addEventListener("change", function () { setHex(picker.value); });
    panel.appendChild(picker);
    panel.appendChild(dialogButton("Очистить", function () {
      dialog.value = "";
      renderDialog();
    }, "fe-color-clear"));
    return panel;
  }

  function colorTitle(value) {
    if (value.indexOf("style:") === 0) {
      var row = PLATFORM_STYLES[value.slice(6)];
      return "стиль: " + (row ? row.title + " (" + row.name + ")" : value.slice(6));
    }
    var web = WEB_COLORS[value.toLowerCase()];
    return web ? "web: " + web.title + " (" + web.name + ")" : value;
  }

  // Формат: закладки по типу значения, параметр - флажок и значение (правка значения ставит флажок), пример
  // значения и его представление; строка - как у конструктора форматной строки 1С (format.js)

  var F = window.FMFormat;
  var FORMAT_ROWS = {
    number: [
      ["ЧЦ", "Длина", "integer"], ["ЧДЦ", "Точность", "integer"], ["ЧС", "Сдвиг", "integer"],
      ["ЧРД", "Разделитель дробной части", "combo", [[".", "."], [",", ","]]],
      ["ЧРГ", "Разделитель групп", "combo", [[" ", "пробел: 123 456 789"], ["'", "': 123'456'789"], [",", ",: 123,456,789"],
        [".", ".: 123.456.789"]]],
      ["ЧГ", "Группировка", "combo", [["0", "0 - без групп"], ["3,0", "3,0"], ["3,2,0", "3,2,0"]]],
      ["ЧН", "Представление нуля", "combo", [["0", "0"], ["-", "-"], ["Ноль", "Ноль"]]],
      ["ЧО", "Представление отрицательных чисел", "select", [["0", "(1,1)"], ["1", "-1,1"], ["2", "- 1,1"], ["3", "1,1-"],
        ["4", "1,1 -"]]],
      ["ЧВН", "Выводить лидирующие нули", "flag"],
      ["ЧФ", "Шаблон форматирования числа", "combo", [["Ч", "Ч"], ["Ч руб.", "Ч руб."], ["Ч %", "Ч %"]]]
    ],
    date: [
      ["ДФ", "Формат даты", "combo", [["dd.MM.yyyy", "01.01.2001"], ["dd.MM.yy", "01.01.01"], ["d.M.yy", "1.1.01"],
        ["dd/MM/yy", "01/01/01"], ["yyyy-MM-dd", "2001-01-01"], ["d MMMM yyyy 'г.'", "1 января 2001 г."], ["HH:mm", "12:00"]]],
      ["ДЛФ", "Локальный формат даты", "select", [["D", "01.01.2001"], ["DD", "1 января 2001 г."], ["DT", "01.01.2001 12:00:00"],
        ["DDT", "1 января 2001 г. 12:00:00"], ["T", "12:00:00"]]],
      ["ДП", "Представление пустой даты", "combo", [["-", "-"], ["Нет даты", "Нет даты"], ["Пустая дата", "Пустая дата"]]]
    ],
    boolean: [
      ["БЛ", "Представление значения булево Ложь", "combo", [["Ложь", "Ложь"], ["Нет", "Нет"], ["Выключено", "Выключено"]]],
      ["БИ", "Представление значения булево Истина", "combo", [["Истина", "Истина"], ["Да", "Да"], ["Включено", "Включено"]]]
    ]
  };
  var FORMAT_TABS = { number: "Число", date: "Дата", "boolean": "Булево" };

  function openFormatChooser(item, prop) {
    var parsed = F.parse(isSet(item, prop) ? item.node[prop] : "");
    var known = {};
    F.NUMBER_KEYS.concat(F.DATE_KEYS, F.BOOLEAN_KEYS).forEach(function (key) { known[key] = true; });
    var params = {};
    var extra = [];
    Object.keys(parsed).forEach(function (key) {
      if (key === "ЧВН") params[key] = true;
      else if (known[key]) params[key] = parsed[key];
      else extra.push([key, parsed[key]]);
    });
    // Закладки - только по типу значения поля; тип не задан - все три. Одна закладка - без панели
    // закладок, как у конструктора форматной строки
    var type = item.kind === "CheckBoxField" ? "boolean" : item.node.dataType;
    var tabs = FORMAT_TABS[type] ? [type] : Object.keys(FORMAT_TABS);
    var now = new Date();
    now.setMilliseconds(0);
    dialog = { kind: "format", item: item, prop: prop, params: params, extra: extra, tabs: tabs,
      tab: tabs[0], number: "-987654.321", date: now };
    renderDialog();
  }

  // Строка формата: параметры в порядке конструктора, затем параметры, которых конструктор не знает (язык и т.п.)
  function formatText() {
    var text = F.build(dialog.params);
    var tail = dialog.extra.map(function (pair) { return pair[0] + " = " + (pair[1] === "" ? "" : "'" + pair[1] + "'"); });
    return [text].concat(tail).filter(Boolean).join("; ");
  }

  function setFormatParam(key, value) {
    if (value === undefined) delete dialog.params[key];
    else dialog.params[key] = value;
    renderDialog();
  }

  function formatControl(row) {
    var key = row[0];
    var value = has(dialog.params, key) ? dialog.params[key] : "";
    var control;
    if (row[2] === "flag") return null;
    if (row[2] === "select") {
      control = h("select");
      control.appendChild(option("", ""));
      row[3].forEach(function (pair) { control.appendChild(option(pair[0], pair[1])); });
    } else {
      control = h("input");
      if (row[2] === "integer") {
        control.type = "number";
        control.min = key === "ЧС" ? -99 : 0;
      } else {
        control.setAttribute("list", "fe-format-" + key);
        var choices = h("datalist");
        choices.id = "fe-format-" + key;
        row[3].forEach(function (pair) { choices.appendChild(option(pair[0], pair[1])); });
        control.appendChild(choices);
      }
    }
    control.className = "fe-format-value";
    control.dataset.key = key;
    control.value = String(value);
    control.addEventListener("change", function () { setFormatParam(key, control.value); });
    return control;
  }

  function renderFormat(body) {
    if (dialog.tabs.length > 1) dialogTabs(body, dialog.tabs.map(function (tab) { return [tab, FORMAT_TABS[tab]]; }));
    else body.appendChild(h("div", "fe-dialog-note", "Формат значения типа «" + FORMAT_TABS[dialog.tab] + "»"));
    var table = h("div", "fe-format-rows");
    FORMAT_ROWS[dialog.tab].forEach(function (row) {
      var line = h("label", "fe-format-row");
      var use = h("input");
      use.type = "checkbox";
      use.dataset.use = row[0];
      use.checked = has(dialog.params, row[0]);
      use.addEventListener("change", function () {
        setFormatParam(row[0], use.checked ? (row[2] === "flag" ? true : (row[2] === "integer" ? "0" : "")) : undefined);
      });
      line.appendChild(use);
      var name = h("span", "fe-format-name", row[1]);
      name.title = row[0];
      line.appendChild(name);
      var control = formatControl(row);
      if (control) line.appendChild(control);
      table.appendChild(line);
    });
    body.appendChild(table);
    body.appendChild(formatSample());
    var text = h("div", "fe-format-text");
    text.appendChild(h("span", "fe-format-name", "Строка формата:"));
    text.appendChild(h("code", "fe-format-result", formatText() || "(пусто - формат по умолчанию)"));
    body.appendChild(text);
  }

  // Пример значения и его представление по собираемой строке - тем же разбором, что читает 1С
  function formatSample() {
    var sample = h("div", "fe-format-sample");
    sample.appendChild(h("span", "fe-format-name", "Пример:"));
    var params = F.parse(formatText());
    var shown;
    if (dialog.tab === "boolean") {
      shown = "Ложь → " + F.boolean(false, params) + ";  Истина → " + F.boolean(true, params);
    } else {
      var input = h("input", "fe-format-input");
      if (dialog.tab === "date") {
        input.type = "datetime-local";
        input.step = 1;
        input.value = dialog.date ? localDate(dialog.date) : "";
      } else {
        input.value = dialog.number;
      }
      input.addEventListener("change", function () {
        if (dialog.tab === "date") dialog.date = input.value ? new Date(input.value) : null;
        else dialog.number = input.value;
        renderDialog();
      });
      sample.appendChild(input);
      sample.appendChild(h("span", "fe-format-arrow", "→"));
      shown = dialog.tab === "date" ? F.date(dialog.date, params)
        : F.number(Number(String(dialog.number).replace(",", ".").replace(/\s/g, "")), params);
    }
    sample.appendChild(h("span", "fe-format-shown", shown));
    return sample;
  }

  function localDate(date) {
    function two(value) { return (value < 10 ? "0" : "") + value; }
    return date.getFullYear() + "-" + two(date.getMonth() + 1) + "-" + two(date.getDate()) + "T" + two(date.getHours()) +
      ":" + two(date.getMinutes()) + ":" + two(date.getSeconds());
  }

  // Список выбора: две колонки, как в конфигураторе - значение и представление (в модели пункт - строка-значение или
  // `{value, presentation}`); без представления пользователь видит значение. Добавление, удаление, перемещение;
  // «Заполнить» - значениями перечисления поля (`enumValues`), как кнопка конфигуратора

  function openListChooser(item, prop) {
    var rows = (Array.isArray(item.node[prop]) ? item.node[prop] : []).map(function (entry) {
      return entry && typeof entry === "object" ? { value: String(entry.value), presentation: entry.presentation || "" }
        : { value: String(entry), presentation: "" };
    });
    dialog = { kind: "list", item: item, prop: prop, rows: rows, chosen: rows.length ? 0 : -1 };
    renderDialog();
  }

  function listValue() {
    var rows = dialog.rows.filter(function (row) { return row.value.trim() || row.presentation.trim(); })
      .map(function (row) { return choiceItem(row.value, row.presentation); });
    return rows.length ? rows : undefined;
  }

  function listCommand(name) {
    var rows = dialog.rows;
    var at = dialog.chosen;
    if (name === "add") {
      rows.splice(at + 1, 0, { value: "", presentation: "" });
      dialog.chosen = at + 1;
    } else if (name === "delete" && at >= 0) {
      rows.splice(at, 1);
      dialog.chosen = Math.min(at, rows.length - 1);
    } else if (name === "up" && at > 0) {
      rows.splice(at - 1, 0, rows.splice(at, 1)[0]);
      dialog.chosen = at - 1;
    } else if (name === "down" && at >= 0 && at < rows.length - 1) {
      rows.splice(at + 1, 0, rows.splice(at, 1)[0]);
      dialog.chosen = at + 1;
    } else if (name === "fill") {
      (Array.isArray(dialog.item.node.enumValues) ? dialog.item.node.enumValues : []).forEach(function (value) {
        var known = rows.some(function (row) { return row.value === String(value); });
        if (!known) rows.push({ value: String(value), presentation: "" });
      });
    }
    renderDialog();
    var focus = ui.dialogBox.querySelector('.fe-list-value[data-index="' + dialog.chosen + '"]');
    if (focus && name === "add") focus.focus();
  }

  function renderList(body) {
    var bar = h("div", "fe-list-bar");
    var canFill = Array.isArray(dialog.item.node.enumValues) && dialog.item.node.enumValues.length > 0;
    [["add", "Добавить"], ["delete", "Удалить"], ["up", "Вверх"], ["down", "Вниз"], ["fill", "Заполнить"]].forEach(function (pair) {
      var run = function () { listCommand(pair[0]); };
      var command = !TOOL_ICONS[pair[0]] ? dialogButton(pair[1], run, "fe-list-" + pair[0]) :
        toolButton(pair[0], pair[0] === "up" || pair[0] === "down" ? "" : pair[1],
          pair[0] === "up" ? "Переместить вверх" : pair[0] === "down" ? "Переместить вниз" : pair[1], run,
          "fe-dialog-button fe-list-" + pair[0]);
      command.dataset.command = pair[0];
      if (pair[0] === "fill" && !canFill) {
        command.disabled = true;
        command.title = "У поля нет значений перечисления (enumValues)";
      }
      bar.appendChild(command);
    });
    body.appendChild(bar);
    body.appendChild(h("div", "fe-dialog-note", "Представление не задано - пользователь видит значение"));
    var list = h("div", "fe-pick fe-list");
    var head = h("div", "fe-list-row fe-list-head");
    head.appendChild(h("span", "fe-list-number", "N"));
    head.appendChild(h("span", "fe-list-cell", "Значение"));
    head.appendChild(h("span", "fe-list-cell", "Представление"));
    list.appendChild(head);
    if (!dialog.rows.length) list.appendChild(h("div", "fe-pick-empty", "Список пуст - «Добавить» или «Заполнить»"));
    dialog.rows.forEach(function (row, index) {
      var line = h("div", "fe-list-row" + (index === dialog.chosen ? " fe-pick-chosen" : ""));
      line.appendChild(h("span", "fe-list-number", String(index + 1)));
      var presentation = h("input", "fe-list-value fe-list-presentation");
      [["value", h("input", "fe-list-value")], ["presentation", presentation]].forEach(function (pair) {
        var input = pair[1];
        input.value = row[pair[0]];
        input.dataset.index = String(index);
        input.dataset.column = pair[0];
        input.addEventListener("focus", function () {
          if (dialog.chosen === index) return;
          dialog.chosen = index;
          ui.dialogBox.querySelectorAll(".fe-list-row:not(.fe-list-head)").forEach(function (other, at) {
            other.classList.toggle("fe-pick-chosen", at === index);
          });
        });
        input.addEventListener("input", function () {
          dialog.rows[index][pair[0]] = input.value;
          // Пустое представление - серым значением: так пункт увидит пользователь
          if (pair[0] === "value") presentation.placeholder = input.value;
        });
        line.appendChild(input);
      });
      presentation.placeholder = row.value;
      list.appendChild(line);
    });
    body.appendChild(list);
  }

  // Команда кнопки: команды формы из кнопок модели, стандартные команды формы и таблиц (как их знает рендерер),
  // общие команды из модели; новая команда формы - по имени (`Form.Command.<Имя>`)

  function modelCommands() {
    var found = {};
    (function visit(node) {
      if (!node || typeof node !== "object") return;
      if (typeof node.commandName === "string" && node.commandName && !found[node.commandName]) {
        found[node.commandName] = typeof node.title === "string" ? node.title : "";
      }
      if (node.commandBar) visit(node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(visit);
    })(formOf(model));
    return found;
  }

  function tablesOf(node, list) {
    (Array.isArray(node.items) ? node.items : []).forEach(function (child) {
      if (child && child.type === "Table") list.push(child);
      if (child && typeof child === "object") tablesOf(child, list);
    });
    return list;
  }

  // Стандартные команды таблицы, доступные кнопке: без снятых в «Составе команд» и без запрещенных флагами
  // «Изменять состав строк» и «Изменять порядок строк», как в 1С
  var ROW_SET_COMMANDS = { Add: true, Copy: true, Delete: true };
  var ROW_ORDER_COMMANDS = { MoveUp: true, MoveDown: true, SortListAsc: true, SortListDesc: true };

  function availableTableCommands(table) {
    var excluded = Array.isArray(table.excludedCommands) ? table.excludedCommands : [];
    return R.tableCommands(table).filter(function (command) {
      if (excluded.indexOf(command.name) >= 0) return false;
      if (table.changeRowSet === false && ROW_SET_COMMANDS[command.name]) return false;
      return !(table.changeRowOrder === false && ROW_ORDER_COMMANDS[command.name]);
    });
  }

  // Таблица, в командной панели которой стоит кнопка, - ее группа раскрыта, остальные таблицы свернуты
  function ownerTable(item) {
    for (var up = item.parent; up; up = up.parent) if (up.kind === "Table") return up.node;
    return null;
  }

  function openCommandChooser(item, prop) {
    var used = modelCommands();
    var sections = [];
    var own = {};
    formCommandList().forEach(function (node) {
      if (node && typeof node.name === "string") own[COMMAND_PREFIX + node.name] = node.title || "";
    });
    Object.keys(used).forEach(function (name) {
      if (name.indexOf(COMMAND_PREFIX) === 0 && !has(own, name)) own[name] = used[name];
    });
    sections.push({ key: "form", title: "Команды формы", rows: Object.keys(own).sort().map(function (name) {
      return { value: name, title: name.slice(COMMAND_PREFIX.length), info: own[name] };
    }) });
    var form = formOf(model);
    var excluded = Array.isArray(form.excludedCommands) ? form.excludedCommands : [];
    sections.push({ key: "standard", title: "Стандартные команды формы", rows: R.formCommands().filter(function (command) {
      return excluded.indexOf(command.name) < 0;
    }).map(function (command) {
      return { value: "Form.StandardCommand." + command.name, title: command.title, info: command.name };
    }) });
    var table = ownerTable(item);
    tablesOf(form, []).forEach(function (node) {
      sections.push({ key: "table:" + node.name, title: "Таблица " + node.name, table: node,
        rows: availableTableCommands(node).map(function (command) {
          return { value: "Form.Item." + node.name + ".StandardCommand." + command.name, title: command.title, info: command.name };
        }) });
    });
    var common = Object.keys(used).filter(function (name) { return name.indexOf("CommonCommand.") === 0; }).sort();
    if (common.length) sections.push({ key: "common", title: "Общие команды", rows: common.map(function (name) {
      return { value: name, title: name.slice(14), info: used[name] };
    }) });
    var value = isSet(item, prop) ? String(item.node[prop]) : "";
    // Свернуто: таблицы, кроме своей, и пустые группы; группа текущей команды раскрыта
    var foldedSections = {};
    sections.forEach(function (section) {
      var current = section.rows.some(function (row) { return row.value === value; });
      if (!current && (!section.rows.length || section.table && section.table !== table)) foldedSections[section.key] = true;
    });
    dialog = { kind: "command", item: item, prop: prop, value: value, sections: sections, folded: foldedSections,
      filter: "", error: "" };
    renderDialog();
  }

  function renderCommandList(body) {
    var list = h("div", "fe-pick fe-command-list");
    body.appendChild(filterBox(list, ".fe-pick-row", refreshCommandList));
    var known = {};
    dialog.sections.forEach(function (section) {
      var head = h("div", "fe-pick-group");
      head.dataset.section = section.key;
      head.appendChild(twistyOf(section.rows.length > 0, false));
      head.appendChild(h("span", "", section.title));
      head.appendChild(h("span", "fe-pick-count", String(section.rows.length)));
      head.addEventListener("click", function () {
        if (dialog.filter.trim()) return;
        dialog.folded[section.key] = !dialog.folded[section.key];
        refreshCommandList(list);
      });
      list.appendChild(head);
      section.rows.forEach(function (row) {
        known[row.value] = true;
        var line = choiceRow(row.value, row.title, row.info);
        line.dataset.section = section.key;
        list.appendChild(line);
      });
    });
    refreshCommandList(list);
    if (dialog.value && !known[dialog.value]) {
      list.appendChild(h("div", "fe-pick-section", "Текущая"));
      list.appendChild(choiceRow(dialog.value, dialog.value, ""));
    }
    body.appendChild(list);
    var add = h("div", "fe-add-attribute");
    add.appendChild(h("span", "fe-add-title", "Новая команда формы:"));
    var name = h("input", "fe-add-name");
    name.placeholder = "Имя команды";
    add.appendChild(name);
    add.appendChild(dialogButton("Выбрать", function () {
      var text = name.value.trim();
      if (!NAME_1C.test(text)) {
        dialog.error = "имя 1С: буквы, цифры и _, не с цифры";
        renderDialog();
        return;
      }
      // Новая команда - сразу в команды формы: в левой колонке «Команды» ее можно описать
      if (!formCommandList().some(function (node) { return node && node.name === text; })) {
        if (!Array.isArray(model.commands)) setRootProp("commands", []);
        model.commands.push({ name: text });
      }
      dialog.value = COMMAND_PREFIX + text;
      confirmDialog();
    }, "fe-add-button"));
    if (dialog.error) add.appendChild(h("div", "fe-reason", dialog.error));
    body.appendChild(add);
  }

  // Группы окна команды: свернутая прячет строки; при поиске все раскрыты, группа без совпадений скрыта
  function refreshCommandList(list) {
    var query = dialog.filter.trim().toLowerCase();
    list.querySelectorAll(".fe-pick-group").forEach(function (head) {
      var key = head.dataset.section;
      var open = !!query || !dialog.folded[key];
      var shown = 0;
      list.querySelectorAll('.fe-pick-row[data-section="' + key + '"]').forEach(function (row) {
        row.hidden = !open || !!query && row.dataset.search.indexOf(query) < 0;
        if (!row.hidden) shown++;
      });
      head.hidden = !!query && !shown;
      head.firstChild.classList.toggle("fe-open", open);
    });
    // Строки без папки (типы верхнего уровня окна типа) - только поиск
    list.querySelectorAll(".fe-pick-row[data-flat]").forEach(function (row) {
      row.hidden = !!query && row.dataset.search.indexOf(query) < 0;
    });
  }

  function choiceRow(value, title, info) {
    var row = h("div", "fe-pick-row" + (dialog.value === value ? " fe-pick-chosen" : ""));
    row.dataset.value = value;
    row.dataset.search = (value + " " + title + " " + (info || "")).toLowerCase();
    if (dialog.filter && row.dataset.search.indexOf(dialog.filter.trim().toLowerCase()) < 0) row.hidden = true;
    row.appendChild(h("span", "fe-pick-name", title));
    if (info) row.appendChild(h("span", "fe-pick-info", info));
    row.addEventListener("click", function () {
      dialog.value = value;
      markChosen(row);
    });
    row.addEventListener("dblclick", function () {
      dialog.value = value;
      confirmDialog();
    });
    return row;
  }

  // Картинка: общие картинки конфигурации из `pictures` модели и библиотека стандартных картинок платформы
  // (сервер, `GET /std-pictures`), поиск по имени - английскому и русскому

  var stdLibrary = null;       // стандартные картинки: [{ name, ru, uri }], загружаются при первом окне
  var configLibrary = null;    // общие картинки конфигурации от сервера (`serve --src`): [{ name, title, uri }]

  function loadLibrary(url, key) {
    return fetch(url, { cache: "no-store" }).then(function (response) { return response.json(); })
      .then(function (data) { return data[key] || []; })
      .catch(function () { return []; });
  }

  function openPictureChooser(item, prop) {
    dialog = { kind: "picture", item: item, prop: prop, value: isSet(item, prop) ? String(item.node[prop]) : "",
      filter: "", loading: stdLibrary === null || configLibrary === null && !!ED.source };
    renderDialog();
    if (!dialog.loading) return;
    Promise.all([
      stdLibrary !== null ? stdLibrary : loadLibrary("/std-pictures", "pictures"),
      configLibrary !== null || !ED.source ? configLibrary || [] : loadLibrary("/config-pictures", "pictures")
    ]).then(function (found) {
      stdLibrary = found[0];
      configLibrary = found[1];
      if (dialog && dialog.kind === "picture") {
        dialog.loading = false;
        renderDialog();
      }
    });
  }

  function pictureTile(name, title, uri) {
    var tile = h("div", "fe-picture-tile" + (dialog.value === name ? " fe-pick-chosen" : ""));
    tile.dataset.picture = name;
    tile.dataset.search = (name + " " + title).toLowerCase();
    if (dialog.filter && tile.dataset.search.indexOf(dialog.filter.trim().toLowerCase()) < 0) tile.hidden = true;
    tile.title = name + (title ? " - " + title : "");
    var image = h("span", "fe-picture-image");
    if (uri) {
      var img = h("img");
      img.src = uri;
      img.alt = "";
      image.appendChild(img);
    } else {
      image.textContent = "?";
    }
    tile.appendChild(image);
    tile.appendChild(h("span", "fe-picture-name", title || name.replace(/^(StdPicture|CommonPicture)\./, "")));
    tile.addEventListener("click", function () {
      dialog.value = name;
      markChosen(tile);
      var note = ui.dialogBox.querySelector(".fe-picture-chosen");
      if (note) note.textContent = "Выбрана: " + name;
    });
    tile.addEventListener("dblclick", function () {
      dialog.value = name;
      confirmDialog();
    });
    return tile;
  }

  function renderPictures(body) {
    var list = h("div", "fe-picture-library");
    body.appendChild(filterBox(list, ".fe-picture-tile"));
    // Картинки конфигурации: все от сервера с исходниками и записанные в `pictures` модели
    var own = model.pictures && typeof model.pictures === "object" ? model.pictures : {};
    var common = {};
    (configLibrary || []).forEach(function (entry) { common[entry.name] = { title: entry.title, uri: entry.uri }; });
    Object.keys(own).filter(function (name) { return name.indexOf("CommonPicture.") === 0; }).forEach(function (name) {
      if (!common[name]) common[name] = { title: "", uri: own[name] };
    });
    if (dialog.value.indexOf("CommonPicture.") === 0 && !common[dialog.value]) common[dialog.value] = { title: "", uri: "" };
    var names = Object.keys(common).sort();
    list.appendChild(h("div", "fe-pick-section", "Картинки конфигурации"));
    if (!names.length) list.appendChild(h("div", "fe-pick-empty", dialog.loading ? "Загрузка..."
      : "Нет: все картинки конфигурации - при запуске serve --src <исходники>, иначе - из pictures модели"));
    var grid = h("div", "fe-picture-grid");
    names.forEach(function (name) {
      var title = common[name].title ? name.slice(14) + " - " + common[name].title : name.slice(14);
      grid.appendChild(pictureTile(name, title, common[name].uri));
    });
    list.appendChild(grid);
    list.appendChild(h("div", "fe-pick-section", "Стандартные картинки"));
    grid = h("div", "fe-picture-grid");
    if (dialog.loading) list.appendChild(h("div", "fe-pick-empty", "Загрузка..."));
    else if (!stdLibrary.length) list.appendChild(h("div", "fe-pick-empty", "Нет выгрузки стандартных картинок (--std-pictures)"));
    (stdLibrary || []).forEach(function (entry) { grid.appendChild(pictureTile(entry.name, entry.ru, entry.uri)); });
    list.appendChild(grid);
    body.appendChild(list);
    body.appendChild(h("div", "fe-dialog-note fe-picture-chosen", dialog.value ? "Выбрана: " + dialog.value : "Картинка не выбрана"));
  }

  // Тип реквизита (владелец): окно с группами - примитивные, коллекции (у реквизита формы), ссылки и
  // объекты по видам метаданных. Объекты метаданных - от сервера (`serve --src`, `GET /config-types`), без
  // исходников - описанные в `types` модели. «Составной тип данных» - несколько типов флажками. Ссылка на объект,
  // которого нет в `types`, при выборе приносит его описание (`GET /type-description`): путь к данным раскрывает
  // новый реквизит

  // Окно типа - по окну «Редактирование типа данных» конфигуратора (снимок владельца 04.11.2026): плоский список
  // типов, папки ссылок (строка папки - общий тип вида: `CatalogRef` - любая ссылка справочника), объекты и наборы
  // записей - у реквизита формы, прочие типы платформы, системные перечисления. «Внешняя обработка» - без исходников
  // внешних обработок не предлагается
  var PRIMITIVE_TYPES = ["Number", "String", "Date", "Boolean", "UUID"];
  var COLLECTION_TYPE_LIST = ["DynamicList", "ValueTable", "ValueTree", "ValueList"];
  var DOCUMENT_TYPES = ["FormattedString", "SpreadsheetDocument", "FormattedDocument", "TextDocument", "PDFDocument", "Null"];
  var REF_KINDS = ["Catalog", "Document", "Enum", "ChartOfCharacteristicTypes", "ChartOfAccounts", "ChartOfCalculationTypes",
    "BusinessProcess", "BusinessProcessRoutePoint", "Task", "ExchangePlan"];
  var OBJECT_KIND_LIST = ["Catalog", "Document", "ChartOfCharacteristicTypes", "ChartOfAccounts", "ChartOfCalculationTypes",
    "Report", "DataProcessor", "BusinessProcess", "Task", "ExchangePlan"];
  var OBJECT_KINDS = {};
  OBJECT_KIND_LIST.forEach(function (kind) { OBJECT_KINDS[kind] = true; });
  var RECORD_KINDS = [["InformationRegister", "RecordSet"], ["InformationRegister", "RecordManager"],
    ["AccumulationRegister", "RecordSet"], ["AccountingRegister", "RecordSet"], ["CalculationRegister", "RecordSet"]];
  var PLATFORM_TYPES = ["DataCompositionSettingsComposer", "GraphicalSchema", "GeographicalSchema", "Chart", "GanttChart",
    "Dendrogram", "Planner", "TypeDescription", "Picture", "Color", "Font", "StandardBeginningDate", "StandardPeriod"];
  var SYSTEM_ENUMS = ["AccumulationRecordType", "AccountType", "AccountingRecordType", "HorizontalAlign", "VerticalAlign",
    "SizeChangeMode", "AnalysisDataType", "ClusterizationMethod", "DataAnalysisTimeIntervalUnitType",
    "DataAnalysisResultTableFillType", "DataAnalysisNumericValueUseType", "AssociationRulesDataSourceType",
    "DataAnalysisColumnTypeDecisionTree", "DataAnalysisColumnTypeClusterization", "DataAnalysisColumnTypeSummaryStatistics",
    "DataAnalysisColumnTypeAssociationRules", "DataAnalysisColumnTypeSequentialPatterns", "PredictionModelColumnType",
    "DataAnalysisDistanceMetricType", "AssociationRulesPruneType", "DataAnalysisStandardizationType",
    "DecisionTreeSimplificationType", "DataAnalysisAssociationRulesOrderType", "DataAnalysisSequentialPatternsOrderType"];
  var configTypes = null;      // объекты метаданных от сервера: [{ key, kind, name, title, values }]
  var configLoading = null;

  function loadConfigTypes() {
    if (configTypes !== null) return Promise.resolve(configTypes);
    if (!ED.source) {
      configTypes = [];
      return Promise.resolve(configTypes);
    }
    if (!configLoading) {
      configLoading = fetch("/config-types", { cache: "no-store" }).then(function (response) { return response.json(); })
        .then(function (data) { configTypes = data.types || []; })
        .catch(function () { configTypes = []; })
        .then(function () { return configTypes; });
    }
    return configLoading;
  }

  // Объекты метаданных для окна: от сервера и из `types` модели (описанные вручную или импортом)
  function metadataObjects() {
    var found = {};
    (configTypes || []).forEach(function (entry) { found[entry.key] = entry; });
    var own = model && model.types && typeof model.types === "object" ? model.types : {};
    Object.keys(own).forEach(function (key) {
      if (found[key]) return;
      var dot = key.indexOf(".");
      found[key] = { key: key, kind: key.slice(0, dot), name: key.slice(dot + 1), title: (own[key] || {}).title || "" };
    });
    return Object.keys(found).map(function (key) { return found[key]; });
  }

  function openTypeChooser(item, prop) {
    var names = typeNames(item.node);
    dialog = { kind: "type", item: item, prop: prop, chosen: names.slice(), composite: names.length > 1, filter: "",
      folded: {}, loading: configTypes === null && !!ED.source, error: "" };
    renderDialog();
    loadConfigTypes().then(function () {
      if (dialog && dialog.kind === "type") {
        dialog.loading = false;
        renderDialog();
      }
    });
  }

  function typeSections() {
    var root = !dialog.item.parent;
    var objects = metadataObjects();
    function ofKind(kind) {
      return objects.filter(function (entry) { return entry.kind === kind; })
        .sort(function (a, b) { return a.name.localeCompare(b.name, "ru"); });
    }
    function named(list, prefix) {
      return list.map(function (entry) { return { name: prefix + entry.name, info: entry.title }; });
    }
    // Раздел без заголовка - строки всегда видны, как типы верхнего уровня окна 1С
    var sections = [{ key: "primitive", title: null, rows: [{ name: "", info: "" }].concat(PRIMITIVE_TYPES,
      root ? COLLECTION_TYPE_LIST : [], DOCUMENT_TYPES) }];
    REF_KINDS.forEach(function (kind) {
      sections.push({ key: "ref:" + kind, title: KIND_TITLES[kind] + "Ссылка", generic: kind + "Ref",
        rows: named(ofKind(kind === "BusinessProcessRoutePoint" ? "" : kind), kind + "Ref.") });
    });
    var characteristics = ofKind("ChartOfCharacteristicTypes");
    if (characteristics.length) sections.push({ key: "characteristic", title: "Характеристика", rows: named(characteristics, "Characteristic.") });
    var defined = ofKind("DefinedType");
    if (defined.length) sections.push({ key: "defined", title: "ОпределяемыйТип", rows: named(defined, "DefinedType.") });
    sections.push({ key: "anyref", title: null, rows: ["AnyRef"] });
    if (root) {
      // Объект и набор записей - тип основного реквизита формы объекта
      OBJECT_KIND_LIST.forEach(function (kind) {
        var list = ofKind(kind);
        if (list.length) sections.push({ key: "object:" + kind, title: KIND_TITLES[kind] + "Объект", rows: named(list, kind + "Object.") });
      });
      RECORD_KINDS.forEach(function (pair) {
        var list = ofKind(pair[0]);
        var role = pair[1];
        if (list.length) sections.push({ key: "record:" + pair.join(""), title: KIND_TITLES[pair[0]] + ROLE_TITLES[role],
          rows: named(list, pair[0] + role + ".") });
      });
    }
    sections.push({ key: "platform", title: null, rows: (root ? ["ConstantsSet", "ReportObject"] : []).concat(PLATFORM_TYPES) });
    sections.push({ key: "system", title: "Системные перечисления", rows: SYSTEM_ENUMS });
    // Выбранный тип вне списка (набран вручную) - своей группой, чтобы его можно было снять
    var listed = {};
    sections.forEach(function (section) {
      section.rows = section.rows.map(function (row) { return typeof row === "string" ? { name: row, info: "" } : row; });
      if (section.generic) section.rows.unshift({ name: section.generic, info: "любая ссылка вида", generic: true });
      section.rows.forEach(function (row) { listed[row.name] = true; });
    });
    var other = dialog.chosen.filter(function (name) { return !listed[name]; });
    if (other.length) sections.unshift({ key: "other", title: "Указанные", rows: other.map(function (name) { return { name: name, info: "" }; }) });
    return sections;
  }

  function renderTypes(body) {
    var bar = h("div", "fe-type-bar");
    var composite = h("label", "fe-type-composite");
    var box = h("input");
    box.type = "checkbox";
    box.checked = dialog.composite;
    box.addEventListener("change", function () {
      dialog.composite = box.checked;
      if (!box.checked) dialog.chosen = dialog.chosen.slice(0, 1);
      else dialog.chosen = dialog.chosen.filter(Boolean);
      renderDialog();
    });
    composite.appendChild(box);
    composite.appendChild(document.createTextNode("Составной тип данных"));
    var list = h("div", "fe-pick fe-command-list fe-type-list");
    bar.appendChild(filterBox(list, ".fe-pick-row", refreshCommandList));
    bar.appendChild(composite);
    body.appendChild(bar);
    if (dialog.loading) list.appendChild(h("div", "fe-pick-empty", "Загрузка объектов конфигурации..."));
    typeSections().forEach(function (section) {
      var chosenHere = section.rows.some(function (row) { return dialog.chosen.indexOf(row.name) >= 0; });
      if (!has(dialog.folded, section.key)) dialog.folded[section.key] = section.title !== null && !chosenHere;
      if (section.title === null) {
        section.rows.forEach(function (row) {
          // «Произвольный» - только у простого типа
          if (row.name === "" && dialog.composite) return;
          list.appendChild(typeRow(section, row));
        });
        return;
      }
      var head = h("div", "fe-pick-group");
      head.dataset.section = section.key;
      head.appendChild(twistyOf(true, false));
      head.appendChild(h("span", "", section.title));
      head.appendChild(h("span", "fe-pick-count", String(section.rows.length)));
      head.addEventListener("click", function () {
        if (dialog.filter.trim()) return;
        dialog.folded[section.key] = !dialog.folded[section.key];
        refreshCommandList(list);
      });
      list.appendChild(head);
      section.rows.forEach(function (row) { list.appendChild(typeRow(section, row)); });
    });
    refreshCommandList(list);
    body.appendChild(list);
    var shown = dialog.chosen.map(typeTitle).join(", ");
    body.appendChild(h("div", "fe-dialog-note fe-type-chosen", shown ? "Тип: " + shown : "Тип не выбран"));
    if (!ED.source) body.appendChild(h("div", "fe-dialog-note", "Объекты конфигурации - из types модели; все объекты - при запуске serve --src <исходники>"));
    if (dialog.error) body.appendChild(h("div", "fe-reason", dialog.error));
  }

  function typeRow(section, row) {
    var on = dialog.chosen.indexOf(row.name) >= 0;
    var line = h("div", "fe-pick-row" + (on && !dialog.composite ? " fe-pick-chosen" : "") + (section.title === null ? "" : " fe-pick-nested"));
    var title = row.name === "" ? "Произвольный" : typeTitle(row.name);
    line.dataset.value = row.name;
    line.dataset.section = section.key;
    if (section.title === null) line.dataset.flat = "1";
    line.dataset.search = (row.name + " " + title + " " + (row.info || "")).toLowerCase();
    if (dialog.composite) {
      var check = h("input");
      check.type = "checkbox";
      check.checked = on;
      check.tabIndex = -1;
      line.appendChild(check);
    }
    line.appendChild(h("span", "fe-pick-name", title));
    if (row.info) line.appendChild(h("span", "fe-pick-info", row.info));
    line.addEventListener("click", function () { chooseType(row.name); });
    line.addEventListener("dblclick", function () {
      if (dialog.composite) return;
      dialog.chosen = [row.name];
      confirmDialog();
    });
    return line;
  }

  function chooseType(name) {
    var index = dialog.chosen.indexOf(name);
    if (!dialog.composite) dialog.chosen = [name];
    else if (index >= 0) dialog.chosen.splice(index, 1);
    else dialog.chosen.push(name);
    dialog.error = "";
    ui.dialogBox.querySelectorAll(".fe-type-list .fe-pick-row[data-value]").forEach(function (row) {
      var on = dialog.chosen.indexOf(row.dataset.value) >= 0;
      var check = row.querySelector("input");
      if (check) check.checked = on;
      else row.classList.toggle("fe-pick-chosen", on);
    });
    var shown = dialog.chosen.map(typeTitle).join(", ");
    var note = ui.dialogBox.querySelector(".fe-type-chosen");
    if (note) note.textContent = shown ? "Тип: " + shown : "Тип не выбран";
    var reason = ui.dialogBox.querySelector(".fe-dialog-body > .fe-reason");
    if (reason) reason.remove();
  }

  // Описание ссылочного типа, которого нет в `types`, - от сервера; без исходников тип остается без состава
  async function describeTypes(names) {
    if (!ED.source) return;
    var own = model.types && typeof model.types === "object" ? model.types : {};
    for (var i = 0; i < names.length; i++) {
      var type = typeOf(names[i]);
      if (!type || has(own, type.key)) continue;
      try {
        var response = await fetch("/type-description?key=" + encodeURIComponent(type.key), { cache: "no-store" });
        if (!response.ok) continue;
        rootDict("types")[type.key] = await response.json();
        own = model.types;
      } catch (error) { /* сервер недоступен: тип без состава */ }
    }
  }

  // Реквизиты формы в левой колонке (владелец): переключатель «Элементы / Реквизиты», дерево реквизитов
  // формы (`attributes`) и их колонок - правятся в панели свойств; состав типов (`types`) - серым, только просмотр.
  // Переименование реквизита переписывает пути к данным элементов

  var leftMode = "items";       // левая колонка: «items» - элементы, «attributes» - реквизиты, «commands» - команды
  var attrSelected = null;      // ключ выбранного узла дерева реквизитов
  var attrEntries = {};
  var attrOpen = {};            // раскрытые узлы дерева реквизитов: путь → true

  function setLeftMode(mode) {
    leftMode = mode;
    if (mode !== "items") picked = [];
    ui.leftItems.classList.toggle("fe-mode-on", mode === "items");
    ui.leftAttrs.classList.toggle("fe-mode-on", mode === "attributes");
    ui.leftCommands.classList.toggle("fe-mode-on", mode === "commands");
    ui.tree.hidden = mode !== "items";
    ui.itemTools.hidden = mode !== "items";
    closeMenu();
    ui.attrPanel.hidden = mode !== "attributes";
    ui.cmdPanel.hidden = mode !== "commands";
    invalid = {};
    invalidText = {};
    if (mode === "attributes") renderAttrTree();
    if (mode === "commands") renderCommandTree();
    renderProps();
    (mode === "items" ? ui.tree : mode === "attributes" ? ui.attrTree : ui.cmdTree).focus();
  }

  // Узел дерева реквизитов: `editable` - реквизит формы или его колонка (в `attributes`), иначе состав типа
  function attrItem(entry, editable, list, parent) {
    var item = { key: "@attr:" + entry.path, node: entry.node, entry: entry, path: entry.path, list: list,
      parent: parent, editable: editable, kind: editable ? "Attribute" : "AttributeInfo" };
    attrEntries[item.key] = item;
    return item;
  }

  // Колонки реквизита формы и дополнительные колонки табличной части объекта (`additionalColumns` реквизита,
  // владелец 04.11.2026: свои колонки табличной части без правки метаданных) правятся, состав типа - нет
  function attrChildren(item) {
    var columns = item.editable && Array.isArray(item.node.columns) ? item.node.columns : [];
    var extra = extraColumns(item, false) || [];
    return pathMembers(item.entry).map(function (entry) {
      var list = columns.indexOf(entry.node) >= 0 ? columns : extra.indexOf(entry.node) >= 0 ? extra : null;
      var child = attrItem(entry, !!list, list, item);
      child.extra = list === extra;
      return child;
    });
  }

  // Дополнительные колонки табличной части объекта (не реквизита формы); `create` - завести список
  function extraColumns(item, create) {
    var entry = item.entry;
    if (item.editable || !entry.rel || !isCollection(entry.node)) return null;
    var root = entry.root;
    var found = root.additionalColumns && root.additionalColumns[entry.rel];
    if (Array.isArray(found) || !create) return Array.isArray(found) ? found : null;
    if (!root.additionalColumns || typeof root.additionalColumns !== "object") setProp(root, "additionalColumns", {});
    root.additionalColumns[entry.rel] = [];
    return root.additionalColumns[entry.rel];
  }

  function attrRoots() {
    var list = model && Array.isArray(model.attributes) ? model.attributes : [];
    return attributeRoots().map(function (entry) { return attrItem(entry, true, list, null); });
  }

  function renderAttrTree() {
    attrEntries = {};
    var box = ui.attrTree;
    box.innerHTML = "";
    var roots = attrRoots();
    var used = usages().paths;
    if (!roots.length) box.appendChild(h("div", "fe-pick-empty", "Реквизитов нет - «Добавить реквизит»"));
    (function visit(items, depth) {
      items.forEach(function (item) {
        var children = attrChildren(item);
        item.childKeys = children.map(function (child) { return child.key; });
        var row = h("div", "fe-row" + (item.editable ? "" : " fe-pale"));
        if (!item.editable) row.title = "Реквизит из метаданных (types) - только просмотр";
        row.draggable = true;
        row.dataset.key = item.key;
        row.dataset.path = item.path;
        row.style.paddingLeft = px(4 + depth * 16);
        if (item.key === attrSelected) row.classList.add("fe-selected");
        var twisty = twistyOf(children.length > 0, !!attrOpen[item.path]);
        twisty.addEventListener("click", function (event) {
          event.stopPropagation();
          if (!children.length) return;
          attrOpen[item.path] = !attrOpen[item.path];
          renderAttrTree();
        });
        row.appendChild(twisty);
        var icon = h("span", "fe-icon");
        var tabular = isCollection(item.node) || !!item.parent && isCollection(item.parent.node);
        icon.innerHTML = '<svg viewBox="0 0 16 16">' + (tabular ? ICONS.table : ICONS.attribute) + "</svg>";
        row.appendChild(icon);
        var standard = STANDARD_NAMES[item.node.name];
        row.appendChild(h("span", "fe-label", standard || item.node.name));
        var info = typeNames(item.node).map(typeTitle).join(", ");
        if (item.extra) info = (info ? info + " - " : "") + "колонка формы";
        if (info) row.appendChild(h("span", "fe-pick-info", info));
        if (used[item.path]) row.appendChild(usageLink(used[item.path]));
        row.addEventListener("click", function () { selectAttr(item.key); });
        box.appendChild(row);
        if (attrOpen[item.path]) visit(children, depth + 1);
      });
    })(roots, 0);
    var current = attrEntries[attrSelected];
    ui.attrAddColumn.disabled = !columnOwner(current);
    ui.attrDelete.disabled = !(current && current.editable);
  }

  // Куда добавляется колонка: таблица или дерево значений реквизита формы, табличная часть объекта (колонка формы
  // в `additionalColumns`); у выбранной колонки - ее таблица
  function columnOwner(item) {
    if (!item) return null;
    if (holdsColumns(item)) return item;
    return item.parent && holdsColumns(item.parent) ? item.parent : null;
  }

  function holdsColumns(item) {
    if (item.editable) {
      return isCollection(item.node) &&
        typeNames(item.node).some(function (name) { return name === "ValueTable" || name === "ValueTree"; });
    }
    return !!item.entry.rel && isCollection(item.entry.node);
  }

  // Меню закладки «Реквизиты»: те же действия, что кнопки над деревом
  function attrMenu(at) {
    var current = attrEntries[attrSelected];
    openListMenu([
      { action: "add-attr", text: "Добавить реквизит", add: true, run: function () { addAttr(false); } },
      { action: "add-column", text: "Добавить колонку", add: true, off: !columnOwner(current), run: function () { addAttr(true); } },
      null,
      { action: "delete", text: "Удалить", key: "Del", off: !(current && current.editable), run: deleteAttr }
    ], at, ui.attrTree);
  }

  // Элементы формы по пути к данным и по команде: значок «есть на форме» в левой колонке, как в конфигураторе;
  // щелчок по значку выбирает элемент (владелец 04.11.2026)
  function usages() {
    var found = { paths: {}, commands: {} };
    function add(map, key, name) { (map[key] = map[key] || []).push(name); }
    (function visit(node) {
      if (!node || typeof node !== "object") return;
      if (typeof node.name === "string" && typeof node.dataPath === "string") add(found.paths, node.dataPath, node.name);
      if (typeof node.name === "string" && typeof node.commandName === "string") add(found.commands, node.commandName, node.name);
      if (node.commandBar) visit(node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(visit);
    })(formOf(model));
    return found;
  }

  function usageLink(names) {
    var link = h("button", "fe-usage");
    link.type = "button";
    link.tabIndex = -1;
    link.dataset.element = names[0];
    link.title = "На форме: " + names.join(", ") + " - перейти к элементу";
    link.innerHTML = '<svg viewBox="0 0 16 16"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor"/>' +
      '<rect x="4" y="7" width="8" height="3" rx="0.5" fill="currentColor"/></svg>';
    // Левая колонка остается на своей закладке (владелец 04.11.2026): строка реквизита или команды выбрана,
    // элемент выделен на макете и в дереве элементов
    link.addEventListener("click", function (event) {
      event.stopPropagation();
      var key = link.closest(".fe-row").dataset.key;
      if (leftMode === "attributes") selectAttr(key);
      else if (leftMode === "commands") selectCommand(key);
      select(names[0]);
      (leftMode === "commands" ? ui.cmdTree : ui.attrTree).focus();
    });
    return link;
  }

  function attrKey(event) {
    if (listKey(event, attrMenu, deleteAttr)) return;
    var done = treeNavigate(event, {
      keys: Array.prototype.map.call(ui.attrTree.querySelectorAll(".fe-row"), function (row) { return row.dataset.key; }),
      current: attrEntries[attrSelected] ? attrSelected : null,
      children: function (key) { return attrEntries[key].childKeys || []; },
      open: function (key) { return !!attrOpen[attrEntries[key].path]; },
      setOpen: function (key, on) {
        attrOpen[attrEntries[key].path] = on;
        renderAttrTree();
      },
      parent: function (key) { return attrEntries[key].parent ? attrEntries[key].parent.key : null; },
      select: selectAttr
    });
    if (done) event.preventDefault();
  }

  function selectAttr(key) {
    attrSelected = key;
    invalid = {};
    invalidText = {};
    renderAttrTree();
    renderProps();
  }

  // Выбор держится за узел модели: после переименования ключ (путь) другой
  function reselectAttr(node) {
    renderAttrTree();
    var keys = Object.keys(attrEntries);
    for (var i = 0; i < keys.length; i++) {
      if (attrEntries[keys[i]].node === node) {
        attrSelected = keys[i];
        break;
      }
    }
    renderAttrTree();
  }

  function uniqueName(list, base) {
    for (var n = 1; ; n++) {
      var name = base + n;
      if (!list.some(function (node) { return node && node.name === name; })) return name;
    }
  }

  function addAttr(column) {
    var current = column ? columnOwner(attrEntries[attrSelected]) : attrEntries[attrSelected];
    var list;
    if (column) {
      if (!current) return;
      if (current.editable) {
        if (!Array.isArray(current.node.columns)) setProp(current.node, "columns", []);
        list = current.node.columns;
      } else {
        list = extraColumns(current, true);
        if (!list) return;
      }
      attrOpen[current.path] = true;
      // Имя не совпадает и с колонками из метаданных
      var taken = pathMembers(current.entry).map(function (entry) { return entry.node; });
      var node = { name: uniqueName(taken, "Колонка"), valueType: "String" };
      list.push(node);
      changed();
      reselectAttr(node);
      renderProps();
      focusField("name");
      return;
    } else {
      if (!Array.isArray(model.attributes)) setRootProp("attributes", []);
      list = model.attributes;
    }
    var node = { name: uniqueName(list, column ? "Колонка" : "Реквизит"), valueType: "String" };
    list.push(node);
    changed();
    reselectAttr(node);
    renderProps();
    focusField("name");
  }

  function deleteAttr() {
    var current = attrEntries[attrSelected];
    if (!current || !current.editable) return;
    current.list.splice(current.list.indexOf(current.node), 1);
    // Пустые дополнительные колонки - убрать из модели
    var root = current.extra && current.entry.root;
    if (root && !current.list.length) {
      delete root.additionalColumns[current.parent.entry.rel];
      if (!Object.keys(root.additionalColumns).length) delete root.additionalColumns;
    }
    attrSelected = current.parent ? current.parent.key : null;
    changed();
  }

  // Пути к данным элементов по переименованному реквизиту: `Старый...` → `Новый...`
  function renameAttr(item, name) {
    var old = item.path;
    item.node.name = name;
    var renamed = (item.parent ? item.parent.path + "." : "") + name;
    (function visit(node) {
      if (!node || typeof node !== "object") return;
      ["dataPath", "rowPictureDataPath"].forEach(function (prop) {
        var value = node[prop];
        if (typeof value === "string" && (value === old || value.indexOf(old + ".") === 0)) {
          node[prop] = renamed + value.slice(old.length);
        }
      });
      if (node.commandBar) visit(node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(visit);
    })(formOf(model));
    if (attrOpen[old]) attrOpen[renamed] = true;
  }

  // Тип реквизита - русскими именами, как в конфигураторе (`Строка`, `СправочникСсылка.Банки`), составной - через
  // запятую; набранное принимается и по-русски, и по-английски, в модель - английское имя платформы
  function typeField(item, prop, spec, value) {
    var field = mark(h("input"), prop);
    var names = Array.isArray(value) ? value : value === undefined ? [] : [String(value)];
    field.value = names.map(typeTitle).join(", ");
    field.placeholder = "Строка, Число, СправочникСсылка.Имя...";
    editable(field, item, prop, function (text) {
      var list = text.split(",").map(function (part) { return typeName(part.trim()); }).filter(Boolean);
      if (!list.length) return parseError("тип обязателен");
      return list.length === 1 ? list[0] : list;
    });
    return field;
  }

  // Свойства реквизита по типу: длина - у строки, разрядность - у числа, состав - у даты, основная таблица - у
  // динамического списка, «основной» - только у реквизита формы, не у колонки
  var ATTR_BY_TYPE = { length: "String", digits: "Number", fractionDigits: "Number", dateFractions: "Date",
    mainTable: "DynamicList" };

  function attrApplicable(item, specs) {
    var types = typeNames(item.node);
    var shown = {};
    Object.keys(specs).forEach(function (prop) {
      var byType = !has(ATTR_BY_TYPE, prop) || types.indexOf(ATTR_BY_TYPE[prop]) >= 0;
      if (prop === "main") byType = !item.parent;
      if (byType || isSet(item, prop)) shown[prop] = specs[prop];
    });
    return shown;
  }

  function renderAttrInfo(item) {
    var body = ui.propsBody;
    body.innerHTML = "";
    ui.propsTitle.textContent = "Свойства: Реквизит";
    if (!item) {
      body.appendChild(h("div", "fe-props-note", "Выберите реквизит формы в дереве слева или добавьте новый"));
      return;
    }
    body.appendChild(h("div", "fe-props-note", "Состав типа из метаданных (types) - только просмотр: правится импортом формы из исходников"));
    [["Имя", STANDARD_NAMES[item.node.name] ? STANDARD_NAMES[item.node.name] + " (" + item.node.name + ")" : item.node.name],
      ["Заголовок", item.node.title || ""], ["Тип", typeNames(item.node).map(typeTitle).join(", ")],
      ["Путь", item.path]].forEach(function (pair) {
      var row = h("div", "fe-prop");
      row.appendChild(h("div", "fe-prop-name", pair[0]));
      var cell = h("div", "fe-value");
      cell.appendChild(h("span", "fe-locked", pair[1]));
      row.appendChild(cell);
      body.appendChild(row);
    });
  }

  // Команды формы в левой колонке (владелец): `commands` модели; команда, на которую ссылается кнопка, а в
  // `commands` ее нет (модель до команд), - бледной строкой, первая правка ее заводит. Переименование команды
  // переписывает `commandName` кнопок

  var cmdSelected = null;       // ключ выбранной команды
  var cmdEntries = {};
  var COMMAND_PREFIX = "Form.Command.";

  function formCommandList() {
    return model && Array.isArray(model.commands) ? model.commands : [];
  }

  function cmdItem(node, virtual) {
    var item = { key: "@cmd:" + node.name, node: node, kind: "Command", list: formCommandList(), virtual: virtual };
    cmdEntries[item.key] = item;
    return item;
  }

  function renderCommandTree() {
    cmdEntries = {};
    var box = ui.cmdTree;
    box.innerHTML = "";
    var items = formCommandList().filter(function (node) { return node && typeof node.name === "string"; })
      .map(function (node) { return cmdItem(node, false); });
    var used = modelCommands();
    Object.keys(used).filter(function (name) { return name.indexOf(COMMAND_PREFIX) === 0; }).sort().forEach(function (name) {
      var own = name.slice(COMMAND_PREFIX.length);
      if (!cmdEntries["@cmd:" + own]) items.push(cmdItem({ name: own }, true));
    });
    if (!items.length) box.appendChild(h("div", "fe-pick-empty", "Команд формы нет - «+ Команда»"));
    var buttons = usages().commands;
    items.forEach(function (item) {
      var row = h("div", "fe-row" + (item.virtual ? " fe-pale" : ""));
      if (item.virtual) row.title = "Команда кнопки без описания: первая правка заводит ее в командах формы";
      row.draggable = true;
      row.dataset.key = item.key;
      row.dataset.name = item.node.name;
      row.style.paddingLeft = px(8);
      if (item.key === cmdSelected) row.classList.add("fe-selected");
      var icon = h("span", "fe-icon");
      icon.innerHTML = '<svg viewBox="0 0 16 16">' + ICONS.button + "</svg>";
      row.appendChild(icon);
      row.appendChild(h("span", "fe-label", item.node.name));
      var info = item.virtual ? "нет в командах формы" : item.node.title || "";
      if (info) row.appendChild(h("span", "fe-pick-info", info));
      var users = buttons[COMMAND_PREFIX + item.node.name];
      if (users) row.appendChild(usageLink(users));
      row.addEventListener("click", function () { selectCommand(item.key); });
      box.appendChild(row);
    });
    var current = box.querySelector(".fe-selected");
    if (current) current.scrollIntoView({ block: "nearest" });
    ui.cmdDelete.disabled = !(cmdEntries[cmdSelected] && !cmdEntries[cmdSelected].virtual);
  }

  function selectCommand(key) {
    cmdSelected = key;
    invalid = {};
    invalidText = {};
    renderCommandTree();
    renderProps();
  }

  function commandKey(event) {
    if (listKey(event, commandMenu, deleteCommand)) return;
    var done = treeNavigate(event, {
      keys: Array.prototype.map.call(ui.cmdTree.querySelectorAll(".fe-row"), function (row) { return row.dataset.key; }),
      current: cmdEntries[cmdSelected] ? cmdSelected : null,
      children: function () { return []; },
      open: function () { return false; },
      setOpen: function () {},
      parent: function () { return null; },
      select: selectCommand
    });
    if (done) event.preventDefault();
  }

  function addCommand() {
    if (!Array.isArray(model.commands)) setRootProp("commands", []);
    var taken = model.commands.concat(Object.keys(modelCommands()).map(function (name) {
      return { name: name.slice(COMMAND_PREFIX.length) };
    }));
    var node = { name: uniqueName(taken, "Команда") };
    model.commands.push(node);
    cmdSelected = "@cmd:" + node.name;
    changed();
    focusField("name");
  }

  // Меню закладки «Команды»: те же действия, что кнопки над списком
  function commandMenu(at) {
    var current = cmdEntries[cmdSelected];
    openListMenu([
      { action: "add-command", text: "Добавить команду", add: true, run: addCommand },
      null,
      { action: "delete", text: "Удалить", key: "Del", off: !(current && !current.virtual), run: deleteCommand }
    ], at, ui.cmdTree);
  }

  function deleteCommand() {
    var current = cmdEntries[cmdSelected];
    if (!current || current.virtual) return;
    model.commands.splice(model.commands.indexOf(current.node), 1);
    if (!model.commands.length) delete model.commands;
    cmdSelected = null;
    changed();
  }

  // Кнопки команды: `Form.Command.<Старое>` → `Form.Command.<Новое>`
  function renameCommand(item, name) {
    var old = COMMAND_PREFIX + item.node.name;
    item.node.name = name;
    (function visit(node) {
      if (!node || typeof node !== "object") return;
      if (node.commandName === old) node.commandName = COMMAND_PREFIX + name;
      if (node.commandBar) visit(node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(visit);
    })(formOf(model));
    cmdSelected = "@cmd:" + name;
  }

  // Правка свойства: проверка по схеме, умолчание платформы - убрать из модели, имя - уникальность и renamedFrom

  function validate(item, prop, value, spec) {
    if (value && typeof value === "object" && value.error) return value.error;
    if (value === undefined) return prop === "name" ? "имя обязательно" : "";
    if (prop === "currentPage") return "";
    if (spec.input === "integer" && typeof spec.minimum === "number" && value < spec.minimum) return "не меньше " + spec.minimum;
    if (spec.input === "enum" && spec.values.indexOf(value) < 0) return "значение не из списка";
    if (spec.pattern && typeof value === "string" && !new RegExp(spec.pattern).test(value)) {
      if (spec.input === "name") return "имя 1С: буквы, цифры и _, не с цифры";
      if (spec.input === "color") return "#RRGGBB, имя web-цвета латиницей или style:<Имя элемента стиля>";
      return "значение не по образцу " + spec.pattern;
    }
    if (prop === "name" && item.kind === "Attribute" && value !== item.node.name &&
        (item.parent ? pathMembers(item.parent.entry) : attributeRoots()).some(function (entry) {
          return entry.name === value && entry.node !== item.node;
        })) return (item.parent ? "колонка " : "реквизит ") + value + " уже есть";
    if (prop === "name" && item.kind === "Command" && value !== item.node.name &&
        (formCommandList().some(function (node) { return node && node.name === value; }) ||
          has(modelCommands(), COMMAND_PREFIX + value))) return "команда " + value + " уже есть";
    if (prop === "name" && item.kind !== "Attribute" && item.kind !== "Command" && value !== item.node.name &&
        collectNames(formOf(model))[value]) {
      return "имя " + value + " уже занято";
    }
    return "";
  }

  function sameValue(left, right) { return textOf(left) === textOf(right); }

  // `text` - набранный текст: при недопустимом значении он остается в поле с причиной
  function apply(item, prop, value, text) {
    if (item.multi) {
      applyMany(item, prop, value, text);
      return;
    }
    if (prop === "type") {
      if (value && value !== item.node.type && fieldKinds(item).indexOf(value) >= 0) {
        changeKind(item.node, value);
        changed();
      }
      return;
    }
    var kind = item.kind;
    var spec = (KINDS[kind] || KINDS.Unknown)[prop];
    var error = validate(item, prop, value, spec);
    if (error) {
      invalid[prop] = error;
      if (text !== undefined) invalidText[prop] = text;
      focusProp = prop;
      renderProps();
      return;
    }
    var hadError = has(invalid, prop);
    delete invalid[prop];
    delete invalidText[prop];
    var node = item.node;
    var current = isSet(item, prop) ? node[prop] : undefined;
    var fallback = defaultOf(kind, prop);
    if (value !== undefined && fallback !== undefined && sameValue(value, fallback)) value = undefined;
    if (sameValue(value, current) && !(value === undefined && isSet(item, prop))) {
      if (hadError) renderProps();
      focusProp = null;
      return;
    }
    materialize(item);
    if (spec.input === "color") addStyle(value);
    if (prop === "name" && item.kind === "Attribute") renameAttr(item, value);
    else if (prop === "name" && item.kind === "Command") renameCommand(item, value);
    else if (prop === "name") rename(item, value);
    else if (value === undefined) delete node[prop];
    else setProp(node, prop, value);
    if (has(AUTO_MAX, prop) && node[prop] !== false) delete node[AUTO_MAX[prop]];
    if (item.kind === "Attribute" && prop === "valueType") trimQualifiers(node);
    if (item.kind === "Attribute" && ATTR_TYPE_PROPS[prop]) syncFields(node);
    if (prop === "dataPath") inheritTitle(node, typeof current === "string" ? current : "");
    if (prop === "commandName") followCommand(node, typeof current === "string" ? current : "");
    if (prop === "dataPath") resetKind(node, placeOf(item) === "column");
    if (prop === "dataPath" && node.type === "InputField") mirrorField(node);
    changed();
    if (prop === "dataPath" && item.kind === "Table") tablePathChanged(item, typeof current === "string" ? current : "");
    if (prop === "autoFill" && node.autoFill === false && fillable(item)) offerStandard(item);
  }

  // Кнопки автозаполнения - в модель: у командной панели формы и таблицы «Заполнить стандартными
  // командами» создает кнопки тех стандартных команд, что показывало автозаполнение (их список - у рендерера), в том
  // же порядке и перед своими кнопками панели; исключенные и уже поставленные кнопкой - нет

  function fillable(item) { return !!item && item.kind === "AutoCommandBar" && !!item.owner; }

  function standardFill(item) {
    if (!model || !fillable(item)) return [];
    var table = item.owner.type === "Table" ? item.owner : null;
    var prefix = table ? "Form.Item." + table.name + ".StandardCommand." : "Form.StandardCommand.";
    var placed = {};
    (function visit(node) {
      (Array.isArray(node.items) ? node.items : []).forEach(function (child) {
        if (!child || typeof child !== "object") return;
        if (typeof child.commandName === "string") placed[child.commandName] = true;
        visit(child);
      });
    })(item.node);
    return R.autoCommands(table, formOf(model)).filter(function (command) {
      return !placed[prefix + command.name];
    }).map(function (command) {
      return Object.assign({ commandName: prefix + command.name }, command);
    });
  }

  // Имя кнопки - владелец панели и заголовок команды словами вместе, как в конфигураторе («ФормаЗаписатьИЗакрыть»,
  // «ТоварыДобавить»)
  function standardButtonName(owner, title) {
    return owner + title.replace(/[^0-9A-Za-zА-Яа-яЁё ]/g, "").split(" ").filter(Boolean).map(function (word) {
      return word.charAt(0).toUpperCase() + word.slice(1);
    }).join("");
  }

  function fillStandard(item) {
    var list = standardFill(item);
    if (!list.length) return;
    var names = collectNames(formOf(model));
    var owner = item.owner.type === "Table" ? item.owner.name : "Форма";
    list.forEach(function (command, index) {
      var node = { type: "Button", name: nameLike(standardButtonName(owner, command.title), names),
        buttonType: "CommandBarButton", commandName: command.commandName };
      if (command["default"]) node.defaultButton = true;
      insertNode(item, index, node);
    });
    changed();
  }

  // Снят флажок «Автозаполнение» - сразу предложение; «Заполнить» - одним шагом со снятием: «Отменить» возвращает и флажок
  function offerStandard(item) {
    var list = standardFill(item);
    if (!list.length) return;
    dialog = { kind: "autofill", item: item, list: list, merge: true };
    renderDialog();
  }

  function renderAutofillOffer(body) {
    body.appendChild(h("div", "fe-dialog-note", "Автозаполнение снято: стандартные команды больше не показываются на панели."));
    body.appendChild(h("div", "", "Создать их кнопками? Тогда рядом с ними можно поставить свои."));
    var list = h("div", "fe-pick fe-columns-offer");
    dialog.list.forEach(function (command) {
      var row = h("div", "fe-pick-row");
      row.dataset.value = command.commandName;
      row.appendChild(h("span", "fe-pick-name", command.title));
      row.appendChild(h("span", "fe-pick-info", command.commandName));
      list.appendChild(row);
    });
    body.appendChild(list);
  }

  // Шаг истории предыдущей правки сливается со следующей: она - продолжение того же действия
  function joinLastStep() {
    if (recordQueued) record();
    if (!undoStack.length) return;
    stable = undoStack.pop();
    renderHistory();
  }

  // Заголовок по пути к данным, как у импорта (`field_title`): синоним реквизита, иначе последнее имя пути по словам
  // (стандартный реквизит - русским именем); без пути - заголовка нет, рендерер пишет имя элемента по словам
  function pathTitle(path) { return R.pathTitle(model, path); }

  // Смена пути (владелец 04.11.2026): унаследованный заголовок - его нет или он равен заголовку прежнего пути -
  // берется от нового реквизита; свой заголовок элемента остается. Имя элемента - забота пользователя
  function inheritTitle(node, old) {
    var path = typeof node.dataPath === "string" ? node.dataPath : "";
    if (has(node, "title") && node.title !== pathTitle(old) && node.title !== R.splitName(node.name)) return;
    var title = pathTitle(path);
    if (title === undefined) delete node.title;
    else setProp(node, "title", title, "name");
  }

  // Смена команды кнопки (владелец 04.11.2026), как смена пути: унаследованный заголовок - равный заголовку прежней
  // команды или имени по словам - снимается, и кнопка берет заголовок новой команды; свой заголовок остается
  function followCommand(node, old) {
    if (!has(node, "title")) return;
    var before = R.commandTitle(Object.assign({}, node, { commandName: old }), model);
    if (node.title === before || node.title === R.splitName(node.name)) delete node.title;
  }

  // Тип значения поля - из реквизита по пути к данным (владелец): в панели элемента типа нет, конструктор
  // переносит тип и квалификаторы реквизита в данные рисования поля (`dataType`, `length`...) при смене пути и при
  // правке типа реквизита, как импорт. Путь не найден среди реквизитов - данные поля не трогаются

  var DERIVED = GROUPS.derived || [];
  var ATTR_TYPE_PROPS = { valueType: true, length: true, digits: true, fractionDigits: true, dateFractions: true };
  var SIMPLE_TYPES = { String: "string", Number: "number", Date: "date", Boolean: "boolean" };

  // Упрощенный тип поля: составной со ссылкой - ссылка, иначе первый известный (как `simple_type` импорта)
  function simpleType(names) {
    var kinds = names.map(function (name) {
      if (SIMPLE_TYPES[name]) return SIMPLE_TYPES[name];
      return /Ref(\.|$)/.test(name) ? "ref" : null;
    }).filter(Boolean);
    if (kinds.indexOf("ref") >= 0) return "ref";
    return kinds[0] || "string";
  }

  function mirrorField(node) {
    if (!node || node.type !== "InputField" || typeof node.dataPath !== "string") return;
    var entry = findEntry(attributeRoots(), node.dataPath);
    if (!entry) return;
    var source = entry.node;
    var names = typeNames(source);
    var values = { dataType: simpleType(names) };
    if (values.dataType === "string" && typeof source.length === "number") values.length = source.length;
    if (values.dataType === "number") {
      if (typeof source.digits === "number") values.digits = source.digits;
      if (typeof source.fractionDigits === "number") values.fractionDigits = source.fractionDigits;
    }
    if (values.dataType === "date" && source.dateFractions && source.dateFractions !== "DateTime") {
      values.dateFractions = source.dateFractions;
    }
    // Перечисление: значения - от сервера (serve --src), иначе прежние значения поля
    var single = names.length === 1 && /^EnumRef\.(.+)$/.exec(names[0]);
    if (single) {
      var found = (configTypes || []).filter(function (one) { return one.key === "Enum." + single[1]; })[0];
      if (found && Array.isArray(found.values) && found.values.length) values.enumValues = found.values;
      else if (Array.isArray(node.enumValues)) values.enumValues = node.enumValues;
    }
    DERIVED.forEach(function (prop) {
      if (has(values, prop)) setProp(node, prop, values[prop]);
      else delete node[prop];
    });
  }

  // Поля формы с путем к данному реквизиту
  function syncFields(attribute) {
    var roots = attributeRoots();
    (function visit(node, inColumn) {
      if (!node || typeof node !== "object") return;
      if (typeof node.dataPath === "string" && node.type !== "Table") {
        var entry = findEntry(roots, node.dataPath);
        if (entry && entry.node === attribute) {
          resetKind(node, inColumn);
          if (node.type === "InputField") mirrorField(node);
        }
      }
      var nested = inColumn || node.type === "Table";
      (Array.isArray(node.items) ? node.items : []).forEach(function (child) { visit(child, nested); });
    })(formOf(model), false);
  }

  // Квалификаторы не своего типа у реквизита - убрать: длина без строки, разрядность без числа и т.д.
  function trimQualifiers(node) {
    var names = typeNames(node);
    Object.keys(ATTR_BY_TYPE).forEach(function (prop) {
      if (names.indexOf(ATTR_BY_TYPE[prop]) < 0) delete node[prop];
    });
  }

  // Путь к данным таблицы сменился (владелец): колонки прежнего пути удаляются, пример строк тоже;
  // у нового пути есть реквизиты - окно предлагает заполнить колонки, как перетаскивание табличной части в 1С
  function tablePathChanged(item, old) {
    var node = item.node;
    var path = typeof node.dataPath === "string" ? node.dataPath : "";
    var removed = Array.isArray(node.items) ? node.items.length : 0;
    if (removed) {
      delete node.items;
      delete node.sample;
      changed();
    }
    var entry = path ? findEntry(attributeRoots(), path) : null;
    if (!entry || !fillMembers(entry).length) return;
    dialog = { kind: "columns", item: item, prop: "dataPath", path: path, old: old, removed: removed };
    renderDialog();
  }

  function renderColumnsOffer(body) {
    var entry = findEntry(attributeRoots(), dialog.path);
    var members = entry ? fillMembers(entry) : [];
    body.appendChild(h("div", "fe-dialog-note", dialog.removed
      ? "Путь к данным сменился на " + dialog.path + ": колонки прежнего пути удалены (" + dialog.removed + ")."
      : "Путь к данным таблицы: " + dialog.path + "."));
    body.appendChild(h("div", "", "Заполнить таблицу колонками реквизитов " + dialog.path + "?"));
    var list = h("div", "fe-pick fe-columns-offer");
    members.forEach(function (member) {
      var row = h("div", "fe-pick-row");
      row.dataset.path = member.path;
      row.appendChild(h("span", "fe-pick-name", STANDARD_NAMES[member.name] || member.name));
      var info = typeNames(member.node).map(typeTitle).join(", ");
      if (info) row.appendChild(h("span", "fe-pick-info", info));
      list.appendChild(row);
    });
    body.appendChild(list);
  }

  // Реквизиты для колонок: без СтандартнаяКартинка динамического списка - она путь картинки строки, а не колонка
  function fillMembers(entry) {
    return pathMembers(entry).filter(function (member) { return member.name !== "DefaultPicture"; });
  }

  // Колонка на реквизит: имя - имя таблицы и реквизита (`ТоварыНоменклатура`), как дает 1С; булево - флажком
  function fillColumns(item, path) {
    var node = item.node;
    var entry = findEntry(attributeRoots(), path);
    if (!entry) return;
    var names = collectNames(formOf(model));
    var columns = fillMembers(entry).map(function (member) {
      var base = node.name + (STANDARD_NAMES[member.name] || member.name);
      var name = base;
      for (var n = 1; names[name]; n++) name = base + n;
      names[name] = true;
      addedNames[name] = true;
      var types = typeNames(member.node);
      var column = { type: types.length === 1 && types[0] === "Boolean" ? "CheckBoxField" : "InputField", name: name,
        dataPath: member.path };
      inheritTitle(column, "");
      mirrorField(column);
      return column;
    });
    setProp(node, "items", columns, has(node, "commandBar") ? "commandBar" : undefined);
    changed();
  }

  // Командная панель по умолчанию и команда кнопки без описания становятся явными при первой правке
  function materialize(item) {
    if (!item.virtual) return;
    if (item.kind === "Command") {
      if (!Array.isArray(model.commands)) setRootProp("commands", []);
      model.commands.push(item.node);
    } else {
      setProp(item.owner, "commandBar", item.node);
    }
    item.virtual = false;
  }

  // Переименование элемента из «было» ставит renamedFrom (правки и render --before покажут переименование),
  // записанный не затирается, возврат прежнего имени его снимает; добавленным в конструкторе не ставится
  function rename(item, name) {
    var node = item.node;
    var old = node.name;
    node.name = name;
    if (typeof node.renamedFrom === "string") {
      if (node.renamedFrom === name) delete node.renamedFrom;
    } else if (baseNames && baseNames[old] && !addedNames[old]) {
      setProp(node, "renamedFrom", old, "name");
    }
    if (addedNames[old]) {
      delete addedNames[old];
      addedNames[name] = true;
    }
    var owner = item.parent && item.parent.node;
    if (node.type === "Page" && owner && owner.currentPage === old) owner.currentPage = name;
    if (folded[old]) {
      folded[name] = true;
      delete folded[old];
    }
  }

  // После правки выбран тот же узел модели, даже если сменилось имя (ключ дерева); правка - шаг истории отмены
  function changed() {
    if (batching) {
      batchChanged = true;
      return;
    }
    var current = entries[selected];
    var others = picked.map(function (key) { return entries[key]; }).filter(Boolean);
    buildTree();
    selected = (current && keyOf(current.node, current.tip)) || FORM_KEY;
    picked = others.map(function (one) { return keyOf(one.node, false); })
      .filter(function (key) { return key && key !== selected; });
    refresh();
    queueRecord();
  }

  // Перерисовка всего по модели: дерево уже построено, выбор поставлен
  function refresh() {
    fileUpdated = false;
    saveError = "";
    renderTree();
    if (leftMode === "attributes") {
      var attr = attrEntries[attrSelected];
      if (attr) reselectAttr(attr.node);
      else renderAttrTree();
    }
    if (leftMode === "commands") renderCommandTree();
    renderProps();
    if (rightTab === "notes" && !(document.activeElement && ui.notesBody.contains(document.activeElement))) renderNotes();
    else renderNoteCount();
    drawLayout();
    renderStatus();
    queueCheck();
  }

  // Отмена и повтор: шаг - текст модели до правки; все правки одного действия (смена пути таблицы и т.п.) -
  // один шаг: запись откладывается до конца задачи. История - с открытия или перечитывания файла, сохранение ее
  // не сбрасывает

  var undoStack = [];
  var redoStack = [];
  var stable = null;           // состояние после последней записанной правки: { text, added, selected }
  var recordQueued = false;

  function snapshot() {
    return { text: textOf(model), added: Object.assign({}, addedNames), selected: selected };
  }

  function resetHistory() {
    undoStack = [];
    redoStack = [];
    stable = snapshot();
    renderHistory();
  }

  function queueRecord() {
    if (recordQueued) return;
    recordQueued = true;
    Promise.resolve().then(record);
  }

  function record() {
    recordQueued = false;
    if (!model || !stable) return;
    var now = snapshot();
    if (now.text === stable.text) return;
    undoStack.push(stable);
    redoStack = [];
    stable = now;
    renderHistory();
  }

  function undo() { travel(undoStack, redoStack); }

  function redo() { travel(redoStack, undoStack); }

  function travel(from, to) {
    if (recordQueued) record();
    if (!from.length || !model) return;
    var step = from.pop();
    to.push(snapshot());
    closeDialog();
    closeMenu();
    model = JSON.parse(step.text);
    addedNames = Object.assign({}, step.added);
    invalid = {};
    invalidText = {};
    picked = [];
    var key = selected;
    buildTree();
    selected = entries[key] ? key : entries[step.selected] ? step.selected : FORM_KEY;
    stable = snapshot();
    refresh();
    renderHistory();
  }

  // Ctrl+Z, Ctrl+Shift+Z и Ctrl+Y (Cmd на Mac) - по физической клавише, при любой раскладке; в текстовом поле - его
  // собственная отмена набора, при открытом окне выбора - ничего
  function historyKey(event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    var redoKey = event.code === "KeyY" || (event.code === "KeyZ" && event.shiftKey);
    if (event.code !== "KeyZ" && !redoKey) return;
    var target = event.target;
    var typing = target && (target.tagName === "TEXTAREA" || target.tagName === "SELECT" ||
      (target.tagName === "INPUT" && target.type !== "checkbox"));
    if (typing || dialog) return;
    event.preventDefault();
    if (redoKey) redo();
    else undo();
  }

  function renderHistory() {
    if (!ui.undo) return;
    ui.undo.disabled = !undoStack.length;
    ui.redo.disabled = !redoStack.length;
  }

  // Правка структуры: добавление из палитры, перенос в дереве, удаление. Что куда кладется - по схеме
  // модели (`children` описания сервера: контейнер → виды его `items`), поля в таблице - без видов «недоступен
  // для полей, расположенных в таблице»

  var CHILDREN = ED.children || {};
  // Дополнение платформа заводит сама вместе с таблицей, нераспознанный элемент приходит только из импорта
  var NOT_IN_PALETTE = { Addition: true, Unknown: true };
  // Частые поля - сверху, редкие (документы, диаграммы, схемы, индикатор...) - в конце, чтобы не заслоняли группы
  var COMMON_FIELDS = ["InputField", "LabelField", "CheckBoxField", "RadioButtonField", "PictureField"];
  var PALETTE_SECTIONS = [
    ["Поля", COMMON_FIELDS],
    ["Группы", ["UsualGroup", "Pages", "Page", "ColumnGroup", "CommandBar", "ButtonGroup", "Popup"]],
    ["Таблица и декорации", ["Table", "LabelDecoration", "PictureDecoration"]],
    ["Кнопки", ["Button"]],
    ["Другие поля", null]
  ];
  // Имя нового элемента - по виду с номером, как в конфигураторе («Группа1», «Поле1», «Страница1», «Кнопка1»)
  var NAME_BASES = { UsualGroup: "Группа", Pages: "Группа", ColumnGroup: "Группа", CommandBar: "Группа",
    ButtonGroup: "Группа", Popup: "Подменю", Page: "Страница", Table: "Таблица", LabelDecoration: "Декорация",
    PictureDecoration: "Декорация", Button: "Кнопка" };
  var menuPlace = null;        // открытая палитра: место вставки
  var menuOwner = null;        // дерево открытого меню: туда возвращается фокус по Esc
  var dragKey = null;          // перетаскиваемый узел дерева
  var dropRow = null;          // строка с отметкой места вставки
  var dropAccepted = null;     // последнее перетаскивание принято - для сценариев теста

  function isField(kind) { return !!(KINDS[kind] || {}).type; }

  function isContainer(item) { return !!item && !item.tip && has(CHILDREN, item.kind); }

  function itemsOf(item) { return Array.isArray(item.node.items) ? item.node.items : []; }

  function accepts(container, kind) {
    if ((CHILDREN[container.kind] || []).indexOf(kind) < 0) return false;
    return !(NOT_IN_TABLE[kind] && (container.kind === "Table" || container.kind === "ColumnGroup"));
  }

  // Переносится и удаляется элемент `items`: не форма и не командная панель формы или таблицы (их свойство
  // `commandBar`); узел расширенной подсказки удаляется - это снять подсказку
  function movable(item) { return !!item && !item.tip && item.kind !== "Form" && !item.owner; }

  function deletable(item) { return !!item && (item.tip || movable(item)); }

  // Место вставки нового элемента: в выбранный контейнер, если он развернут в дереве (пустой - тоже; форма и
  // командная панель - всегда), иначе после выбранного
  function insertPlace() {
    var item = entries[selected] || tree;
    if (item.tip) item = item.parent;
    if (isContainer(item) && (item.kind === "Form" || item.owner || !folded[item.key] || !item.children.length)) {
      return { container: item, index: itemsOf(item).length, inside: true };
    }
    var parent = item.parent;
    return { container: parent, index: itemsOf(parent).indexOf(item.node) + 1, inside: false, after: item };
  }

  function paletteSections(container) {
    var allowed = (CHILDREN[container.kind] || []).filter(function (kind) {
      return !NOT_IN_PALETTE[kind] && accepts(container, kind);
    });
    return PALETTE_SECTIONS.map(function (section) {
      var kinds = section[1] ? section[1].filter(function (kind) { return allowed.indexOf(kind) >= 0; })
        : fieldOrder(allowed.filter(function (kind) { return isField(kind) && COMMON_FIELDS.indexOf(kind) < 0; }));
      return { title: section[0], kinds: kinds };
    }).filter(function (section) { return section.kinds.length; });
  }

  // Поля: частые - порядком «Вида» поля, остальные - по названию
  function fieldOrder(list) {
    var rank = function (kind) { var at = FIELD_KIND_ORDER.indexOf(kind); return at < 0 ? FIELD_KIND_ORDER.length : at; };
    return list.sort(function (a, b) {
      return rank(a) - rank(b) || kindTitle(a).localeCompare(kindTitle(b), "ru");
    });
  }

  // Палитра: под кнопкой «Добавить» или в точке `options.at`; `options.actions` - контекстное меню, сверху действия
  // над выбранным (удалить, вверх, вниз); `options.focus` - открыто с клавиатуры, фокус на первый пункт
  function openPalette(options) {
    if (!model) return;
    var at = options && options.at;
    var focus = options && options.focus;
    closeMenu();
    var menu = ui.menu;
    menu.innerHTML = "";
    // Несколько выделенных: в контекстном меню - только действия, «Добавить» сверху - у одного (выбранного)
    if (multiSelected()) {
      if (options && options.actions) {
        menuActions(menu);
        menu.appendChild(h("div", "fe-menu-note", "Добавить элемент - у одного выделенного"));
        menuOwner = ui.tree;
        var corner = ui.addButton.getBoundingClientRect();
        placeMenu(menu, at || { x: corner.left, y: corner.bottom + 4 }, focus);
        return;
      }
      select(selected);
    }
    menuPlace = insertPlace();
    if (options && options.actions) menuActions(menu);
    var target = menuPlace.inside ? menuPlace.container : menuPlace.after;
    var where = (options && options.actions ? "Добавить " : "") + (menuPlace.inside ? "в " : "после ");
    menu.appendChild(h("div", "fe-menu-note", where + "«" + (target.kind === "Form" ? "Форма" : target.label) + "»"));
    var sections = paletteSections(menuPlace.container);
    if (!sections.length) menu.appendChild(h("div", "fe-menu-note", "Сюда элементы не добавляются"));
    sections.forEach(function (section) {
      menu.appendChild(h("div", "fe-menu-head", section.title));
      section.kinds.forEach(function (kind) {
        var row = button("", function () { addElement(kind); }, "fe-menu-item");
        row.dataset.kind = kind;
        row.appendChild(treeIcon({ kind: kind }));
        row.appendChild(h("span", "", kindTitle(kind)));
        menu.appendChild(row);
      });
    });
    var anchor = ui.addButton.getBoundingClientRect();
    menuOwner = ui.tree;
    placeMenu(menu, at || { x: anchor.left, y: anchor.bottom + 4 }, focus);
  }

  // Меню в точке `at`, не за краем окна; `focus` - открыто с клавиатуры, фокус на первый доступный пункт
  function placeMenu(menu, at, focus) {
    menu.style.left = px(at.x);
    menu.style.top = px(at.y);
    menu.hidden = false;
    var box = menu.getBoundingClientRect();
    if (box.right > window.innerWidth - 4) menu.style.left = px(Math.max(4, window.innerWidth - box.width - 4));
    if (box.bottom > window.innerHeight - 4) menu.style.top = px(Math.max(4, window.innerHeight - box.height - 4));
    if (focus) {
      var first = menu.querySelector(".fe-menu-item:not(:disabled)");
      if (first) first.focus();
    }
  }

  // Контекстное меню закладок «Реквизиты» и «Команды» (владелец): действия кнопок над деревом у
  // курсора. `actions` - пункты `{action, text, key, off, add, run}`, `null` - черта; `owner` - дерево закладки.
  // Добавление ставит фокус на имя нового в панели свойств, остальное возвращает фокус в дерево
  function openListMenu(actions, at, owner) {
    closeMenu();
    var menu = ui.menu;
    menu.innerHTML = "";
    menuOwner = owner;
    actions.forEach(function (one) {
      if (!one) {
        menu.appendChild(h("div", "fe-menu-line"));
        return;
      }
      var row = button("", function () {
        closeMenu();
        one.run();
        if (!dialog && !one.add) owner.focus();
      }, "fe-menu-item fe-menu-action");
      row.dataset.action = one.action;
      row.appendChild(h("span", "fe-menu-text", one.text));
      row.appendChild(h("span", "fe-menu-key", one.key || ""));
      row.disabled = !!one.off;
      menu.appendChild(row);
    });
    var selectedRow = owner.querySelector(".fe-selected");
    var rect = (selectedRow || owner).getBoundingClientRect();
    placeMenu(menu, at || { x: rect.left + 24, y: selectedRow ? rect.bottom : rect.top + 4 }, !at);
  }

  // Клавиши закладок «Реквизиты» и «Команды», как в дереве элементов: Del и Backspace - удалить, Insert и
  // Shift+F10 - меню у выбранной строки (клавиша меню приходит событием `contextmenu`)
  function listKey(event, openMenu, remove) {
    if (event.key === "Delete" || event.key === "Backspace") remove();
    else if (event.key === "Insert" || event.key === "F10" && event.shiftKey) openMenu(null);
    else return false;
    event.preventDefault();
    return true;
  }

  // Правая кнопка по строке выбирает ее, по пустому месту - снимает выбор; с клавиатуры - у выбранной строки
  function listContext(event, select, openMenu) {
    event.preventDefault();
    var row = event.target.closest(".fe-row");
    var at = pointOf(event);
    if (row) select(row.dataset.key);
    else if (at) select(null);
    openMenu(at);
  }

  function menuActions(menu) {
    var item = entries[selected];
    var list = movable(item) ? itemsOf(item.parent) : [];
    var at = list.indexOf(item && item.node);
    // Несколько выделенных: удаление - всех, остальное - у одного
    var many = multiSelected();
    [["delete", many ? "Удалить выделенные (" + selection().length + ")" : "Удалить", "Del", deleteSelected,
      many ? !pickedDeletable().length : !deletable(item)],
      ["up", "Переместить вверх", "Alt+↑", function () { moveSibling(-1); }, at <= 0 || many],
      ["down", "Переместить вниз", "Alt+↓", function () { moveSibling(1); }, at < 0 || at >= list.length - 1 || many],
      ["note", "Примечание", "", function () { openNote(selected); }, !item || many]
    ].concat(fillable(item) && !many ? [["fill", "Заполнить стандартными командами", "", function () { fillStandard(item); },
      !standardFill(item).length]] : []).forEach(function (one) {
      var row = button("", function () {
        closeMenu();
        one[3]();
        if (!dialog && one[0] !== "note") ui.tree.focus();
      }, "fe-menu-item fe-menu-action");
      row.dataset.action = one[0];
      row.appendChild(h("span", "fe-menu-text", one[1]));
      row.appendChild(h("span", "fe-menu-key", one[2]));
      row.disabled = one[4];
      menu.appendChild(row);
    });
    menu.appendChild(h("div", "fe-menu-line"));
  }

  // Контекстное меню у строки дерева или элемента макета: сначала выбор, затем меню в точке курсора `at`. С
  // клавиатуры (клавиша меню, Shift+F10) точки нет - меню у выбранной строки, фокус на первом пункте
  function openContext(key, at, fromLayout) {
    if (!model) return;
    if (leftMode !== "items") setLeftMode("items");
    // По одному из нескольких выделенных - выделение остается, меню - для всех
    if (!(multiSelected() && selection().indexOf(key) >= 0)) select(entries[key] ? key : FORM_KEY, fromLayout);
    var row = ui.tree.querySelector(".fe-selected");
    var rect = !at && row ? row.getBoundingClientRect() : null;
    openPalette({ at: at || (rect && { x: rect.left + 24, y: rect.bottom }), focus: !at, actions: true });
  }

  // Точка курсора события `contextmenu`; с клавиатуры ее нет
  function pointOf(event) {
    return event.clientX || event.clientY ? { x: event.clientX, y: event.clientY } : null;
  }

  // Стрелки по пунктам меню; Esc - закрыть и вернуться в дерево
  function menuKey(event) {
    if (event.key === "Escape") {
      closeMenu();
      (menuOwner || ui.tree).focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    var rows = Array.prototype.filter.call(ui.menu.querySelectorAll(".fe-menu-item"), function (row) { return !row.disabled; });
    var at = rows.indexOf(document.activeElement);
    var next = at < 0 ? rows[0] : rows[(at + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length];
    if (next) next.focus();
  }

  function closeMenu() {
    menuPlace = null;
    if (ui.menu) ui.menu.hidden = true;
  }

  function freeName(base, names) {
    for (var n = 1; ; n++) {
      if (names[base + n]) continue;
      names[base + n] = true;
      addedNames[base + n] = true;
      return base + n;
    }
  }

  // Новый элемент; у «Страниц» сразу одна страница, у таблицы - одна колонка (правила `check` о пустых контейнерах);
  // у кнопки - вид по месту
  function newElement(kind, names, container) {
    var node = { type: kind, name: freeName(NAME_BASES[kind] || "Поле", names) };
    if (kind === "Pages") node.items = [{ type: "Page", name: freeName("Страница", names) }];
    if (kind === "Table") node.items = [{ type: "InputField", name: freeName("Поле", names) }];
    if (kind === "Button") node.buttonType = buttonTypeIn(container);
    return node;
  }

  // Кнопка в командной панели (в ней самой, в группе кнопок или подменю панели) - «Кнопка командной панели», на
  // форме и в группе - «Обычная кнопка», как дает конфигуратор
  function buttonTypeIn(container) {
    for (var up = container; up; up = up.parent) {
      if (up.kind === "AutoCommandBar" || up.kind === "CommandBar") return "CommandBarButton";
    }
    return "UsualButton";
  }

  // Имя элемента по имени реквизита или команды: свободное - как есть, занятое - с номером
  function nameLike(base, names) {
    var name = base;
    for (var n = 1; names[name]; n++) name = base + n;
    names[name] = true;
    addedNames[name] = true;
    return name;
  }

  function insertNode(container, index, node) {
    materialize(container);
    var owner = container.node;
    if (!Array.isArray(owner.items)) setProp(owner, "items", [], has(owner, "commandBar") ? "commandBar" : undefined);
    owner.items.splice(index, 0, node);
  }

  // Элемент уходит из контейнера: пустой `items` - из модели, текущая закладка «Страниц» - тоже, если закладка
  // уходит из них (`stays` - перенос внутри того же контейнера)
  function takeOut(item, stays) {
    var owner = item.parent.node;
    owner.items.splice(owner.items.indexOf(item.node), 1);
    if (!owner.items.length) delete owner.items;
    if (!stays && owner.type === "Pages" && owner.currentPage === item.node.name) delete owner.currentPage;
  }

  function addElement(kind) {
    var place = menuPlace || insertPlace();
    closeMenu();
    if (!place.container || !accepts(place.container, kind)) return;
    var node = newElement(kind, collectNames(formOf(model)), place.container);
    insertNode(place.container, place.index, node);
    changed();
    select(keyOf(node, false) || FORM_KEY);
    ui.tree.focus();
  }

  function nestedCount(item) {
    return item.children.reduce(function (sum, child) {
      return child.tip || child.virtual ? sum : sum + 1 + nestedCount(child);
    }, 0);
  }

  // Удаление выбранного с подчиненными; есть подчиненные - подтверждение со счетом
  function deleteSelected() {
    if (multiSelected()) {
      var items = pickedDeletable();
      if (!items.length) return;
      var nested = items.reduce(function (sum, one) { return sum + nestedCount(one); }, 0);
      if (nested) {
        dialog = { kind: "delete", items: items, item: items[0], count: nested };
        renderDialog();
        return;
      }
      removeItems(items);
      return;
    }
    var item = entries[selected];
    if (!deletable(item)) return;
    var count = item.tip ? 0 : nestedCount(item);
    if (count) {
      dialog = { kind: "delete", item: item, count: count };
      renderDialog();
      return;
    }
    removeItem(item);
  }

  // Выделенные, которые можно удалить; лежащий внутри другого выделенного уходит вместе с ним
  function pickedDeletable() {
    var items = selection().map(function (key) { return entries[key]; }).filter(deletable);
    return items.filter(function (one) {
      for (var up = one.parent; up; up = up.parent) {
        if (items.indexOf(up) >= 0) return false;
      }
      return true;
    });
  }

  function renderDeleteConfirm(body) {
    if (dialog.items) {
      body.appendChild(h("div", "", "Удалить выделенные элементы (" + dialog.items.length + ") вместе с подчиненными (" +
        dialog.count + ")?"));
      return;
    }
    body.appendChild(h("div", "", "Удалить «" + dialog.item.label + "» вместе с подчиненными элементами (" +
      dialog.count + ")?"));
  }

  // Удаление нескольких - одной правкой; выбор - сосед первого удаленного или его родитель
  function removeItems(items) {
    var first = items[0];
    var list = itemsOf(first.parent);
    var gone = items.map(function (one) { return one.node; });
    var at = list.indexOf(first.node);
    var next = list.slice(at + 1).concat(list.slice(0, at).reverse()).filter(function (node) {
      return gone.indexOf(node) < 0;
    })[0] || null;
    var parent = first.parent;
    items.forEach(function (one) { takeOut(one); });
    picked = [];
    changed();
    select((next && keyOf(next, false)) || keyOf(parent.node, false) || FORM_KEY);
    ui.tree.focus();
  }

  function removeItem(item) {
    if (item.tip) {
      delete item.node.extendedTooltip;
      selected = item.parent.key;
      changed();
      return;
    }
    var list = itemsOf(item.parent);
    var at = list.indexOf(item.node);
    var next = list[at + 1] || list[at - 1] || null;
    var parent = item.parent;
    takeOut(item);
    changed();
    select((next && keyOf(next, false)) || keyOf(parent.node, false) || FORM_KEY);
    ui.tree.focus();
  }

  // «Вверх» / «Вниз», Alt+стрелки - среди соседей
  function moveSibling(delta) {
    var item = entries[selected];
    if (!movable(item) || multiSelected()) return;
    var list = itemsOf(item.parent);
    var at = list.indexOf(item.node);
    var to = at + delta;
    if (at < 0 || to < 0 || to >= list.length) return;
    list.splice(at, 1);
    list.splice(to, 0, item.node);
    changed();
  }

  // Место переноса по строке под курсором: верх строки - перед ней, низ - после, середина контейнера - внутрь;
  // низ развернутого контейнера с подчиненными - внутрь первым. Итог - null, если туда нельзя: вид не принимается,
  // перенос в себя или в свои подчиненные
  function dropPlace(source, target, zone) {
    var place = source ? placeAt(target, zone) : null;
    if (!place || !accepts(place.container, source.node.type)) return null;
    for (var up = place.container; up; up = up.parent) {
      if (up.node === source.node) return null;
    }
    return place;
  }

  // Контейнер и позиция по строке цели, без проверки вида
  function placeAt(target, zone) {
    if (!target || target.tip) return null;
    var container, index;
    if (target.kind === "Form" || target.owner) zone = "inside";
    if (zone === "after" && isContainer(target) && target.children.length && !folded[target.key]) zone = "first";
    if (zone === "inside" || zone === "first") {
      container = target;
      index = zone === "first" ? 0 : itemsOf(target).length;
    } else {
      container = target.parent;
      index = itemsOf(container).indexOf(target.node) + (zone === "after" ? 1 : 0);
    }
    if (!isContainer(container)) return null;
    return { container: container, index: index, zone: zone === "first" ? "inside" : zone };
  }

  // Реквизит и команда на форму перетаскиванием: строка закладки «Реквизиты» или «Команды»
  // становится новым элементом. Дерево элементов в той же колонке, что закладки: курсор с реквизитом над
  // переключателем «Элементы» открывает дерево. Бросок на макет - тоже: место по элементу под курсором
  var dragNew = null;          // перетаскиваемое с закладки: { attr: узел дерева реквизитов } или { command: имя }

  // Таблица, в которую попадает элемент контейнера `container`: сама таблица или таблица группы колонок
  function tableAround(container) {
    for (var up = container; up; up = up.parent) {
      if (up.kind === "Table") return up;
    }
    return null;
  }

  // Ближайшая коллекция над реквизитом (табличная часть, таблица значений): реквизит внутри нее - колонка
  function collectionAbove(attr) {
    for (var up = attr.parent; up; up = up.parent) {
      if (isCollection(up.node)) return up;
    }
    return null;
  }

  // Вид поля по реквизиту, как в конфигураторе: булево - флажок, картинка (тип «Картинка», двоичные данные, строка
  // с картинкой в имени - путь к ней) - поле картинки, прочее - первый допустимый (поле ввода); вида поля нет
  // (объект, набор записей) - null
  var PICTURE_NAME = /картинк|изображен|picture|image/i;

  function droppedFieldKind(attr, inTable) {
    var names = typeNames(attr.node);
    var list = allowedKinds({ dataPath: attr.path }, inTable);
    var only = function (type) { return names.length > 0 && names.every(function (name) { return name === type; }); };
    if (only("BinaryData")) return "PictureField";
    if (!list.length) return null;
    if (only("Boolean") && list.indexOf("CheckBoxField") >= 0) return "CheckBoxField";
    var picture = only("Picture") || (only("String") && PICTURE_NAME.test(attr.node.name || ""));
    if (picture && list.indexOf("PictureField") >= 0) return "PictureField";
    return list[0];
  }

  // Новый элемент для места `container` (без имени); null - сюда нельзя: колонка вне своей таблицы, реквизит не
  // колонкой - в таблицу, тип без вида поля
  function droppedNode(container) {
    if (dragNew.command) {
      return { type: "Button", buttonType: buttonTypeIn(container), commandName: COMMAND_PREFIX + dragNew.command };
    }
    var attr = dragNew.attr;
    var table = tableAround(container);
    var rows = collectionAbove(attr);
    if (table ? !rows || table.node.dataPath !== rows.path : !!rows) return null;
    if (!rows && isCollection(attr.node)) return { type: "Table", dataPath: attr.path };
    var kind = droppedFieldKind(attr, !!table);
    return kind ? { type: kind, dataPath: attr.path } : null;
  }

  function newDropPlace(target, zone) {
    var place = placeAt(target, zone);
    var node = place ? droppedNode(place.container) : null;
    if (!node || !accepts(place.container, node.type)) return null;
    place.node = node;
    return place;
  }

  // Бросок с закладки: имя - имя реквизита или команды (колонка - имя таблицы и реквизита, как при заполнении
  // колонок), заголовок и тип поля - от реквизита; таблица - сразу окно «заполнить колонками», как при смене пути
  function dropNew(place) {
    var attr = dragNew.attr;
    var names = collectNames(formOf(model));
    var base = attr ? STANDARD_NAMES[attr.node.name] || attr.node.name : dragNew.command;
    var table = attr ? tableAround(place.container) : null;
    var fresh = Object.assign({ type: place.node.type, name: nameLike(table ? table.node.name + base : base, names) },
      place.node);
    if (attr) {
      inheritTitle(fresh, "");
      mirrorField(fresh);
    }
    insertNode(place.container, place.index, fresh);
    changed();
    select(keyOf(fresh, false) || FORM_KEY);
    ui.tree.focus();
    var entry = fresh.type === "Table" ? findEntry(attributeRoots(), fresh.dataPath) : null;
    if (entry && fillMembers(entry).length) {
      dialog = { kind: "columns", item: entries[selected], prop: "dataPath", path: fresh.dataPath, old: "", removed: 0 };
      renderDialog();
    }
  }

  // Строки закладок «Реквизиты» и «Команды» - источник переноса
  function setupNewDrag(box, sourceOf) {
    box.addEventListener("dragstart", function (event) {
      var row = event.target.closest ? event.target.closest(".fe-row") : null;
      var source = row ? sourceOf(row) : null;
      if (!source) {
        event.preventDefault();
        return;
      }
      dragNew = source;
      dragKey = null;
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("text/plain", row.querySelector(".fe-label").textContent);
    });
    box.addEventListener("dragend", endNewDrag);
  }

  function endNewDrag() {
    dragNew = null;
    markDrop(null);
    markCanvas(null);
  }

  // Бросок на макет: цель - элемент под курсором, место - ближняя к курсору сторона по оси его ряда
  // (соседи стоят рядом - ось X, друг под другом - Y); у контейнера середина - внутрь, кромка - до или после.
  // Мимо элементов, но на окне формы - в конец формы. Удаленный или тень правок - не цель
  var CANVAS_EDGE = 8;         // px кромки контейнера: ближе к краю - до или после, дальше - внутрь

  function canvasElement(name) {
    return ui.center.querySelector('#fm-root .fm-item[data-name="' + CSS.escape(name) + '"]');
  }

  function canvasAxis(target, element) {
    var list = itemsOf(target.parent);
    var at = list.indexOf(target.node);
    var near = list[at - 1] || list[at + 1];
    var other = near && near.name ? canvasElement(near.name) : null;
    if (other && other.getClientRects().length) {
      var one = element.getBoundingClientRect();
      var two = other.getBoundingClientRect();
      var overlap = Math.min(one.bottom, two.bottom) - Math.max(one.top, two.top);
      return overlap > Math.min(one.height, two.height) / 2 ? "x" : "y";
    }
    return /CommandBar$|^ButtonGroup$|^Table$|^ColumnGroup$/.test(target.parent.kind) ? "x" : "y";
  }

  function canvasZone(event, element, target, axis) {
    var rect = element.getBoundingClientRect();
    var from = axis === "x" ? event.clientX - rect.left : event.clientY - rect.top;
    var size = Math.max(1, axis === "x" ? rect.width : rect.height);
    if (isContainer(target)) return from < CANVAS_EDGE ? "before" : from > size - CANVAS_EDGE ? "after" : "inside";
    return from < size / 2 ? "before" : "after";
  }

  function canvasPlace(event) {
    var root = ui.center.querySelector("#fm-root");
    if (!root || !root.contains(event.target)) return null;
    var tab = event.target.closest(".fm-tab[data-page]");
    var element = tab || event.target.closest(".fm-item[data-name]");
    var target = element ? entries[tab ? tab.dataset.page : element.dataset.name] : entries[FORM_KEY];
    if (!target || target.tip) return null;
    if (!element || target.kind === "Form") element = root;
    var axis = target.parent ? canvasAxis(target, element) : "y";
    var zone = tab || target.kind === "Form" || target.owner ? "inside" : canvasZone(event, element, target, axis);
    var container = zone === "inside" ? target : target.parent;
    if (!isContainer(container)) return null;
    var index = zone === "inside" ? itemsOf(target).length : itemsOf(container).indexOf(target.node) + (zone === "after" ? 1 : 0);
    var node = droppedNode(container);
    if (!node || !accepts(container, node.type)) return null;
    return { container: container, index: index, zone: zone, node: node, element: element, axis: axis };
  }

  function markCanvas(place) {
    var mark = ui.canvasDrop;
    if (!mark) return;
    mark.hidden = !place;
    if (!place) return;
    var rect = place.element.getBoundingClientRect();
    var line = place.zone !== "inside";
    var edge = place.zone === "before" ? 0 : 1;
    var x = place.axis === "x" && line;
    var y = place.axis !== "x" && line;
    mark.className = "fe-canvas-drop" + (line ? "" : " fe-canvas-drop-inside");
    mark.style.left = (x ? rect.left + rect.width * edge - 1.5 : rect.left) + "px";
    mark.style.top = (y ? rect.top + rect.height * edge - 1.5 : rect.top) + "px";
    mark.style.width = (x ? 3 : rect.width) + "px";
    mark.style.height = (y ? 3 : rect.height) + "px";
  }

  function setupCanvasDrop() {
    ui.canvasDrop = h("div", "fe-canvas-drop");
    ui.canvasDrop.hidden = true;
    document.body.appendChild(ui.canvasDrop);
    ui.center.addEventListener("dragover", function (event) {
      if (!dragNew || blocked) return;
      var place = canvasPlace(event);
      markCanvas(place);
      if (!place) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    ui.center.addEventListener("dragleave", function (event) {
      if (!ui.center.contains(event.relatedTarget)) markCanvas(null);
    });
    ui.center.addEventListener("drop", function (event) {
      var place = dragNew && !blocked ? canvasPlace(event) : null;
      markCanvas(null);
      dropAccepted = !!place;
      if (!place) return;
      event.preventDefault();
      dropNew(place);
      dragNew = null;
    });
  }

  function dragZone(event, row, target) {
    var rect = row.getBoundingClientRect();
    var y = (event.clientY - rect.top) / Math.max(1, rect.height);
    if (isContainer(target)) return y < 0.25 ? "before" : y > 0.75 ? "after" : "inside";
    return y < 0.5 ? "before" : "after";
  }

  function dragPlace(event) {
    var row = event.target && event.target.closest ? event.target.closest(".fe-row") : null;
    var target = row && entries[row.dataset.key];
    if (!target) return null;
    var zone = dragZone(event, row, target);
    var place = dragNew ? newDropPlace(target, zone) : dropPlace(entries[dragKey], target, zone);
    if (place) place.row = row;
    return place;
  }

  function markDrop(place) {
    if (dropRow) dropRow.classList.remove("fe-drop-before", "fe-drop-after", "fe-drop-inside");
    dropRow = place ? place.row : null;
    if (dropRow) dropRow.classList.add("fe-drop-" + place.zone);
  }

  function moveNode(source, place) {
    var same = place.container.node === source.parent.node;
    var index = place.index;
    var at = itemsOf(source.parent).indexOf(source.node);
    if (same && at < index) index--;
    if (same && at === index) return;
    takeOut(source, same);
    insertNode(place.container, index, source.node);
    changed();
    select(keyOf(source.node, false) || FORM_KEY);
  }

  function setupDrag() {
    ui.tree.addEventListener("dragstart", function (event) {
      var row = event.target.closest ? event.target.closest(".fe-row") : null;
      var item = row && entries[row.dataset.key];
      if (!movable(item)) {
        event.preventDefault();
        return;
      }
      dragKey = item.key;
      picked = [];                 // переносится один элемент - тот, что тянут
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.node.name || "");
    });
    ui.tree.addEventListener("dragover", function (event) {
      if (!dragKey && !dragNew) return;
      var place = dragPlace(event);
      markDrop(place);
      if (!place) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = dragNew ? "copy" : "move";
    });
    ui.tree.addEventListener("dragleave", function (event) {
      if (!ui.tree.contains(event.relatedTarget)) markDrop(null);
    });
    ui.tree.addEventListener("drop", function (event) {
      var place = dragKey || dragNew ? dragPlace(event) : null;
      var source = entries[dragKey];
      markDrop(null);
      dropAccepted = !!place;
      if (place) event.preventDefault();
      if (place && dragNew) dropNew(place);
      else if (place) moveNode(source, place);
      dragKey = null;
      dragNew = null;
    });
    ui.tree.addEventListener("dragend", function () {
      dragKey = null;
      markDrop(null);
    });
    // Реквизит или команда над переключателем «Элементы» - открыть дерево элементов
    ui.leftItems.addEventListener("dragenter", function () {
      if (dragNew && leftMode !== "items") setLeftMode("items");
    });
    ui.leftItems.addEventListener("dragover", function (event) {
      if (dragNew) event.preventDefault();
    });
    setupNewDrag(ui.attrTree, function (row) {
      var attr = attrEntries[row.dataset.key];
      return attr ? { attr: attr } : null;
    });
    setupNewDrag(ui.cmdTree, function (row) {
      return row.dataset.name ? { command: row.dataset.name } : null;
    });
    // Источник скрыт сменой закладки - его `dragend` может не дойти: перенос кончается с любым следующим нажатием
    document.addEventListener("mousedown", function () { if (dragNew) endNewDrag(); });
  }

  function renderItemTools() {
    if (!ui.itemTools) return;
    var item = entries[selected];
    var list = movable(item) ? itemsOf(item.parent) : [];
    var at = list.indexOf(item && item.node);
    ui.addButton.disabled = !model;
    ui.deleteButton.disabled = multiSelected() ? !pickedDeletable().length : !deletable(item);
    // Перенос нескольких - не сейчас (владелец 07.11.2026): «Вверх» и «Вниз» - у одного выделенного
    ui.upButton.disabled = at <= 0 || multiSelected();
    ui.downButton.disabled = at < 0 || at >= list.length - 1 || multiSelected();
  }

  // Макет: модель с блокирующими замечаниями не рисуется - вместо макета их список

  function drawLayout() {
    ui.blocked.hidden = !blocked;
    if (blocked) {
      R.clear();
      renderIssueRows(ui.blockedList, issues.filter(function (issue) { return issue.blocking; }));
      return;
    }
    var start = performance.now();
    try {
      R.update(model, pictures, diffOfLayout());
    } catch (error) {
      errors.push(String(error && error.stack || error));
    }
    renderMs = Math.round(performance.now() - start);
  }

  function renderIssueRows(box, list) {
    box.innerHTML = "";
    list.forEach(function (issue) {
      var row = h("div", "fe-issue" + (issue.blocking ? " fe-issue-blocking" : ""));
      row.appendChild(h("span", "fe-issue-path", issue.path || issue.where));
      var text = h("span", "fe-issue-text", issue.message);
      text.appendChild(h("span", "fe-issue-code", issue.code));
      row.appendChild(text);
      row.addEventListener("click", function () {
        ui.issueList.hidden = true;
        select(entries[issue.name] ? issue.name : FORM_KEY);
      });
      box.appendChild(row);
    });
  }

  // Сервер: проверка, чтение, запись, слежение за файлом

  var checkTimer = null;
  var checkSeq = 0;
  var checking = null;

  function queueCheck() {
    clearTimeout(checkTimer);
    checking = new Promise(function (resolve) {
      checkTimer = setTimeout(function () { runCheck().then(resolve); }, CHECK_DELAY);
    });
  }

  async function runCheck() {
    var seq = ++checkSeq;
    try {
      var body = textOf(model);
      // Объединенное дерево правок - только при включенных «Правках»: оно размером с форму
      var response = await fetch(modelUrl("/check" + (diffOn ? "?tree=1" : "")),
        { method: "POST", headers: { "Content-Type": "application/json" }, body: body });
      var data = await response.json();
      online = true;
      if (data.folderChanged) {
        folderLost(data);
        return;
      }
      if (seq !== checkSeq) return;
      var redraw = takeIssues(data.issues, data.pictures);
      if (takeChanges(data.changes, data.tree, body)) redraw = true;
      if (redraw) drawLayout();
      renderStatus();
    } catch (error) {
      online = false;
      renderStatus();
    }
  }

  // Правки против «было» от сервера; итог - надо ли перерисовать макет
  function takeChanges(list, tree, text) {
    var was = textOf({ changes: changes, tree: diffOn ? diffTree : null });
    changes = Array.isArray(list) ? list : null;
    diffTree = tree || null;
    diffText = tree ? text : null;
    if (activeChange && !changeByNumber(activeChange)) activeChange = 0;
    renderDiffCount();
    if (!diffOn) return false;
    if (textOf({ changes: changes, tree: diffTree }) !== was) {
      renderTree();
      renderChanges();
      // Панель свойств - только если отметки у выбранного сменились и пользователь не набирает в ней
      var typing = document.activeElement && ui.propsBody.contains(document.activeElement);
      if (!typing && propsDiffKey(currentItem()) !== propsDiffShown) renderProps();
    }
    // Макет после правки нарисован без объединенного дерева - теперь оно есть
    return true;
  }

  // Правки для рендерера: дерево - только посчитанное по этой модели, иначе форма модели с отметками по именам
  function diffOfLayout() {
    if (!diffOn || !changes) return null;
    return { changes: changes, tree: diffTree && diffText === textOf(model) ? diffTree : null };
  }

  // Правки против «было»: переключатель, закладка «Правки», отметки в дереве и панели свойств

  // `quiet` - при первом чтении: дерево и макет нарисует сам load
  function setDiffOn(on, quiet) {
    diffOn = on;
    if (ui.diffToggle) ui.diffToggle.checked = on;
    if (!on) {
      if (rightTab === "changes") rightTab = "props";
      activeChange = 0;
    }
    renderDiffCount();
    renderRightTab();
    if (quiet || !model) return;
    renderTree();
    renderProps();
    drawLayout();
    // Объединенное дерево сервер отдает только по просьбе - при включении его еще нет
    if (on) queueCheck();
  }

  function renderDiffCount() {
    if (!ui.diffLabel) return;
    ui.diffLabel.textContent = "Правки" + (changes ? " (" + changes.length + ")" : "");
    ui.diffLabel.parentNode.title = "Правки против «было»: " + (baseFile || "файл на запуске конструктора") +
      (changes ? "" : " - не посчитаны, пока у модели блокирующие замечания");
    if (ui.tabChanges) ui.tabChanges.textContent = "Правки" + (changes ? " (" + changes.length + ")" : "");
  }

  function changeByNumber(number) {
    return (changes || []).filter(function (change) { return change.n === number; })[0] || null;
  }

  // Правка элемента дерева: по имени в «стало»; у расширенной подсказки своей правки нет
  function changeOfItem(item) {
    if (!diffOn || !changes || !item || item.tip || leftMode !== "items") return null;
    var name = item.key === FORM_KEY ? FORM_KEY : item.node.name;
    return changes.filter(function (change) { return change.op !== "removed" && change.after === name; })[0] || null;
  }

  // Измененные свойства выбранного элемента: свойство → { before } (нет `before` - в «было» свойства не было)
  function propDiffs(item) {
    var change = changeOfItem(item);
    var result = {};
    ((change && change.props) || []).forEach(function (entry) { result[entry.prop] = entry; });
    return result;
  }

  function propsDiffKey(item) {
    var change = changeOfItem(item);
    return change ? textOf([change.n, change.what, change.props]) : "";
  }

  // Удаленные элементы - строками на старых местах: родитель → [{ after: ключ соседа выше или null, change }].
  // Место - по объединенному дереву (последнему посчитанному): ближайший сосед выше, который есть в модели
  function removedPlaces() {
    var places = {};
    if (!diffOn || !changes || !diffTree) return places;
    var removed = {};
    changes.forEach(function (change) { if (change.op === "removed") removed[change.before] = change; });
    (function visit(node, parentKey) {
      var slots = [];
      if (node.commandBar) slots.push(node.commandBar);
      (Array.isArray(node.items) ? node.items : []).forEach(function (item) { if (item && typeof item === "object") slots.push(item); });
      var before = null;
      slots.forEach(function (child) {
        var change = removed[child.name];
        if (change) {
          (places[parentKey] = places[parentKey] || []).push({ after: before, change: change });
          return;
        }
        if (entries[child.name]) {
          before = child.name;
          visit(child, child.name);
        }
      });
    })(diffTree, FORM_KEY);
    return places;
  }

  function diffBadge(change, op) {
    var badge = h("span", "fe-diff-n fm-diff-badge fm-diff-" + (op || change.op), String(change.n));
    badge.title = change.what;
    return badge;
  }

  function removedRow(place, depth) {
    var change = place.change;
    var row = h("div", "fe-row fe-row-removed");
    row.dataset.removed = change.before;
    row.dataset.change = change.n;
    row.style.paddingLeft = px(4 + depth * 16);
    if (change.n === activeChange) row.classList.add("fe-change-current");
    row.title = "Удален: " + change.details.join("; ");
    row.appendChild(twistyOf(false, false));
    row.appendChild(treeIcon({ kind: change.kind }));
    row.appendChild(h("span", "fe-label", change.before));
    row.appendChild(diffBadge(change));
    return row;
  }

  // Закладки правой колонки: «Свойства», «Примечания» и «Правки» (видна при включенных правках)
  function renderRightTab() {
    if (!ui.rightTabs) return;
    if (!diffOn && rightTab === "changes") rightTab = "props";
    ui.tabChanges.hidden = !diffOn;
    ui.tabProps.classList.toggle("fe-mode-on", rightTab === "props");
    ui.tabNotes.classList.toggle("fe-mode-on", rightTab === "notes");
    ui.tabChanges.classList.toggle("fe-mode-on", rightTab === "changes");
    ui.propsHead.hidden = rightTab !== "props";
    ui.propsBody.hidden = rightTab !== "props";
    ui.notesBody.hidden = rightTab !== "notes";
    ui.changesBody.hidden = rightTab !== "changes";
    if (rightTab === "changes") renderChanges();
    if (rightTab === "notes") renderNotes();
    else renderNoteCount();
  }

  function setRightTab(tab) {
    rightTab = tab;
    renderRightTab();
    if (tab === "props") renderProps();
  }

  // Примечания: элементы с `note` порядком дерева - тем же, что у рендерера (`noteList`) и `table`; номер на
  // макете рисует рендерер, при включенных правках - нет. Строка пункта меню «Примечание» у элемента без примечания -
  // пустая, без номера, на месте элемента в дереве

  function noteRows() {
    var rows = [];
    var number = 0;
    if (!tree) return rows;
    (function visit(item) {
      var text = typeof item.node.note === "string" ? item.node.note : "";
      if (!item.tip && (text.trim() || item.key === noteDraft)) {
        rows.push({ key: item.key, item: item, n: text.trim() ? ++number : 0, text: text });
      }
      item.children.forEach(visit);
    })(tree);
    return rows;
  }

  function renderNoteCount() {
    if (!ui.tabNotes || !model) return;
    var count = noteRows().filter(function (row) { return row.n; }).length;
    ui.tabNotes.textContent = "Примечания" + (count ? " (" + count + ")" : "");
  }

  function renderNotes() {
    var box = ui.notesBody;
    if (!box || rightTab !== "notes" || !model) return;
    box.innerHTML = "";
    var rows = noteRows();
    renderNoteCount();
    if (diffOn) box.appendChild(h("div", "fe-props-note", "Номера на макете не рисуются, пока включены «Правки»"));
    if (!rows.length) {
      box.appendChild(h("div", "fe-props-note", "Примечаний нет. Примечание - свойство «Примечание для ТЗ» (группа «Макет») или пункт «Примечание» контекстного меню элемента"));
      return;
    }
    rows.forEach(function (row) {
      var line = h("div", "fe-note" + (row.key === selected ? " fe-note-current" : ""));
      line.dataset.key = row.key;
      var head = h("div", "fe-change-head");
      head.appendChild(h("span", "fe-diff-n fm-diff-badge fm-diff-note", row.n ? String(row.n) : "+"));
      head.appendChild(h("span", "fe-change-title", row.item.kind === "Form" ? "Форма" : R.titleOf(row.item.node, model) || row.item.label));
      head.appendChild(h("span", "fe-change-what", row.item.kind === "Form" ? "" : row.item.node.name || ""));
      line.appendChild(head);
      var text = h("textarea", "fe-note-text");
      text.rows = 2;
      text.value = row.text;
      text.placeholder = "Текст примечания для ТЗ";
      text.dataset.key = row.key;
      text.addEventListener("change", function () { setNote(row.key, text.value); });
      text.addEventListener("blur", function () {
        // Пустая строка из меню без текста - убрать
        if (noteDraft === row.key && !text.value.trim()) {
          noteDraft = null;
          renderNotes();
        }
      });
      line.appendChild(text);
      line.addEventListener("click", function (event) {
        if (event.target === text) return;
        if (leftMode !== "items") setLeftMode("items");
        select(row.key);
        renderNotes();
      });
      box.appendChild(line);
    });
    var current = box.querySelector(".fe-note-current");
    if (current) current.scrollIntoView({ block: "nearest" });
  }

  // Текст из списка: пустой снимает примечание; правка - как в панели свойств (отмена, проверка, запись)
  function setNote(key, value) {
    var item = entries[key];
    if (!item) return;
    if (noteDraft === key) noteDraft = null;
    var text = value.replace(/\s+$/, "");
    apply(item, "note", text.trim() ? text : undefined);
    renderNotes();
  }

  // Пункт «Примечание» контекстного меню: закладка «Примечания» на строке элемента, фокус в текст
  function openNote(key) {
    var item = entries[key];
    if (!item) return;
    if (item.tip) key = item.parent.key;
    var text = typeof entries[key].node.note === "string" ? entries[key].node.note : "";
    noteDraft = text.trim() ? null : key;
    rightTab = "notes";
    renderRightTab();
    var field = ui.notesBody.querySelector('.fe-note-text[data-key="' + key + '"]');
    if (field) field.focus();
  }

  // Список правок, как у `render`: номер, элемент, что сделано, подробности; щелчок - к элементу
  function renderChanges() {
    var box = ui.changesBody;
    if (!box || rightTab !== "changes") return;
    box.innerHTML = "";
    if (!changes) {
      box.appendChild(h("div", "fe-props-note", "Правки не посчитаны: у модели блокирующие замечания"));
      return;
    }
    box.appendChild(h("div", "fe-props-note", "Против «было»: " + (baseFile || "файл на запуске конструктора")));
    if (!changes.length) box.appendChild(h("div", "fe-props-note", "Формы не различаются"));
    changes.forEach(function (change) {
      var item = h("div", "fe-change");
      item.dataset.change = change.n;
      if (change.n === activeChange) item.classList.add("fe-change-current");
      var head = h("div", "fe-change-head");
      head.appendChild(diffBadge(change));
      head.appendChild(h("span", "fe-change-title", change.title));
      head.appendChild(h("span", "fe-change-what", change.what));
      item.appendChild(head);
      var name = change.op === "removed" ? change.before : change.after;
      item.appendChild(h("div", "fe-change-name", name + " - " + kindTitle(change.kind)));
      change.details.forEach(function (detail) { item.appendChild(h("div", "fe-change-detail", detail)); });
      item.addEventListener("click", function () { showChange(change.n); });
      box.appendChild(item);
    });
    var current = box.querySelector(".fe-change-current");
    if (current) current.scrollIntoView({ block: "nearest" });
  }

  // Правка выбрана: элемент «стало» - выбор в дереве и на макете; удаленный - показан на макете на старом месте
  function showChange(number, openList) {
    var change = changeByNumber(number);
    if (!change) return;
    activeChange = number;
    if (openList && rightTab !== "changes") {
      rightTab = "changes";
      renderRightTab();
    }
    if (change.op !== "removed" && entries[change.after]) {
      if (leftMode !== "items") setLeftMode("items");
      select(change.after);
    } else {
      renderTree();
      if (!blocked && R.reveal(change.before)) drawLayout();
      var element = blocked ? null : R.element(change.before);
      if (element) R.partsOf(element)[0].scrollIntoView({ block: "center", inline: "nearest" });
    }
    renderChanges();
    R.setActiveChange(number);
  }

  // «Вернуть как было»: значение из «было» или свойство убирается, если его там не было
  function revertButton(item, prop, entry) {
    var button = h("button", "fe-in fe-revert", "↺");
    button.type = "button";
    button.tabIndex = -1;
    button.dataset.prop = prop;
    button.title = "Вернуть как было: " + (has(entry, "before") ? valueText(entry.before) : "не задано");
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () {
      apply(item, prop, has(entry, "before") ? JSON.parse(textOf(entry.before)) : undefined);
    });
    return button;
  }

  function valueText(value) {
    if (typeof value === "boolean") return value ? "Да" : "Нет";
    return typeof value === "string" ? "«" + value + "»" : textOf(value);
  }

  // Замечания и картинки от сервера; итог - надо ли перерисовать макет
  function takeIssues(list, found) {
    issues = list || [];
    var fresh = Object.keys(found || {}).some(function (name) { return !has(pictures, name); });
    Object.assign(pictures, found || {});
    var was = blocked;
    blocked = issues.some(function (issue) { return issue.blocking; });
    renderIssueRows(ui.issueRows, issues);
    return blocked || was !== blocked || fresh;
  }

  function setIssues(list, found) {
    if (takeIssues(list, found)) drawLayout();
    renderStatus();
  }

  async function load(updated) {
    var response, data;
    try {
      response = await fetch(modelUrl("/model"), { cache: "no-store" });
      data = await response.json();
    } catch (error) {
      online = false;
      renderStatus();
      return false;
    }
    online = true;
    if (data.folderChanged) {
      folderLost(data);
      return false;
    }
    var etag = response.headers.get("ETag");
    if (!response.ok) {
      unreadable = data.error || "файл не читается";
      if (etag) diskEtag = etag;
      renderStatus();
      return false;
    }
    unreadable = "";
    conflict = false;
    keepEtag = null;
    invalid = {};
    invalidText = {};
    saveError = "";
    model = data.model;
    savedText = textOf(model);
    baseEtag = diskEtag = etag;
    // «Было» у сервера одно на всю работу: имена и включение «Правок» - с первого чтения
    if (!baseNames) {
      var base = data.base || {};
      baseNames = {};
      (base.names || []).forEach(function (name) { baseNames[name] = true; });
      baseFile = base.file || null;
      setDiffOn(!!baseFile, true);
    }
    addedNames = {};
    fileUpdated = !!updated;
    closeMenu();
    buildTree();
    if (!entries[selected]) selected = FORM_KEY;
    resetHistory();
    renderTree();
    renderProps();
    takeIssues(data.issues, data.pictures);
    drawLayout();
    renderStatus();
    // Правки против «было» приходят с проверкой
    queueCheck();
    return true;
  }

  var polling = false;
  async function poll() {
    if (polling || movedFolder) return;
    polling = true;
    try {
      var data;
      try {
        var response = await fetch(modelUrl("/version"), { cache: "no-store" });
        data = await response.json();
      } catch (error) {
        if (online) {
          online = false;
          renderStatus();
        }
        return;
      }
      if (!online) {
        online = true;
        renderStatus();
      }
      if (data.folderChanged) {
        folderLost(data);
        return;
      }
      if (data.etag === diskEtag) return;
      diskEtag = data.etag;
      if (data.etag === baseEtag) {
        conflict = false;
        renderStatus();
      } else if (!dirty()) {
        await load(true);
      } else if (data.etag !== keepEtag) {
        conflict = true;
        renderStatus();
      }
    } finally {
      polling = false;
    }
  }

  async function save() {
    if (!model || !online || movedFolder) return;
    if (blocked) {
      saveError = "есть блокирующие замечания - сохранение после исправления";
      renderStatus();
      return;
    }
    var body = textOf(model);
    var response, data;
    try {
      response = await fetch(modelUrl("/model"), { method: "PUT", headers: { "Content-Type": "application/json", "If-Match": baseEtag || "-" }, body: body });
      data = await response.json();
    } catch (error) {
      online = false;
      saveError = "нет связи с сервером - правки не сохранены";
      renderStatus();
      return;
    }
    if (response.ok) {
      baseEtag = diskEtag = response.headers.get("ETag");
      savedText = body;
      saveError = "";
      conflict = false;
      keepEtag = null;
      unreadable = "";
      setIssues(data.issues);
    } else if (data.folderChanged) {
      folderLost(data);
      return;
    } else if (response.status === 409) {
      diskEtag = data.etag;
      conflict = true;
      saveError = "файл изменён на диске - не сохранено";
    } else if (response.status === 422) {
      setIssues(data.issues);
      saveError = "не сохранено: блокирующие замечания";
    } else {
      saveError = data.error || "ошибка сервера " + response.status;
    }
    renderStatus();
  }

  function reread() {
    conflict = false;
    return load(false);
  }

  function keepMine() {
    keepEtag = diskEtag;
    baseEtag = diskEtag;
    conflict = false;
    renderStatus();
  }

  // Сервис переключен на другую папку макетов: вкладка больше не пишет и не перечитывает файл -
  // одноименный файл новой папки ей чужой. «Перечитать» и «Оставить мои» тут не к месту: обе вели бы к нему
  function folderLost(data) {
    movedFolder = data.folder || "другая папка";
    conflict = false;
    saveError = "";
    renderStatus();
  }

  function renderStatus() {
    ui.issuesButton.textContent = "Замечания: " + issues.length;
    ui.issuesButton.classList.toggle("fe-has-issues", issues.length > 0);
    if (movedFolder) {
      ui.status.textContent = "папка макетов сменилась - сохранение выключено";
      ui.status.className = "fe-status fe-status-alert";
      ui.error.textContent = "";
      ui.save.disabled = true;
      ui.save.title = "Макет открыт из другой папки: сервис работает с папкой " + movedFolder;
      ui.banner.hidden = true;
      ui.folderNote.textContent = "Сервис переключён на папку " + movedFolder + ", а этот макет открыт из папки " +
        ED.folder + ". Сохранение из этой вкладки выключено, чтобы не записать одноимённый файл другой папки.";
      ui.folderBanner.hidden = false;
      return;
    }
    var text = !online ? "нет связи с сервером"
      : unreadable ? "файл не читается: " + unreadable
      : conflict ? "файл изменён на диске"
      : dirty() ? "есть несохранённые правки"
      : "сохранено";
    if (online && !unreadable && !conflict && !dirty() && fileUpdated) text += " - файл обновлён";
    ui.status.textContent = text;
    FMAlive.update({ dirty: dirty() });
    ui.status.className = "fe-status" + (!online || unreadable || conflict ? " fe-status-alert" : dirty() ? " fe-status-dirty" : "");
    ui.error.textContent = saveError;
    ui.save.disabled = !online || !model;
    ui.save.title = blocked ? "Модель с блокирующими замечаниями не сохраняется" : "Сохранить (Ctrl+S)";
    ui.banner.hidden = !conflict;
    ui.folderBanner.hidden = true;
  }

  // Страница: панель конструктора, баннер, три колонки

  function button(text, handler, cls) {
    var item = h("button", cls || "", text);
    item.type = "button";
    item.addEventListener("click", handler);
    return item;
  }

  // Значки кнопок панелей: добавить - зеленый плюс, удалить - красный крест, перемещение - синие стрелки
  var TOOL_ICONS = {
    add: '<path d="M8 3v10M3 8h10" stroke="#2e9b3a" stroke-width="2" stroke-linecap="round"/>',
    "delete": '<path d="M4 4l8 8M12 4l-8 8" stroke="#d14343" stroke-width="2" stroke-linecap="round"/>',
    up: '<path d="M8 13V3.5M3.5 8L8 3.5 12.5 8" fill="none" stroke="#2f6fde" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    down: '<path d="M8 3v9.5M3.5 8L8 12.5 12.5 8" fill="none" stroke="#2f6fde" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
  };

  // Кнопка со значком: `text` - подпись рядом со значком, без нее - только значок, `title` - подсказка и имя для
  // экранного диктора
  function toolButton(icon, text, title, handler, cls) {
    var item = button("", handler, "fe-tool" + (text ? "" : " fe-tool-icon") + (cls ? " " + cls : ""));
    var holder = h("span");
    holder.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true">' + TOOL_ICONS[icon] + "</svg>";
    item.appendChild(holder.firstChild);
    if (text) item.appendChild(h("span", "", text));
    item.title = title;
    item.setAttribute("aria-label", title);
    return item;
  }

  function toggle(text, on, handler) {
    var label = h("label", "fe-toggle");
    var input = h("input");
    input.type = "checkbox";
    input.checked = on;
    input.addEventListener("change", function () { handler(input.checked); });
    label.appendChild(input);
    label.appendChild(document.createTextNode(text));
    return { label: label, input: input };
  }

  // `least` - самая узкая колонка: у панели свойств - 260 px, чтобы переключатель «По группам / По алфавиту» и
  // кнопки стояли в ряд, у дерева - 160 px
  function splitter(column, side, store, least) {
    least = least || 160;
    var bar = h("div", "fe-split");
    bar.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      var start = event.clientX;
      var width = column.getBoundingClientRect().width;
      bar.setPointerCapture(event.pointerId);
      function move(moved) {
        var next = Math.max(least, Math.min(900, width + (moved.clientX - start) * side));
        column.style.width = px(next);
      }
      function stop() {
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", stop);
        try { localStorage.setItem(store, column.style.width); } catch (error) { /* хранилище недоступно */ }
        R.redraw();
      }
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", stop);
    });
    try {
      var saved = localStorage.getItem(store);
      if (saved) column.style.width = px(Math.max(least, parseFloat(saved) || least));
    } catch (error) { /* хранилище недоступно */ }
    return bar;
  }

  function setupPage() {
    document.body.classList.add("fe-editor");
    var root = document.getElementById("fm-root");

    var bar = h("div", "fe-bar");
    var home = FMAlive.link(h("a", "fe-home", "К списку"));
    home.href = "/";
    home.title = "Список макетов папки";
    bar.appendChild(home);
    ui.save = button("Сохранить", save, "fe-save");
    bar.appendChild(ui.save);
    ui.undo = button("Отменить", undo, "fe-undo");
    ui.undo.title = "Отменить (Ctrl+Z)";
    ui.redo = button("Повторить", redo, "fe-redo");
    ui.redo.title = "Повторить (Ctrl+Shift+Z)";
    bar.appendChild(ui.undo);
    bar.appendChild(ui.redo);
    renderHistory();
    var names = toggle("Имена", false, function (on) { R.setShowNames(on); });
    var hidden = toggle("Скрытые", false, function (on) { R.setShowHidden(on); });
    ui.names = names.input;
    ui.hidden = hidden.input;
    bar.appendChild(names.label);
    bar.appendChild(hidden.label);
    // Правки против «было»: счетчик виден и при выключенном
    var diffToggle = toggle("Правки", diffOn, function (on) { setDiffOn(on); });
    diffToggle.label.classList.add("fe-diff-toggle");
    ui.diffToggle = diffToggle.input;
    ui.diffLabel = diffToggle.label.lastChild;
    bar.appendChild(diffToggle.label);
    ui.status = h("span", "fe-status");
    bar.appendChild(ui.status);
    ui.error = h("span", "fe-error");
    bar.appendChild(ui.error);
    var spacer = h("span", "fe-spacer");
    bar.appendChild(spacer);
    ui.issuesButton = button("Замечания: 0", function () { ui.issueList.hidden = !ui.issueList.hidden; }, "fe-issues-button");
    bar.appendChild(ui.issuesButton);
    bar.appendChild(h("span", "fe-file", ED.file));

    ui.issueList = h("div", "fe-issue-list");
    ui.issueList.hidden = true;
    ui.issueRows = h("div");
    ui.issueList.appendChild(ui.issueRows);

    ui.banner = h("div", "fe-banner");
    ui.banner.hidden = true;
    ui.banner.appendChild(h("span", "", "Файл изменён на диске."));
    ui.banner.appendChild(button("Перечитать", reread, "fe-reread"));
    ui.banner.appendChild(button("Оставить мои", keepMine, "fe-keep"));
    ui.banner.appendChild(h("span", "fe-banner-note", "«Перечитать» - правки страницы пропадут; «Оставить мои» - следующее сохранение перезапишет файл"));
    // Папка макетов сменилась: выход один - вернуть сервис к папке макета или открыть макет заново
    ui.folderBanner = h("div", "fe-banner fe-folder-banner");
    ui.folderBanner.hidden = true;
    ui.folderNote = h("span", "");
    ui.folderBanner.appendChild(ui.folderNote);
    ui.folderBanner.appendChild(h("span", "fe-banner-note", "Правки этой вкладки не сохранятся: перенесите нужное вручную и закройте вкладку, макет открывайте со стартовой страницы"));

    var main = h("div", "fe-main");
    var treeColumn = h("div", "fe-tree-col");
    // «Элементы / Реквизиты» - сегментом, как закладки редактора формы
    var leftHead = h("div", "fe-col-head fe-left-head");
    ui.leftItems = button("Элементы", function () { setLeftMode("items"); }, "fe-mode fe-mode-on fe-left-items");
    ui.leftAttrs = button("Реквизиты", function () { setLeftMode("attributes"); }, "fe-mode fe-left-attrs");
    ui.leftCommands = button("Команды", function () { setLeftMode("commands"); }, "fe-mode fe-left-commands");
    leftHead.appendChild(ui.leftItems);
    leftHead.appendChild(ui.leftAttrs);
    leftHead.appendChild(ui.leftCommands);
    treeColumn.appendChild(leftHead);
    ui.attrPanel = h("div", "fe-attr-panel");
    ui.attrPanel.hidden = true;
    var attrTools = h("div", "fe-attr-tools");
    attrTools.appendChild(toolButton("add", "Реквизит", "Добавить реквизит", function () { addAttr(false); }, "fe-attr-add"));
    ui.attrAddColumn = toolButton("add", "Колонка", "Добавить колонку", function () { addAttr(true); }, "fe-attr-add-column");
    ui.attrDelete = toolButton("delete", "Удалить", "Удалить (Del)", deleteAttr, "fe-attr-delete");
    attrTools.appendChild(ui.attrAddColumn);
    attrTools.appendChild(ui.attrDelete);
    ui.attrPanel.appendChild(attrTools);
    ui.attrTree = h("div", "fe-tree fe-attr-tree");
    ui.attrTree.tabIndex = 0;
    ui.attrTree.addEventListener("keydown", attrKey);
    ui.attrTree.addEventListener("contextmenu", function (event) { listContext(event, selectAttr, attrMenu); });
    ui.attrPanel.appendChild(ui.attrTree);
    treeColumn.appendChild(ui.attrPanel);
    ui.cmdPanel = h("div", "fe-attr-panel fe-cmd-panel");
    ui.cmdPanel.hidden = true;
    var cmdTools = h("div", "fe-attr-tools");
    cmdTools.appendChild(toolButton("add", "Команда", "Добавить команду", addCommand, "fe-cmd-add"));
    ui.cmdDelete = toolButton("delete", "Удалить", "Удалить (Del)", deleteCommand, "fe-cmd-delete");
    cmdTools.appendChild(ui.cmdDelete);
    ui.cmdPanel.appendChild(cmdTools);
    ui.cmdTree = h("div", "fe-tree fe-cmd-tree");
    ui.cmdTree.tabIndex = 0;
    ui.cmdTree.addEventListener("keydown", commandKey);
    ui.cmdTree.addEventListener("contextmenu", function (event) { listContext(event, selectCommand, commandMenu); });
    ui.cmdPanel.appendChild(ui.cmdTree);
    treeColumn.appendChild(ui.cmdPanel);
    // Панель дерева элементов
    ui.itemTools = h("div", "fe-attr-tools fe-item-tools");
    ui.addButton = toolButton("add", "Добавить", "Добавить элемент", function () {
      if (ui.menu.hidden) openPalette();
      else closeMenu();
    }, "fe-item-add");
    ui.deleteButton = toolButton("delete", "Удалить", "Удалить (Del)", deleteSelected, "fe-item-delete");
    ui.upButton = toolButton("up", "", "Переместить вверх (Alt+↑)", function () { moveSibling(-1); }, "fe-item-up");
    ui.downButton = toolButton("down", "", "Переместить вниз (Alt+↓)", function () { moveSibling(1); }, "fe-item-down");
    [ui.addButton, ui.deleteButton, ui.upButton, ui.downButton].forEach(function (one) { ui.itemTools.appendChild(one); });
    treeColumn.appendChild(ui.itemTools);
    ui.menu = h("div", "fe-menu");
    ui.menu.hidden = true;
    ui.tree = h("div", "fe-tree");
    ui.tree.tabIndex = 0;
    ui.tree.addEventListener("click", function (event) {
      var row = event.target.closest(".fe-row");
      if (!row) return;
      // Удаленный элемент не правится: щелчок показывает его правку
      if (row.dataset.removed) {
        showChange(Number(row.dataset.change), true);
        return;
      }
      var key = row.dataset.key;
      if (event.target.classList.contains("fe-twisty") && entries[key] && entries[key].children.length) {
        folded[key] = !folded[key];
        renderTree();
        return;
      }
      if (event.ctrlKey || event.metaKey) togglePick(key);
      else if (event.shiftKey) rangePick(key);
      else select(key);
    });
    ui.tree.addEventListener("dblclick", function (event) {
      var row = event.target.closest(".fe-row");
      if (!row || !entries[row.dataset.key] || !entries[row.dataset.key].children.length) return;
      folded[row.dataset.key] = !folded[row.dataset.key];
      renderTree();
    });
    ui.tree.addEventListener("keydown", treeKey);
    // Контекстное меню: по строке - для нее, по пустому месту дерева - для формы, с клавиатуры - для выбранной
    ui.tree.addEventListener("contextmenu", function (event) {
      event.preventDefault();
      var row = event.target.closest(".fe-row");
      if (row && row.dataset.removed) return;
      var at = pointOf(event);
      openContext(row ? row.dataset.key : at ? FORM_KEY : selected, at, false);
    });
    setupDrag();
    treeColumn.appendChild(ui.tree);

    ui.center = h("div", "fe-center");
    ui.blocked = h("div", "fe-blocked");
    ui.blocked.hidden = true;
    ui.blocked.appendChild(h("div", "fe-blocked-title", "Модель не рисуется: замечания схемы или повтор имени. Дерево и свойства работают - после исправления макет появится."));
    ui.blockedList = h("div");
    ui.blocked.appendChild(ui.blockedList);
    ui.center.appendChild(ui.blocked);
    ui.center.appendChild(root);
    ui.center.addEventListener("click", layoutClick);
    ui.center.addEventListener("contextmenu", layoutContext);
    setupCanvasDrop();

    var propsColumn = h("div", "fe-props-col");
    // Закладки «Свойства / Примечания / Правки»; «Правки» - при включенных правках
    ui.rightTabs = h("div", "fe-left-head fe-right-tabs");
    ui.tabProps = button("Свойства", function () { setRightTab("props"); }, "fe-mode fe-tab-props");
    ui.tabNotes = button("Примечания", function () { setRightTab("notes"); }, "fe-mode fe-tab-notes");
    ui.tabChanges = button("Правки", function () { setRightTab("changes"); }, "fe-mode fe-tab-changes");
    ui.rightTabs.appendChild(ui.tabProps);
    ui.rightTabs.appendChild(ui.tabNotes);
    ui.rightTabs.appendChild(ui.tabChanges);
    propsColumn.appendChild(ui.rightTabs);
    var head = h("div", "fe-props-head");
    ui.propsHead = head;
    ui.propsTitle = h("div", "fe-col-head", "Свойства");
    head.appendChild(ui.propsTitle);
    var tools = h("div", "fe-props-tools");
    var byGroups = button("По группам", function () { setAlphabetical(false); }, "fe-mode fe-mode-groups fe-mode-on");
    var byName = button("По алфавиту", function () { setAlphabetical(true); }, "fe-mode fe-mode-alpha");
    function setAlphabetical(on) {
      alphabetical = on;
      byGroups.classList.toggle("fe-mode-on", !on);
      byName.classList.toggle("fe-mode-on", on);
      renderProps();
    }
    tools.appendChild(byGroups);
    tools.appendChild(byName);
    // Свернуть / развернуть все группы свойств
    var foldAll = button("", function () {
      ui.propsBody.querySelectorAll(".fe-group-head").forEach(function (head) { foldedGroups[head.dataset.group] = true; });
      renderProps();
    }, "fe-icon-button fe-fold-all");
    foldAll.title = "Свернуть все группы";
    foldAll.innerHTML = '<svg viewBox="0 0 16 16"><path d="M4 6.5 8 3l4 3.5M4 13 8 9.5l4 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var unfoldAll = button("", function () {
      foldedGroups = {};
      renderProps();
    }, "fe-icon-button fe-unfold-all");
    unfoldAll.title = "Развернуть все группы";
    unfoldAll.innerHTML = '<svg viewBox="0 0 16 16"><path d="M4 3 8 6.5 12 3M4 9.5 8 13l4-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    ui.search = h("input", "fe-search");
    ui.search.placeholder = "Поиск свойства";
    tools.appendChild(foldAll);
    tools.appendChild(unfoldAll);
    ui.search.addEventListener("input", function () {
      search = ui.search.value;
      renderProps();
    });
    tools.appendChild(ui.search);
    head.appendChild(tools);
    propsColumn.appendChild(head);
    ui.propsBody = h("div", "fe-props");
    propsColumn.appendChild(ui.propsBody);
    ui.notesBody = h("div", "fe-props fe-changes fe-notes");
    propsColumn.appendChild(ui.notesBody);
    ui.changesBody = h("div", "fe-props fe-changes");
    propsColumn.appendChild(ui.changesBody);
    renderRightTab();
    renderDiffCount();

    main.appendChild(treeColumn);
    main.appendChild(splitter(treeColumn, 1, "fe-tree-width"));
    main.appendChild(ui.center);
    main.appendChild(splitter(propsColumn, -1, "fe-props-width", 260));
    main.appendChild(propsColumn);

    document.body.insertBefore(main, document.body.firstChild);
    document.body.insertBefore(ui.banner, main);
    document.body.insertBefore(ui.folderBanner, main);
    document.body.insertBefore(bar, ui.banner);
    document.body.appendChild(ui.issueList);
    document.body.appendChild(ui.menu);
    // Палитра закрывается щелчком мимо нее и Esc
    document.addEventListener("mousedown", function (event) {
      if (!ui.menu.hidden && !ui.menu.contains(event.target) && !ui.addButton.contains(event.target)) closeMenu();
    });
    ui.menu.addEventListener("keydown", menuKey);
    ui.dialog = h("div", "fe-dialog-back");
    ui.dialog.hidden = true;
    ui.dialogBox = h("div", "fe-dialog");
    ui.dialogBox.tabIndex = -1;
    ui.dialog.appendChild(ui.dialogBox);
    ui.dialog.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDialog();
      else if (dialog && dialog.kind === "path" && !/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) pathKey(event);
    });
    document.body.appendChild(ui.dialog);
    ui.result = h("pre");
    ui.result.id = "fe-result";
    ui.result.hidden = true;
    document.body.appendChild(ui.result);

    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === "s" || event.key === "ы")) {
        event.preventDefault();
        var field = document.activeElement;
        // Значение в поле свойства применяется до записи
        if (field && field.classList && (field.classList.contains("fe-input") || field.classList.contains("fe-note-text"))) {
          field.dispatchEvent(new Event("change"));
        }
        save();
        return;
      }
      historyKey(event);
    });
    window.addEventListener("beforeunload", function (event) {
      if (!dirty() || quitting) return;
      event.preventDefault();
      event.returnValue = "";
    });
    R.onDraw = drawSelection;
    // Номера примечаний на макете; при включенных правках рендерер их не рисует
    R.setShowNotes(true);
  }

  // Сценарии теста: действия из адреса, итог - в pre#fe-result

  // Строка левой колонки в итоге: зазор значка «есть на форме» до правого края строки, ширина имени, обрезано ли
  // имя, вылезает ли строка за колонку (узкая колонка)
  function rowFit(row) {
    var usage = row.querySelector(".fe-usage");
    var label = row.querySelector(".fe-label");
    var box = row.getBoundingClientRect();
    var tree = row.closest(".fe-tree").getBoundingClientRect();
    return {
      usageGap: usage ? Math.round(box.right - usage.getBoundingClientRect().right) : null,
      labelWidth: label ? Math.round(label.getBoundingClientRect().width) : null,
      labelClipped: label ? label.scrollWidth > label.clientWidth : false,
      overflow: Math.round(Math.max(0, box.right - tree.right, row.scrollWidth - row.clientWidth))
    };
  }

  function actionsOf() {
    var found = location.hash.replace(/^#/, "").split("&").filter(function (part) { return part.indexOf("do=") === 0; })[0];
    return found ? decodeURIComponent(found.slice(3)).split(";").filter(Boolean) : [];
  }

  function field(prop) {
    var found = ui.propsBody.querySelector('.fe-input[data-prop="' + prop + '"]');
    if (!found) throw new Error("нет поля свойства " + prop);
    return found;
  }

  async function runAction(action) {
    var colon = action.indexOf(":");
    var verb = colon < 0 ? action : action.slice(0, colon);
    var arg = colon < 0 ? "" : action.slice(colon + 1);
    if (verb === "tree" || verb === "ctrl-tree" || verb === "shift-tree") {
      // `ctrl-tree:` и `shift-tree:` - щелчок с Ctrl или Shift: несколько выделенных
      var row = ui.tree.querySelector('.fe-row[data-key="' + arg + '"] .fe-label');
      if (!row) throw new Error("нет узла дерева " + arg);
      row.dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: verb === "ctrl-tree", shiftKey: verb === "shift-tree" }));
    } else if (verb === "ctrl-click") {
      var clicked = R.element(arg);
      if (!clicked) throw new Error("нет элемента на макете " + arg);
      R.partsOf(clicked)[0].dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: true }));
    } else if (verb === "click") {
      var element = R.element(arg);
      if (!element) throw new Error("нет элемента на макете " + arg);
      R.partsOf(element)[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    } else if (verb === "key") {
      var target = dialog && dialog.kind === "path" ? ui.dialogBox
        : leftMode === "attributes" ? ui.attrTree : leftMode === "commands" ? ui.cmdTree : ui.tree;
      var shifted = arg.indexOf("Shift+") === 0;
      target.dispatchEvent(new KeyboardEvent("keydown", { key: shifted ? arg.slice(6) : arg, shiftKey: shifted, bubbles: true }));
    } else if (verb === "set") {
      var equal = arg.indexOf("=");
      var input = field(arg.slice(0, equal));
      var value = arg.slice(equal + 1);
      if (input.type === "checkbox") input.checked = value === "true";
      else input.value = value;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (verb === "diff") {
      ui.diffToggle.checked = arg === "on";
      ui.diffToggle.dispatchEvent(new Event("change"));
    } else if (verb === "right") {
      // Закладка правой колонки: props | notes | changes
      (arg === "changes" ? ui.tabChanges : arg === "notes" ? ui.tabNotes : ui.tabProps).click();
    } else if (verb === "note-row") {
      var noteLine = ui.notesBody.querySelector('.fe-note[data-key="' + arg + '"] .fe-change-head');
      if (!noteLine) throw new Error("нет в списке примечания " + arg);
      noteLine.click();
    } else if (verb === "note-set") {
      // `note-set:Ключ=текст` - текст набран в строке списка и поле покинуто
      var noteAt = arg.indexOf("=");
      var noteField = ui.notesBody.querySelector('.fe-note-text[data-key="' + arg.slice(0, noteAt) + '"]');
      if (!noteField) throw new Error("нет строки примечания " + arg.slice(0, noteAt));
      noteField.focus();
      noteField.value = arg.slice(noteAt + 1);
      noteField.dispatchEvent(new Event("change"));
      noteField.blur();
    } else if (verb === "change") {
      var changeItem = ui.changesBody.querySelector('.fe-change[data-change="' + arg + '"]');
      if (!changeItem) throw new Error("нет в списке правки " + arg);
      changeItem.click();
    } else if (verb === "removed") {
      var removedLine = ui.tree.querySelector('.fe-row[data-removed="' + arg + '"]');
      if (!removedLine) throw new Error("нет в дереве удаленного " + arg);
      removedLine.click();
    } else if (verb === "revert") {
      var revert = ui.propsBody.querySelector('.fe-revert[data-prop="' + arg + '"]');
      if (!revert) throw new Error("нет кнопки «вернуть как было» у " + arg);
      revert.click();
    } else if (verb === "reset") {
      var reset = ui.propsBody.querySelector('.fe-reset[data-prop="' + arg + '"]');
      if (!reset) throw new Error("нет кнопки «по умолчанию» у " + arg);
      reset.click();
    } else if (verb === "spin") {
      var parts = arg.split("=");
      var spin = ui.propsBody.querySelector((parts[1] === "down" ? ".fe-down" : ".fe-up") + '[data-prop="' + parts[0] + '"]');
      if (!spin) throw new Error("нет кнопок «+/-» у " + parts[0]);
      spin.click();
    } else if (verb === "save") {
      await save();
    } else if (verb === "check") {
      if (checking) await checking;
    } else if (verb === "wait") {
      await sleep(Number(arg));
    } else if (verb === "hidden" || verb === "names") {
      var box = verb === "hidden" ? ui.hidden : ui.names;
      box.checked = arg === "on";
      box.dispatchEvent(new Event("change"));
    } else if (verb === "reread") {
      await reread();
    } else if (verb === "keep") {
      keepMine();
    } else if (verb === "rerender") {
      // Замер скорости перерисовки: N перерисовок подряд, время - по часам снаружи
      for (var n = 0; n < Number(arg); n++) drawLayout();
    } else if (verb === "search") {
      ui.search.value = arg;
      ui.search.dispatchEvent(new Event("input"));
    } else if (verb === "choose") {
      var chooser = ui.propsBody.querySelector('.fe-choose[data-prop="' + arg + '"]');
      if (!chooser) throw new Error("нет кнопки выбора у " + arg);
      chooser.click();
    } else if (verb === "pick") {
      // Строка дерева пути: родители раскрываются, как это сделал бы пользователь
      var parts = arg.split(".");
      for (var p = 1; p < parts.length; p++) dialog.open[parts.slice(0, p).join(".")] = true;
      renderDialog();
      var pickRow = ui.dialogBox.querySelector('.fe-pick-row[data-path="' + arg + '"]');
      if (!pickRow) throw new Error("нет строки пути " + arg);
      pickRow.click();
    } else if (verb === "ok") {
      confirmDialog();
    } else if (verb === "command") {
      var pair = arg.split("=");
      var command = ui.dialogBox.querySelector('input[data-command="' + pair[0] + '"]');
      if (!command) throw new Error("нет команды " + pair[0]);
      command.checked = pair[1] === "true";
      command.dispatchEvent(new Event("change"));
    } else if (verb === "tab") {
      dialogControl('.fe-tab[data-tab="' + arg + '"]', "закладки " + arg).click();
    } else if (verb === "color") {
      dialogControl('.fe-color-row[data-color="' + arg + '"]', "цвета " + arg).click();
    } else if (verb === "rgb") {
      var hex = dialogControl(".fe-color-hex", "поля #RRGGBB");
      hex.value = arg;
      hex.dispatchEvent(new Event("change"));
    } else if (verb === "fmt" || verb === "fmtoff") {
      var pairFormat = arg.split("=");
      var key = pairFormat[0];
      var valueControl = ui.dialogBox.querySelector('.fe-format-value[data-key="' + key + '"]');
      if (verb === "fmt" && valueControl) {
        valueControl.value = arg.slice(key.length + 1);
        valueControl.dispatchEvent(new Event("change"));
      } else {
        var use = dialogControl('input[data-use="' + key + '"]', "флажка " + key);
        use.checked = verb === "fmt";
        use.dispatchEvent(new Event("change"));
      }
    } else if (verb === "sample") {
      var sampleInput = dialogControl(".fe-format-input", "поля примера");
      sampleInput.value = arg;
      sampleInput.dispatchEvent(new Event("change"));
    } else if (verb === "list") {
      var pairList = arg.split("=");
      dialogControl('.fe-list-bar [data-command="' + pairList[0] + '"]', "команды " + pairList[0]).click();
      // `list:add=Значение` или `list:add=Значение|Представление`
      if (pairList[0] === "add" && pairList.length > 1) {
        var parts = arg.slice(4).split("|");
        ["value", "presentation"].slice(0, parts.length).forEach(function (column, at) {
          var added = dialogControl('.fe-list-value[data-index="' + dialog.chosen + '"][data-column="' + column + '"]',
            "новой строки");
          added.value = parts[at];
          added.dispatchEvent(new Event("input"));
        });
      }
    } else if (verb === "row") {
      dialogControl('.fe-list-value[data-index="' + arg + '"][data-column="value"]', "строки " + arg)
        .dispatchEvent(new Event("focus"));
    } else if (verb === "find") {
      await libraryLoaded();
      var filter = dialogControl(".fe-filter", "поиска");
      filter.value = arg;
      filter.dispatchEvent(new Event("input"));
    } else if (verb === "picture") {
      await libraryLoaded();
      dialogControl('.fe-picture-tile[data-picture="' + arg + '"]', "картинки " + arg).click();
    } else if (verb === "pick-value") {
      dialogControl('.fe-pick-row[data-value="' + arg + '"]', "значения " + arg).click();
    } else if (verb === "new-command") {
      dialogControl(".fe-add-name", "имени команды").value = arg;
      dialogControl(".fe-add-button", "кнопки новой команды").click();
    } else if (verb === "fold") {
      ui.propsBody.parentElement.querySelector(arg === "all" ? ".fe-fold-all" : ".fe-unfold-all").click();
    } else if (verb === "left") {
      (arg === "attributes" ? ui.leftAttrs : arg === "commands" ? ui.leftCommands : ui.leftItems).click();
    } else if (verb === "left-width") {
      // Ширина левой колонки, как после перетаскивания разделителя (не уже 160 px)
      document.querySelector(".fe-tree-col").style.width = px(Math.max(160, Number(arg)));
    } else if (verb === "attr-pick") {
      var parts = arg.split(".");
      for (var a = 1; a < parts.length; a++) attrOpen[parts.slice(0, a).join(".")] = true;
      renderAttrTree();
      var attrRow = ui.attrTree.querySelector('.fe-row[data-path="' + arg + '"]');
      if (!attrRow) throw new Error("нет реквизита " + arg);
      attrRow.click();
    } else if (verb === "attr-add") {
      ui.attrPanel.querySelector(arg === "column" ? ".fe-attr-add-column" : ".fe-attr-add").click();
    } else if (verb === "attr-delete") {
      ui.attrDelete.click();
    } else if (verb === "cmd-pick") {
      var cmdRow = ui.cmdTree.querySelector('.fe-row[data-name="' + arg + '"]');
      if (!cmdRow) throw new Error("нет команды " + arg);
      cmdRow.click();
    } else if (verb === "usage") {
      var tree = leftMode === "commands" ? ui.cmdTree : ui.attrTree;
      var usage = tree.querySelector('.fe-row[data-key="' + arg + '"] .fe-usage');
      if (!usage) throw new Error("нет значка «на форме» у " + arg);
      usage.click();
    } else if (verb === "cmd-add") {
      ui.cmdPanel.querySelector(".fe-cmd-add").click();
    } else if (verb === "cmd-delete") {
      ui.cmdDelete.click();
    } else if (verb === "composite") {
      var composite = dialogControl(".fe-type-composite input", "флажка составного типа");
      composite.checked = arg === "on";
      composite.dispatchEvent(new Event("change"));
    } else if (verb === "section") {
      dialogControl('.fe-pick-group[data-section="' + arg + '"]', "группы " + arg).click();
    } else if (verb === "dlg-set" || verb === "panel-set") {
      var equalAt = arg.lastIndexOf("=");
      var control = verb === "dlg-set" ? dialogControl(arg.slice(0, equalAt), arg.slice(0, equalAt))
        : ui.propsBody.querySelector(arg.slice(0, equalAt));
      if (!control) throw new Error("нет в панели " + arg.slice(0, equalAt));
      if (control.type === "checkbox") control.checked = arg.slice(equalAt + 1) === "true";
      else control.value = arg.slice(equalAt + 1);
      control.dispatchEvent(new Event("change"));
    } else if (verb === "dlg-click") {
      dialogControl(arg, arg).click();
    } else if (verb === "cancel") {
      dialogControl(".fe-dialog-cancel", "кнопки отмены").click();
    } else if (verb === "palette") {
      ui.addButton.click();
    } else if (verb === "add") {
      if (ui.menu.hidden) ui.addButton.click();
      var kindRow = ui.menu.querySelector('.fe-menu-item[data-kind="' + arg + '"]');
      if (!kindRow) throw new Error("нет в палитре " + arg);
      kindRow.click();
    } else if (verb === "ctx" || verb === "ctx-layout") {
      // Правая кнопка по строке дерева или элементу макета; `ctx:` без имени - с клавиатуры (клавиша меню)
      var spot = !arg ? ui.tree : verb === "ctx" ? ui.tree.querySelector('.fe-row[data-key="' + arg + '"] .fe-label')
        : R.element(arg) && R.partsOf(R.element(arg))[0];
      if (!spot) throw new Error("нет места для меню " + arg);
      var spotRect = spot.getBoundingClientRect();
      spot.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2,
        clientX: arg ? spotRect.left + 4 : 0, clientY: arg ? spotRect.top + 4 : 0 }));
    } else if (verb === "ctx-attr" || verb === "ctx-cmd") {
      // Правая кнопка на закладке «Реквизиты» (по пути) или «Команды» (по имени); `*` - пустое место дерева, без
      // аргумента - с клавиатуры (клавиша меню)
      var listTree = verb === "ctx-attr" ? ui.attrTree : ui.cmdTree;
      var listSpot = !arg || arg === "*" ? listTree
        : listTree.querySelector('.fe-row[data-' + (verb === "ctx-attr" ? "path" : "name") + '="' + arg + '"] .fe-label');
      if (!listSpot) throw new Error("нет строки для меню " + arg);
      var listRect = listSpot.getBoundingClientRect();
      listSpot.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2,
        clientX: arg ? listRect.left + 4 : 0, clientY: arg ? listRect.bottom - 2 : 0 }));
    } else if (verb === "menu") {
      var action = ui.menu.hidden ? null : ui.menu.querySelector('.fe-menu-action[data-action="' + arg + '"]');
      if (!action) throw new Error("нет в меню " + arg);
      action.click();
    } else if (verb === "delete") {
      ui.deleteButton.click();
    } else if (verb === "move") {
      (arg === "up" ? ui.upButton : ui.downButton).click();
    } else if (verb === "alt") {
      ui.tree.dispatchEvent(new KeyboardEvent("keydown", { key: arg, altKey: true, bubbles: true }));
    } else if (verb === "undo" || verb === "redo") {
      (verb === "undo" ? ui.undo : ui.redo).click();
    } else if (verb === "hotkey") {
      // `hotkey:KeyZ`, `hotkey:Shift+KeyZ` - с Ctrl
      var shifted = arg.indexOf("Shift+") === 0;
      document.body.dispatchEvent(new KeyboardEvent("keydown", { code: arg.replace("Shift+", ""), ctrlKey: true,
        shiftKey: shifted, bubbles: true, cancelable: true }));
    } else if (verb === "drag") {
      // `drag:Источник>Цель@before|after|inside` - события перетаскивания с курсором в своей части строки цели
      var drag = /^(.+)>(.+)@(before|after|inside)$/.exec(arg);
      if (!drag) throw new Error("drag:Источник>Цель@место");
      var fromRow = ui.tree.querySelector('.fe-row[data-key="' + drag[1] + '"]');
      var toRow = ui.tree.querySelector('.fe-row[data-key="' + drag[2] + '"]');
      if (!fromRow || !toRow) throw new Error("нет узла дерева " + (fromRow ? drag[2] : drag[1]));
      var transfer = new DataTransfer();
      fromRow.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      var rect = toRow.getBoundingClientRect();
      var at = { clientX: rect.left + 30, clientY: rect.top + rect.height * ({ before: 0.1, after: 0.9, inside: 0.5 })[drag[3]] };
      var init = Object.assign({ bubbles: true, cancelable: true, dataTransfer: transfer }, at);
      toRow.dispatchEvent(new DragEvent("dragover", init));
      dropAccepted = false;
      toRow.dispatchEvent(new DragEvent("drop", init));
      fromRow.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: transfer }));
    } else if (verb === "drag-new" || verb === "drop-canvas") {
      // `drag-new:attr:<путь>>Цель@место` или `drag-new:cmd:<имя>>Цель@место` - с закладки «Реквизиты» или
      // «Команды» в дерево элементов: курсор проходит над переключателем «Элементы»; `drop-canvas:...` - так же,
      // но на элемент макета (цель `Форма` - окно формы)
      var fresh = /^(attr|cmd):(.+)>(.+)@(before|after|inside)$/.exec(arg);
      if (!fresh) throw new Error("drag-new:attr|cmd:Источник>Цель@место");
      setLeftMode(fresh[1] === "attr" ? "attributes" : "commands");
      if (fresh[1] === "attr") {
        var opened = fresh[2].split(".");
        for (var o = 1; o < opened.length; o++) attrOpen[opened.slice(0, o).join(".")] = true;
        renderAttrTree();
      }
      var sourceRow = fresh[1] === "attr" ? ui.attrTree.querySelector('.fe-row[data-path="' + fresh[2] + '"]')
        : ui.cmdTree.querySelector('.fe-row[data-name="' + fresh[2] + '"]');
      if (!sourceRow) throw new Error("нет строки " + fresh[2]);
      var carry = new DataTransfer();
      sourceRow.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: carry }));
      if (verb === "drag-new") {
        ui.leftItems.dispatchEvent(new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: carry }));
      }
      var onCanvas = verb === "drop-canvas";
      var targetRow = onCanvas ? (fresh[3] === FORM_KEY ? ui.center.querySelector("#fm-root") : canvasElement(fresh[3]))
        : ui.tree.querySelector('.fe-row[data-key="' + fresh[3] + '"]');
      if (!targetRow) throw new Error((onCanvas ? "нет на макете " : "нет узла дерева ") + fresh[3]);
      var box = targetRow.getBoundingClientRect();
      var share = ({ before: 0.1, after: 0.9, inside: 0.5 })[fresh[4]];
      var point = { clientX: box.left + 30, clientY: box.top + box.height * share };
      if (onCanvas) {
        // На макете - по оси ряда цели; у контейнера кромка - в пределах CANVAS_EDGE
        var aim = entries[fresh[3]];
        var horizontal = aim && aim.parent && canvasAxis(aim, targetRow) === "x";
        var length = horizontal ? box.width : box.height;
        var offset = fresh[4] === "inside" ? length / 2 : fresh[4] === "before" ? 2 : length - 2;
        if (!isContainer(aim)) offset = length * share;
        point = horizontal ? { clientX: box.left + offset, clientY: box.top + box.height / 2 }
          : { clientX: box.left + Math.min(30, box.width / 2), clientY: box.top + offset };
      }
      var over = Object.assign({ bubbles: true, cancelable: true, dataTransfer: carry }, point);
      targetRow.dispatchEvent(new DragEvent("dragover", over));
      dropAccepted = false;
      targetRow.dispatchEvent(new DragEvent("drop", over));
      sourceRow.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: carry }));
    } else if (verb === "dbl") {
      // `dbl:<селектор строки окна>` - двойной щелчок, как у браузера: два щелчка, двойной - только если второй
      // пришелся в ту же строку (перерисовка окна ее подменила бы)
      var first = dialogControl(arg, arg);
      first.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
      var second = dialog ? ui.dialogBox.querySelector(arg) : null;
      dblSame = second === first;
      if (second) second.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 2 }));
      if (dblSame) second.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, detail: 2 }));
    } else if (verb === "panel-click") {
      var panelControl = ui.propsBody.querySelector(arg);
      if (!panelControl) throw new Error("нет в панели " + arg);
      panelControl.click();
    } else if (verb === "alpha") {
      ui.propsBody.parentElement.querySelector(arg === "on" ? ".fe-mode-alpha" : ".fe-mode-groups").click();
    } else {
      throw new Error("неизвестное действие " + action);
    }
  }

  var dblSame = null;           // сценарий `dbl`: второй щелчок пришелся в ту же строку окна

  async function libraryLoaded() {
    for (var tries = 0; dialog && dialog.loading && tries < 100; tries++) await sleep(50);
  }

  function dialogControl(selector, what) {
    var found = ui.dialogBox.querySelector(selector);
    if (!found) throw new Error("нет в окне " + what);
    return found;
  }

  function shownCount(selector) {
    return Array.prototype.filter.call(ui.dialogBox.querySelectorAll(selector), function (node) { return !node.hidden; }).length;
  }

  function publishResult() {
    var layout = {};
    try { layout = JSON.parse(document.getElementById("fm-result").textContent || "{}"); } catch (error) { /* нет итога */ }
    var current = ui.tree.querySelector(".fe-selected");
    var groups = Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-group-head"), function (head) { return head.textContent; });
    var props = Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-input"), function (input) {
      var entry = { prop: input.dataset.prop, set: !input.classList.contains("fe-default"),
        value: input.type === "checkbox" ? input.checked : input.value };
      if (input.placeholder) entry.placeholder = input.placeholder;
      if (input.tagName === "SELECT") {
        entry.options = Array.prototype.map.call(input.options, function (one) { return one.value; });
        entry.titles = Array.prototype.map.call(input.options, function (one) { return one.textContent; });
      }
      return entry;
    });
    var element = model && !blocked ? R.element(elementName(selected)) : null;
    ui.result.textContent = JSON.stringify({
      errors: errors,
      selected: selected,
      selectedText: element ? element.textContent.slice(0, 200) : null,
      layoutShown: !!document.querySelector("#fm-root .fm-window"),
      windowWidth: document.querySelector("#fm-root .fm-window") ? document.querySelector("#fm-root .fm-window").offsetWidth : 0,
      saveDisabled: ui.save.disabled,
      focused: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.prop || null : null,
      treeSelected: current ? current.dataset.key : null,
      treeKeys: visibleKeys(),
      // Открытое на макете меню (подменю, «Еще», список поля): пункты по порядку
      openMenu: Array.prototype.map.call(document.querySelectorAll("body > .fm-menu .fm-menu-text"), function (item) {
        return item.textContent;
      }),
      frame: frameShown,
      hidden: R.showHidden(),
      currentPages: layout.dom ? layout.dom.currentPages : {},
      collapsed: layout.dom ? layout.dom.collapsed : [],
      model: model,
      dirty: dirty(),
      status: ui.status.textContent,
      conflict: conflict,
      unreadable: unreadable,
      fileUpdated: fileUpdated,
      online: online,
      saveError: saveError,
      invalid: invalid,
      propsTitle: ui.propsTitle.textContent,
      groups: groups,
      props: props,
      leftMode: leftMode,
      attrSelected: attrSelected,
      attrRows: Array.prototype.map.call(ui.attrTree.querySelectorAll(".fe-row"), function (row) {
        var usage = row.querySelector(".fe-usage");
        return { path: row.dataset.path, readOnly: row.classList.contains("fe-pale"), element: usage ? usage.dataset.element : null };
      }),
      attrFit: Array.prototype.map.call(ui.attrTree.querySelectorAll(".fe-row"), rowFit),
      cmdSelected: cmdSelected,
      cmdRows: Array.prototype.map.call(ui.cmdTree.querySelectorAll(".fe-row"), function (row) {
        var usage = row.querySelector(".fe-usage");
        return { name: row.dataset.name, virtual: row.classList.contains("fe-pale"), element: usage ? usage.dataset.element : null };
      }),
      cmdFit: Array.prototype.map.call(ui.cmdTree.querySelectorAll(".fe-row"), rowFit),
      // Нажатые кнопки с пометкой на макете
      checkedButtons: Array.prototype.map.call(document.querySelectorAll("#fm-root .fm-button.fm-checked[data-name]"),
        function (button) { return button.dataset.name; }),
      foldedGroups: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-folded > .fe-group-head"), function (head) {
        return head.dataset.group;
      }),
      resets: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-reset"), function (button) { return button.dataset.prop; }),
      spins: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-up"), function (button) { return button.dataset.prop; }),
      issues: issues,
      blocked: blocked,
      dialog: dialog ? {
        kind: dialog.kind, mode: dialog.mode || null, chosen: dialog.chosen || null, cursor: dialog.cursor || null,
        error: dialog.error || "",
        rows: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-row"), function (row) {
          return { path: row.dataset.path, off: row.classList.contains("fe-pick-off") };
        }),
        names: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-name"), function (name) {
          return name.textContent;
        }),
        infos: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-row .fe-pick-info"), function (info) {
          return info.textContent;
        }),
        commands: Array.prototype.map.call(ui.dialogBox.querySelectorAll("input[data-command]"), function (box) {
          return { name: box.dataset.command, on: box.checked };
        }),
        tab: dialog.tab || null,
        tabs: dialog.tabs || null,
        groups: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-group"), function (head) {
          var rows = ui.dialogBox.querySelectorAll('.fe-pick-row[data-section="' + head.dataset.section + '"]');
          return { section: head.dataset.section, hidden: head.hidden,
            open: Array.prototype.some.call(rows, function (row) { return !row.hidden; }) };
        }),
        font: dialog.kind === "font" ? fontValue(dialog.font) || null : null,
        values: Array.prototype.map.call(ui.dialogBox.querySelectorAll(".fe-pick-row[data-value]"), function (row) {
          return row.dataset.value;
        }),
        value: dialog.kind === "format" ? formatText() : dialog.kind === "list" ? listValue() || [] : dialog.value,
        shown: (ui.dialogBox.querySelector(".fe-format-shown") || {}).textContent || null,
        colorRows: shownCount(".fe-color-row"),
        tiles: shownCount(".fe-picture-tile"),
        fillDisabled: !!(ui.dialogBox.querySelector('.fe-list-bar [data-command="fill"]') || {}).disabled,
        text: ui.dialogBox.querySelector(".fe-dialog-body") ? ui.dialogBox.querySelector(".fe-dialog-body").textContent : ""
      } : null,
      palette: ui.menu.hidden ? null : {
        note: (ui.menu.querySelector(".fe-menu-note") || {}).textContent || "",
        kinds: Array.prototype.map.call(ui.menu.querySelectorAll(".fe-menu-item[data-kind]"), function (row) { return row.dataset.kind; }),
        actions: Array.prototype.map.call(ui.menu.querySelectorAll(".fe-menu-action"), function (row) {
          return row.dataset.action + (row.disabled ? "-" : "");
        }),
        focused: (document.activeElement && ui.menu.contains(document.activeElement)) ?
          document.activeElement.dataset.action || document.activeElement.dataset.kind : null
      },
      undo: undoStack.length,
      redo: redoStack.length,
      // Несколько выделенных: выделение, заголовок панели, свойства «разные» и «недоступно», рамки
      picked: selection(),
      propsTitle: ui.propsTitle.textContent,
      mixedProps: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-mixed"), function (one) { return one.dataset.prop; }),
      unavailableProps: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-unavailable"), function (one) {
        return one.dataset.prop;
      }),
      frames: document.querySelectorAll(".fe-frame").length,
      dropAccepted: dropAccepted,
      dblSame: dblSame,
      fillStandard: ui.propsBody.querySelector(".fe-fill-standard") ?
        !ui.propsBody.querySelector(".fe-fill-standard").disabled : null,
      tools: { add: !ui.addButton.disabled, "delete": !ui.deleteButton.disabled, up: !ui.upButton.disabled,
        down: !ui.downButton.disabled },
      // Правки против «было»: что показано в дереве, панели, списке и на макете
      diff: {
        on: diffOn,
        label: ui.diffLabel.textContent,
        base: baseFile,
        changes: changes && changes.map(function (change) {
          return { n: change.n, op: change.op, after: change.after || null, before: change.before || null };
        }),
        tab: diffOn ? rightTab : null,
        active: activeChange,
        tree: Array.prototype.map.call(ui.tree.querySelectorAll(".fe-row[data-change]"), function (row) {
          return [row.dataset.key || "-" + row.dataset.removed, Number(row.dataset.change)];
        }),
        props: Array.prototype.map.call(ui.propsBody.querySelectorAll(".fe-prop-diff"), function (row) {
          return row.dataset.prop || row.querySelector(".fe-input").dataset.prop;
        }),
        header: (ui.propsBody.querySelector(".fe-props-change") || {}).textContent || null,
        list: Array.prototype.map.call(ui.changesBody.querySelectorAll(".fe-change"), function (item) {
          return Number(item.dataset.change);
        }),
        frames: (layout.dom && layout.dom.diffFrames) || [],
        mode: layout.dom ? layout.dom.mode : null
      },
      // Примечания: закладка, строки списка, номера на макете
      notes: {
        tab: rightTab,
        label: ui.tabNotes.textContent,
        rows: Array.prototype.map.call(ui.notesBody.querySelectorAll(".fe-note"), function (line) {
          return { key: line.dataset.key, n: line.querySelector(".fm-diff-badge").textContent,
            text: line.querySelector(".fe-note-text").value };
        }),
        focused: document.activeElement && document.activeElement.classList.contains("fe-note-text") ?
          document.activeElement.dataset.key : null,
        frames: (layout.dom && layout.dom.noteFrames) || []
      },
      renderMs: renderMs
    });
  }

  async function start() {
    // Отметка вкладки: макет и несохраненные правки - для предупреждения «Завершить»
    FMAlive.start({ file: new URLSearchParams(location.search).get("file") || ED.file, dirty: false });
    // «Завершить» на списке (владелец 08.11.2026): окно конструктора закрывается; несохраненные правки список уже
    // показал и человек подтвердил - второго вопроса браузера нет
    FMAlive.onQuit(function () {
      quitting = true;
      window.close();
    });
    setupPage();
    renderStatus();
    await load(false);
    setInterval(poll, POLL_MS);
    var actions = actionsOf();
    try {
      for (var i = 0; i < actions.length; i++) {
        await runAction(actions[i]);
        await sleep(0);
      }
    } catch (error) {
      errors.push(String(error && error.stack || error));
    }
    // Слой рамок перерисовывается в следующем кадре (`R.redraw`), а в Chrome без окна кадр может не прийти: перед
    // итогом - перерисовка сразу, иначе на итоге рамки до последнего действия
    R.drawNow();
    publishResult();
  }

  start();
})();
