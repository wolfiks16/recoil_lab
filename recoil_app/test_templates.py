"""Шаблоны: все компилируются (подключены нужные теги/фильтры) и основные списки открываются."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import BrakeCatalog


class TemplatesCompileTests(SimpleTestCase):
    def test_all_templates_compile(self):
        root = Path(settings.BASE_DIR) / "templates"
        names = [p.relative_to(root).as_posix() for p in root.rglob("*.html")]
        self.assertTrue(names)
        for name in names:
            with self.subTest(template=name):
                get_template(name)   # TemplateSyntaxError, если фильтр/тег не подключён


class ListPagesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("lists_user", "l@example.com", "pw")
        self.client.force_login(self.user)

    def test_catalog_list_renders_with_plural(self):
        for k in range(3):
            BrakeCatalog.objects.create(name=f"cat_{k}", model_type="parametric", n=16, bz=0.83)
        response = self.client.get(reverse("catalog_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3 тормоза")

    def test_workspace_and_results_render(self):
        for url in (reverse("dashboard"), reverse("results"), reverse("compare")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
