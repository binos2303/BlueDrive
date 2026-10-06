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
                    "maxlength": 255,
                }
            ),
            "parent": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Folder.objects.filter(
            owner=user,
            deleted_at__isnull=True,
        ).order_by("folder_name") if user is not None else Folder.objects.none()
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "My Drive"
        if parent is not None:
            self.fields["parent"].initial = parent.id

    def clean_folder_name(self):
        name = self.cleaned_data["folder_name"].strip()
        if not name:
            raise forms.ValidationError("Folder name cannot be empty.")
        return name
