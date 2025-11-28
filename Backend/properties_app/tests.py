from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Land, LandInstallmentPlan
from payments_app.models import LandPurchase, LandPayment, PaymentAttempt
from datetime import timedelta

# Create your tests here.
User = get_user_model()

class PaymentModelsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            phone='+2348012345678'
        )
        
        self.land = Land.objects.create(
            title='Test Land Plot',
            land_type='residential',
            address_line_1='123 Test Street',
            city='Lagos',
            state='Lagos',
            country='Nigeria',
            size_square_meters=500,
            price_per_square_meter=100000,
            total_price=50000000,  # 50 million
        )
        
        self.installment_plan = LandInstallmentPlan.objects.create(
            land=self.land,
            name='6-Month Plan',
            total_months=6,
            down_payment_percentage=30.0,
            monthly_interest_rate=0.0
        )

    def test_land_creation(self):
        """Test land model creation and price calculation"""
        self.assertEqual(self.land.total_price, 50000000)
        self.assertEqual(self.land.status, 'available')

    def test_land_purchase_creation(self):
        """Test land purchase model creation"""
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=self.land.total_price,
            payment_type='full_payment'
        )
        
        self.assertTrue(purchase.purchase_reference.startswith('LAND-'))
        self.assertEqual(purchase.status, 'draft')

    def test_land_payment_creation(self):
        """Test land payment model creation"""
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=self.land.total_price,
            payment_type='full_payment'
        )
        
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=self.user,
            amount=50000000,
            payment_type='full_payment',
            customer_email=self.user.email,
            customer_name=f"{self.user.first_name} {self.user.last_name}",
            customer_phone=self.user.phone
        )
        
        self.assertTrue(payment.payment_reference.startswith('LAND-PAY-'))
        self.assertTrue(payment.flutterwave_tx_ref.startswith('land_'))

    def test_payment_attempt_creation(self):
        """Test payment attempt model creation"""
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=self.land.total_price,
            payment_type='full_payment'
        )
        
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=self.user,
            amount=50000000,
            payment_type='full_payment'
        )
        
        attempt = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1
        )
        
        self.assertEqual(attempt.status, 'initiated')
        self.assertTrue(attempt.flutterwave_tx_ref.startswith('myhouse_attempt_'))

    def test_payment_attempt_status_flow(self):
        """Test payment attempt status transitions"""
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=self.land.total_price
        )
        
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=self.user,
            amount=50000000
        )
        
        attempt = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=1
        )
        
        # Test processing
        attempt.mark_processing()
        self.assertEqual(attempt.status, 'processing')
        self.assertIsNotNone(attempt.processing_started_at)
        
        # Test completion
        attempt.mark_completed({'status': 'success'})
        self.assertEqual(attempt.status, 'completed')
        self.assertIsNotNone(attempt.completed_at)
        self.assertFalse(attempt.is_failed)
        
        # Test failure
        attempt2 = PaymentAttempt.objects.create(
            payment=payment,
            attempt_number=2
        )
        attempt2.mark_failed('Card declined', {'status': 'failed'})
        self.assertEqual(attempt2.status, 'failed')
        self.assertTrue(attempt2.is_failed)
        self.assertEqual(attempt2.error_message, 'Card declined')

    def test_installment_plan_calculations(self):
        """Test installment plan calculations"""
        down_payment = self.installment_plan.calculate_down_payment(self.land.total_price)
        monthly_payment = self.installment_plan.calculate_monthly_payment(self.land.total_price)
        
        self.assertEqual(down_payment, 15000000)  # 30% of 50 million
        self.assertAlmostEqual(monthly_payment, 5833333.33, places=2)  # (50M - 15M) / 6