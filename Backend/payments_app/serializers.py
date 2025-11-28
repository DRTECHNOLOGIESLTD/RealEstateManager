# payments/serializers.py
from rest_framework import serializers
from .models import LandPurchase, LandPayment, LandReservation, PaymentAttempt

class LandPaymentInitiationSerializer(serializers.Serializer):
    payment_type = serializers.ChoiceField(choices=LandPurchase.PAYMENT_TYPES)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    installment_plan_id = serializers.UUIDField(required=False)
    reservation_fee = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    payment_method = serializers.ChoiceField(
        choices=LandPayment.PAYMENT_METHODS, 
        required=False,
        allow_blank=True
    )

class LandPurchaseSerializer(serializers.ModelSerializer):
    land_title = serializers.CharField(source='land.title', read_only=True)
    land_location = serializers.SerializerMethodField()
    buyer_name = serializers.CharField(source='buyer.get_full_name', read_only=True)
    remaining_balance = serializers.SerializerMethodField()
    
    class Meta:
        model = LandPurchase
        fields = [
            'id', 'purchase_reference', 'land_title', 'land_location', 
            'total_land_price', 'payment_type', 'status', 'buyer_name',
            'down_payment_amount', 'down_payment_paid', 'total_installments',
            'completed_installments', 'purchase_date', 'completion_date',
            'remaining_balance', 'created_at'
        ]
        read_only_fields = ['id', 'purchase_reference', 'created_at']
    
    def get_land_location(self, obj):
        return f"{obj.land.city}, {obj.land.state}"
    
    def get_remaining_balance(self, obj):
        return obj.calculate_remaining_balance()
# payments/serializers.py
class PaymentAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAttempt
        fields = [
            'id', 'attempt_number', 'status', 'is_failed', 
            'error_message', 'created_at', 'completed_at'
        ]
        read_only_fields = ['id', 'created_at']

class LandPaymentSerializer(serializers.ModelSerializer):
    land_title = serializers.CharField(source='purchase.land.title', read_only=True)
    buyer_name = serializers.CharField(source='buyer.get_full_name', read_only=True)
    attempts = PaymentAttemptSerializer(many=True, read_only=True)
    latest_attempt = serializers.SerializerMethodField()
    
    class Meta:
        model = LandPayment
        fields = [
            'id', 'payment_reference', 'amount', 'currency', 'payment_type',
            'payment_method', 'status', 'due_date', 'paid_date', 'created_at',
            'land_title', 'buyer_name', 'attempts', 'latest_attempt'
        ]
        read_only_fields = ['id', 'payment_reference', 'created_at']
    
    def get_latest_attempt(self, obj):
        latest = obj.attempts.order_by('-created_at').first()
        if latest:
            return PaymentAttemptSerializer(latest).data
        return None

class LandReservationSerializer(serializers.ModelSerializer):
    land_title = serializers.CharField(source='land.title', read_only=True)
    customer_name = serializers.CharField(source='customer.get_full_name', read_only=True)
    
    class Meta:
        model = LandReservation
        fields = [
            'id', 'land_title', 'customer_name', 'reservation_fee',
            'reservation_duration_days', 'expiry_date', 'status', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']