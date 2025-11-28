from django.urls import path
from . import views


urlpatterns = [
    path('login/', views.login_with_2fa, name='login'),
    path('test_resend/', views.test_resend, name='test_resend'),
]
