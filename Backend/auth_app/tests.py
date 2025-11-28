# test_sendgrid.py
from django.test import TestCase
from services.twofactor_service import TwoFactorService
from users_app.models import User

class SendGridTest(TestCase):
    def test_sendgrid_email(self):
        user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            password='testpass123'
        )
        success = TwoFactorService.send_otp_email(user, '123456')
        self.assertTrue(success)