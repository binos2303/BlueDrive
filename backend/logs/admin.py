from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "description")
    list_filter = ("action", "created_at")
    search_fields = ("user__username", "description")
    ordering = ("-created_at",)

    # ============================================
    # Activity Log chỉ được xem
    # ============================================

    def get_readonly_fields(self, request, obj=None):
        return [
            field.name
            for field in self.model._meta.fields
        ]

    # ============================================
    # Không cho Admin tạo log thủ công
    # ============================================

    def has_add_permission(self, request):
        return False

    # ============================================
    # Không cho Admin xóa log
    # ============================================

    def has_delete_permission(self, request, obj=None):
        return False

    # ============================================
    # Cho phép xem log
    # ============================================

    def has_view_permission(self, request, obj=None):
        return True