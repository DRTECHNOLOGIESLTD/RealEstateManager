# payments/tasks.py
from celery import shared_task
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
import logging
import resend
from .models import LandPayment, LandPurchase
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Initialize Resend
resend.api_key = settings.RESEND_API_KEY

@shared_task(bind=True, max_retries=3)
def generate_land_payment_receipt(self, payment_id):
    """
    Generate and save PDF receipt for land payment
    """
    try:
        payment = LandPayment.objects.select_related('purchase', 'purchase__land', 'buyer').get(id=payment_id)
        
        # Create receipt data structure
        receipt_data = {
            'receipt_number': f"RCP-{payment.payment_reference}",
            'payment_date': payment.paid_date or timezone.now(),
            'customer_name': payment.customer_name,
            'customer_email': payment.customer_email,
            'land_title': payment.purchase.land.title,
            'land_location': f"{payment.purchase.land.city}, {payment.purchase.land.state}",
            'amount_paid': float(payment.amount),
            'currency': payment.currency,
            'payment_method': payment.payment_method or 'Flutterwave',
            'payment_type': payment.payment_type,
            'transaction_reference': payment.payment_reference,
            'flutterwave_reference': payment.flutterwave_tx_ref,
        }
        
        # Store receipt data in payment metadata
        payment.metadata['receipt_data'] = receipt_data
        payment.metadata['receipt_generated_at'] = timezone.now().isoformat()
        payment.save()
        
        logger.info(f"Receipt generated for payment: {payment.payment_reference}")
        return f"Receipt generated for {payment.payment_reference}"
        
    except LandPayment.DoesNotExist:
        logger.error(f"Payment not found for receipt generation: {payment_id}")
        return f"Payment not found: {payment_id}"
    except Exception as e:
        logger.error(f"Error generating receipt for payment {payment_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task(bind=True, max_retries=3)
def send_land_payment_confirmation(self, payment_id):
    """
    Send payment confirmation email to customer using Resend
    """
    try:
        payment = LandPayment.objects.select_related('purchase', 'purchase__land', 'buyer').get(id=payment_id)
        
        # Render email template
        html_content = render_to_string('emails/payment_confirmation.html', {
            'customer_name': payment.customer_name,
            'land_title': payment.purchase.land.title,
            'land_location': f"{payment.purchase.land.city}, {payment.purchase.land.state}",
            'amount_paid': float(payment.amount),
            'currency': payment.currency,
            'payment_date': payment.paid_date or timezone.now(),
            'payment_reference': payment.payment_reference,
            'payment_type': payment.payment_type.replace('_', ' ').title(),
            'company_name': 'MyHouse Land Sales',
            'support_email': 'support@myhouse.ng',
        })
        
        # Send email using Resend
        params = {
            "from": f"MyHouse Land Sales <{settings.RESEND_FROM_EMAIL}>",
            "to": [payment.customer_email],
            "subject": f"Payment Confirmation - {payment.purchase.land.title}",
            "html": html_content,
            "tags": [
                {"name": "category", "value": "payment_confirmation"},
                {"name": "payment_reference", "value": payment.payment_reference}
            ]
        }
        
        email = resend.Emails.send(params)
        
        # Log the email sent
        payment.metadata['confirmation_email_sent'] = True
        payment.metadata['confirmation_email_sent_at'] = timezone.now().isoformat()
        payment.metadata['resend_email_id'] = email['id']
        payment.save()
        
        logger.info(f"Payment confirmation sent via Resend to {payment.customer_email}")
        return f"Confirmation sent for {payment.payment_reference}"
        
    except LandPayment.DoesNotExist:
        logger.error(f"Payment not found for confirmation email: {payment_id}")
        return f"Payment not found: {payment_id}"
    except resend.ResendError as e:
        logger.error(f"Resend error sending confirmation for payment {payment_id}: {str(e)}")
        self.retry(countdown=30, exc=e)
    except Exception as e:
        logger.error(f"Error sending confirmation email for payment {payment_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task(bind=True, max_retries=3)
def update_land_purchase_status(self, purchase_id):
    """
    Update land purchase status based on payment
    """
    try:
        from django.db.models import Sum
        purchase = LandPurchase.objects.select_related('land').get(id=purchase_id)
        
        # Calculate total paid amount
        total_paid = LandPayment.objects.filter(
            purchase=purchase, 
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Update purchase status based on payment type and amount paid
        if purchase.payment_type == 'full_payment' and total_paid >= purchase.total_land_price:
            purchase.status = 'completed'
            purchase.completion_date = timezone.now().date()
            purchase.land.status = 'sold'
            purchase.land.save()
            
        elif purchase.payment_type == 'down_payment' and total_paid >= purchase.down_payment_amount:
            purchase.status = 'down_payment_paid'
            purchase.down_payment_paid = True
            
        elif purchase.payment_type == 'reservation_fee' and total_paid > 0:
            purchase.status = 'reserved'
        
        # Check if installment plan is completed
        if (purchase.installment_plan and 
            purchase.down_payment_paid and 
            total_paid >= purchase.total_land_price):
            purchase.status = 'completed'
            purchase.completion_date = timezone.now().date()
            purchase.land.status = 'sold'
            purchase.land.save()
        
        purchase.save()
        
        logger.info(f"Purchase status updated: {purchase.purchase_reference} -> {purchase.status}")
        return f"Purchase status updated: {purchase.status}"
        
    except LandPurchase.DoesNotExist:
        logger.error(f"Purchase not found for status update: {purchase_id}")
        return f"Purchase not found: {purchase_id}"
    except Exception as e:
        logger.error(f"Error updating purchase status {purchase_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task(bind=True, max_retries=2)
def notify_sales_team(self, purchase_id):
    """
    Notify sales team about successful payment using Resend
    """
    try:
        purchase = LandPurchase.objects.select_related('land', 'buyer').get(id=purchase_id)
        
        # Get the latest successful payment
        latest_payment = LandPayment.objects.filter(
            purchase=purchase, 
            status='completed'
        ).order_by('-paid_date').first()
        
        if not latest_payment:
            logger.warning(f"No completed payment found for purchase: {purchase_id}")
            return "No completed payment found"
        
        # Calculate total paid
        from django.db.models import Sum
        total_paid = LandPayment.objects.filter(
            purchase=purchase, 
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Sales team email
        sales_team_email = getattr(settings, 'SALES_TEAM_EMAIL', 'sales@myhouse.ng')
        
        # Render email template
        html_content = render_to_string('emails/sales_team_notification.html', {
            'land_title': purchase.land.title,
            'land_location': f"{purchase.land.city}, {purchase.land.state}",
            'customer_name': purchase.buyer.get_full_name(),
            'customer_email': purchase.buyer.email,
            'customer_phone': purchase.buyer.phone or 'Not provided',
            'amount_paid': float(latest_payment.amount),
            'currency': latest_payment.currency,
            'payment_type': latest_payment.payment_type.replace('_', ' ').title(),
            'payment_reference': latest_payment.payment_reference,
            'purchase_reference': purchase.purchase_reference,
            'total_land_price': float(purchase.total_land_price),
            'paid_to_date': float(total_paid),
            'payment_date': latest_payment.paid_date or timezone.now(),
        })
        
        # Send email using Resend
        params = {
            "from": f"MyHouse Land Sales <{settings.RESEND_FROM_EMAIL}>",
            "to": [sales_team_email],
            "subject": f"New Land Payment - {purchase.land.title}",
            "html": html_content,
            "tags": [
                {"name": "category", "value": "sales_notification"},
                {"name": "purchase_reference", "value": purchase.purchase_reference}
            ]
        }
        
        email = resend.Emails.send(params)
        
        logger.info(f"Sales team notified via Resend about payment: {latest_payment.payment_reference}")
        return f"Sales team notified for {purchase.purchase_reference}"
        
    except LandPurchase.DoesNotExist:
        logger.error(f"Purchase not found for sales notification: {purchase_id}")
        return f"Purchase not found: {purchase_id}"
    except resend.ResendError as e:
        logger.error(f"Resend error notifying sales team for purchase {purchase_id}: {str(e)}")
        self.retry(countdown=30, exc=e)
    except Exception as e:
        logger.error(f"Error notifying sales team for purchase {purchase_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task(bind=True, max_retries=3)
def process_failed_payment(self, payment_id, error_message):
    """
    Handle failed payments - notify customer using Resend
    """
    try:
        payment = LandPayment.objects.select_related('purchase', 'purchase__land', 'buyer').get(id=payment_id)
        
        # Render failure email template
        html_content = render_to_string('emails/payment_failed.html', {
            'customer_name': payment.customer_name,
            'land_title': payment.purchase.land.title,
            'amount': float(payment.amount),
            'currency': payment.currency,
            'error_message': error_message,
            'payment_reference': payment.payment_reference,
            'support_email': 'support@myhouse.ng',
        })
        
        # Send failure notification using Resend
        params = {
            "from": f"MyHouse Land Sales <{settings.RESEND_FROM_EMAIL}>",
            "to": [payment.customer_email],
            "subject": f"Payment Failed - {payment.purchase.land.title}",
            "html": html_content,
            "tags": [
                {"name": "category", "value": "payment_failed"},
                {"name": "payment_reference", "value": payment.payment_reference}
            ]
        }
        
        email = resend.Emails.send(params)
        
        # Update payment metadata
        payment.metadata['failure_notification_sent'] = True
        payment.metadata['failure_notification_sent_at'] = timezone.now().isoformat()
        payment.metadata['last_error'] = error_message
        payment.metadata['resend_failure_email_id'] = email['id']
        payment.save()
        
        logger.info(f"Failure notification sent via Resend for payment: {payment.payment_reference}")
        return f"Failure handled for {payment.payment_reference}"
        
    except LandPayment.DoesNotExist:
        logger.error(f"Payment not found for failure processing: {payment_id}")
        return f"Payment not found: {payment_id}"
    except resend.ResendError as e:
        logger.error(f"Resend error processing failed payment {payment_id}: {str(e)}")
        self.retry(countdown=30, exc=e)
    except Exception as e:
        logger.error(f"Error processing failed payment {payment_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task(bind=True, max_retries=3)
def send_installment_reminder(self, payment_schedule_id):
    """
    Send installment payment reminder using Resend
    """
    try:
        from .models import PaymentSchedule
        schedule = PaymentSchedule.objects.select_related(
            'purchase', 
            'purchase__land', 
            'purchase__buyer'
        ).get(id=payment_schedule_id)
        
        # Render reminder email
        html_content = render_to_string('emails/installment_reminder.html', {
            'customer_name': schedule.purchase.buyer.get_full_name(),
            'land_title': schedule.purchase.land.title,
            'installment_number': schedule.installment_number,
            'due_date': schedule.due_date,
            'amount': float(schedule.amount),
            'currency': schedule.purchase.land.currency,
            'total_installments': schedule.purchase.total_installments,
            'paid_installments': schedule.purchase.completed_installments,
            'payment_link': f"{settings.FRONTEND_URL}/payments/installment/{schedule.purchase.id}/{schedule.installment_number}",
        })
        
        # Send reminder using Resend
        params = {
            "from": f"MyHouse Land Sales <{settings.RESEND_FROM_EMAIL}>",
            "to": [schedule.purchase.buyer.email],
            "subject": f"Installment Reminder - {schedule.purchase.land.title}",
            "html": html_content,
            "tags": [
                {"name": "category", "value": "installment_reminder"},
                {"name": "purchase_reference", "value": schedule.purchase.purchase_reference}
            ]
        }
        
        email = resend.Emails.send(params)
        
        # Mark reminder as sent
        schedule.metadata['reminder_sent'] = True
        schedule.metadata['reminder_sent_at'] = timezone.now().isoformat()
        schedule.metadata['resend_reminder_email_id'] = email['id']
        schedule.save()
        
        logger.info(f"Installment reminder sent via Resend for {schedule.purchase.purchase_reference}")
        return f"Reminder sent for installment {schedule.installment_number}"
        
    except PaymentSchedule.DoesNotExist:
        logger.error(f"Payment schedule not found for reminder: {payment_schedule_id}")
        return f"Schedule not found: {payment_schedule_id}"
    except resend.ResendError as e:
        logger.error(f"Resend error sending installment reminder {payment_schedule_id}: {str(e)}")
        self.retry(countdown=30, exc=e)
    except Exception as e:
        logger.error(f"Error sending installment reminder {payment_schedule_id}: {str(e)}")
        self.retry(countdown=30, exc=e)

@shared_task
def cleanup_old_pending_payments():
    """
    Clean up payments that have been pending for too long (24 hours)
    """
    try:
        cutoff_time = timezone.now() - timezone.timedelta(hours=24)
        
        old_pending_payments = LandPayment.objects.filter(
            status='pending',
            created_at__lt=cutoff_time
        )
        
        count = old_pending_payments.count()
        
        for payment in old_pending_payments:
            payment.status = 'expired'
            payment.metadata['auto_expired_at'] = timezone.now().isoformat()
            payment.save()
        
        logger.info(f"Cleaned up {count} expired pending payments")
        return f"Cleaned up {count} expired payments"
        
    except Exception as e:
        logger.error(f"Error cleaning up old payments: {str(e)}")
        return f"Cleanup error: {str(e)}"