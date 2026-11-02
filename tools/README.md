# tools — лаунчеры и калибровка

Скрипты предполагают, что рядом с репозиторием есть `.venv` с зависимостями
(см. основной `README.md`). Здесь: поднять веб-сервис, получить консольный
отчёт и сравнить грейды с размеченным набором.

## `quick_web.bat` — быстрый запуск сервера

Двойной клик:
- сервер стартует на `127.0.0.1`, порт по умолчанию `8010`;
- если порт занят (например, остался старый процесс), берётся следующий
  свободный — так старый код не будет молча обслуживать запросы;
- браузер открывается сам, когда сервер готов;
- остановка — `Ctrl+C` в окне консоли.

Свой порт и доступ из локальной сети:

```powershell
tools\quick_web.bat --port 8080
tools\quick_web.bat --port 8010 --host 0.0.0.0
```

Эквивалент без `.bat`:

```powershell
.venv\Scripts\python.exe tools\quick_web.py --port 8010
```

У веб-режима нет авторизации: `--host 0.0.0.0` открывает его всей сети.

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

## `evaluate_grades.py` — точность грейдов

Сравнивает класс приложения с метками в имени файла:

- `G0_*.jpg ... G4_*.jpg` — ожидаемый грейд 0–4;
- `G_ERROR_*.jpg` — ожидается БРАК (нераспознанный или плохой код).

```powershell
.venv\Scripts\python.exe tools\evaluate_grades.py --dir samples
.venv\Scripts\python.exe tools\evaluate_grades.py --dir samples --verbose
.venv\Scripts\python.exe tools\evaluate_grades.py --dir samples --csv grades.csv
.venv\Scripts\python.exe tools\evaluate_grades.py --dir samples --json grades.json
.venv\Scripts\python.exe tools\evaluate_grades.py --dir samples --strict
```

Выводится матрица «эталон → наш округлённый грейд», доля точных
совпадений, ошибка ±1, средняя абсолютная ошибка и список расхождений.
`--strict` завершается с кодом 1 при любом расхождении — удобно для CI на
закрытом наборе.

Папки `samples/` в git нет; инструмент нужен для локальной калибровки
`core/grade.py` перед изменением порогов.

## Другие ОС

Скрипты `.bat` — только для Windows. На Linux/macOS работают те же команды
`main.py` (веб-сервис), `main.py --file ...` и
`.venv/bin/python tools/quick_web.py --port 8010`.
