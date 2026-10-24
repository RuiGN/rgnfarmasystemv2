from django.urls import path

from accounts.views import EmailLogoutView, UsernameLoginView


app_name = 'accounts'

urlpatterns = [
    path('login/', UsernameLoginView.as_view(), name='login'),
    path('logout/', EmailLogoutView.as_view(), name='logout'),
]
