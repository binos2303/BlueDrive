from django import forms
from django.contrib.auth.models import User

from .models import Share


class FileShareForm(forms.Form):
    """Form cấp quyền theo username, không nhận user ID từ browser."""

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "placeholder": "Recipient username",
            }
        ),
    )

    permission = forms.ChoiceField(
        choices=Share.Permission.choices,
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        try:
            receiver = User.objects.get(username=username)
        except User.DoesNotExist:
            raise forms.ValidationError(
                "Recipient account was not found."
            )

        if receiver == self.owner:
            raise forms.ValidationError(
                "You cannot share a file with yourself."
            )

        return receiver