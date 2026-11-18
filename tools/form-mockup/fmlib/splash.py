"""Заставка ярлыка: вместо окна консоли на все время запуска - небольшое окно со значком
и ходом запуска.

- Ярлык (`serve --shortcut`) из консоли сразу запускает себя же оконным Python (`pythonw`, без консоли) с ключом
  `--splash` и выходит: консоль ярлыка закрывается за долю секунды.
- Процесс заставки показывает окно и в отдельном потоке выполняет обычный запуск ярлыка; его вывод построчно
  идет в окно. Сервис запущен - заставка гаснет, когда окно макетов уже на экране; ошибка - остается с текстом
  ошибки и кнопкой «Закрыть». Итог запуска пишется в журнал сервиса.
- Окно рисует tkinter из стандартной поставки Python. Нет его, нет `pythonw` (пока заставка только на Windows) или
  задано `FORMMOCKUP_NO_SPLASH` - запуск в консоли, как раньше.
"""

from __future__ import annotations

import importlib.util
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from . import ROOT

SCRIPT = ROOT / "formmockup.py"
ICON = ROOT / "render" / "icon.png"
NO_SPLASH_ENV = "FORMMOCKUP_NO_SPLASH"
# Сколько заставка держится после запуска сервиса: окно браузера появляется через 1-2 с. Задано в окружении
# (тесты) - так же быстро закрывается и окно ошибки
HOLD_ENV = "FORMMOCKUP_SPLASH_HOLD"
HOLD_SECONDS = 2.5

TITLE = "Макеты форм 1С"
WHITE = "#ffffff"
TEXT = "#1f2937"
MUTED = "#4b5563"
ALERT = "#b42318"
BORDER = "#c9ced6"
ACCENT = "#2f6fde"          # цвет значка
TROUGH = "#e5e7eb"
FONT = "Segoe UI"


def windowed_python() -> Path | None:
    """`pythonw.exe` рядом с текущим Python; не Windows или его нет - None."""
    if sys.platform != "win32":
        return None
    path = Path(sys.executable).with_name("pythonw.exe")
    return path if path.is_file() else None


def console_python() -> str:
    """Python для процесса сервиса: у оконного `pythonw` вывода нет - сервису нужен консольный рядом с ним."""
    path = Path(sys.executable)
    if path.name.lower() == "pythonw.exe" and path.with_name("python.exe").is_file():
        return str(path.with_name("python.exe"))
    return sys.executable


def available() -> bool:
    return (not os.environ.get(NO_SPLASH_ENV) and windowed_python() is not None
            and importlib.util.find_spec("tkinter") is not None)


def start(arguments: list):
    """Запуск ярлыка в процессе заставки; консоль ярлыка его не ждет."""
    command = [str(windowed_python()), str(SCRIPT), *arguments, "--splash"]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def hold_seconds() -> float:
    try:
        return float(os.environ[HOLD_ENV])
    except (KeyError, ValueError):
        return HOLD_SECONDS


class Lines:
    """Вывод запуска построчно - в очередь окна (`print` потока запуска вместо консоли)."""

    def __init__(self, sink: queue.Queue):
        self.sink = sink
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.sink.put(line.rstrip())
        return len(text)

    def flush(self):
        if self.buffer.strip():
            self.sink.put(self.buffer.rstrip())
        self.buffer = ""


def status_text(line: str) -> str:
    """Строка запуска - человеку: адрес сервиса не нужен, нужно, что сейчас происходит."""
    if line.startswith(("Макеты:", "Конструктор:")):
        return "Открываю окно макетов..."
    if line.startswith("Сервис на эту папку уже запущен"):
        return "Макеты уже открыты - показываю окно..."
    return line


def run(handler) -> int:
    """Окно заставки на время запуска `handler` (обычный запуск ярлыка); итог - код запуска."""
    import tkinter as tk
    from tkinter import ttk

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # четкий текст при масштабе экрана больше 100 %
    except (AttributeError, OSError):
        pass
    lines = queue.Queue()
    result = {}
    seen = []

    def work():
        out = Lines(lines)
        sys.stdout = sys.stderr = out
        try:
            result["code"] = handler()
        except BaseException as error:  # noqa: BLE001 - заставка не должна повиснуть без итога
            result["code"] = 2
            lines.put(f"Ошибка: {error}")
        finally:
            out.flush()

    root = tk.Tk()
    root.withdraw()
    root.title(TITLE)
    root.configure(bg=BORDER)
    # Размеры в пикселях - под масштаб экрана (шрифты в пунктах Tk масштабирует сам)
    scale = max(1.0, root.winfo_fpixels("1i") / 96)

    def px(value: float) -> int:
        return int(round(value * scale))

    body = tk.Frame(root, bg=WHITE, padx=px(22), pady=px(18))
    body.pack(padx=1, pady=1, fill="both", expand=True)
    try:
        icon = tk.PhotoImage(file=str(ICON))          # 128 px: при масштабе до 175 % - вдвое мельче
        root.iconphoto(True, icon)
        shown = icon if scale >= 1.75 else icon.subsample(2)
        tk.Label(body, image=shown, bg=WHITE).grid(row=0, column=0, rowspan=3, sticky="n", padx=(0, px(16)))
    except tk.TclError:
        icon = shown = None
    tk.Label(body, text=TITLE, font=(FONT, 14, "bold"), bg=WHITE, fg=TEXT).grid(row=0, column=1, sticky="w")
    status = tk.Label(body, text="Запуск...", font=(FONT, 10), bg=WHITE, fg=MUTED, justify="left", anchor="w",
                      wraplength=px(360))
    status.grid(row=1, column=1, sticky="w", pady=(px(4), 0))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Splash.Horizontal.TProgressbar", background=ACCENT, troughcolor=TROUGH, bordercolor=TROUGH,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=px(6))
    bar = ttk.Progressbar(body, mode="indeterminate", length=px(360), style="Splash.Horizontal.TProgressbar")
    bar.grid(row=2, column=1, sticky="we", pady=(px(12), 0))
    bar.start(12)

    def place():
        # Размер и место - вместе и после расчета раскладки: окно без рамки иначе встает в угол экрана
        root.update_idletasks()
        width, height = root.winfo_reqwidth(), root.winfo_reqheight()
        left = (root.winfo_screenwidth() - width) // 2
        top = (root.winfo_screenheight() - height) // 3
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.update_idletasks()

    def failed():
        from .launch import log_path
        bar.destroy()
        status.configure(text="\n".join(seen[-6:]) or "Ошибка запуска", fg=ALERT, wraplength=px(520))
        tk.Label(body, text=f"Подробности - в журнале {log_path()}", font=(FONT, 9), bg=WHITE, fg=MUTED,
                 justify="left", anchor="w", wraplength=px(520)).grid(row=2, column=1, sticky="w", pady=(px(10), 0))
        tk.Button(body, text="Закрыть", font=(FONT, 10), command=root.destroy, padx=px(14)).grid(
            row=3, column=1, sticky="e", pady=(px(14), 0))
        root.bind("<Escape>", lambda event: root.destroy())
        root.bind("<Return>", lambda event: root.destroy())
        place()
        root.focus_force()
        if os.environ.get(HOLD_ENV):
            root.after(int(hold_seconds() * 1000), root.destroy)

    def poll():
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                break
            seen.append(line)
            if "code" not in result or result["code"] == 0:
                status.configure(text=status_text(line))
        if worker.is_alive() or not lines.empty():
            root.after(100, poll)
        elif result.get("code", 2) == 0:
            root.after(int(hold_seconds() * 1000), root.destroy)
        else:
            failed()

    place()
    root.overrideredirect(True)
    root.deiconify()
    place()
    root.attributes("-topmost", True)
    root.after(400, lambda: root.attributes("-topmost", False))
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    root.after(100, poll)
    root.mainloop()
    worker.join(5)
    code = result.get("code", 2)
    from .launch import log
    log(f"Заставка ярлыка: код {code}\n" + "\n".join(seen))
    return code
