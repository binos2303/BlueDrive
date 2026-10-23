from rest_framework import serializers

from accounts.models import QuotaAccount
from files.models import File, FileVersion, UploadSession


class FileMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = (
            "id",
            "workspace",
            "file_name",
            "file_size",
            "mime_type",
            "folder",
            "created_at",
            "updated_at",
            "deleted_at",
        )
        read_only_fields = fields


class FileVersionMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileVersion
        fields = (
            "id",
            "version_number",
            "state",
            "size_bytes",
            "mime_type",
            "is_current",
            "created_at",
            "verified_at",
            "deleted_at",
        )
        read_only_fields = fields


class UploadSessionStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadSession
        fields = (
            "id",
            "workspace",
            "client_name",
            "expected_size_bytes",
            "received_bytes",
            "actual_size_bytes",
            "state",
            "failure_code",
            "expires_at",
            "created_at",
            "updated_at",
            "completed_at",
        )
        read_only_fields = fields


class QuotaUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotaAccount
        fields = (
            "scope",
            "limit_bytes",
            "used_bytes",
            "reserved_bytes",
            "updated_at",
        )
        read_only_fields = fields
