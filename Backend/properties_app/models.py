from django.db import models

# Create your models here.
# properties/models.py
from django.db import models
from core.models import TimeStampedModel, SoftDeleteModel
from users_app.models import User
import uuid

class Land(SoftDeleteModel):
    """Land/Plot model for sale"""
    LAND_TYPES = [
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('industrial', 'Industrial'),
        ('agricultural', 'Agricultural'),
        ('mixed_use', 'Mixed Use'),
    ]
    
    LAND_STATUS = [
        ('available', 'Available for Sale'),
        ('reserved', 'Reserved'),
        ('sold', 'Sold'),
        ('unavailable', 'Unavailable'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    land_type = models.CharField(max_length=20, choices=LAND_TYPES)
    status = models.CharField(max_length=20, choices=LAND_STATUS, default='available')

    
    # Location Details
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default='Nigeria')
    postal_code = models.CharField(max_length=20)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Land Specifications
    size_square_meters = models.DecimalField(max_digits=12, decimal_places=2)
    size_acres = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    land_use_purpose = models.CharField(max_length=100, blank=True)
    topographical_features = models.JSONField(default=list)  # ['flat', 'hilly', 'waterfront']
    
    # Pricing
    price_per_square_meter = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, default='NGN')
    
    # Payment Plans
    has_installment_plan = models.BooleanField(default=False)
    installment_months = models.IntegerField(default=0)  # 0 means full payment
    
    # Legal & Documentation
    c_of_o_available = models.BooleanField(default=False)
    survey_plan_available = models.BooleanField(default=False)
    government_approval = models.BooleanField(default=False)
    
    # Media
    images = models.JSONField(default=list)  # List of image URLs
    survey_plan_image = models.FileField(upload_to='survey_plans/', null=True, blank=True)
    video_tour_url = models.URLField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        # Auto-calculate total price if not set
        if not self.total_price and self.size_square_meters and self.price_per_square_meter:
            self.total_price = self.size_square_meters * self.price_per_square_meter
        
        # Auto-calculate acres if not set
        if not self.size_acres and self.size_square_meters:
            self.size_acres = self.size_square_meters * 0.000247105
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.title} - {self.city}"

class LandInstallmentPlan(TimeStampedModel):
    """Installment payment plans for land purchases"""
    land = models.ForeignKey(Land, on_delete=models.CASCADE, related_name='installment_plans')
    name = models.CharField(max_length=100)  # e.g., "6-Month Plan", "12-Month Plan"
    total_months = models.IntegerField()
    down_payment_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=30.00)
    monthly_interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    
    def calculate_down_payment(self, land_price):
        return (land_price * self.down_payment_percentage) / 100
    
    def calculate_monthly_payment(self, land_price):
        principal = land_price - self.calculate_down_payment(land_price)
        monthly_rate = self.monthly_interest_rate / 100
        if monthly_rate > 0:
            return (principal * monthly_rate * (1 + monthly_rate) ** self.total_months) / ((1 + monthly_rate) ** self.total_months - 1)
        else:
            return principal / self.total_months
    
    def __str__(self):
        return f"{self.name} - {self.land.title}"

class LandReservation(TimeStampedModel):
    """Track land reservations by potential buyers"""
    RESERVATION_STATUS = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('converted', 'Converted to Sale'),
        ('cancelled', 'Cancelled'),
    ]
    
    land = models.ForeignKey(Land, on_delete=models.CASCADE, related_name='reservations')
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='land_reservations')
    reservation_fee = models.DecimalField(max_digits=12, decimal_places=2)
    reservation_duration_days = models.IntegerField(default=30)
    expiry_date = models.DateField()
    status = models.CharField(max_length=20, choices=RESERVATION_STATUS, default='active')
    notes = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['land', 'customer']
    
    def save(self, *args, **kwargs):
        if not self.expiry_date:
            from django.utils import timezone
            from datetime import timedelta
            self.expiry_date = timezone.now().date() + timedelta(days=self.reservation_duration_days)
        super().save(*args, **kwargs)
    
    def is_expired(self):
        from django.utils import timezone
        return timezone.now().date() > self.expiry_date
    
    def __str__(self):
        return f"Reservation - {self.land.title} - {self.customer.get_full_name()}"