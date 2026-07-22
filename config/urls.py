from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("nested_admin/", include("nested_admin.urls")),
    path("admin/", admin.site.urls),
]
