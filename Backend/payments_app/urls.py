from django.urls import path
from .views import (
    initiate_land_payment,
    verify_land_payment,
    get_installment_payment_schedule,
    pay_installment,
    payment_history,
)

app_name = 'payments_app'  
urlpatterns = [
    path('land/initiate/<uuid:land_id>/', initiate_land_payment, name='initiate-land-payment'),
    path('land/verify/<str:payment_reference>/', verify_land_payment, name='verify-land-payment'),
    path('land/schedule/<uuid:purchase_id>/', get_installment_payment_schedule, name='land-payment-schedule'),
    path('land/installment/<uuid:purchase_id>/<int:installment_number>/', pay_installment, name='pay-installment'),
    path('history/', payment_history, name='payment-history'),
]