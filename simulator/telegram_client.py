"""
Обёртки над Telethon для авторизации аккаунтов.

Функции синхронные (внутри поднимают собственный event loop через asyncio.run),
поэтому их удобно вызывать из обычных Django-вью и management-команд.
"""
import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger("simulator.telegram_client")


# ----------------------------------------------------------------------------
#  Единый «профиль устойчивости» для всех подключений
# ----------------------------------------------------------------------------
# Задачи профиля:
#   1) Сессия выглядит как обычный настольный Telegram на конкретном устройстве,
#      а не как одинаковые боты (разные, но СТАБИЛЬНЫЕ отпечатки на аккаунт).
#   2) Мелкие флуд-лимиты Telegram переживаются автоматически (flood_sleep_threshold).
#   3) Обрывы связи не роняют аккаунт — авто-переподключение с повторами.
#   4) При желании — прокси, чтобы не гнать десятки сессий с одного IP.
# Эти параметры не меняют, ЧТО и КОГДА отправляет бот, — только делают
# соединение живучее и незаметнее.

# Правдоподобные отпечатки настольного Telegram (устройство/ОС/версия приложения).
_DEVICE_POOL = [
    ("Desktop", "Windows 11", "5.10.1 x64"),
    ("Desktop", "Windows 10", "5.9.3 x64"),
    ("PC 64bit", "Windows 11", "5.10.5 x64"),
    ("Desktop", "macOS 14.6", "11.2.3"),
    ("Desktop", "macOS 15.1", "11.3.0"),
    ("Desktop", "Ubuntu 24.04", "5.10.0 x64"),
]


def _device_for(seed):
    """Стабильно (без случайности между перезапусками) выбирает отпечаток по «семени».

    В качестве семени используем номер телефона аккаунта — тогда один и тот же
    аккаунт всегда представляется одним и тем же устройством и при авторизации,
    и в фоновом процессе.
    """
    key = str(seed if seed not in (None, "") else "default").encode("utf-8")
    idx = int(hashlib.md5(key).hexdigest(), 16) % len(_DEVICE_POOL)
    return _DEVICE_POOL[idx]


def _proxy():
    """Необязательный SOCKS5-прокси из .env (если задан TELEGRAM_PROXY_HOST)."""
    host = getattr(settings, "TELEGRAM_PROXY_HOST", "") or ""
    if not host:
        return None
    try:
        import socks  # из пакета PySocks
    except ImportError:
        logger.warning(
            "TELEGRAM_PROXY_HOST задан, но пакет PySocks не установлен — прокси "
            "проигнорирован. Установите его: pip install PySocks."
        )
        return None
    port = int(getattr(settings, "TELEGRAM_PROXY_PORT", 0) or 0)
    user = getattr(settings, "TELEGRAM_PROXY_USER", "") or None
    password = getattr(settings, "TELEGRAM_PROXY_PASS", "") or None
    if user:
        return (socks.SOCKS5, host, port, True, user, password)
    return (socks.SOCKS5, host, port)


def client_settings(seed=None) -> dict:
    """Общие kwargs для TelegramClient: отпечаток устройства + живучесть соединения."""
    device_model, system_version, app_version = _device_for(seed)
    lang = getattr(settings, "TELEGRAM_DEVICE_LANG", "ru") or "ru"
    kwargs = dict(
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
        lang_code=lang,
        system_lang_code=lang,
        # Флуд-лимиты короче порога Telethon пережидает сам, не роняя запрос
        flood_sleep_threshold=int(getattr(settings, "TELEGRAM_FLOOD_SLEEP_THRESHOLD", 120)),
        connection_retries=int(getattr(settings, "TELEGRAM_CONNECTION_RETRIES", 5)),
        retry_delay=int(getattr(settings, "TELEGRAM_RETRY_DELAY", 2)),
        request_retries=int(getattr(settings, "TELEGRAM_REQUEST_RETRIES", 5)),
    )
    proxy = _proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


class TelegramConfigError(Exception):
    """API ID / API HASH не заданы в .env."""


class PasswordRequired(Exception):
    """Для входа включена двухфакторная защита — нужен облачный пароль."""


@dataclass
class AuthorizedAccount:
    session_string: str
    user_id: int
    username: str
    display_name: str


def _default_db_credentials():
    """(api_id, api_hash) приложения «по умолчанию» из базы, или (0, '')."""
    try:
        from .models import ApiCredentials

        obj = ApiCredentials.objects.filter(is_default=True).first()
        if obj and obj.api_id and obj.api_hash:
            return int(obj.api_id), obj.api_hash
    except Exception:  # noqa: BLE001 — на старте (до миграций) таблицы может ещё не быть
        pass
    return 0, ""


def _credentials():
    """Данные приложения по умолчанию: сначала «Главный аккаунт по умолчанию» из
    панели, затем .env. Бросает TelegramConfigError, если не заданы нигде.
    """
    api_id, api_hash = _default_db_credentials()
    if api_id and api_hash:
        return api_id, api_hash

    api_id = settings.TELEGRAM_API_ID
    api_hash = settings.TELEGRAM_API_HASH
    if not api_id or not api_hash:
        raise TelegramConfigError(
            "Не заданы API ID / API Hash. Добавьте «Главный аккаунт» в панели "
            "(и отметьте «по умолчанию») либо заполните .env."
        )
    return api_id, api_hash


def credentials_for_account(account):
    """Данные приложения для конкретного аккаунта: его приложение → по умолчанию → .env.

    `account` — экземпляр TelegramAccount. Если у аккаунта выбрано своё приложение
    и оно заполнено, берём его; иначе откатываемся к приложению по умолчанию / .env.
    """
    cred = getattr(account, "api_credentials", None)
    if cred and cred.api_id and cred.api_hash:
        return int(cred.api_id), cred.api_hash
    return _credentials()


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _describe_code_type(sent_type) -> str:
    """Человеко-понятное описание того, КУДА Telegram отправил код."""
    name = type(sent_type).__name__
    return {
        "SentCodeTypeApp": "в приложение Telegram (служебный чат «Telegram»)",
        "SentCodeTypeSms": "по SMS",
        "SentCodeTypeCall": "звонком (код продиктуют)",
        "SentCodeTypeMissedCall": "звонком-сбросом (код — последние цифры номера)",
        "SentCodeTypeFlashCall": "звонком",
        "SentCodeTypeEmailCode": "на привязанную почту",
    }.get(name, "в Telegram")


def send_login_code(phone: str, api_id=None, api_hash=None):
    """Шаг 1. Запрашивает код подтверждения.

    Возвращает (session_string, phone_code_hash, delivery),
    где delivery — куда именно был отправлен код.
    `api_id`/`api_hash` — приложение конкретного аккаунта; если не заданы, берётся
    приложение по умолчанию / из .env.
    """
    if not (api_id and api_hash):
        api_id, api_hash = _credentials()

    async def _do():
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(), api_id, api_hash, **client_settings(phone))
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            delivery = _describe_code_type(sent.type)
            # Сырой ответ Telegram — полезно для диагностики, если код так и не пришёл
            # (например, если приложение/IP временно ограничены на стороне Telegram).
            logger.info(
                "send_code_request phone=%s type=%s timeout=%s next_type=%s api_id=%s",
                phone, type(sent.type).__name__, sent.timeout,
                type(sent.next_type).__name__ if sent.next_type else None,
                api_id,
            )
            return StringSession.save(client.session), sent.phone_code_hash, delivery
        finally:
            await client.disconnect()

    return _run(_do())


def complete_login(session_string: str, phone: str, code: str,
                   phone_code_hash: str, password: str | None = None,
                   api_id=None, api_hash=None) -> AuthorizedAccount:
    """Шаг 2. Завершает вход по коду (и, при необходимости, паролю 2FA)."""
    if not (api_id and api_hash):
        api_id, api_hash = _credentials()

    async def _do():
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import SessionPasswordNeededError

        client = TelegramClient(StringSession(session_string), api_id, api_hash, **client_settings(phone))
        await client.connect()
        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                if not password:
                    raise PasswordRequired()
                await client.sign_in(password=password)

            me = await client.get_me()
            display = " ".join(p for p in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if p)
            return AuthorizedAccount(
                session_string=StringSession.save(client.session),
                user_id=me.id,
                username=me.username or "",
                display_name=display.strip(),
            )
        finally:
            await client.disconnect()

    return _run(_do())


def logout_account(session_string: str, api_id=None, api_hash=None) -> None:
    """Выход из аккаунта и аннулирование сессии на стороне Telegram."""
    if not (api_id and api_hash):
        api_id, api_hash = _credentials()

    async def _do():
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(session_string), api_id, api_hash, **client_settings())
        await client.connect()
        try:
            if await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()

    _run(_do())


def fetch_account_info(session_string: str, api_id=None, api_hash=None) -> AuthorizedAccount | None:
    """Проверяет сессию и возвращает актуальные данные пользователя (или None, если сессия недействительна)."""
    if not (api_id and api_hash):
        api_id, api_hash = _credentials()

    async def _do():
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(session_string), api_id, api_hash, **client_settings())
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return None
            me = await client.get_me()
            display = " ".join(p for p in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if p)
            return AuthorizedAccount(
                session_string=session_string,
                user_id=me.id,
                username=me.username or "",
                display_name=display.strip(),
            )
        finally:
            await client.disconnect()

    return _run(_do())
