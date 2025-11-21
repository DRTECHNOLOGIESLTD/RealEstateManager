from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from users_app.models import User
# Import from your app
from .models import TwoFactorAuth
from .serializers import VerifyOTPSerializer
from users_app.serializers import UserSerializer
from .services import TwoFactorService
# Create your views here.
# views.py - Login Endpoint

#{"email":"solomonokuneye1@gmail.com","password":"test2345"}
@api_view(['POST'])
@permission_classes([])  # No authentication required for login
def login_with_2fa(request):
    """
    Step 1: User provides email and password
    """
    email = request.data.get('email')
    password = request.data.get('password')
    
    # Authenticate user credentials using email
    try:
        user = User.objects.get(email=email)
        if not user.check_password(password):
            user = None
    except User.DoesNotExist:
        user = None
    
    if not user:
        return Response(
            {'error': 'Invalid credentials'}, 
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    # Check if 2FA is enabled for this user
    if not user.is_2fa_enabled:
        # If 2FA is disabled, return tokens immediately
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })
    
    # If 2FA is enabled, proceed with OTP generation
    two_fa = TwoFactorService.generate_otp(user, user.two_factor_method)
    
    # Send OTP via selected method
    if user.two_factor_method == 'email':
        TwoFactorService.send_otp_email(user, two_fa.otp)
    elif user.two_factor_method == 'sms':
        TwoFactorService.send_otp_sms(user, two_fa.otp)
    # For authenticator app, OTP is generated client-side
    
    return Response({
        'message': f'OTP sent to your {user.two_factor_method}',
        'requires_2fa': True,
        'email': user.email  # Return email for OTP verification
    })
    
# views.py - OTP Verification Endpoint
@api_view(['POST'])
@permission_classes([])
def verify_2fa(request):
    """
    Step 3: User submits OTP for verification
    """
    serializer = VerifyOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=serializer.validated_data['email'])
    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Verify the OTP
    is_valid, message = TwoFactorService.verify_otp(
        user, 
        serializer.validated_data['otp']
    )
    
    if is_valid:
        # OTP is valid, generate JWT tokens
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })
    else:
        return Response(
            {'error': message}, 
            status=status.HTTP_400_BAD_REQUEST
        )