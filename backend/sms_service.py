"""
SMS Service - Africa's Talking
"""

import requests
import os

# Sandbox configuration (using HTTP for sandbox)
SMS_API_URL = "http://api.sandbox.africastalking.com/version1/messaging"
SMS_USERNAME = "sandbox"
SMS_API_KEY = "atsk_fe1c0dcda0ed58eb254db24e1d05026faaf0a34c73148e748d6e8e8381a1d575fc556ea2"  # ← REPLACE with your actual key

def format_phone_number(phone: str) -> str:
    """Format phone number for Africa's Talking"""
    # Remove spaces, dashes, and plus sign
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    
    # If starts with 0 (local format), add Uganda code
    if phone.startswith("0"):
        phone = "256" + phone[1:]
    
    # If doesn't start with 256 and is 9 digits, add it
    if not phone.startswith("256") and len(phone) == 9:
        phone = "256" + phone
    
    return phone

def send_otp_sms(phone: str, otp: str) -> dict:
    """
    Send OTP verification code via SMS
    Returns: {"success": bool, "message": str}
    """
    phone = format_phone_number(phone)
    message = f"Your Boda Boda verification code is: {otp}"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "apiKey": SMS_API_KEY,
    }
    
    # IMPORTANT: No "from" field for sandbox
    data = {
        "username": SMS_USERNAME,
        "to": phone,
        "message": message
    }
    
    try:
        response = requests.post(SMS_API_URL, headers=headers, data=data, timeout=30)
        
        if response.status_code == 201:
            result = response.json()
            msg_data = result.get('SMSMessageData', {})
            
            if 'Sent' in msg_data.get('Message', ''):
                print(f"✅ OTP SMS sent to {phone}")
                return {"success": True, "message": "OTP sent via SMS"}
            else:
                print(f"⚠️ SMS response: {msg_data.get('Message')}")
                return {"success": False, "message": "SMS sending failed"}
        else:
            print(f"❌ SMS API error: {response.status_code}")
            return {"success": False, "message": f"SMS API error: {response.status_code}"}
            
    except requests.exceptions.Timeout:
        print("❌ SMS timeout")
        return {"success": False, "message": "SMS service timeout"}
    except requests.exceptions.ConnectionError:
        print("❌ SMS connection error")
        return {"success": False, "message": "Cannot connect to SMS service"}
    except Exception as e:
        print(f"❌ SMS error: {e}")
        return {"success": False, "message": str(e)}