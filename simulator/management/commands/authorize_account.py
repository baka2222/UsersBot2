"""
Авторизация Telegram-аккаунта из командной строки (запасной способ,
если удобнее делать это в терминале, а не через веб-панель).

Пример:
    python manage.py authorize_account --id 1
    python manage.py authorize_account --phone +79991234567 --title "Аккаунт №1"
"""
from django.core.management.base import BaseCommand, CommandError

from simulator import telegram_client
from simulator.models import TelegramAccount


class Command(BaseCommand):
    help = "Интерактивно подключает Telegram-аккаунт (запрашивает код в терминале)."

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, help="ID существующего аккаунта в панели.")
        parser.add_argument("--phone", type=str, help="Номер телефона (если аккаунта ещё нет).")
        parser.add_argument("--title", type=str, help="Название для нового аккаунта.")

    def handle(self, *args, **options):
        account = self._get_or_create_account(options)

        phone = account.phone
        if not phone:
            phone = input("Номер телефона (например +79991234567): ").strip()
            account.phone = phone

        # Приложение (api_id/api_hash) этого аккаунта: его → по умолчанию → .env
        try:
            api_id, api_hash = telegram_client.credentials_for_account(account)
        except telegram_client.TelegramConfigError as exc:
            raise CommandError(str(exc))

        self.stdout.write("Запрашиваю код подтверждения…")
        try:
            session, code_hash, delivery = telegram_client.send_login_code(phone, api_id, api_hash)
        except telegram_client.TelegramConfigError as exc:
            raise CommandError(str(exc))

        self.stdout.write(f"Код отправлен {delivery}.")
        code = input("Введите код из Telegram: ").strip()
        password = None
        try:
            result = telegram_client.complete_login(session, phone, code, code_hash,
                                                    api_id=api_id, api_hash=api_hash)
        except telegram_client.PasswordRequired:
            password = input("Включена 2FA. Введите облачный пароль: ").strip()
            result = telegram_client.complete_login(session, phone, code, code_hash, password=password,
                                                    api_id=api_id, api_hash=api_hash)

        account.session_string = result.session_string
        account.telegram_user_id = result.user_id
        account.telegram_username = result.username
        account.display_name = result.display_name
        account.status = TelegramAccount.Status.ACTIVE
        account.is_enabled = True
        account.auth_session = ""
        account.auth_phone_code_hash = ""
        account.last_error = ""
        account.save()

        self.stdout.write(self.style.SUCCESS(
            f"Готово! Аккаунт «{account.title}» подключён (@{result.username or result.user_id})."
        ))

    def _get_or_create_account(self, options):
        if options.get("id"):
            try:
                return TelegramAccount.objects.get(pk=options["id"])
            except TelegramAccount.DoesNotExist:
                raise CommandError(f"Аккаунт с ID {options['id']} не найден.")

        phone = options.get("phone")
        title = options.get("title") or (phone and f"Аккаунт {phone}") or "Новый аккаунт"
        if phone:
            account, _ = TelegramAccount.objects.get_or_create(
                phone=phone, defaults={"title": title},
            )
            return account
        return TelegramAccount.objects.create(title=title)
