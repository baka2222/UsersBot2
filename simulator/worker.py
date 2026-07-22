"""
Фоновый модуль симуляции.

Подключает все активные Telegram-аккаунты, слушает сообщения в настроенных
группах и по совпавшим сценариям отправляет запланированные реплики с задержкой.

Запуск:  python manage.py run_bot
"""
import asyncio
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from .matching import message_matches
from .models import (
    ActivityLog,
    Dialog,
    DialogMessage,
    Group,
    Scenario,
    TelegramAccount,
)

logger = logging.getLogger("simulator.worker")


# ----------------------------------------------------------------------------
#  Доступ к базе (синхронный ORM, обёрнутый для async)
# ----------------------------------------------------------------------------
@sync_to_async
def load_accounts():
    from . import telegram_client

    accounts = (
        TelegramAccount.objects.filter(
            is_enabled=True, status=TelegramAccount.Status.ACTIVE,
        )
        .exclude(session_string="")
        .select_related("api_credentials")
    )
    result = []
    for a in accounts:
        # Приложение (api_id/api_hash) для этого аккаунта: его → по умолчанию → .env
        try:
            api_id, api_hash = telegram_client.credentials_for_account(a)
        except telegram_client.TelegramConfigError:
            api_id, api_hash = 0, ""
        result.append({
            "id": a.id, "title": a.title, "session": a.session_string,
            "user_id": a.telegram_user_id, "phone": a.phone,
            "api_id": api_id, "api_hash": api_hash,
        })
    return result


@sync_to_async
def load_groups():
    result = []
    for g in Group.objects.filter(is_active=True):
        result.append({
            "id": g.id,
            "title": g.title,
            "chat_id": g.chat_id,
            "chat_username": g.chat_username,
            "invite_link": g.invite_link,
            "trigger_scope": g.trigger_scope,
            "host_username": g.host_username,
            "host_user_id": g.host_user_id,
        })
    return result


@sync_to_async
def save_group_chat_id(group_id: int, chat_id: int):
    Group.objects.filter(pk=group_id).update(chat_id=chat_id)


@sync_to_async
def save_group_host_id(group_id: int, host_user_id: int):
    Group.objects.filter(pk=group_id).update(host_user_id=host_user_id)


@sync_to_async
def load_matching_scenarios(group_id: int, text: str, available_account_ids: set[int]):
    """Возвращает совпавшие включённые сценарии с готовыми к отправке репликами."""
    matched = []
    scenarios = (
        Scenario.objects.filter(group_id=group_id, is_enabled=True)
        .prefetch_related("replies", "replies__account", "replies__template")
        .order_by("-priority", "id")
    )
    now = timezone.now()
    for scenario in scenarios:
        if not message_matches(scenario, text):
            continue
        if scenario.cooldown_seconds and scenario.last_triggered_at:
            elapsed = (now - scenario.last_triggered_at).total_seconds()
            if elapsed < scenario.cooldown_seconds:
                continue

        replies = []
        for reply in scenario.replies.all():
            if not reply.is_enabled:
                continue
            if reply.account_id not in available_account_ids:
                continue
            # Подставляем случайное число вместо {number} в момент срабатывания
            text_out = reply.render_text()
            if not text_out.strip():
                continue
            replies.append({
                "id": reply.id,
                "account_id": reply.account_id,
                "delay": reply.delay_seconds,
                "text": text_out,
                "reply_to_trigger": reply.reply_to_trigger,
            })
        if replies:
            matched.append({"id": scenario.id, "name": scenario.name, "replies": replies})
            Scenario.objects.filter(pk=scenario.id).update(last_triggered_at=now)
    return matched


@sync_to_async
def create_log(*, group_id, scenario_id, reply_id, account_id, trigger_text,
               trigger_sender, sent_text, scheduled_at):
    log = ActivityLog.objects.create(
        group_id=group_id,
        scenario_id=scenario_id,
        reply_id=reply_id,
        account_id=account_id,
        trigger_text=trigger_text or "",
        trigger_sender=trigger_sender or "",
        sent_text=sent_text or "",
        status=ActivityLog.Status.SCHEDULED,
        scheduled_at=scheduled_at,
    )
    return log.id


@sync_to_async
def mark_log_sent(log_id: int):
    ActivityLog.objects.filter(pk=log_id).update(
        status=ActivityLog.Status.SENT, sent_at=timezone.now(),
    )


@sync_to_async
def mark_log_failed(log_id: int, error: str):
    ActivityLog.objects.filter(pk=log_id).update(
        status=ActivityLog.Status.FAILED, error=error[:2000],
    )


# ----------------------------------------------------------------------------
#  Инбокс: сохранение входящих/исходящих сообщений и очередь ответов из панели
# ----------------------------------------------------------------------------
@sync_to_async
def record_message(*, kind, peer_id, account_id, group_id, title, username,
                   tg_id, sender_id, sender_name, text, date, outgoing):
    """Сохраняет одно сообщение в диалог. Диалог заводится автоматически.

    Дубликаты (одно и то же сообщение видно нескольким нашим аккаунтам в группе)
    отсекаются уникальным ограничением (dialog, tg_id).
    """
    from django.db import IntegrityError
    from django.db.models import F

    if kind == Dialog.Kind.GROUP:
        dialog, _ = Dialog.objects.get_or_create(
            kind=Dialog.Kind.GROUP, peer_id=peer_id,
            defaults={"title": title, "username": username, "group_id": group_id},
        )
    else:
        dialog, _ = Dialog.objects.get_or_create(
            kind=Dialog.Kind.PRIVATE, account_id=account_id, peer_id=peer_id,
            defaults={"title": title, "username": username},
        )

    # Поддерживаем название/username диалога в актуальном виде
    changed = []
    if title and dialog.title != title:
        dialog.title = title
        changed.append("title")
    if username and dialog.username != username:
        dialog.username = username
        changed.append("username")
    if kind == Dialog.Kind.GROUP and group_id and dialog.group_id != group_id:
        dialog.group_id = group_id
        changed.append("group")
    if changed:
        dialog.save(update_fields=changed)

    try:
        DialogMessage.objects.create(
            dialog=dialog,
            tg_id=tg_id,
            outgoing=outgoing,
            account_id=account_id if outgoing else None,
            sender_id=sender_id,
            sender_name=sender_name or "",
            text=text or "",
            date=date,
            status=DialogMessage.Status.SENT,
        )
    except IntegrityError:
        # Это сообщение уже сохранено (увидел другой наш аккаунт либо это наш
        # ответ из панели) — пропускаем.
        return

    fields = ["last_message_at", "last_text", "last_outgoing"]
    dialog.last_message_at = date or timezone.now()
    dialog.last_text = (text or "")[:500]
    dialog.last_outgoing = outgoing
    if not outgoing:
        Dialog.objects.filter(pk=dialog.pk).update(unread=F("unread") + 1)
    dialog.save(update_fields=fields)


@sync_to_async
def load_pending_outgoing():
    """Ответы, созданные оператором в панели и ждущие отправки живым аккаунтом."""
    qs = (
        DialogMessage.objects
        .filter(outgoing=True, status=DialogMessage.Status.PENDING)
        .select_related("dialog", "account", "dialog__account")
        .order_by("id")[:20]
    )
    items = []
    for m in qs:
        account_id = m.account_id or m.dialog.account_id
        items.append({
            "id": m.id,
            "peer_id": m.dialog.peer_id,
            "username": m.dialog.username,
            "text": m.text,
            "account_id": account_id,
        })
    return items


@sync_to_async
def mark_outgoing_sent(msg_id: int, tg_id: int, date):
    msg = DialogMessage.objects.select_related("dialog").filter(pk=msg_id).first()
    if not msg:
        return
    # Наш собственный исходящий апдейт мог быть уже пойман обработчиком событий и
    # сохранён отдельной строкой — убираем дубль, оставляя запись из панели.
    DialogMessage.objects.filter(
        dialog_id=msg.dialog_id, tg_id=tg_id,
    ).exclude(pk=msg_id).delete()
    DialogMessage.objects.filter(pk=msg_id).update(
        status=DialogMessage.Status.SENT, tg_id=tg_id, date=date, error="",
    )
    Dialog.objects.filter(pk=msg.dialog_id).update(
        last_message_at=date or timezone.now(),
        last_text=(msg.text or "")[:500],
        last_outgoing=True,
    )


@sync_to_async
def mark_outgoing_failed(msg_id: int, error: str):
    DialogMessage.objects.filter(pk=msg_id).update(
        status=DialogMessage.Status.FAILED, error=error[:2000],
    )


# ----------------------------------------------------------------------------
#  Управление ботом (флаг вкл/выкл + heartbeat), общее на весь процесс
# ----------------------------------------------------------------------------
HEARTBEAT_INTERVAL = 5      # как часто процесс отмечается «живым», сек
RETRY_INTERVAL = 15         # пауза перед повторной попыткой подключения, сек
GROUP_REFRESH_INTERVAL = 30  # как часто перечитывать список групп на ходу, сек
OUTBOX_INTERVAL = 3         # как часто проверять очередь ответов из панели, сек

# Флаг «бот включён», обновляется heartbeat-циклом и читается обработчиком сообщений
_STATE = {"active": False}


@sync_to_async
def beat_and_get_active() -> bool:
    """Отмечает процесс живым (heartbeat=сейчас) и возвращает актуальный флаг is_active."""
    from .models import BotState

    state = BotState.load()
    state.heartbeat = timezone.now()
    state.save(update_fields=["heartbeat"])
    return state.is_active


async def _heartbeat_loop():
    """Постоянно: отмечаем процесс живым и подхватываем нажатие кнопки «Вкл/Выкл»."""
    while True:
        try:
            _STATE["active"] = await beat_and_get_active()
        except Exception as exc:  # noqa: BLE001
            logger.debug("heartbeat error: %s", exc)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ----------------------------------------------------------------------------
#  Основной класс воркера
# ----------------------------------------------------------------------------
class SimulationWorker:
    def __init__(self):
        self.clients = {}            # account_id -> TelegramClient
        self.account_titles = {}     # account_id -> название (для подписи наших сообщений)
        self.own_user_ids = set()    # id аккаунтов системы (их сообщения игнорируем)
        self.chat_to_group = {}      # peer_id -> group dict
        self.processed = set()       # (chat_id, message_id) для защиты от дублей
        self._tasks = set()          # активные отложенные отправки
        self._warned_group_ids = set()  # чтобы не спамить предупреждениями каждые 30 сек
        self._refresh_task = None    # фоновое перечитывание групп
        self._outbox_task = None     # фоновая отправка ответов из панели

    async def run(self):
        """Подключает аккаунты и слушает группы. Возвращает управление, если
        подключаться нечем или все клиенты отключились (внешний цикл повторит попытку)."""
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        from . import telegram_client

        accounts = await load_accounts()
        if not accounts:
            logger.info("Нет активных авторизованных аккаунтов. Жду, пока их подключат в панели.")
            return

        # Поднимаем клиентов. Каждый аккаунт подключается через СВОЁ приложение
        # (api_id/api_hash) — их удобно распределять, чтобы снизить риск блокировок.
        for acc in accounts:
            if not acc.get("api_id") or not acc.get("api_hash"):
                logger.warning(
                    "Аккаунт «%s» пропущен: не заданы API ID / API Hash (ни своё "
                    "приложение, ни приложение по умолчанию, ни .env).", acc["title"],
                )
                continue
            client = TelegramClient(
                StringSession(acc["session"]), acc["api_id"], acc["api_hash"],
                **telegram_client.client_settings(acc.get("phone")),
            )
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning("Аккаунт «%s» не авторизован — пропущен.", acc["title"])
                    await client.disconnect()
                    continue
                me = await client.get_me()
                self.own_user_ids.add(me.id)
                self.clients[acc["id"]] = client
                self.account_titles[acc["id"]] = acc["title"]
                logger.info("Подключён аккаунт: %s (@%s)", acc["title"], me.username or me.id)
            except Exception as exc:  # noqa: BLE001
                logger.error("Не удалось подключить аккаунт «%s»: %s", acc["title"], exc)

        if not self.clients:
            logger.warning("Ни один аккаунт не подключился. Повторю попытку позже.")
            return

        await self._resolve_groups()
        self._register_handlers()

        logger.info(
            "Готов к работе. Аккаунтов: %d, групп под наблюдением: %d. Отправка: %s.",
            len(self.clients), len(self.chat_to_group),
            "включена" if _STATE["active"] else "на паузе (нажмите «Запустить бота»)",
        )
        # На ходу подхватываем новые/изменённые группы — без перезапуска бота
        self._refresh_task = asyncio.create_task(self._periodic_refresh())
        # Отправляем ответы, созданные оператором в панели
        self._outbox_task = asyncio.create_task(self._outbox_loop())
        try:
            # Держим всех клиентов в работе, пока они на связи. return_exceptions=True —
            # чтобы сбой одного аккаунта не ронял остальные посреди занятия.
            await asyncio.gather(
                *(c.run_until_disconnected() for c in self.clients.values()),
                return_exceptions=True,
            )
        finally:
            if self._refresh_task:
                self._refresh_task.cancel()
            if self._outbox_task:
                self._outbox_task.cancel()
            for client in self.clients.values():
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    async def _periodic_refresh(self):
        """Раз в GROUP_REFRESH_INTERVAL сек перечитывает группы: новые начинают
        отслеживаться, а отключённые/удалённые перестают — без перезапуска процесса."""
        while True:
            await asyncio.sleep(GROUP_REFRESH_INTERVAL)
            try:
                await self._resolve_groups()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ошибка обновления списка групп: %s", exc)

    async def _resolve_groups(self):
        """Перечитывает активные группы и заново строит карту «чат → группа».
        Безопасно вызывать повторно: новые группы добавляются, исчезнувшие убираются."""
        from telethon import utils

        resolver = next(iter(self.clients.values()))
        groups = await load_groups()
        new_map = {}

        for group in groups:
            chat_id = group["chat_id"]

            # 1) Определяем чат по username/ссылке, если числовой ID ещё не задан
            if not chat_id and group["chat_username"]:
                try:
                    entity = await resolver.get_entity(group["chat_username"])
                    chat_id = utils.get_peer_id(entity)
                except Exception as exc:  # noqa: BLE001
                    self._warn_group(group, f"не удалось найти @{group['chat_username']} ({exc})")

            if not chat_id and group["invite_link"] and settings.WORKER_AUTOJOIN:
                chat_id = await self._resolve_by_invite(resolver, group["invite_link"], group)

            if not chat_id:
                self._warn_group(group, "не удалось определить чат — пропущена")
                continue

            self._warned_group_ids.discard(group["id"])  # чат определился — снимаем прошлые предупреждения

            if chat_id != group["chat_id"]:
                await save_group_chat_id(group["id"], chat_id)
                group["chat_id"] = chat_id

            # 2) Определяем ведущего по username, если задан только он
            if group["host_username"] and not group["host_user_id"]:
                try:
                    host = await resolver.get_entity(group["host_username"])
                    group["host_user_id"] = host.id
                    await save_group_host_id(group["id"], host.id)
                except Exception as exc:  # noqa: BLE001
                    self._warn_group(group, f"не удалось определить ведущего @{group['host_username']} ({exc})")

            new_map[chat_id] = group
            if chat_id not in self.chat_to_group:
                logger.info("Наблюдение за группой «%s» (чат %s).", group["title"], chat_id)

        # Сообщаем о группах, которые перестали отслеживаться (отключили/удалили)
        for old_chat, old_group in self.chat_to_group.items():
            if old_chat not in new_map:
                logger.info("Группа «%s» больше не отслеживается.", old_group["title"])

        self.chat_to_group = new_map

    def _warn_group(self, group, message: str):
        """Предупреждение по группе — не чаще одного раза до устранения причины."""
        if group["id"] not in self._warned_group_ids:
            self._warned_group_ids.add(group["id"])
            logger.warning("Группа «%s»: %s", group["title"], message)

    async def _resolve_by_invite(self, client, link: str, group):
        """Определяет чат по ссылке-приглашению. Работает и когда аккаунт уже
        состоит в группе (тогда просто берём её chat_id, не пытаясь вступить снова)."""
        from telethon import utils
        from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
        from telethon.tl.types import ChatInviteAlready, ChatInvitePeek

        try:
            invite_hash = link.rstrip("/").split("/")[-1].lstrip("+")
            info = await client(CheckChatInviteRequest(invite_hash))
            # Уже участник — берём чат из ответа, не вступая повторно
            if isinstance(info, (ChatInviteAlready, ChatInvitePeek)):
                return utils.get_peer_id(info.chat)
            # Ещё не участник — вступаем по ссылке
            updates = await client(ImportChatInviteRequest(invite_hash))
            return utils.get_peer_id(updates.chats[0])
        except Exception as exc:  # noqa: BLE001
            self._warn_group(group, f"не удалось определить чат по ссылке ({exc})")
            return None

    def _register_handlers(self):
        from telethon import events

        for account_id, client in self.clients.items():
            @client.on(events.NewMessage())
            async def handler(event, _self=self, _aid=account_id):
                await _self._on_message(event, _aid)

    async def _on_message(self, event, account_id):
        # 1) Всегда сохраняем сообщение в инбокс (личку и настроенные группы),
        #    независимо от того, включена ли отправка по сценариям.
        try:
            await self._capture(event, account_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось сохранить сообщение в инбокс: %s", exc)

        # Наши собственные исходящие в сценариях не участвуют
        if event.out:
            return

        # 2) Автоответы по сценариям — только когда бот включён кнопкой в панели
        if not _STATE["active"]:
            return

        chat_id = event.chat_id
        group = self.chat_to_group.get(chat_id)
        if not group:
            return

        key = (chat_id, event.id)
        if key in self.processed:
            return
        self.processed.add(key)
        if len(self.processed) > 20000:
            self.processed.clear()

        sender_id = event.sender_id
        # Никогда не реагируем на сообщения собственных аккаунтов (защита от петель)
        if sender_id in self.own_user_ids:
            return

        # Фильтр «слушать только ведущего»
        if group["trigger_scope"] == Group.TriggerScope.HOST_ONLY and group.get("host_user_id"):
            if sender_id != group["host_user_id"]:
                return

        text = event.raw_text or ""
        available = set(self.clients.keys())
        scenarios = await load_matching_scenarios(group["id"], text, available)
        if not scenarios:
            return

        sender_name = await self._describe_sender(event)
        now = timezone.now()
        from datetime import timedelta

        for scenario in scenarios:
            for reply in scenario["replies"]:
                scheduled_at = now + timedelta(seconds=reply["delay"])
                log_id = await create_log(
                    group_id=group["id"],
                    scenario_id=scenario["id"],
                    reply_id=reply["id"],
                    account_id=reply["account_id"],
                    trigger_text=text,
                    trigger_sender=sender_name,
                    sent_text=reply["text"],
                    scheduled_at=scheduled_at,
                )
                task = asyncio.create_task(
                    self._send_later(chat_id, event.id, reply, log_id, scenario["name"])
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _send_later(self, chat_id, trigger_msg_id, reply, log_id, scenario_name):
        from telethon.errors import FloodWaitError, PeerFloodError

        try:
            await asyncio.sleep(reply["delay"])
            client = self.clients.get(reply["account_id"])
            if client is None:
                await mark_log_failed(log_id, "Аккаунт не подключён.")
                return
            kwargs = {}
            if reply["reply_to_trigger"] and trigger_msg_id:
                kwargs["reply_to"] = trigger_msg_id
            await client.send_message(chat_id, reply["text"], **kwargs)
            await mark_log_sent(log_id)
            logger.info("Отправлено по сценарию «%s» (задержка %s с).", scenario_name, reply["delay"])
        except FloodWaitError as exc:
            # Telegram просит паузу дольше нашего порога — не отправляем, чтобы не усугублять
            await mark_log_failed(
                log_id, f"Флуд-контроль Telegram: аккаунт просит паузу {exc.seconds} с. Сообщение не отправлено.",
            )
            logger.warning(
                "FloodWait %s с по сценарию «%s» — пропускаю отправку, даю аккаунту передохнуть.",
                exc.seconds, scenario_name,
            )
        except PeerFloodError:
            await mark_log_failed(
                log_id, "Аккаунт временно ограничен Telegram (PeerFlood). Дайте ему паузу минимум на сутки.",
            )
            logger.warning(
                "PeerFlood по сценарию «%s» — аккаунт ограничен, отправка приостановлена.", scenario_name,
            )
        except Exception as exc:  # noqa: BLE001
            await mark_log_failed(log_id, str(exc))
            logger.error("Ошибка отправки по сценарию «%s»: %s", scenario_name, exc)

    async def _describe_sender(self, event):
        try:
            sender = await event.get_sender()
            if sender is None:
                return str(event.sender_id)
            name = " ".join(p for p in [getattr(sender, "first_name", ""),
                                        getattr(sender, "last_name", "")] if p)
            username = getattr(sender, "username", "")
            if username:
                return f"{name} (@{username})".strip()
            return name or str(event.sender_id)
        except Exception:  # noqa: BLE001
            return str(event.sender_id)

    # ---- Инбокс: сохранение входящих/исходящих сообщений ----
    async def _capture(self, event, account_id):
        """Сохраняет сообщение в диалог: личку — всегда, группу — если она настроена."""
        peer_id = event.chat_id
        outgoing = bool(event.out)

        # Текст или пометка о вложении, чтобы в панели было видно и медиа-сообщения
        text = event.raw_text or ""
        if not text:
            if event.message and event.message.media is not None:
                text = "[вложение]"
            else:
                return  # служебное/пустое сообщение — не сохраняем

        if event.is_private:
            kind = Dialog.Kind.PRIVATE
            group_id = None
            chat = await self._safe_get_chat(event)
            title = self._entity_name(chat) or str(peer_id)
            username = getattr(chat, "username", "") or ""
        elif event.is_group or event.is_channel:
            group = self.chat_to_group.get(peer_id)
            if not group:
                return  # группа не настроена в панели — не засоряем инбокс
            kind = Dialog.Kind.GROUP
            group_id = group["id"]
            title = group["title"]
            username = group.get("chat_username", "") or ""
        else:
            return

        if outgoing:
            sender_id = None
            sender_name = self.account_titles.get(account_id, "Вы")
        else:
            sender_id = event.sender_id
            sender_name = await self._describe_sender(event)

        await record_message(
            kind=kind,
            peer_id=peer_id,
            account_id=account_id,
            group_id=group_id,
            title=title,
            username=username,
            tg_id=event.id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            date=event.date,
            outgoing=outgoing,
        )

    async def _safe_get_chat(self, event):
        try:
            return await event.get_chat()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _entity_name(entity) -> str:
        if entity is None:
            return ""
        name = " ".join(p for p in [getattr(entity, "first_name", ""),
                                     getattr(entity, "last_name", "")] if p)
        return name or getattr(entity, "title", "") or ""

    # ---- Очередь ответов из панели ----
    async def _outbox_loop(self):
        """Периодически берёт из базы ответы, созданные оператором, и отправляет их."""
        while True:
            await asyncio.sleep(OUTBOX_INTERVAL)
            try:
                pending = await load_pending_outgoing()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ошибка чтения очереди ответов: %s", exc)
                continue
            for item in pending:
                await self._send_outgoing(item)

    async def _send_outgoing(self, item):
        from telethon.errors import FloodWaitError, PeerFloodError

        client = self.clients.get(item["account_id"])
        if client is None:
            await mark_outgoing_failed(
                item["id"], "Аккаунт-отправитель сейчас не подключён к боту.",
            )
            return
        try:
            target = item["peer_id"]
            try:
                msg = await client.send_message(target, item["text"])
            except (ValueError, TypeError):
                # Сущность ещё не в кеше клиента — пробуем по username
                if item.get("username"):
                    msg = await client.send_message(item["username"], item["text"])
                else:
                    raise
            await mark_outgoing_sent(item["id"], msg.id, msg.date)
            logger.info("Ответ из панели отправлен (диалог %s).", item["peer_id"])
        except FloodWaitError as exc:
            await mark_outgoing_failed(
                item["id"], f"Флуд-контроль Telegram: пауза {exc.seconds} с. Повторите ответ позже.",
            )
            logger.warning("FloodWait %s с при ответе из панели (диалог %s).", exc.seconds, item["peer_id"])
        except PeerFloodError:
            await mark_outgoing_failed(
                item["id"], "Аккаунт временно ограничен Telegram (PeerFlood). Нужна пауза минимум на сутки.",
            )
            logger.warning("PeerFlood при ответе из панели (диалог %s) — аккаунт ограничен.", item["peer_id"])
        except Exception as exc:  # noqa: BLE001
            await mark_outgoing_failed(item["id"], str(exc))
            logger.error("Не удалось отправить ответ из панели: %s", exc)


async def run_worker():
    """Точка входа фонового процесса.

    Постоянно отмечается «живым» (heartbeat) и подключает аккаунты. Если аккаунтов
    ещё нет или связь оборвалась — периодически повторяет попытку, не завершаясь.
    Отправка сообщений включается/выключается кнопкой в панели (флаг is_active).
    """
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info("Фоновый процесс запущен и ждёт команд из панели.")
    try:
        while True:
            worker = SimulationWorker()
            try:
                await worker.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Сбой воркера, перезапуск через %d с: %s", RETRY_INTERVAL, exc)
            await asyncio.sleep(RETRY_INTERVAL)
    finally:
        heartbeat_task.cancel()
