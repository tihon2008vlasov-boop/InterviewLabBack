# InterviewLab Backend (FastAPI + MongoDB)

Каркас API для платформы технического скрининга. Фронтенд сейчас работает на моках —
этот сервис задаёт структуру, которую команда дорабатывает и подключает к фронту.

## Стек

- **FastAPI** — HTTP API, автодокументация на `/docs`
- **MongoDB + Beanie (Motor)** — асинхронная ODM
- **JWT (python-jose) + passlib/bcrypt** — авторизация
- **Pydantic v2** — валидация и настройки из `.env`

## Запуск

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

copy .env.example .env         # заполнить значения
python -m app.seed             # демо-данные: HR-аккаунт, тесты, инвайт-ссылки
uvicorn app.main:app --reload --port 8000
```

После сида доступен HR-аккаунт **hr@interviewlab.ai / Password123!** и инвайт-ссылки
`DEMO01` (без лимитов), `RCT7Q2`, `NODE01` — кандидатская ссылка выглядит как
`http://localhost:5173/test/DEMO01`. Повторный запуск сида безопасен (ничего не дублирует).

Swagger: http://localhost:8000/docs · Health: `GET /api/health`

Нужен запущенный MongoDB (`mongodb://localhost:27017` по умолчанию). Проще всего — из папки `backend/`:

```bash
docker compose up -d
```

Это поднимет Mongo + веб-просмотрщик коллекций (mongo-express) на http://localhost:8081.

## Как посмотреть коллекции

База: `interviewlab` (см. `MONGODB_DB` в `.env`). Коллекции создаются при первой записи —
зарегистрируй пользователя через Swagger (`POST /api/auth/register`), появятся `users` и `companies`.

- **mongo-express** — http://localhost:8081 → база `interviewlab`
- **MongoDB Compass** (GUI) — строка подключения `mongodb://localhost:27017`
- **mongosh** — `docker exec -it interviewlab-mongo mongosh`, затем `use interviewlab`, `show collections`, `db.users.find().pretty()`

Для общей командной БД — бесплатный кластер [MongoDB Atlas](https://www.mongodb.com/atlas),
в `.env` меняется только `MONGODB_URI`.

## Структура

```
app/
  main.py             # приложение, CORS, lifespan (инициализация БД)
  core/
    config.py         # настройки из .env (pydantic-settings)
    db.py             # подключение Mongo + init_beanie
    security.py       # jwt, хэширование паролей, get_current_user_id
  models/             # Beanie-документы: User, Company, Test, Candidate, Session, Invitation
  schemas/            # Pydantic-схемы запросов/ответов
  api/
    router.py         # сборка /api
    routes/           # auth, tests, candidates, sessions, analytics
```

## Что уже работает

- `POST /api/auth/register`, `POST /api/auth/login` — реальные, с Mongo и JWT
- CRUD тестов: список, создание, чтение, patch, удаление, дубликат
- Инвайт-ссылки: генерация кода, toggle
- Приглашения по email (запись в БД, без реальной отправки)
- Кандидаты: список с фильтрами, карточка, смена статуса
- `GET /api/analytics/dashboard` — живые счётчики из БД
- **Живой трекинг прохождений:**
  - `POST /api/sessions/{code}/start` — кандидат открывает ссылку, вводит имя/email → создаются Candidate + Session, проверяются лимиты/срок ссылки
  - `POST /api/sessions/{id}/events` — воркспейс шлёт heartbeat каждые 5 сек (стадия, текущий файл, прогресс, tab switches, камера) + replay-события
  - `POST /api/sessions/{id}/submit` — финальная отправка: файлы кандидата сохраняются в БД, сессия закрывается
  - `GET /api/sessions/` — активные сессии для страницы Live sessions (HR)
- `python -m app.seed` — демо-данные: HR-аккаунт, 2 теста, ссылки, кандидаты

## Что доработать (возвращают 501)

- `POST /auth/reset-password` — токены сброса пароля
- `POST /candidates/{id}/analyze` — AI-анализ (Anthropic API, ключ в `.env`)
- `GET /analytics/overview` — агрегации для страницы Analytics
- Отправка email (SMTP-параметры в `.env`), загрузка файлов в S3
- Мультитенантность: фильтрация всех запросов по `company_id` из JWT

## Соглашения

- Все ручки под `/api/*`; защищённые — через `Depends(get_current_user_id)`
- Ошибки — `HTTPException` с понятным сообщением
- Поля в БД и API — `snake_case` (фронт мапит в camelCase на своём слое API)
