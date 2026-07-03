# cursor-vibemode

`cursor-vibemode` настраивает Cursor на работу через Vibemode/OpenAI-compatible
API. Скрипт патчит реальное хранилище Cursor `state.vscdb`: записывает ключ,
включает OpenAI BYOK, прописывает base URL и добавляет модели Vibemode в список
доступных моделей.

Скрипт автоматически работает с обычным редактором Cursor и новым агентным
окном Cursor. Если в профиле есть обе версии интерфейса, настройка применяется
для обеих через общий профиль Cursor.

## Быстрый запуск

Перед запуском полностью закрой Cursor.

Linux, macOS или WSL:

```bash
curl -fsSL https://github.com/OlegGorsky/cursor-vibemode/raw/main/i|bash
```

Если GitHub отдал старую версию установщика:

```bash
curl -fsSL "https://github.com/OlegGorsky/cursor-vibemode/raw/main/i?$(date +%s)"|bash
```

Windows PowerShell:

```powershell
irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1|iex
```

Если GitHub отдал старую версию установщика:

```powershell
irm "https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1?$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"|iex
```

Windows-скрипт настраивает Cursor в Windows и автоматически пробует настроить
WSL, если `wsl.exe` есть и default distro уже инициализирован. Если WSL не
установлен или не готов, он просто пропускается.

Терминал попросит вставить Vibemode API key скрытым вводом. В обычном терминале
будет показываться одна `*` на каждый символ.

## Что делает скрипт

1. находит Cursor `state.vscdb`;
2. проверяет, что Cursor закрыт;
3. делает backup базы;
4. записывает ключ в `cursorAuth/openAIKey`;
5. выставляет `openAIBaseUrl = https://api.vibemod.pro/v1`;
6. включает `useOpenAIKey = true`;
7. получает список моделей Vibemode через `/v1/models`;
8. добавляет в Cursor все модели, которые вернул API;
9. обновляет все найденные режимы выбора модели в Cursor;
10. проверяет API через `/v1/models`.

Если API-проверка отключена, скрипт использует встроенный резервный список
моделей.

После успешной настройки открой Cursor заново.

Обычный успешный вывод выглядит так:

```text
Настройка завершена: Vibemode подключен к Cursor.
Подключено для: редактор и агентное окно
Моделей подключено: 11
Основная модель: gpt-5.4
Резервная копия: создана
Проверка API: каталог доступен (11 моделей)
```

Если что-то не сработало, скрипт выводит код ошибки, причину и строку для
разработчика. Такой вывод можно сразу переслать в issue или разработчику.

Если Cloudflare заблокирует терминальную проверку `/v1/models`, установка не
остановится: скрипт применит настройки с резервным списком моделей и покажет
предупреждение. Это не обязательно означает, что ключ неправильный.

## Пути Cursor DB

Linux:

```text
~/.config/Cursor/User/globalStorage/state.vscdb
```

macOS:

```text
~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
```

Windows:

```text
%APPDATA%\Cursor\User\globalStorage\state.vscdb
```

WSL обычно использует Windows Cursor DB через `/mnt/c/...`. Скрипт умеет
находить этот путь автоматически. Если внутри WSL установлен отдельный Linux
Cursor и есть `~/.config/Cursor/User/globalStorage/state.vscdb`, он тоже может
быть настроен.

## Что именно меняется

В SQLite-базе Cursor меняются записи:

- `cursorAuth/openAIKey`
- `src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser`
- `__$__targetStorageMarker`

Перед изменением создается backup рядом с базой:

```text
state.vscdb.bak-YYYYmmdd-HHMMSS
```

## Windows: полезные варианты

Взять ключ из буфера обмена:

```powershell
$env:CURSOR_VIBEMODE_KEY_FROM_CLIPBOARD='1'; irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1|iex; Remove-Item Env:\CURSOR_VIBEMODE_KEY_FROM_CLIPBOARD
```

Пропустить проверку API:

```powershell
$env:CURSOR_VIBEMODE_SKIP_API_CHECK='1'; irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1|iex; Remove-Item Env:\CURSOR_VIBEMODE_SKIP_API_CHECK
```

Запустить глубокую endpoint-проверку:

```powershell
$env:CURSOR_VIBEMODE_DEEP_API_CHECK='1'; irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1|iex; Remove-Item Env:\CURSOR_VIBEMODE_DEEP_API_CHECK
```

Настроить конкретный WSL-дистрибутив:

```powershell
& ([scriptblock]::Create((irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1))) -WslDistro Ubuntu
```

Отключить WSL-часть:

```powershell
& ([scriptblock]::Create((irm https://github.com/OlegGorsky/cursor-vibemode/raw/main/i.ps1))) -NoWsl
```

## Linux/macOS/WSL: полезные варианты

Пропустить проверку API:

```bash
curl -fsSL https://github.com/OlegGorsky/cursor-vibemode/raw/main/i|bash -s -- --skip-api-check
```

Запустить глубокую endpoint-проверку:

```bash
curl -fsSL https://github.com/OlegGorsky/cursor-vibemode/raw/main/i|bash -s -- --deep-api-check
```

Указать путь к Cursor DB вручную:

```bash
curl -fsSL https://github.com/OlegGorsky/cursor-vibemode/raw/main/i|bash -s -- --db ~/.config/Cursor/User/globalStorage/state.vscdb
```

Автоматический запуск без prompt:

```bash
export CURSOR_VIBEMODE_KEY=sk-...
curl -fsSL https://github.com/OlegGorsky/cursor-vibemode/raw/main/i|bash -s -- --non-interactive
unset CURSOR_VIBEMODE_KEY
```

## Локальный запуск из клона

```bash
git clone https://github.com/OlegGorsky/cursor-vibemode.git
cd cursor-vibemode
./cursor-vibemode doctor
./cursor-vibemode setup
```

Команды:

```bash
./cursor-vibemode doctor
./cursor-vibemode status
./cursor-vibemode setup --model gpt-5.4
./cursor-vibemode repair
./cursor-vibemode verify
./cursor-vibemode watch
./cursor-vibemode toggle
./cursor-vibemode disable
./cursor-vibemode enable
./cursor-vibemode remove --forget-key
```

`repair` заново применяет ключ, base URL, `useOpenAIKey`, labels и каталог
моделей. Это полезно после обновления Cursor или если модельные подписи/тумблер
сбились.

`watch` держит `useOpenAIKey=true`, если Cursor сам сбрасывает этот флаг. По
умолчанию проверяет базу раз в 30 секунд:

```bash
./cursor-vibemode watch
```

`toggle` быстро включает или выключает BYOK без удаления ключа и URL.

## Модели и endpoint-проверка

Vibemode отдает не только GPT-модели. Поэтому обычный `setup` по умолчанию
берет полный список из `/v1/models` и регистрирует все возвращенные model ID в
Cursor. Вручную можно выбрать режим:

```bash
./cursor-vibemode setup --models auto      # default, все из /models
./cursor-vibemode setup --models builtin   # встроенный резервный список
./cursor-vibemode setup --models gpt-5.4,deepseek-v4-pro
```

Глубокая проверка учитывает разные endpoint-семейства:

- `gpt-*` проверяются через `/v1/responses`;
- остальные модели проверяются через `/v1/chat/completions`.

Запустить глубокую проверку после установки:

```bash
./cursor-vibemode verify
```

Или сразу во время установки:

```bash
./cursor-vibemode setup --deep-api-check
```

Обычный `/v1/models` почти ничего не стоит и проверяет только доступность
каталога. `verify` и `--deep-api-check` отправляют короткий smoke-запрос на
каждую модель, поэтому они могут списать минимальные токены у провайдера.

## Важно

- Перед `setup`, `enable`, `disable` и `remove` Cursor должен быть закрыт.
- Перед `repair` Cursor тоже должен быть закрыт.
- Скрипт не читает `~/.codex`, `~/.codex2` и `CODEX_KEY`.
- Обычный `setup` получает ключ прямо в терминале.
- Ключ может быть сохранен только в локальный cache `~/.cursor-vibemode/auth.json`.
- Если Cursor не был открыт ни разу, `state.vscdb` может еще не существовать.
- Cursor может блокировать `localhost`, `127.0.0.1` и private network URL как
  Override OpenAI Base URL. Для локального прокси обычно нужен публичный HTTPS
  tunnel, например Cloudflare Tunnel или ngrok.
- Cursor-native модели вроде Composer могут конфликтовать с включенным BYOK.
  В таком случае выключай BYOK через `./cursor-vibemode toggle` или горячую
  клавишу Cursor `Cmd/Ctrl+Shift+0`, ключ при этом не удаляется.

## Проверка после установки

```bash
./cursor-vibemode status
```

Ожидаемые признаки:

```text
Статус Cursor Vibemode
Подключение: включено
Подключено для: редактор и агентное окно
Моделей подключено: 11
Основная модель: gpt-5.4
```

## Требования

Linux/macOS/WSL:

- `bash`
- `curl`
- `tar`
- `python3`

Windows:

- PowerShell
- Python 3 в `PATH` или Python Launcher `py.exe`
- Cursor, открытый хотя бы один раз
- WSL опционален
