from django.db import transaction
from django.utils import timezone

from accounts.models import Membership, QuotaAccount, Tenant
from files.models import QuotaReservation, UploadSession


class QuotaError(Exception):
    """Base exception for upload quota operations."""


class QuotaExceeded(QuotaError):
    pass


class QuotaStateError(QuotaError):
    pass


def _get_active_membership(upload, user):
    if not user or not user.is_authenticated or not user.is_active:
        raise QuotaStateError("An authenticated tenant member is required.")
    if upload.tenant.status != Tenant.Status.ACTIVE:
        raise QuotaStateError("The upload tenant is not active.")

    membership = Membership.objects.filter(
        tenant_id=upload.tenant_id,
        user_id=user.pk,
        status=Membership.Status.ACTIVE,
    ).first()
    if membership is None:
        raise QuotaStateError("The user is not an active member of this tenant.")
    return membership


@transaction.atomic
def reserve_upload_quota(upload_session_id, user):
    upload = (
        UploadSession.objects.select_for_update()
        .select_related("tenant")
        .get(pk=upload_session_id)
    )
    if upload.initiated_by_id != getattr(user, "pk", None):
        raise QuotaStateError("Only the upload initiator can reserve its quota.")

    _get_active_membership(upload, user)
    reservations = list(
        QuotaReservation.objects.select_for_update()
        .filter(upload_session=upload)
        .order_by("quota_account_id")
    )
    if reservations and all(
        reservation.state == QuotaReservation.State.RESERVED
        for reservation in reservations
    ):
        return reservations
    if reservations and all(
        reservation.state == QuotaReservation.State.CONSUMED
        for reservation in reservations
    ):
        return reservations
    if reservations and not all(
        reservation.state == QuotaReservation.State.RELEASED
        for reservation in reservations
    ):
        raise QuotaStateError("The upload has inconsistent quota reservation state.")
    if upload.state not in (
        UploadSession.State.INITIATED,
        UploadSession.State.UPLOADING,
    ):
        raise QuotaStateError("Quota can only be reserved for an active upload.")

    accounts = QuotaAccount.objects.filter(
        tenant_id=upload.tenant_id,
        scope=QuotaAccount.Scope.TENANT,
    )
    if upload.tenant.kind == "business":
        accounts = accounts | QuotaAccount.objects.filter(
            tenant_id=upload.tenant_id,
            user_id=user.pk,
            scope=QuotaAccount.Scope.MEMBER,
        )
    accounts_by_id = {
        account.pk: account
        for account in QuotaAccount.objects.select_for_update()
        .filter(pk__in=accounts.values("pk"))
        .order_by("pk")
    }
    if not accounts_by_id or not any(
        account.scope == QuotaAccount.Scope.TENANT
        for account in accounts_by_id.values()
    ):
        raise QuotaStateError("The tenant quota account is not configured.")
    if upload.tenant.kind == "business" and not any(
        account.scope == QuotaAccount.Scope.MEMBER
        and account.user_id == user.pk
        for account in accounts_by_id.values()
    ):
        raise QuotaStateError("The member has no quota allocation.")

    requested_bytes = upload.expected_size_bytes
    for account in accounts_by_id.values():
        if (
            account.limit_bytes is not None
            and account.used_bytes + account.reserved_bytes + requested_bytes
            > account.limit_bytes
        ):
            raise QuotaExceeded("The upload exceeds the available quota.")

    prior_by_account = {
        reservation.quota_account_id: reservation for reservation in reservations
    }
    result = []
    for account in accounts_by_id.values():
        account.reserved_bytes += requested_bytes
        account.save(update_fields=["reserved_bytes", "updated_at"])
        reservation = prior_by_account.get(account.pk)
        if reservation:
            reservation.reserved_bytes = requested_bytes
            reservation.state = QuotaReservation.State.RESERVED
            reservation.finalized_at = None
            reservation.save(
                update_fields=["reserved_bytes", "state", "finalized_at"]
            )
        else:
            reservation = QuotaReservation.objects.create(
                tenant_id=upload.tenant_id,
                upload_session=upload,
                quota_account=account,
                reserved_bytes=requested_bytes,
                state=QuotaReservation.State.RESERVED,
            )
        result.append(reservation)
    return result


@transaction.atomic
def finalize_upload_quota(
    upload_session_id,
    *,
    completed,
    actual_size_bytes=None,
    actor=None,
):
    upload = UploadSession.objects.select_for_update().get(pk=upload_session_id)
    if actor is not None:
        if upload.initiated_by_id != getattr(actor, "pk", None):
            raise QuotaStateError("Only the upload initiator can finalize its quota.")
        _get_active_membership(upload, actor)
    reservations = list(
        QuotaReservation.objects.select_for_update()
        .filter(upload_session=upload)
        .order_by("quota_account_id")
    )
    if not reservations:
        raise QuotaStateError("The upload has no quota reservation.")

    target_state = (
        QuotaReservation.State.CONSUMED
        if completed
        else QuotaReservation.State.RELEASED
    )
    if all(reservation.state == target_state for reservation in reservations):
        if completed and upload.actual_size_bytes != actual_size_bytes:
            raise QuotaStateError(
                "The upload was already finalized with a different object size."
            )
        return reservations
    if not all(
        reservation.state == QuotaReservation.State.RESERVED
        for reservation in reservations
    ):
        raise QuotaStateError("The upload quota has already been finalized.")
    if completed and (
        actual_size_bytes is None
        or actual_size_bytes < 0
        or any(actual_size_bytes > row.reserved_bytes for row in reservations)
    ):
        raise QuotaStateError("The verified object size exceeds its reservation.")
    if completed:
        if (
            upload.actual_size_bytes is not None
            and upload.actual_size_bytes != actual_size_bytes
        ):
            raise QuotaStateError(
                "The verified object size conflicts with the upload session."
            )
        upload.actual_size_bytes = actual_size_bytes
        upload.save(update_fields=["actual_size_bytes", "updated_at"])

    accounts = {
        account.pk: account
        for account in QuotaAccount.objects.select_for_update()
        .filter(pk__in=[row.quota_account_id for row in reservations])
        .order_by("pk")
    }
    for reservation in reservations:
        account = accounts[reservation.quota_account_id]
        if account.reserved_bytes < reservation.reserved_bytes:
            raise QuotaStateError("The quota reservation counters are inconsistent.")
        account.reserved_bytes -= reservation.reserved_bytes
        if completed:
            account.used_bytes += actual_size_bytes
        account.save(update_fields=["reserved_bytes", "used_bytes", "updated_at"])
        reservation.state = target_state
        reservation.finalized_at = timezone.now()
        reservation.save(update_fields=["state", "finalized_at"])
    return reservations
