# Claude Code — установка и настройка skills/plugins для проекта TelegramMassSender

## Цель

Подготовить Claude Code к полноценной разработке, тестированию, отладке и выпуску проекта TelegramMassSender — Windows desktop-приложения на Python + PySide6 + qasync + Telethon, собираемого в EXE через PyInstaller.

Работай самостоятельно. Не проси меня вручную скачивать каждый skill/plugin, если его можно установить или подключить через доступные механизмы Claude Code.

---

# 1. Сначала изучи проект

Перед установкой:

1. Определи корень проекта.
2. Прочитай существующий `CLAUDE.md`, если он есть.
3. Изучи структуру проекта.
4. Определи:

   * Python version;
   * используемый package manager;
   * зависимости;
   * PySide6;
   * qasync/asyncio;
   * Telethon;
   * pytest;
   * PyInstaller;
   * существующие tests;
   * существующие `.claude/skills`, `.claude/commands`, plugins и прочие Claude Code-конфигурации.
5. Не изменяй рабочий код приложения на этом этапе.

---

# 2. Проверь возможности текущего Claude Code

Определи, какие механизмы доступны в текущей версии Claude Code:

* plugins;
* marketplaces;
* skills;
* commands;
* hooks;
* project-level `.claude/` configuration.

Проверь актуальный синтаксис установки plugins/skills для установленной версии Claude Code.

НЕ предполагай, что команды из этого файла обязательно существуют в конкретной версии Claude Code.

Если команда не поддерживается — найди корректный способ для текущей версии.

---

# 3. Установи полезные официальные/проверенные инструменты

В первую очередь проверь возможность установки:

## Superpowers

Если доступен официальный plugin:

```text
/plugin install superpowers@claude-plugins-official
```

Установи его.

После установки проверь, что он действительно доступен Claude Code.

---

# 4. Подбери skills/plugins по категориям

Нужны инструменты для следующих областей:

### Python

Нужны навыки для:

* современного Python;
* type hints;
* async/await;
* архитектуры Python-проектов;
* обработки исключений;
* dependency management;
* написания поддерживаемого кода.

### Testing

Нужны:

* pytest;
* unit tests;
* integration tests;
* regression tests;
* mocking;
* async tests;
* test-driven debugging;
* анализ покрытия тестами.

Особенно важно:

При исправлении бага сначала воспроизводить проблему тестом, затем исправлять код и добавлять regression test.

### PySide6 / Qt

Нужны навыки для:

* PySide6;
* Qt signals/slots;
* event loop;
* threading;
* async integration;
* qasync;
* корректного завершения приложения;
* GUI state management;
* предотвращения зависаний UI.

### asyncio

Нужны:

* asyncio;
* qasync;
* event loops;
* cancellation;
* graceful shutdown;
* race conditions;
* async exception handling.

### Telethon / Telegram API

Нужны навыки для:

* Telethon;
* Telegram MTProto;
* Telegram entities;
* access_hash;
* usernames;
* numeric IDs;
* media sending;
* albums;
* formatting entities;
* UTF-16 offsets;
* FloodWait;
* session management;
* 2FA;
* Telegram API errors.

ВАЖНО:

Не предлагай методы обхода Telegram anti-spam/anti-flood механизмов.

Приложение должно использовать Telegram API корректно и предназначаться для контролируемой отправки сообщений получателям, которым пользователь имеет право их отправлять.

### Windows

Нужны:

* Windows desktop development;
* `%APPDATA%`;
* Windows paths;
* Windows DPAPI;
* subprocess;
* packaging;
* Windows-specific bugs.

### PyInstaller

Нужны:

* PyInstaller;
* сборка Windows EXE;
* `onedir`;
* hidden imports;
* bundled resources;
* runtime paths;
* clean builds;
* release verification.

### Git

Нужны:

* git workflow;
* diff review;
* meaningful commits;
* safe refactoring;
* rollback;
* checking changed files.

### Security

Нужны навыки для:

* secure local storage;
* secrets management;
* Windows DPAPI;
* session protection;
* не сохранять 2FA password;
* безопасного логирования;
* предотвращения утечки API credentials;
* проверки пользовательского ввода.

### Code review

Нужны:

* архитектурный review;
* поиск потенциальных багов;
* поиск race conditions;
* error handling review;
* security review;
* regression analysis.

### Debugging

Нужны:

* systematic debugging;
* reproduction-first;
* root cause analysis;
* minimal fixes;
* regression testing.

---

# 5. Не устанавливай мусор

НЕ устанавливай skills/plugins только ради количества.

Не нужны для этого проекта:

* React;
* Next.js;
* frontend web frameworks;
* Kubernetes;
* Terraform;
* AWS;
* Docker-specific tooling;
* mobile development;
* game development;
* unrelated AI frameworks;
* unrelated databases;
* unrelated DevOps tooling.

Если skill не приносит очевидной пользы Python + PySide6 + asyncio + Telethon + Windows desktop проекту — не устанавливай его.

---

# 6. Проверка существующих skills

Перед установкой каждого инструмента:

1. Проверь, установлен ли он уже.
2. Если установлен — не создавай дубликат.
3. Если установленная версия рабочая — оставь её.
4. Если plugin уже активен — не переустанавливай без необходимости.

---

# 7. Создай project-specific skills

Если соответствующих skills ещё нет, создай их внутри:

```text
.claude/skills/
```

Создай следующие skills:

```text
.claude/skills/telegram-development/
.claude/skills/telethon-debugging/
.claude/skills/qt-async-development/
.claude/skills/telegram-media-testing/
.claude/skills/windows-exe-release/
.claude/skills/security-review/
.claude/skills/regression-testing/
```

Для каждого skill создай корректный `SKILL.md`.

---

# 8. Содержимое project-specific skills

## telegram-development

Skill должен заставлять Claude:

* учитывать Telegram API limitations;
* правильно работать с Telethon entities;
* учитывать access_hash;
* различать private users, groups и channels;
* корректно обрабатывать FloodWait;
* не предлагать anti-ban обходы;
* не использовать небезопасные способы хранения credentials;
* писать тесты на Telegram-related business logic.

---

## telethon-debugging

При проблемах с Telegram:

1. Определить точную версию Telethon.
2. Проверить фактический traceback.
3. Найти минимальный reproduction case.
4. Проверить документацию/API behavior.
5. Проверить исходный код Telethon при необходимости.
6. Написать regression test.
7. Исправить проблему минимально.
8. Запустить targeted tests.
9. Запустить полный test suite.

Особенно внимательно проверять:

* entities;
* formatting_entities;
* UTF-16 offsets;
* albums;
* media;
* async behavior;
* FloodWait;
* session handling.

---

## qt-async-development

При изменениях GUI:

* не блокировать Qt event loop;
* не блокировать asyncio event loop;
* корректно работать с qasync;
* учитывать cancellation;
* корректно завершать фоновые задачи;
* не оставлять hanging tasks;
* проверять закрытие окна;
* проверять WM_CLOSE;
* проверять завершение packaged EXE.

---

## telegram-media-testing

Для media-related изменений обязательно тестировать:

* 1 файл;
* 2 файла;
* 3 файла;
* несколько файлов;
* caption;
* bold;
* italic;
* underline;
* links;
* emoji;
* UTF-16 offsets;
* отсутствие caption;
* разные типы media;
* album отправку.

Если используется низкоуровневый Telegram API вызов — проверять фактические параметры запроса.

---

## windows-exe-release

Перед release:

1. Запустить полный test suite.
2. Выполнить clean PyInstaller build.
3. Проверить наличие EXE.
4. Проверить запуск EXE на чистом окружении.
5. Проверить необходимые bundled files.
6. Проверить `%APPDATA%`.
7. Проверить корректное закрытие приложения.
8. Проверить отсутствие Python/Node dependency для конечного пользователя.
9. Проверить README.
10. Проверить ZIP/release artifact.

---

## security-review

Проверять:

* API ID/Hash;
* Telegram sessions;
* 2FA;
* локальную БД;
* logs;
* secrets;
* temporary files;
* exception messages;
* credentials accidentally written to logs;
* bundled configuration.

Не сохранять пароль 2FA без явной необходимости.

Не выводить credentials в логах.

---

## regression-testing

Каждый исправленный баг должен по возможности получать regression test.

Workflow:

```text
bug
↓
reproduce
↓
write failing test
↓
fix
↓
run targeted test
↓
run full test suite
↓
manual smoke test if GUI/Telegram behavior is involved
```

---

# 9. Создай или обнови CLAUDE.md

Если `CLAUDE.md` уже существует:

* не уничтожай существующие полезные инструкции;
* аккуратно дополни их.

Если его нет — создай.

Он должен содержать следующие основные правила.

---

## Project rules

### Architecture

Не переписывай архитектуру проекта без необходимости.

Перед крупным изменением:

1. изучи существующую архитектуру;
2. найди связанные компоненты;
3. определи минимальное изменение;
4. оцени regression risk.

### Bug fixing

Не исправляй баг «на глаз».

Всегда:

```text
reproduce → understand root cause → test → fix → regression test → full suite
```

### Tests

После изменения кода запускай:

* targeted tests;
* затем полный test suite.

Не удаляй существующие тесты только ради прохождения suite.

### GUI

Не блокируй UI event loop.

Все долгие операции должны быть async/background operations в соответствии с существующей архитектурой проекта.

### Telegram

Не добавляй:

* anti-ban bypass;
* flood-limit bypass;
* спам-механику;
* обход Telegram restrictions.

FloodWait должен обрабатываться безопасно.

### Security

Никогда не печатай в ответ:

* API hash;
* session contents;
* passwords;
* secrets.

Не добавляй secrets в Git.

### Release

Перед утверждением, что задача завершена:

```text
tests
↓
build
↓
launch
↓
smoke test
```

---

# 10. Проверка после установки

После всех изменений:

1. Покажи список реально установленных plugins/skills.
2. Покажи созданные `.claude/skills`.
3. Покажи изменённый `CLAUDE.md`.
4. Проверь, что нет дубликатов.
5. Проверь, что конфигурация синтаксически корректна.
6. Проверь, что Claude Code видит созданные skills.
7. Не изменяй application source code без необходимости.

---

# 11. Итоговый отчёт

В конце выведи таблицу:

| Инструмент     | Статус                   | Источник | Для чего нужен |
| -------------- | ------------------------ | -------- | -------------- |
| Superpowers    | installed/skipped/failed | ...      | ...            |
| Python         | ...                      | ...      | ...            |
| Testing        | ...                      | ...      | ...            |
| PySide6/Qt     | ...                      | ...      | ...            |
| asyncio/qasync | ...                      | ...      | ...            |
| Telethon       | ...                      | ...      | ...            |
| Windows        | ...                      | ...      | ...            |
| PyInstaller    | ...                      | ...      | ...            |
| Git            | ...                      | ...      | ...            |
| Security       | ...                      | ...      | ...            |
| Code Review    | ...                      | ...      | ...            |

После таблицы отдельно укажи:

* что установлено;
* что уже было установлено;
* что создано локально;
* что не удалось установить;
* почему не удалось;
* какие действия требуют ручного вмешательства.

Не утверждай, что skill установлен, если ты не смог это проверить.

---

# 12. Главное правило

Не делай вид, что что-то установлено или проверено.

Если конкретный plugin/skill отсутствует, несовместим или недоступен:

```text
не выдумывать
↓
зафиксировать проблему
↓
использовать доступный официальный способ
↓
если невозможно — создать локальный project-specific skill
```

Главная цель — получить максимально полезную и стабильную среду Claude Code для разработки TelegramMassSender, а не максимальное количество установленных skills.
