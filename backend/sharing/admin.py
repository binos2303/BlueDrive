from django.contrib import admin

from .models import Share


@admin.register(Share)
class ShareAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "shared_item_name",
        "receiver",
        "created_at",
    )

    list_filter = ("created_at",)

    search_fields = (
        "owner__username",
        "receiver__username",
        "file__file_name",
        "folder__folder_name",
    )

    readonly_fields = (
        "owner",
        "receiver",
        "file",
        "folder",
        "created_at",
    )

    def shared_item_name(self, obj):
        if obj.file_id:
            return obj.file.file_name
        if obj.folder_id:
            return obj.folder.folder_name
        return "-"

    shared_item_name.short_description = "Shared item"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
