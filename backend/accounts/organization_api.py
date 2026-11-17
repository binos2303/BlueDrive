"""API quản lý identity Organization; quyền hiện hành được kiểm lại trong transaction."""
import logging
from smtplib import SMTPException

from django.db import IntegrityError
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .api_views import require_csrf
from .organization_provisioning import (
    ProvisioningError, accept_invitation, create_employee, create_organization,
    member_capabilities, member_data, reinvite,
)

logger = logging.getLogger(__name__)


def _call(operation, *, creation=False):
    try:
        result = operation()
    except ProvisioningError as error:
        data = {'detail': error.detail}
        if error.fields:
            data['fieldErrors'] = error.fields
        return Response(data, status=error.status)
    except IntegrityError:
        return Response({'detail': 'Organization identity or request key already exists.'}, status=409)
    except (SMTPException, OSError, ConnectionError):
        logger.warning('Organization invitation delivery failed; no credential or token logged.')
        return Response({'detail': 'Could not deliver the invitation. Retry after checking email delivery.'}, status=503)
    if creation:
        data, replay = result
        return Response(data, status=200 if replay else 201)
    return Response(result)


def create_organization_response(request):
    return _call(lambda: create_organization(request.user, request.data, request.headers.get('Idempotency-Key')), creation=True)


def create_employee_response(request, tenant_id):
    return _call(lambda: create_employee(request.user, tenant_id, request.data, request.headers.get('Idempotency-Key')), creation=True)


@require_csrf
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def accept_organization_invitation_view(request):
    return _call(lambda: accept_invitation(request.data))


@require_csrf
@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def reinvite_organization_member_view(request, tenant_id, membership_id):
    return _call(lambda: reinvite(request.user, tenant_id, request.data, membership_id=membership_id))


@require_csrf
@api_view(['POST'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def reinvite_organization_administrator_view(request, tenant_id):
    return _call(lambda: reinvite(request.user, tenant_id, request.data, initial_admin=True))
