"""View'хи аутентификации: регистрация и управление пользователями.

Login/logout — стандартные `LoginView` / `LogoutView` из django.contrib.auth,
включены в urls.py. Здесь только то, чего нет «из коробки».
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import UserProfileEditForm, UserRegistrationForm
from ..models import UserProfile
from ..services.permissions import can_manage_users

User = get_user_model()


def register_view(request):
    """Открытая регистрация. После сабмита сразу логиним пользователя.

    Сигнал `post_save` на User создаёт UserProfile с ролью `engineer` по
    умолчанию (для не-суперпользователей). Повысить роль может только admin
    через страницу `/users/`.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request,
                f"Аккаунт «{user.username}» создан. Роль: Инженер.",
            )
            return redirect("dashboard")
    else:
        form = UserRegistrationForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
def profile_view(request):
    """Личный кабинет: имя/фамилия/дата рождения + выбор аватара.

    Роль показывается, но менять её здесь нельзя — это делает только admin
    через `/users/`. Кнопка «Выйти» отрабатывает стандартным `LogoutView`.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = UserProfileEditForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Профиль обновлён.")
            return redirect("profile")
    else:
        form = UserProfileEditForm(user=request.user)

    # Готовый список аватаров для шаблона: чистое разделение эмодзи и подписи —
    # никаких юникод-слайсингов в шаблоне.
    avatar_options = [
        {
            "key":   key,
            "emoji": UserProfile.AVATAR_EMOJI.get(key, "🦊"),
            "name":  label.split(" ", 1)[1] if " " in label else label,
        }
        for key, label in UserProfile.AVATAR_CHOICES
    ]
    # Текущий выбранный аватар: если форма уже с ошибками — берём из POST,
    # иначе — из профиля. Это чтобы при невалидной отправке выбор не «прыгал».
    selected = form["avatar_key"].value() or profile.avatar_key

    return render(request, "recoil_app/profile.html", {
        "form": form,
        "profile": profile,
        "avatar_options": avatar_options,
        "selected_avatar_key": selected,
    })


@login_required
@user_passes_test(can_manage_users)
def users_list_view(request):
    """Список пользователей с их ролями (только admin)."""
    users = (
        User.objects.select_related("profile")
        .order_by("-is_superuser", "username")
    )
    return render(request, "recoil_app/users_list.html", {
        "users_list": users,
        "role_choices": UserProfile.ROLE_CHOICES,
    })


@login_required
@require_POST
def users_set_role_view(request, user_id: int):
    """POST endpoint: смена роли пользователя. Только admin."""
    if not can_manage_users(request.user):
        return HttpResponseForbidden("Только администратор может менять роли.")

    target_user = get_object_or_404(User, pk=user_id)

    # Защита от самопонижения единственного админа в системе.
    if target_user.id == request.user.id:
        messages.warning(
            request,
            "Нельзя менять собственную роль через этот интерфейс — это может "
            "оставить систему без администраторов. Используйте django-admin.",
        )
        return redirect("users_list")

    new_role = request.POST.get("role", "").strip()
    valid_roles = {value for value, _ in UserProfile.ROLE_CHOICES}
    if new_role not in valid_roles:
        messages.error(request, f"Недопустимая роль: {new_role!r}.")
        return redirect("users_list")

    profile, _created = UserProfile.objects.get_or_create(user=target_user)
    old_role = profile.role
    profile.role = new_role
    profile.save(update_fields=["role", "updated_at"])
    messages.success(
        request,
        f"{target_user.username}: роль {old_role} → {new_role}.",
    )
    return redirect("users_list")
