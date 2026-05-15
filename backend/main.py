"""
MAIN BACKEND SERVER - COMPLETE WITH PAYMENTS
"""

import json
import uuid
import math
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ============================================
# DATABASE SETUP
# ============================================

import sqlite3
import random

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
    
    # ============ PAYMENT TABLES ============
    
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
    cursor.execute('INSERT INTO users (id, phone, name, role, is_verified) VALUES (?, ?, ?, ?, 0)', 
                   (user_id, phone, name, role))
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
            destination_lat, destination_lng, distance_km, fare, status,
            requested_at, accepted_at, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ride_id, ride_data.get('customer_id'), ride_data.get('driver_id'),
        ride_data.get('pickup_lat'), ride_data.get('pickup_lng'),
        ride_data.get('destination_lat'), ride_data.get('destination_lng'),
        ride_data.get('distance_km'), ride_data.get('fare'),
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
        cursor.execute('''
            INSERT INTO wallets (id, user_id, balance)
            VALUES (?, ?, 0)
        ''', (wallet_id, user_id))
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
        cursor.execute('''
            UPDATE wallets 
            SET balance = balance + ?, total_deposited = total_deposited + ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (amount, amount, user_id))
    else:
        cursor.execute('''
            UPDATE wallets 
            SET balance = balance - ?, total_withdrawn = total_withdrawn + ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND balance >= ?
        ''', (amount, amount, user_id, amount))
    
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
        transaction_id,
        transaction_data.get('user_id'),
        transaction_data.get('ride_id'),
        transaction_data.get('amount'),
        transaction_data.get('type'),
        transaction_data.get('method'),
        transaction_data.get('status', 'pending'),
        transaction_data.get('reference'),
        transaction_data.get('provider_reference'),
        transaction_data.get('description')
    ))
    
    conn.commit()
    cursor.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,))
    transaction = cursor.fetchone()
    conn.close()
    return dict(transaction)

def update_transaction_status(reference: str, status: str, provider_reference: str = None):
    conn = get_db()
    cursor = conn.cursor()
    
    if provider_reference:
        cursor.execute('''
            UPDATE transactions 
            SET status = ?, provider_reference = ?, completed_at = CURRENT_TIMESTAMP
            WHERE reference = ?
        ''', (status, provider_reference, reference))
    else:
        cursor.execute('''
            UPDATE transactions 
            SET status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE reference = ?
        ''', (status, reference))
    
    conn.commit()
    conn.close()

def get_transactions(user_id: str, limit: int = 50) -> list:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM transactions 
        WHERE user_id = ? 
        ORDER BY created_at DESC LIMIT ?
    ''', (user_id, limit))
    transactions = cursor.fetchall()
    conn.close()
    return [dict(t) for t in transactions]

def create_payout(payout_data: dict) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    
    payout_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO payouts (id, driver_id, amount, phone, provider, status, reference)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        payout_id,
        payout_data.get('driver_id'),
        payout_data.get('amount'),
        payout_data.get('phone'),
        payout_data.get('provider'),
        'pending',
        payout_data.get('reference')
    ))
    
    conn.commit()
    cursor.execute("SELECT * FROM payouts WHERE id = ?", (payout_id,))
    payout = cursor.fetchone()
    conn.close()
    return dict(payout)

# ============================================
# FARE CALCULATION
# ============================================

def calculate_fare(distance_km: float) -> int:
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

def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return round(R * c, 2)

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
    if not phone or not code:
        return {"success": False, "message": "Phone and OTP required"}
    if verify_otp(phone, code):
        user = get_user_by_phone(phone)
        if not user:
            display_name = name if name else f"User_{phone[-4:]}"
            user = create_user(phone, display_name, role)
        verify_user(phone, True)
        
        # Create wallet for user if not exists
        get_or_create_wallet(user['id'])
        
        return {
            "success": True,
            "user": {
                "id": user['id'],
                "phone": user['phone'],
                "name": user['name'],
                "role": user['role'],
                "is_verified": user['is_verified']
            }
        }
    else:
        return {"success": False, "message": "Invalid or expired OTP"}

@app.get("/api/driver/rating/{driver_id}")
async def get_driver_rating_endpoint(driver_id: str):
    rating = get_driver_rating(driver_id)
    return {"success": True, "rating": rating['rating'], "total_rides": rating['total_rides']}

# ============================================
# PAYMENT ENDPOINTS
# ============================================

@app.get("/api/wallet/{user_id}")
async def get_wallet(user_id: str):
    """Get user's wallet balance"""
    wallet = get_or_create_wallet(user_id)
    return {
        "success": True,
        "balance": wallet['balance'],
        "total_deposited": wallet['total_deposited'],
        "total_withdrawn": wallet['total_withdrawn']
    }

@app.post("/api/wallet/deposit")
async def deposit_to_wallet(request: dict):
    """Deposit money to wallet via mobile money"""
    user_id = request.get('user_id')
    amount = request.get('amount')
    method = request.get('method', 'mtn')
    phone = request.get('phone')
    
    if not user_id or not amount or not phone:
        return {"success": False, "message": "Missing required fields"}
    
    if amount < 5000:
        return {"success": False, "message": "Minimum deposit is UGX 5,000"}
    
    reference = f"DEPOSIT_{user_id}_{int(datetime.now().timestamp())}"
    
    # Create transaction record
    transaction = create_transaction({
        'user_id': user_id,
        'amount': amount,
        'type': 'deposit',
        'method': method,
        'status': 'pending',
        'reference': reference,
        'description': f'Deposit of UGX {amount} via {method.upper()}'
    })
    
    # For production, integrate with MTN/Airtel API here
    # For now, simulate successful deposit
    update_transaction_status(reference, 'completed')
    update_wallet_balance(user_id, amount, 'credit')
    
    return {
        "success": True,
        "message": f"Successfully deposited UGX {amount}",
        "reference": reference
    }

@app.post("/api/payments/process-ride")
async def process_ride_payment(request: dict):
    """Process payment for a completed ride"""
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
        
        return {
            "success": True,
            "message": f"Payment of UGX {amount} completed from wallet",
            "reference": reference
        }
    
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
        
        return {
            "success": True,
            "message": "Cash payment recorded",
            "reference": reference
        }
    
    elif method in ['mtn', 'airtel']:
        if not phone:
            return {"success": False, "message": "Phone number required for mobile money"}
        
        create_transaction({
            'user_id': user_id,
            'ride_id': ride_id,
            'amount': amount,
            'type': 'payment',
            'method': method,
            'status': 'pending',
            'reference': reference,
            'description': f'Payment for ride {ride_id} via {method.upper()}'
        })
        
        # For production, integrate with MTN/Airtel API here
        # Simulate successful payment
        update_transaction_status(reference, 'completed')
        
        return {
            "success": True,
            "message": f"Payment initiated via {method.upper()}. Check your phone to complete.",
            "reference": reference
        }
    
    else:
        return {"success": False, "message": f"Unknown payment method: {method}"}

@app.get("/api/transactions/{user_id}")
async def get_user_transactions(user_id: str):
    """Get user's transaction history"""
    transactions = get_transactions(user_id)
    return {"success": True, "transactions": transactions}

@app.post("/api/driver/withdraw")
async def driver_withdrawal(request: dict):
    """Driver requests withdrawal to mobile money"""
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
    
    # Deduct from wallet
    update_wallet_balance(driver_id, amount, 'debit')
    
    # Create withdrawal transaction
    create_transaction({
        'user_id': driver_id,
        'amount': amount,
        'type': 'withdrawal',
        'method': method,
        'status': 'pending',
        'reference': reference,
        'description': f'Withdrawal request to {method.upper()} {phone}'
    })
    
    # Create payout record
    create_payout({
        'driver_id': driver_id,
        'amount': amount,
        'phone': phone,
        'provider': method,
        'reference': reference
    })
    
    new_balance = get_wallet_balance(driver_id)
    
    return {
        "success": True,
        "message": f"Withdrawal request for UGX {amount} submitted. Funds will be sent to {method.upper()} {phone}",
        "reference": reference,
        "new_balance": new_balance
    }

@app.get("/")
async def root():
    return {
        "status": "running",
        "server": "Boda Boda System",
        "version": "2.0.0",
        "online_drivers": len(online_drivers),
        "active_connections": len(manager.active_connections)
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

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
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat()
                    }
                    save_ride(ride_data)
                    
                    # Credit driver's wallet for the ride
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
                
                fare = calculate_fare(distance_km)
                
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 50)
    print("🚀 BODA BODA SYSTEM - UGANDA")
    print("=" * 50)
    print(f"📡 Server running on port {port}")
    print("💰 Payment system enabled")
    print("=" * 50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)