from django import forms
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from urllib.parse import urlencode, urlsplit

from logs.models import ActivityLog
from logs.services import log_action


def _next_auth_redirect(request, path):
    frontend_url = settings.NEXTJS_FRONTEND_URL
    if not frontend_url:
        raise ImproperlyConfigured(
            "NEXTJS_FRONTEND_URL must be configured for legacy auth routes."
        )

    query = {}
    next_path = request.GET.get("next", "")
    parsed_next = urlsplit(next_path)
    if (
        next_path.startswith("/")
        and not next_path.startswith("//")
        and not parsed_next.netloc
        and not parsed_next.scheme
        and "\\" not in next_path
        and not any(ord(char) < 32 or ord(char) == 127 for char in next_path)
        and not any(token in next_path.lower() for token in ("%2f", "%5c"))
    ):
        query["next"] = next_path

    target = f"{frontend_url}{path}"
    if query:
        target = f"{target}?{urlencode(query)}"
    return HttpResponseRedirect(target)


def register_view(request):
    return _next_auth_redirect(request, "/register")


def login_view(request):
    return _next_auth_redirect(request, "/login")


@login_required
@require_POST
def logout_view(request):
    user = request.user
    log_action(user, ActivityLog.Action.LOGOUT, "User logout")
    logout(request)

    messages.success(
        request,
        "Bạn đã đăng xuất."
    )

    return redirect("login")

class ProfileEmailForm(forms.Form):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Email",
        }),
    )


def _configure_password_form(form):
    labels = {
        "old_password": "Mật khẩu hiện tại",
        "new_password1": "Mật khẩu mới",
        "new_password2": "Xác nhận mật khẩu mới",
    }
    placeholders = {
        "old_password": "Nhập mật khẩu hiện tại",
        "new_password1": "Nhập mật khẩu mới",
        "new_password2": "Nhập lại mật khẩu mới",
    }
    for name, field in form.fields.items():
        field.label = labels.get(name, field.label)
        field.widget.attrs.update({
            "class": "form-control profile-input",
            "placeholder": placeholders.get(name, ""),
            "autocomplete": "current-password" if name == "old_password" else "new-password",
        })



@login_required
def profile_view(request):
    email_form = ProfileEmailForm(initial={"email": request.user.email})
    password_form = PasswordChangeForm(request.user)
    _configure_password_form(password_form)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "update_email":
            email_form = ProfileEmailForm(request.POST)
            if email_form.is_valid():
                request.user.email = email_form.cleaned_data["email"]
                request.user.save(update_fields=["email"])
                messages.success(request, "Đã cập nhật email thành công.")
                return redirect("profile")

        elif action == "change_password":
            password_form = PasswordChangeForm(request.user, request.POST)
            _configure_password_form(password_form)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Đã đổi mật khẩu thành công.")
                return redirect("profile")

    return render(
        request,
        "accounts/profile.html",
        {
            "email_form": email_form,
            "password_form": password_form,
        },
    )
