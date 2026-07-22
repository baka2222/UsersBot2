"""Формы для пошаговой авторизации Telegram-аккаунта в админ-панели."""
from django import forms


class PhoneForm(forms.Form):
    phone = forms.CharField(
        label="Номер телефона",
        max_length=32,
        help_text="В международном формате, например +79991234567",
        widget=forms.TextInput(attrs={"placeholder": "+79991234567", "autofocus": "autofocus"}),
    )


class CodeForm(forms.Form):
    code = forms.CharField(
        label="Код подтверждения из Telegram",
        max_length=16,
        widget=forms.TextInput(attrs={"placeholder": "12345", "autofocus": "autofocus"}),
    )
    password = forms.CharField(
        label="Облачный пароль (2FA)",
        required=False,
        help_text="Заполните только если на аккаунте включена двухэтапная проверка.",
        widget=forms.PasswordInput(render_value=False),
    )
