let currentUser = null;
let currentPhone = '';

async function sendOTP() {
    const phone = document.getElementById('phoneInput').value;
    if (!phone) { showLoginStatus('Enter phone number', 'error'); return; }
    currentPhone = phone;
    
    const res = await fetch('http://localhost:8000/api/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phone })
    });
    const data = await res.json();
    
    if (data.success) {
        document.getElementById('loginStep1').style.display = 'none';
        document.getElementById('loginStep2').style.display = 'block';
        if (data.otp) document.getElementById('otpInput').value = data.otp;
    }
}

async function verifyOTP() {
    const code = document.getElementById('otpInput').value;
    const res = await fetch('http://localhost:8000/api/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: currentPhone, code: code, role: 'driver', name: 'Driver' })
    });
    const data = await res.json();
    
    if (data.success) {
        currentUser = data.user;
        localStorage.setItem('driverId', currentUser.id);
        localStorage.setItem('driverPhone', currentUser.phone);
        document.getElementById('loginModal').style.display = 'none';
        startDriverApp();
    }
}

function checkLogin() {
    const driverId = localStorage.getItem('driverId');
    if (driverId) {
        document.getElementById('loginModal').style.display = 'none';
        startDriverApp();
    }
}

function startDriverApp() {
    // Initialize driver app
    initMap();
    getLocation();
    startWatching();
    connectWebSocket();
    loadEarnings();
}

checkLogin();
/**
 * DRIVER APP - JavaScript
 * Handles location tracking, ride acceptance, and navigation
 */

// ============================================
// GLOBAL VARIABLES
// ============================================

let map;                    // Leaflet map
let driverMarker;           // Driver's location marker
let customerMarker;         // Customer's location marker (for active ride)
let watchId;                // Geolocation watch ID
let ws;                     // WebSocket connection
let driverId;               // Unique driver ID
let isOnline = false;       // Online status
let currentLocation = null; // Current lat/lng
let currentRide = null;     // Currently active ride
let currentRideId = null;   // Active ride ID
let earnings = 0;           // Today's earnings
let ridesCompleted = 0;     // Number of rides today
let locationUpdateInterval = null;

// ============================================
// INITIALIZATION
// ============================================

window.onload = async () => {
    console.log('🏍️ Driver App Starting...');
    
    // Generate unique driver ID (stored in browser)
    driverId = localStorage.getItem('driverId');
    if (!driverId) {
        driverId = 'driver_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
        localStorage.setItem('driverId', driverId);
    }
    console.log('📱 Driver ID:', driverId);
    
    // Load saved earnings
    loadEarnings();
    
    // Initialize map
    initMap();
    
    // Get current location
    await getCurrentLocation();
    
    // Connect WebSocket
    connectWebSocket();
    
    // Start watching position
    startWatchingPosition();
    
    // Setup event listeners
    setupEventListeners();
    
    // Update stats periodically
    setInterval(updateStats, 10000);
    
    console.log('✅ Driver App Ready');
};

/**
 * Initialize map
 */
function initMap() {
    map = L.map('map').setView([14.5995, 120.9842], 14);
    
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    // Driver marker (motorcycle)
    driverMarker = L.marker([0, 0], {
        icon: L.divIcon({
            html: '🏍️',
            iconSize: [35, 35],
            className: 'driver-marker'
        })
    }).addTo(map);
    
    // Customer marker (for active rides)
    customerMarker = L.marker([0, 0], {
        icon: L.divIcon({
            html: '📍',
            iconSize: [30, 30],
            className: 'customer-marker'
        })
    }).addTo(map);
    
    customerMarker.setOpacity(0);
    
    console.log('🗺️ Map initialized');
}

/**
 * Get current location
 */
async function getCurrentLocation() {
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                currentLocation = {
                    lat: position.coords.latitude,
                    lng: position.coords.longitude
                };
                
                map.setView([currentLocation.lat, currentLocation.lng], 15);
                driverMarker.setLatLng([currentLocation.lat, currentLocation.lng]);
                
                resolve(currentLocation);
            },
            (error) => {
                console.error('Geolocation error:', error);
                showNotification('Please enable location access', 'error');
                resolve(null);
            },
            {
                enableHighAccuracy: true,
                timeout: 10000
            }
        );
    });
}

/**
 * Start watching position for live updates
 */
function startWatchingPosition() {
    watchId = navigator.geolocation.watchPosition(
        (position) => {
            currentLocation = {
                lat: position.coords.latitude,
                lng: position.coords.longitude
            };
            
            // Update driver marker
            driverMarker.setLatLng([currentLocation.lat, currentLocation.lng]);
            
            // Send location to server if online
            if (ws && ws.readyState === WebSocket.OPEN && isOnline) {
                ws.send(JSON.stringify({
                    type: 'location_update',
                    lat: currentLocation.lat,
                    lng: currentLocation.lng,
                    status: isOnline ? 'online' : 'offline',
                    current_ride_id: currentRideId
                }));
            }
        },
        (error) => {
            console.error('Watch position error:', error);
        },
        {
            enableHighAccuracy: true,
            maximumAge: 10000,
            timeout: 27000
        }
    );
}

// ============================================
// WEBSOCKET CONNECTION
// ============================================

/**
 * Connect to WebSocket server
 */
function connectWebSocket() {
    const wsUrl = `ws://localhost:8000/ws/driver/${driverId}`;
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        showNotification('Connected to server!', 'success');
        
        // Send initial status
        if (currentLocation && isOnline) {
            ws.send(JSON.stringify({
                type: 'location_update',
                lat: currentLocation.lat,
                lng: currentLocation.lng,
                status: 'online'
            }));
        }
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('📨 Received:', data);
        handleServerMessage(data);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        showNotification('Connection error', 'error');
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        setTimeout(connectWebSocket, 3000);
    };
}

/**
 * Handle messages from server
 */
function handleServerMessage(data) {
    switch(data.type) {
        case 'connected':
            showNotification(data.message, 'success');
            break;
            
        case 'new_ride_request':
            // Show new ride request
            addRideRequest(data);
            // Play sound notification (optional)
            playNotificationSound();
            break;
            
        case 'ride_accepted':
            // Ride accepted confirmation
            showNotification('Ride accepted! Head to pickup location.', 'success');
            break;
            
        case 'ride_cancelled_by_customer':
            // Customer cancelled
            showNotification('Customer cancelled the ride', 'warning');
            clearActiveRide();
            break;
            
        case 'status_report':
            updateStatsFromServer(data);
            break;
            
        case 'error':
            showNotification('Error: ' + data.message, 'error');
            break;
    }
}

// ============================================
// RIDE MANAGEMENT
// ============================================

/**
 * Add ride request to the list
 */
function addRideRequest(ride) {
    const requestsList = document.getElementById('requestsList');
    
    // Remove empty state if present
    if (requestsList.innerHTML.includes('empty-state')) {
        requestsList.innerHTML = '';
    }
    
    const requestDiv = document.createElement('div');
    requestDiv.className = 'ride-request';
    requestDiv.id = `request_${ride.ride_id}`;
    requestDiv.innerHTML = `
        <h4>🚲 New Ride Request!</h4>
        <p>📍 Pickup: ${ride.pickup || 'Current location'}</p>
        <p>🎯 Destination: ${ride.destination || 'Not specified'}</p>
        <p>📏 Distance: <span class="distance">${ride.distance_km || 2}km away</span></p>
        <p>💰 Est. fare: ₱${Math.round(50 + (ride.distance_km || 2) * 20)}</p>
        <div class="button-group">
            <button class="accept-btn" onclick="acceptRide('${ride.ride_id}')">✅ Accept</button>
            <button class="decline-btn" onclick="declineRide('${ride.ride_id}')">❌ Decline</button>
        </div>
    `;
    
    requestsList.insertBefore(requestDiv, requestsList.firstChild);
    
    // Show customer marker on map if pickup location exists
    if (ride.pickup_lat && ride.pickup_lng) {
        customerMarker.setLatLng([ride.pickup_lat, ride.pickup_lng]);
        customerMarker.setOpacity(0.7);
        customerMarker.bindPopup('Pickup location').openPopup();
        
        // Fit map to show both driver and pickup
        const bounds = L.latLngBounds([
            [currentLocation.lat, currentLocation.lng],
            [ride.pickup_lat, ride.pickup_lng]
        ]);
        map.fitBounds(bounds, { padding: [50, 50] });
    }
    
    // Update pending rides count
    updatePendingRidesCount();
}

/**
 * Accept a ride
 */
function acceptRide(rideId) {
    if (!currentLocation) {
        showNotification('Getting your location...', 'warning');
        return;
    }
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'accept_ride',
            ride_id: rideId,
            driver_lat: currentLocation.lat,
            driver_lng: currentLocation.lng
        }));
        
        currentRideId = rideId;
        currentRide = { ride_id: rideId, status: 'accepted' };
        
        // Remove from requests list
        const requestDiv = document.getElementById(`request_${rideId}`);
        if (requestDiv) requestDiv.remove();
        
        // Show active ride section
        showActiveRide(rideId);
        
        showNotification('Ride accepted! Navigate to pickup.', 'success');
    }
}

/**
 * Decline a ride
 */
function declineRide(rideId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'decline_ride',
            ride_id: rideId
        }));
        
        // Remove from requests list
        const requestDiv = document.getElementById(`request_${rideId}`);
        if (requestDiv) requestDiv.remove();
        
        showNotification('Ride declined', 'info');
        
        // Update pending rides count
        updatePendingRidesCount();
    }
}

/**
 * Show active ride UI
 */
function showActiveRide(rideId) {
    document.getElementById('requestsSection').style.display = 'none';
    document.getElementById('activeRideSection').style.display = 'block';
    
    const activeRideInfo = document.getElementById('activeRideInfo');
    activeRideInfo.innerHTML = `
        <div class="active-ride">
            <h4>🏍️ Ride in Progress</h4>
            <p><strong>Status:</strong> <span id="rideStatusText">Heading to pickup</span></p>
            <button class="start-btn" id="startRideBtn" onclick="startRide()">🚀 Arrived at Pickup - Start Ride</button>
            <button class="complete-btn" id="completeRideBtn" style="display:none;" onclick="completeRide()">✅ Complete Ride</button>
        </div>
    `;
}

/**
 * Start ride (arrived at pickup)
 */
function startRide() {
    if (ws && ws.readyState === WebSocket.OPEN && currentRideId) {
        ws.send(JSON.stringify({
            type: 'ride_started',
            ride_id: currentRideId
        }));
        
        document.getElementById('rideStatusText').innerHTML = '🚀 Ride in progress - Heading to destination';
        document.getElementById('startRideBtn').style.display = 'none';
        document.getElementById('completeRideBtn').style.display = 'block';
        
        showNotification('Ride started! Head to destination.', 'success');
    }
}

/**
 * Complete ride
 */
function completeRide() {
    const fare = Math.floor(Math.random() * 100) + 70; // Random fare ₱70-170
    
    if (ws && ws.readyState === WebSocket.OPEN && currentRideId) {
        ws.send(JSON.stringify({
            type: 'ride_completed',
            ride_id: currentRideId,
            fare: fare,
            distance_km: Math.floor(Math.random() * 8) + 2
        }));
        
        // Add to earnings
        earnings += fare;
        ridesCompleted++;
        saveEarnings();
        updateEarningsDisplay();
        
        showNotification(`Ride complete! Earned ₱${fare}`, 'success');
        
        clearActiveRide();
    }
}

/**
 * Clear active ride and return to online mode
 */
function clearActiveRide() {
    currentRideId = null;
    currentRide = null;
    
    document.getElementById('requestsSection').style.display = 'block';
    document.getElementById('activeRideSection').style.display = 'none';
    
    customerMarker.setOpacity(0);
    
    // Refresh requests list
    document.getElementById('requestsList').innerHTML = '<div class="empty-state">No ride requests at the moment</div>';
}

// ============================================
// UI HELPERS
// ============================================

/**
 * Setup event listeners
 */
function setupEventListeners() {
    const toggle = document.getElementById('onlineToggle');
    toggle.addEventListener('change', (e) => {
        toggleOnline(e.target.checked);
    });
}

/**
 * Toggle online/offline status
 */
function toggleOnline(online) {
    isOnline = online;
    
    const statusText = document.getElementById('statusText');
    const toggle = document.getElementById('onlineToggle');
    
    if (online) {
        statusText.textContent = 'Online';
        statusText.className = 'status-badge badge-online';
        showNotification('You are now ONLINE - Ready to receive rides!', 'success');
        
        // Send online status to server
        if (ws && ws.readyState === WebSocket.OPEN && currentLocation) {
            ws.send(JSON.stringify({
                type: 'location_update',
                lat: currentLocation.lat,
                lng: currentLocation.lng,
                status: 'online'
            }));
        }
    } else {
        statusText.textContent = 'Offline';
        statusText.className = 'status-badge badge-offline';
        showNotification('You are now OFFLINE', 'info');
        
        // Send offline status to server
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'location_update',
                lat: currentLocation?.lat || 0,
                lng: currentLocation?.lng || 0,
                status: 'offline'
            }));
        }
        
        // Clear requests
        document.getElementById('requestsList').innerHTML = '<div class="empty-state">Go online to receive ride requests</div>';
    }
}

/**
 * Update pending rides count in UI
 */
function updatePendingRidesCount() {
    const requests = document.querySelectorAll('.ride-request').length;
    document.getElementById('pendingRidesCount').textContent = requests;
}

/**
 * Update stats from server
 */
function updateStatsFromServer(data) {
    if (data.online_drivers !== undefined) {
        document.getElementById('onlineDriversCount').textContent = data.online_drivers;
    }
    if (data.pending_rides !== undefined) {
        document.getElementById('pendingRidesCount').textContent = data.pending_rides;
    }
}

/**
 * Update stats by fetching from server
 */
async function updateStats() {
    try {
        const response = await fetch('http://localhost:8000/');
        const data = await response.json();
        if (data.stats) {
            document.getElementById('onlineDriversCount').textContent = data.stats.online_drivers || 0;
            document.getElementById('pendingRidesCount').textContent = data.stats.pending_rides || 0;
        }
    } catch (error) {
        console.log('Could not fetch stats');
    }
}

// ============================================
// EARNINGS MANAGEMENT
// ============================================

/**
 * Load earnings from localStorage
 */
function loadEarnings() {
    const saved = localStorage.getItem('driverEarnings');
    if (saved) {
        const data = JSON.parse(saved);
        earnings = data.earnings || 0;
        ridesCompleted = data.rides || 0;
    }
    updateEarningsDisplay();
}

/**
 * Save earnings to localStorage
 */
function saveEarnings() {
    localStorage.setItem('driverEarnings', JSON.stringify({
        earnings: earnings,
        rides: ridesCompleted,
        date: new Date().toDateString()
    }));
}

/**
 * Update earnings display
 */
function updateEarningsDisplay() {
    document.getElementById('earningsAmount').textContent = `₱${earnings}`;
    document.getElementById('ridesCount').textContent = ridesCompleted;
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

/**
 * Play notification sound
 */
function playNotificationSound() {
    try {
        const audio = new Audio('https://www.soundjay.com/misc/sounds/bell-ringing-05.mp3');
        audio.play().catch(e => console.log('Cannot play sound'));
    } catch(e) {
        console.log('Sound not supported');
    }
}

/**
 * Show notification
 */
function showNotification(message, type = 'info') {
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();
    
    const notification = document.createElement('div');
    notification.className = 'notification';
    
    let bgColor = '#333';
    if (type === 'success') bgColor = '#4CAF50';
    if (type === 'error') bgColor = '#f44336';
    if (type === 'warning') bgColor = '#ff9800';
    if (type === 'info') bgColor = '#2196F3';
    
    notification.style.backgroundColor = bgColor;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// ============================================
// CLEANUP
// ============================================

window.onbeforeunload = () => {
    if (watchId) {
        navigator.geolocation.clearWatch(watchId);
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'location_update',
            status: 'offline'
        }));
        ws.close();
    }
};

console.log('Driver App JS loaded');
'@ | Out-File -FilePath "driver-app\app.js" -Encoding UTF8'

'Write-Host "✅ Driver App JavaScript created!" -ForegroundColor Green'