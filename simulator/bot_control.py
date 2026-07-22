"""
Управление ботом из панели.

Кнопка «Запустить/Остановить» переключает флаг в базе (`BotState.is_active`),
а сам фоновый процесс (контейнер `bot` или `python manage.py run_bot`) читает
этот флаг и решает, отправлять сообщения или нет. Процесс также обновляет
«heartbeat», по которому панель понимает, что он жив.

Такой подход работает одинаково и когда бот запущен отдельным контейнером,
и когда локально в терминале.
"""
from django.conf import settings
from django.utils import timezone

from .models import BotState

# Насколько свежим должен быть heartbeat, чтобы считать процесс живым
ALIVE_TIMEOUT = 30  # секунд


def _is_alive(state: BotState) -> bool:
    if not state.heartbeat:
        return False
    return (timezone.now() - state.heartbeat).total_seconds() < ALIVE_TIMEOUT


def set_active(active: bool):
    state = BotState.load()
    state.is_active = active
    state.save(update_fields=["is_active"])


def status() -> dict:
    state = BotState.load()
    alive = _is_alive(state)
    return {
        "is_active": state.is_active,
        "alive": alive,
        "heartbeat": state.heartbeat,
        # Итоговое состояние для панели
        "running": state.is_active and alive,
    }


def tail_log(lines: int = 60) -> str:
    """Последние строки лога фонового процесса."""
    try:
        data = settings.BOT_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "Лог пока пуст."
    return "\n".join(data.splitlines()[-lines:])
