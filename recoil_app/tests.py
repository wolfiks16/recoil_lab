"""Тесты системы прав доступа (`services.permissions`).

Покрывают 4 роли × своё/чужое × ключевые действия:
    - can_view_run     (12 кейсов)
    - can_delete_run   (12 кейсов)
    - runs_visible_to  (4 кейса)
    - can_edit_catalog (12 кейсов)
    - can_run_calc, can_create_catalog, can_manage_users (per-role)

Не покрывают: вьюхи целиком (это сделают интеграционные тесты позже).
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import BrakeCatalog, CalculationRun, UserProfile
from .services.permissions import (
    can_create_catalog,
    can_delete_catalog,
    can_delete_run,
    can_duplicate_run,
    can_edit_catalog,
    can_manage_users,
    can_run_calc,
    can_view_run,
    runs_visible_to,
    user_role,
)

User = get_user_model()


def _set_role(user: User, role: str) -> None:
    """Хелпер: подменяет роль профиля (сигнал создал по умолчанию engineer).

    Сбрасывает кэш `user.profile`, чтобы дальнейшие обращения к нему через
    related descriptor подтянули свежее значение role.
    """
    UserProfile.objects.update_or_create(user=user, defaults={"role": role})
    # Сброс кеша related-объекта на инстансе user — иначе user.profile вернёт старое.
    fc = getattr(user, "_state", None)
    if fc is not None:
        fc.fields_cache.pop("profile", None)


class PermissionsBaseFixture(TestCase):
    """Общие фикстуры: 1 admin, 1 analyst, 1 engineer, 1 engineer2, 1 anon."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="alice_admin", password="x")
        _set_role(cls.admin, UserProfile.ROLE_ADMIN)
        cls.analyst = User.objects.create_user(username="bob_analyst", password="x")
        _set_role(cls.analyst, UserProfile.ROLE_ANALYST)
        cls.engineer = User.objects.create_user(username="carol_engineer", password="x")
        _set_role(cls.engineer, UserProfile.ROLE_ENGINEER)
        cls.engineer2 = User.objects.create_user(username="dave_engineer", password="x")
        _set_role(cls.engineer2, UserProfile.ROLE_ENGINEER)

        # 4 расчёта — по одному на каждого «нечисто-гостя».
        cls.run_admin = CalculationRun.objects.create(
            name="run_admin", input_file="uploads/x.xlsx",
            mass=1000.0, owner=cls.admin,
        )
        cls.run_analyst = CalculationRun.objects.create(
            name="run_analyst", input_file="uploads/x.xlsx",
            mass=1000.0, owner=cls.analyst,
        )
        cls.run_engineer = CalculationRun.objects.create(
            name="run_engineer", input_file="uploads/x.xlsx",
            mass=1000.0, owner=cls.engineer,
        )
        cls.run_legacy = CalculationRun.objects.create(
            name="run_legacy", input_file="uploads/x.xlsx",
            mass=1000.0, owner=None,
        )

        # 2 записи каталога (своя + чужая для engineer).
        cls.cat_engineer = BrakeCatalog.objects.create(
            name="cat_engineer", model_type="parametric", owner=cls.engineer,
        )
        cls.cat_analyst = BrakeCatalog.objects.create(
            name="cat_analyst", model_type="parametric", owner=cls.analyst,
        )

    def setUp(self):
        # AnonymousUser создаём в каждом тесте — он не сохраняется в БД.
        from django.contrib.auth.models import AnonymousUser
        self.guest = AnonymousUser()


class UserRoleTests(PermissionsBaseFixture):

    def test_role_for_each_user(self):
        self.assertEqual(user_role(self.admin), UserProfile.ROLE_ADMIN)
        self.assertEqual(user_role(self.analyst), UserProfile.ROLE_ANALYST)
        self.assertEqual(user_role(self.engineer), UserProfile.ROLE_ENGINEER)
        self.assertIsNone(user_role(self.guest))

    def test_signal_assigned_admin_to_superuser(self):
        """Сигнал ставит role=admin для is_superuser=True."""
        su = User.objects.create_superuser(username="root", password="x", email="r@x.local")
        self.assertEqual(su.profile.role, UserProfile.ROLE_ADMIN)


class CanViewRunTests(PermissionsBaseFixture):

    def test_admin_sees_everything(self):
        for run in [self.run_admin, self.run_analyst, self.run_engineer, self.run_legacy]:
            self.assertTrue(can_view_run(self.admin, run), f"admin should see {run.name}")

    def test_analyst_sees_everything(self):
        for run in [self.run_admin, self.run_analyst, self.run_engineer, self.run_legacy]:
            self.assertTrue(can_view_run(self.analyst, run), f"analyst should see {run.name}")

    def test_engineer_sees_only_own(self):
        self.assertTrue(can_view_run(self.engineer, self.run_engineer))
        self.assertFalse(can_view_run(self.engineer, self.run_analyst))
        self.assertFalse(can_view_run(self.engineer, self.run_admin))
        self.assertFalse(can_view_run(self.engineer, self.run_legacy))

    def test_guest_sees_nothing(self):
        for run in [self.run_admin, self.run_analyst, self.run_engineer, self.run_legacy]:
            self.assertFalse(can_view_run(self.guest, run), f"guest should NOT see {run.name}")


class CanDeleteRunTests(PermissionsBaseFixture):

    def test_admin_deletes_anything(self):
        for run in [self.run_admin, self.run_analyst, self.run_engineer, self.run_legacy]:
            self.assertTrue(can_delete_run(self.admin, run))

    def test_analyst_deletes_only_own(self):
        self.assertTrue(can_delete_run(self.analyst, self.run_analyst))
        self.assertFalse(can_delete_run(self.analyst, self.run_engineer))
        self.assertFalse(can_delete_run(self.analyst, self.run_admin))
        self.assertFalse(can_delete_run(self.analyst, self.run_legacy))

    def test_engineer_deletes_only_own(self):
        self.assertTrue(can_delete_run(self.engineer, self.run_engineer))
        self.assertFalse(can_delete_run(self.engineer, self.run_analyst))
        self.assertFalse(can_delete_run(self.engineer, self.run_legacy))

    def test_guest_deletes_nothing(self):
        self.assertFalse(can_delete_run(self.guest, self.run_admin))


class RunsVisibleToTests(PermissionsBaseFixture):

    def test_admin_queryset_includes_all(self):
        qs = runs_visible_to(self.admin)
        self.assertEqual(qs.count(), 4)

    def test_analyst_queryset_includes_all(self):
        qs = runs_visible_to(self.analyst)
        self.assertEqual(qs.count(), 4)

    def test_engineer_queryset_only_own(self):
        qs = runs_visible_to(self.engineer)
        names = set(qs.values_list("name", flat=True))
        self.assertEqual(names, {"run_engineer"})

    def test_guest_queryset_empty(self):
        qs = runs_visible_to(self.guest)
        self.assertEqual(qs.count(), 0)


class CanCreateAndRunCalcTests(PermissionsBaseFixture):

    def test_authenticated_can_run(self):
        for user in [self.admin, self.analyst, self.engineer]:
            self.assertTrue(can_run_calc(user))
        self.assertFalse(can_run_calc(self.guest))

    def test_authenticated_can_create_catalog(self):
        for user in [self.admin, self.analyst, self.engineer]:
            self.assertTrue(can_create_catalog(user))
        self.assertFalse(can_create_catalog(self.guest))


class CanEditCatalogTests(PermissionsBaseFixture):

    def test_admin_edits_any_catalog(self):
        self.assertTrue(can_edit_catalog(self.admin, self.cat_engineer))
        self.assertTrue(can_edit_catalog(self.admin, self.cat_analyst))

    def test_analyst_edits_any_catalog(self):
        self.assertTrue(can_edit_catalog(self.analyst, self.cat_engineer))
        self.assertTrue(can_edit_catalog(self.analyst, self.cat_analyst))

    def test_engineer_edits_only_own_catalog(self):
        self.assertTrue(can_edit_catalog(self.engineer, self.cat_engineer))
        self.assertFalse(can_edit_catalog(self.engineer, self.cat_analyst))
        # И другой инженер тоже не может редактировать чужое.
        self.assertFalse(can_edit_catalog(self.engineer2, self.cat_engineer))

    def test_guest_cannot_edit(self):
        self.assertFalse(can_edit_catalog(self.guest, self.cat_engineer))

    def test_can_delete_catalog_mirrors_edit(self):
        # delete = edit по нашей политике
        self.assertEqual(
            can_delete_catalog(self.engineer, self.cat_engineer),
            can_edit_catalog(self.engineer, self.cat_engineer),
        )
        self.assertEqual(
            can_delete_catalog(self.engineer, self.cat_analyst),
            can_edit_catalog(self.engineer, self.cat_analyst),
        )


class CanManageUsersTests(PermissionsBaseFixture):

    def test_only_admin_manages_users(self):
        self.assertTrue(can_manage_users(self.admin))
        self.assertFalse(can_manage_users(self.analyst))
        self.assertFalse(can_manage_users(self.engineer))
        self.assertFalse(can_manage_users(self.guest))


class CanDuplicateRunTests(PermissionsBaseFixture):

    def test_duplicate_follows_view(self):
        """Дублировать можно ровно то, что можно смотреть."""
        for user in [self.admin, self.analyst, self.engineer, self.guest]:
            for run in [self.run_admin, self.run_engineer, self.run_legacy]:
                self.assertEqual(
                    can_duplicate_run(user, run),
                    can_view_run(user, run),
                    f"duplicate≠view for user={user!r}, run={run.name}",
                )


class ProfilePageTests(TestCase):
    """Smoke-тесты страницы /profile/: доступ, GET, POST с сохранением."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="eve_profile", password="x12345pass")
        # Сигнал создаёт profile по умолчанию — роль engineer, avatar fox.

    def test_guest_redirected_to_login(self):
        url = reverse("profile")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_authenticated_get_renders_200(self):
        self.client.login(username="eve_profile", password="x12345pass")
        resp = self.client.get(reverse("profile"))
        self.assertEqual(resp.status_code, 200)
        # На странице должен быть текущий ник, бейдж роли, форма
        self.assertContains(resp, "eve_profile")
        self.assertContains(resp, "Инженер")  # role label
        self.assertContains(resp, "first_name")
        self.assertContains(resp, "avatar_key")

    def test_post_updates_user_and_profile(self):
        self.client.login(username="eve_profile", password="x12345pass")
        resp = self.client.post(reverse("profile"), data={
            "first_name": "Ева",
            "last_name":  "Петрова",
            "birth_date": "1990-05-12",
            "avatar_key": "panda",
        })
        # Успех → редирект обратно на /profile/.
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("profile"))

        user = User.objects.get(pk=self.user.pk)
        self.assertEqual(user.first_name, "Ева")
        self.assertEqual(user.last_name, "Петрова")
        self.assertEqual(user.profile.birth_date, date(1990, 5, 12))
        self.assertEqual(user.profile.avatar_key, "panda")
        self.assertEqual(user.profile.avatar_emoji, "🐼")

    def test_post_invalid_avatar_rerenders_form(self):
        self.client.login(username="eve_profile", password="x12345pass")
        resp = self.client.post(reverse("profile"), data={
            "first_name": "Ева",
            "last_name":  "",
            "birth_date": "",
            "avatar_key": "dragon",  # нет в списке
        })
        # 200 + форма с ошибкой, не 302.
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(pk=self.user.pk)
        # Изменения не сохранились.
        self.assertEqual(user.profile.avatar_key, "fox")

    def test_post_role_not_editable(self):
        """В форме нет поля role — POST с role не повышает права."""
        self.client.login(username="eve_profile", password="x12345pass")
        self.client.post(reverse("profile"), data={
            "first_name": "X",
            "last_name":  "Y",
            "birth_date": "",
            "avatar_key": "cat",
            "role":       "admin",   # попытка хакнуть роль
        })
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual(user.profile.role, UserProfile.ROLE_ENGINEER)


class RegistrationFormTests(TestCase):
    """Smoke-тесты расширенной регистрации с ФИО и датой рождения."""

    def test_get_renders_new_fields(self):
        resp = self.client.get(reverse("register"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="first_name"')
        self.assertContains(resp, 'name="last_name"')
        self.assertContains(resp, 'name="birth_date"')

    def test_post_creates_user_with_full_data(self):
        resp = self.client.post(reverse("register"), data={
            "username":   "fresh_eng",
            "first_name": "Иван",
            "last_name":  "Сидоров",
            "birth_date": "1995-08-22",
            "password1":  "ComplexPass!2026",
            "password2":  "ComplexPass!2026",
        })
        # Успех → авто-логин и редирект на дашборд.
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("dashboard"))

        user = User.objects.get(username="fresh_eng")
        self.assertEqual(user.first_name, "Иван")
        self.assertEqual(user.last_name, "Сидоров")
        self.assertEqual(user.profile.birth_date, date(1995, 8, 22))
        # Дефолтная роль из сигнала.
        self.assertEqual(user.profile.role, UserProfile.ROLE_ENGINEER)

    def test_post_missing_required_fields_rejected(self):
        resp = self.client.post(reverse("register"), data={
            "username":  "noname",
            "password1": "ComplexPass!2026",
            "password2": "ComplexPass!2026",
            # first_name / last_name / birth_date пропущены
        })
        # 200 + ошибки формы.
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="noname").exists())
