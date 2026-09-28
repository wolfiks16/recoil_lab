"""AJAX: фоновые задачи пользователя для индикатора в верхней строке."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..services.background_tasks import running_tasks_for


@require_GET
def background_tasks_view(request):
    return JsonResponse({"tasks": running_tasks_for(request.user)})
