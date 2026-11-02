# tools — быстрый запуск по файлу

Скрипты предполагают, что рядом с репозиторием есть `.venv` с зависимостями
(см. основной `README.md`).

## `quick_open.bat` — открыть файл в GUI

1. Перетащите файл изображения (`jpg`, `jpeg`, `png`, `bmp`, `tif`, `tiff`)
   на `quick_open.bat`.
2. Откроется GUI, изображение загрузится и сразу будет проанализировано.

Эквивалент из консоли:

```powershell
.venv\Scripts\python.exe main.py --gui --file "C:\photos\code.jpg"
```

Если файл не открылся, запустите ту же команду в консоли — там будет текст
ошибки.

## `quick_check.bat` — консольный отчёт

Перетащите файл на `quick_check.bat`: в консоли появится отчёт по **всем**
DataMatrix-кодам в изображении (содержимое, GS1, грейды, размеры).
Окно останется открытым до нажатия клавиши.

Эквивалент:

```powershell
.venv\Scripts\python.exe main.py --file "C:\photos\code.jpg"
```

Для пакетной обработки папки и JSON-вывода используйте основной CLI:

```powershell
.venv\Scripts\python.exe main.py --dir C:\photos --json
```

## Другие ОС

Скрипты `.bat` — только для Windows. На Linux/macOS те же команды
`main.py --gui --file ...` и `main.py --file ...` работают напрямую.
