from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dbms-lab/", include("dbms_lab.urls")),
    path("", include("sports.urls")),
]
