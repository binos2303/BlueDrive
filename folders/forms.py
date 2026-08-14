from django import forms

from .models import Folder


class FolderCreateForm(forms.ModelForm):

    class Meta:
        model = Folder
        fields = ["folder_name", "parent"]

        widgets = {
            "folder_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Folder name",
                    "autocomplete": "off",
                }
            ),
            "parent": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        parent=None,
        **kwargs
    ):

        super().__init__(*args, **kwargs)

        if user is not None:

            self.fields["parent"].queryset = Folder.objects.filter(
                owner=user
            ).order_by("folder_name")

        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "My Drive"

        if parent is not None:

            self.fields["parent"].initial = parent.id