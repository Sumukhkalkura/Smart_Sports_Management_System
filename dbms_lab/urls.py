from django.urls import path

from . import views

urlpatterns = [
    path("", views.lab_home, name="lab_home"),
    path("tables/<str:table>/", views.table_detail, name="lab_table"),
    path("queries/", views.query_list, name="lab_queries"),
    path("queries/<slug:slug>/", views.query_detail, name="lab_query"),
    path("queries/<slug:slug>/sandbox/", views.sandbox_run, name="lab_sandbox"),
    path("editor/", views.editor, name="lab_editor"),
]
