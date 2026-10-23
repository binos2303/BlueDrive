"""Read-only, platform-admin-only API. No account mutations are exposed."""
from django.contrib.auth import get_user_model
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAdminUser])
def admin_access_view(request):
    user = request.user
    return Response({"allowed": True, "username": user.get_username(), "email": user.email})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAdminUser])
def admin_users_view(request):
    query = str(request.query_params.get("q", "")).strip()[:100]
    users = get_user_model().objects.all().order_by("pk")
    if query:
        from django.db.models import Q
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    count = users.count()
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    per_page = 20
    results = users[(page - 1) * per_page:page * per_page]
    return Response({"count": count, "page": page, "page_size": per_page, "results": [
        {"id": user.pk, "username": user.get_username(), "email": user.email,
         "is_active": user.is_active, "is_staff": user.is_staff,
         "last_login": user.last_login.isoformat() if user.last_login else None}
        for user in results
    ]})
