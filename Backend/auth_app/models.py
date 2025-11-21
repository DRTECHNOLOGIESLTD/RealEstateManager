from django.db import models
from users_app.models import User
from django.utils import timezone
# Create your models here.
class TwoFactorAuth(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp = models.CharField(max_length=6)  # 6-digit code
    secret_key = models.CharField(max_length=32, null=True, blank=True)  # For TOTP (Time-based OTP)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()  # OTP expiration time
    is_used = models.BooleanField(default=False)  # Prevents reuse
    attempts = models.IntegerField(default=0)  # Track failed attempts
    
    class Meta:
        indexes = [
            # Optimized query for OTP validation
            models.Index(fields=['user', 'is_used', 'expires_at']),
        ]

    def is_expired(self):
        """Check if OTP has expired"""
        return timezone.now() > self.expires_at

    def increment_attempts(self):
        """Increment failed attempt counter"""
        self.attempts += 1
        self.save()

    def mark_used(self):
        """Mark OTP as used"""
        self.is_used = True
        self.save()