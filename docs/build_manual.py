# -*- coding: utf-8 -*-
"""
Генератор PDF-инструкции для не-программиста ("Инструкция-по-панели.pdf").

Как пересобрать (Windows):
    pip install fpdf2
    python docs/build_manual.py

Готовый файл кладётся в корень проекта. Кириллица берётся из системного шрифта
Arial (C:/Windows/Fonts). Текст инструкции можно редактировать прямо здесь —
в блоках «ШАГ 1..9» ниже.
"""
import os

from fpdf import FPDF
from fpdf.enums import XPos, YPos, MethodReturnValue

F = "Arial"
FONTS = os.environ.get("WINDIR", "C:/Windows") + "/Fonts"

BRAND = (37, 99, 155)      # синий
NAVY = (26, 54, 82)        # тёмно-синий (заголовки)
INK = (35, 40, 46)         # основной текст

STYLES = {
    "tip":    ((231, 241, 251), (37, 99, 155), "СОВЕТ"),
    "warn":   ((255, 243, 205), (166, 111, 6), "ВАЖНО"),
    "danger": ((250, 224, 227), (176, 42, 55), "ЕСЛИ НЕ ПОЛУЧАЕТСЯ"),
    "info":   ((238, 241, 244), (78, 90, 102), "ПОЯСНЕНИЕ"),
}


class PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font(F, "", 8)
        self.set_text_color(160)
        self.set_draw_color(220)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1)
        self.cell(0, 6, f"Инструкция по работе с панелью  ·  стр. {self.page_no()}",
                  align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def pdf_new():
    pdf = PDF(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_font(F, "", f"{FONTS}/arial.ttf")
    pdf.add_font(F, "B", f"{FONTS}/arialbd.ttf")
    pdf.add_font(F, "I", f"{FONTS}/ariali.ttf")
    return pdf


def ensure(pdf, h):
    if pdf.get_y() + h > pdf.h - pdf.b_margin:
        pdf.add_page()


def para(pdf, text, size=10.5, gap=2.2):
    pdf.set_font(F, "", size)
    pdf.set_text_color(*INK)
    pdf.multi_cell(pdf.epw, 5.6, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(gap)


def subhead(pdf, text):
    ensure(pdf, 12)
    pdf.ln(0.5)
    pdf.set_font(F, "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(pdf.epw, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(0.8)
    pdf.set_text_color(*INK)


def bullet(pdf, text, size=10.5):
    pdf.set_font(F, "", size)
    pdf.set_text_color(*INK)
    ensure(pdf, 6)
    x = pdf.l_margin
    y = pdf.get_y()
    pdf.set_xy(x + 2, y)
    pdf.cell(4, 5.4, "•", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_xy(x + 6.5, y)
    pdf.multi_cell(pdf.epw - 6.5, 5.4, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def step_heading(pdf, num, title):
    ensure(pdf, 18)
    pdf.ln(2)
    y = pdf.get_y()
    x = pdf.l_margin
    d = 9.0
    pdf.set_fill_color(*BRAND)
    pdf.ellipse(x, y, d, d, style="F")
    pdf.set_font(F, "B", 12)
    pdf.set_text_color(255)
    pdf.set_xy(x, y + 1.3)
    pdf.cell(d, 6, str(num), align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_xy(x + d + 4.5, y)
    pdf.set_font(F, "B", 14.5)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(pdf.epw - d - 4.5, d, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    yy = pdf.get_y() + 1.5
    pdf.set_draw_color(*BRAND)
    pdf.set_line_width(0.4)
    pdf.line(x, yy, pdf.w - pdf.r_margin, yy)
    pdf.ln(4)
    pdf.set_text_color(*INK)


def callout(pdf, kind, text, title=None):
    bg, accent, label = STYLES[kind]
    if title:
        label = title
    pad, stripe = 3.5, 1.8
    x, w = pdf.l_margin, pdf.epw
    tw = w - 2 * pad - stripe

    pdf.set_font(F, "B", 9.5)
    th_title = pdf.multi_cell(tw, 4.8, label, dry_run=True,
                              output=MethodReturnValue.HEIGHT, new_x=XPos.LEFT, new_y=YPos.TOP)
    pdf.set_font(F, "", 10)
    th_body = pdf.multi_cell(tw, 5.2, text, dry_run=True,
                             output=MethodReturnValue.HEIGHT, new_x=XPos.LEFT, new_y=YPos.TOP)
    total = pad + th_title + 1.6 + th_body + pad
    ensure(pdf, total + 3)

    y = pdf.get_y()
    pdf.set_fill_color(*bg)
    pdf.rect(x, y, w, total, style="F")
    pdf.set_fill_color(*accent)
    pdf.rect(x, y, stripe, total, style="F")

    pdf.set_xy(x + stripe + pad, y + pad)
    pdf.set_font(F, "B", 9.5)
    pdf.set_text_color(*accent)
    pdf.multi_cell(tw, 4.8, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(x + stripe + pad, pdf.get_y() + 1.6)
    pdf.set_font(F, "", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(tw, 5.2, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(y + total + 3.5)
    pdf.set_text_color(*INK)


def build():
    pdf = pdf_new()
    pdf.add_page()

    # --- Шапка титула ---
    pdf.set_fill_color(*BRAND)
    pdf.rect(0, 0, pdf.w, 40, style="F")
    pdf.set_xy(pdf.l_margin, 11)
    pdf.set_font(F, "B", 23)
    pdf.set_text_color(255)
    pdf.cell(0, 11, "Панель управления", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(pdf.l_margin)
    pdf.set_font(F, "", 13)
    pdf.cell(0, 8, "Пошаговая инструкция для работы с системой")
    pdf.set_y(48)

    pdf.set_text_color(*INK)
    para(pdf,
         "Это веб-панель, которая управляет Telegram-аккаунтами. Вы подключаете аккаунты, описываете, "
         "на какие сообщения и как отвечать, и запускаете бота — дальше он работает сам. Отдельно есть "
         "раздел «Сообщения» для живой переписки вручную. Ниже — весь путь по шагам, без лишнего.", gap=3)

    overview = [
        "Войдите в панель",
        "(по желанию) Добавьте «главные аккаунты» — приложения Telegram",
        "Подключите Telegram-аккаунты",
        "Создайте группу и сценарии ответов",
        "Запустите бота",
        "Следите за журналом работы",
        "Отвечайте вручную в разделе «Сообщения»",
        "Берегите аккаунты от блокировок",
    ]
    pad = 4
    x, w = pdf.l_margin, pdf.epw
    line_h = 6.2
    box_h = pad + 7 + len(overview) * line_h + pad
    ensure(pdf, box_h + 3)
    y = pdf.get_y()
    pdf.set_fill_color(245, 247, 249)
    pdf.rect(x, y, w, box_h, style="F")
    pdf.set_draw_color(*BRAND)
    pdf.set_line_width(0.5)
    pdf.rect(x, y, w, box_h)
    pdf.set_xy(x + pad, y + pad)
    pdf.set_font(F, "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 7, "Весь путь за 8 шагов", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for i, t in enumerate(overview, 1):
        pdf.set_x(x + pad)
        pdf.set_font(F, "B", 10.5)
        pdf.set_text_color(*BRAND)
        pdf.cell(6, line_h, f"{i}.", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font(F, "", 10.5)
        pdf.set_text_color(*INK)
        pdf.cell(0, line_h, t, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(y + box_h + 2)

    # ШАГ 1
    step_heading(pdf, 1, "Войдите в панель")
    bullet(pdf, "Откройте в браузере адрес панели. Его даёт тот, кто устанавливал систему "
                "(обычно http://localhost:8080 или http://адрес-сервера:8080).")
    bullet(pdf, "Введите логин и пароль администратора.")
    callout(pdf, "tip",
            "Не знаете адрес или пароль — спросите у того, кто устанавливал систему. "
            "Пароль администратора задаётся при установке в файле .env.")

    # ШАГ 2
    step_heading(pdf, 2, "Добавьте «главные аккаунты» (по желанию)")
    para(pdf, "«Главный аккаунт» — это приложение Telegram с данными api_id и api_hash. Их можно "
              "завести несколько и распределить по ним подключённые аккаунты: так активность не "
              "сходится к одному приложению — меньше риск блокировок.")
    subhead(pdf, "Где взять api_id и api_hash")
    bullet(pdf, "Откройте my.telegram.org и войдите под номером телефона.")
    bullet(pdf, "Раздел «API development tools» — там будут api_id и api_hash.")
    subhead(pdf, "Как добавить в панель")
    bullet(pdf, "Меню → «Главные аккаунты (API Telegram)» → «Добавить».")
    bullet(pdf, "Впишите название, api_id и api_hash. Одно приложение отметьте «по умолчанию».")
    callout(pdf, "info",
            "Этот шаг можно пропустить — тогда все аккаунты используют приложение, заданное при "
            "установке (в файле .env). Заводить несколько приложений имеет смысл, когда аккаунтов много.")
    callout(pdf, "warn",
            "Приложение для аккаунта выбирайте ДО его подключения. Смена приложения у уже "
            "подключённого аккаунта потребует подключить его заново.")

    # ШАГ 3
    step_heading(pdf, 3, "Подключите Telegram-аккаунты")
    bullet(pdf, "Меню → «Telegram-аккаунты» → «Добавить». Впишите понятное название, например «Аккаунт №1».")
    bullet(pdf, "При желании выберите приложение (главный аккаунт), через которое он будет работать. Нажмите «Сохранить».")
    bullet(pdf, "Нажмите кнопку «Подключить» и пройдите два шага:")
    para(pdf, "        • Шаг 1 — введите номер телефона, на него придёт код в Telegram.\n"
              "        • Шаг 2 — введите код. Если на аккаунте включён облачный пароль (2FA) — введите и его.")
    callout(pdf, "danger",
            "Код не приходит? Нажмите «Войти по QR-коду». На телефоне ЭТОГО аккаунта откройте: "
            "Telegram → Настройки → Устройства → Подключить устройство — и наведите камеру на QR-код, "
            "показанный в панели.")
    bullet(pdf, "Когда всё удалось, статус аккаунта станет «Активен» (зелёный).")

    # ШАГ 4
    step_heading(pdf, 4, "Создайте группу и сценарии ответов")
    para(pdf, "Меню → «Группы» → «Добавить». Вся настройка — на одной странице, сверху вниз.")
    subhead(pdf, "1. Название")
    bullet(pdf, "Понятное имя группы — только для вас, в панели.")
    subhead(pdf, "2. Какой чат в Telegram — укажите ОДИН вариант")
    bullet(pdf, "@username — для публичной группы (без символа «@»);")
    bullet(pdf, "ссылка-приглашение вида https://t.me/+... — для закрытой группы;")
    bullet(pdf, "или числовой ID. Обычно поле оставляют пустым — определится само.")
    subhead(pdf, "3. Чьи сообщения запускают сценарии")
    bullet(pdf, "Обычно это @username ведущего занятия (без «@»).")
    subhead(pdf, "Аккаунты-участники")
    bullet(pdf, "Отметьте, какие подключённые аккаунты будут отвечать в этой группе.")
    callout(pdf, "warn",
            "Аккаунт должен быть участником этого чата в Telegram, иначе он не увидит сообщения "
            "и не сможет ответить. Для закрытых групп поможет ссылка-приглашение.")
    subhead(pdf, "Сценарии — на что и как отвечать")
    bullet(pdf, "Нажмите «Добавить ещё один Сценарий».")
    bullet(pdf, "Условие: на какое сообщение реагировать (содержит текст / точно совпадает / любое сообщение и т.п.).")
    bullet(pdf, "Ответы: кто отвечает, через сколько секунд и что именно пишет.")
    callout(pdf, "tip",
            "Чтобы фразы выглядели живее, пишите в тексте ответа диапазоны в фигурных скобках, "
            "например: Босс, мы получили {50000-200000}$ за {5-30} дней. Вместо каждого диапазона "
            "подставится своё случайное число.")
    bullet(pdf, "Внизу страницы нажмите «Сохранить».")

    # ШАГ 5
    step_heading(pdf, 5, "Запустите бота")
    bullet(pdf, "Меню → «Запуск бота» (кнопка слева или сверху) → зелёная кнопка «Запустить бота».")
    bullet(pdf, "Проводите занятие: когда ведущий отправит подходящее сообщение, выбранные аккаунты ответят через заданное время.")
    bullet(pdf, "После занятия нажмите красную кнопку «Остановить бота».")
    callout(pdf, "info",
            "Группы, сценарии и ответы применяются на ходу — их можно менять без перезапуска. "
            "Перезапуск бота нужен только после добавления НОВОГО аккаунта.")

    # ШАГ 6
    step_heading(pdf, 6, "Следите за журналом работы")
    bullet(pdf, "Меню → «Журнал работы».")
    bullet(pdf, "Видно: кто написал сообщение-триггер, какой аккаунт ответил, каким сценарием, когда — и если была ошибка.")

    # ШАГ 7
    step_heading(pdf, 7, "Отвечайте вручную в разделе «Сообщения»")
    bullet(pdf, "Меню → «Сообщения». Здесь собираются личные переписки и чаты настроенных групп.")
    bullet(pdf, "Откройте диалог кнопкой «Открыть» и напишите ответ внизу страницы.")
    bullet(pdf, "В группе можно выбрать, от имени какого аккаунта-участника ответить.")
    callout(pdf, "info",
            "Сообщения появляются и ваши ответы отправляются, пока бот запущен. Если бот выключен — "
            "ответ сохранится и уйдёт автоматически, как только вы запустите бота.")

    # ШАГ 8
    step_heading(pdf, 8, "Берегите аккаунты от блокировок")
    para(pdf, "Система уже защищает аккаунты автоматически, но многое зависит и от того, как вы их используете.")
    bullet(pdf, "Распределяйте аккаунты по разным приложениям (см. шаг 2).")
    bullet(pdf, "Не подключайте много новых аккаунтов с одного интернета (IP) за короткое время.")
    bullet(pdf, "Оставляйте человеческие паузы между ответами и не шлите всем один и тот же текст — используйте случайные числа {от-до}.")
    bullet(pdf, "Лучше небольшой пул «живых», прогретых аккаунтов с историей, чем много новых пустых.")
    callout(pdf, "danger",
            "Если в журнале появилось «PeerFlood» или «Флуд-контроль» — Telegram временно ограничил "
            "аккаунт. Дайте ему отдохнуть минимум сутки и не отправляйте с него сообщения.",
            title="АККАУНТ ОГРАНИЧЕН")

    # ШАГ 9
    step_heading(pdf, 9, "Если что-то пошло не так")
    bullet(pdf, "Код при подключении не приходит  →  войдите по QR-коду (шаг 3).")
    bullet(pdf, "Бот включён, но не отвечает  →  проверьте, запущен ли фоновый процесс бота (спросите администратора; в Docker это контейнер «bot»).")
    bullet(pdf, "Аккаунт не отвечает в группе  →  убедитесь, что он добавлен в участники и состоит в чате Telegram.")
    bullet(pdf, "Сообщение «Не заданы API ID / API Hash»  →  добавьте «главный аккаунт» в панели или проверьте файл .env.")
    callout(pdf, "tip",
            "Общее правило: если аккаунт «отвалился» — откройте его карточку, посмотрите статус и поле "
            "с последней ошибкой, при необходимости нажмите «Переподключить».")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Инструкция-по-панели.pdf")
    out = os.path.abspath(out)
    pdf.output(out)
    print("PDF saved:", out, "| pages:", pdf.page_no())


if __name__ == "__main__":
    build()
