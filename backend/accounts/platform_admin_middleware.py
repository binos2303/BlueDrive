from django.http import JsonResponse
from .platform_admin import is_platform_admin, is_platform_super_admin
from .session_tracking import record_authenticated_session


class DedicatedPlatformAdminMiddleware:
    """Block dedicated admins from non-admin product APIs (not just the UI).

    This runs after AuthenticationMiddleware and intentionally does not alter
    normal user permissions or Django's own /admin/ routes.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if is_platform_admin(request.user):
            # Only the bootstrap Super Admin may enter Django's /admin/ site;
            # ordinary Platform Admins use the Next.js admin console instead.
            if path.startswith('/admin/') and not is_platform_super_admin(request.user):
                return JsonResponse({'detail': 'Django admin access is restricted.'}, status=403)
            # Dedicated admins may only call their admin APIs, inspect their
            # session, or log out. CSRF remains available for sign-in flows.
            allowed = (
                path.startswith('/accounts/api/admin/')
                or path.startswith('/accounts/api/me/security/')
                or path in ('/accounts/api/me/', '/accounts/api/logout/',
                            '/accounts/api/csrf/', '/accounts/api/login/')
                or path.startswith('/admin/')
            )
            if not allowed:
                return JsonResponse({'detail': 'Platform administrators cannot use user/Drive APIs.'}, status=403)
        response = self.get_response(request)
        record_authenticated_session(request)
        return response