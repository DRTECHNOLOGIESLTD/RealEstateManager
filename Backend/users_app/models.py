from django.db import models
from django.contrib.auth.models import AbstractUser
# Create your models here.
# models.py - Enhanced User Model
class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('agent', 'Agent'),
        ('owner', 'Owner'),
        ('tenant', 'Tenant'),
    ]
    
    # Custom fields for our real estate app
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=15, blank=True)
    
    # 2FA Specific Fields
    is_2fa_enabled = models.BooleanField(default=False)
    two_factor_method = models.CharField(
        max_length=10, 
        choices=[
            ('email', 'Email'), 
            ('sms', 'SMS'), 
            ('app', 'Authenticator App')
        ],
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Fix reverse accessor clashes with auth.User
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='users_app_user_groups',
        blank=True,
        help_text='The groups this user belongs to.'
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='users_app_user_permissions',
        blank=True,
        help_text='Specific permissions for this user.'
    )

    def enable_2fa(self, method):
        """Enable 2FA for user"""
        self.is_2fa_enabled = True
        self.two_factor_method = method
        self.save()

    def disable_2fa(self):
        """Disable 2FA for user"""
        self.is_2fa_enabled = False
        self.two_factor_method = None
        self.save()