"""
SMS Service - Africa's Talking
"""

import requests
import os

# Sandbox configuration (working from your test)
SMS_API_URL = "http://api.sandbox.africastalking.com/version1/messaging"
SMS_USERNAME = "sandbox"
SMS_API_KEY = "atsk_fe1c0dcda0ed58eb254db24e1d05026faaf0a34c73148e748d6e8e8381a1d575fc556ea2"  # Replace with your actual key

def format_phone_number(phone: str) -> str:
    """Format phone number for Africa's Talking"""
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("0"):
        phone = "256" + phone[1:]
    return phone

def send_otp_sms(phone: str, otp: str) -> dict:
    """Send OTP via SMS"""
    phone = format_phone_number(phone)
    message = f"Your Boda Boda verification code is: {otp}"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "apiKey": SMS_API_KEY,
    }
    
    data = {
        "username": SMS_USERNAME,
        "to": phone,
        "message": message
    }
    
    try:
        response = requests.post(SMS_API_URL, headers=headers, data=data, timeout=30)
        
        if response.status_code == 201:
            result = response.json()
            if 'Sent' in result.get('SMSMessageData', {}).get('Message', ''):
                print(f"✅ OTP SMS sent to {phone}")
                return {"success": True, "message": "OTP sent"}
        
        print(f"❌ SMS failed: {response.text}")
        return {"success": False, "message": "SMS failed"}
        
    except Exception as e:
        print(f"❌ SMS error: {e}")
        return {"success": False, "message": str(e)}