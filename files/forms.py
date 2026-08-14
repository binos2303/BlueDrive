from django import forms
from django.core.exceptions import ValidationError

from folders.models import Folder

from .models import File
from .validators import (
    MAX_UPLOAD_SIZE,
    calculate_sha256,
    detect_mime_type,
    validate_client_mime_type,
    validate_filename,
)
from pathlib import PurePath

from .validators import validate_filename

class FileUploadForm(forms.ModelForm):

    class Meta:
        model = File
        fields = ["file_path", "folder"]

        widgets = {
            "file_path": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "folder": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user is not None:
            self.fields["folder"].queryset = Folder.objects.filter(
                owner=user
            ).order_by("folder_name")

        self.fields["folder"].required = False
        self.fields["folder"].empty_label = "My Drive"

    def clean_file_path(self):
        uploaded_file = self.cleaned_data["file_path"]

        if uploaded_file.size > MAX_UPLOAD_SIZE:
            raise ValidationError(
                "File size must not exceed 100 MB."
            )

        extension = validate_filename(uploaded_file.name)

        detected_mime_type = detect_mime_type(
            uploaded_file,
            extension,
        )

        validate_client_mime_type(
            uploaded_file.content_type,
            extension,
            detected_mime_type,
        )

        # Hash plaintext trước encryption ở bước sau.
        self.detected_mime_type = detected_mime_type
        self.sha256 = calculate_sha256(uploaded_file)

        return uploaded_file


class FileRenameForm(forms.ModelForm):
    """Chỉ đổi tên hiển thị; ciphertext trên storage không cần đổi tên."""

    class Meta:
        model = File
        fields = ["file_name"]

        widgets = {
            "file_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "autocomplete": "off",
                    "maxlength": 255,
                }
            ),
        }

    def clean_file_name(self):
        new_name = self.cleaned_data["file_name"]

        # Dùng cùng policy an toàn với lúc upload.
        new_extension = validate_filename(new_name)

        # Không đổi extension vì nội dung đã được validate/mã hóa từ lúc upload.
        old_extension = PurePath(
            self.instance.file_name
        ).suffix.lower()

        if new_extension != old_extension:
            raise ValidationError(
                "Changing the file extension is not allowed."
            )

        return new_name


class FileMoveForm(forms.ModelForm):
    """Di chuyển file sang folder thuộc chính user hoặc về My Drive."""

    class Meta:
        model = File
        fields = ["folder"]

        widgets = {
            "folder": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["folder"].queryset = Folder.objects.filter(
            owner=user
        ).order_by("folder_name")

        self.fields["folder"].required = False
        self.fields["folder"].empty_label = "My Drive"