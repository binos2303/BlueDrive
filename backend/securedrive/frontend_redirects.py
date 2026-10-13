from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseRedirect


def redirect_to_frontend(path, query=None):
    """Redirect a legacy Django page route to its Next.js page."""
    frontend_url = settings.NEXTJS_FRONTEND_URL
    if not frontend_url:
        raise ImproperlyConfigured(
            "NEXTJS_FRONTEND_URL must be configured for frontend redirects."
        )

    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Frontend redirect paths must be local absolute paths.")

    target = f"{frontend_url}{path}"
    if query:
        target = f"{target}?{urlencode(query, doseq=True)}"
    return HttpResponseRedirect(target)


def redirect_admin(request):
    return redirect_to_frontend("/admin")


def redirect_admin_subpath(request, subpath):
    safe_subpath = quote(subpath.strip("/"), safe="/")
    target_path = f"/admin/{safe_subpath}" if safe_subpath else "/admin"
    return redirect_to_frontend(target_path)
