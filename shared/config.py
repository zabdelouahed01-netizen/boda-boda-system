"""
CONFIGURATION FILE
This file stores all settings for our bike ride system
Think of it as the control panel for how the system behaves
"""

import os
from datetime import datetime

# ===== REDIS CONFIGURATION =====
# Redis is our fast in-memory database for driver locations
# These settings tell our code how to connect to Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')  # 'localhost' means same computer
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))    # 6379 is Redis's default port number

# ===== SERVER CONFIGURATION =====
# Where our backend server will run
SERVER_HOST = '0.0.0.0'  # '0.0.0.0' means accept connections from anywhere
SERVER_PORT = 8000       # Port 8000 - like a door number for our server

# ===== RIDE MATCHING CONFIGURATION =====
MAX_SEARCH_RADIUS_KM = 5          # Look for drivers within 5 kilometers
DRIVER_TIMEOUT_SECONDS = 30       # Driver must respond within 30 seconds
MAX_RETRIES = 3                   # Try 3 times if no driver found

# ===== FARE CALCULATION =====
# How we calculate the ride price (in your local currency)
BASE_FARE = 50           # Minimum fare - customer pays at least this much
PER_KM_RATE = 20         # Each kilometer costs 20 currency units
PER_MINUTE_RATE = 5      # Each minute of travel costs 5 currency units

# ===== WEBSOCKET URL =====
# WebSockets keep a live connection between app and server
WEBSOCKET_URL = f'ws://localhost:{SERVER_PORT}'

# ===== DISPLAY CONFIGURATION =====
print("=" * 50)
print("🚀 BIKE RIDE SYSTEM CONFIGURATION")
print("=" * 50)
print(f"📍 Redis Server: {REDIS_HOST}:{REDIS_PORT}")
print(f"🌐 Web Server: http://{SERVER_HOST}:{SERVER_PORT}")
print(f"📡 WebSocket: {WEBSOCKET_URL}")
print(f"🔄 Search Radius: {MAX_SEARCH_RADIUS_KM}km")
print(f"💰 Base Fare: {BASE_FARE}")
print("=" * 50)