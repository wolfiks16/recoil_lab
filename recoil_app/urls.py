from django.urls import path
from . import views

urlpatterns = [
    path("", views.index_view, name="index"),
    path("run/<int:run_id>/", views.run_detail_view, name="run_detail"),
    path("run/<int:run_id>/delete/", views.delete_run_view, name="delete_run"),
    path("compare/", views.compare_view, name="compare"),
]