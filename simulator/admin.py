import nested_admin
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from . import bot_control, qr_auth, telegram_client
from .admin_auth import CodeForm, PhoneForm
from .models import (
    ActivityLog,
    ApiCredentials,
    Dialog,
    DialogMessage,
    Group,
    GroupMembership,
    MessageTemplate,
    Scenario,
    ScenarioReply,
    TelegramAccount,
    validate_media_upload,
)

admin.site.site_header = "Панель управления"
admin.site.site_title = "Панель управления"
admin.site.index_title = "Разделы"


# --------------------------------------------------------------------------
#  Telegram-аккаунты + пошаговая авторизация
# --------------------------------------------------------------------------
_STATUS_COLORS = {
    TelegramAccount.Status.ACTIVE: "#28a745",
    TelegramAccount.Status.CODE_SENT: "#f0ad4e",
    TelegramAccount.Status.NEW: "#6c757d",
    TelegramAccount.Status.DISABLED: "#6c757d",
    TelegramAccount.Status.ERROR: "#dc3545",
}


@admin.register(TelegramAccount)
class TelegramAccountAdmin(admin.ModelAdmin):
    list_display = ("title", "phone", "app_display", "status_badge", "telegram_username", "is_enabled", "auth_button")
    list_filter = ("status", "is_enabled", "api_credentials")
    search_fields = ("title", "phone", "telegram_username", "display_name")
    readonly_fields = (
        "status", "telegram_user_id", "telegram_username", "display_name",
        "last_error", "created_at", "updated_at", "auth_button",
    )
    fieldsets = (
        ("Основное", {"fields": ("title", "phone", "is_enabled")}),
        ("Через какое приложение работать", {
            "fields": ("api_credentials",),
            "description": "Распределяйте аккаунты по разным «главным аккаунтам» (приложениям), "
                           "чтобы снизить нагрузку и риск блокировок. Пусто — приложение по умолчанию "
                           "или значения из .env. Выбирайте ДО подключения аккаунта.",
        }),
        ("Подключение", {"fields": ("auth_button", "status", "telegram_username", "display_name", "telegram_user_id")}),
        ("Служебное", {"classes": ("collapse",), "fields": ("last_error", "created_at", "updated_at")}),
    )
    actions = ("action_enable", "action_disable", "action_check_status", "action_logout")

    @admin.display(description="Статус")
    def status_badge(self, obj):
        color = _STATUS_COLORS.get(obj.status, "#6c757d")
        return format_html(
            '<span style="color:#fff;background:{};padding:2px 8px;border-radius:10px;font-size:12px;">{}</span>',
            color, obj.get_status_display(),
        )

    @admin.display(description="Приложение")
    def app_display(self, obj):
        if obj.api_credentials:
            return obj.api_credentials.title
        return "по умолчанию / .env"

    @admin.display(description="Подключение")
    def auth_button(self, obj):
        if not obj.pk:
            return "Сначала сохраните аккаунт"
        url = reverse("admin:simulator_telegramaccount_authorize", args=[obj.pk])
        if obj.status == TelegramAccount.Status.ACTIVE:
            label, bg = "Переподключить", "#6c757d"
        elif obj.status == TelegramAccount.Status.CODE_SENT:
            label, bg = "Ввести код", "#f0ad4e"
        else:
            label, bg = "Подключить", "#28a745"
        return format_html(
            '<a class="button" style="background:{};color:#fff;padding:4px 12px;border-radius:4px;" href="{}">{}</a>',
            bg, url, label,
        )

    # --- дополнительные URL ---
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/authorize/",
                self.admin_site.admin_view(self.authorize_view),
                name="simulator_telegramaccount_authorize",
            ),
            path(
                "<int:pk>/authorize-qr/",
                self.admin_site.admin_view(self.authorize_qr_view),
                name="simulator_telegramaccount_authorize_qr",
            ),
        ]
        return custom + urls

    def authorize_view(self, request, pk):
        account = get_object_or_404(TelegramAccount, pk=pk)

        # Сброс процесса — вернуться к вводу телефона
        if request.method == "POST" and request.POST.get("action") == "reset":
            account.status = TelegramAccount.Status.NEW
            account.auth_session = ""
            account.auth_phone_code_hash = ""
            account.save(update_fields=["status", "auth_session", "auth_phone_code_hash"])
            return redirect(request.path)

        step = "code" if account.status == TelegramAccount.Status.CODE_SENT else "phone"
        phone_form = PhoneForm(initial={"phone": account.phone})
        code_form = CodeForm()

        if request.method == "POST":
            try:
                # Приложение (api_id/api_hash) именно этого аккаунта — его → по умолчанию → .env
                api_id, api_hash = telegram_client.credentials_for_account(account)
                if step == "phone":
                    phone_form = PhoneForm(request.POST)
                    if phone_form.is_valid():
                        phone = phone_form.cleaned_data["phone"].strip()
                        session, code_hash, delivery = telegram_client.send_login_code(phone, api_id, api_hash)
                        account.phone = phone
                        account.auth_session = session
                        account.auth_phone_code_hash = code_hash
                        account.status = TelegramAccount.Status.CODE_SENT
                        account.last_error = ""
                        account.save()
                        messages.info(request, f"Код отправлен {delivery}. Введите его ниже.")
                        return redirect(request.path)
                else:  # step == "code"
                    code_form = CodeForm(request.POST)
                    if code_form.is_valid():
                        result = telegram_client.complete_login(
                            session_string=account.auth_session,
                            phone=account.phone,
                            code=code_form.cleaned_data["code"].strip(),
                            phone_code_hash=account.auth_phone_code_hash,
                            password=code_form.cleaned_data.get("password") or None,
                            api_id=api_id, api_hash=api_hash,
                        )
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
                        messages.success(request, f"Аккаунт «{account.title}» успешно подключён.")
                        return redirect(reverse("admin:simulator_telegramaccount_change", args=[account.pk]))
            except telegram_client.PasswordRequired:
                messages.warning(request, "На аккаунте включён облачный пароль (2FA). Введите его в поле ниже.")
            except telegram_client.TelegramConfigError as exc:
                messages.error(request, str(exc))
            except Exception as exc:  # noqa: BLE001 — показываем ошибку пользователю панели
                account.last_error = str(exc)
                account.save(update_fields=["last_error"])
                messages.error(request, f"Не удалось выполнить действие: {exc}")

        context = {
            **self.admin_site.each_context(request),
            "title": f"Подключение аккаунта: {account.title}",
            "account": account,
            "step": step,
            "phone_form": phone_form,
            "code_form": code_form,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/simulator/telegramaccount/authorize.html", context)

    def authorize_qr_view(self, request, pk):
        account = get_object_or_404(TelegramAccount, pk=pk)

        # Отмена/перезапуск попытки
        if request.method == "POST" and request.POST.get("action") == "restart":
            qr_auth.clear(account.pk)
            return redirect(request.path)

        # Проверка API-ключей до старта (приложение именно этого аккаунта)
        try:
            telegram_client.credentials_for_account(account)
        except telegram_client.TelegramConfigError as exc:
            messages.error(request, str(exc))
            return redirect(reverse("admin:simulator_telegramaccount_authorize", args=[account.pk]))

        state = qr_auth.status(account.pk)

        # Ввод облачного пароля (2FA), если потребовался
        if request.method == "POST" and request.POST.get("action") == "password":
            qr_auth.submit_password(account.pk, request.POST.get("password", ""))
            return redirect(request.path)

        # Первый заход — начинаем новую попытку и получаем ссылку QR
        if state["status"] == "none":
            try:
                qr_auth.start(account.pk)
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Не удалось начать QR-вход: {exc}")
                return redirect(reverse("admin:simulator_telegramaccount_authorize", args=[account.pk]))
            state = qr_auth.status(account.pk)

        # Успех — сохраняем сессию в аккаунт
        if state["status"] == "done" and state.get("result"):
            r = state["result"]
            account.session_string = r["session_string"]
            account.telegram_user_id = r["user_id"]
            account.telegram_username = r["username"]
            account.display_name = r["display_name"]
            account.status = TelegramAccount.Status.ACTIVE
            account.is_enabled = True
            account.auth_session = ""
            account.auth_phone_code_hash = ""
            account.last_error = ""
            account.save()
            qr_auth.clear(account.pk)
            messages.success(request, f"Аккаунт «{account.title}» успешно подключён по QR-коду.")
            return redirect(reverse("admin:simulator_telegramaccount_change", args=[account.pk]))

        qr_image = qr_auth.qr_data_uri(state["url"]) if state.get("url") else ""
        # Автообновление страницы, пока ждём сканирования
        auto_refresh = state["status"] in ("waiting",)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Подключение по QR: {account.title}",
            "account": account,
            "qr_state": state["status"],
            "qr_image": qr_image,
            "qr_error": state.get("error", ""),
            "auto_refresh": auto_refresh,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/simulator/telegramaccount/authorize_qr.html", context)

    # --- массовые действия ---
    @admin.action(description="Включить в работу")
    def action_enable(self, request, queryset):
        updated = queryset.update(is_enabled=True)
        self.message_user(request, f"Включено аккаунтов: {updated}.")

    @admin.action(description="Отключить от работы")
    def action_disable(self, request, queryset):
        updated = queryset.update(is_enabled=False)
        self.message_user(request, f"Отключено аккаунтов: {updated}.")

    @admin.action(description="Проверить статус подключения")
    def action_check_status(self, request, queryset):
        ok = failed = 0
        for account in queryset:
            if not account.session_string:
                continue
            try:
                api_id, api_hash = telegram_client.credentials_for_account(account)
                info = telegram_client.fetch_account_info(account.session_string, api_id, api_hash)
                if info:
                    account.telegram_user_id = info.user_id
                    account.telegram_username = info.username
                    account.display_name = info.display_name
                    account.status = TelegramAccount.Status.ACTIVE
                    account.last_error = ""
                    ok += 1
                else:
                    account.status = TelegramAccount.Status.ERROR
                    account.last_error = "Сессия недействительна, требуется повторное подключение."
                    failed += 1
                account.save()
            except Exception as exc:  # noqa: BLE001
                account.status = TelegramAccount.Status.ERROR
                account.last_error = str(exc)
                account.save(update_fields=["status", "last_error"])
                failed += 1
        self.message_user(request, f"Проверено. Активны: {ok}, с ошибкой: {failed}.")

    @admin.action(description="Выйти из аккаунта (logout)")
    def action_logout(self, request, queryset):
        count = 0
        for account in queryset:
            if account.session_string:
                try:
                    api_id, api_hash = telegram_client.credentials_for_account(account)
                    telegram_client.logout_account(account.session_string, api_id, api_hash)
                except Exception:  # noqa: BLE001 — всё равно очищаем локально
                    pass
            account.session_string = ""
            account.status = TelegramAccount.Status.DISABLED
            account.save(update_fields=["session_string", "status"])
            count += 1
        self.message_user(request, f"Выполнен выход из аккаунтов: {count}.")


# --------------------------------------------------------------------------
#  Главные аккаунты (API-приложения Telegram): несколько штук, чтобы
#  распределять по ним подключённые аккаунты и снижать риск блокировок.
# --------------------------------------------------------------------------
@admin.register(ApiCredentials)
class ApiCredentialsAdmin(admin.ModelAdmin):
    list_display = ("title", "api_id", "hash_preview", "is_default", "accounts_count")
    list_filter = ("is_default",)
    search_fields = ("title",)
    fields = ("title", "api_id", "api_hash", "is_default")

    @admin.display(description="API Hash")
    def hash_preview(self, obj):
        h = obj.api_hash or ""
        if not h:
            return "—"
        return f"{h[:4]}…{h[-4:]}" if len(h) > 8 else "задан"

    @admin.display(description="Аккаунтов")
    def accounts_count(self, obj):
        return obj.accounts.count()


# ==========================================================================
#  ЕДИНЫЙ ФЛОУ: карточка ГРУППЫ, внутри которой сразу настраиваются
#  участники, сценарии и ответы аккаунтов. Отдельно ходить никуда не нужно.
# ==========================================================================

# Подсказка про регулярные выражения — с готовым промтом для ChatGPT
REGEX_HELP = mark_safe(
    """
    <b>Как выбрать «Тип условия»:</b>
    <ul style="margin:6px 0 6px 18px;">
      <li><b>Содержит текст</b> — реагировать, если в сообщении ведущего где-то встретился указанный текст. Самый частый вариант.</li>
      <li><b>Точно совпадает</b> — сообщение должно быть в точности равно тексту-триггеру.</li>
      <li><b>Начинается с</b> — сообщение начинается с указанного текста.</li>
      <li><b>Любое сообщение</b> — реагировать на каждое сообщение ведущего (поле «Текст-триггер» можно оставить пустым).</li>
      <li><b>Регулярное выражение</b> — для сложных условий (несколько вариантов фраз сразу, формы слов, опечатки).</li>
    </ul>
    <details style="margin-top:6px;">
      <summary style="cursor:pointer;color:#2b6cb0;"><b>Не знаете, что такое регулярное выражение? Нажмите сюда</b></summary>
      <div style="background:#f1f5f9;border:1px solid #d7dee7;border-radius:6px;padding:10px 12px;margin-top:8px;">
        Регулярное выражение — это шаблон, описывающий, на какие сообщения нужно реагировать.
        Составлять его вручную не обязательно: скопируйте промт ниже, вставьте его в ChatGPT
        (или другой ИИ), опишите словами нужные фразы — и вставьте полученный результат
        в поле «Текст-триггер», выбрав тип «Регулярное выражение».
        <div style="margin-top:8px;font-family:monospace;background:#fff;border:1px dashed #b8c2cc;border-radius:6px;padding:10px;white-space:pre-wrap;">Составь регулярное выражение для Python (модуль re). Оно должно срабатывать, когда сообщение по смыслу содержит такие фразы: [ОПИШИТЕ СВОИМИ СЛОВАМИ, НА КАКИЕ СООБЩЕНИЯ РЕАГИРОВАТЬ]. Учитывай разные формы слов и возможные опечатки. В ответе верни только само выражение, без пояснений.</div>
      </div>
    </details>
    """
)

NUMBER_HELP = mark_safe(
    """
    <b>Гибкий способ (рекомендуется):</b> пишите диапазон прямо в тексте ответа
    в фигурных скобках — <code>{от-до}</code>. Пример:
    <br><code>Босс, мы получили {50000-200000}$ за {5-30} дней, рост {2-8}%</code>
    <br>Каждый такой диапазон получит своё независимое случайное число.
    Можно и дроби: <code>{1.5-3.5}</code>. Поля ниже для этого способа <u>не нужны</u>.
    <hr style="margin:8px 0;border:none;border-top:1px solid #d7dee7;">
    <b>Простой способ:</b> вставьте в текст <code>{number}</code> — оно возьмёт диапазон
    из полей «от» и «до» ниже.
    <br><b>Галочка «разделять тысячи»</b> действует на все числа этого ответа (1 250 000).
    """
)


class ScenarioReplyInline(nested_admin.NestedStackedInline):
    model = ScenarioReply
    extra = 1
    fk_name = "scenario"
    verbose_name = "ответ"
    verbose_name_plural = "Ответы аккаунтов (кто, через сколько секунд и что отправляет)"
    fieldsets = (
        (None, {"fields": (("account", "delay_seconds"),)}),
        ("Что отправить", {
            "fields": ("content_type", "text", "reaction", "media", "template"),
            "description": (
                "Текст работает как прежде. Для реакции укажите emoji; для изображения или стикера "
                "загрузите файл. У реакции можно заполнить и «Текст реплики»: аккаунт сначала поставит реакцию, "
                "а затем отправит этот текст — второй ответ создавать не нужно. Можно выбрать шаблон любого типа "
                "— при пустых полях реплики он будет использован целиком."
            ),
        }),
        ("Случайные числа в ответе", {
            "classes": ("collapse",),
            "description": NUMBER_HELP,
            "fields": (("number_min", "number_max"), "number_thousands"),
        }),
        ("Дополнительно", {
            "classes": ("collapse",),
            "fields": (("reply_to_trigger", "is_enabled", "order"),),
        }),
    )


class ScenarioInline(nested_admin.NestedStackedInline):
    model = Scenario
    extra = 0
    fk_name = "group"
    inlines = [ScenarioReplyInline]
    verbose_name = "сценарий"
    verbose_name_plural = "Сценарии — на какие сообщения реагировать"
    fieldsets = (
        (None, {"fields": (("name", "is_enabled"),)}),
        ("Когда срабатывать", {
            "description": REGEX_HELP,
            "fields": ("match_type", "trigger_text", "case_sensitive"),
        }),
        ("Дополнительно (можно не трогать)", {
            "classes": ("collapse",),
            "description": "«Приоритет» — какой сценарий проверять раньше, если подходит несколько. "
                           "«Пауза перед повтором» — сколько секунд не срабатывать этому сценарию заново.",
            "fields": (("priority", "cooldown_seconds"),),
        }),
    )


class GroupMembershipInline(nested_admin.NestedTabularInline):
    model = GroupMembership
    extra = 1
    verbose_name = "участник"
    verbose_name_plural = "Аккаунты-участники этой группы (кто будет отвечать)"


@admin.register(Group)
class GroupAdmin(nested_admin.NestedModelAdmin):
    list_display = ("title", "chat_display", "accounts_count", "scenarios_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "chat_username", "host_username")
    inlines = [GroupMembershipInline, ScenarioInline]
    save_on_top = True
    fieldsets = (
        ("1. Название", {
            "fields": ("title", "owner", "is_active"),
            "description": "Придумайте понятное название группы. «Владелец» — кто из пользователей "
                           "панели ведёт эту группу (можно не заполнять).",
        }),
        ("2. Какой чат в Telegram", {
            "fields": ("chat_username", "invite_link", "chat_id"),
            "description": "Укажите ОДИН из вариантов — остальное определится само при запуске бота:<br>"
                           "• <b>@username чата</b> — для публичной группы (без «@»);<br>"
                           "• <b>Ссылка-приглашение</b> — для закрытой группы (вида https://t.me/+...);<br>"
                           "• <b>ID чата</b> — если знаете числовой идентификатор. Обычно оставляют пустым.",
        }),
        ("3. Чьи сообщения запускают сценарии", {
            "fields": ("trigger_scope", "host_username", "host_user_id"),
            "description": "Обычно реагируют только на сообщения ведущего занятия. Укажите его "
                           "@username (без «@»). Поле «Telegram ID ведущего» заполнять не нужно — "
                           "определится автоматически.",
        }),
    )

    class Media:
        css = {"all": ()}

    @admin.display(description="Чат")
    def chat_display(self, obj):
        if obj.chat_username:
            return f"@{obj.chat_username}"
        if obj.chat_id:
            return str(obj.chat_id)
        if obj.invite_link:
            return "по ссылке"
        return "— не указан —"

    @admin.display(description="Аккаунтов")
    def accounts_count(self, obj):
        return obj.accounts.count()

    @admin.display(description="Сценариев")
    def scenarios_count(self, obj):
        return obj.scenarios.count()

    # ---- Панель запуска бота (кнопки Старт/Стоп) ----
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("bot-control/", self.admin_site.admin_view(self.bot_control_view), name="bot_control"),
            path("bot-control/start/", self.admin_site.admin_view(self.bot_control_start), name="bot_control_start"),
            path("bot-control/stop/", self.admin_site.admin_view(self.bot_control_stop), name="bot_control_stop"),
        ]
        return custom + urls

    def bot_control_start(self, request):
        bot_control.set_active(True)
        messages.success(request, "Бот включён.")
        return redirect("admin:bot_control")

    def bot_control_stop(self, request):
        bot_control.set_active(False)
        messages.success(request, "Бот выключен.")
        return redirect("admin:bot_control")

    def bot_control_view(self, request):
        state = bot_control.status()
        context = {
            **self.admin_site.each_context(request),
            "title": "Запуск бота",
            "is_active": state["is_active"],
            "alive": state["alive"],
            "running": state["running"],
            "heartbeat": state["heartbeat"],
            "log_text": bot_control.tail_log(60),
            "auto_refresh": True,
        }
        return TemplateResponse(request, "admin/simulator/bot_control.html", context)


# --------------------------------------------------------------------------
#  Шаблоны сообщений
# --------------------------------------------------------------------------
@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "content_type", "content_preview")
    list_filter = ("category",)
    search_fields = ("title", "text", "reaction", "category")
    fieldsets = (
        (None, {"fields": ("title", "category", "content_type")} ),
        ("Содержимое", {
            "fields": ("text", "reaction", "media"),
            "description": (
                "Для текста заполните текст. Для реакции укажите emoji. Для изображения или стикера загрузите файл; "
                "текст у изображения может быть подписью."
            ),
        }),
    )

    @admin.display(description="Содержимое")
    def content_preview(self, obj):
        if obj.content_type == MessageTemplate.ContentType.REACTION:
            return obj.reaction or "—"
        if obj.content_type in (MessageTemplate.ContentType.IMAGE, MessageTemplate.ContentType.STICKER):
            return obj.media.name.rsplit("/", 1)[-1] if obj.media else "—"
        return (obj.text or "")[:80]


# --------------------------------------------------------------------------
#  Журнал работы (только просмотр)
# --------------------------------------------------------------------------
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status_badge", "group", "account", "scenario", "sent_preview", "sent_at")
    list_filter = ("status", "group", "account", "scenario")
    search_fields = ("trigger_text", "sent_text", "trigger_sender")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Статус")
    def status_badge(self, obj):
        colors = {
            ActivityLog.Status.SENT: "#28a745",
            ActivityLog.Status.SCHEDULED: "#f0ad4e",
            ActivityLog.Status.FAILED: "#dc3545",
        }
        return format_html(
            '<span style="color:#fff;background:{};padding:2px 8px;border-radius:10px;font-size:12px;">{}</span>',
            colors.get(obj.status, "#6c757d"), obj.get_status_display(),
        )

    @admin.display(description="Отправлено")
    def sent_preview(self, obj):
        return (obj.sent_text or "")[:60]


# --------------------------------------------------------------------------
#  Сообщения (инбокс): личные переписки и группы + ответы из панели
# --------------------------------------------------------------------------
def _repliers_for_group(group):
    """Аккаунты, которые могут отвечать в этой группе (участники, готовые к работе)."""
    if group is None:
        return []
    memberships = (
        GroupMembership.objects
        .filter(group=group, is_active=True)
        .select_related("account")
        .order_by("account__title")
    )
    result = []
    for m in memberships:
        acc = m.account
        if acc.is_enabled and acc.status == TelegramAccount.Status.ACTIVE and acc.session_string:
            result.append(acc)
    return result


@admin.register(Dialog)
class DialogAdmin(admin.ModelAdmin):
    list_display = ("kind_badge", "who", "context_display", "unread_badge", "last_preview", "last_message_at", "open_button")
    list_filter = ("kind",)
    search_fields = ("title", "username")
    list_display_links = None
    ordering = ("-last_message_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Список показываем, отдельную «форму редактирования» не используем —
        # общение идёт через кнопку «Открыть» (чат-страница).
        return obj is None

    @admin.display(description="Тип")
    def kind_badge(self, obj):
        color = "#2b6cb0" if obj.kind == Dialog.Kind.GROUP else "#6f42c1"
        return format_html(
            '<span style="color:#fff;background:{};padding:2px 8px;border-radius:10px;font-size:12px;">{}</span>',
            color, obj.get_kind_display(),
        )

    @admin.display(description="Кто/что")
    def who(self, obj):
        return obj.peer_label

    @admin.display(description="Наш аккаунт / группа")
    def context_display(self, obj):
        if obj.kind == Dialog.Kind.GROUP:
            return obj.group.title if obj.group else "—"
        return obj.account.title if obj.account else "—"

    @admin.display(description="Непрочитано")
    def unread_badge(self, obj):
        if not obj.unread:
            return "—"
        return format_html(
            '<span style="color:#fff;background:#dc3545;padding:2px 8px;border-radius:10px;font-size:12px;">{}</span>',
            obj.unread,
        )

    @admin.display(description="Последнее сообщение")
    def last_preview(self, obj):
        prefix = "Вы: " if obj.last_outgoing else ""
        return (prefix + (obj.last_text or ""))[:70]

    @admin.display(description="")
    def open_button(self, obj):
        url = reverse("admin:simulator_dialog_chat", args=[obj.pk])
        return format_html(
            '<a class="button" style="background:#28a745;color:#fff;padding:4px 14px;'
            'border-radius:4px;" href="{}">Открыть</a>', url,
        )

    # --- чат-страница диалога ---
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:pk>/chat/",
                self.admin_site.admin_view(self.chat_view),
                name="simulator_dialog_chat",
            ),
        ]
        return custom + urls

    def chat_view(self, request, pk):
        dialog = get_object_or_404(Dialog, pk=pk)

        if request.method == "POST":
            return self._handle_reply(request, dialog)

        # Открыли диалог — считаем прочитанным
        if dialog.unread:
            Dialog.objects.filter(pk=dialog.pk).update(unread=0)

        repliers = _repliers_for_group(dialog.group) if dialog.kind == Dialog.Kind.GROUP else []
        can_reply, reply_hint = self._reply_readiness(dialog, repliers)
        bot_running = bot_control.status()["running"]

        context = {
            **self.admin_site.each_context(request),
            "title": f"Диалог: {dialog.peer_label}",
            "dialog": dialog,
            "chat_messages": dialog.messages.all(),
            "is_group": dialog.kind == Dialog.Kind.GROUP,
            "repliers": repliers,
            "reaction_targets": dialog.messages.filter(outgoing=False, tg_id__isnull=False).order_by("-date", "-id")[:100],
            "can_reply": can_reply,
            "reply_hint": reply_hint,
            "bot_running": bot_running,
            "opts": self.model._meta,
            "auto_refresh": True,
        }
        return TemplateResponse(request, "admin/simulator/dialog/chat.html", context)

    def _reply_readiness(self, dialog, repliers):
        """Можно ли отвечать в этом диалоге и подсказка, если нет."""
        if dialog.kind == Dialog.Kind.GROUP:
            if not repliers:
                return False, ("В этой группе нет готового к работе аккаунта-участника. "
                               "Добавьте активный подключённый аккаунт в состав группы.")
            return True, ""
        acc = dialog.account
        if acc is None:
            return False, "У диалога не задан аккаунт."
        if not (acc.is_enabled and acc.status == TelegramAccount.Status.ACTIVE and acc.session_string):
            return False, f"Аккаунт «{acc.title}» сейчас не подключён — ответить нельзя."
        return True, ""

    def _handle_reply(self, request, dialog):
        chat_url = reverse("admin:simulator_dialog_chat", args=[dialog.pk])
        content_type = request.POST.get("content_type") or DialogMessage.ContentType.TEXT
        allowed_content_types = set(DialogMessage.ContentType.values)
        if content_type not in allowed_content_types:
            messages.error(request, "Неизвестный тип ответа.")
            return redirect(chat_url)
        text = (request.POST.get("text") or "").strip()
        reaction = (request.POST.get("reaction") or "").strip()
        media = request.FILES.get("media")
        reaction_to_tg_id = None
        if content_type == DialogMessage.ContentType.TEXT and not text:
            messages.warning(request, "Введите текст ответа.")
            return redirect(chat_url)
        if content_type == DialogMessage.ContentType.REACTION:
            if not reaction:
                messages.warning(request, "Укажите emoji реакции.")
                return redirect(chat_url)
            try:
                reaction_to_tg_id = int(request.POST.get("reaction_to") or 0)
            except (TypeError, ValueError):
                reaction_to_tg_id = None
            if not reaction_to_tg_id or not dialog.messages.filter(
                outgoing=False, tg_id=reaction_to_tg_id,
            ).exists():
                messages.warning(request, "Выберите входящее сообщение, на которое поставить реакцию.")
                return redirect(chat_url)
        if content_type in (DialogMessage.ContentType.IMAGE, DialogMessage.ContentType.STICKER) and not media:
            messages.warning(request, "Загрузите изображение или стикер.")
            return redirect(chat_url)
        if media:
            try:
                validate_media_upload(media, content_type)
            except Exception as exc:  # ValidationError is safely shown to the operator.
                messages.warning(request, f"Файл не принят: {exc}")
                return redirect(chat_url)

        # Определяем, от какого аккаунта отправлять
        if dialog.kind == Dialog.Kind.GROUP:
            repliers = _repliers_for_group(dialog.group)
            allowed = {a.id: a for a in repliers}
            try:
                account = allowed[int(request.POST.get("account") or 0)]
            except (KeyError, ValueError):
                account = repliers[0] if repliers else None
            if account is None:
                messages.error(request, "Нет подходящего аккаунта для ответа в этой группе.")
                return redirect(chat_url)
        else:
            account = dialog.account
            ok, hint = self._reply_readiness(dialog, [])
            if not ok:
                messages.error(request, hint)
                return redirect(chat_url)

        now = timezone.now()
        DialogMessage.objects.create(
            dialog=dialog,
            outgoing=True,
            via_panel=True,
            account=account,
            sender_name=account.title,
            text=text,
            content_type=content_type,
            reaction=reaction,
            media=media,
            reaction_to_tg_id=reaction_to_tg_id,
            date=now,
            status=DialogMessage.Status.PENDING,
        )
        Dialog.objects.filter(pk=dialog.pk).update(
            last_message_at=now, last_text=self._preview_outgoing(content_type, text, reaction), last_outgoing=True,
        )
        if bot_control.status()["running"]:
            messages.success(request, "Ответ поставлен в очередь и будет отправлен через несколько секунд.")
        else:
            messages.warning(
                request,
                "Ответ сохранён, но бот сейчас выключен — он отправится, как только вы запустите бота.",
            )
        return redirect(chat_url)

    @staticmethod
    def _preview_outgoing(content_type, text, reaction):
        if content_type == DialogMessage.ContentType.REACTION:
            return f"Реакция {reaction}"
        if content_type == DialogMessage.ContentType.IMAGE:
            return text or "[изображение]"
        if content_type == DialogMessage.ContentType.STICKER:
            return "[стикер]"
        return text[:500]
