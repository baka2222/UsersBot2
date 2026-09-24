"""
Модели данных системы симуляции активности.

Терминология намеренно нейтральная и универсальная:
  • Группа        — учебная/рабочая площадка в Telegram, где идёт общение.
  • Ведущий       — участник, чьи сообщения служат триггером сценариев.
  • Аккаунт       — подключённый Telegram-аккаунт, отвечающий по сценарию.
  • Сценарий      — правило: на какое сообщение и как реагировать.
  • Реплика       — одно запланированное сообщение внутри сценария.
  • Шаблон        — переиспользуемый текст сообщения.
  • Журнал        — история срабатываний и отправок.
"""
from django.db import models
from django.db.models import Q
from django.conf import settings
from pathlib import Path


MEDIA_MAX_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
STICKER_EXTENSIONS = {".webp", ".tgs", ".webm"}


def validate_media_upload(uploaded_file, content_type: str) -> None:
    """Проверка общая для шаблонов, сценариев и отправки из панели."""
    from django.core.exceptions import ValidationError

    if not uploaded_file:
        return
    suffix = Path(uploaded_file.name).suffix.lower()
    allowed = IMAGE_EXTENSIONS if content_type == "image" else STICKER_EXTENSIONS
    if suffix not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValidationError(f"Недопустимый формат файла. Разрешены: {allowed_text}.")
    if getattr(uploaded_file, "size", 0) > MEDIA_MAX_BYTES:
        raise ValidationError("Размер файла не должен превышать 10 МБ.")


class TimeStamped(models.Model):
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True


class TelegramAccount(TimeStamped):
    """Подключённый Telegram-аккаунт, от имени которого отправляются сообщения."""

    class Status(models.TextChoices):
        NEW = "new", "Новый (не авторизован)"
        CODE_SENT = "code_sent", "Ожидает код подтверждения"
        ACTIVE = "active", "Активен"
        DISABLED = "disabled", "Отключён"
        ERROR = "error", "Ошибка"

    title = models.CharField(
        "Название", max_length=120,
        help_text="Понятное имя аккаунта для панели, например «Аккаунт №1».",
    )
    phone = models.CharField(
        "Номер телефона", max_length=32, blank=True,
        help_text="В международном формате, например +79991234567.",
    )
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.NEW,
    )
    is_enabled = models.BooleanField(
        "Использовать в работе", default=True,
        help_text="Если выключено — аккаунт не подключается и не отвечает.",
    )
    api_credentials = models.ForeignKey(
        "ApiCredentials", verbose_name="Главный аккаунт (приложение)",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="accounts",
        help_text="Через какое API-приложение работает этот аккаунт. Распределяйте "
                  "аккаунты по разным приложениям, чтобы снизить риск блокировок. "
                  "Пусто — приложение по умолчанию или значения из .env. "
                  "Выбирайте ДО подключения: смена приложения у уже подключённого "
                  "аккаунта требует повторной авторизации.",
    )

    # Заполняется автоматически после успешной авторизации
    session_string = models.TextField("Строка сессии", blank=True, editable=False)
    telegram_user_id = models.BigIntegerField("Telegram ID", null=True, blank=True, editable=False)
    telegram_username = models.CharField("Username", max_length=64, blank=True, editable=False)
    display_name = models.CharField("Имя в Telegram", max_length=200, blank=True, editable=False)

    # Служебные поля процесса авторизации (не для ручного редактирования)
    auth_session = models.TextField(blank=True, editable=False)
    auth_phone_code_hash = models.CharField(max_length=128, blank=True, editable=False)

    last_error = models.TextField("Последняя ошибка", blank=True, editable=False)

    class Meta:
        verbose_name = "Telegram-аккаунт"
        verbose_name_plural = "Telegram-аккаунты"
        ordering = ["title"]

    def __str__(self):
        return self.title

    @property
    def is_authorized(self) -> bool:
        return bool(self.session_string)


class Group(TimeStamped):
    """Учебная/рабочая группа в Telegram."""

    class TriggerScope(models.TextChoices):
        HOST_ONLY = "host", "Только сообщения ведущего"
        ANYONE = "anyone", "Сообщения любого участника"

    title = models.CharField("Название группы", max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Владелец",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_groups",
        help_text="Пользователь панели, который управляет этой группой.",
    )

    # Идентификация чата в Telegram. Можно указать любой из вариантов —
    # числовой ID, @username или ссылку-приглашение; недостающее определится автоматически.
    chat_id = models.BigIntegerField(
        "ID чата", null=True, blank=True,
        help_text="Числовой идентификатор чата. Заполнится сам, если указан @username или ссылка.",
    )
    chat_username = models.CharField(
        "@username чата", max_length=64, blank=True,
        help_text="Для публичных групп, без символа @ (например: my_group).",
    )
    invite_link = models.CharField(
        "Ссылка-приглашение", max_length=255, blank=True,
        help_text="Ссылка вида https://t.me/+... для приватных групп.",
    )

    trigger_scope = models.CharField(
        "Реагировать на сообщения", max_length=16,
        choices=TriggerScope.choices, default=TriggerScope.HOST_ONLY,
    )
    host_username = models.CharField(
        "Username ведущего", max_length=64, blank=True,
        help_text="Чьи сообщения запускают сценарии (без @). Если пусто — определяется по ID.",
    )
    host_user_id = models.BigIntegerField(
        "Telegram ID ведущего", null=True, blank=True,
        help_text="Можно указать вместо username для точного совпадения.",
    )

    is_active = models.BooleanField(
        "Группа активна", default=True,
        help_text="Если выключено — сценарии этой группы не срабатывают.",
    )

    accounts = models.ManyToManyField(
        TelegramAccount, verbose_name="Аккаунты группы",
        through="GroupMembership", related_name="groups", blank=True,
    )

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"
        ordering = ["title"]

    def __str__(self):
        return self.title


class GroupMembership(TimeStamped):
    """Связь «аккаунт участвует в группе». Один аккаунт может быть в нескольких группах."""

    group = models.ForeignKey(Group, verbose_name="Группа", on_delete=models.CASCADE)
    account = models.ForeignKey(TelegramAccount, verbose_name="Аккаунт", on_delete=models.CASCADE)
    is_active = models.BooleanField("Активен в группе", default=True)

    class Meta:
        verbose_name = "Аккаунт в группе"
        verbose_name_plural = "Аккаунты в группе"
        unique_together = ("group", "account")

    def __str__(self):
        return f"{self.account} → {self.group}"


class MessageTemplate(TimeStamped):
    """Библиотека переиспользуемых ответов для сценариев."""

    class ContentType(models.TextChoices):
        TEXT = "text", "Текст"
        REACTION = "reaction", "Реакция"
        IMAGE = "image", "Изображение"
        STICKER = "sticker", "Стикер"

    title = models.CharField("Название шаблона", max_length=200)
    category = models.CharField(
        "Категория", max_length=100, blank=True,
        help_text="Необязательная группировка, например «Маркетинг».",
    )
    content_type = models.CharField(
        "Тип ответа", max_length=12, choices=ContentType.choices,
        default=ContentType.TEXT,
    )
    text = models.TextField("Текст сообщения / подпись", blank=True)
    reaction = models.CharField(
        "Реакция", max_length=32, blank=True,
        help_text="Emoji, например 👍, ❤️ или 🔥. Реакция ставится на сообщение-триггер.",
    )
    media = models.FileField(
        "Изображение или стикер", upload_to="template_media/%Y/%m/%d", blank=True,
        help_text="Для изображения загрузите JPG, PNG, WEBP или GIF. Для стикера — WEBP, TGS или WEBM.",
    )

    class Meta:
        verbose_name = "Шаблон сообщения"
        verbose_name_plural = "Шаблоны сообщений"
        ordering = ["category", "title"]

    def __str__(self):
        return self.title

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.content_type == self.ContentType.TEXT and not self.text.strip():
            errors["text"] = "Для текстового шаблона укажите текст."
        elif self.content_type == self.ContentType.REACTION and not self.reaction.strip():
            errors["reaction"] = "Для шаблона-реакции укажите emoji."
        elif self.content_type in (self.ContentType.IMAGE, self.ContentType.STICKER) and not self.media:
            errors["media"] = "Для изображения или стикера загрузите файл."
        elif self.content_type in (self.ContentType.IMAGE, self.ContentType.STICKER):
            try:
                validate_media_upload(self.media, self.content_type)
            except ValidationError as exc:
                errors["media"] = exc
        if errors:
            raise ValidationError(errors)


class Scenario(TimeStamped):
    """Сценарий: условие срабатывания и набор запланированных реплик."""

    class MatchType(models.TextChoices):
        CONTAINS = "contains", "Содержит текст"
        EQUALS = "equals", "Точно совпадает"
        STARTS_WITH = "starts", "Начинается с"
        REGEX = "regex", "Регулярное выражение"
        ANY = "any", "Любое сообщение"

    group = models.ForeignKey(
        Group, verbose_name="Группа", on_delete=models.CASCADE, related_name="scenarios",
    )
    name = models.CharField("Название сценария", max_length=200)

    match_type = models.CharField(
        "Тип условия", max_length=16, choices=MatchType.choices, default=MatchType.CONTAINS,
    )
    trigger_text = models.CharField(
        "Текст-триггер", max_length=500, blank=True,
        help_text="На какое сообщение реагировать. Для «Любое сообщение» можно оставить пустым.",
    )
    case_sensitive = models.BooleanField("Учитывать регистр", default=False)

    is_enabled = models.BooleanField(
        "Сценарий включён", default=True,
        help_text="Быстрое включение/отключение без удаления.",
    )
    cooldown_seconds = models.PositiveIntegerField(
        "Пауза перед повтором, сек", default=0,
        help_text="Минимум секунд между повторными срабатываниями одного сценария (0 — без ограничения).",
    )
    priority = models.IntegerField(
        "Приоритет", default=0,
        help_text="Чем больше число, тем раньше проверяется сценарий.",
    )

    last_triggered_at = models.DateTimeField("Последнее срабатывание", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Сценарий"
        verbose_name_plural = "Сценарии"
        ordering = ["-priority", "name"]

    def __str__(self):
        return self.name


class ScenarioReply(TimeStamped):
    """Одна запланированная реплика внутри сценария."""

    scenario = models.ForeignKey(
        Scenario, verbose_name="Сценарий", on_delete=models.CASCADE, related_name="replies",
    )
    account = models.ForeignKey(
        TelegramAccount, verbose_name="Отвечающий аккаунт", on_delete=models.PROTECT,
        related_name="replies",
    )
    delay_seconds = models.PositiveIntegerField(
        "Задержка, сек", default=15,
        help_text="Через сколько секунд после сообщения-триггера отправить эту реплику.",
    )

    template = models.ForeignKey(
        MessageTemplate, verbose_name="Готовый шаблон (необязательно)", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="replies",
        help_text="Можно подставить текст из библиотеки шаблонов вместо ручного ввода. "
                  "Если поле «Текст реплики» заполнено — используется оно, а не шаблон.",
    )
    content_type = models.CharField(
        "Тип ответа", max_length=12, choices=MessageTemplate.ContentType.choices,
        default=MessageTemplate.ContentType.TEXT,
        help_text="Для текста оставьте «Текст». Для реакции, изображения или стикера заполните соответствующее поле ниже.",
    )
    text = models.TextField(
        "Текст реплики", blank=True,
        help_text="Что именно напишет аккаунт. Можно подставлять случайные числа: "
                  "напишите диапазон прямо в тексте в фигурных скобках — {от-до}. "
                  "Пример: «Босс, мы получили {50000-200000}$ за {5-30} дней». "
                  "Таких диапазонов может быть сколько угодно, у каждого своё число.",
    )
    reaction = models.CharField(
        "Реакция", max_length=32, blank=True,
        help_text="Emoji для ответа-реакции на сообщение-триггер.",
    )
    media = models.FileField(
        "Изображение или стикер", upload_to="scenario_media/%Y/%m/%d", blank=True,
        help_text="Для изображения: JPG, PNG, WEBP или GIF. Для стикера: WEBP, TGS или WEBM.",
    )

    # Случайное число вместо {number} — чтобы одинаковые фразы выглядели живее
    number_min = models.IntegerField(
        "Число: от", null=True, blank=True,
        help_text="Нижняя граница случайного числа для {number}. Оставьте пустым, если {number} не используете.",
    )
    number_max = models.IntegerField(
        "Число: до", null=True, blank=True,
        help_text="Верхняя граница случайного числа для {number}.",
    )
    number_thousands = models.BooleanField(
        "Разделять тысячи пробелами", default=False,
        help_text="Показывать число как «1 250 000» вместо «1250000».",
    )

    reply_to_trigger = models.BooleanField(
        "Ответить именно на сообщение ведущего", default=False,
        help_text="Если включено — реплика будет оформлена как ответ (со стрелочкой) "
                  "на сообщение-триггер. Если выключено — просто новое сообщение в чат.",
    )
    is_enabled = models.BooleanField(
        "Реплика включена", default=True,
        help_text="Снимите галочку, чтобы временно отключить эту реплику, не удаляя её.",
    )
    order = models.PositiveIntegerField(
        "Порядок", default=0,
        help_text="Порядок показа в списке (на отправку не влияет — там важна задержка).",
    )

    class Meta:
        verbose_name = "Реплика сценария"
        verbose_name_plural = "Реплики сценария"
        ordering = ["order", "delay_seconds", "id"]

    def __str__(self):
        return f"{self.account} через {self.delay_seconds} с"

    @property
    def resolved_text(self) -> str:
        """Итоговый текст: своё поле имеет приоритет, иначе текст шаблона."""
        if self.text.strip():
            return self.text
        if self.template:
            return self.template.text
        return ""

    @property
    def resolved_content_type(self) -> str:
        """Явно заданный тип имеет приоритет; текстовый ответ может брать тип из шаблона."""
        if self.content_type != MessageTemplate.ContentType.TEXT:
            return self.content_type
        # Сохраняем старое правило: вручную введённый текст важнее шаблона.
        if self.text.strip():
            return MessageTemplate.ContentType.TEXT
        if self.template:
            return self.template.content_type
        return MessageTemplate.ContentType.TEXT

    @property
    def resolved_reaction(self) -> str:
        if self.reaction.strip():
            return self.reaction.strip()
        return self.template.reaction.strip() if self.template else ""

    @property
    def resolved_media(self):
        if self.media:
            return self.media
        return self.template.media if self.template else None

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        content_type = self.resolved_content_type
        if content_type == MessageTemplate.ContentType.TEXT and not self.resolved_text.strip():
            errors["text"] = "Укажите текст реплики или выберите текстовый шаблон."
        elif content_type == MessageTemplate.ContentType.REACTION and not self.resolved_reaction:
            errors["reaction"] = "Укажите реакцию или выберите шаблон-реакцию."
        elif content_type in (MessageTemplate.ContentType.IMAGE, MessageTemplate.ContentType.STICKER) and not self.resolved_media:
            errors["media"] = "Загрузите файл или выберите шаблон с файлом."
        elif content_type in (MessageTemplate.ContentType.IMAGE, MessageTemplate.ContentType.STICKER):
            try:
                validate_media_upload(self.resolved_media, content_type)
            except ValidationError as exc:
                errors["media"] = exc
        if errors:
            raise ValidationError(errors)

    def render_text(self) -> str:
        """Готовый текст к отправке: подставляет случайное число вместо {number}."""
        from .matching import substitute_number

        return substitute_number(
            self.resolved_text, self.number_min, self.number_max, self.number_thousands,
        )


class ActivityLog(TimeStamped):
    """Журнал: что произошло — от срабатывания до отправки реплики."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Запланировано"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"

    group = models.ForeignKey(
        Group, verbose_name="Группа", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs",
    )
    scenario = models.ForeignKey(
        Scenario, verbose_name="Сценарий", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs",
    )
    reply = models.ForeignKey(
        ScenarioReply, verbose_name="Реплика", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs",
    )
    account = models.ForeignKey(
        TelegramAccount, verbose_name="Аккаунт", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs",
    )

    trigger_text = models.TextField("Сообщение-триггер", blank=True)
    trigger_sender = models.CharField("Автор триггера", max_length=200, blank=True)
    sent_text = models.TextField("Отправленный текст", blank=True)

    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.SCHEDULED,
    )
    scheduled_at = models.DateTimeField("Запланировано на", null=True, blank=True)
    sent_at = models.DateTimeField("Отправлено в", null=True, blank=True)
    error = models.TextField("Текст ошибки", blank=True)

    class Meta:
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал работы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_status_display()} — {self.account} ({self.created_at:%d.%m %H:%M})"


class Dialog(TimeStamped):
    """Переписка одного из наших аккаунтов: личный чат или группа.

    Диалоги создаёт фоновый процесс, когда аккаунт получает сообщение. Оператор
    видит их в разделе «Сообщения» и может отвечать прямо из панели —
    ответ уходит в очередь и отправляется живым аккаунтом.
    """

    class Kind(models.TextChoices):
        PRIVATE = "private", "Личные сообщения"
        GROUP = "group", "Группа"

    kind = models.CharField("Тип", max_length=10, choices=Kind.choices, default=Kind.PRIVATE)
    peer_id = models.BigIntegerField(
        "ID чата/собеседника",
        help_text="Внутренний идентификатор чата в Telegram.",
    )

    # Кто/что на другой стороне: имя собеседника (для лички) или название группы.
    title = models.CharField("Кто/что", max_length=255, blank=True)
    username = models.CharField("Username", max_length=64, blank=True)

    # Для лички — наш аккаунт, который ведёт эту переписку.
    account = models.ForeignKey(
        TelegramAccount, verbose_name="Наш аккаунт", on_delete=models.CASCADE,
        null=True, blank=True, related_name="dialogs",
    )
    # Для группы — связь с настроенной группой (чтобы знать, кто может отвечать).
    group = models.ForeignKey(
        Group, verbose_name="Группа", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="dialogs",
    )

    last_message_at = models.DateTimeField("Последнее сообщение", null=True, blank=True)
    last_text = models.TextField("Текст последнего сообщения", blank=True)
    last_outgoing = models.BooleanField("Последнее — наше", default=False)
    unread = models.PositiveIntegerField("Непрочитано", default=0)

    class Meta:
        verbose_name = "Диалог"
        verbose_name_plural = "Сообщения"
        ordering = ["-last_message_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["peer_id"], condition=Q(kind="group"), name="uniq_group_dialog",
            ),
            models.UniqueConstraint(
                fields=["account", "peer_id"], condition=Q(kind="private"),
                name="uniq_private_dialog",
            ),
        ]

    def __str__(self):
        return self.title or str(self.peer_id)

    @property
    def peer_label(self) -> str:
        if self.username:
            return f"{self.title} (@{self.username})".strip()
        return self.title or str(self.peer_id)


class DialogMessage(TimeStamped):
    """Одно сообщение внутри диалога — входящее или отправленное нами."""

    class Status(models.TextChoices):
        PENDING = "pending", "Отправляется"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"

    class ContentType(models.TextChoices):
        TEXT = "text", "Текст"
        REACTION = "reaction", "Реакция"
        IMAGE = "image", "Изображение"
        STICKER = "sticker", "Стикер"

    dialog = models.ForeignKey(
        Dialog, verbose_name="Диалог", on_delete=models.CASCADE, related_name="messages",
    )
    tg_id = models.BigIntegerField("ID сообщения в Telegram", null=True, blank=True)

    outgoing = models.BooleanField("Исходящее (от нас)", default=False)
    via_panel = models.BooleanField("Отправлено из панели", default=False)

    # Каким аккаунтом отправлено (важно для групп, где отвечать может любой участник).
    account = models.ForeignKey(
        TelegramAccount, verbose_name="Аккаунт-отправитель", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="dialog_messages",
    )

    sender_id = models.BigIntegerField("ID автора", null=True, blank=True)
    sender_name = models.CharField("Автор", max_length=255, blank=True)
    text = models.TextField("Текст", blank=True)
    content_type = models.CharField(
        "Тип содержимого", max_length=12, choices=ContentType.choices,
        default=ContentType.TEXT,
    )
    reaction = models.CharField("Реакция", max_length=32, blank=True)
    media = models.FileField("Файл", upload_to="dialog_media/%Y/%m/%d", blank=True)
    reaction_to_tg_id = models.BigIntegerField(
        "ID сообщения для реакции", null=True, blank=True,
        help_text="Служебное поле: реакция всегда привязана к конкретному сообщению Telegram.",
    )
    date = models.DateTimeField("Время сообщения", null=True, blank=True)

    status = models.CharField(
        "Статус отправки", max_length=10, choices=Status.choices, default=Status.SENT,
    )
    error = models.TextField("Текст ошибки", blank=True)

    class Meta:
        verbose_name = "Сообщение диалога"
        verbose_name_plural = "Сообщения диалогов"
        ordering = ["date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["dialog", "tg_id"], condition=Q(tg_id__isnull=False),
                name="uniq_dialog_message",
            ),
        ]

    def __str__(self):
        who = "Мы" if self.outgoing else (self.sender_name or "собеседник")
        return f"{who}: {self.text[:40]}"

    @property
    def media_previewable(self) -> bool:
        """WEBP-стикеры можно показать прямо в браузере; TGS/WEBM — только открыть."""
        return bool(self.media and Path(self.media.name).suffix.lower() in IMAGE_EXTENSIONS)


class BotState(models.Model):
    """Единая «панель управления» ботом (одна строка).

    Кнопка в админке переключает `is_active`, а фоновый процесс (контейнер `bot`
    или `python manage.py run_bot`) читает этот флаг и обновляет `heartbeat`,
    чтобы панель знала, что процесс жив.
    """

    is_active = models.BooleanField("Бот включён", default=False)
    heartbeat = models.DateTimeField("Последний отклик процесса", null=True, blank=True)

    class Meta:
        verbose_name = "Состояние бота"
        verbose_name_plural = "Состояние бота"

    def __str__(self):
        return "включён" if self.is_active else "выключен"

    @classmethod
    def load(cls) -> "BotState":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ApiCredentials(TimeStamped):
    """«Главный аккаунт» — приложение Telegram (api_id / api_hash) с my.telegram.org.

    Таких можно завести несколько и распределить по ним Telegram-аккаунты: разные
    аккаунты работают через разные приложения — это снижает нагрузку на одно
    приложение и риск массовых блокировок (меньше похоже на «ферму» под одним api_id).

    Аккаунт, которому приложение не задано явно, использует приложение с галочкой
    «по умолчанию», а если такого нет — значения из .env.
    """

    title = models.CharField(
        "Название", max_length=120,
        help_text="Понятное имя приложения, например «Приложение №1».",
    )
    api_id = models.BigIntegerField(
        "API ID",
        help_text="Из https://my.telegram.org → API development tools.",
    )
    api_hash = models.CharField(
        "API Hash", max_length=64,
        help_text="Из https://my.telegram.org (там же, где API ID).",
    )
    is_default = models.BooleanField(
        "Использовать по умолчанию", default=False,
        help_text="Это приложение возьмут аккаунты, которым приложение не выбрано явно. "
                  "Отметить можно только одно.",
    )

    class Meta:
        verbose_name = "Главный аккаунт (API Telegram)"
        verbose_name_plural = "Главные аккаунты (API Telegram)"
        ordering = ["-is_default", "title"]

    def __str__(self):
        mark = " (по умолчанию)" if self.is_default else ""
        return f"{self.title}{mark}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # «По умолчанию» может быть только одно приложение
        if self.is_default:
            ApiCredentials.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_id and self.api_hash)
