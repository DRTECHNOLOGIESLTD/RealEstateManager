# services.py - Minimal imports version
from .models import TwoFactorAuth
from django.utils import timezone
from datetime import timedelta
import random
import pyotp
from django.core.mail import send_mail
import requests
from django.conf import settings


class TwoFactorService:
    
    @staticmethod
    def generate_otp(user, method):
        """
        Generate OTP based on the selected method
        """
        # Invalidate any previous unused OTPs for security
        TwoFactorAuth.objects.filter(
            user=user, 
            is_used=False,
            expires_at__gt=timezone.now()
        ).update(is_used=True)
        
        if method == 'app':
            # Time-based OTP for authenticator apps
            secret = pyotp.random_base32()  # Generate random secret
            totp = pyotp.TOTP(secret)
            otp = totp.now()  # Generate current time-based code
        else:
            # Random 6-digit OTP for email/SMS
            otp = str(random.randint(100000, 999999))
            secret = None
        
        # Create OTP record in database
        two_fa = TwoFactorAuth.objects.create(
            user=user,
            otp=otp,
            secret_key=secret,
            expires_at=timezone.now() + timedelta(minutes=10)  # 10-minute expiry
        )
        
        return two_fa
    


    @staticmethod
    def send_otp_email(user, otp):
        """
        Send OTP to user email using Resend API
        """
        subject = "Your Verification Code"
        html = f"""
        <p>Hello {user.first_name},</p>
        <p>Your verification code is: <strong>{otp}</strong></p>
        <p>This code will expire in 10 minutes.</p>
        <p>If you didn't request this code, please ignore this email.</p>
        <p>Best regards,<br/>Real Estate Team</p>
        """

        data = {
            "from": settings.RESEND_FROM_EMAIL,  # Must be a verified sender
            "to": [user.email],
            "subject": subject,
            "html": html
        }

        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post("https://api.resend.com/emails", json=data, headers=headers)
            response.raise_for_status()
            return True  # Email sent successfully
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err} - {response.text}")
            return False
        except requests.exceptions.RequestException as err:
            print(f"Request exception: {err}")
            return False
    
    @staticmethod
    def send_otp_sms(user, otp):
        """
        Send OTP via SMS (Twilio example)
        """
        # This would integrate with Twilio, AWS SNS, etc.
        # Example with Twilio:
        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            message = client.messages.create(
                body=f'Your verification code is: {otp}. Valid for 10 minutes.',
                from_=settings.TWILIO_PHONE_NUMBER,
                to=user.phone
            )
            return True
        except Exception as e:
            logger.error(f"SMS sending failed: {e}")
            return False