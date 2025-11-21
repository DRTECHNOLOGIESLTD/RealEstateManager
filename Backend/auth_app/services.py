# services.py - Minimal imports version
from .models import TwoFactorAuth
from django.utils import timezone
from datetime import timedelta
import random
import pyotp
from django.core.mail import send_mail
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
        Send OTP via email
        """
        subject = 'Your Verification Code'
        message = f'''
        Hello {user.first_name},
        
        Your verification code is: {otp}
        
        This code will expire in 10 minutes.
        
        If you didn't request this code, please ignore this email.
        
        Best regards,
        Real Estate Team
        '''
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    
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