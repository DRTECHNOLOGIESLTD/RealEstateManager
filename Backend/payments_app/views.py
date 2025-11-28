from django.shortcuts import render

# Create your views here.
# payments/views/land_payment_views.py
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.conf import settings
from datetime import timedelta
import logging

from properties_app.models import Land, LandInstallmentPlan, LandReservation
from .models import LandPurchase, LandPayment,PaymentSchedule, PaymentAttempt
from .serializers import (
    LandPaymentInitiationSerializer,
    LandPurchaseSerializer,
    LandPaymentSerializer,
    LandReservationSerializer
)
from services.flutterwave_service import FlutterwaveService

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initiate_land_payment(request, land_id):
    """
    Initialize payment for land purchase - UPDATED with attempts
    """
    try:
        land = get_object_or_404(Land, id=land_id, status__in=['available', 'reserved'])
        
        serializer = LandPaymentInitiationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        payment_type = serializer.validated_data['payment_type']
        installment_plan_id = serializer.validated_data.get('installment_plan_id')
        
        # Create or get land purchase record
        purchase, created = LandPurchase.objects.get_or_create(
            land=land,
            buyer=request.user,
            status='draft',
            defaults={
                'total_land_price': land.total_price,
                'payment_type': payment_type,
            }
        )
        
        if installment_plan_id:
            installment_plan = get_object_or_404(LandInstallmentPlan, id=installment_plan_id, land=land)
            purchase.installment_plan = installment_plan
            purchase.save()
        
        # Calculate payment amount
        if payment_type == 'full_payment':
            amount = land.total_price
        elif payment_type == 'down_payment' and purchase.installment_plan:
            amount = purchase.down_payment_amount
        elif payment_type == 'reservation_fee':
            amount = serializer.validated_data.get('reservation_fee', land.total_price * 0.05)
        else:
            amount = serializer.validated_data['amount']
        
        # Create payment record
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=request.user,
            amount=amount,
            payment_type=payment_type,
            due_date=timezone.now().date(),
            customer_email=request.user.email,
            customer_phone=request.user.phone or '',
            customer_name=f"{request.user.first_name} {request.user.last_name}",
            description=f"{payment_type.replace('_', ' ').title()} for {land.title}",
            metadata={
                'land_id': str(land.id),
                'payment_type': payment_type,
            }
        )
        
        # Create payment attempt
        attempt = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1,
            status='initiated'
        )
        
        # Initialize Flutterwave payment
        #flutterwave_service = FlutterwaveService()
        
        payment_data = {
            'tx_ref': attempt.flutterwave_tx_ref,  # Use attempt's tx_ref
            'amount': float(amount),
            'currency': 'NGN',
            'redirect_url': f"{settings.FRONTEND_URL}/payment/verify/{payment.payment_reference}",
            'customer_email': payment.customer_email,
            'customer_name': payment.customer_name,
            'customer_phone': payment.customer_phone,
            'description': payment.description,
            'metadata': payment.metadata,
        }
        
        result = FlutterwaveService.initialize_payment(payment_data)
        
        if result['success']:
            # Update attempt status
            attempt.mark_processing()
            payment.status = 'processing'
            payment.save()
            
            return Response({
                'success': True,
                'payment_reference': payment.payment_reference,
                'payment_link': result['payment_link'],
                'attempt_reference': attempt.flutterwave_tx_ref,
                'amount': amount,
                'message': 'Payment initialized successfully'
            })
        else:
            # Mark attempt as failed
            attempt.mark_failed(error_message=result['error'])
            payment.status = 'failed'
            payment.save()
            
            return Response({
                'success': False,
                'error': result['error'],
                'code': result['code']
            })
            
    except Exception as e:
        logger.error(f"Land payment initiation error: {str(e)}")
        return Response({
            'error': 'Payment initialization failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_land_payment(request, payment_reference):
    """
    Verify land payment status after user redirect
    """
    try:
        payment = get_object_or_404(
            LandPayment, 
            payment_reference=payment_reference, 
            buyer=request.user
        )
        
        #flutterwave_service = FlutterwaveService()
        
        if payment.flutterwave_transaction_id:
            result = FlutterwaveService.verify_payment(payment.flutterwave_transaction_id)
        else:
            result = FlutterwaveService.verify_payment(payment.flutterwave_tx_ref)
        
        if result['success']:
            if result['status'] == 'successful':
                payment.status = 'completed'
                payment.paid_date = timezone.now()
                payment.payment_method = result.get('payment_type', '')
                payment.flutterwave_response = result
                payment.save()
                
                # Update purchase status based on payment type
                purchase = payment.purchase
                
                if payment.payment_type == 'full_payment':
                    purchase.status = 'completed'
                    purchase.completion_date = timezone.now().date()
                    purchase.land.status = 'sold'
                    purchase.land.save()
                
                elif payment.payment_type == 'down_payment':
                    purchase.status = 'down_payment_paid'
                    purchase.down_payment_paid = True
                    # Generate payment schedule for installments
                    generate_installment_schedule(purchase)
                
                elif payment.payment_type == 'reservation_fee':
                    purchase.status = 'reserved'
                
                purchase.save()
                
                # Trigger post-payment actions
                trigger_land_post_payment_actions(payment)
                
                return Response({
                    'success': True,
                    'status': 'completed',
                    'payment': LandPaymentSerializer(payment).data,
                    'purchase': LandPurchaseSerializer(purchase).data,
                    'message': 'Payment verified successfully'
                })
            else:
                payment.status = 'failed'
                payment.flutterwave_response = result
                payment.save()
                
                return Response({
                    'success': False,
                    'status': 'failed',
                    'error': 'Payment verification failed',
                    'details': result
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({
                'success': False,
                'error': result['error'],
                'code': result['code']
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except LandPayment.DoesNotExist:
        return Response({
            'error': 'Payment not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Land payment verification error: {str(e)}")
        return Response({
            'error': 'Payment verification failed',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_installment_payment_schedule(request, purchase_id):
    """
    Get payment schedule for installment plan
    """
    try:
        purchase = get_object_or_404(LandPurchase, id=purchase_id, buyer=request.user)
        
        if not purchase.installment_plan:
            return Response({
                'error': 'No installment plan for this purchase'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        schedule = purchase.payment_schedule.all().order_by('installment_number')
        
        schedule_data = []
        for installment in schedule:
            schedule_data.append({
                'installment_number': installment.installment_number,
                'due_date': installment.due_date,
                'amount': installment.amount,
                'is_paid': installment.is_paid,
                'paid_date': installment.paid_date
            })
        
        return Response({
            'purchase_reference': purchase.purchase_reference,
            'total_land_price': purchase.total_land_price,
            'down_payment_paid': purchase.down_payment_paid,
            'remaining_balance': purchase.calculate_remaining_balance(),
            'payment_schedule': schedule_data
        })
        
    except LandPurchase.DoesNotExist:
        return Response({
            'error': 'Purchase not found'
        }, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pay_installment(request, purchase_id, installment_number):
    """
    Pay specific installment
    """
    try:
        purchase = get_object_or_404(LandPurchase, id=purchase_id, buyer=request.user)
        
        if not purchase.down_payment_paid:
            return Response({
                'error': 'Down payment must be paid first'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        schedule = get_object_or_404(
            PaymentSchedule, 
            purchase=purchase, 
            installment_number=installment_number
        )
        
        if schedule.is_paid:
            return Response({
                'error': 'This installment is already paid'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create installment payment
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=request.user,
            amount=schedule.amount,
            payment_type='installment',
            is_installment=True,
            installment_number=installment_number,
            due_date=schedule.due_date,
            customer_email=request.user.email,
            customer_phone=request.user.phone or '',
            customer_name=f"{request.user.first_name} {request.user.last_name}",
            description=f"Installment {installment_number} for {purchase.land.title}",
            metadata={
                'land_id': str(purchase.land.id),
                'installment_number': installment_number
            }
        )
        
        # Initialize Flutterwave payment
        flutterwave_service = FlutterwaveService()
        
        payment_data = {
            'tx_ref': payment.flutterwave_tx_ref,
            'amount': float(schedule.amount),
            'currency': 'NGN',
            'redirect_url': f"{settings.FRONTEND_URL}/payment/verify/{payment.payment_reference}",
            'customer_email': payment.customer_email,
            'customer_name': payment.customer_name,
            'customer_phone': payment.customer_phone,
            'description': payment.description,
            'metadata': payment.metadata
        }
        
        result = flutterwave_service.initialize_payment(payment_data)
        
        if result['success']:
            payment.status = 'initiated'
            payment.save()
            
            return Response({
                'success': True,
                'payment_reference': payment.payment_reference,
                'payment_link': result['payment_link'],
                'amount': schedule.amount,
                'installment_number': installment_number,
                'message': 'Installment payment initialized'
            })
        else:
            payment.status = 'failed'
            payment.save()
            
            return Response({
                'success': False,
                'error': result['error']
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Installment payment error: {str(e)}")
        return Response({
            'error': 'Installment payment failed',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Helper functions
def generate_installment_schedule(purchase):
    """Generate payment schedule for installment plan"""
    if not purchase.installment_plan:
        return
    
    monthly_amount = purchase.installment_plan.calculate_monthly_payment(purchase.total_land_price)
    today = timezone.now().date()
    
    for i in range(1, purchase.total_installments + 1):
        due_date = today + timedelta(days=30 * i)
        
        PaymentSchedule.objects.create(
            purchase=purchase,
            installment_number=i,
            due_date=due_date,
            amount=monthly_amount
        )

def trigger_land_post_payment_actions(payment):
    """Trigger actions after successful land payment"""
    from .tasks import (
        generate_land_payment_receipt,
        send_land_payment_confirmation,
        update_land_purchase_status,
        notify_sales_team
    )
    
    generate_land_payment_receipt.delay(payment.id)
    send_land_payment_confirmation.delay(payment.id)
    update_land_purchase_status.delay(payment.purchase.id)
    notify_sales_team.delay(payment.purchase.id)
    
    
# Payment history
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_history(request):
    """
    Retrieve all payments made by the authenticated user.
    """
    user = request.user
    payments = LandPayment.objects.filter(buyer=user).order_by('-created_at')
    serializer = LandPaymentSerializer(payments, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)