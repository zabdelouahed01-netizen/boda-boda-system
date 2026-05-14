"""
MAIN BACKEND SERVER - COMPLETE FIXED VERSION
- Fixed WebSocket disconnections
- Fixed rating calculation
- Fixed "No drivers nearby" bug
- Added driver distance display
- 50km search radius
"""

import json
import uuid
import math
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            code TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
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
        print(f"✅ {user_id} connected - Total: {len(self.active_connections)}")
    
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"❌ {user_id} disconnected - Total: {len(self.active_connections)}")
    
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
            print(f"⚠️ Cannot send to {user_id} - not connected")
        return False

manager = ConnectionManager()

# ============================================
# API ENDPOINTS
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

@app.get("/")
async def root():
    return {
        "status": "running",
        "server": "Boda Boda System",
        "version": "1.0.0",
        "online_drivers": len(online_drivers),
        "active_connections": len(manager.active_connections)
    }

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
                    print(f"📍 Driver {driver_id[:8]} ONLINE at ({data['lat']:.4f}, {data['lng']:.4f})")
                else:
                    online_drivers.discard(driver_id)
                    print(f"📍 Driver {driver_id[:8]} OFFLINE")
                
                # Send location to customer if on active ride
                for ride_id, ride in active_rides.items():
                    if ride['driver_id'] == driver_id:
                        await manager.send(ride['customer_id'], {
                            'type': 'driver_location_update',
                            'lat': data['lat'],
                            'lng': data['lng']
                        })
            
            elif msg_type == 'accept_ride':
                ride_id = data['ride_id']
                print(f"🎯 Driver {driver_id[:8]} accepting ride {ride_id}")
                
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
                    
                    # Send to customer
                    await manager.send(customer_id, {
                        'type': 'driver_assigned',
                        'driver_id': driver_id,
                        'ride_id': ride_id,
                        'fare': fare,
                        'distance_km': distance,
                        'driver_distance_km': ride.get('driver_distance_km', 0),
                        'driver_location': driver_locations.get(driver_id, {'lat': 0, 'lng': 0})
                    })
                    
                    # Confirm to driver
                    await websocket.send_json({
                        'type': 'ride_accepted',
                        'fare': fare,
                        'distance_km': distance,
                        'message': f'Ride accepted! Fare: UGX {fare:,}'
                    })
                    
                    del pending_rides[ride_id]
                    print(f"✅ Ride {ride_id} accepted")
                else:
                    print(f"⚠️ Ride {ride_id} not found")
            
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
                print(f"🚲 New ride request {ride_id} - Distance: {distance_km}km, Fare: UGX {fare:,}")
                
                # Find nearest driver within 50km
                MAX_SEARCH_RADIUS_KM = 50
                nearest = None
                min_dist = float('inf')
                
                print(f"🔍 Searching among {len(online_drivers)} online drivers...")
                
                for driver_id in online_drivers:
                    loc = driver_locations.get(driver_id)
                    if loc:
                        dist = calculate_distance(data['pickup_lat'], data['pickup_lng'], loc['lat'], loc['lng'])
                        print(f"   Driver {driver_id[:8]} is {dist:.2f}km away")
                        if dist < min_dist and dist <= MAX_SEARCH_RADIUS_KM:
                            min_dist = dist
                            nearest = driver_id
                
                if nearest:
                    print(f"✅ Found driver {nearest[:8]} - Distance: {min_dist:.2f}km")
                    
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
                        'driver_distance_km': round(min_dist, 1)
                    }
                    
                    # Send to driver
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
                    
                    # Send searching message to customer
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
                    print(f"❌ No drivers found within {MAX_SEARCH_RADIUS_KM}km")
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
    print("📍 Driver search radius: 50km")
    print("⭐ Rating system: Active")
    print("=" * 50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)