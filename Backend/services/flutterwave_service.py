# payments/services/secure_flutterwave_service.py
import requests
import json
import logging
import hmac
import hashlib
import time
from django.conf import settings
from django.utils import timezone
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import secrets

from payments_app.models import LandPayment, PaymentAttempt

logger = logging.getLogger(__name__)

class FlutterwaveService:
    """
    Secure Flutterwave service implementation with enhanced security features
    """
    
    def __init__(self):
        self.secret_key = settings.FLUTTERWAVE_SECRET_KEY
        self.public_key = settings.FLUTTERWAVE_PUBLIC_KEY
        self.base_url = "https://api.flutterwave.com/v3"
        self.webhook_hash = settings.FLUTTERWAVE_WEBHOOK_HASH
        
        # Request timeout (seconds)
        self.timeout = 30
        
        # Initialize encryption
        self.cipher_suite = self._initialize_encryption()
        
        # Request headers with security enhancements
        self.headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'MyHouse-API/1.0',
            'X-Client-ID': 'myhouse-land-sales'
        }
    
    def _initialize_encryption(self):
        """Initialize Fernet encryption with key derivation"""
        try:
            # Derive key for additional security
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b'myhouse_land_sales_salt',
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(settings.FLUTTERWAVE_ENCRYPTION_KEY.encode()))
            return Fernet(key)
        except Exception as e:
            logger.error(f"Encryption initialization failed: {e}")
            raise
    
    def _generate_secure_reference(self, prefix):
        """Generate secure transaction reference"""
        timestamp = int(time.time())
        random_part = secrets.token_urlsafe(8)
        return f"{prefix}_{timestamp}_{random_part}"
    
    def _validate_input_amount(self, amount):
        """Validate and sanitize payment amount"""
        try:
            amount_float = float(amount)
            if amount_float <= 0:
                raise ValueError("Amount must be positive")
            if amount_float > 100000000:  # 100 million limit
                raise ValueError("Amount exceeds maximum limit")
            return amount_float
        except (ValueError, TypeError):
            raise ValueError("Invalid amount format")
    
    def _sanitize_customer_data(self, customer_data):
        """Sanitize and validate customer data"""
        required_fields = ['email', 'name']
        for field in required_fields:
            if field not in customer_data or not customer_data[field]:
                raise ValueError(f"Missing required customer field: {field}")
        
        # Basic email validation
        if '@' not in customer_data['email']:
            raise ValueError("Invalid email format")
        
        return {
            'email': customer_data['email'].strip().lower(),
            'name': customer_data['name'].strip()[:200],
            'phonenumber': customer_data.get('phonenumber', '').strip()[:20]
        }
    
    def _make_secure_request(self, url, method='POST', payload=None):
        """Make secure HTTP request with timeout and retry logic"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout,
                    verify=True  # Always verify SSL
                )
                
                # Log request for audit (without sensitive data)
                safe_payload = payload.copy() if payload else {}
                if 'card_details' in safe_payload:
                    safe_payload['card_details'] = '***REDACTED***'
                
                logger.info(f"Flutterwave API Request: {method} {url} - Attempt {attempt + 1}")
                
                return response
                
            except requests.exceptions.Timeout:
                logger.warning(f"Flutterwave API timeout (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                continue
                
            except requests.exceptions.SSLError as e:
                logger.error(f"SSL error in Flutterwave request: {e}")
                raise Exception("Secure connection failed")
                
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Connection error in Flutterwave request: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                continue
                
            except Exception as e:
                logger.error(f"Unexpected error in Flutterwave request: {e}")
                raise
        
        raise Exception("Max retries exceeded for Flutterwave API")
    
    def initialize_payment(self, payment_data):
        """
        Securely initialize payment with Flutterwave
        """
        try:
            # Input validation
            if not payment_data.get('tx_ref'):
                raise ValueError("Transaction reference is required")
            
            amount = self._validate_input_amount(payment_data['amount'])
            customer = self._sanitize_customer_data({
                'email': payment_data['customer_email'],
                'name': payment_data['customer_name'],
                'phonenumber': payment_data.get('customer_phone', '')
            })
            
            # Construct secure payload
            payload = {
                "tx_ref": payment_data['tx_ref'],
                "amount": amount,
                "currency": payment_data.get('currency', 'NGN'),
                "redirect_url": payment_data['redirect_url'],
                "customer": customer,
                "customizations": {
                    "title": "MyHouse Land Sales",
                    "description": payment_data.get('description', 'Land Purchase Payment'),
                    "logo": "https://myhouse.ng/static/logo.png"
                },
                "meta": {
                    **payment_data.get('metadata', {}),
                    "security_token": self._generate_security_token(),
                    "integration_type": "land_sales"
                }
            }
            
            # Add payment method restrictions for security
            if payment_data.get('payment_method'):
                allowed_methods = ['card', 'banktransfer', 'mobilemoney']
                if payment_data['payment_method'] in allowed_methods:
                    payload["payment_options"] = payment_data['payment_method']
                else:
                    logger.warning(f"Restricted payment method attempted: {payment_data['payment_method']}")
            
            url = f"{self.base_url}/payments"
            response = self._make_secure_request(url, 'POST', payload)
            response_data = response.json()
            
            # Secure logging (redact sensitive information)
            log_data = response_data.copy()
            if 'data' in log_data and 'link' in log_data['data']:
                log_data['data']['link'] = '***REDACTED***'
            
            logger.info(f"Payment initialization response: {log_data}")
            
            if response.status_code == 200 and response_data['status'] == 'success':
                return {
                    'success': True,
                    'payment_link': response_data['data']['link'],
                    'tx_ref': payload['tx_ref'],
                    'flw_ref': response_data['data']['flw_ref'],
                    'security_token': payload['meta']['security_token']
                }
            else:
                error_msg = response_data.get('message', 'Payment initialization failed')
                logger.error(f"Flutterwave initialization failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'code': response_data.get('status', 'error'),
                    'gateway_response': response_data
                }
                
        except ValueError as e:
            logger.error(f"Input validation error: {e}")
            return {
                'success': False,
                'error': str(e),
                'code': 'validation_error'
            }
        except Exception as e:
            logger.error(f"Payment initialization error: {str(e)}")
            return {
                'success': False,
                'error': 'Payment gateway temporarily unavailable',
                'code': 'service_unavailable'
            }
    
    def verify_payment(self, transaction_id):
        """
        Securely verify payment status
        """
        try:
            if not transaction_id:
                raise ValueError("Transaction ID is required")
            
            url = f"{self.base_url}/transactions/{transaction_id}/verify"
            response = self._make_secure_request(url, 'GET')
            response_data = response.json()
            
            if response.status_code == 200 and response_data['status'] == 'success':
                transaction_data = response_data['data']
                
                # Additional security validation
                if not self._validate_transaction_data(transaction_data):
                    raise Exception("Transaction data validation failed")
                
                verification_result = {
                    'success': True,
                    'transaction_id': transaction_data['id'],
                    'tx_ref': transaction_data['tx_ref'],
                    'amount': transaction_data['amount'],
                    'currency': transaction_data['currency'],
                    'status': transaction_data['status'],
                    'payment_type': transaction_data['payment_type'],
                    'created_at': transaction_data['created_at'],
                    'customer': transaction_data['customer'],
                    'flw_ref': transaction_data['flw_ref'],
                    'device_fingerprint': transaction_data.get('device_fingerprint'),
                    'ip': transaction_data.get('ip')
                }
                
                logger.info(f"Payment verified securely: {transaction_data['tx_ref']}")
                return verification_result
            else:
                error_msg = response_data.get('message', 'Verification failed')
                logger.error(f"Payment verification failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'code': response_data.get('status', 'error')
                }
                
        except Exception as e:
            logger.error(f"Payment verification error: {str(e)}")
            return {
                'success': False,
                'error': 'Payment verification temporarily unavailable',
                'code': 'service_unavailable'
            }
    
    def verify_payment_by_reference(self, tx_ref):
        """
        Verify payment using transaction reference (additional security layer)
        """
        try:
            url = f"{self.base_url}/transactions/verify_by_reference"
            payload = {"tx_ref": tx_ref}
            
            response = self._make_secure_request(url, 'POST', payload)
            response_data = response.json()
            
            if response.status_code == 200 and response_data['status'] == 'success':
                return self.verify_payment(response_data['data']['id'])
            else:
                return {
                    'success': False,
                    'error': 'Transaction not found',
                    'code': 'not_found'
                }
                
        except Exception as e:
            logger.error(f"Reference verification error: {str(e)}")
            return {
                'success': False,
                'error': 'Verification service unavailable',
                'code': 'service_unavailable'
            }
    
    def handle_webhook(self, webhook_data, signature):
        """
        Securely handle Flutterwave webhook with signature verification
        """
        try:
            # Verify webhook signature
            if not self.verify_webhook_signature(webhook_data, signature):
                logger.error("Webhook signature verification failed")
                return False
            
            # Validate webhook data structure
            if not self._validate_webhook_data(webhook_data):
                logger.error("Webhook data validation failed")
                return False
            
            event_type = webhook_data.get('event')
            data = webhook_data.get('data', {})
            
            logger.info(f"Processing secure webhook: {event_type}")
            
            # Rate limiting check for webhooks
            if not self._check_webhook_rate_limit(data.get('tx_ref')):
                logger.warning(f"Webhook rate limit exceeded for: {data.get('tx_ref')}")
                return True  # Still return 200 to prevent retries
            
            if event_type == 'charge.completed':
                return self._handle_successful_payment(data)
            elif event_type == 'charge.failed':
                return self._handle_failed_payment(data)
            elif event_type in ['transfer.completed', 'transfer.reversed']:
                return self._handle_transfer_event(data, event_type)
            else:
                logger.info(f"Unhandled webhook event (logged): {event_type}")
                return True  # Return success for unhandled but valid events
                
        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            return False
    
    def verify_webhook_signature(self, webhook_data, signature):
        """
        Verify Flutterwave webhook signature for security
        """
        try:
            if not signature:
                logger.error("Missing webhook signature")
                return False
            
            # Flutterwave's webhook verification
            expected_signature = hmac.new(
                self.webhook_hash.encode(),
                json.dumps(webhook_data, separators=(',', ':')).encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Use constant-time comparison to prevent timing attacks
            return hmac.compare_digest(expected_signature, signature)
            
        except Exception as e:
            logger.error(f"Webhook signature verification error: {e}")
            return False
    
    def _validate_webhook_data(self, webhook_data):
        """Validate webhook data structure"""
        required_fields = ['event', 'data']
        for field in required_fields:
            if field not in webhook_data:
                return False
        
        if 'data' in webhook_data and 'tx_ref' not in webhook_data['data']:
            return False
            
        return True
    
    def _validate_transaction_data(self, transaction_data):
        """Validate transaction data for security"""
        required_fields = ['id', 'tx_ref', 'amount', 'status', 'currency']
        for field in required_fields:
            if field not in transaction_data:
                return False
        
        # Validate amount is reasonable
        try:
            amount = float(transaction_data['amount'])
            if amount <= 0 or amount > 100000000:  # 100 million limit
                return False
        except (ValueError, TypeError):
            return False
            
        return True
    
    def _check_webhook_rate_limit(self, tx_ref):
        """Implement webhook rate limiting"""
        # Implement your rate limiting logic here
        # This could use Redis or database-based rate limiting
        return True  # Placeholder
    
    def _generate_security_token(self):
        """Generate security token for additional verification"""
        return secrets.token_urlsafe(16)
    def _handle_successful_payment(self, data):
        """Handle successful payment webhook - SIMPLIFIED"""
        try:
            tx_ref = data.get('tx_ref')
            
            # Find payment record
            payment = LandPayment.objects.get(flutterwave_tx_ref=tx_ref)
            
            # Find and update the latest payment attempt
            attempt = payment.attempts.filter(flutterwave_tx_ref=tx_ref).first()
            if attempt:
                attempt.mark_completed(data)
            
            # Update payment status
            payment.status = 'completed'
            payment.paid_date = timezone.now()
            payment.flutterwave_transaction_id = data.get('id')
            payment.flutterwave_response = data
            payment.payment_method = data.get('payment_type', '')
            payment.save()
            
            # Trigger post-payment actions
            self._trigger_secure_post_payment_actions(payment)
            
            logger.info(f"Payment completed: {tx_ref}")
            return True
            
        except LandPayment.DoesNotExist:
            logger.error(f"Payment not found for tx_ref: {tx_ref}")
            return False

    def _handle_failed_payment(self, data):
        """Handle failed payment webhook - SIMPLIFIED"""
        try:
            tx_ref = data.get('tx_ref')
            payment = LandPayment.objects.get(flutterwave_tx_ref=tx_ref)
            
            # Find and update the latest payment attempt
            attempt = payment.attempts.filter(flutterwave_tx_ref=tx_ref).first()
            if attempt:
                attempt.mark_failed(
                    error_message=data.get('processor_response', 'Payment failed'),
                    gateway_data=data
                )
            
            payment.status = 'failed'
            payment.flutterwave_response = data
            payment.save()
            
            logger.warning(f"Payment failed: {tx_ref}")
            return True
            
        except LandPayment.DoesNotExist:
            logger.error(f"Payment not found for failed tx_ref: {tx_ref}")
            return False
        
    def _handle_transfer_event(self, data, event_type):
        """Handle transfer events (payouts) securely"""
        try:
            # Implement secure transfer handling
            logger.info(f"Transfer event {event_type} processed: {data.get('reference')}")
            return True
        except Exception as e:
            logger.error(f"Transfer event handling error: {str(e)}")
            return False
    
    def encrypt_sensitive_data(self, data):
        """Encrypt sensitive data before storage"""
        try:
            sensitive_fields = ['card', 'account', 'authorization', 'customer']
            encrypted_data = data.copy()
            
            for field in sensitive_fields:
                if field in encrypted_data:
                    encrypted_data[field] = self.cipher_suite.encrypt(
                        json.dumps(encrypted_data[field]).encode()
                    ).decode()
            
            return encrypted_data
        except Exception as e:
            logger.error(f"Data encryption error: {e}")
            return data
    
    def decrypt_sensitive_data(self, encrypted_data):
        """Decrypt sensitive data when needed"""
        try:
            decrypted_data = encrypted_data.copy()
            sensitive_fields = ['card', 'account', 'authorization', 'customer']
            
            for field in sensitive_fields:
                if field in decrypted_data and isinstance(decrypted_data[field], str):
                    decrypted_data[field] = json.loads(
                        self.cipher_suite.decrypt(decrypted_data[field].encode()).decode()
                    )
            
            return decrypted_data
        except Exception as e:
            logger.error(f"Data decryption error: {e}")
            return encrypted_data
    
    def _trigger_secure_post_payment_actions(self, payment):
        """Trigger secure post-payment actions"""
        from payments_app.tasks import (
            generate_land_payment_receipt,
            send_land_payment_confirmation,
            update_land_purchase_status,
            notify_sales_team_secure
        )
        
        # Use task IDs for tracking
        generate_land_payment_receipt.delay(payment.id)
        send_land_payment_confirmation.delay(payment.id)
        update_land_purchase_status.delay(payment.purchase.id)
        notify_sales_team_secure.delay(payment.purchase.id)
    
    def get_transaction_history(self, customer_email, days=30):
        """Get transaction history with security checks"""
        try:
            from datetime import timedelta
            url = f"{self.base_url}/transactions"
            params = {
                'email': customer_email,
                'from': (timezone.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
                'to': timezone.now().strftime('%Y-%m-%d')
            }
            
            response = self._make_secure_request(url, 'GET', payload=None)
            response_data = response.json()
            
            if response_data['status'] == 'success':
                return {
                    'success': True,
                    'transactions': response_data['data'],
                    'total': len(response_data['data'])
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to fetch transaction history'
                }
                
        except Exception as e:
            logger.error(f"Transaction history error: {str(e)}")
            return {
                'success': False,
                'error': 'Failed to fetch transaction history'
            }