"""Общее для тестов: временные каталоги, которые не остаются после прогона."""

import atexit
import tempfile
from pathlib import Path

from fmlib.render import remove_tree


def temp_dir(prefix: str = "formmockup-") -> Path:
    """Временный каталог теста; удаляется в конце прогона - и из метода теста, и из `setUpClass`. На Windows
    `rmtree` бывает не удаляет с первого раза (файлы держит Chrome) - удаление с повтором."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(remove_tree, folder)
    return folder
