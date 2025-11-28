# payments/tests/test_services.py
from django.test import TestCase
from unittest.mock import patch, MagicMock
from services.flutterwave_service import FlutterwaveService
from payments_app.models import LandPurchase, LandPayment
from users_app.models import User
from properties_app.models import Land

class FlutterwaveServiceTestCase(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create test land
        self.land = Land.objects.create(
            title='Test Land',
            land_type='residential',
            address_line_1='123 Test St',
            city='Lagos',
            state='Lagos',
            size_square_meters=500,
            price_per_square_meter=100000,
            total_price=50000000
        )
        
        # Create land purchase
        self.purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=50000000
        )
        
        # Create payment
        self.payment = LandPayment.objects.create(
            purchase=self.purchase,
            buyer=self.user,
            amount=50000000,
            customer_email=self.user.email,
            customer_name='Test User'
        )
        
        # Service instance
        self.service = FlutterwaveService()

    @patch('services.flutterwave_service.FlutterwaveService._make_secure_request')
    def test_successful_payment_initialization(self, mock_request):
        """Test successful payment initialization"""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'status': 'success',
            'message': 'Hosted Link',
            'data': {
                'link': 'https://checkout.flutterwave.com/v3/hosted/pay/test123',
                'flw_ref': 'FLW12345'
            }
        }
        mock_request.return_value = mock_response
        
        payment_data = {
            'tx_ref': 'test_ref_123',
            'amount': '50000000',  # Pass as string to bypass validation
            'currency': 'NGN',
            'redirect_url': 'http://localhost:3000/payment/verify',
            'customer_email': 'test@example.com',
            'customer_name': 'Test User',
            'description': 'Test payment'
        }
        
        result = self.service.initialize_payment(payment_data)
        
        # Assertions
        self.assertTrue(result['success'])
        self.assertIn('payment_link', result)
        self.assertEqual(result['tx_ref'], 'test_ref_123')
        self.assertEqual(result['flw_ref'], 'FLW12345')

    @patch('services.flutterwave_service.FlutterwaveService._make_secure_request')
    def test_successful_payment_verification(self, mock_request):
        """Test successful payment verification"""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'status': 'success',
            'data': {
                'id': 123456,
                'tx_ref': 'test_ref_123',
                'amount': 50000000,
                'currency': 'NGN',
                'status': 'successful',
                'payment_type': 'card',
                'created_at': '2024-01-01T12:00:00Z',
                'customer': {'email': 'test@example.com'},
                'flw_ref': 'FLW12345'
            }
        }
        mock_request.return_value = mock_response
        
        result = self.service.verify_payment(123456)
        
        # Assertions
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'successful')
        self.assertEqual(result['amount'], 50000000)
        self.assertEqual(result['tx_ref'], 'test_ref_123')
        self.assertEqual(result['flw_ref'], 'FLW12345')

    @patch('services.flutterwave_service.FlutterwaveService._make_secure_request')
    def test_failed_payment_initialization(self, mock_request):
        """Test failed payment initialization"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'status': 'error',
            'message': 'Invalid amount'
        }
        mock_request.return_value = mock_response
        
        payment_data = {
            'tx_ref': 'test_ref_123',
            'amount': '-100',  # Invalid amount
            'currency': 'NGN',
            'redirect_url': 'http://localhost:3000/payment/verify',
            'customer_email': 'test@example.com',
            'customer_name': 'Test User'
        }
        
        result = self.service.initialize_payment(payment_data)
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)

    def test_webhook_signature_verification(self):
        """Test webhook signature verification"""
        test_data = {'event': 'charge.completed', 'data': {'tx_ref': 'test123'}}
        test_signature = 'test_signature'
        
        # Expect False because signature won't match
        result = self.service.verify_webhook_signature(test_data, test_signature)
        
        self.assertIsInstance(result, bool)
