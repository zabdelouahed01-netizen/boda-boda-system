"""
MAIN BACKEND SERVER - COMPLETE WITH RATING SYSTEM
"""

import json
import uuid
import math
from datetime import datetime
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ============================================
# DATABASE IMPORTS
# ============================================

from database_sqlite import (
    create_user, get_user_by_phone, verify_user, 
    generate_otp, verify_otp, get_driver_by_user_id,
    update_driver_location, get_online_drivers, save_ride,
    get_user_by_id, get_driver_stats, init_db,
    update_driver_rating, get_driver_rating
)

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

# ============================================
# DISTANCE CALCULATION
# ============================================

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
from backend.config import ALLOWED_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Keep * for now, we'll restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    print("✅ Database initialized")

# ============================================
# AUTHENTICATION ENDPOINTS
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

@app.post("/api/send-otp")
async def send_otp_endpoint(request: dict):
    phone = request.get('phone')
    print(f"📱 Send OTP request for: {phone}")
    
    if not phone:
        return {"success": False, "message": "Phone number required"}
    
    otp_code = generate_otp(phone)
    
    return {
        "success": True, 
        "message": "OTP sent successfully",
        "otp": otp_code
    }

@app.post("/api/verify-otp")
async def verify_otp_endpoint(request: dict):
    phone = request.get('phone')
    code = request.get('code')
    name = request.get('name', '')
    role = request.get('role', 'customer')
    
    print(f"🔐 Verify OTP for: {phone}, Code: {code}")
    
    if not phone or not code:
        return {"success": False, "message": "Phone and OTP required"}
    
    if verify_otp(phone, code):
        user = get_user_by_phone(phone)
        
        if not user:
            display_name = name if name else f"User_{phone[-4:]}"
            user = create_user(phone, display_name, role)
        
        verify_user(phone, True)
        
        print(f"✅ User logged in: {user['phone']}")
        
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

@app.get("/api/user/{user_id}")
async def get_user_endpoint(user_id: str):
    user = get_user_by_id(user_id)
    if user:
        return {"success": True, "user": user}
    return {"success": False, "message": "User not found"}

@app.get("/api/driver/stats/{user_id}")
async def get_driver_stats_endpoint(user_id: str):
    stats = get_driver_stats(user_id)
    rating = get_driver_rating(user_id)
    if stats:
        stats['rating'] = rating['rating']
        stats['total_rated_rides'] = rating['total_rides']
        return {"success": True, "stats": stats}
    return {"success": False, "message": "Driver not found"}

@app.get("/api/driver/rating/{driver_id}")
async def get_driver_rating_endpoint(driver_id: str):
    rating = get_driver_rating(driver_id)
    return {"success": True, "rating": rating['rating'], "total_rides": rating['total_rides']}

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

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
# DRIVER WEBSOCKET
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
                    update_driver_location(driver_id, data['lat'], data['lng'], True)
                else:
                    online_drivers.discard(driver_id)
                    update_driver_location(driver_id, data['lat'], data['lng'], False)
                
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
                    print(f"✅ Ride {ride_id} accepted - Distance: {distance}km, Fare: UGX {fare:,}")
            
            elif msg_type == 'ride_completed':
                ride_id = data['ride_id']
                fare = data.get('fare', 0)
                distance = data.get('distance_km', 0)
                
                print(f"🏁 Completing ride {ride_id} - Distance: {distance}km, Fare: UGX {fare:,}")
                
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
                    print(f"🏁 Ride {ride_id} COMPLETED")
            
            elif msg_type == 'decline_ride':
                ride_id = data['ride_id']
                if ride_id in pending_rides:
                    del pending_rides[ride_id]
                    print(f"❌ Ride {ride_id} declined")
                    
    except WebSocketDisconnect:
        manager.disconnect(driver_id)
        online_drivers.discard(driver_id)
        print(f"🚪 Driver {driver_id[:8]} disconnected")

# ============================================
# CUSTOMER WEBSOCKET
# ============================================

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
                
                # Get distance from customer (already calculated)
                distance_km = data.get('distance_km', 0)
                if distance_km == 0 and 'dest_lat' in data:
                    distance_km = calculate_distance(
                        data['pickup_lat'], data['pickup_lng'],
                        data['dest_lat'], data['dest_lng']
                    )
                
                fare = calculate_fare(distance_km)
                print(f"🚲 New ride {ride_id} - Distance: {distance_km}km, Fare: UGX {fare:,}")
                print(f"   📍 Pickup: ({data['pickup_lat']}, {data['pickup_lng']})")
                print(f"   🎯 Destination: ({data.get('dest_lat', 0)}, {data.get('dest_lng', 0)})")
                
                # Find nearest driver
                nearest = None
                min_dist = float('inf')
                for driver_id in online_drivers:
                    loc = driver_locations.get(driver_id)
                    if loc:
                        dist = calculate_distance(data['pickup_lat'], data['pickup_lng'], loc['lat'], loc['lng'])
                        if dist < min_dist and dist <= 5:
                            min_dist = dist
                            nearest = driver_id
                
                if nearest:
                    # Store ALL location data in pending_rides
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
                    
                    # Send COMPLETE ride request to driver with BOTH locations
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
                    
                    # Tell customer we're looking for a driver
                    await websocket.send_json({
                        'type': 'searching_for_driver',
                        'ride_id': ride_id,
                        'fare': fare,
                        'distance_km': distance_km,
                        'message': f'Searching for driver... Fare: UGX {fare:,}'
                    })
                    
                    print(f"   → Sent to driver {nearest[:8]} with pickup AND destination")
                else:
                    await websocket.send_json({
                        'type': 'no_drivers',
                        'message': 'No drivers nearby'
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
            
            # ============ RATING SYSTEM ============
            elif msg_type == 'submit_rating':
                ride_id = data.get('ride_id')
                driver_id = data.get('driver_id')
                rating = data.get('rating')
                comment = data.get('comment', '')
                
                print(f"⭐ Rating received - Ride: {ride_id}, Driver: {driver_id}, Rating: {rating}/5")
                print(f"   Comment: {comment}")
                
                # Update driver rating in database
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
    print("\n" + "=" * 50)
    print("🚀 BODA BODA SYSTEM - UGANDA")
    print("=" * 50)
    print("💰 Base Fare: UGX 5,000")
    print("💰 Per KM: UGX 2,000")
    print("⭐ Rating System: Active")
    print("\n✅ Server running on http://localhost:8000")
    print("=" * 50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")