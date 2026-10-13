from rest_framework import serializers

from folders.models import Folder


class FolderMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = Folder
        fields = (
            "id",
            "folder_name",
            "parent",
            "created_at",
            "updated_at",
            "deleted_at",
        )
        read_only_fields = fields
