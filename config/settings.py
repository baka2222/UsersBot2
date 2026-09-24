"""
Настройки Django. Все параметры берутся из единого файла .env в корне проекта.
"""
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем единый .env из корня проекта
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# --- Базовые настройки безопасности ---
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]
# Доверенные источники для CSRF. По умолчанию строятся из ALLOWED_HOSTS,
# но при работе за доменом/HTTPS можно явно задать через .env
# (например: https://panel.example.com,https://www.example.com)
_csrf_env = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
if _csrf_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_env.split(",") if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = (
        [f"http://{h}" for h in ALLOWED_HOSTS] + [f"https://{h}" for h in ALLOWED_HOSTS]
    )

# --- Работа за обратным прокси (Nginx) ---
# Nginx проксирует запросы на Gunicorn; доверяем его заголовкам.
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Приложения ---
INSTALLED_APPS = [
    "jazzmin",  # должен идти перед django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "nested_admin",  # вложенные инлайны (сценарии и ответы внутри группы)
    "simulator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- База данных ---
# Значение считается строкой подключения, только если это действительно URL
# (например postgres://...). Пустая строка или случайный текст -> используем SQLite.
_database_url = os.getenv("DATABASE_URL", "").strip()
_sqlite_default = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Разумные таймауты для одновременной работы панели и фонового модуля
        "OPTIONS": {"timeout": 20},
    }
}
if "://" in _database_url:
    try:
        DATABASES = {"default": dj_database_url.parse(_database_url, conn_max_age=600)}
    except Exception:
        # Некорректная строка подключения — не роняем проект, откатываемся на SQLite
        DATABASES = _sqlite_default
else:
    DATABASES = _sqlite_default

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Локализация ---
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "ru-ru")
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ = True

# --- Статика ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Параметры Telegram / фонового модуля (читаются также из .env) ---
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
WORKER_AUTOJOIN = env_bool("WORKER_AUTOJOIN", True)

# --- Защита аккаунтов от блокировок и обрывов (см. simulator/telegram_client.py) ---
# Флуд-лимиты Telegram короче этого порога (сек) библиотека пережидает сама,
# не роняя отправку и не «долбя» сервер повторами.
TELEGRAM_FLOOD_SLEEP_THRESHOLD = int(os.getenv("TELEGRAM_FLOOD_SLEEP_THRESHOLD", "120") or "120")
# Живучесть соединения: сколько раз переподключаться и с какой паузой.
TELEGRAM_CONNECTION_RETRIES = int(os.getenv("TELEGRAM_CONNECTION_RETRIES", "5") or "5")
TELEGRAM_RETRY_DELAY = int(os.getenv("TELEGRAM_RETRY_DELAY", "2") or "2")
TELEGRAM_REQUEST_RETRIES = int(os.getenv("TELEGRAM_REQUEST_RETRIES", "5") or "5")
# Язык, которым представляется «клиент» (по умолчанию — из языка панели).
TELEGRAM_DEVICE_LANG = os.getenv("TELEGRAM_DEVICE_LANG", (LANGUAGE_CODE or "ru")[:2]) or "ru"
# Необязательный SOCKS5-прокси. Полезно, если аккаунтов много: не гоняйте
# десятки сессий с одного IP. Оставьте host пустым, чтобы прокси не использовать.
TELEGRAM_PROXY_HOST = os.getenv("TELEGRAM_PROXY_HOST", "")
TELEGRAM_PROXY_PORT = int(os.getenv("TELEGRAM_PROXY_PORT", "0") or "0")
TELEGRAM_PROXY_USER = os.getenv("TELEGRAM_PROXY_USER", "")
TELEGRAM_PROXY_PASS = os.getenv("TELEGRAM_PROXY_PASS", "")

# Каталог для рантайм-данных (лог бота). В Docker — общий том между web и bot.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
BOT_LOG_FILE = DATA_DIR / "bot.log"
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"

# --- Логирование: диагностические сообщения simulator.* видно в консоли ---
# (полезно, например, чтобы увидеть сырой ответ Telegram при отправке кода входа)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "simulator": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Оформление панели (Jazzmin) ---
JAZZMIN_SETTINGS = {
    "site_title": "Панель управления",
    "site_header": "Панель управления",
    "site_brand": "Симуляция активности",
    "welcome_sign": "Добро пожаловать в панель управления",
    "copyright": "",
    "search_model": ["simulator.Group", "simulator.TelegramAccount"],
    "topmenu_links": [
        {"name": "Главная", "url": "admin:index"},
        {"name": "✉ Сообщения", "url": "admin:simulator_dialog_changelist"},
        {"name": "▶ Запуск бота", "url": "admin:bot_control"},
    ],
    # Отдельная заметная кнопка в боковом меню
    "custom_links": {
        "simulator": [
            {"name": "Запуск бота", "url": "admin:bot_control", "icon": "fas fa-robot"},
        ],
    },
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "simulator.Group": "fas fa-layer-group",
        "simulator.TelegramAccount": "fas fa-user-astronaut",
        "simulator.MessageTemplate": "fas fa-comment-dots",
        "simulator.ActivityLog": "fas fa-clipboard-list",
        "simulator.Dialog": "fas fa-comments",
        "simulator.ApiCredentials": "fas fa-key",
    },
    "order_with_respect_to": [
        "simulator",
        "simulator.Dialog",
        "simulator.Group",
        "simulator.TelegramAccount",
        "simulator.ApiCredentials",
        "simulator.MessageTemplate",
        "simulator.ActivityLog",
        "auth",
    ],
    # Вся карточка группы — одной цельной страницей (сценарии и ответы внутри)
    "changeform_format": "single",
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "navbar_small_text": False,
    "sidebar_nav_compact_style": True,
}
