"""
SQLITE DATABASE - Complete with Rating Functions
"""

import sqlite3
import uuid
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, List

DB_PATH = "boda_system.db"

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create all tables"""
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ride_id) REFERENCES rides(id),
            FOREIGN KEY (driver_id) REFERENCES users(id),
            FOREIGN KEY (customer_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ SQLite database ready!")

# ============================================
# USER FUNCTIONS
# ============================================

def create_user(phone: str, name: str, role: str):
    """Create a new user"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user exists
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        return dict(existing)
    
    # Create new user
    user_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO users (id, phone, name, role, is_verified)
        VALUES (?, ?, ?, ?, 0)
    ''', (user_id, phone, name, role))
    
    conn.commit()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    print(f"✅ Created {role}: {name}")
    return dict(user)

def get_user_by_phone(phone: str):
    """Get user by phone number"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_id(user_id: str):
    """Get user by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def verify_user(phone: str, is_verified: bool = True):
    """Mark user as verified"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_verified = ? WHERE phone = ?", (1 if is_verified else 0, phone))
    conn.commit()
    conn.close()

# ============================================
# DRIVER FUNCTIONS
# ============================================

def register_driver(user_id: str, license_number: str, bike_registration: str, bike_model: str, bike_color: str):
    """Register a new driver"""
    conn = get_db()
    cursor = conn.cursor()
    
    driver_id = str(uuid.uuid4())[:8]
    cursor.execute('''
        INSERT INTO drivers (id, user_id, license_number, bike_registration, bike_model, bike_color, is_approved)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    ''', (driver_id, user_id, license_number, bike_registration, bike_model, bike_color))
    
    conn.commit()
    
    cursor.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
    driver = cursor.fetchone()
    conn.close()
    
    print(f"✅ Driver registered - Awaiting approval")
    return dict(driver)

def get_driver_by_user_id(user_id: str):
    """Get driver by user ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers WHERE user_id = ?", (user_id,))
    driver = cursor.fetchone()
    conn.close()
    return dict(driver) if driver else None

def get_driver_by_id(driver_id: str):
    """Get driver by driver ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
    driver = cursor.fetchone()
    conn.close()
    return dict(driver) if driver else None

def approve_driver(driver_id: str):
    """Approve a driver"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE drivers SET is_approved = 1 WHERE id = ?", (driver_id,))
    conn.commit()
    conn.close()
    print(f"✅ Driver {driver_id} approved!")

def update_driver_location(user_id: str, lat: float, lng: float, is_online: bool = True):
    """Update driver location and online status"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if driver exists, if not create basic record
    cursor.execute("SELECT * FROM drivers WHERE user_id = ?", (user_id,))
    driver = cursor.fetchone()
    
    if not driver:
        # Create basic driver record
        driver_id = str(uuid.uuid4())[:8]
        cursor.execute('''
            INSERT INTO drivers (id, user_id, is_approved, is_online, current_lat, current_lng)
            VALUES (?, ?, 1, ?, ?, ?)
        ''', (driver_id, user_id, 1 if is_online else 0, lat, lng))
    else:
        cursor.execute('''
            UPDATE drivers SET current_lat = ?, current_lng = ?, is_online = ?
            WHERE user_id = ?
        ''', (lat, lng, 1 if is_online else 0, user_id))
    
    conn.commit()
    conn.close()

def get_online_drivers():
    """Get all online drivers"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.*, u.name as driver_name, u.phone, u.rating
        FROM drivers d 
        JOIN users u ON d.user_id = u.id 
        WHERE d.is_online = 1
    ''')
    drivers = cursor.fetchall()
    conn.close()
    return [dict(d) for d in drivers]

# ============================================
# RATING FUNCTIONS
# ============================================

def update_driver_rating(driver_id: str, new_rating: int):
    """Update driver's average rating"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current rating and total rides from ratings
    cursor.execute("SELECT AVG(rating), COUNT(*) FROM ratings WHERE driver_id = ?", (driver_id,))
    result = cursor.fetchone()
    
    current_avg = result[0] or 0
    total_ratings = result[1] or 0
    
    # Calculate new average
    new_avg = ((current_avg * total_ratings) + new_rating) / (total_ratings + 1)
    new_avg = round(new_avg, 1)
    
    # Update user's rating
    cursor.execute("UPDATE users SET rating = ? WHERE id = ?", (new_avg, driver_id))
    
    conn.commit()
    conn.close()
    print(f"⭐ Driver {driver_id[:8]} new rating: {new_avg}/5 from {total_ratings + 1} ratings")

def get_driver_rating(driver_id: str):
    """Get driver's current rating"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rating, total_rides FROM users WHERE id = ?", (driver_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {'rating': user[0] or 0, 'total_rides': user[1] or 0}
    return {'rating': 0, 'total_rides': 0}

def save_rating(ride_id: str, driver_id: str, customer_id: str, rating: int, comment: str = ''):
    """Save a rating to the database"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO ratings (ride_id, driver_id, customer_id, rating, comment)
        VALUES (?, ?, ?, ?, ?)
    ''', (ride_id, driver_id, customer_id, rating, comment))
    
    # Update ride with customer rating
    cursor.execute("UPDATE rides SET customer_rating = ? WHERE id = ?", (rating, ride_id))
    
    conn.commit()
    conn.close()
    print(f"⭐ Rating saved for ride {ride_id}: {rating}/5")

# ============================================
# RIDE FUNCTIONS
# ============================================

def save_ride(ride_data: dict):
    """Save completed ride to database"""
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
        ride_id,
        ride_data.get('customer_id'),
        ride_data.get('driver_id'),
        ride_data.get('pickup_lat'),
        ride_data.get('pickup_lng'),
        ride_data.get('destination_lat'),
        ride_data.get('destination_lng'),
        ride_data.get('distance_km'),
        ride_data.get('fare'),
        ride_data.get('status', 'completed'),
        ride_data.get('requested_at', datetime.now().isoformat()),
        ride_data.get('accepted_at'),
        ride_data.get('started_at'),
        ride_data.get('completed_at', datetime.now().isoformat())
    ))
    
    # Update driver earnings if driver exists
    cursor.execute('''
        UPDATE drivers 
        SET total_earnings = total_earnings + ?,
            today_earnings = today_earnings + ?,
            rides_today = rides_today + 1
        WHERE user_id = ?
    ''', (ride_data.get('fare', 0), ride_data.get('fare', 0), ride_data.get('driver_id')))
    
    # Update user total rides
    cursor.execute('''
        UPDATE users SET total_rides = total_rides + 1
        WHERE id = ?
    ''', (ride_data.get('customer_id'),))
    
    conn.commit()
    conn.close()
    print(f"💾 Ride {ride_id} saved to database!")
    return {'id': ride_id}

def get_driver_stats(driver_user_id: str):
    """Get driver statistics"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT total_earnings, today_earnings, rides_today, is_approved
        FROM drivers WHERE user_id = ?
    ''', (driver_user_id,))
    driver = cursor.fetchone()
    
    cursor.execute('''
        SELECT COUNT(*) as total_rides FROM rides WHERE driver_id = ? AND status = 'completed'
    ''', (driver_user_id,))
    rides = cursor.fetchone()
    
    conn.close()
    
    if driver:
        return {
            'total_earnings': driver[0] or 0,
            'today_earnings': driver[1] or 0,
            'rides_today': driver[2] or 0,
            'total_rides': rides[0] if rides else 0,
            'is_approved': bool(driver[3])
        }
    return {
        'total_earnings': 0,
        'today_earnings': 0,
        'rides_today': 0,
        'total_rides': 0,
        'is_approved': True
    }

def get_user_rides(user_id: str, limit: int = 20):
    """Get ride history for a user"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM rides 
        WHERE customer_id = ? OR driver_id = ?
        ORDER BY requested_at DESC LIMIT ?
    ''', (user_id, user_id, limit))
    rides = cursor.fetchall()
    conn.close()
    return [dict(ride) for ride in rides]

# ============================================
# OTP FUNCTIONS
# ============================================

def generate_otp(phone: str) -> str:
    """Generate and store OTP code"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Delete old OTPs
    cursor.execute("DELETE FROM otps WHERE phone = ?", (phone,))
    
    # Generate new OTP
    code = str(random.randint(100000, 999999))
    expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()
    
    cursor.execute('''
        INSERT INTO otps (phone, code, expires_at)
        VALUES (?, ?, ?)
    ''', (phone, code, expires_at))
    
    conn.commit()
    conn.close()
    
    print(f"📱 OTP for {phone}: {code}")
    return code

def verify_otp(phone: str, code: str) -> bool:
    """Verify OTP code"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM otps 
        WHERE phone = ? AND code = ? AND expires_at > ?
    ''', (phone, code, datetime.now().isoformat()))
    
    otp = cursor.fetchone()
    
    if otp:
        cursor.execute("DELETE FROM otps WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        return True
    
    conn.close()
    return False

# ============================================
# INITIALIZE DATABASE
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("📦 SQLITE DATABASE INITIALIZATION")
    print("=" * 50)
    
    init_db()
    
    print("\n✅ Database ready!")
    print("   File: boda_system.db")
    print("   Tables: users, drivers, rides, otps, ratings")
    print("   Rating System: Active")