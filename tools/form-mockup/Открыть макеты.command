#!/bin/bash
# Ярлык сервиса макетов форм: двойной щелчок - последняя папка макетов. Окно Терминала
# можно закрыть, когда появилась строка с адресом; ошибка остается на экране.
pause() {
    [ -n "$FORMMOCKUP_NO_PAUSE" ] || read -r -p "Нажмите Enter, чтобы закрыть окно" _
}
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1         && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Не найден Python 3.9 или новее - он нужен, чтобы открыть макеты."
    echo "Скачайте установщик: https://www.python.org/downloads/macos/ и снова откройте ярлык."
    pause
    exit 1
fi
if ! "$PY" "$(dirname "$0")/formmockup.py" serve --shortcut "$@"; then
    echo
    pause
    exit 1
fi
