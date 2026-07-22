"""
Создаёт демонстрационные данные по примеру из ТЗ (тема «маркетинг»):
одна группа, три аккаунта-заготовки, шаблоны и сценарий с тремя репликами
на 15, 30 и 45 секунд.

    python manage.py seed_demo

Аккаунты создаются как заготовки — их нужно подключить (авторизовать) в панели.
"""
from django.core.management.base import BaseCommand

from simulator.models import (
    Group,
    MessageTemplate,
    Scenario,
    ScenarioReply,
    TelegramAccount,
)


class Command(BaseCommand):
    help = "Наполняет базу демонстрационным сценарием из примера ТЗ."

    def handle(self, *args, **options):
        group, _ = Group.objects.get_or_create(
            title="Демо-группа",
            defaults={"trigger_scope": Group.TriggerScope.HOST_ONLY},
        )

        accounts = []
        for i in range(1, 4):
            acc, _ = TelegramAccount.objects.get_or_create(
                title=f"Аккаунт №{i}",
                defaults={"is_enabled": True},
            )
            group.accounts.add(acc)
            accounts.append(acc)

        questions = [
            "А как определить целевую аудиторию?",
            "Какой рекламный канал лучше выбрать?",
            "Сколько нужно денег на первый запуск рекламы?",
        ]
        templates = []
        for i, q in enumerate(questions, start=1):
            tpl, _ = MessageTemplate.objects.get_or_create(
                title=f"Вопрос про маркетинг №{i}",
                defaults={"category": "Маркетинг", "text": q},
            )
            templates.append(tpl)

        scenario, created = Scenario.objects.get_or_create(
            group=group,
            name="Обсуждение маркетинга",
            defaults={
                "match_type": Scenario.MatchType.CONTAINS,
                "trigger_text": "маркетинг",
                "is_enabled": True,
            },
        )

        if created:
            for order, (acc, tpl, delay) in enumerate(zip(accounts, templates, [15, 30, 45]), start=1):
                ScenarioReply.objects.create(
                    scenario=scenario,
                    account=acc,
                    delay_seconds=delay,
                    template=tpl,
                    order=order,
                )

        self.stdout.write(self.style.SUCCESS(
            "Демо-данные готовы. Откройте панель -> Сценарии -> «Обсуждение маркетинга».\n"
            "Не забудьте подключить аккаунты-заготовки и указать чат группы."
        ))
