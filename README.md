# InterviewLab Backend (FastAPI + MongoDB)

API платформы технического скрининга: тесты и задания, инвайт-ссылки, прохождение
кандидатом, live-прокторинг с записью сессии, AI-генерация заданий и AI-анализ решений.

Фронтенд ([InterviewLabFront](https://github.com/tihon2008vlasov-boop/InterviewLabFront))
работает **только** с этим сервисом — режима моков у него больше нет.

## Стек

- **FastAPI** — HTTP API + WebSocket, автодокументация на `/docs`
- **MongoDB + Beanie (Motor)** — асинхронная ODM
- **JWT (python-jose) + bcrypt** — авторизация
- **Pydantic v2 / pydantic-settings** — валидация и настройки из `.env`
- **Google Gemini** — генерация заданий и анализ кандидатов (обычный HTTPS через `urllib`, без SDK)
- **smtplib** — реальная отправка приглашений и решений по SMTP
- **ffmpeg** (опционально, внешний бинарник) — индексация записей для перемотки

## Запуск

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env                    # заполнить значения
python -m app.seed                        # демо-данные: HR-аккаунт, тесты, инвайт-ссылки
python -m app.scripts.seed_task_library   # библиотека готовых заданий (опционально)
uvicorn app.main:app --reload --port 8000
```

После сида доступен HR-аккаунт **hr@interviewlab.ai / Password123!** и инвайт-ссылки
`DEMO01` (без лимитов), `RCT7Q2` (50 использований, 14 дней), `NODE01` — кандидатская ссылка
выглядит как `http://localhost:5173/test/DEMO01`. Повторный запуск сида безопасен.

Swagger: http://localhost:8000/docs · Health: `GET /api/health`

> Если MongoDB не поднята, приложение **всё равно стартует** и пишет в консоль
> `[db] ERROR: cannot connect to MongoDB` — но все ручки с БД будут падать.

## .env для разработки

Готовый рабочий `.env` — скопируй как есть в `backend/.env`:

```env
ENV=development
HOST=0.0.0.0
PORT=8000
CLIENT_URL=http://localhost:5173

MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=interviewlab

JWT_SECRET=interviewlab-dev-secret-2026
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080

INVITE_LINK_BASE_URL=http://localhost:5173/test
```

Секретов тут нет: `localhost:27017` — это адрес MongoDB **на твоём же компьютере**.
Этот env одинаковый у всех, но базу он не «расшаривает» — у каждого своя (см. ниже).

`CLIENT_URL` — единственный origin, разрешённый в CORS. Если фронт запущен не на
`localhost:5173` (например, через `--host` или ngrok), этот адрес надо поменять, иначе
браузер заблокирует запросы.

Полный список переменных — в `.env.example`. Что важно знать:

| Переменная | Зачем |
|---|---|
| `GEMINI_API_KEY` | **единственный AI-ключ в проекте**: генерация заданий, макетов, анализ кандидата |
| `GEMINI_MODEL` / `GEMINI_GENERATION_MODEL` | модели для анализа и для генерации заданий |
| `SMTP_*`, `EMAIL_FROM` | реальная отправка приглашений и решений; без них отправка вернёт ошибку |
| `RECORDINGS_DIR` | куда складывать записи сессий (по умолчанию `./data/recordings`) |
| `RECORDING_RETENTION_DAYS` | через сколько дней запись удаляется фоновой задачей (30) |
| `RECORDING_MAX_BYTES` / `RECORDING_MAX_CHUNK_BYTES` | лимиты на размер записи (2 ГБ) и чанка (25 МБ) |

## MongoDB

Нужен запущенный MongoDB (`mongodb://localhost:27017` по умолчанию).

**Установка (один раз, всё по дефолту):**

1. Скачать [MongoDB Community Server](https://www.mongodb.com/try/download/community) (msi для Windows)
2. В установщике ничего не менять: «Complete», галочка **Install MongoDB as a Service** оставлена
3. Готово — Mongo запускается сама как служба Windows и слушает `localhost:27017`

Либо одной командой: `winget install MongoDB.Server`

Проверить, что служба работает: `Get-Service MongoDB` (Status должен быть `Running`).

**У каждого разработчика — своя локальная база.** `.env` с `localhost:27017` у всех
одинаковый, но данные не общие: каждый прогоняет `python -m app.seed` и получает свой
стартовый набор.

### Общая база на команду (MongoDB Atlas, бесплатно)

Если нужно, чтобы все видели одни и те же данные:

1. Зарегистрироваться на [mongodb.com/atlas](https://www.mongodb.com/atlas) → **Create Cluster** → tier **M0 (Free)**
2. **Database Access** → Add New Database User → логин/пароль (запомнить)
3. **Network Access** → Add IP Address → `0.0.0.0/0` (разрешить всем; на время разработки ок)
4. **Connect → Drivers** → скопировать connection string вида
   `mongodb+srv://user:<password>@cluster0.xxxxx.mongodb.net`
5. Каждый в команде заменяет в своём `.env` одну строку:
   ```env
   MONGODB_URI=mongodb+srv://user:пароль@cluster0.xxxxx.mongodb.net
   ```
   Локальную Mongo при этом ставить не нужно. Сид (`python -m app.seed`) прогоняется
   один раз кем-то одним — он идемпотентный, повторные запуски ничего не дублируют.

⚠️ Строку Atlas с паролем в git не коммитить — передавать лично (мессенджер/менеджер секретов).

## Как посмотреть коллекции

База: `interviewlab` (см. `MONGODB_DB` в `.env`). Коллекции создаются при первой записи —
после сидов появятся `users`, `companies`, `tests`, `task_templates`, `candidates`,
`sessions`, `invitations`.

- **MongoDB Compass** (GUI, рекомендую) — [скачать](https://www.mongodb.com/try/download/compass),
  строка подключения `mongodb://localhost:27017`, слева база `interviewlab`
- **mongosh** (консоль, ставится вместе с сервером): `mongosh`, затем
  `use interviewlab`, `show collections`, `db.users.find().pretty()`

## Структура

```
app/
  main.py                  # приложение, CORS, lifespan (init БД + фоновая чистка записей)
  seed.py                  # демо-данные: компания, HR, тесты, ссылки, кандидаты
  task_catalog.py          # каталог готовых заданий (источник для библиотеки)
  core/
    config.py              # настройки из .env (pydantic-settings)
    db.py                  # подключение Mongo + init_beanie
    security.py            # jwt, хэширование паролей, get_current_user_id
    tenant.py              # current_company_id — мультитенантность
    lookup.py              # get_or_none: безопасный поиск документа по id
  models/                  # Beanie-документы: User, Company, Test, TaskTemplate,
                           # Candidate, Session, Invitation
  schemas/                 # Pydantic-схемы запросов/ответов
  services/
    gemini.py              # генерация заданий и HTML-макетов
    candidate_analysis.py  # AI-анализ решения кандидата
    typing_forensics.py    # эвристика «печатал сам или вставил»
    proctoring.py          # запись инцидентов прокторинга, уровень риска
    recordings.py          # чанки записи, склейка, ffmpeg-индексация, ретеншен
    emailer.py             # SMTP: приглашения и письма с решением
  api/
    router.py              # сборка /api
    routes/                # auth, tests, task_library, candidates, sessions,
                           # analytics, admin, ai, proctoring, settings
  scripts/
    seed_task_library.py   # наполнить библиотеку заданий из task_catalog
    repair_recordings.py   # пересобрать/починить записи сессий
```

## API

Все ручки под `/api`. Защищённые — через `Depends(get_current_user_id)`,
данные компании — через `Depends(current_company_id)`.

**Auth** `/api/auth`
- `POST /register`, `POST /login` — JWT + bcrypt
- `POST /forgot-password` — заглушка: всегда отдаёт «If the email exists…», письмо не шлёт
- `POST /reset-password` — **501, не реализовано**

**Тесты** `/api/tests`
- `GET /`, `POST /`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`, `POST /{id}/duplicate`
- `POST /{id}/links`, `POST /{id}/links/{link_id}/toggle` — инвайт-ссылки
- `POST /{id}/invitations` — приглашения по email (реальная отправка через SMTP)

**Библиотека заданий** `/api/task-library`
- `GET /`, `POST /`, `PATCH /{id}`, `DELETE /{id}` — переиспользуемые шаблоны заданий

**Кандидаты** `/api/candidates`
- `GET /`, `GET /{id}`, `PATCH /{id}/status`
- `POST /{id}/analyze` — AI-анализ на Gemini, `202 Accepted`, статус в `analysis_status`
  (`not_started` → `pending` → `completed`/`failed`); `?force=true` перезапускает
- `POST /{id}/send-results` — письмо кандидату с решением

**Сессии** `/api/sessions`
- `GET /` — активные сессии для страницы Live sessions
- `POST /{code}/start` — старт по коду ссылки: создаются Candidate + Session,
  проверяются лимиты и срок ссылки
- `POST /{session_id}/events` — heartbeat каждые 5 сек (стадия, файл, прогресс,
  tab switches) + replay-события
- `POST /{session_id}/submit` — финальная отправка, файлы кандидата сохраняются в БД

**Прокторинг** `/api/proctoring`
- `WS /ws/{session_id}` — WebRTC-signaling между кандидатом и HR
- `POST /events/{session_id}` — журнал инцидентов
- `POST /recordings/{session_id}/start` · `/chunks` · `/complete` — заливка записи чанками
- `GET /recordings/{session_id}/media` — отдача записи (с поддержкой Range)
- `POST /recordings/{session_id}/playback-access` — токен на просмотр

**Настройки** `/api/settings`
- `GET ""` — профиль, компания и настройки уведомлений одним ответом
- `PATCH /profile` — имя, email, аватар (`avatar_url`)
- `PATCH /company` — название, сайт, логотип
- `PATCH /notifications` — тумблеры `candidate_completed`, `weekly_report`,
  `ai_analysis`, `team_activity`, `product_updates` (хранятся в `User.notification_preferences`)
- `POST /password` — смена пароля с проверкой текущего, `204`
- `POST /api-key` — выпуск нового ключа компании; **полный ключ отдаётся один раз**,
  в БД остаются только sha256-хэш и префикс. Доступно ролям `owner` и `admin`
- `DELETE /api-key` — отзыв ключа, `204`

**Файлы** `/api/files`
- `GET /{file_id}` — отдаёт аватар или логотип из GridFS

**Аналитика и прочее**
- `GET /api/analytics/dashboard`, `/overview`, `/recent-invitations`, `/notifications`
- `GET /api/team` — участники компании · `POST /api/team` — добавить участника
- `POST /api/ai/tasks/generate`, `POST /api/ai/tasks/mockup` — генерация на Gemini
- `GET /api/health`

## Live-прокторинг: как устроено

- Кандидат до старта явно разрешает камеру, микрофон и показ **всего экрана**;
  сессия стартует только с `proctoring_consent=true`.
- Видео и аудио идут **peer-to-peer через WebRTC**, backend работает только как signaling —
  поток через сервер не проксируется.
- Компьютерное зрение и распознавание речи крутятся **в браузере кандидата**
  (TensorFlow.js и Web Speech API). На сервер уходит только текстовый журнал:
  `phone_detected`, `multiple_people`, `face_missing`, `identity_mismatch`,
  `looking_away`, `speech_detected`, `sustained_audio`, `tab_hidden`, `camera_stopped`,
  `camera_obstructed`, `screen_share_stopped`, `paste` и т.д. По ним считается
  `risk_level` (`low` / `medium` / `high` / `critical`).
- Параллельно браузер пишет композит «экран + камера» через `MediaRecorder` и шлёт
  чанками на `/recordings/...`. Файлы лежат в `RECORDINGS_DIR`, старше
  `RECORDING_RETENTION_DAYS` удаляются фоновой задачей (проверка раз в час).

**ffmpeg** ищется в `PATH`. Если его нет — запись сохранится и проиграется, но без перемотки
по таймкодам; в консоли будет `[recordings] WARNING: ffmpeg not found`.
Установка: `winget install Gyan.FFmpeg`.

## Аватары и логотипы: GridFS

Картинки профиля и компании хранятся **в MongoDB через GridFS** — в коллекциях
`images.files` и `images.chunks`. Никакой настройки не требуется: работает на локальной
Mongo и на Atlas одинаково.

Как это работает:

1. Браузер шлёт выбранный файл как `data:image/png;base64,...`.
2. `app/services/images.py` декодирует, проверяет тип и размер, кладёт в GridFS.
3. В документе `User` / `Company` остаётся короткая ссылка `"/files/<id>"` — а не мегабайт base64.
4. Отдаётся через `GET /api/files/{id}` с `Cache-Control: immutable`, поэтому браузер
   тянет картинку один раз.
5. При замене или удалении картинки старый файл сразу удаляется из GridFS.

Ограничения на входе: PNG, JPEG, WebP, GIF, до 2 МБ. **SVG отклоняется** — внутрь можно
спрятать скрипт. Битый base64, внешние ссылки и превышение размера дают `422` / `413`.

Старые значения с data URL остаются валидными картинками и переедут в GridFS при первом
пересохранении профиля.

## Что доработать

- `POST /auth/reset-password` — единственная 501-заглушка. Плюс `forgot-password` ничего
  не отправляет, так что восстановление пароля не работает end-to-end: фронтовая страница
  `/reset-password` существует и шлёт запрос, но получает 501.
- **Записи сессий лежат на локальном диске** (`RECORDINGS_DIR`). На хостинге с эфемерной
  ФС (Railway, Render, Heroku) они пропадут при первом же редеплое — под прод нужен S3
  или примонтированный том. Аватары и логотипы этой проблемы уже не имеют, см. ниже.
- Выпущенный API-ключ компании нигде не проверяется: `POST /settings/api-key` его
  генерирует и хранит хэш, но ни один эндпоинт не аутентифицирует по нему запросы.

## Соглашения

- Все ручки под `/api/*`; защищённые — через `Depends(get_current_user_id)`
- Выборки данных компании фильтруются по `current_company_id` — пользователь видит
  только свои тесты, кандидатов и статистику
- Ошибки — `HTTPException` с понятным сообщением
- Поля в БД и API — `snake_case` (фронт мапит в camelCase в `shared/services/backendMappers.ts`)
