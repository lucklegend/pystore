from django.urls import path

from .views import NavigationView, ResolvePageView

urlpatterns = [
    path("pages/resolve/", ResolvePageView.as_view(), name="cms-page-resolve"),
    path("navigation/", NavigationView.as_view(), name="cms-navigation"),
]
