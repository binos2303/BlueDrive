from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect

from .forms import RegisterForm


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
    logout(request)

    messages.success(
        request,
        "Bạn đã đăng xuất."
    )

    return redirect("login")