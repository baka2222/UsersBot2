"""Создаёт суперпользователя из переменных окружения, если его ещё нет.

Используется при старте контейнера, чтобы в панель можно было войти сразу.
Читает DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD / DJANGO_SUPERUSER_EMAIL.
Безопасно запускать многократно.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Создаёт суперпользователя из переменных окружения, если он ещё не создан."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.getenv("DJANGO_SUPERUSER_USERNAME")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "")

        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_* не заданы — пропускаю создание админа.")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Суперпользователь «{username}» уже существует.")
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Создан суперпользователь «{username}»."))
