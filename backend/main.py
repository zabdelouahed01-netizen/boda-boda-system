"""
MAIN BACKEND SERVER - COMPLETE WITH PHASE 3 FEATURES
- Admin Dashboard
- Driver Analytics
- Support Chat
- Surge Pricing
- Referral System
"""

import json
import uuid
import math
import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

# ============================================
# DATABASE SETUP
# ============================================

import sqlite3

DB_PATH = "boda_system.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            name TEXT,
            role TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0,
            rating REAL DEFAULT 0,
            total_rides INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Drivers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE,
            license_number TEXT UNIQUE,
            bike_registration TEXT UNIQUE,
            bike_model TEXT,
            bike_color TEXT,
            is_approved INTEGER DEFAULT 0,
            is_online INTEGER DEFAULT 0,
            current_lat REAL,
            current_lng REAL,
            total_earnings INTEGER DEFAULT 0,
            today_earnings INTEGER DEFAULT 0,
            rides_today INTEGER DEFAULT 0,
            rating REAL DEFAULT 0,
            total_rides INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Rides table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rides (
            id TEXT PRIMARY KEY,
            customer_id TEXT,
            driver_id TEXT,
            pickup_lat REAL,
            pickup_lng REAL,
            pickup_address TEXT,
            destination_lat REAL,
            destination_lng REAL,
            destination_address TEXT,
            distance_km REAL,
            fare INTEGER,
            original_fare INTEGER,
            surge_multiplier REAL DEFAULT 1.0,
            status TEXT,
            customer_rating INTEGER DEFAULT 0,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accepted_at TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES users(id),
            FOREIGN KEY (driver_id) REFERENCES users(id)
        )
    ''')
    
    # OTP table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            code TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Ratings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ride_id TEXT,
            driver_id TEXT,
            customer_id TEXT,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Wallet table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallets (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE NOT NULL,
            balance INTEGER DEFAULT 0,
            total_deposited INTEGER DEFAULT 0,
            total_withdrawn INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            ride_id TEXT,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            method TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reference TEXT UNIQUE NOT NULL,
            provider_reference TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (ride_id) REFERENCES rides(id)
        )
    ''')
    
    # Payouts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payouts (
            id TEXT PRIMARY KEY,
            driver_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            phone TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reference TEXT UNIQUE NOT NULL,
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES users(id)
        )
    ''')
    
    # Referrals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id TEXT PRIMARY KEY,
            referrer_id TEXT NOT NULL,
            referred_id TEXT NOT NULL,
            referrer_name TEXT,
            referred_name TEXT,
            status TEXT DEFAULT 'pending',
            reward INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id)
        )
    ''')
    
    # Support Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            message TEXT NOT NULL,
            from_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database ready")

# ============================================
# DATABASE FUNCTIONS
# ============================================

def create_user(phone: str, name: str, role: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return dict(existing)
    user_id = str(uuid.uuid4())[:8]
    referral_code = str(uuid.uuid4())[:8].upper()
    cursor.execute('INSERT INTO users (id, phone, name, role, is_verified, referral_code) VALUES (?, ?, ?, ?, 0, ?)', 
                   (user_id, phone, name, role, referral_code))
    conn.commit()
    
    # Create wallet
    wallet_id = str(uuid.uuid4())[:8]
    cursor.execute('INSERT INTO wallets (id, user_id, balance) VALUES (?, ?, 0)', (wallet_id, user_id))
    
    conn.commit()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user)

def get_user_by_phone(phone: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_id(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def verify_user(phone: str, is_verified: bool = True):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_verified = ? WHERE phone = ?", (1 if is_verified else 0, phone))
    conn.commit()
    conn.close()

def update_driver_rating(driver_id: str, new_rating: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rating, total_rides FROM users WHERE id = ?", (driver_id,))
    user = cursor.fetchone()
    if user:
        current_rating = user[0] or 0
        total_rides = user[1] or 0
        new_avg = ((current_rating * total_rides) + new_rating) / (total_rides + 1) if total_rides > 0 else new_rating
        cursor.execute("UPDATE users SET rating = ? WHERE id = ?", (round(new_avg, 1), driver_id))
        cursor.execute("UPDATE drivers SET rating = ?, total_rides = total_rides + 1 WHERE user_id = ?", 
                       (round(new_avg, 1), driver_id))
        conn.commit()
    conn.close()

def get_driver_rating(driver_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rating, total_rides FROM users WHERE id = ?", (driver_id,))
    user = cursor.fetchone()
    conn.close()
    return {'rating': user[0] or 0, 'total_rides': user[1] or 0} if user else {'rating': 0, 'total_rides': 0}

def generate_otp(phone: str) -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM otps WHERE phone = ?", (phone,))
    code = str(random.randint(100000, 999999))
    expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()
    cursor.execute('INSERT INTO otps (phone, code, expires_at) VALUES (?, ?, ?)', (phone, code, expires_at))
    conn.commit()
    conn.close()
    print(f"📱 OTP for {phone}: {code}")
    return code

def verify_otp(phone: str, code: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM otps WHERE phone = ? AND code = ? AND expires_at > ?', 
                   (phone, code, datetime.now().isoformat()))
    otp = cursor.fetchone()
    if otp:
        cursor.execute("DELETE FROM otps WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def update_driver_location(user_id: str, lat: float, lng: float, is_online: bool = True):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers WHERE user_id = ?", (user_id,))
    driver = cursor.fetchone()
    if not driver:
        driver_id = str(uuid.uuid4())[:8]
        cursor.execute('INSERT INTO drivers (id, user_id, is_approved, is_online, current_lat, current_lng) VALUES (?, ?, 1, ?, ?, ?)',
                       (driver_id, user_id, 1 if is_online else 0, lat, lng))
    else:
        cursor.execute('UPDATE drivers SET current_lat = ?, current_lng = ?, is_online = ? WHERE user_id = ?',
                       (lat, lng, 1 if is_online else 0, user_id))
    conn.commit()
    conn.close()

def save_ride(ride_data: dict):
    conn = get_db()
    cursor = conn.cursor()
    ride_id = ride_data.get('id', str(uuid.uuid4())[:8])
    cursor.execute('''
        INSERT OR REPLACE INTO rides (
            id, customer_id, driver_id, pickup_lat, pickup_lng,
            destination_lat, destination_lng, distance_km, fare, original_fare, surge_multiplier, status,
            requested_at, accepted_at, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ride_id, ride_data.get('customer_id'), ride_data.get('driver_id'),
        ride_data.get('pickup_lat'), ride_data.get('pickup_lng'),
        ride_data.get('destination_lat'), ride_data.get('destination_lng'),
        ride_data.get('distance_km'), ride_data.get('fare'), ride_data.get('original_fare'),
        ride_data.get('surge_multiplier', 1.0),
        ride_data.get('status', 'completed'),
        ride_data.get('requested_at', datetime.now().isoformat()),
        ride_data.get('accepted_at'), ride_data.get('started_at'),
        ride_data.get('completed_at', datetime.now().isoformat())
    ))
    cursor.execute('UPDATE drivers SET total_earnings = total_earnings + ?, rides_today = rides_today + 1 WHERE user_id = ?',
                   (ride_data.get('fare', 0), ride_data.get('driver_id')))
    cursor.execute('UPDATE users SET total_rides = total_rides + 1 WHERE id = ?', (ride_data.get('customer_id'),))
    conn.commit()
    conn.close()
    print(f"💾 Ride {ride_id} saved")

# ============================================
# WALLET FUNCTIONS
# ============================================

def get_or_create_wallet(user_id: str) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,))
    wallet = cursor.fetchone()
    if not wallet:
        wallet_id = str(uuid.uuid4())[:8]
        cursor.execute('INSERT INTO wallets (id, user_id, balance) VALUES (?, ?, 0)', (wallet_id, user_id))
        conn.commit()
        cursor.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,))
        wallet = cursor.fetchone()
    conn.close()
    return dict(wallet)

def get_wallet_balance(user_id: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def update_wallet_balance(user_id: str, amount: int, transaction_type: str = 'credit') -> bool:
    conn = get_db()
    cursor = conn.cursor()
    if transaction_type == 'credit':
        cursor.execute('UPDATE wallets SET balance = balance + ?, total_deposited = total_deposited + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                       (amount, amount, user_id))
    else:
        cursor.execute('UPDATE wallets SET balance = balance - ?, total_withdrawn = total_withdrawn + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND balance >= ?',
                       (amount, amount, user_id, amount))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def create_transaction(transaction_data: dict) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    transaction_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO transactions (
            id, user_id, ride_id, amount, type, method, 
            status, reference, provider_reference, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        transaction_id, transaction_data.get('user_id'), transaction_data.get('ride_id'),
        transaction_data.get('amount'), transaction_data.get('type'), transaction_data.get('method'),
        transaction_data.get('status', 'pending'), transaction_data.get('reference'),
        transaction_data.get('provider_reference'), transaction_data.get('description')
    ))
    conn.commit()
    cursor.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
    transaction = cursor.fetchone()
    conn.close()
    return dict(transaction)

def get_transactions(user_id: str, limit: int = 50) -> list:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?', (user_id, limit))
    transactions = cursor.fetchall()
    conn.close()
    return [dict(t) for t in transactions]

# ============================================
# SURGE PRICING
# ============================================

# Surge zones configuration (can be modified via admin)
SURGE_ZONES = [
    {"name": "Kampala CBD", "lat": 0.3136, "lng": 32.5811, "radius": 3, "multiplier": 1.5, "active": True},
    {"name": "Entebbe Road", "lat": 0.2953, "lng": 32.5836, "radius": 2, "multiplier": 1.3, "active": True},
]

PEAK_HOURS = [
    {"start": 7, "end": 9, "multiplier": 1.4, "active": True},
    {"start": 17, "end": 19, "multiplier": 1.6, "active": True},
    {"start": 12, "end": 14, "multiplier": 1.2, "active": True},
]

def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 2)

def calculate_surge_multiplier(lat: float, lng: float) -> float:
    """Calculate surge multiplier based on location and time"""
    multiplier = 1.0
    
    # Check location-based surge
    for zone in SURGE_ZONES:
        if zone.get('active', True):
            distance = calculate_distance(lat, lng, zone['lat'], zone['lng'])
            if distance <= zone['radius']:
                multiplier = max(multiplier, zone['multiplier'])
    
    # Check time-based surge
    hour = datetime.now().hour
    for peak in PEAK_HOURS:
        if peak.get('active', True) and peak['start'] <= hour <= peak['end']:
            multiplier = max(multiplier, peak['multiplier'])
    
    return multiplier

def calculate_fare(distance_km: float, lat: float = None, lng: float = None) -> int:
    BASE_FARE = 5000
    PER_KM_RATE = 2000
    
    base_fare = BASE_FARE + (distance_km * PER_KM_RATE)
    
    if lat is not None and lng is not None:
        surge_multiplier = calculate_surge_multiplier(lat, lng)
        final_fare = base_fare * surge_multiplier
    else:
        final_fare = base_fare
    
    final_fare = max(final_fare, BASE_FARE)
    return int(round(final_fare / 500) * 500)

# ============================================
# REFERRAL FUNCTIONS
# ============================================

def create_referral(referrer_id: str, referred_id: str, referrer_name: str = None, referred_name: str = None):
    conn = get_db()
    cursor = conn.cursor()
    referral_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO referrals (id, referrer_id, referred_id, referrer_name, referred_name, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    ''', (referral_id, referrer_id, referred_id, referrer_name, referred_name))
    conn.commit()
    conn.close()
    return referral_id

def complete_referral(referral_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM referrals WHERE id = ?', (referral_id,))
    referral = cursor.fetchone()
    if referral:
        BONUS_AMOUNT = 5000
        update_wallet_balance(referral['referrer_id'], BONUS_AMOUNT, 'credit')
        update_wallet_balance(referral['referred_id'], BONUS_AMOUNT, 'credit')
        cursor.execute('''
            UPDATE referrals SET status = 'completed', reward = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (BONUS_AMOUNT, referral_id))
        conn.commit()
    conn.close()

def get_referral_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM referrals')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE status = "completed"')
    completed = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(reward) FROM referrals WHERE status = "completed"')
    rewards = cursor.fetchone()[0] or 0
    conn.close()
    return {'total': total, 'completed': completed, 'rewards': rewards}

# ============================================
# SUPPORT FUNCTIONS
# ============================================

def save_support_message(user_id: str, message: str, from_admin: bool = False):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO support_messages (user_id, message, from_admin)
        VALUES (?, ?, ?)
    ''', (user_id, message, 1 if from_admin else 0))
    conn.commit()
    conn.close()

def get_support_messages(user_id: str, limit: int = 50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM support_messages WHERE user_id = ? ORDER BY created_at ASC LIMIT ?
    ''', (user_id, limit))
    messages = cursor.fetchall()
    conn.close()
    return [dict(m) for m in messages]

# ============================================
# DRIVER ANALYTICS
# ============================================

def get_driver_analytics(driver_id: str):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all rides
    cursor.execute('''
        SELECT 
            COUNT(*) as total_rides,
            AVG(customer_rating) as avg_rating,
            AVG(strftime('%s', accepted_at) - strftime('%s', requested_at)) as avg_response,
            SUM(fare) as total_earnings
        FROM rides WHERE driver_id = ? AND status = 'completed'
    ''', (driver_id,))
    result = cursor.fetchone()
    
    # Weekly rides
    cursor.execute('''
        SELECT COUNT(*) FROM rides 
        WHERE driver_id = ? AND status = 'completed' 
        AND requested_at > datetime('now', '-7 days')
    ''', (driver_id,))
    weekly_rides = cursor.fetchone()[0]
    
    # Peak hour analysis
    cursor.execute('''
        SELECT strftime('%H', requested_at) as hour, COUNT(*) 
        FROM rides WHERE driver_id = ? GROUP BY hour ORDER BY COUNT(*) DESC LIMIT 1
    ''', (driver_id,))
    peak = cursor.fetchone()
    
    conn.close()
    
    return {
        'total_rides': result[0] or 0,
        'avg_rating': round(result[1] or 0, 1),
        'avg_response_time': round(result[2] or 0, 1),
        'total_earnings': result[3] or 0,
        'weekly_rides': weekly_rides,
        'peak_hour': int(peak[0]) if peak else 17,
        'completion_rate': 98  # Calculate from actual data
    }

# ============================================
# STORAGE
# ============================================

driver_locations = {}
online_drivers = set()
pending_rides = {}
active_rides = {}
connections = {}

# ============================================
# FASTAPI APP
# ============================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bodacustomer.netlify.app",
        "https://bodadriver.netlify.app",
        "https://boda-boda-system.onrender.com",
        "http://localhost:3000",
        "http://localhost:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.on_event("startup")
async def startup_event():
    init_db()
    print("✅ Database initialized")

# ============================================
# CONNECTION MANAGER
# ============================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"✅ {user_id} connected")
    
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"❌ {user_id} disconnected")
    
    async def send(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except:
                self.disconnect(user_id)
        return False

manager = ConnectionManager()

# ============================================
# AUTHENTICATION ENDPOINTS
# ============================================

@app.post("/api/send-otp")
async def send_otp_endpoint(request: dict):
    phone = request.get('phone')
    print(f"📱 Send OTP request for: {phone}")
    if not phone:
        return {"success": False, "message": "Phone number required"}
    otp_code = generate_otp(phone)
    return {"success": True, "message": "OTP sent successfully", "otp": otp_code}

@app.post("/api/verify-otp")
async def verify_otp_endpoint(request: dict):
    phone = request.get('phone')
    code = request.get('code')
    name = request.get('name', '')
    role = request.get('role', 'customer')
    referral_code = request.get('referral_code')
    
    if not phone or not code:
        return {"success": False, "message": "Phone and OTP required"}
    
    if verify_otp(phone, code):
        user = get_user_by_phone(phone)
        
        if not user:
            user = create_user(phone, name, role)
            
            # Apply referral if provided
            if referral_code:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM users WHERE referral_code = ?", (referral_code,))
                referrer = cursor.fetchone()
                if referrer:
                    create_referral(referrer['id'], user['id'], referrer['name'], name)
                    complete_referral(referrer['id'])
                conn.close()
        
        verify_user(phone, True)
        get_or_create_wallet(user['id'])
        
        return {
            "success": True,
            "user": {
                "id": user['id'],
                "phone": user['phone'],
                "name": user['name'],
                "role": user['role'],
                "is_verified": user['is_verified'],
                "referral_code": user.get('referral_code', '')
            }
        }
    else:
        return {"success": False, "message": "Invalid or expired OTP"}

@app.get("/api/driver/rating/{driver_id}")
async def get_driver_rating_endpoint(driver_id: str):
    rating = get_driver_rating(driver_id)
    return {"success": True, "rating": rating['rating'], "total_rides": rating['total_rides']}

@app.get("/api/driver/analytics/{driver_id}")
async def get_driver_analytics_endpoint(driver_id: str):
    analytics = get_driver_analytics(driver_id)
    return {"success": True, "analytics": analytics}

@app.get("/api/user/referral/{user_id}")
async def get_user_referral_code(user_id: str):
    user = get_user_by_id(user_id)
    if user:
        return {"success": True, "referral_code": user.get('referral_code', '')}
    return {"success": False, "message": "User not found"}

# ============================================
# WALLET ENDPOINTS
# ============================================

@app.get("/api/wallet/{user_id}")
async def get_wallet(user_id: str):
    wallet = get_or_create_wallet(user_id)
    return {
        "success": True,
        "balance": wallet['balance'],
        "total_deposited": wallet['total_deposited'],
        "total_withdrawn": wallet['total_withdrawn']
    }

@app.post("/api/wallet/deposit")
async def deposit_to_wallet(request: dict):
    user_id = request.get('user_id')
    amount = request.get('amount')
    method = request.get('method', 'mtn')
    phone = request.get('phone')
    
    if not user_id or not amount or not phone:
        return {"success": False, "message": "Missing required fields"}
    
    if amount < 5000:
        return {"success": False, "message": "Minimum deposit is UGX 5,000"}
    
    reference = f"DEPOSIT_{user_id}_{int(datetime.now().timestamp())}"
    
    create_transaction({
        'user_id': user_id,
        'amount': amount,
        'type': 'deposit',
        'method': method,
        'status': 'completed',
        'reference': reference,
        'description': f'Deposit of UGX {amount} via {method.upper()}'
    })
    
    update_wallet_balance(user_id, amount, 'credit')
    
    return {
        "success": True,
        "message": f"Successfully deposited UGX {amount}",
        "reference": reference
    }

@app.post("/api/payments/process-ride")
async def process_ride_payment(request: dict):
    user_id = request.get('user_id')
    ride_id = request.get('ride_id')
    amount = request.get('amount')
    method = request.get('method', 'wallet')
    phone = request.get('phone')
    
    if not user_id or not ride_id or not amount:
        return {"success": False, "message": "Missing required fields"}
    
    reference = f"PAYMENT_{ride_id}_{int(datetime.now().timestamp())}"
    
    if method == 'wallet':
        balance = get_wallet_balance(user_id)
        if balance < amount:
            return {"success": False, "message": f"Insufficient wallet balance. Available: UGX {balance}"}
        
        update_wallet_balance(user_id, amount, 'debit')
        create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': 'wallet',
            'status': 'completed',
            'reference': reference,
            'description': f'Payment for ride {ride_id}'
        })
        
        return {"success": True, "message": f"Payment of UGX {amount} completed from wallet", "reference": reference}
    
    elif method == 'cash':
        create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': 'cash',
            'status': 'completed',
            'reference': reference,
            'description': f'Cash payment for ride {ride_id}'
        })
        return {"success": True, "message": "Cash payment recorded", "reference": reference}
    
    elif method in ['mtn', 'airtel']:
        if not phone:
            return {"success": False, "message": "Phone number required for mobile money"}
        
        create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': method,
            'status': 'completed',
            'reference': reference,
            'description': f'Payment for ride {ride_id} via {method.upper()}'
        })
        
        return {"success": True, "message": f"Payment initiated via {method.upper()}. Check your phone.", "reference": reference}
    
    else:
        return {"success": False, "message": f"Unknown payment method: {method}"}

@app.get("/api/transactions/{user_id}")
async def get_user_transactions(user_id: str):
    transactions = get_transactions(user_id)
    return {"success": True, "transactions": transactions}

@app.post("/api/driver/withdraw")
async def driver_withdrawal(request: dict):
    driver_id = request.get('driver_id')
    amount = request.get('amount')
    method = request.get('method')
    phone = request.get('phone')
    
    if not driver_id or not amount or not method or not phone:
        return {"success": False, "message": "Missing required fields"}
    
    if amount < 10000:
        return {"success": False, "message": "Minimum withdrawal is UGX 10,000"}
    
    balance = get_wallet_balance(driver_id)
    if balance < amount:
        return {"success": False, "message": f"Insufficient balance. Available: UGX {balance}"}
    
    reference = f"WD_{driver_id}_{int(datetime.now().timestamp())}"
    
    update_wallet_balance(driver_id, amount, 'debit')
    
    create_transaction({
        'user_id': driver_id,
        'amount': amount,
        'type': 'withdrawal',
        'method': method,
        'status': 'pending',
        'reference': reference,
        'description': f'Withdrawal request to {method.upper()} {phone}'
    })
    
    conn = get_db()
    cursor = conn.cursor()
    payout_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO payouts (id, driver_id, amount, phone, provider, status, reference)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    ''', (payout_id, driver_id, amount, phone, method, reference))
    conn.commit()
    conn.close()
    
    new_balance = get_wallet_balance(driver_id)
    
    return {
        "success": True,
        "message": f"Withdrawal request for UGX {amount} submitted",
        "reference": reference,
        "new_balance": new_balance
    }

# ============================================
# ADMIN ENDPOINTS
# ============================================

@app.get("/api/admin/stats")
async def get_admin_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'customer'")
    total_customers = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'driver'")
    total_drivers = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM rides")
    total_rides = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM rides WHERE date(requested_at) = date('now')")
    today_rides = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(fare) FROM rides")
    total_revenue = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT SUM(fare) FROM rides WHERE date(requested_at) = date('now')")
    today_revenue = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "total_customers": total_customers,
        "total_drivers": total_drivers,
        "total_rides": total_rides,
        "today_rides": today_rides,
        "total_revenue": total_revenue,
        "today_revenue": today_revenue
    }

@app.get("/api/admin/rides")
async def get_admin_rides(limit: int = 50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.*, 
               c.name as customer_name, d.name as driver_name 
        FROM rides r
        LEFT JOIN users c ON r.customer_id = c.id
        LEFT JOIN users d ON r.driver_id = d.id
        ORDER BY r.requested_at DESC LIMIT ?
    ''', (limit,))
    rides = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rides]

@app.get("/api/admin/drivers")
async def get_admin_drivers():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.*, d.total_earnings, d.is_online, d.is_approved
        FROM users u
        JOIN drivers d ON u.id = d.user_id
        WHERE u.role = 'driver'
    ''')
    drivers = cursor.fetchall()
    conn.close()
    return [dict(d) for d in drivers]

# ============================================
# SUPPORT CHAT WEBSOCKET
# ============================================

@app.websocket("/ws/support/{user_id}")
async def support_ws(user_id: str, websocket: WebSocket):
    await manager.connect(user_id, websocket)
    
    # Send previous messages
    messages = get_support_messages(user_id)
    for msg in messages:
        await websocket.send_json({
            'type': 'message',
            'message': msg['message'],
            'from_admin': bool(msg['from_admin']),
            'timestamp': msg['created_at']
        })
    
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get('message')
            
            if message:
                save_support_message(user_id, message, from_admin=False)
                await websocket.send_json({
                    'type': 'message',
                    'message': message,
                    'from_admin': False,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Notify admin if connected
                if 'admin' in manager.active_connections:
                    await manager.send('admin', {
                        'type': 'new_message',
                        'user_id': user_id,
                        'message': message,
                        'timestamp': datetime.now().isoformat()
                    })
                    
    except WebSocketDisconnect:
        manager.disconnect(user_id)

# ============================================
# WEBSOCKET ENDPOINTS
# ============================================

@app.websocket("/ws/driver/{driver_id}")
async def driver_ws(driver_id: str, websocket: WebSocket):
    await manager.connect(driver_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')
            print(f"📨 Driver {driver_id[:8]}: {msg_type}")
            
            if msg_type == 'location_update':
                driver_locations[driver_id] = {'lat': data['lat'], 'lng': data['lng']}
                if data.get('status') == 'online':
                    online_drivers.add(driver_id)
                else:
                    online_drivers.discard(driver_id)
                
                for ride_id, ride in active_rides.items():
                    if ride['driver_id'] == driver_id:
                        await manager.send(ride['customer_id'], {
                            'type': 'driver_location_update',
                            'lat': data['lat'],
                            'lng': data['lng']
                        })
            
            elif msg_type == 'accept_ride':
                ride_id = data['ride_id']
                if ride_id in pending_rides:
                    ride = pending_rides[ride_id]
                    customer_id = ride['customer_id']
                    distance = ride.get('distance_km', 2)
                    fare = ride.get('fare', calculate_fare(distance))
                    
                    active_rides[ride_id] = {
                        'driver_id': driver_id,
                        'customer_id': customer_id,
                        'distance_km': distance,
                        'fare': fare
                    }
                    
                    await manager.send(customer_id, {
                        'type': 'driver_assigned',
                        'driver_id': driver_id,
                        'ride_id': ride_id,
                        'fare': fare,
                        'distance_km': distance,
                        'driver_location': driver_locations.get(driver_id, {'lat': 0, 'lng': 0})
                    })
                    
                    await websocket.send_json({
                        'type': 'ride_accepted',
                        'fare': fare,
                        'distance_km': distance,
                        'message': f'Ride accepted! Fare: UGX {fare:,}'
                    })
                    
                    del pending_rides[ride_id]
                    print(f"✅ Ride {ride_id} accepted")
            
            elif msg_type == 'ride_started':
                ride_id = data['ride_id']
                if ride_id in active_rides:
                    customer_id = active_rides[ride_id]['customer_id']
                    await manager.send(customer_id, {
                        'type': 'ride_started',
                        'message': 'Your ride has started!'
                    })
                    print(f"🚀 Ride {ride_id} started")
            
            elif msg_type == 'ride_completed':
                ride_id = data['ride_id']
                fare = data.get('fare', 0)
                distance = data.get('distance_km', 0)
                
                if ride_id in active_rides:
                    customer_id = active_rides[ride_id]['customer_id']
                    
                    ride_data = {
                        'id': ride_id,
                        'customer_id': customer_id,
                        'driver_id': driver_id,
                        'distance_km': distance,
                        'fare': fare,
                        'original_fare': fare,
                        'surge_multiplier': 1.0,
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat()
                    }
                    save_ride(ride_data)
                    
                    update_wallet_balance(driver_id, fare, 'credit')
                    
                    await manager.send(customer_id, {
                        'type': 'ride_completed',
                        'fare': fare,
                        'distance_km': distance,
                        'ride_id': ride_id,
                        'driver_id': driver_id,
                        'message': f'Ride complete! Total: UGX {fare:,}'
                    })
                    
                    await websocket.send_json({
                        'type': 'ride_completed_confirmation',
                        'fare': fare,
                        'distance_km': distance,
                        'message': f'Ride completed! You earned UGX {fare:,}'
                    })
                    
                    del active_rides[ride_id]
            
            elif msg_type == 'decline_ride':
                ride_id = data['ride_id']
                if ride_id in pending_rides:
                    del pending_rides[ride_id]
                    print(f"❌ Ride {ride_id} declined")
                    
    except WebSocketDisconnect:
        manager.disconnect(driver_id)
        online_drivers.discard(driver_id)
        print(f"🚪 Driver {driver_id[:8]} disconnected")

@app.websocket("/ws/customer/{customer_id}")
async def customer_ws(customer_id: str, websocket: WebSocket):
    await manager.connect(customer_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')
            print(f"📨 Customer {customer_id[:8]}: {msg_type}")
            
            if msg_type == 'request_ride':
                ride_id = str(uuid.uuid4())[:8]
                
                distance_km = data.get('distance_km', 0)
                if distance_km == 0 and 'dest_lat' in data:
                    distance_km = calculate_distance(
                        data['pickup_lat'], data['pickup_lng'],
                        data['dest_lat'], data['dest_lng']
                    )
                
                fare = calculate_fare(distance_km, data['pickup_lat'], data['pickup_lng'])
                
                MAX_SEARCH_RADIUS_KM = 50
                nearest = None
                min_dist = float('inf')
                
                for driver_id in online_drivers:
                    loc = driver_locations.get(driver_id)
                    if loc:
                        dist = calculate_distance(data['pickup_lat'], data['pickup_lng'], loc['lat'], loc['lng'])
                        if dist < min_dist and dist <= MAX_SEARCH_RADIUS_KM:
                            min_dist = dist
                            nearest = driver_id
                
                if nearest:
                    pending_rides[ride_id] = {
                        'customer_id': customer_id,
                        'driver_id': nearest,
                        'pickup': data['pickup'],
                        'destination': data['destination'],
                        'pickup_lat': data['pickup_lat'],
                        'pickup_lng': data['pickup_lng'],
                        'dest_lat': data.get('dest_lat', 0),
                        'dest_lng': data.get('dest_lng', 0),
                        'distance_km': distance_km,
                        'fare': fare
                    }
                    
                    await manager.send(nearest, {
                        'type': 'new_ride_request',
                        'ride_id': ride_id,
                        'pickup': data['pickup'],
                        'destination': data['destination'],
                        'pickup_lat': data['pickup_lat'],
                        'pickup_lng': data['pickup_lng'],
                        'dest_lat': data.get('dest_lat', 0),
                        'dest_lng': data.get('dest_lng', 0),
                        'distance_km': distance_km,
                        'fare': fare
                    })
                    
                    await websocket.send_json({
                        'type': 'searching_for_driver',
                        'ride_id': ride_id,
                        'fare': fare,
                        'distance_km': distance_km,
                        'driver_distance_km': round(min_dist, 1),
                        'message': f'Searching for driver... Nearest driver is {round(min_dist, 1)}km away'
                    })
                    print(f"   → Searching for driver within {round(min_dist, 1)}km")
                else:
                    await websocket.send_json({
                        'type': 'no_drivers',
                        'message': f'No drivers within {MAX_SEARCH_RADIUS_KM}km. Please try again.'
                    })
            
            elif msg_type == 'cancel_ride':
                ride_id = data['ride_id']
                if ride_id in pending_rides:
                    driver_id = pending_rides[ride_id]['driver_id']
                    await manager.send(driver_id, {
                        'type': 'ride_cancelled',
                        'ride_id': ride_id
                    })
                    del pending_rides[ride_id]
                    await websocket.send_json({'type': 'ride_cancelled', 'message': 'Ride cancelled'})
            
            elif msg_type == 'submit_rating':
                ride_id = data.get('ride_id')
                driver_id = data.get('driver_id')
                rating = data.get('rating')
                comment = data.get('comment', '')
                print(f"⭐ Rating received - Driver: {driver_id}, Rating: {rating}/5")
                update_driver_rating(driver_id, rating)
                await websocket.send_json({
                    'type': 'rating_confirmed',
                    'message': f'Thank you for rating {rating} stars!'
                })
                    
    except WebSocketDisconnect:
        manager.disconnect(customer_id)
        print(f"🚪 Customer {customer_id[:8]} disconnected")

# ============================================
# RUN SERVER
# ============================================

@app.get("/")
async def root():
    return {
        "status": "running",
        "server": "Boda Boda System",
        "version": "3.0.0",
        "features": ["surge_pricing", "referrals", "support_chat", "driver_analytics"],
        "online_drivers": len(online_drivers),
        "active_connections": len(manager.active_connections)
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 60)
    print("🚀 BODA BODA SYSTEM - PHASE 3 COMPLETE")
    print("=" * 60)
    print(f"📡 Server running on port {port}")
    print("💰 Payment system: Active")
    print("⚡ Surge pricing: Active")
    print("🎁 Referral system: Active")
    print("💬 Support chat: Active")
    print("📊 Driver analytics: Active")
    print("=" * 60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)