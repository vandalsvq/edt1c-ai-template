/* Строка формата 1С для конструктора макета: разбор, сборка и представление значения.
   Сборка - как у конструктора форматной строки: параметры в постоянном порядке для числа, даты
   и булева, «КЛЮЧ = значение» через «; », число -
   цифрами, строка - в одинарных кавычках, флажок - «Истина», «ЧГ» и «ЧН» пишутся и пустыми. Представление - свой
   `Формат()` по документации 1С (русская локаль): таблица случаев и обработка, снимающая ее в 1С, - в тестах
   (`tests/fixtures/format-1c.json`, `1c/СнятьТаблицуФормата.bsl`). */
(function (root) {
  "use strict";

  var NUMBER_KEYS = ["ЧЦ", "ЧДЦ", "ЧС", "ЧРД", "ЧРГ", "ЧН", "ЧВН", "ЧГ", "ЧО", "ЧФ"];
  var DATE_KEYS = ["ДФ", "ДЛФ", "ДП"];
  var BOOLEAN_KEYS = ["БЛ", "БИ"];
  var NUMERIC = { "ЧЦ": true, "ЧДЦ": true, "ЧС": true };
  var FLAGS = { "ЧВН": true };
  // Английские имена параметров 1С → русские
  var ENGLISH = { ND: "ЧЦ", NFD: "ЧДЦ", NS: "ЧС", NDS: "ЧРД", NGS: "ЧРГ", NZ: "ЧН", NLZ: "ЧВН", NG: "ЧГ", NN: "ЧО",
    NF: "ЧФ", DF: "ДФ", DLF: "ДЛФ", DE: "ДП", BF: "БЛ", BT: "БИ", L: "Л" };
  var NBSP = " ";       // разделитель групп русской локали по умолчанию
  var MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
    "ноябрь", "декабрь"];
  var MONTHS_OF = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
    "ноября", "декабря"];
  var MONTHS_SHORT = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."];
  var DAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
  var DAYS_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

  // Разбор: «ЧЦ=10; ЧДЦ=2; ЧРД='.'» → { ЧЦ: "10", ЧДЦ: "2", ЧРД: "." }; разделитель «;» в кавычках - часть значения
  function parse(text) {
    var result = {};
    var parts = [];
    var current = "";
    var quote = "";
    String(text || "").split("").forEach(function (char) {
      if (quote) {
        if (char === quote) quote = "";
        current += char;
      } else if (char === "'" || char === '"') {
        quote = char;
        current += char;
      } else if (char === ";") {
        parts.push(current);
        current = "";
      } else {
        current += char;
      }
    });
    parts.push(current);
    parts.forEach(function (part) {
      var equal = part.indexOf("=");
      if (equal < 0) return;
      var key = part.slice(0, equal).trim();
      key = ENGLISH[key.toUpperCase()] || key.toUpperCase();
      var value = part.slice(equal + 1).trim();
      var found = /^(['"])([\s\S]*)\1$/.exec(value);
      result[key] = found ? found[2] : value;
    });
    return result;
  }

  function quoted(value) { return value === "" ? "" : "'" + value + "'"; }

  // Сборка по образцу конструктора: только включенные параметры; пустое значение пропускается, кроме «ЧГ»
  function build(params) {
    var parts = [];
    NUMBER_KEYS.concat(DATE_KEYS, BOOLEAN_KEYS).forEach(function (key) {
      if (!Object.prototype.hasOwnProperty.call(params, key)) return;
      var value = params[key];
      var text;
      if (FLAGS[key]) text = value === false ? "" : "Истина";
      else if (NUMERIC[key]) text = value === "" || value === null || isNaN(Number(value)) ? "" : String(Number(value));
      else text = quoted(String(value));
      // «ЧГ» пустым пишет и конструктор; «ЧН» пустым - отступление: «ЧН=» в 1С значит «ноль - числом», конструктор-
      // образец его теряет, а этот бы стер у импортированного формата
      if (text === "" && key !== "ЧГ" && key !== "ЧН") return;
      parts.push(key + " = " + text);
    });
    return parts.join("; ");
  }

  function integer(value) {
    var number = parseInt(value, 10);
    return isNaN(number) ? null : number;
  }

  // Округление 1С - от нуля, по десятичной записи (1,005 → 1,01)
  function round(value, digits) {
    var result = Number(Math.round(Number(Math.abs(value) + "e" + digits)) + "e-" + digits);
    return value < 0 ? -result : result;
  }

  // Группы разрядов «3,2,0»: справа 3, дальше по 2; последний «0» - повторять предыдущий размер, без него
  // остаток не делится; «0» - без групп
  function group(digits, sizes, separator) {
    var repeat = sizes[sizes.length - 1] === 0;
    var list = repeat ? sizes.slice(0, -1) : sizes.slice();
    var groups = [];
    var rest = digits;
    for (var index = 0; ; index++) {
      var size = index < list.length ? list[index] : (repeat && list.length ? list[list.length - 1] : 0);
      if (!size || rest.length <= size) break;
      groups.unshift(rest.slice(rest.length - size));
      rest = rest.slice(0, rest.length - size);
    }
    groups.unshift(rest);
    return groups.join(separator);
  }

  function groupSizes(value) {
    if (value === undefined) return [3, 0];
    return String(value).split(",").map(function (part) { return integer(part.trim()) || 0; });
  }

  function plainDigits(value) {
    return String(Number(Math.abs(value).toPrecision(15))).replace(/e.*$/, "");
  }

  function formatNumber(value, params) {
    params = params || {};
    if (typeof value !== "number" || !isFinite(value)) return "";
    var shift = integer(params["ЧС"]);
    if (shift) value = value / Math.pow(10, shift);
    var fraction = integer(params["ЧДЦ"]);
    if (fraction !== null) value = round(value, fraction);
    if (value === 0 || Object.is(value, -0)) {
      if (params["ЧН"] === undefined) return "";
      if (params["ЧН"] !== "") return params["ЧН"];
      value = 0;
    }
    var text = fraction !== null ? Math.abs(value).toFixed(fraction) : plainDigits(value);
    var parts = text.split(".");
    var whole = parts[0];
    var length = integer(params["ЧЦ"]);
    if (params["ЧВН"] !== undefined && length !== null) {
      var wholeDigits = length - (fraction || 0);
      while (whole.length < wholeDigits) whole = "0" + whole;
    }
    var separator = params["ЧРГ"] !== undefined ? params["ЧРГ"] : NBSP;
    whole = group(whole, params["ЧГ"] === "" ? [0] : groupSizes(params["ЧГ"]), separator);
    var decimal = params["ЧРД"] !== undefined && params["ЧРД"] !== "" ? params["ЧРД"] : ",";
    var result = parts.length > 1 && parts[1] !== "" ? whole + decimal + parts[1] : whole;
    if (value < 0) {
      var mode = params["ЧО"] !== undefined ? integer(params["ЧО"]) : 1;
      result = mode === 0 ? "(" + result + ")" : mode === 2 ? "- " + result : mode === 3 ? result + "-"
        : mode === 4 ? result + " -" : "-" + result;
    }
    if (params["ЧФ"]) result = params["ЧФ"].replace(/Ч/g, result);
    return result;
  }

  function pad(value, width) {
    var text = String(value);
    while (text.length < width) text = "0" + text;
    return text;
  }

  // Шаблон даты: d dd ddd dddd, M MM MMM MMMM, y yy yyyy, h hh H HH, m mm, s ss, q; прочее - как есть,
  // текст в кавычках - как есть без кавычек. Полное название месяца при дне в шаблоне - в родительном падеже
  function formatPattern(date, pattern) {
    var withDay = /d/.test(pattern.replace(/'[^']*'|"[^"]*"/g, ""));
    return pattern.replace(/'([^']*)'|"([^"]*)"|d{1,4}|M{1,4}|y{1,4}|h{1,2}|H{1,2}|m{1,2}|s{1,2}|q/g,
      function (token, single, double) {
        if (single !== undefined) return single;
        if (double !== undefined) return double;
        var hours12 = date.getHours() % 12 || 12;
        switch (token) {
          case "d": return String(date.getDate());
          case "dd": return pad(date.getDate(), 2);
          case "ddd": return DAYS_SHORT[date.getDay()];
          case "dddd": return DAYS[date.getDay()];
          case "M": return String(date.getMonth() + 1);
          case "MM": return pad(date.getMonth() + 1, 2);
          case "MMM": return MONTHS_SHORT[date.getMonth()];
          case "MMMM": return withDay ? MONTHS_OF[date.getMonth()]
            : MONTHS[date.getMonth()].charAt(0).toUpperCase() + MONTHS[date.getMonth()].slice(1);
          case "y": case "yy": return pad(date.getFullYear() % 100, 2);
          case "yyy": case "yyyy": return pad(date.getFullYear(), 4);
          case "h": return String(hours12);
          case "hh": return pad(hours12, 2);
          case "H": return String(date.getHours());
          case "HH": return pad(date.getHours(), 2);
          case "m": return String(date.getMinutes());
          case "mm": return pad(date.getMinutes(), 2);
          case "s": return String(date.getSeconds());
          case "ss": return pad(date.getSeconds(), 2);
          case "q": return String(Math.floor(date.getMonth() / 3) + 1);
        }
        return token;
      });
  }

  // перед «г.» 1С ставит неразрывный пробел (таблица format-1c.json, снята на 8.3.27)
  var LOCAL = { D: "dd.MM.yyyy", DD: "d MMMM yyyy' г.'", T: "H:mm:ss", DT: "dd.MM.yyyy H:mm:ss",
    DDT: "d MMMM yyyy' г.' H:mm:ss" };

  // `date` - Date или пусто (пустая дата 1С)
  function formatDate(date, params) {
    params = params || {};
    if (!(date instanceof Date) || isNaN(date.getTime()) || date.getFullYear() <= 1) {
      return params["ДП"] !== undefined ? params["ДП"] : "";
    }
    var pattern = params["ДФ"] || LOCAL[String(params["ДЛФ"] || "").toUpperCase()] || LOCAL.DT;
    return formatPattern(date, pattern);
  }

  function formatBoolean(value, params) {
    params = params || {};
    if (value) return params["БИ"] !== undefined ? params["БИ"] : "Да";
    return params["БЛ"] !== undefined ? params["БЛ"] : "Нет";
  }

  root.FMFormat = {
    NUMBER_KEYS: NUMBER_KEYS, DATE_KEYS: DATE_KEYS, BOOLEAN_KEYS: BOOLEAN_KEYS,
    parse: parse, build: build, number: formatNumber, date: formatDate, boolean: formatBoolean
  };
})(typeof window !== "undefined" ? window : this);
