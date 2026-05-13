"""
MATCHING ENGINE
This finds the nearest driver to a customer
It's like a GPS-based matchmaker for rides
"""

import math
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import redis.asyncio as redis
from geopy.distance import geodesic

# Import our configuration
from shared.config import MAX_SEARCH_RADIUS_KM

class MatchingEngine:
    """
    The MatchingEngine finds and assigns drivers to customers
    Think of it as a automated dispatcher
    """
    
    def __init__(self):
        # Redis connection (will be set up later)
        self.redis = None
        
        # In-memory storage for active connections
        # These are Python dictionaries (like address books)
        self.active_drivers = {}     # {driver_id: websocket_connection}
        self.active_customers = {}    # {customer_id: websocket_connection}
        self.pending_requests = {}    # {request_id: ride_details}
        
        print("✅ Matching Engine initialized")
    
    async def connect_redis(self):
        """
        Connect to Redis database
        This is like opening a phone line to our fast database
        """
        try:
            self.redis = await redis.Redis(
                host='localhost',
                port=6379,
                decode_responses=True,  # Convert bytes to strings automatically
                db=0                    # Use database 0 (Redis can have multiple databases)
            )
            
            # Test the connection
            await self.redis.ping()
            print("✅ Connected to Redis successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect to Redis: {e}")
            print("   Make sure Redis is running! (redis-server command)")
            return False
    
    def calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """
        Calculate the distance between two points on Earth
        Returns distance in kilometers
        
        Example: 
            calculate_distance(37.7749, -122.4194, 37.7694, -122.4862) 
            Returns about 5.7km (San Francisco to Oakland)
        """
        try:
            # Use geopy's geodesic formula (most accurate)
            distance = geodesic((lat1, lng1), (lat2, lng2)).kilometers
            return round(distance, 2)  # Round to 2 decimal places
            
        except Exception as e:
            # If geopy fails, use the Haversine formula (fallback)
            # This is a mathematical formula for great-circle distance
            R = 6371  # Earth's radius in kilometers
            
            # Convert degrees to radians
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1)
            delta_lng = math.radians(lng2 - lng1)
            
            # Haversine formula
            a = math.sin(delta_lat/2)**2 + \
                math.cos(lat1_rad) * math.cos(lat2_rad) * \
                math.sin(delta_lng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance = R * c
            
            return round(distance, 2)
    
    async def find_nearest_driver(self, pickup_lat: float, pickup_lng: float) -> Optional[Tuple[str, float]]:
        """
        Find the closest available driver to the pickup location
        
        Returns: (driver_id, distance_in_km) or None if no drivers found
        
        This is the CORE MATCHING LOGIC - most important function in the system
        """
        try:
            # Step 1: Get all online drivers from Redis
            # Redis stores driver IDs in a "set" (like a list with no duplicates)
            drivers = await self.redis.smembers('drivers:online')
            
            if not drivers:
                print("📢 No online drivers available")
                return None
            
            print(f"🔍 Checking {len(drivers)} online drivers...")
            
            # Step 2: Calculate distance to each driver
            nearest_driver = None
            min_distance = float('inf')  # Start with infinity
            
            for driver_id in drivers:
                # Get this driver's last known location
                location = await self.redis.hgetall(f'driver:{driver_id}:location')
                
                if location and 'lat' in location and 'lng' in location:
                    # Calculate distance from pickup to this driver
                    distance = self.calculate_distance(
                        pickup_lat, pickup_lng,
                        float(location['lat']), float(location['lng'])
                    )
                    
                    print(f"   Driver {driver_id[:8]}... is {distance:.2f}km away")
                    
                    # Check if this driver is closer than previous best
                    if distance < min_distance and distance <= MAX_SEARCH_RADIUS_KM:
                        min_distance = distance
                        nearest_driver = driver_id
            
            # Step 3: Return result
            if nearest_driver:
                print(f"✅ Found nearest driver: {nearest_driver[:8]}... ({min_distance:.2f}km)")
                return (nearest_driver, min_distance)
            else:
                print(f"❌ No drivers within {MAX_SEARCH_RADIUS_KM}km radius")
                return None
                
        except Exception as e:
            print(f"💥 Error finding nearest driver: {e}")
            return None
    
    async def update_driver_location(self, driver_id: str, lat: float, lng: float, status: str = 'online'):
        """
        Store a driver's current location in Redis
        This gets called every few seconds as the driver moves
        """
        try:
            # Update the online drivers set
            if status == 'online':
                await self.redis.sadd('drivers:online', driver_id)
                print(f"📍 Driver {driver_id[:8]}... is ONLINE at ({lat:.4f}, {lng:.4f})")
            else:
                await self.redis.srem('drivers:online', driver_id)
                print(f"📍 Driver {driver_id[:8]}... is OFFLINE")
            
            # Store the location with an expiry (TTL = Time To Live)
            # If driver doesn't send update for 30 seconds, they're removed
            await self.redis.hset(f'driver:{driver_id}:location', mapping={
                'lat': lat,
                'lng': lng,
                'status': status,
                'updated_at': datetime.now().isoformat()
            })
            
            # Set expiry to 30 seconds
            await self.redis.expire(f'driver:{driver_id}:location', 30)
            
            return True
            
        except Exception as e:
            print(f"💥 Error updating driver location: {e}")
            return False
    
    async def remove_driver(self, driver_id: str):
        """
        Remove a driver from the system when they disconnect
        """
        try:
            await self.redis.srem('drivers:online', driver_id)
            await self.redis.delete(f'driver:{driver_id}:location')
            print(f"🗑️ Removed driver {driver_id[:8]}... from system")
            return True
        except Exception as e:
            print(f"💥 Error removing driver: {e}")
            return False
    
    async def calculate_fare(self, distance_km: float, duration_minutes: float) -> int:
        """
        Calculate the ride fare based on distance and estimated time
        """
        from shared.config import BASE_FARE, PER_KM_RATE, PER_MINUTE_RATE
        
        fare = BASE_FARE + (distance_km * PER_KM_RATE) + (duration_minutes * PER_MINUTE_RATE)
        
        # Round to nearest 10 units (makes pricing look cleaner)
        fare = int(round(fare / 10) * 10)
        
        # Ensure minimum fare
        fare = max(fare, BASE_FARE)
        
        return fare

# Create a global instance of the matching engine
# This single instance will be used throughout the application
matching_engine = MatchingEngine()