# Единый образ для веб-панели (gunicorn) и фонового процесса (run_bot)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Каталоги для статики и рантайм-данных (сюда монтируются тома) + непривилегированный пользователь
RUN mkdir -p /app/staticfiles /app/data \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Значение по умолчанию — веб-сервер. Контейнер бота переопределяет команду в compose.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
