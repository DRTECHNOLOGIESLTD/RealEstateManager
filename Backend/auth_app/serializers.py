# serializers.py
from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
import pyotp
import random
from .models import TwoFactorAuth

class TwoFactorSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=['email', 'sms', 'app'])
    
class VerifyOTPSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=6, min_length=6)
    email = serializers.EmailField()

