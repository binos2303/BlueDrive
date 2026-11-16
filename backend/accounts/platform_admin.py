"""Centralized authorization for dedicated BlueDrive platform administrators.

A Django staff Superuser is the bootstrap SUPER ADMIN, not a regular admin.
A non-superuser requires an explicit ACTIVE PlatformAdminIdentity.
"""
from django.core.exceptions import ObjectDoesNotExist


def platform_role(user):
    if not user or not user.is_authenticated or not user.is_active or not user.is_staff:
        return None
    if user.is_superuser:
        return "super_admin"
    try:
        identity = user.platform_admin_identity
    except ObjectDoesNotExist:
        return None
    return "platform_admin" if identity.status == "active" else None


def is_platform_admin(user):
    return platform_role(user) is not None


def is_platform_super_admin(user):
    return platform_role(user) == "super_admin"
