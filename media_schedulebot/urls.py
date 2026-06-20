from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("favicon.ico", lambda request: HttpResponse(status=204)),
    path("", include("scheduler_app.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
