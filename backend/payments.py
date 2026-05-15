"""
Payment Service - MTN Mobile Money & Airtel Money
For Uganda market
"""

import uuid
import requests
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

# ============================================
# CONFIGURATION
# ============================================

# For testing, use sandbox. For production, change to live URLs
MTN_API_URL = os.getenv("MTN_API_URL", "https://sandbox.mtn.co.ug")
MTN_CLIENT_ID = os.getenv("MTN_CLIENT_ID", "")  # Get from MTN after registration
MTN_CLIENT_SECRET = os.getenv("MTN_CLIENT_SECRET", "")
MTN_CALLBACK_URL = os.getenv("MTN_CALLBACK_URL", "https://boda-boda-system.onrender.com/api/payments/mtn/callback")

AIRTEL_API_URL = os.getenv("AIRTEL_API_URL", "https://openapi.airtel.ug")
AIRTEL_CLIENT_ID = os.getenv("AIRTEL_CLIENT_ID", "")
AIRTEL_CLIENT_SECRET = os.getenv("AIRTEL_CLIENT_SECRET", "")
AIRTEL_CALLBACK_URL = os.getenv("AIRTEL_CALLBACK_URL", "https://boda-boda-system.onrender.com/api/payments/airtel/callback")

# ============================================
# MTN MOBILE MONEY
# ============================================

class MTNMobileMoney:
    """MTN Mobile Money API - Uganda"""
    
    def __init__(self):
        self.access_token = None
        self.token_expiry = None
    
    async def get_token(self) -> Optional[str]:
        """Get OAuth2 access token"""
        if self.access_token:
            return self.access_token
        
        url = f"{MTN_API_URL}/collection/token/"
        
        import base64
        credentials = f"{MTN_CLIENT_ID}:{MTN_CLIENT_SECRET}"
        encoded = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                print(f"✅ MTN token obtained")
                return self.access_token
            return None
        except Exception as e:
            print(f"❌ MTN token error: {e}")
            return None
    
    async def request_payment(self, phone: str, amount: int, reference: str) -> Dict[str, Any]:
        """Request payment from customer's MTN mobile money"""
        token = await self.get_token()
        if not token:
            return {"success": False, "message": "Payment service unavailable"}
        
        # Format phone number (remove +, spaces)
        phone = phone.replace("+", "").replace(" ", "")
        
        url = f"{MTN_API_URL}/collection/v1_0/requesttopay"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Target-Environment": "sandbox",  # Change to 'production' for live
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": MTN_CLIENT_ID
        }
        
        body = {
            "amount": str(amount),
            "currency": "UGX",
            "externalId": reference,
            "payer": {
                "partyIdType": "MSISDN",
                "partyId": phone
            },
            "payerMessage": "Boda Boda Ride Payment",
            "payeeNote": f"Payment for ride {reference}"
        }
        
        try:
            response = requests.post(url, headers=headers, json=body)
            if response.status_code == 202:
                return {
                    "success": True,
                    "status": "pending",
                    "reference": reference,
                    "message": "Check your phone to complete payment"
                }
            else:
                return {"success": False, "message": "Payment request failed"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    async def check_status(self, reference: str) -> Dict[str, Any]:
        """Check payment status"""
        token = await self.get_token()
        if not token:
            return {"success": False}
        
        url = f"{MTN_API_URL}/collection/v1_0/requesttopay/{reference}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Target-Environment": "sandbox",
            "Ocp-Apim-Subscription-Key": MTN_CLIENT_ID
        }
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status": data.get("status"),
                    "transaction_id": data.get("financialTransactionId")
                }
            return {"success": False}
        except Exception as e:
            return {"success": False}

# ============================================
# AIRTEL MONEY
# ============================================

class AirtelMoney:
    """Airtel Money API - Uganda"""
    
    async def request_payment(self, phone: str, amount: int, reference: str) -> Dict[str, Any]:
        """Request payment from customer's Airtel money"""
        # Airtel API implementation
        # Similar structure to MTN
        
        # For now, return simulated response
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": "Payment initiated. Check your phone."
        }

# ============================================
# WALLET PAYMENT (Internal)
# ============================================

class WalletPayment:
    """Pay using internal wallet balance"""
    
    @staticmethod
    async def process_payment(user_id: str, amount: int, ride_id: str) -> Dict[str, Any]:
        """Process payment from wallet"""
        from database_sqlite import get_wallet_balance, update_wallet_balance, create_transaction
        
        balance = get_wallet_balance(user_id)
        
        if balance < amount:
            return {
                "success": False,
                "message": f"Insufficient balance. Available: UGX {balance}"
            }
        
        # Deduct from wallet
        if update_wallet_balance(user_id, amount, 'debit'):
            # Record transaction
            transaction = create_transaction({
                'user_id': user_id,
                'ride_id': ride_id,
                'amount': amount,
                'type': 'payment',
                'method': 'wallet',
                'status': 'completed',
                'reference': f'WALLET_{ride_id}_{int(datetime.now().timestamp())}',
                'description': f'Payment for ride {ride_id}'
            })
            
            return {
                "success": True,
                "message": f"Payment of UGX {amount} completed from wallet",
                "transaction": transaction
            }
        
        return {"success": False, "message": "Payment failed"}

# ============================================
# MAIN PAYMENT PROCESSOR
# ============================================

class PaymentProcessor:
    """Main payment processor - routes to appropriate provider"""
    
    def __init__(self):
        self.mtn = MTNMobileMoney()
        self.airtel = AirtelMoney()
        self.wallet = WalletPayment()
    
    async def process_payment(
        self, 
        method: str, 
        user_id: str, 
        amount: int, 
        ride_id: str,
        phone: str = None
    ) -> Dict[str, Any]:
        """Process payment based on method"""
        
        if method == 'wallet':
            return await self.wallet.process_payment(user_id, amount, ride_id)
        
        elif method == 'mtn':
            if not phone:
                return {"success": False, "message": "Phone number required for MTN"}
            reference = f"MTN_{ride_id}_{int(datetime.now().timestamp())}"
            return await self.mtn.request_payment(phone, amount, reference)
        
        elif method == 'airtel':
            if not phone:
                return {"success": False, "message": "Phone number required for Airtel"}
            reference = f"AIRTEL_{ride_id}_{int(datetime.now().timestamp())}"
            return await self.airtel.request_payment(phone, amount, reference)
        
        elif method == 'cash':
            # Cash payment - record but no API call
            from database_sqlite import create_transaction
            transaction = create_transaction({
                'user_id': user_id,
                'ride_id': ride_id,
                'amount': amount,
                'type': 'payment',
                'method': 'cash',
                'status': 'completed',
                'reference': f'CASH_{ride_id}_{int(datetime.now().timestamp())}',
                'description': f'Cash payment for ride {ride_id}'
            })
            return {
                "success": True,
                "message": "Cash payment recorded",
                "transaction": transaction
            }
        
        else:
            return {"success": False, "message": f"Unknown payment method: {method}"}

payment_processor = PaymentProcessor()