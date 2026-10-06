from django import forms
from django.contrib.auth.models import User
from django.db.models import Q

from .models import Share


class FileShareForm(forms.Form):
    """
    Find a recipient by username or email and select
    the permission level for the shared resource.

    Permission defaults to Viewer so existing share requests
    without an explicit permission remain valid.
    """

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "placeholder": "Enter username or email",
            }
        ),
    )

    permission = forms.ChoiceField(
        choices=Share.Permission.choices,
        required=False,
        initial=Share.Permission.VIEWER,
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        matches = User.objects.filter(
            Q(username__iexact=username)
            | Q(email__iexact=username)
        ).distinct()

        if matches.count() == 0:
            raise forms.ValidationError(
                "Recipient account was not found."
            )

        if matches.count() > 1:
            raise forms.ValidationError(
                "This email is linked to multiple accounts. "
                "Use the username instead."
            )

        receiver = matches.first()

        if receiver == self.owner:
            raise forms.ValidationError(
                "You cannot share a file with yourself."
            )

        return receiver

    def clean_permission(self):
        permission = self.cleaned_data.get("permission")

        if not permission:
            return Share.Permission.VIEWER

        valid_permissions = {
            value
            for value, _label in Share.Permission.choices
        }

        if permission not in valid_permissions:
            raise forms.ValidationError(
                "Invalid permission."
            )

        return permission