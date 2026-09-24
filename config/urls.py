from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("nested_admin/", include("nested_admin.urls")),
    path("admin/", admin.site.urls),
]

# В production /media/ отдаёт Nginx; это нужно только для локального запуска
# без Docker, чтобы загруженные изображения тоже можно было увидеть в панели.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
