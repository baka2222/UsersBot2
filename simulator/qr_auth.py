"""
Вход в Telegram-аккаунт по QR-коду.

Используется, когда код подтверждения не доходит (Telegram может «молча» не
доставлять его при подозрении на api_id/IP). QR-вход не зависит от доставки кода:
пользователь сканирует картинку в своём приложении Telegram — и сессия готова.

QR-логин требует держать одно живое соединение, пока код сканируют. Поэтому здесь
поднимается фоновый event loop в отдельном потоке-демоне, а состояние каждой
попытки хранится в реестре по id аккаунта. Django-вью работают синхронно и лишь
опрашивают это состояние.
"""
import asyncio
import base64
import io
import threading

from . import telegram_client

# --- Фоновый event loop -----------------------------------------------------
_loop = None
_loop_lock = threading.Lock()

# Реестр попыток: account_id -> dict(status, url, client, qr, error, result)
_state: dict[int, dict] = {}


def _get_loop():
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _submit(coro):
    return asyncio.run_coroutine_threadsafe(coro, _get_loop())


# --- Вспомогательное --------------------------------------------------------
def qr_data_uri(url: str) -> str:
    """Превращает tg://login-ссылку в data:image PNG с QR-кодом."""
    import qrcode

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def _safe_disconnect(client):
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001
        pass


def _display_name(me) -> str:
    return " ".join(
        p for p in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if p
    ).strip()


# --- Корутины, работающие в фоновом loop ------------------------------------
async def _begin(account_id: int, api_id: int, api_hash: str, seed=None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(), api_id, api_hash, **telegram_client.client_settings(seed),
    )
    await client.connect()
    qr = await client.qr_login()
    _state[account_id] = {
        "status": "waiting",
        "url": qr.url,
        "client": client,
        "qr": qr,
        "error": "",
        "result": None,
    }
    asyncio.create_task(_wait_loop(account_id))


async def _wait_loop(account_id: int):
    from telethon.errors import SessionPasswordNeededError

    st = _state.get(account_id)
    if not st:
        return
    client, qr = st["client"], st["qr"]
    deadline = asyncio.get_event_loop().time() + 300  # общий лимит 5 минут
    try:
        while asyncio.get_event_loop().time() < deadline:
            try:
                await qr.wait(timeout=25)
                await _finalize(account_id)
                return
            except asyncio.TimeoutError:
                # Токен QR живёт ~30 сек — обновляем и показываем новый
                await qr.recreate()
                st["url"] = qr.url
            except SessionPasswordNeededError:
                st["status"] = "password"  # держим клиента живым для ввода пароля
                return
        st["status"] = "timeout"
        await _safe_disconnect(client)
    except Exception as exc:  # noqa: BLE001
        st["status"] = "error"
        st["error"] = str(exc)
        await _safe_disconnect(client)


async def _finalize(account_id: int):
    from telethon.sessions import StringSession

    st = _state[account_id]
    client = st["client"]
    me = await client.get_me()
    st["result"] = {
        "session_string": StringSession.save(client.session),
        "user_id": me.id,
        "username": me.username or "",
        "display_name": _display_name(me),
    }
    st["status"] = "done"
    await _safe_disconnect(client)


async def _do_password(account_id: int, password: str):
    st = _state.get(account_id)
    if not st:
        return
    client = st["client"]
    try:
        await client.sign_in(password=password)
        await _finalize(account_id)
    except Exception as exc:  # noqa: BLE001
        st["status"] = "password"
        st["error"] = str(exc)


async def _cancel(account_id: int):
    st = _state.pop(account_id, None)
    if st and st.get("client"):
        await _safe_disconnect(st["client"])


# --- Синхронный API для Django-вью ------------------------------------------
def start(account_id: int) -> str:
    """Начинает новую QR-попытку и возвращает ссылку для QR-кода."""
    from .models import TelegramAccount

    account = TelegramAccount.objects.select_related("api_credentials").filter(pk=account_id).first()
    if account is None:
        raise telegram_client.TelegramConfigError("Аккаунт не найден.")
    # Приложение (api_id/api_hash) именно этого аккаунта: его → по умолчанию → .env
    api_id, api_hash = telegram_client.credentials_for_account(account)
    # Отпечаток устройства привязываем к телефону — тогда он совпадёт с тем,
    # что фоновый процесс использует при подключении этого же аккаунта.
    _submit(_cancel(account_id)).result(timeout=30)
    _submit(_begin(account_id, api_id, api_hash, account.phone)).result(timeout=30)
    return _state[account_id]["url"]


def status(account_id: int) -> dict:
    st = _state.get(account_id)
    if not st:
        return {"status": "none"}
    return {
        "status": st["status"],
        "url": st.get("url"),
        "error": st.get("error", ""),
        "result": st.get("result"),
    }


def submit_password(account_id: int, password: str):
    _submit(_do_password(account_id, password)).result(timeout=30)


def clear(account_id: int):
    _submit(_cancel(account_id)).result(timeout=30)
