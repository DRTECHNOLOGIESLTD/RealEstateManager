from django.db import models
from core.models import TimeStampedModel
from users_app.models import User
from properties_app.models import Land, LandInstallmentPlan, LandReservation
import uuid
from django.utils import timezone

class LandPurchase(TimeStampedModel):
    """Main land purchase transaction"""
    PURCHASE_STATUS = [
        ('draft', 'Draft'),
        ('reserved', 'Reserved'),
        ('down_payment_paid', 'Down Payment Paid'),
        ('in_progress', 'Payment in Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('defaulted', 'Defaulted'),
    ]
    
    PAYMENT_TYPES = [
        ('full_payment', 'Full Payment'),
        ('down_payment', 'Down Payment'),
        ('installment', 'Installment Payment'),
        ('reservation_fee', 'Reservation Fee'),
        ('legal_fee', 'Legal Fee'),
        ('documentation_fee', 'Documentation Fee'),
    ]
    
    purchase_reference = models.CharField(max_length=100, unique=True)
    land = models.ForeignKey(Land, on_delete=models.CASCADE, related_name='purchases')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='land_purchases')
    installment_plan = models.ForeignKey(LandInstallmentPlan, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Purchase Details
    total_land_price = models.DecimalField(max_digits=15, decimal_places=2)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='full_payment')
    status = models.CharField(max_length=20, choices=PURCHASE_STATUS, default='draft')
    
    # Installment Details (if applicable)
    down_payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    down_payment_paid = models.BooleanField(default=False)
    total_installments = models.IntegerField(default=0)
    completed_installments = models.IntegerField(default=0)
    
    # Dates
    purchase_date = models.DateField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    
    # Legal & Documentation
    agreement_document = models.FileField(upload_to='purchase_agreements/', null=True, blank=True)
    legal_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    documentation_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.purchase_reference:
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.purchase_reference = f'LAND-{timestamp}-{uuid.uuid4().hex[:6].upper()}'
        
        # Calculate down payment if installment plan
        if self.installment_plan and not self.down_payment_amount:
            self.down_payment_amount = self.installment_plan.calculate_down_payment(self.total_land_price)
            self.total_installments = self.installment_plan.total_months
        
        super().save(*args, **kwargs)
    
    def calculate_remaining_balance(self):
        total_paid = sum(payment.amount for payment in self.payments.filter(status='completed'))
        return self.total_land_price - total_paid
    
    def get_next_installment_amount(self):
        if self.installment_plan and self.down_payment_paid:
            return self.installment_plan.calculate_monthly_payment(self.total_land_price)
        return 0
    
    def __str__(self):
        return f"{self.purchase_reference} - {self.land.title}"



class LandPayment(TimeStampedModel):
    """Individual payments for land purchases"""
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('initiated', 'Initiated'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_METHODS = [
        ('card', 'Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('ussd', 'USSD'),
        ('account', 'Bank Account'),
    ]
    
    # Basic Information
    payment_reference = models.CharField(max_length=100, unique=True)
    purchase = models.ForeignKey(LandPurchase, on_delete=models.CASCADE, related_name='payments')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='land_payments')
    
    # Payment Details
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='NGN')
    payment_type = models.CharField(max_length=20, choices=LandPurchase.PAYMENT_TYPES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, blank=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    
    # Installment Tracking
    is_installment = models.BooleanField(default=False)
    installment_number = models.IntegerField(null=True, blank=True)
    
    # Dates
    due_date = models.DateField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    
    # Flutterwave Specific
    flutterwave_tx_ref = models.CharField(max_length=100, unique=True, blank=True)
    flutterwave_transaction_id = models.BigIntegerField(null=True, blank=True)
    flutterwave_response = models.JSONField(null=True, blank=True)
    
    # Customer Details
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    
    # Metadata
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.payment_reference:
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.payment_reference = f'LAND-PAY-{timestamp}-{uuid.uuid4().hex[:6].upper()}'
        
        if not self.flutterwave_tx_ref:
            self.flutterwave_tx_ref = f'land_{self.payment_reference}_{int(timezone.now().timestamp())}'
            
        super().save(*args, **kwargs)
        
        # Add this property to the LandPayment model
    @property
    def latest_attempt(self):
        """Get the most recent payment attempt"""
        return self.attempts.order_by('-created_at').first()
    
    @property
    def successful_attempt(self):
        """Get the successful payment attempt if any"""
        return self.attempts.filter(status='completed').first()
    
    @property
    def attempt_count(self):
        """Get total number of attempts"""
        return self.attempts.count()
    
    def create_new_attempt(self, payment_method, ip_address=None, user_agent=None):
        """Create a new payment attempt"""
        attempt_number = self.attempt_count + 1
        
        return PaymentAttempt.objects.create(
            payment=self,
            attempt_number=attempt_number,
            status='initiated'
        )
    
    def __str__(self):
        return f"{self.payment_reference} - {self.amount} {self.currency}"
    
    
    

class PaymentSchedule(TimeStampedModel):
    """Installment payment schedule for land purchases"""
    purchase = models.ForeignKey(LandPurchase, on_delete=models.CASCADE, related_name='payment_schedule')
    installment_number = models.IntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)
    
    class Meta:
        unique_together = ['purchase', 'installment_number']
        ordering = ['installment_number']
    
    def __str__(self):
        return f"Installment {self.installment_number} - {self.purchase.purchase_reference}"
    
    
    
    

class PaymentAttempt(TimeStampedModel):
    """
    Simplified model to track payment attempts with essential fields
    """
    
    ATTEMPT_STATUS = [
        ('initiated', 'Initiated'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Basic Identification
    payment = models.ForeignKey('LandPayment', on_delete=models.CASCADE, related_name='attempts')
    attempt_number = models.IntegerField(default=1)
    
    # Status Tracking
    status = models.CharField(max_length=20, choices=ATTEMPT_STATUS, default='initiated')
    
    # Flutterwave Integration
    flutterwave_tx_ref = models.CharField(max_length=100, unique=True)
    flutterwave_transaction_id = models.BigIntegerField(null=True, blank=True)
    
    # Failure Tracking
    is_failed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    
    # Gateway Communication
    gateway_response = models.JSONField(null=True, blank=True)
    
    # Timestamps
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['payment', 'attempt_number']

    def __str__(self):
        return f"Attempt {self.attempt_number} - {self.payment.payment_reference}"

    def save(self, *args, **kwargs):
        # Generate Flutterwave transaction reference if not set
        if not self.flutterwave_tx_ref:
            timestamp = int(timezone.now().timestamp())
            self.flutterwave_tx_ref = f'myhouse_attempt_{timestamp}_{uuid.uuid4().hex[:8]}'
        
        # Auto-set failure flag
        if self.status in ['failed', 'cancelled']:
            self.is_failed = True
            self.completed_at = timezone.now()
        elif self.status == 'completed':
            self.is_failed = False
            self.completed_at = timezone.now()
        
        super().save(*args, **kwargs)

    @property
    def is_successful(self):
        return self.status == 'completed'

    def mark_processing(self):
        """Mark attempt as processing"""
        self.status = 'processing'
        self.processing_started_at = timezone.now()
        self.save()

    def mark_completed(self, gateway_data=None):
        """Mark attempt as completed successfully"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if gateway_data:
            self.gateway_response = gateway_data
        self.save()

    def mark_failed(self, error_message='', gateway_data=None):
        """Mark attempt as failed"""
        self.status = 'failed'
        self.is_failed = True
        self.error_message = error_message
        self.completed_at = timezone.now()
        if gateway_data:
            self.gateway_response = gateway_data
        self.save()
        