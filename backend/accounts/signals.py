from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.services import get_personal_tenant


@receiver(post_save, sender=get_user_model())
def create_personal_tenant_for_new_user(sender, instance, created, **kwargs):
    if created:
        get_personal_tenant(instance)
