/* Отметка вкладки для автоостановки сервиса: открытая страница (стартовая или конструктор) раз в
   ALIVE_MS шлет `POST /alive` {tab, file, dirty}; нет отметок ни от одной вкладки дольше паузы - сервис
   останавливается. Таймер - в Worker: таймеры свернутой вкладки браузер будит не чаще раза в минуту, а в Worker
   их не замедляет. Нет Worker - обычный таймер страницы. */
var FMAlive = (function () {
  "use strict";

  var ALIVE_MS = 15000;
  var tab = Date.now().toString(36) + Math.random().toString(36).slice(2);
  var state = null;
  var worker = null;

  function send() {
    fetch("/alive", {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state)
    }).catch(function () { /* сервис остановлен - страница скажет об этом сама */ });
  }

  function post() {
    if (worker) worker.postMessage(state);
    else send();
  }

  function start(info) {
    state = { url: location.origin + "/alive", tab: tab, file: (info && info.file) || null, dirty: !!(info && info.dirty) };
    try {
      // Адрес отметки - полный: относительный от адреса blob: в Worker не разбирается
      var code = "var state = null;" +
        "function send() { if (state) fetch(state.url, { method: 'POST', cache: 'no-store'," +
        " headers: { 'Content-Type': 'application/json' }," +
        " body: JSON.stringify({ tab: state.tab, file: state.file, dirty: state.dirty }) }).catch(function () {}); }" +
        "onmessage = function (event) { state = event.data; send(); };" +
        "setInterval(send, " + ALIVE_MS + ");";
      worker = new Worker(URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
    } catch (error) {
      worker = null;
      setInterval(send, ALIVE_MS);
    }
    post();
  }

  // Несохраненные правки - сразу, не ждать таймера: «Завершить» предупреждает по ним
  function update(info) {
    if (!state) return;
    var dirty = !!info.dirty;
    if (dirty === state.dirty) return;
    state.dirty = dirty;
    post();
  }

  // «Завершить» закрывает все окна сервиса (владелец 08.11.2026): страница, остановившая сервис, рассылает `quit`
  // по каналу страниц того же адреса; каждая закрывает свое окно. Закрыть окно скриптом браузер дает, только если в
  // его истории одна страница, - поэтому переходы список ↔ конструктор идут через `go` (замена, а не новая запись)
  var channel = null;
  try { channel = new BroadcastChannel("form-mockup"); } catch (error) { channel = null; }

  function onQuit(handler) {
    if (channel) channel.addEventListener("message", function (event) { if (event.data === "quit") handler(); });
  }

  function quitAll() {
    if (channel) channel.postMessage("quit");
  }

  function go(url) {
    location.replace(url);
  }

  // Ссылка-переход внутри сервиса: обычный щелчок - `go`; с Ctrl / Cmd / Shift и средней кнопкой - как у ссылки
  function link(anchor) {
    anchor.addEventListener("click", function (event) {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      go(anchor.href);
    });
    return anchor;
  }

  return { start: start, update: update, tab: tab, onQuit: onQuit, quitAll: quitAll, go: go, link: link };
})();
