Meeting Transcriber
Автоматическая транскрибация видеоконференций (Zoom, Teams, Webex, TrueConf,Meet, Телемост и др.) в реальном времени. Офлайн-модель Whisper (faster-whisper):бесплатно, безлимитно, аудио никуда не отправляется.

Возможности
🔍 Автодетект платформ ВКС по процессам + двухфакторный триггер «процесс + речь»
🔴 Запись голосов всех участников (системный звук) или своего микрофона
🖥 GUI + системный трей: приложение живёт в фоне, окно можно закрыть
📋 Копирование всего текста кнопкой / из меню трея / Ctrl+Alt+C
💾 Автосохранение транскриптов с таймкодами
⚙ Настройки в GUI, конфиг config.json, логи в logs/
🚫 Защита от второго экземпляра
Готовые сборки
Платформа	Файл	Где
Windows 10/11 x64	MeetingTranscriber.exe	Releases / Actions
macOS 11+ (Intel/Apple Silicon)	MeetingTranscriber-macOS.dmg	Releases / Actions
macOS — первый запуск
Откройте dmg, перетащите приложение в Applications.
Если Gatekeeper блокирует запуск (сборка ad-hoc подписана):xattr -cr "/Applications/Meeting Transcriber.app"
Разрешите доступ к микрофону в «Системные настройки → Конфиденциальность».
Для захвата голосов участников установите BlackHole 2ch(existential.audio/blackhole) — приложение найдёт его автоматически ипокажет подсказку, если он отсутствует.
Windows — первый запуск
SmartScreen может предупредить о неподписанном exe — «Подробнее → Выполнить в любом случае».

Запуск из исходников
git clone <repo> && cd meeting-transcriberpip install -e ".[hotkeys]"          # + "[gpu]" для NVIDIApython -m transcriber                # или команда meeting-transcriber
Сборка
# Windows (PowerShell):           # macOS:scripts\build_windows.ps1         chmod +x scripts/build_macos.sh                                  ./scripts/build_macos.sh
Артефакты: dist/MeetingTranscriber.exe, dist/MeetingTranscriber-macOS.dmg.Сборка с GPU: установите nvidia-cublas-cu12 nvidia-cudnn-cu12 и задайтеWITH_CUDA=1 (exe вырастет до ~2 ГБ).

Конфиг …/meeting-transcriber/config.json
Ключ	Значения по умолчанию	Описание
model	auto	tiny/base/small/medium/large-v3/large-v3-turbo
compute	auto	cpu/cuda
language	ru	код языка или auto
source	loopback	loopback (участники) / mic (вы)
trigger	process+sound	или sound — для встреч в браузере
silence_timeout	180	сек тишины до автоостановки
processes	zoom, teams, …	подстроки имён процессов ВКС
Хоткеи
Ctrl+Alt+R — старт/стоп записи · Ctrl+Alt+C — копировать весь текст(macOS: только через меню трея — системные хоткеи ограничены ОС)

Логи и данные
Windows: %APPDATA%\meeting-transcriber
macOS: ~/Library/Application Support/meeting-transcriberВнутри: config.json, transcripts/, logs/transcriber.log.
Как собрать и получить артефакты
Локально:
powershell:
# Windows → exe
scripts\build_windows.ps1

bash:
# macOS → dmg
chmod +x scripts/build_macos.sh && ./scripts/build_macos.sh

Через CI: запушьте тег v1.0.0 — GitHub Actions соберёт оба артефакта и прикрепит их к Release.

Ключевые инженерные решения, на которые обратите внимание:

hiddenimports в spec обязательны: soundcard/pystray импортируют бэкенды динамически, без них exe упадёт на старте.
На macOS трей запускается через run_detached(), потому что tkinter должен занимать main thread — это классический конфликт, который здесь обойдён.
NSMicrophoneUsageDescription вшит в Info.plist — без него macOS молча убьёт захват аудио.
Модель Whisper (~1–3 ГБ) не пакуется в бинарь — скачивается с HuggingFace при первом распознавании в пользовательский кэш; зеркало задаётся переменной HF_ENDPOINT=https://hf-mirror.com, если HuggingFace недоступен.