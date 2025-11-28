# payments_app/tests/test_views.py
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from payments_app.models import LandPurchase, LandPayment
from users_app.models import User
from properties_app.models import Land

class PaymentViewsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        self.land = Land.objects.create(
            title='Test Land',
            land_type='residential',
            address_line_1='123 Test St',
            city='Lagos',
            state='Lagos',
            size_square_meters=500,
            price_per_square_meter=100000,
            total_price=50000000,
            status='available'
        )
        
        # Authenticate the client
        self.client.force_authenticate(user=self.user)

    @patch('payments_app.views.FlutterwaveService.initialize_paymen')
    def test_initiate_land_payment_success(self, mock_initiate):
        """Test successful payment initiation"""
        # Mock successful payment initialization
        mock_initiate.return_value = {
            'success': True,
            'payment_link': 'https://checkout.flutterwave.com/v3/hosted/pay/test123',
            'tx_ref': 'test_ref_123'
        }
        
        # Use the correct URL name with app namespace
        url = reverse('payments_app:initiate-land-payment', kwargs={'land_id': self.land.id})
        data = {
            'payment_type': 'full_payment'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('payment_link', response.data)

    def test_initiate_land_payment_invalid_land(self):
        """Test payment initiation with invalid land"""
        # Use the correct URL name with app namespace
        url = reverse('payments_app:initiate-land-payment', kwargs={'land_id': '99999999-9999-9999-9999-999999999999'})
        data = {
            'payment_type': 'full_payment'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('payments_app.views.FlutterwaveService.verify_payment')
    def test_verify_payment_success(self, mock_verify):
        """Test successful payment verification"""
        # Create a payment first
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=50000000
        )
        
        payment = LandPayment.objects.create(
            purchase=purchase,
            buyer=self.user,
            amount=50000000,
            flutterwave_tx_ref='test_ref_123'
        )
        
        # Mock successful verification
        mock_verify.return_value = {
            'success': True,
            'status': 'successful',
            'transaction_id': 123456,
            'amount': 50000000
        }
        
        # Use the correct URL name with app namespace
        url = reverse('payments_app:verify-land-payment', kwargs={'payment_reference': payment.payment_reference})
        
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['status'], 'completed')

    def test_payment_history(self):
        """Test retrieving payment history"""
        # Create test payments
        purchase = LandPurchase.objects.create(
            land=self.land,
            buyer=self.user,
            total_land_price=50000000
        )
        
        LandPayment.objects.create(
            purchase=purchase,
            buyer=self.user,
            amount=50000000,
            status='completed'
        )
        
        # Use the correct URL name with app namespace
        url = reverse('payments_app:payment-history')
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_unauthenticated_access(self):
        """Test that unauthenticated users cannot access payment endpoints"""
        self.client.force_authenticate(user=None)
        
        # Use the correct URL name with app namespace
        url = reverse('payments_app:initiate-land-payment', kwargs={'land_id': self.land.id})
        response = self.client.post(url, {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)