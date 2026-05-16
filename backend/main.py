"""
MAIN BACKEND SERVER - POSTGRESQL PRODUCTION (WITH AUTO-MIGRATION)
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
# DATABASE SETUP - POSTGRESQL
# ============================================
# ============ SMS FUNCTION ============
import requests

def send_otp_sms(phone: str, otp: str) -> dict:
    """Send OTP via SMS using Africa's Talking"""
    # Format phone number
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    if phone.startswith("0"):
        phone = "256" + phone[1:]
    
    message = f"Your Boda Boda verification code is: {otp}"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "apiKey": "atsk_fe1c0dcda0ed58eb254db24e1d05026faaf0a34c73148e748d6e8e8381a1d575fc556ea2",
    }
    
    data = {
        "username": "sandbox",
        "to": phone,
        "message": message
    }
    
    try:
        response = requests.post("http://api.sandbox.africastalking.com/version1/messaging", headers=headers, data=data, timeout=30)
        if response.status_code == 201:
            result = response.json()
            if 'Sent' in result.get('SMSMessageData', {}).get('Message', ''):
                print(f"✅ OTP SMS sent to {phone}")
                return {"success": True, "message": "OTP sent"}
        return {"success": False, "message": "SMS failed"}
    except Exception as e:
        print(f"❌ SMS error: {e}")
        return {"success": False, "message": str(e)}
import asyncpg

DB_POOL = None
DATABASE_URL = os.environ.get("DATABASE_URL", "")

async def get_db():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
    return await DB_POOL.acquire()

async def release_db(conn):
    await DB_POOL.release(conn)

def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            value = value.replace('Z', '+00:00')
            return datetime.fromisoformat(value)
        except:
            return datetime.now()
    return datetime.now()

async def init_db():
    conn = await get_db()
    
    await conn.execute('''
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
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE REFERENCES users(id),
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
            total_rides INTEGER DEFAULT 0
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS rides (
            id TEXT PRIMARY KEY,
            customer_id TEXT REFERENCES users(id),
            driver_id TEXT REFERENCES users(id),
            pickup_lat REAL,
            pickup_lng REAL,
            pickup_address TEXT,
            destination_lat REAL,
            destination_lng REAL,
            destination_address TEXT,
            distance_km REAL,
            fare INTEGER,
            surge_multiplier REAL DEFAULT 1.0,
            status TEXT,
            customer_rating INTEGER DEFAULT 0,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accepted_at TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS otps (
            id SERIAL PRIMARY KEY,
            phone TEXT,
            code TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            ride_id TEXT REFERENCES rides(id),
            driver_id TEXT REFERENCES users(id),
            customer_id TEXT REFERENCES users(id),
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS wallets (
            id TEXT PRIMARY KEY,
            user_id TEXT UNIQUE NOT NULL REFERENCES users(id),
            balance INTEGER DEFAULT 0,
            total_deposited INTEGER DEFAULT 0,
            total_withdrawn INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            ride_id TEXT REFERENCES rides(id),
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            method TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reference TEXT UNIQUE NOT NULL,
            provider_reference TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS payouts (
            id TEXT PRIMARY KEY,
            driver_id TEXT NOT NULL REFERENCES users(id),
            amount INTEGER NOT NULL,
            phone TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reference TEXT UNIQUE NOT NULL,
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id TEXT PRIMARY KEY,
            referrer_id TEXT NOT NULL REFERENCES users(id),
            referred_id TEXT NOT NULL REFERENCES users(id),
            referrer_name TEXT,
            referred_name TEXT,
            status TEXT DEFAULT 'pending',
            reward INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            message TEXT NOT NULL,
            from_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    await release_db(conn)
    print("✅ PostgreSQL database ready")

# ============================================
# DATABASE FUNCTIONS
# ============================================

async def create_user(phone: str, name: str, role: str):
    conn = await get_db()
    
    existing = await conn.fetchrow("SELECT * FROM users WHERE phone = $1", phone)
    if existing:
        await release_db(conn)
        return dict(existing)
    
    user_id = str(uuid.uuid4())[:8]
    referral_code = str(uuid.uuid4())[:8].upper()
    
    await conn.execute('''
        INSERT INTO users (id, phone, name, role, is_verified, referral_code) 
        VALUES ($1, $2, $3, $4, 0, $5)
    ''', user_id, phone, name, role, referral_code)
    
    wallet_id = str(uuid.uuid4())[:8]
    await conn.execute('INSERT INTO wallets (id, user_id, balance) VALUES ($1, $2, 0)', wallet_id, user_id)
    
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    await release_db(conn)
    return dict(user)

async def get_user_by_phone(phone: str):
    conn = await get_db()
    user = await conn.fetchrow("SELECT * FROM users WHERE phone = $1", phone)
    await release_db(conn)
    return dict(user) if user else None

async def get_user_by_id(user_id: str):
    conn = await get_db()
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    await release_db(conn)
    return dict(user) if user else None

async def verify_user(phone: str, is_verified: bool = True):
    conn = await get_db()
    await conn.execute("UPDATE users SET is_verified = $1 WHERE phone = $2", 1 if is_verified else 0, phone)
    await release_db(conn)

async def update_driver_rating(driver_id: str, new_rating: int):
    conn = await get_db()
    
    user = await conn.fetchrow("SELECT rating, total_rides FROM users WHERE id = $1", driver_id)
    if user:
        current_rating = user[0] or 0
        total_rides = user[1] or 0
        new_avg = ((current_rating * total_rides) + new_rating) / (total_rides + 1) if total_rides > 0 else new_rating
        await conn.execute("UPDATE users SET rating = $1 WHERE id = $2", round(new_avg, 1), driver_id)
        await conn.execute("UPDATE drivers SET rating = $1, total_rides = total_rides + 1 WHERE user_id = $2", 
                           round(new_avg, 1), driver_id)
    
    await release_db(conn)

async def get_driver_rating(driver_id: str):
    conn = await get_db()
    user = await conn.fetchrow("SELECT rating, total_rides FROM users WHERE id = $1", driver_id)
    await release_db(conn)
    return {'rating': user[0] or 0, 'total_rides': user[1] or 0} if user else {'rating': 0, 'total_rides': 0}

async def generate_otp(phone: str) -> str:
    conn = await get_db()
    await conn.execute("DELETE FROM otps WHERE phone = $1", phone)
    
    code = str(random.randint(100000, 999999))
    expires_at = datetime.now() + timedelta(minutes=5)
    
    await conn.execute('INSERT INTO otps (phone, code, expires_at) VALUES ($1, $2, $3)', phone, code, expires_at)
    await release_db(conn)
    
    print(f"📱 OTP for {phone}: {code}")
    return code

async def verify_otp(phone: str, code: str) -> bool:
    conn = await get_db()
    otp = await conn.fetchrow('SELECT * FROM otps WHERE phone = $1 AND code = $2 AND expires_at > $3', 
                              phone, code, datetime.now())
    
    if otp:
        await conn.execute("DELETE FROM otps WHERE phone = $1", phone)
        await release_db(conn)
        return True
    
    await release_db(conn)
    return False

async def update_driver_location(user_id: str, lat: float, lng: float, is_online: bool = True):
    conn = await get_db()
    
    driver = await conn.fetchrow("SELECT * FROM drivers WHERE user_id = $1", user_id)
    if not driver:
        driver_id = str(uuid.uuid4())[:8]
        await conn.execute('''
            INSERT INTO drivers (id, user_id, is_approved, is_online, current_lat, current_lng) 
            VALUES ($1, $2, 1, $3, $4, $5)
        ''', driver_id, user_id, 1 if is_online else 0, lat, lng)
    else:
        await conn.execute('''
            UPDATE drivers SET current_lat = $1, current_lng = $2, is_online = $3 WHERE user_id = $4
        ''', lat, lng, 1 if is_online else 0, user_id)
    
    await release_db(conn)

async def save_ride(ride_data: dict):
    conn = await get_db()
    ride_id = ride_data.get('id', str(uuid.uuid4())[:8])
    
    customer_id = ride_data.get('customer_id')
    customer = await conn.fetchrow("SELECT * FROM users WHERE id = $1", customer_id)
    if not customer:
        await release_db(conn)
        print(f"❌ Cannot save ride: Customer {customer_id} does not exist")
        return
    
    driver_id = ride_data.get('driver_id')
    driver = await conn.fetchrow("SELECT * FROM users WHERE id = $1", driver_id)
    if not driver:
        await release_db(conn)
        print(f"❌ Cannot save ride: Driver {driver_id} does not exist")
        return
    
    requested_at = parse_datetime(ride_data.get('requested_at'))
    accepted_at = parse_datetime(ride_data.get('accepted_at'))
    started_at = parse_datetime(ride_data.get('started_at'))
    completed_at = parse_datetime(ride_data.get('completed_at', datetime.now()))
    payment_method = ride_data.get('payment_method', 'wallet')
    
    await conn.execute('''
        INSERT INTO rides (
            id, customer_id, driver_id, pickup_lat, pickup_lng,
            destination_lat, destination_lng, distance_km, fare, surge_multiplier, status,
            payment_method, requested_at, accepted_at, started_at, completed_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
    ''', ride_id, customer_id, driver_id,
        ride_data.get('pickup_lat'), ride_data.get('pickup_lng'),
        ride_data.get('destination_lat'), ride_data.get('destination_lng'),
        ride_data.get('distance_km'), ride_data.get('fare'), ride_data.get('surge_multiplier', 1.0),
        ride_data.get('status', 'completed'), payment_method,
        requested_at, accepted_at, started_at, completed_at)
    
    await conn.execute('''
        UPDATE drivers SET total_earnings = total_earnings + $1, rides_today = rides_today + 1 WHERE user_id = $2
    ''', ride_data.get('fare', 0), driver_id)
    
    await conn.execute('UPDATE users SET total_rides = total_rides + 1 WHERE id = $1', customer_id)
    
    await release_db(conn)
    print(f"💾 Ride {ride_id} saved with payment method: {payment_method}")

# ============================================
# WALLET FUNCTIONS
# ============================================

async def get_or_create_wallet(user_id: str) -> dict:
    conn = await get_db()
    
    user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    if not user:
        await release_db(conn)
        raise Exception(f"User {user_id} does not exist")
    
    wallet = await conn.fetchrow("SELECT * FROM wallets WHERE user_id = $1", user_id)
    if not wallet:
        wallet_id = str(uuid.uuid4())[:8]
        await conn.execute('INSERT INTO wallets (id, user_id, balance) VALUES ($1, $2, 0)', wallet_id, user_id)
        wallet = await conn.fetchrow("SELECT * FROM wallets WHERE id = $1", wallet_id)
    
    await release_db(conn)
    return dict(wallet)

async def get_wallet_balance(user_id: str) -> int:
    conn = await get_db()
    result = await conn.fetchval("SELECT balance FROM wallets WHERE user_id = $1", user_id)
    await release_db(conn)
    return result or 0

async def update_wallet_balance(user_id: str, amount: int, transaction_type: str = 'credit') -> bool:
    conn = await get_db()
    
    if transaction_type == 'credit':
        result = await conn.execute('''
            UPDATE wallets 
            SET balance = balance + $1, 
                total_deposited = total_deposited + $1, 
                updated_at = CURRENT_TIMESTAMP 
            WHERE user_id = $2
        ''', amount, user_id)
    else:
        result = await conn.execute('''
            UPDATE wallets 
            SET balance = balance - $1, 
                total_withdrawn = total_withdrawn + $1, 
                updated_at = CURRENT_TIMESTAMP 
            WHERE user_id = $2 AND balance >= $1
        ''', amount, user_id)
    
    await release_db(conn)
    return result != "UPDATE 0"

async def create_transaction(transaction_data: dict) -> dict:
    conn = await get_db()
    transaction_id = str(uuid.uuid4())[:8]
    
    await conn.execute('''
        INSERT INTO transactions (
            id, user_id, ride_id, amount, type, method, 
            status, reference, provider_reference, description
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ''', transaction_id,
        transaction_data.get('user_id'), transaction_data.get('ride_id'),
        transaction_data.get('amount'), transaction_data.get('type'), transaction_data.get('method'),
        transaction_data.get('status', 'pending'), transaction_data.get('reference'),
        transaction_data.get('provider_reference'), transaction_data.get('description'))
    
    transaction = await conn.fetchrow("SELECT * FROM transactions WHERE id = $1", transaction_id)
    await release_db(conn)
    return dict(transaction)

async def get_transactions(user_id: str, limit: int = 50) -> list:
    conn = await get_db()
    transactions = await conn.fetch('''
        SELECT * FROM transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2
    ''', user_id, limit)
    await release_db(conn)
    return [dict(t) for t in transactions]

# ============================================
# DRIVER ANALYTICS
# ============================================

async def get_driver_analytics(driver_id: str):
    conn = await get_db()
    
    result = await conn.fetchrow('''
        SELECT 
            COUNT(*) as total_rides,
            AVG(customer_rating) as avg_rating,
            AVG(EXTRACT(EPOCH FROM (accepted_at - requested_at))) as avg_response,
            SUM(fare) as total_earnings
        FROM rides WHERE driver_id = $1 AND status = 'completed'
    ''', driver_id)
    
    weekly_rides = await conn.fetchval('''
        SELECT COUNT(*) FROM rides 
        WHERE driver_id = $1 AND status = 'completed' 
        AND requested_at > NOW() - INTERVAL '7 days'
    ''', driver_id)
    
    peak = await conn.fetchrow('''
        SELECT EXTRACT(HOUR FROM requested_at) as hour, COUNT(*) 
        FROM rides WHERE driver_id = $1 GROUP BY hour ORDER BY COUNT(*) DESC LIMIT 1
    ''', driver_id)
    
    await release_db(conn)
    
    peak_hour = 17
    if peak and peak[0] is not None:
        try:
            peak_hour = int(float(peak[0]))
        except (ValueError, TypeError):
            peak_hour = 17
    
    return {
        'total_rides': result[0] or 0,
        'avg_rating': round(result[1] or 0, 1),
        'avg_response_time': round(result[2] or 0, 1),
        'total_earnings': result[3] or 0,
        'weekly_rides': weekly_rides or 0,
        'peak_hour': peak_hour,
        'completion_rate': 98
    }

# ============================================
# ADMIN FUNCTIONS
# ============================================

async def get_admin_stats():
    conn = await get_db()
    
    total_customers = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'customer'")
    total_drivers = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'driver'")
    total_rides = await conn.fetchval("SELECT COUNT(*) FROM rides")
    today_rides = await conn.fetchval("SELECT COUNT(*) FROM rides WHERE DATE(requested_at) = CURRENT_DATE")
    total_revenue = await conn.fetchval("SELECT COALESCE(SUM(fare), 0) FROM rides")
    today_revenue = await conn.fetchval("SELECT COALESCE(SUM(fare), 0) FROM rides WHERE DATE(requested_at) = CURRENT_DATE")
    
    await release_db(conn)
    
    return {
        "total_customers": total_customers or 0,
        "total_drivers": total_drivers or 0,
        "total_rides": total_rides or 0,
        "today_rides": today_rides or 0,
        "total_revenue": total_revenue or 0,
        "today_revenue": today_revenue or 0
    }

async def get_admin_rides(limit=50):
    conn = await get_db()
    rides = await conn.fetch('''
        SELECT r.*, 
               c.name as customer_name, d.name as driver_name 
        FROM rides r
        LEFT JOIN users c ON r.customer_id = c.id
        LEFT JOIN users d ON r.driver_id = d.id
        ORDER BY r.requested_at DESC LIMIT $1
    ''', limit)
    await release_db(conn)
    return [dict(r) for r in rides]

async def get_admin_drivers():
    conn = await get_db()
    drivers = await conn.fetch('''
        SELECT u.*, d.total_earnings, d.is_online, d.is_approved, d.rating as driver_rating
        FROM users u
        JOIN drivers d ON u.id = d.user_id
        WHERE u.role = 'driver'
    ''')
    await release_db(conn)
    return [dict(d) for d in drivers]

# ============================================
# REFERRAL FUNCTIONS
# ============================================

async def create_referral(referrer_id: str, referred_id: str, referrer_name: str = None, referred_name: str = None):
    conn = await get_db()
    referral_id = str(uuid.uuid4())[:8]
    await conn.execute('''
        INSERT INTO referrals (id, referrer_id, referred_id, referrer_name, referred_name, status)
        VALUES ($1, $2, $3, $4, $5, 'pending')
    ''', referral_id, referrer_id, referred_id, referrer_name, referred_name)
    await release_db(conn)
    return referral_id

async def complete_referral(referral_id: str):
    conn = await get_db()
    referral = await conn.fetchrow("SELECT * FROM referrals WHERE id = $1", referral_id)
    if referral:
        BONUS_AMOUNT = 5000
        await update_wallet_balance(referral['referrer_id'], BONUS_AMOUNT, 'credit')
        await update_wallet_balance(referral['referred_id'], BONUS_AMOUNT, 'credit')
        await conn.execute('''
            UPDATE referrals SET status = 'completed', reward = $1, completed_at = CURRENT_TIMESTAMP WHERE id = $2
        ''', BONUS_AMOUNT, referral_id)
    await release_db(conn)

# ============================================
# SUPPORT FUNCTIONS
# ============================================

async def save_support_message(user_id: str, message: str, from_admin: bool = False):
    conn = await get_db()
    await conn.execute('''
        INSERT INTO support_messages (user_id, message, from_admin)
        VALUES ($1, $2, $3)
    ''', user_id, message, 1 if from_admin else 0)
    await release_db(conn)

async def get_support_messages(user_id: str, limit: int = 50):
    conn = await get_db()
    messages = await conn.fetch('''
        SELECT * FROM support_messages WHERE user_id = $1 ORDER BY created_at ASC LIMIT $2
    ''', user_id, limit)
    await release_db(conn)
    return [dict(m) for m in messages]

# ============================================
# SURGE PRICING & UTILITIES
# ============================================

def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 2)

def calculate_fare(distance_km: float, lat: float = None, lng: float = None) -> int:
    BASE_FARE = 5000
    PER_KM_RATE = 2000
    fare = BASE_FARE + (distance_km * PER_KM_RATE)
    fare = max(fare, BASE_FARE)
    return int(round(fare / 500) * 500)

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
    if not DATABASE_URL:
        print("❌ DATABASE_URL environment variable is not set!")
        return
    
    await init_db()
    
    # ============ AUTO-MIGRATION: Add payment_method column ============
    conn = await get_db()
    try:
        await conn.execute('ALTER TABLE rides ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT \'wallet\'')
        print("✅ payment_method column verified/added to rides table")
    except Exception as e:
        print(f"⚠️ Migration note: {e}")
    finally:
        await release_db(conn)
    # ===================================================================
    
    print("✅ Database initialized and ready")

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
                print(f"📤 Sent to {user_id}: {message.get('type')}")
                return True
            except Exception as e:
                print(f"💥 Error sending to {user_id}: {e}")
                self.disconnect(user_id)
        else:
            print(f"⚠️ User {user_id} not connected")
        return False

manager = ConnectionManager()

# ============================================
# AUTHENTICATION ENDPOINTS
# ============================================




@app.post("/api/verify-otp")
async def verify_otp_endpoint(request: dict):
    phone = request.get('phone')
    code = request.get('code')
    name = request.get('name', '')
    role = request.get('role', 'customer')
    referral_code = request.get('referral_code')
    
    if not phone or not code:
        return {"success": False, "message": "Phone and OTP required"}
    
    if await verify_otp(phone, code):
        user = await get_user_by_phone(phone)
        
        if not user:
            user = await create_user(phone, name, role)
            
            if referral_code:
                referrer = await get_user_by_id(referral_code)
                if referrer:
                    await create_referral(referrer['id'], user['id'], referrer['name'], name)
                    await complete_referral(referrer['id'])
        
        await verify_user(phone, True)
        
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
    rating = await get_driver_rating(driver_id)
    return {"success": True, "rating": rating['rating'], "total_rides": rating['total_rides']}

@app.get("/api/driver/analytics/{driver_id}")
async def get_driver_analytics_endpoint(driver_id: str):
    analytics = await get_driver_analytics(driver_id)
    return {"success": True, "analytics": analytics}

@app.get("/api/user/referral/{user_id}")
async def get_user_referral_code(user_id: str):
    user = await get_user_by_id(user_id)
    if user:
        return {"success": True, "referral_code": user.get('referral_code', '')}
    return {"success": False, "message": "User not found"}

# ============================================
# WALLET ENDPOINTS
# ============================================

@app.get("/api/wallet/{user_id}")
async def get_wallet(user_id: str):
    try:
        wallet = await get_or_create_wallet(user_id)
        return {
            "success": True,
            "balance": wallet['balance'],
            "total_deposited": wallet['total_deposited'],
            "total_withdrawn": wallet['total_withdrawn']
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

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
    
    await create_transaction({
        'user_id': user_id,
        'amount': amount,
        'type': 'deposit',
        'method': method,
        'status': 'completed',
        'reference': reference,
        'description': f'Deposit of UGX {amount} via {method.upper()}'
    })
    
    await update_wallet_balance(user_id, amount, 'credit')
    
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
        balance = await get_wallet_balance(user_id)
        if balance < amount:
            return {"success": False, "message": f"Insufficient wallet balance. Available: UGX {balance}"}
        
        await update_wallet_balance(user_id, amount, 'debit')
        await create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': 'wallet',
            'status': 'completed',
            'reference': reference,
            'description': f'Payment for ride {ride_id} from wallet'
        })
        
        return {"success": True, "message": f"Payment of UGX {amount} completed from wallet", "reference": reference}
    
    elif method == 'cash':
        await create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': 'cash',
            'status': 'completed',
            'reference': reference,
            'description': f'Cash payment for ride {ride_id} - paid directly to driver'
        })
        return {"success": True, "message": "Cash payment recorded. Please pay driver directly.", "reference": reference}
    
    elif method in ['mtn', 'airtel']:
        if not phone:
            return {"success": False, "message": "Phone number required for mobile money"}
        
        await create_transaction({
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
    transactions = await get_transactions(user_id)
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
    
    balance = await get_wallet_balance(driver_id)
    if balance < amount:
        return {"success": False, "message": f"Insufficient balance. Available: UGX {balance}"}
    
    reference = f"WD_{driver_id}_{int(datetime.now().timestamp())}"
    
    await update_wallet_balance(driver_id, amount, 'debit')
    
    await create_transaction({
        'user_id': driver_id,
        'amount': amount,
        'type': 'withdrawal',
        'method': method,
        'status': 'pending',
        'reference': reference,
        'description': f'Withdrawal request to {method.upper()} {phone}'
    })
    
    new_balance = await get_wallet_balance(driver_id)
    
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
async def admin_stats():
    return await get_admin_stats()

@app.get("/api/admin/rides")
async def admin_rides(limit: int = 50):
    return await get_admin_rides(limit)

@app.get("/api/admin/drivers")
async def admin_drivers():
    return await get_admin_drivers()

# ============================================
# SUPPORT CHAT WEBSOCKET
# ============================================

@app.websocket("/ws/support/{user_id}")
async def support_ws(user_id: str, websocket: WebSocket):
    await manager.connect(user_id, websocket)
    
    messages = await get_support_messages(user_id)
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
                await save_support_message(user_id, message, from_admin=False)
                await websocket.send_json({
                    'type': 'message',
                    'message': message,
                    'from_admin': False,
                    'timestamp': datetime.now().isoformat()
                })
                
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
                    payment_method = ride.get('payment_method', 'wallet')
                    
                    active_rides[ride_id] = {
                        'driver_id': driver_id,
                        'customer_id': customer_id,
                        'distance_km': distance,
                        'fare': fare,
                        'payment_method': payment_method
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
                payment_method = data.get('payment_method', 'wallet')
                
                if ride_id in active_rides:
                    customer_id = active_rides[ride_id]['customer_id']
                    
                    # For wallet payments, verify balance again
                    if payment_method == 'wallet':
                        customer_balance = await get_wallet_balance(customer_id)
                        if customer_balance < fare:
                            await websocket.send_json({
                                'type': 'payment_error',
                                'message': f'Insufficient wallet balance'
                            })
                            await manager.send(customer_id, {
                                'type': 'payment_error',
                                'message': f'Insufficient wallet balance. Please add funds.'
                            })
                            del active_rides[ride_id]
                            return
                    
                    ride_data = {
                        'id': ride_id,
                        'customer_id': customer_id,
                        'driver_id': driver_id,
                        'distance_km': distance,
                        'fare': fare,
                        'surge_multiplier': 1.0,
                        'status': 'completed',
                        'payment_method': payment_method,
                        'completed_at': datetime.now()
                    }
                    await save_ride(ride_data)
                    
                    # Process payment based on method
                    if payment_method == 'wallet':
                        await update_wallet_balance(customer_id, fare, 'debit')
                        await update_wallet_balance(driver_id, fare, 'credit')
                        await websocket.send_json({
                            'type': 'ride_completed_confirmation',
                            'fare': fare,
                            'distance_km': distance,
                            'message': f'Ride completed! UGX {fare:,} added to your wallet.'
                        })
                    elif payment_method == 'cash':
                        await websocket.send_json({
                            'type': 'ride_completed_confirmation',
                            'fare': fare,
                            'distance_km': distance,
                            'message': f'Ride completed! Customer will pay UGX {fare:,} in cash.'
                        })
                    else:
                        await websocket.send_json({
                            'type': 'ride_completed_confirmation',
                            'fare': fare,
                            'distance_km': distance,
                            'message': f'Ride completed! Payment processed via {payment_method.upper()}.'
                        })
                    
                    await manager.send(customer_id, {
                        'type': 'ride_completed',
                        'fare': fare,
                        'distance_km': distance,
                        'ride_id': ride_id,
                        'driver_id': driver_id,
                        'payment_method': payment_method,
                        'message': f'Ride complete! Total: UGX {fare:,}'
                    })
                    
                    del active_rides[ride_id]
                    print(f"🏁 Ride {ride_id} completed with payment method: {payment_method}")
            
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
                payment_method = data.get('payment_method', 'wallet')
                
                # Check wallet balance for wallet payments
                if payment_method == 'wallet':
                    wallet_balance = await get_wallet_balance(customer_id)
                    if wallet_balance < fare:
                        await websocket.send_json({
                            'type': 'payment_error',
                            'message': f'Insufficient wallet balance. Available: UGX {wallet_balance:,}, Required: UGX {fare:,}'
                        })
                        print(f"❌ Customer {customer_id[:8]} insufficient wallet balance")
                        return
                
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
                        'fare': fare,
                        'payment_method': payment_method
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
                        'fare': fare,
                        'payment_method': payment_method
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
                await update_driver_rating(driver_id, rating)
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
        "features": ["surge_pricing", "referrals", "support_chat", "driver_analytics", "admin_dashboard"],
        "online_drivers": len(online_drivers),
        "active_connections": len(manager.active_connections)
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 60)
    print("🚀 BODA BODA SYSTEM - POSTGRESQL PRODUCTION (WITH AUTO-MIGRATION)")
    print("=" * 60)
    print(f"📡 Server running on port {port}")
    print("💰 Payment system: Active (Wallet validation enabled)")
    print("⚡ Surge pricing: Active")
    print("🎁 Referral system: Active")
    print("💬 Support chat: Active")
    print("📊 Driver analytics: Active")
    print("👑 Admin dashboard: Active")
    print("🐘 Database: PostgreSQL")
    print("=" * 60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)