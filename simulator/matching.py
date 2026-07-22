"""Логика проверки: подходит ли сообщение под условие сценария."""
import random
import re

from .models import Scenario


# Диапазон прямо в тексте: {50000-200000}, {1.5-3.5}, {10..20}, {-5..5}
_RANGE_RE = re.compile(
    r"\{\s*(-?\d+(?:\.\d+)?)\s*(?:\.\.|-)\s*(-?\d+(?:\.\d+)?)\s*\}"
)


def _format_number(value, decimals: int, thousands: bool) -> str:
    if decimals > 0:
        s = f"{value:,.{decimals}f}" if thousands else f"{value:.{decimals}f}"
    else:
        s = f"{int(value):,d}" if thousands else str(int(value))
    return s.replace(",", " ") if thousands else s


def _random_in_range(a_str: str, b_str: str) -> str:
    """Случайное число из диапазона, заданного двумя строками. Понимает дроби."""
    a, b = float(a_str), float(b_str)
    low, high = (a, b) if a <= b else (b, a)
    is_float = ("." in a_str) or ("." in b_str)
    if is_float:
        decimals = max(
            len(a_str.split(".")[1]) if "." in a_str else 0,
            len(b_str.split(".")[1]) if "." in b_str else 0,
        )
        return round(random.uniform(low, high), decimals), decimals
    return random.randint(int(low), int(high)), 0


def substitute_number(text: str, number_min=None, number_max=None, thousands: bool = False) -> str:
    """Подставляет случайные числа в текст.

    Поддерживает два способа:
      1) диапазон прямо в тексте — {50000-200000}, {1.5-3.5}, {10..20};
         каждый такой фрагмент получает своё независимое случайное число;
      2) {number} — берёт диапазон из полей «Число: от / до».
    Если включена галочка «разделять тысячи» — форматирует все числа с пробелами.
    """
    if not text:
        return text

    def _replace_inline(match):
        value, decimals = _random_in_range(match.group(1), match.group(2))
        return _format_number(value, decimals, thousands)

    text = _RANGE_RE.sub(_replace_inline, text)

    if "{number}" in text and number_min is not None and number_max is not None:
        value, decimals = _random_in_range(str(number_min), str(number_max))
        text = text.replace("{number}", _format_number(value, decimals, thousands))

    return text


def message_matches(scenario: Scenario, text: str) -> bool:
    """Возвращает True, если сообщение `text` удовлетворяет условию сценария."""
    match_type = scenario.match_type

    if match_type == Scenario.MatchType.ANY:
        return True

    trigger = scenario.trigger_text or ""
    message = text or ""

    if not scenario.case_sensitive and match_type != Scenario.MatchType.REGEX:
        trigger = trigger.lower()
        message = message.lower()

    if match_type == Scenario.MatchType.CONTAINS:
        return trigger in message
    if match_type == Scenario.MatchType.EQUALS:
        return message.strip() == trigger.strip()
    if match_type == Scenario.MatchType.STARTS_WITH:
        return message.lstrip().startswith(trigger.strip())
    if match_type == Scenario.MatchType.REGEX:
        flags = 0 if scenario.case_sensitive else re.IGNORECASE
        try:
            return re.search(scenario.trigger_text, text or "", flags) is not None
        except re.error:
            return False
    return False


def normalize_chat_id(raw) -> int | None:
    """Приводит идентификатор чата к числовому виду Telethon (супергруппы: -100...)."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value
