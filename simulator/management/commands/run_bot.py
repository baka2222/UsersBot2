"""Запуск фонового процесса симуляции.

Обычно запускается автоматически (контейнер `bot` в Docker). Локально можно
запустить вручную: `python manage.py run_bot`. Включение/выключение отправки —
кнопкой в панели (раздел «Запуск бота»).
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler

from django.conf import settings
from django.core.management.base import BaseCommand

from simulator.worker import run_worker


class Command(BaseCommand):
    help = "Фоновый процесс: слушает группы и отправляет реплики по сценариям."

    def handle(self, *args, **options):
        settings.BOT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Пишем лог в файл (панель его показывает; в Docker — общий том) и в консоль
        file_handler = RotatingFileHandler(
            settings.BOT_LOG_FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8",
        )
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
            handlers=[logging.StreamHandler(), file_handler],
            force=True,
        )
        # Логи simulator.* тоже должны попадать в файл: направляем их в корневые обработчики
        sim_logger = logging.getLogger("simulator")
        sim_logger.handlers.clear()
        sim_logger.propagate = True
        sim_logger.setLevel(logging.INFO)
        # Приглушаем «болтовню» Telethon, оставляя предупреждения и ошибки
        logging.getLogger("telethon").setLevel(logging.WARNING)

        self.stdout.write(self.style.SUCCESS("Фоновый процесс запущен. (Ctrl+C для остановки)"))
        try:
            asyncio.run(run_worker())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nОстановлено."))
