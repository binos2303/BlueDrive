from django import forms
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect

from .forms import RegisterForm
from logs.models import ActivityLog
from logs.services import log_action


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()

            login(request, user)

            messages.success(
                request,
                "Tạo tài khoản thành công."
            )

            return redirect("dashboard")

    else:
        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form}
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            login(request, user)
            log_action(user, ActivityLog.Action.LOGIN, "Successful login")

            if user.is_staff:
                return redirect("admin:index")

            return redirect("dashboard")

        messages.error(
            request,
            "Username hoặc password không chính xác."
        )

    return render(
        request,
        "accounts/login.html"
    )


@login_required
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
