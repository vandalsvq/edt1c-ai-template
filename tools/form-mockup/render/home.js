/* Стартовая страница сервиса макетов: список макетов папки с миниатюрами, «Новая форма»,
   «Импорт из 1С» (перетаскивание Form.xml / Form.form или форма из исходников), «Другая папка», исходники
   конфигурации у папки. Данные - у сервера (`GET /models`), страница только показывает и просит.
   Итог для тестов - `#fh-result`: {folder, src, models, error}. */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("fh-data").textContent);
  var root = document.getElementById("fh-root");
  // `tags` - выбранные метки фильтра, `collapsed` - свернутые группы (помнятся в браузере)
  // `#tags=метка,метка` - фильтр меток сразу (тесты)
  var state = { info: null, error: "", filter: "", stopped: false, collapsed: readCollapsed(),
    tags: decodeURIComponent((location.hash.match(/[#&]tags=([^&]*)/) || [])[1] || "").split(",").filter(Boolean) };

  function readCollapsed() {
    try { return JSON.parse(localStorage.getItem("fh-collapsed") || "{}") || {}; } catch (error) { return {}; }
  }

  function saveCollapsed() {
    try { localStorage.setItem("fh-collapsed", JSON.stringify(state.collapsed)); } catch (error) { /* без памяти */ }
  }
  var scriptErrors = [];
  window.addEventListener("error", function (event) {
    scriptErrors.push(String(event.message));
    report();
  });

  // Разметка

  function h(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function button(text, action, className) {
    var node = h("button", "fh-button" + (className ? " " + className : ""), text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  function linkButton(text, action) {
    var node = h("button", "fh-link", text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  // Сервер

  // Правки папки - с папкой, которую показывает страница: другая вкладка могла переключить сервис на другую
  // папку, и «Удалить» или «Перенести» попали бы в одноименный макет новой папки. Сервер ответит 409 folderChanged -
  // список перечитывается. Чтение и само переключение папки - без нее
  function withFolder(method, path) {
    var folder = state.info && state.info.folder;
    if (!folder || method === "GET" || path.split("?")[0] === "/folder") return path;
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + "folder=" + encodeURIComponent(folder);
  }

  async function api(method, path, body) {
    var options = { method: method, cache: "no-store", headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    var response = await fetch(withFolder(method, path), options);
    var text = await response.text();
    var data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (error) { data = { error: text }; }
    if (!response.ok && data.folderChanged) {
      load();
      throw new Error("папка макетов сменилась в другой вкладке - список перечитан, действие не выполнено");
    }
    if (!response.ok) throw new Error(data.error || ("ошибка сервера " + response.status));
    return data;
  }

  async function load() {
    try {
      state.info = await api("GET", "/models");
      state.error = "";
    } catch (error) {
      state.error = "Список макетов не получен: " + error.message;
    }
    draw();
    // `#open=new|import|config|mockups|group|folder|src` - сразу открыть окно (сценарии тестов и снимки для README)
    var open = (location.hash.match(/(?:^#|&)open=(\w+)/) || [])[1];
    if (open && !opened) {
      opened = true;
      ({ "new": newForm, "import": function () { importForm(null); }, "config": function () { importForm(null, "config"); },
         "mockups": function () { importForm(null, "mockups"); }, "group": newGroup,
         // `#open=delete|menu&file=<путь>` - окно удаления и контекстное меню макета
         "delete": function () { var model = hashModel(); if (model) deleteDialog(model); },
         "menu": function () {
           var model = hashModel();
           var card = model && document.querySelector('.fh-card[data-file="' + CSS.escape(model.file) + '"]');
           if (card) cardMenu(card, model, { x: 40, y: 40 });
         },
         "folder": function () { pickFolder("folder"); }, "src": function () { pickFolder("src"); },
         "quit": quit }[open] || function () {})();
      report();
    }
  }
  var opened = false;

  function report() {
    var info = state.info || {};
    document.getElementById("fh-result").textContent = JSON.stringify({
      folder: info.folder || null, src: info.src || null, suggestedSrc: info.suggestedSrc || null,
      extensions: info.extensions || [], suggestedProjects: info.suggestedProjects || null,
      projects: info.projects ? info.projects.items.map(function (item) {
        return { name: item.name, extension: item.extension, base: item.base };
      }) : null,
      choices: Array.prototype.map.call(document.querySelectorAll(".fh-project input:checked"), function (input) {
        return input.value;
      }),
      models: (info.models || []).map(function (model) { return model.file; }), error: state.error, stopped: state.stopped,
      // Разделы списка: группа → макеты на странице (свернутая - null)
      sections: Array.prototype.map.call(document.querySelectorAll(".fh-group"), function (section) {
        var grid = section.querySelector(".fh-grid");
        return [section.dataset.group, section.querySelector(".fh-group-toggle").getAttribute("aria-expanded") === "true"
          ? Array.prototype.map.call(grid ? grid.querySelectorAll(".fh-card") : [], function (card) { return card.dataset.file; })
          : null];
      }),
      tags: info.tags || [],
      menu: Array.prototype.map.call(document.querySelectorAll(".fh-menu .fh-menu-item"), function (item) {
        return item.textContent;
      }),
      // Горизонтальной прокрутки у страницы быть не должно ни при какой ширине окна
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      dialog: (document.querySelector("dialog[open] .fh-dialog-head") || {}).textContent || null,
      errors: scriptErrors
    });
  }

  // Виды объектов метаданных - для списка форм конфигурации
  var OBJECT_KINDS = {
    Catalog: "Справочник", Document: "Документ", DataProcessor: "Обработка", Report: "Отчет", Enum: "Перечисление",
    InformationRegister: "Регистр сведений", AccumulationRegister: "Регистр накопления",
    AccountingRegister: "Регистр бухгалтерии", CalculationRegister: "Регистр расчета",
    ChartOfCharacteristicTypes: "План видов характеристик", ChartOfAccounts: "План счетов",
    ChartOfCalculationTypes: "План видов расчета", ExchangePlan: "План обмена", BusinessProcess: "Бизнес-процесс",
    Task: "Задача", DocumentJournal: "Журнал документов", CommonForm: "Общая форма", FilterCriterion: "Критерий отбора",
    SettingsStorage: "Хранилище настроек"
  };

  // Дерево «Из конфигурации» - как дерево метаданных конфигуратора (владелец 08.11.2026):
  // вид - объект - форма; планы обмена, критерии отбора, хранилища настроек и общие формы - в «Общих»; формы
  // нескольких проектов (конфигурация и расширения) - под своим проектом. Значки - `metadata-icons.json`
  var COMMON_KINDS = ["ExchangePlan", "FilterCriterion", "SettingsStorage", "CommonForm"];
  var KIND_ORDER = ["Catalog", "Document", "DocumentJournal", "Enum", "Report", "DataProcessor",
    "ChartOfCharacteristicTypes", "ChartOfAccounts", "ChartOfCalculationTypes", "InformationRegister",
    "AccumulationRegister", "AccountingRegister", "CalculationRegister", "BusinessProcess", "Task"];
  var KIND_PLURAL = {
    ExchangePlan: "Планы обмена", FilterCriterion: "Критерии отбора", SettingsStorage: "Хранилища настроек",
    CommonForm: "Общие формы", Catalog: "Справочники", Document: "Документы", DocumentJournal: "Журналы документов",
    Enum: "Перечисления", Report: "Отчеты", DataProcessor: "Обработки", ChartOfCharacteristicTypes: "Планы видов характеристик",
    ChartOfAccounts: "Планы счетов", ChartOfCalculationTypes: "Планы видов расчета", InformationRegister: "Регистры сведений",
    AccumulationRegister: "Регистры накопления", AccountingRegister: "Регистры бухгалтерии",
    CalculationRegister: "Регистры расчета", BusinessProcess: "Бизнес-процессы", Task: "Задачи"
  };

  // `all` - все формы: уровень проектов от поиска не зависит; `layered` - к конфигурации подключены расширения:
  // проект верхним уровнем, даже если формы есть только у одного
  function formTree(forms, all, layered) {
    var projects = [];
    all.forEach(function (form) {
      if (projects.indexOf(form.project || "") < 0) projects.push(form.project || "");
    });
    var counted = function (node) {
      node.count = node.children.reduce(function (sum, child) { return sum + (child.form ? 1 : child.count); }, 0);
      return node;
    };
    var kindNode = function (prefix, kind, own) {
      var objects = [];
      var byObject = {};
      own.filter(function (form) { return form.kind === kind; }).forEach(function (form) {
        var leaf = { key: prefix + form.key, title: form.form, icon: "Form", form: form };
        if (kind === "CommonForm") {
          leaf.icon = "CommonForm";
          objects.push(leaf);
          return;
        }
        if (!byObject[form.object]) {
          byObject[form.object] = { key: prefix + kind + "." + form.object, title: form.object, icon: kind, children: [] };
          objects.push(byObject[form.object]);
        }
        byObject[form.object].children.push(leaf);
      });
      objects.forEach(function (node) { if (node.children) counted(node); });
      return objects.length ? counted({ key: prefix + kind, title: KIND_PLURAL[kind] || kind, icon: kind, children: objects })
        : null;
    };
    var kindsOf = function (prefix, own) {
      var common = COMMON_KINDS.map(function (kind) { return kindNode(prefix, kind, own); }).filter(Boolean);
      var nodes = common.length ? [counted({ key: prefix + "Common", title: "Общие", icon: "Common", children: common })] : [];
      var known = COMMON_KINDS.concat(KIND_ORDER);
      var other = own.map(function (form) { return form.kind; }).filter(function (kind, index, all) {
        return known.indexOf(kind) < 0 && all.indexOf(kind) === index;
      });
      return nodes.concat(KIND_ORDER.concat(other).map(function (kind) { return kindNode(prefix, kind, own); }).filter(Boolean));
    };
    if (projects.length < 2 && !layered) return kindsOf("", forms);
    return projects.filter(function (project) {
      return forms.some(function (form) { return (form.project || "") === project; });
    }).map(function (project) {
      var own = forms.filter(function (form) { return (form.project || "") === project; });
      return counted({ key: "@" + project + "/", title: project || "Конфигурация", icon: "Configuration", project: true,
        children: kindsOf("@" + project + "/", own) });
    });
  }

  function kindTitle(kind) {
    var found = DATA.formKinds.filter(function (item) { return item.kind === kind; })[0];
    return found ? found.title : kind;
  }

  function editUrl(file) {
    return "/edit?file=" + encodeURIComponent(file);
  }

  // Страница

  function draw() {
    root.textContent = "";
    if (state.stopped) {
      drawStopped();
      return;
    }
    var info = state.info || { models: [] };
    document.title = "Макеты форм" + (info.folder ? " - " + info.folder : "");

    var head = h("header", "fh-head");
    var top = h("div", "fh-row");
    top.appendChild(h("h1", "fh-title", "Макеты форм"));
    top.appendChild(h("span", "fh-label", "Папка:"));
    top.appendChild(h("span", "fh-path", info.folder || ""));
    top.appendChild(linkButton("Другая папка", function () { pickFolder("folder"); }));
    top.appendChild(h("span", "fh-spacer"));
    var quitButton = button("Завершить", quit, "fh-quit");
    quitButton.title = "Остановить сервис макетов; без открытых страниц он остановится и сам через минуту";
    top.appendChild(quitButton);
    head.appendChild(top);

    var source = h("div", "fh-row");
    if (info.projects) {
      source.appendChild(h("span", "fh-label", "Папка проектов:"));
      source.appendChild(h("span", "fh-path", info.projects.folder));
      source.appendChild(linkButton("Сменить", function () { pickFolder("src"); }));
      source.appendChild(linkButton("Убрать", function () { setProjects(null); }));
      head.appendChild(source);
      head.appendChild(projectsBlock(info));
    } else {
      source.appendChild(h("span", "fh-label", "Конфигурация:"));
      if (info.src) {
        source.appendChild(h("span", "fh-path", info.src));
        if (info.srcPinned) {
          source.appendChild(h("span", "fh-note", "(заданы при запуске - на этот запуск)"));
        }
        source.appendChild(linkButton("Сменить", function () { pickFolder("src"); }));
        source.appendChild(linkButton("Убрать", function () { setSource(null); }));
      } else {
        source.appendChild(h("span", "fh-note", "не задана - окна выбора типа, картинки и цвета видят только макет"));
        source.appendChild(linkButton("Указать", function () { pickFolder("src"); }));
      }
      head.appendChild(source);
    }

    var nearby = info.suggestedProjects || info.suggestedSrc;
    if (nearby) {
      var suggest = h("div", "fh-suggest");
      suggest.appendChild(h("span", "", info.suggestedProjects ? "Рядом найдены конфигурации:" : "Рядом найдены исходники конфигурации:"));
      suggest.appendChild(h("span", "fh-path", nearby));
      suggest.appendChild(button("Использовать", function () {
        if (info.suggestedProjects) setProjects(info.suggestedProjects);
        else setSource(info.suggestedSrc);
      }, "fh-main"));
      head.appendChild(suggest);
    }

    var tools = h("div", "fh-row");
    tools.appendChild(button("Новая форма", newForm, "fh-main"));
    tools.appendChild(button("Импорт из 1С", function () { importForm(null); }));
    tools.appendChild(button("Новая группа", newGroup));
    var search = h("input", "fh-input fh-search");
    search.type = "search";
    search.placeholder = "Найти макет";
    search.value = state.filter;
    search.addEventListener("input", function () { state.filter = search.value; drawList(list); });
    tools.appendChild(search);
    tools.appendChild(h("span", "fh-spacer"));
    tools.appendChild(button("Обновить", load));
    head.appendChild(tools);
    var tagRow = h("div", "fh-row fh-tag-row");
    head.appendChild(tagRow);
    drawTagRow(tagRow, function () { drawList(list); });

    if (state.error) head.appendChild(h("div", "fh-error", state.error));
    // Сообщение об удавшемся действии вне списка (копия в другую папку, удаление со ссылкой «Вернуть») - один раз
    if (state.notice) {
      var notice = h("div", "fh-suggest fh-notice", typeof state.notice === "string" ? state.notice : state.notice.text);
      if (state.notice.undo) notice.appendChild(linkButton("Вернуть", state.notice.undo));
      head.appendChild(notice);
    }
    state.notice = "";
    root.appendChild(head);

    var body = h("main", "fh-body");
    var list = h("div");
    body.appendChild(list);
    root.appendChild(body);
    drawList(list);
    report();
  }

  // Метки папки: щелчок оставляет макеты с меткой, несколько выбранных - все сразу
  function drawTagRow(row, redraw) {
    var tags = (state.info && state.info.tags) || [];
    state.tags = state.tags.filter(function (tag) { return tags.indexOf(tag) >= 0; });
    row.textContent = "";
    row.hidden = !tags.length;
    row.appendChild(h("span", "fh-label", "Метки:"));
    tags.forEach(function (tag) {
      var chip = h("button", "fh-tag fh-tag-filter", tag);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(state.tags.indexOf(tag) >= 0));
      chip.addEventListener("click", function () {
        var at = state.tags.indexOf(tag);
        if (at >= 0) state.tags.splice(at, 1);
        else state.tags.push(tag);
        drawTagRow(row, redraw);
        redraw();
      });
      row.appendChild(chip);
    });
    if (state.tags.length) {
      row.appendChild(linkButton("Сбросить", function () { state.tags = []; drawTagRow(row, redraw); redraw(); }));
    }
  }

  function modelShown(model, needle) {
    var tags = model.tags || [];
    var text = (model.title + " " + model.file + " " + tags.join(" ")).toLowerCase();
    return (!needle || text.indexOf(needle) >= 0) && state.tags.every(function (tag) { return tags.indexOf(tag) >= 0; });
  }

  // Макеты разделами по группам - подкаталогам папки: корень - «Без группы», раздел сворачивается;
  // при поиске и фильтре пустые разделы не показываются
  function drawList(list) {
    list.textContent = "";
    var info = state.info || {};
    var models = info.models || [];
    var needle = state.filter.trim().toLowerCase();
    var filtering = !!needle || state.tags.length > 0;
    var shown = models.filter(function (model) { return modelShown(model, needle); });
    var groups = [""].concat(info.groups || []);
    if (!models.length && groups.length === 1) {
      list.appendChild(h("div", "fh-empty",
        "В папке нет макетов. «Новая форма» - начать с пустой формы, «Импорт из 1С» - из Form.xml или Form.form."));
      return;
    }
    if (filtering && !shown.length) {
      list.appendChild(h("div", "fh-empty", "Ничего не найдено"));
      return;
    }
    groups.forEach(function (group) {
      var own = shown.filter(function (model) { return (model.group || "") === group; });
      var total = models.filter(function (model) { return (model.group || "") === group; }).length;
      if (!own.length && (filtering || (group === "" && groups.length > 1))) return;
      list.appendChild(groupSection(group, own, total));
    });
  }

  function groupSection(group, own, total) {
    var section = h("section", "fh-group");
    section.dataset.group = group;
    var collapsed = !!state.collapsed[group];
    var head = h("div", "fh-group-head");
    var toggle = h("button", "fh-group-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.appendChild(h("span", "fh-group-mark", collapsed ? "+" : "\u2212"));
    toggle.appendChild(h("span", "fh-group-name", group || "Без группы"));
    toggle.appendChild(h("span", "fh-group-count", String(own.length)));
    toggle.addEventListener("click", function () {
      if (collapsed) delete state.collapsed[group];
      else state.collapsed[group] = true;
      saveCollapsed();
      var fresh = groupSection(group, own, total);
      section.replaceWith(fresh);
      report();
    });
    head.appendChild(toggle);
    if (group && !total) {
      head.appendChild(h("span", "fh-note", "пустая группа"));
      head.appendChild(linkButton("Удалить группу", function () { deleteGroup(group); }));
    }
    section.appendChild(head);
    if (collapsed) return section;
    if (!own.length) {
      section.appendChild(h("div", "fh-group-empty", "Макетов нет: «Новая форма», «Импорт из 1С» или «Переместить в...» у макета."));
      return section;
    }
    var grid = h("div", "fh-grid");
    own.forEach(function (model) { grid.appendChild(modelCard(model)); });
    section.appendChild(grid);
    return section;
  }

  function modelCard(model) {
    var box = h("div", "fh-card-box");
    var card = FMAlive.link(h("a", "fh-card"));
    card.href = editUrl(model.file);
    card.dataset.file = model.file;
    var thumb = h("div", "fh-thumb");
    var frame = h("iframe");
    frame.loading = "lazy";
    frame.tabIndex = -1;
    frame.title = model.title;
    frame.src = "/thumb?file=" + encodeURIComponent(model.file) + "#static";
    frame.addEventListener("load", function () { fitThumb(thumb, frame); });
    thumb.appendChild(frame);
    card.appendChild(thumb);
    var text = h("div", "fh-card-text");
    text.appendChild(h("div", "fh-card-title", model.title));
    text.appendChild(h("div", "fh-card-file", model.file));
    var when = model.modified ? model.modified.replace("T", " ").slice(0, 16) : "";
    text.appendChild(h("div", "fh-card-meta", [kindTitle(model.kind), when].filter(Boolean).join(" · ")));
    if ((model.tags || []).length) {
      var tags = h("div", "fh-card-tags");
      model.tags.forEach(function (tag) { tags.appendChild(h("span", "fh-tag", tag)); });
      text.appendChild(tags);
    }
    card.appendChild(text);
    box.appendChild(card);
    // Действия макета: кнопка поверх карточки, вне ссылки - щелчок не открывает конструктор
    var more = h("button", "fh-card-more", "⋯");
    more.type = "button";
    more.title = "Метки, перенос, копирование";
    more.setAttribute("aria-label", "Действия с макетом " + model.title);
    more.addEventListener("click", function (event) {
      event.stopPropagation();
      cardMenu(more, model);
    });
    box.appendChild(more);
    // Контекстное меню - правой кнопкой по карточке, то же, что «⋯» (владелец 08.11.2026)
    box.addEventListener("contextmenu", function (event) {
      event.preventDefault();
      cardMenu(card, model, { x: event.clientX, y: event.clientY });
    });
    return box;
  }

  // Макет из адреса `&file=<путь>` (тесты окон и меню)
  function hashModel() {
    var file = decodeURIComponent((location.hash.match(/[#&]file=([^&]*)/) || [])[1] || "");
    return ((state.info && state.info.models) || []).filter(function (model) { return model.file === file; })[0] || null;
  }

  // Меню макета: кнопка «⋯» (под ней) и правая кнопка мыши (у курсора, `point`). Стрелки - по пунктам, Esc - закрыть
  function cardMenu(anchor, model, point) {
    closeCardMenu();
    var menu = h("div", "fh-menu");
    menu.setAttribute("role", "menu");
    menu.dataset.file = model.file;
    var items = [
      ["Открыть", function () { FMAlive.go(editUrl(model.file)); }],
      ["Открыть в новой вкладке", function () { window.open(editUrl(model.file), "_blank"); }],
      null,
      ["Метки...", function () { tagsDialog(model); }],
      ["Переместить в...", function () { moveDialog(model); }],
      ["Копировать в...", function () { copyDialog(model); }],
      ["Дублировать", function () { duplicate(model); }],
      ["Скопировать путь к файлу", function () { copyPath(model); }],
      null,
      ["Удалить...", function () { deleteDialog(model); }, "fh-menu-danger"]
    ];
    items.forEach(function (entry) {
      if (!entry) {
        menu.appendChild(h("div", "fh-menu-sep"));
        return;
      }
      var item = h("button", "fh-menu-item" + (entry[2] ? " " + entry[2] : ""), entry[0]);
      item.type = "button";
      item.setAttribute("role", "menuitem");
      item.addEventListener("click", function () { closeCardMenu(); entry[1](); });
      menu.appendChild(item);
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      var buttons = Array.prototype.slice.call(menu.querySelectorAll("button"));
      var at = buttons.indexOf(document.activeElement);
      var next = (at + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length;
      buttons[next].focus();
    });
    document.body.appendChild(menu);
    var width = menu.offsetWidth;
    var height = menu.offsetHeight;
    var left, top;
    if (point) {
      left = Math.min(point.x, window.innerWidth - width - 8);
      top = point.y + height + 8 > window.innerHeight ? Math.max(8, point.y - height) : point.y;
    } else {
      var rect = anchor.getBoundingClientRect();
      left = rect.right - width;
      top = rect.bottom + 4;
    }
    menu.style.left = (Math.max(8, left) + window.scrollX) + "px";
    menu.style.top = (Math.max(8, top) + window.scrollY) + "px";
    menu.querySelector("button").focus({ preventScroll: true });
    report();
  }

  function closeCardMenu() {
    Array.prototype.forEach.call(document.querySelectorAll(".fh-menu"), function (menu) { menu.remove(); });
  }

  // «Дублировать» - копия рядом, в той же группе, без окна; сервер дает свободное имя (`имя-2.json`)
  async function duplicate(model) {
    try {
      var result = await api("POST", "/models", { file: model.file, copyFrom: model.file });
      state.info = await api("GET", "/models");
      state.error = "";
      state.notice = "Копия: " + result.file;
    } catch (error) {
      state.error = "Копия не создана: " + error.message;
    }
    draw();
  }

  // Полный путь файла - для агента, проводника, письма; без доступа к буферу - путь в сообщении
  function copyPath(model) {
    var folder = (state.info && state.info.folder) || "";
    var separator = folder.indexOf("\\") >= 0 ? "\\" : "/";
    var path = folder + separator + model.file.split("/").join(separator);
    var shown = function (copied) {
      state.notice = (copied ? "Путь скопирован: " : "Путь к файлу: ") + path;
      draw();
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(path).then(function () { shown(true); }, function () { shown(false); });
    } else {
      shown(false);
    }
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest || !event.target.closest(".fh-menu, .fh-card-more")) closeCardMenu();
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") closeCardMenu(); });

  // Миниатюра - страница рендерера того же сервера: после отрисовки мерим форму и вписываем ее в карточку целиком
  function fitThumb(thumb, frame) {
    var doc;
    try { doc = frame.contentDocument; } catch (error) { return; }
    if (!doc || !doc.body) return;
    var apply = function () {
      // Мерим окно формы (`.fm-window` рендерера), а не страницу: страница занимает все окно iframe
      var win = doc.querySelector(".fm-window");
      var box = win ? win.getBoundingClientRect() : { right: doc.documentElement.scrollWidth, bottom: doc.documentElement.scrollHeight };
      var width = Math.max(Math.ceil(box.right + 8), 1);
      var height = Math.max(Math.ceil(box.bottom + 8), 1);
      var scale = Math.min(thumb.clientWidth / width, thumb.clientHeight / height, 1);
      frame.style.width = width + "px";
      frame.style.height = height + "px";
      frame.style.transform = "scale(" + scale + ")";
      frame.style.left = Math.max(0, (thumb.clientWidth - width * scale) / 2) + "px";
    };
    // Рендерер раскладывает форму после загрузки - мерим на следующих кадрах
    requestAnimationFrame(function () { requestAnimationFrame(apply); });
    thumb.fitThumb = apply;
  }

  window.addEventListener("resize", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".fh-thumb"), function (thumb) {
      if (thumb.fitThumb) thumb.fitThumb();
    });
  });

  // Завершить: несохраненные правки в открытых конструкторах - предупреждение до остановки

  async function quit() {
    try {
      await stop(false);
    } catch (error) {
      if (!error.dirty) {
        state.error = "Сервис не остановлен: " + error.message;
        draw();
        return;
      }
      var box = dialog("Завершить работу с макетами");
      box.body.appendChild(h("div", "", "Есть несохранённые правки:"));
      var list = h("ul", "fh-dirty");
      error.dirty.forEach(function (file) { list.appendChild(h("li", "", file || "макет")); });
      box.body.appendChild(list);
      box.body.appendChild(h("div", "", "Завершить без сохранения? Правки будут потеряны."));
      box.body.appendChild(box.error);
      var ok = button("Завершить", function () {
        ok.disabled = true;
        stop(true).then(box.close, function (failure) { box.fail(failure.message); ok.disabled = false; });
      }, "fh-main");
      box.foot.appendChild(button("Отмена", box.close));
      box.foot.appendChild(ok);
      box.node.showModal();
      report();
    }
  }

  async function stop(force) {
    var response = await fetch("/shutdown", {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: force })
    });
    var data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    if (!response.ok) {
      var failure = new Error(data.error || ("ошибка сервера " + response.status));
      failure.dirty = response.status === 409 ? (data.dirty || []) : null;
      throw failure;
    }
    // Остальные окна сервиса (конструкторы, второй список) закрываются сами; это окно - следом. Не дал браузер
    // (вкладка с историей переходов) - остается страница «Сервис макетов остановлен»
    FMAlive.quitAll();
    stopped();
  }

  function stopped() {
    state.stopped = true;
    draw();
    window.close();
  }

  FMAlive.onQuit(stopped);

  function drawStopped() {
    document.title = "Макеты форм - сервис остановлен";
    var box = h("div", "fh-stopped");
    box.appendChild(h("h1", "fh-title", "Сервис макетов остановлен"));
    box.appendChild(h("p", "", "Окно можно закрыть. Снова открыть макеты - ярлыком «Открыть макеты»."));
    root.appendChild(box);
    report();
  }

  // Окна

  function dialog(title) {
    var node = h("dialog", "fh-dialog");
    var form = h("form", "fh-dialog-form");
    form.method = "dialog";
    form.appendChild(h("div", "fh-dialog-head", title));
    var body = h("div", "fh-dialog-body");
    var error = h("div", "fh-error");
    error.hidden = true;
    var foot = h("div", "fh-dialog-foot");
    form.appendChild(body);
    form.appendChild(foot);
    node.appendChild(form);
    document.body.appendChild(node);
    node.addEventListener("close", function () { node.remove(); });
    return {
      node: node, body: body, foot: foot, error: error,
      fail: function (text) { error.textContent = text; error.hidden = !text; },
      close: function () { node.close(); }
    };
  }

  function field(label, input) {
    var box = h("label", "fh-field");
    box.appendChild(h("span", "fh-label", label));
    box.appendChild(input);
    return box;
  }

  function freeName(base) {
    var taken = {};
    ((state.info && state.info.models) || []).forEach(function (model) { taken[model.file.toLowerCase()] = true; });
    var name = base + ".json";
    for (var index = 2; taken[name.toLowerCase()]; index++) name = base + " " + index + ".json";
    return name;
  }

  function withJson(name) {
    name = name.trim();
    return /\.json$/i.test(name) ? name : name + ".json";
  }

  // Группы, метки, перенос, копирование

  function groupSelect(selected) {
    var select = h("select", "fh-input");
    [""].concat((state.info && state.info.groups) || []).forEach(function (group) {
      var option = h("option", "", group || "Без группы");
      option.value = group;
      option.selected = group === (selected || "");
      select.appendChild(option);
    });
    return select;
  }

  function fileName(file) {
    return file.split("/").pop();
  }

  function inGroup(group, name) {
    return (group ? group + "/" : "") + name;
  }

  // Обновить список по ответу сервера (у групп и меток - сразу `GET /models`) и закрыть окно
  async function done(box, okButton, request) {
    okButton.disabled = true;
    box.fail("");
    try {
      var result = await request();
      if (result && result.models) state.info = result;
      else state.info = await api("GET", "/models");
      state.error = "";
      box.close();
      draw();
    } catch (error) {
      box.fail(error.message);
      okButton.disabled = false;
    }
  }

  function newGroup() {
    var box = dialog("Новая группа");
    var name = h("input", "fh-input");
    name.placeholder = "Задача-12 или Задачи/Задача-12";
    var ok = button("Создать", function () {
      done(box, ok, function () { return api("POST", "/groups", { group: name.value.trim() }); });
    }, "fh-main");
    box.body.appendChild(field("Имя группы (подкаталог папки макетов; вложенная - через /)", name));
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    name.addEventListener("keydown", function (event) { if (event.key === "Enter") { event.preventDefault(); ok.click(); } });
    box.node.showModal();
    name.focus();
  }

  async function deleteGroup(group) {
    try {
      state.info = await api("DELETE", "/groups?group=" + encodeURIComponent(group));
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
    draw();
  }

  // Метки макета: список с удалением, ввод с подсказкой из меток папки; Enter или запятая - добавить
  function tagsDialog(model) {
    var box = dialog("Метки: " + model.title);
    var tags = (model.tags || []).slice();
    var chips = h("div", "fh-row fh-tag-edit");
    var input = h("input", "fh-input");
    input.placeholder = "Новая метка, Enter - добавить";
    var known = h("datalist");
    known.id = "fh-known-tags";
    ((state.info && state.info.tags) || []).forEach(function (tag) {
      var option = h("option");
      option.value = tag;
      known.appendChild(option);
    });
    input.setAttribute("list", known.id);
    function drawChips() {
      chips.textContent = "";
      if (!tags.length) chips.appendChild(h("span", "fh-note", "Меток нет"));
      tags.forEach(function (tag, index) {
        var chip = h("span", "fh-tag", tag);
        var remove = h("button", "fh-tag-remove", "×");
        remove.type = "button";
        remove.title = "Убрать метку";
        remove.addEventListener("click", function () { tags.splice(index, 1); drawChips(); });
        chip.appendChild(remove);
        chips.appendChild(chip);
      });
    }
    function add() {
      input.value.split(",").forEach(function (part) {
        var tag = part.trim();
        if (tag && tags.indexOf(tag) < 0) tags.push(tag);
      });
      input.value = "";
      drawChips();
    }
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        add();
      }
    });
    var ok = button("Сохранить", function () {
      add();
      done(box, ok, function () { return api("PUT", "/tags", { file: model.file, tags: tags }); });
    }, "fh-main");
    drawChips();
    box.body.appendChild(chips);
    box.body.appendChild(input);
    box.body.appendChild(known);
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    input.focus();
  }

  // Удаление: в корзину папки `.trash`, после - сообщение со ссылкой «Вернуть»
  function deleteDialog(model) {
    var box = dialog("Удалить макет");
    box.body.appendChild(h("div", "", "Удалить «" + model.title + "» (" + model.file + ")?"));
    box.body.appendChild(h("div", "fh-note", "Файл уйдет в корзину папки макетов (скрытый каталог .trash) - вернуть " +
      "можно ссылкой «Вернуть» сразу после удаления или перенести файл из корзины руками."));
    box.body.appendChild(box.error);
    var ok = button("Удалить", function () {
      done(box, ok, function () {
        return api("POST", "/delete", { file: model.file }).then(function (result) {
          state.notice = { text: "Макет «" + model.title + "» удален. ", undo: function () { restore(result.trashed); } };
          return null;
        });
      });
    }, "fh-main fh-danger");
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    ok.focus();
  }

  async function restore(trashed) {
    try {
      await api("POST", "/restore", { trashed: trashed });
      state.info = await api("GET", "/models");
      state.error = "";
    } catch (error) {
      state.error = "Макет не возвращен: " + error.message;
    }
    draw();
  }

  function moveDialog(model) {
    var box = dialog("Переместить: " + model.title);
    var select = groupSelect(model.group);
    var ok = button("Переместить", function () {
      done(box, ok, function () { return api("POST", "/move", { file: model.file, to: select.value }); });
    }, "fh-main");
    box.body.appendChild(field("Группа", select));
    box.body.appendChild(h("div", "fh-note", "Файл переносится в подкаталог группы, метки остаются. Открытый в " +
      "конструкторе макет не переносится - сначала закройте его вкладку."));
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    select.focus();
  }

  // Копия: в группу этой папки или в другую папку макетов; занятое имя сервер дополнит номером
  function copyDialog(model) {
    var box = dialog("Копировать: " + model.title);
    var where = { other: "" };
    var modes = h("div", "fh-tabs");
    var herePane = h("div", "fh-field");
    var otherPane = h("div", "fh-field");
    var select = groupSelect(model.group);
    var name = h("input", "fh-input");
    name.value = fileName(model.file);
    var otherPath = h("div", "fh-path", "папка не выбрана");
    var otherName = h("input", "fh-input");
    otherName.value = fileName(model.file);
    var mode = "here";
    function selectMode(value) {
      mode = value;
      Array.prototype.forEach.call(modes.children, function (node) {
        node.setAttribute("aria-selected", String(node.dataset.tab === value));
      });
      herePane.hidden = value !== "here";
      otherPane.hidden = value !== "other";
      ok.disabled = value === "other" && !where.other;
    }
    [["here", "В эту папку"], ["other", "В другую папку"]].forEach(function (pair) {
      var tab = h("button", "fh-tab", pair[1]);
      tab.type = "button";
      tab.dataset.tab = pair[0];
      tab.addEventListener("click", function () { selectMode(pair[0]); });
      modes.appendChild(tab);
    });
    herePane.appendChild(field("Группа", select));
    herePane.appendChild(field("Имя файла", name));
    var pickRow = h("div", "fh-row");
    pickRow.appendChild(otherPath);
    pickRow.appendChild(button("Выбрать папку...", function () {
      pickFolder("pick", {
        title: "Папка макетов для копии", start: lastOtherFolder() || (state.info || {}).folder,
        hint: "Папка макетов другой задачи; копия ляжет в ее корень под указанным именем (можно с подкаталогом).",
        onChoose: function (path) {
          where.other = path;
          rememberOtherFolder(path);
          otherPath.textContent = path;
          ok.disabled = false;
        }
      });
    }));
    otherPane.appendChild(pickRow);
    otherPane.appendChild(field("Имя файла (путь от выбранной папки)", otherName));
    var ok = button("Копировать", function () {
      var body = mode === "here"
        ? { file: inGroup(select.value, withJson(name.value)), copyFrom: model.file }
        : { file: withJson(otherName.value), copyFrom: model.file, toFolder: where.other };
      done(box, ok, function () {
        return api("POST", "/models", body).then(function (result) {
          if (mode === "other") state.notice = "Копия: " + result.folder + " / " + result.file;
          return null;
        });
      });
    }, "fh-main");
    box.body.appendChild(modes);
    box.body.appendChild(herePane);
    box.body.appendChild(otherPane);
    box.body.appendChild(h("div", "fh-note", "Метки копируются; занятое имя дополняется номером."));
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    selectMode("here");
  }

  // Последняя «другая» папка - подсказка для копии и «Из папки макетов» (только в этом браузере)
  function lastOtherFolder() {
    try { return localStorage.getItem("fh-other-folder") || ""; } catch (error) { return ""; }
  }

  function rememberOtherFolder(path) {
    try { localStorage.setItem("fh-other-folder", path); } catch (error) { /* без памяти */ }
  }

  async function create(box, body, okButton) {
    okButton.disabled = true;
    box.fail("");
    try {
      var result = await api("POST", "/models", body);
      box.close();
      FMAlive.go(editUrl(result.file));
    } catch (error) {
      box.fail(error.message);
      okButton.disabled = false;
    }
  }

  function newForm() {
    var box = dialog("Новая форма");
    var name = h("input", "fh-input");
    name.value = freeName("Новая форма");
    var kind = h("select", "fh-input");
    DATA.formKinds.forEach(function (item) {
      var option = h("option", "", item.title);
      option.value = item.kind;
      kind.appendChild(option);
    });
    kind.value = "DataProcessorForm";
    box.body.appendChild(field("Файл (путь от папки макетов)", name));
    box.body.appendChild(field("Вид формы", kind));
    box.body.appendChild(box.error);
    var ok = button("Создать", function () { create(box, { file: withJson(name.value), kind: kind.value }, ok); }, "fh-main");
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    name.select();
  }

  // Импорт: перетащенный файл или форма из исходников конфигурации

  function importForm(dropped, tab) {
    var info = state.info || {};
    var box = dialog("Импорт из 1С");
    var name = h("input", "fh-input");
    var chosen = { file: null, object: null, copy: null };
    var tabs = h("div", "fh-tabs");
    var filePane = h("div", "fh-field");
    var configPane = h("div", "fh-field");
    var mockupsPane = h("div", "fh-field");
    var ok = button("Импортировать", run, "fh-main");

    function select(tab) {
      Array.prototype.forEach.call(tabs.children, function (node) {
        node.setAttribute("aria-selected", String(node.dataset.tab === tab));
      });
      filePane.hidden = tab !== "file";
      configPane.hidden = tab !== "config";
      mockupsPane.hidden = tab !== "mockups";
      chosen.mode = tab;
      sync();
      var first = ({ config: configPane, mockups: mockupsPane }[tab] || filePane).querySelector("input");
      if (first && box.node.open) first.focus();
    }

    function sync() {
      ok.disabled = chosen.mode === "file" ? !chosen.file : chosen.mode === "mockups" ? !chosen.copy : !chosen.object;
    }

    [["file", "Файл формы"], ["config", "Из конфигурации"], ["mockups", "Из папки макетов"]].forEach(function (pair) {
      var tab = h("button", "fh-tab", pair[1]);
      tab.type = "button";
      tab.dataset.tab = pair[0];
      tab.addEventListener("click", function () { select(pair[0]); });
      tabs.appendChild(tab);
    });

    // Файл: перетащить или выбрать
    var drop = h("div", "fh-drop");
    var dropText = h("div", "", "Перетащите сюда Form.xml (выгрузка конфигуратора) или Form.form (EDT)");
    var input = h("input");
    input.type = "file";
    input.accept = ".xml,.form";
    drop.appendChild(dropText);
    drop.appendChild(input);
    filePane.appendChild(drop);

    function takeFile(file) {
      if (!file) return;
      var lower = file.name.toLowerCase();
      var kind = lower.slice(-5) === ".form" ? "Form.form" : lower.slice(-4) === ".xml" ? "Form.xml" : "";
      if (!kind) {
        box.fail("Ожидается Form.xml или Form.form: " + file.name);
        return;
      }
      file.text().then(function (text) {
        chosen.file = { name: kind, xml: text };
        dropText.textContent = "Файл: " + file.name;
        box.fail("");
        sync();
      });
    }
    input.addEventListener("change", function () { takeFile(input.files[0]); });
    drop.addEventListener("dragover", function (event) { event.preventDefault(); drop.classList.add("fh-over"); });
    drop.addEventListener("dragleave", function () { drop.classList.remove("fh-over"); });
    drop.addEventListener("drop", function (event) {
      event.preventDefault();
      event.stopPropagation();
      drop.classList.remove("fh-over");
      takeFile(event.dataTransfer.files[0]);
    });

    // Из конфигурации: дерево форм исходников папки с поиском
    if (!info.src) {
      configPane.appendChild(h("div", "fh-note", "Конфигурация у папки не задана - укажите папку проектов в шапке страницы, " +
        "и здесь появятся формы конфигурации и расширений."));
    } else {
      var search = h("input", "fh-input");
      search.type = "search";
      search.placeholder = "Объект или форма";
      var list = h("div", "fh-list");
      list.appendChild(h("div", "fh-empty", "Загрузка форм конфигурации..."));
      configPane.appendChild(search);
      configPane.appendChild(list);
      list.classList.add("fh-tree");
      var forms = [];
      var expanded = {};
      var drawForms = function () {
        list.textContent = "";
        var needle = search.value.trim().toLowerCase();
        var shown = forms.filter(function (form) {
          var text = form.key + " " + (OBJECT_KINDS[form.kind] || "") + " " + (KIND_PLURAL[form.kind] || "") + " " +
            (form.project || "");
          return !needle || text.toLowerCase().indexOf(needle) >= 0;
        });
        var limited = !!needle && shown.length > 300;
        // Поиск раскрывает все ветки найденного
        formTree(limited ? shown.slice(0, 300) : shown, forms, (info.extensions || []).length > 0).forEach(function (node) { drawNode(node, 0, !!needle); });
        if (limited) list.appendChild(h("div", "fh-empty", "Показаны первые 300 - уточните поиск"));
        if (!shown.length) list.appendChild(h("div", "fh-empty", "Ничего не найдено"));
      };
      var drawNode = function (node, depth, all) {
        var open = all || !!expanded[node.key];
        var item = h("button", "fh-item fh-tree-row" + (node.form ? " fh-tree-form" : "") + (node.project ? " fh-tree-project" : ""));
        item.type = "button";
        item.style.paddingLeft = (10 + depth * 18) + "px";
        item.dataset.key = node.key;
        var toggle = h("span", "fh-tree-toggle", node.form ? "" : open ? "\u2212" : "+");
        item.appendChild(toggle);
        var picture = h("img", "fh-tree-icon");
        picture.alt = "";
        picture.src = (DATA.metadataIcons || {})[node.icon] || "";
        if (!picture.src) picture.style.visibility = "hidden";
        item.appendChild(picture);
        item.appendChild(h("span", "fh-tree-text", node.title));
        if (node.form) {
          item.setAttribute("aria-selected", String(chosen.object === node.form.key));
          item.addEventListener("click", function () { chooseForm(node.form); });
          item.addEventListener("dblclick", function () { chooseForm(node.form); if (!ok.disabled) run(); });
        } else {
          item.setAttribute("aria-expanded", String(open));
          if (node.count) item.appendChild(h("span", "fh-item-sub", String(node.count)));
          item.addEventListener("click", function () {
            if (all) return;
            expanded[node.key] = !expanded[node.key];
            drawForms();
          });
        }
        list.appendChild(item);
        if (open && node.children) node.children.forEach(function (child) { drawNode(child, depth + 1, all); });
      };
      var chooseForm = function (form) {
        chosen.object = form.key;
        name.value = freeName(form.object ? form.object + "." + form.form : form.form);
        drawForms();
        sync();
      };
      // `#open=config&find=текст` - поиск сразу (тесты)
      search.value = decodeURIComponent((location.hash.match(/[#&]find=([^&]*)/) || [])[1] || "");
      search.addEventListener("input", drawForms);
      // Проекты раскрыты сразу, виды - свернуты, как в конфигураторе
      api("GET", "/config-forms").then(function (data) {
        forms = data.forms || [];
        forms.forEach(function (form) { expanded["@" + (form.project || "") + "/"] = true; });
        drawForms();
      })
        .catch(function (error) { box.fail(error.message); });
    }

    // Из папки макетов: макет другой задачи копируется сюда - основной путь «взять форму в задачу»
    var otherHead = h("div", "fh-row");
    var otherPath = h("span", "fh-path", "папка не выбрана");
    var otherSearch = h("input", "fh-input");
    otherSearch.type = "search";
    otherSearch.placeholder = "Макет, группа или метка";
    var otherList = h("div", "fh-list");
    var otherModels = [];
    var otherFolder = "";
    otherHead.appendChild(otherPath);
    otherHead.appendChild(button("Выбрать папку...", function () {
      pickFolder("pick", {
        title: "Папка макетов", start: otherFolder || lastOtherFolder() || info.folder,
        hint: "Папка макетов, где лежит нужный макет, - например, папка другой задачи.",
        onChoose: loadOther
      });
    }));
    mockupsPane.appendChild(otherHead);
    mockupsPane.appendChild(otherSearch);
    mockupsPane.appendChild(otherList);
    function loadOther(path) {
      otherFolder = path;
      otherPath.textContent = path;
      chosen.copy = null;
      sync();
      otherList.textContent = "";
      otherList.appendChild(h("div", "fh-empty", "Загрузка макетов..."));
      api("GET", "/folder-models?path=" + encodeURIComponent(path)).then(function (data) {
        rememberOtherFolder(data.folder);
        otherFolder = data.folder;
        otherPath.textContent = data.folder;
        otherModels = data.models || [];
        drawOther();
      }).catch(function (error) { otherList.textContent = ""; box.fail(error.message); });
    }
    function drawOther() {
      otherList.textContent = "";
      var needle = otherSearch.value.trim().toLowerCase();
      var shown = otherModels.filter(function (model) {
        return (model.title + " " + model.file + " " + (model.tags || []).join(" ")).toLowerCase().indexOf(needle) >= 0;
      });
      shown.forEach(function (model) {
        var item = h("button", "fh-item");
        item.type = "button";
        item.setAttribute("aria-selected", String(!!chosen.copy && chosen.copy.file === model.file));
        item.appendChild(h("span", "", model.title));
        item.appendChild(h("span", "fh-item-sub", model.file + ((model.tags || []).length ? " · " + model.tags.join(", ") : "")));
        item.addEventListener("click", function () {
          chosen.copy = { folder: otherFolder, file: model.file };
          name.value = freeName(fileName(model.file).replace(/\.json$/i, ""));
          drawOther();
          sync();
        });
        item.addEventListener("dblclick", function () { if (!ok.disabled) run(); });
        otherList.appendChild(item);
      });
      if (!shown.length) otherList.appendChild(h("div", "fh-empty", otherModels.length ? "Ничего не найдено" : "В папке нет макетов"));
    }
    otherSearch.addEventListener("input", drawOther);
    if (lastOtherFolder()) loadOther(lastOtherFolder());
    else otherList.appendChild(h("div", "fh-empty", "Выберите папку макетов - например, папку другой задачи"));

    name.value = freeName("Импорт");
    box.body.appendChild(tabs);
    box.body.appendChild(filePane);
    box.body.appendChild(configPane);
    box.body.appendChild(mockupsPane);
    box.body.appendChild(field("Файл макета (путь от папки макетов)", name));
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);

    function run() {
      var body = { file: withJson(name.value) };
      if (chosen.mode === "file") {
        body.name = chosen.file.name;
        body.xml = chosen.file.xml;
      } else if (chosen.mode === "mockups") {
        body.copyFrom = chosen.copy.file;
        body.fromFolder = chosen.copy.folder;
      } else {
        body.object = chosen.object;
      }
      create(box, body, ok);
    }

    box.node.showModal();
    select(tab || "file");
    if (dropped) takeFile(dropped);
  }

  // Папка проектов: найденные конфигурации - выбор одной, под ней ее расширения флажками
  // (выбор конфигурации отмечает ее расширения сам); расширения без найденной основы - отдельным разделом,
  // флажками, по нескольку, с подсказкой, где искать основу. Выбор сразу запоминается

  var FORMATS = { edt: "EDT", designer: "выгрузка конфигуратора" };

  function projectsBlock(info) {
    var block = h("div", "fh-projects");
    var items = info.projects.items;
    var chosen = info.src || null;
    var added = info.extensions || [];
    var configurations = items.filter(function (item) { return !item.extension; });
    var alone = items.filter(function (item) {
      return item.extension && (!item.base || !configurations.some(function (one) { return one.src === item.base; }));
    });
    function caption(item) {
      var text = item.name + (item.synonym && item.synonym !== item.name ? " (" + item.synonym + ")" : "");
      return text;
    }
    function details(item) {
      return [FORMATS[item.format] || item.format, item.extension ? item.purpose + (item.prefix ? ", префикс " + item.prefix : "") : "",
        item.project].filter(Boolean).join(" · ");
    }
    function row(item, type, checked, disabled, onChange, nested) {
      var label = h("label", "fh-project" + (nested ? " fh-project-ext" : ""));
      var input = h("input");
      input.type = type;
      input.name = type === "radio" ? "fh-configuration" : "";
      input.value = item.src;
      input.checked = checked;
      input.disabled = disabled;
      input.addEventListener("change", onChange);
      label.appendChild(input);
      label.appendChild(h("span", "fh-project-name", caption(item)));
      label.appendChild(h("span", "fh-item-sub", details(item)));
      label.title = item.src;
      return label;
    }
    if (configurations.length) {
      block.appendChild(h("div", "fh-projects-head", configurations.length > 1 ? "Конфигурация (одна из найденных) и ее расширения"
        : "Конфигурация и ее расширения"));
    }
    configurations.forEach(function (configuration) {
      var on = chosen === configuration.src;
      block.appendChild(row(configuration, "radio", on, false, function () {
        var own = items.filter(function (item) { return item.extension && item.base === configuration.src; })
          .map(function (item) { return item.src; });
        setProjects(info.projects.folder, configuration.src, own);
      }));
      items.filter(function (item) {
        return item.extension && (item.base === configuration.src || !item.base && item.candidates.indexOf(configuration.src) >= 0);
      }).forEach(function (extension) {
        block.appendChild(row(extension, "checkbox", on && added.indexOf(extension.src) >= 0, !on, function (event) {
          var next = added.filter(function (path) { return path !== extension.src; });
          if (event.target.checked) next.push(extension.src);
          setProjects(info.projects.folder, configuration.src, next);
        }, true));
      });
    });
    var ownChosen = items.some(function (item) { return item.extension && item.base && item.base === chosen; });
    if (ownChosen) block.appendChild(h("div", "fh-note", "Расширения выбранной конфигурации отмечаются сами - лишние можно снять."));
    if (alone.length) {
      // Взятые расширения без основы: первое - главный слой исходников, остальные - поверх
      var picked = alone.some(function (item) { return item.src === chosen; }) ? [chosen].concat(added) : [];
      var bases = [];
      alone.forEach(function (item) { if (item.baseProject && bases.indexOf(item.baseProject) < 0) bases.push(item.baseProject); });
      block.appendChild(h("div", "fh-projects-head", "Расширения без основы"));
      block.appendChild(h("div", "fh-note", (bases.length ? "Основа (" + bases.join(", ") + ") в этой папке не найдена. "
        : "Конфигурация, к которой подключаются эти расширения, в этой папке не найдена. ") +
        "Чтобы взять конфигурацию вместе с расширениями, выберите папку, где лежат и она, и расширения, - обычно " +
        "воркспейс EDT. Без основы окна выбора и импорт видят только объекты отмеченных расширений."));
      alone.forEach(function (extension) {
        block.appendChild(row(extension, "checkbox", picked.indexOf(extension.src) >= 0, false, function (event) {
          var next = picked.filter(function (path) { return path !== extension.src; });
          if (event.target.checked) next.push(extension.src);
          setProjects(info.projects.folder, next.length ? next[0] : "", next.slice(1));
        }));
      });
    }
    if (!chosen) {
      block.appendChild(h("div", "fh-note", configurations.length
        ? "Выберите конфигурацию - окна выбора и импорт будут видеть ее объекты и объекты отмеченных расширений."
        : "Отметьте расширения - окна выбора и импорт будут видеть их объекты."));
    }
    return block;
  }

  async function setProjects(folder, configuration, extensions) {
    try {
      var body = { projects: folder };
      if (configuration !== undefined) {
        body.configuration = configuration;
        body.extensions = extensions || [];
      }
      state.info = await api("PUT", "/settings", body);
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
    draw();
  }

  // Выбор каталога: папка макетов или папка проектов (исходники конфигурации)

  // `mode`: folder - папка макетов сервиса, src - папка проектов, pick - просто выбрать каталог (`options`: title,
  // hint, start, onChoose(path)) - копия и «Из папки макетов»
  function pickFolder(mode, options) {
    var info = state.info || {};
    var box = dialog(mode === "pick" ? options.title : mode === "src" ? "Папка проектов" : "Папка макетов");
    var path = h("div", "fh-path");
    var roots = h("div", "fh-roots");
    var list = h("div", "fh-list");
    var hint = h("div", "fh-note", mode === "pick" ? options.hint : mode === "src" ?
      "Любая папка, где лежат конфигурация и ее расширения: проект EDT, репозиторий, воркспейс EDT, каталог выгрузок " +
      "конфигуратора. Конфигурации и расширения найдутся сами; выбор запомнится у папки макетов." :
      "Каталог, в котором (и в подкаталогах) лежат макеты; макетов в нем может еще не быть.");
    var current = null;
    var ok = button("Выбрать", choose, "fh-main");

    async function open(target) {
      try {
        current = await api("GET", "/dirs?path=" + encodeURIComponent(target || ""));
        box.fail("");
      } catch (error) {
        box.fail(error.message);
        return;
      }
      path.textContent = current.path;
      roots.textContent = "";
      if (current.parent) roots.appendChild(button("Вверх", function () { open(current.parent); }));
      roots.appendChild(button("Домашняя", function () { open(current.home); }));
      current.roots.forEach(function (item) { roots.appendChild(button(item, function () { open(item); })); });
      list.textContent = "";
      current.dirs.forEach(function (dir) {
        var item = h("button", "fh-item");
        item.type = "button";
        item.appendChild(h("span", "", dir.name));
        if (dir.source) item.appendChild(h("span", "fh-item-note", dir.source === "edt" ? "исходники EDT" : "выгрузка конфигуратора"));
        item.addEventListener("click", function () { open(dir.path); });
        list.appendChild(item);
      });
      if (!current.dirs.length) list.appendChild(h("div", "fh-empty", "Подкаталогов нет"));
      ok.textContent = "Выбрать эту папку";
    }

    async function choose() {
      if (!current) return;
      if (mode === "pick") {
        box.close();
        options.onChoose(current.path);
        return;
      }
      ok.disabled = true;
      try {
        if (mode === "src") {
          state.info = await api("PUT", "/settings", { projects: current.path });
        } else {
          state.info = await api("PUT", "/folder", { path: current.path });
          state.filter = "";
        }
        state.error = "";
        box.close();
        draw();
      } catch (error) {
        box.fail(error.message);
        ok.disabled = false;
      }
    }

    box.body.appendChild(hint);
    box.body.appendChild(path);
    box.body.appendChild(roots);
    box.body.appendChild(list);
    box.body.appendChild(box.error);
    box.foot.appendChild(button("Отмена", box.close));
    box.foot.appendChild(ok);
    box.node.showModal();
    open(mode === "pick" ? options.start : mode === "src"
      ? ((info.projects && info.projects.folder) || info.suggestedProjects || info.src || info.folder) : info.folder);
  }

  async function setSource(value) {
    try {
      state.info = await api("PUT", "/settings", { src: value });
      state.error = "";
    } catch (error) {
      state.error = error.message;
    }
    draw();
  }

  // Перетаскивание файла формы на страницу - импорт

  var depth = 0;
  document.addEventListener("dragenter", function (event) {
    if (!event.dataTransfer || Array.prototype.indexOf.call(event.dataTransfer.types, "Files") < 0) return;
    if (document.querySelector("dialog[open]")) return;
    depth++;
    document.body.classList.add("fh-dragging");
  });
  document.addEventListener("dragleave", function () {
    depth = Math.max(0, depth - 1);
    if (!depth) document.body.classList.remove("fh-dragging");
  });
  document.addEventListener("dragover", function (event) { event.preventDefault(); });
  document.addEventListener("drop", function (event) {
    event.preventDefault();
    depth = 0;
    document.body.classList.remove("fh-dragging");
    if (document.querySelector("dialog[open]")) return;
    var file = event.dataTransfer && event.dataTransfer.files[0];
    if (file) importForm(file);
  });

  FMAlive.start({});
  load();
})();
