/**
 * CUSTOMER APP - JavaScript
 * Handles map, location, WebSocket communication, and UI
 */
// ============ AUTHENTICATION ============
let currentUser = null;
let currentPhone = '';

async function sendOTP() {
    const phone = document.getElementById('phoneInput').value;
    if (!phone) {
        showLoginStatus('Please enter your phone number', 'error');
        return;
    }
    
    currentPhone = phone;
    showLoginStatus('Sending OTP...', 'info');
    
    try {
        const response = await fetch('http://localhost:8000/api/send-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: phone })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showLoginStatus('OTP sent! Check code below', 'success');
            document.getElementById('loginStep1').style.display = 'none';
            document.getElementById('loginStep2').style.display = 'block';
            
            // Auto-fill OTP for testing
            if (data.otp) {
                document.getElementById('otpInput').value = data.otp;
            }
        } else {
            showLoginStatus(data.message || 'Failed to send OTP', 'error');
        }
    } catch (error) {
        showLoginStatus('Connection error. Is the server running?', 'error');
    }
}

async function verifyOTP() {
    const code = document.getElementById('otpInput').value;
    if (!code) {
        showLoginStatus('Please enter the OTP code', 'error');
        return;
    }
    
    showLoginStatus('Verifying...', 'info');
    
    try {
        const response = await fetch('http://localhost:8000/api/verify-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone: currentPhone,
                code: code,
                role: 'customer'
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentUser = data.user;
            localStorage.setItem('userId', currentUser.id);
            localStorage.setItem('userPhone', currentUser.phone);
            localStorage.setItem('userName', currentUser.name);
            
            showLoginStatus('Login successful!', 'success');
            
            setTimeout(() => {
                document.getElementById('loginModal').style.display = 'none';
                startApp();
            }, 1000);
        } else {
            showLoginStatus(data.message || 'Invalid OTP', 'error');
        }
    } catch (error) {
        showLoginStatus('Connection error', 'error');
    }
}

function resetLogin() {
    document.getElementById('loginStep1').style.display = 'block';
    document.getElementById('loginStep2').style.display = 'none';
    document.getElementById('loginStep3').style.display = 'none';
    document.getElementById('otpInput').value = '';
    showLoginStatus('', '');
}

function completeRegistration() {
    const name = document.getElementById('nameInput').value;
    if (!name) {
        showLoginStatus('Please enter your name', 'error');
        return;
    }
    
    // Update user name
    currentUser.name = name;
    localStorage.setItem('userName', name);
    
    document.getElementById('loginModal').style.display = 'none';
    startApp();
}

function showLoginStatus(message, type) {
    const statusDiv = document.getElementById('loginStatus');
    statusDiv.textContent = message;
    statusDiv.style.color = type === 'error' ? '#f44336' : type === 'success' ? '#4CAF50' : '#999';
}

function checkLogin() {
    const userId = localStorage.getItem('userId');
    if (userId) {
        // User already logged in
        document.getElementById('loginModal').style.display = 'none';
        currentUser = {
            id: userId,
            phone: localStorage.getItem('userPhone'),
            name: localStorage.getItem('userName')
        };
        startApp();
    }
}

function startApp() {
    console.log('Starting app for user:', currentUser);
    initMap();
    getCurrentLocation();
    connectWebSocket();
}

// Call this when page loads
checkLogin();
// ============================================
// GLOBAL VARIABLES
// ============================================

let map;                    // Leaflet map object
let customerMarker;         // Marker for customer location
let driverMarker;           // Marker for driver location
let watchId;                // Geolocation watch ID
let ws;                     // WebSocket connection
let customerId;             // Unique customer ID
let currentLocation = null; // Current lat/lng
let currentRideId = null;   // Active ride ID
let currentDriverId = null; // Assigned driver ID
let rideStartTime = null;   // When ride started
let locationUpdateInterval = null; // For sending location updates

// Bike type base fares
const bikeFares = {
    'standard': 50,
    'electric': 70,
    'cargo': 80
};

// ============================================
// INITIALIZATION
// ============================================

/**
 * Initialize everything when page loads
 */
window.onload = async () => {
    console.log('🚲 Customer App Starting...');
    
    // Generate unique customer ID (stored in browser)
    customerId = localStorage.getItem('customerId');
    if (!customerId) {
        customerId = 'customer_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
        localStorage.setItem('customerId', customerId);
    }
    console.log('📱 Customer ID:', customerId);
    
    // Initialize map
    initMap();
    
    // Get current location
    await getCurrentLocation();
    
    // Connect WebSocket
    connectWebSocket();
    
    // Start watching position (for live tracking)
    startWatchingPosition();
    
    // Setup destination input listener for fare calculation
    document.getElementById('destinationInput').addEventListener('input', calculateFare);
    document.getElementById('bikeType').addEventListener('change', calculateFare);
    
    console.log('✅ Customer App Ready');
};

/**
 * Initialize Leaflet map
 */
function initMap() {
    // Create map centered on a default location (will update when we get GPS)
    map = L.map('map').setView([14.5995, 120.9842], 13); // Manila coordinates
    
    // Add OpenStreetMap tiles (free!)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);
    
    // Create customer marker (blue dot)
    customerMarker = L.marker([0, 0], {
        icon: L.divIcon({
            className: 'customer-marker',
            html: '📍',
            iconSize: [30, 30],
            popupAnchor: [0, -15]
        })
    }).addTo(map);
    
    // Create driver marker (motorcycle icon)
    driverMarker = L.marker([0, 0], {
        icon: L.divIcon({
            className: 'driver-marker',
            html: '🏍️',
            iconSize: [35, 35],
            popupAnchor: [0, -17]
        })
    }).addTo(map);
    
    // Hide driver marker initially
    driverMarker.setOpacity(0);
    
    // Add scale control
    L.control.scale().addTo(map);
    
    console.log('🗺️ Map initialized');
}

/**
 * Get current location from GPS
 */
async function getCurrentLocation() {
    if (!navigator.geolocation) {
        showNotification('Geolocation not supported by your browser', 'error');
        document.getElementById('pickupInput').value = 'Location not available';
        return;
    }
    
    showNotification('Getting your location...', 'info');
    
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (position) => {
                currentLocation = {
                    lat: position.coords.latitude,
                    lng: position.coords.longitude
                };
                
                console.log('📍 Location obtained:', currentLocation);
                
                // Update map
                map.setView([currentLocation.lat, currentLocation.lng], 15);
                customerMarker.setLatLng([currentLocation.lat, currentLocation.lng]);
                
                // Get address from coordinates (reverse geocoding)
                getAddressFromCoords(currentLocation.lat, currentLocation.lng).then(address => {
                    document.getElementById('pickupInput').value = address;
                });
                
                showNotification('Location detected!', 'success');
                resolve(currentLocation);
            },
            (error) => {
                console.error('Geolocation error:', error);
                let errorMessage = 'Unable to get location';
                
                switch(error.code) {
                    case error.PERMISSION_DENIED:
                        errorMessage = 'Please allow location access';
                        break;
                    case error.POSITION_UNAVAILABLE:
                        errorMessage = 'Location unavailable';
                        break;
                    case error.TIMEOUT:
                        errorMessage = 'Location timeout';
                        break;
                }
                
                document.getElementById('pickupInput').value = errorMessage;
                showNotification(errorMessage, 'error');
                resolve(null);
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0
            }
        );
    });
}

/**
 * Convert coordinates to address (reverse geocoding)
 */
async function getAddressFromCoords(lat, lng) {
    try {
        // Using OpenStreetMap's Nominatim (free, no API key needed)
        const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`);
        const data = await response.json();
        
        if (data.display_name) {
            // Extract short address
            const road = data.address.road || '';
            const city = data.address.city || data.address.town || data.address.village || '';
            return `${road}, ${city}`.trim() || data.display_name.substring(0, 50);
        }
        return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    } catch (error) {
        console.error('Reverse geocoding error:', error);
        return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    }
}

/**
 * Start watching position for live updates
 */
function startWatchingPosition() {
    if (!navigator.geolocation) return;
    
    watchId = navigator.geolocation.watchPosition(
        (position) => {
            currentLocation = {
                lat: position.coords.latitude,
                lng: position.coords.longitude
            };
            
            // Update customer marker
            customerMarker.setLatLng([currentLocation.lat, currentLocation.lng]);
            
            // Update pickup input if not in a ride
            if (!currentRideId) {
                getAddressFromCoords(currentLocation.lat, currentLocation.lng).then(address => {
                    document.getElementById('pickupInput').value = address;
                });
            }
            
            // If we have a WebSocket connection, send location update
            if (ws && ws.readyState === WebSocket.OPEN && currentRideId) {
                ws.send(JSON.stringify({
                    type: 'customer_location',
                    ride_id: currentRideId,
                    lat: currentLocation.lat,
                    lng: currentLocation.lng
                }));
            }
        },
        (error) => {
            console.error('Watch position error:', error);
        },
        {
            enableHighAccuracy: true,
            maximumAge: 30000,
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
    const wsUrl = `ws://localhost:8000/ws/customer/${customerId}`;
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        showNotification('Connected to server!', 'success');
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
        console.log('WebSocket disconnected, reconnecting in 3 seconds...');
        showNotification('Reconnecting...', 'warning');
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
            
        case 'searching_for_driver':
            // Show searching status
            currentRideId = data.ride_id;
            document.getElementById('requestForm').style.display = 'none';
            document.getElementById('rideStatus').style.display = 'block';
            document.getElementById('rideComplete').style.display = 'none';
            
            document.getElementById('statusMessage').innerHTML = `
                <span class="status-badge status-searching">Searching</span>
                <div class="loading">
                    <div class="spinner"></div>
                    <p>${data.message}</p>
                    <small style="color: #999;">Estimated wait: ${data.estimated_wait || 3} minutes</small>
                </div>
            `;
            
            document.getElementById('statusTitle').innerHTML = '🔍 Finding your ride...';
            showNotification(data.message, 'info');
            break;
            
        case 'driver_assigned':
    console.log('Driver assigned:', data);
    showStatus('✅ Driver found! They are on the way.', 'success');
    document.getElementById('requestBtn').style.display = 'none';
    document.getElementById('cancelBtn').style.display = 'block';
    
    // ★ STORE DRIVER ID FOR RATING ★
    currentDriverId = data.driver_id;
    console.log('Driver ID stored for rating:', currentDriverId);
    
    // Show driver marker
    if (data.driver_location) {
        driverMarker.setLatLng([data.driver_location.lat, data.driver_location.lng]);
        driverMarker.setOpacity(1);
        driverMarker.bindPopup('Driver location').openPopup();
    }
    break;
            
        case 'driver_location_update':
            // Update driver marker position
            if (data.lat && data.lng) {
                driverMarker.setLatLng([data.lat, data.lng]);
                
                // Calculate distance to driver
                if (currentLocation) {
                    const distance = calculateDistance(
                        currentLocation.lat, currentLocation.lng,
                        data.lat, data.lng
                    );
                    const etaMinutes = Math.max(1, Math.round(distance * 3)); // Rough ETA
                    document.getElementById('driverETA').innerHTML = `${etaMinutes} minutes`;
                }
                
                // Center map on driver if not too far
                const distanceToDriver = calculateDistance(
                    currentLocation.lat, currentLocation.lng,
                    data.lat, data.lng
                );
                
                if (distanceToDriver > 0.5) {
                    // Show both markers by fitting bounds
                    const bounds = L.latLngBounds([
                        [currentLocation.lat, currentLocation.lng],
                        [data.lat, data.lng]
                    ]);
                    map.fitBounds(bounds, { padding: [50, 50] });
                }
            }
            break;
            
        case 'ride_started':
            document.getElementById('driverStatus').innerHTML = '🚀 In progress - heading to destination';
            document.getElementById('statusTitle').innerHTML = '🚀 Ride in progress!';
            rideStartTime = Date.now();
            showNotification('Your ride has started! Enjoy the trip!', 'success');
            break;
            
        case 'ride_completed':
            // Ride finished
            const fare = data.fare || 100;
            const distance = data.distance_km || 5;
            
            document.getElementById('rideStatus').style.display = 'none';
            document.getElementById('rideComplete').style.display = 'block';
            document.getElementById('finalFare').innerHTML = `₱${fare}`;
            document.getElementById('rideDetails').innerHTML = `Distance: ${distance}km | Duration: ${Math.round((Date.now() - (rideStartTime || Date.now())) / 60000)} mins`;
            
            showNotification(`Ride complete! Total: ₱${fare}`, 'success');
            
            // Save to ride history
            saveToHistory({
                id: currentRideId,
                date: new Date().toISOString(),
                fare: fare,
                distance: distance,
                destination: document.getElementById('destinationInput').value
            });
            
            // Reset current ride
            currentRideId = null;
            currentDriverId = null;
            driverMarker.setOpacity(0);
            break;
            
        case 'no_drivers':
            alert('No drivers available nearby. Please try again in a few minutes.');
            resetToRequestForm();
            break;
            
        case 'ride_cancelled':
            showNotification('Ride cancelled', 'warning');
            resetToRequestForm();
            break;
            
        case 'error':
            showNotification('Error: ' + data.message, 'error');
            if (currentRideId) {
                resetToRequestForm();
            }
            break;
            
        case 'status_report':
            console.log('Status report:', data);
            break;
    }
}

// ============================================
// RIDE FUNCTIONS
// ============================================

/**
 * Calculate fare estimate
 */
function calculateFare() {
    const destination = document.getElementById('destinationInput').value;
    const bikeType = document.getElementById('bikeType').value;
    
    if (!destination || !currentLocation) {
        document.getElementById('fareEstimate').style.display = 'none';
        return;
    }
    
    // Simple fare calculation based on bike type and estimated distance
    const baseFare = bikeFares[bikeType];
    // Assume average distance of 3-8km based on destination text length
    const estimatedDistance = Math.min(10, Math.max(2, destination.length / 5));
    const estimatedFare = baseFare + (estimatedDistance * 15);
    
    document.getElementById('estimatedFare').innerHTML = `₱${Math.round(estimatedFare)}`;
    document.getElementById('fareEstimate').style.display = 'block';
}

/**
 * Request a ride
 */
function requestRide() {
    const destination = document.getElementById('destinationInput').value;
    const bikeType = document.getElementById('bikeType').value;
    const pickup = document.getElementById('pickupInput').value;
    
    if (!destination) {
        showNotification('Please enter a destination', 'error');
        return;
    }
    
    if (!currentLocation) {
        showNotification('Unable to get your location. Please refresh.', 'error');
        return;
    }
    
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showNotification('Connecting to server...', 'warning');
        connectWebSocket();
        setTimeout(() => requestRide(), 1000);
        return;
    }
    
    // Disable request button
    const requestBtn = document.getElementById('requestBtn');
    requestBtn.disabled = true;
    requestBtn.textContent = 'Requesting...';
    
    // Send ride request to server
    ws.send(JSON.stringify({
        type: 'request_ride',
        pickup: pickup,
        destination: destination,
        bike_type: bikeType,
        pickup_lat: currentLocation.lat,
        pickup_lng: currentLocation.lng
    }));
    
    showNotification('Looking for nearby drivers...', 'info');
    
    // Re-enable button after 2 seconds if no response
    setTimeout(() => {
        requestBtn.disabled = false;
        requestBtn.textContent = '🚲 Find a Bike';
    }, 2000);

// Calculate estimated fare before requesting
function calculateEstimatedFare(distanceKm) {
    const baseFare = 50;
    const perKmRate = 20;
    return baseFare + (distanceKm * perKmRate);
}

// Show fare when destination is set
async function onMapClick(e) {
    // ... existing code ...
    
    // Calculate distance and fare
    if (currentLocation) {
        const distance = calculateDistance(
            currentLocation.lat, currentLocation.lng,
            lat, lng
        );
        const fare = calculateEstimatedFare(distance);
        showStatus(`💰 Estimated fare: ₱${Math.round(fare)} (${distance.toFixed(1)}km)`, 'info');
    }
}

}

/**
 * Cancel current ride
 */
function cancelRide() {
    if (!currentRideId) return;
    
    if (confirm('Are you sure you want to cancel this ride?')) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'cancel_ride',
                ride_id: currentRideId
            }));
        }
        
        showNotification('Cancelling ride...', 'warning');
        resetToRequestForm();
    }
}

/**
 * Reset to request form
 */
function resetToRequestForm() {
    document.getElementById('requestForm').style.display = 'block';
    document.getElementById('rideStatus').style.display = 'none';
    document.getElementById('rideComplete').style.display = 'none';
    document.getElementById('driverInfo').style.display = 'none';
    document.getElementById('destinationInput').value = '';
    document.getElementById('requestBtn').disabled = false;
    document.getElementById('requestBtn').textContent = '🚲 Find a Bike';
    document.getElementById('fareEstimate').style.display = 'none';
    
    currentRideId = null;
    currentDriverId = null;
    driverMarker.setOpacity(0);
    
    if (locationUpdateInterval) {
        clearInterval(locationUpdateInterval);
        locationUpdateInterval = null;
    }
}

/**
 * Reset app for new ride
 */
function resetApp() {
    resetToRequestForm();
    document.getElementById('destinationInput').value = '';
}

/**
 * Start ETA calculation for driver arrival
 */
function startETACalculation() {
    if (locationUpdateInterval) {
        clearInterval(locationUpdateInterval);
    }
    
    locationUpdateInterval = setInterval(() => {
        if (currentDriverId && currentLocation && ws && ws.readyState === WebSocket.OPEN) {
            // Request driver location update
            ws.send(JSON.stringify({
                type: 'track_driver',
                ride_id: currentRideId
            }));
        }
    }, 5000); // Every 5 seconds
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

/**
 * Calculate distance between two coordinates (Haversine formula)
 */
function calculateDistance(lat1, lng1, lat2, lng2) {
    const R = 6371; // Earth's radius in km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLng/2) * Math.sin(dLng/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
}

/**
 * Show notification
 */
function showNotification(message, type = 'info') {
    // Remove existing notification
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = 'notification';
    
    // Set color based on type
    let bgColor = '#333';
    if (type === 'success') bgColor = '#4CAF50';
    if (type === 'error') bgColor = '#f44336';
    if (type === 'warning') bgColor = '#ff9800';
    if (type === 'info') bgColor = '#2196F3';
    
    notification.style.backgroundColor = bgColor;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

/**
 * Save ride to local storage history
 */
function saveToHistory(ride) {
    let history = localStorage.getItem('rideHistory');
    history = history ? JSON.parse(history) : [];
    history.unshift(ride); // Add to beginning
    history = history.slice(0, 20); // Keep last 20 rides
    localStorage.setItem('rideHistory', JSON.stringify(history));
}

/**
 * Load ride history
 */
function loadHistory() {
    const history = localStorage.getItem('rideHistory');
    if (history) {
        const rides = JSON.parse(history);
        console.log(`📜 Loaded ${rides.length} past rides`);
        return rides;
    }
    return [];
}

// ============================================
// CLEANUP
// ============================================

/**
 * Clean up on page unload
 */
window.onbeforeunload = () => {
    if (watchId) {
        navigator.geolocation.clearWatch(watchId);
    }
    if (locationUpdateInterval) {
        clearInterval(locationUpdateInterval);
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
    }
};

console.log('Customer App JS loaded');

// ============ RIDE HISTORY FUNCTIONS ============

// Save ride to history
function saveToHistory(ride) {
    let history = localStorage.getItem('rideHistory');
    history = history ? JSON.parse(history) : [];
    
    history.unshift({
        id: Date.now(),
        date: new Date().toLocaleString(),
        destination: ride.destination,
        fare: ride.fare,
        distance: ride.distance || '?',
        status: 'Completed'
    });
    
    // Keep last 50 rides
    history = history.slice(0, 50);
    localStorage.setItem('rideHistory', JSON.stringify(history));
    
    console.log('✅ Ride saved to history');
}

// Show history modal
function showHistory() {
    const history = JSON.parse(localStorage.getItem('rideHistory') || '[]');
    const historyList = document.getElementById('historyList');
    
    if (history.length === 0) {
        historyList.innerHTML = '<div style="text-align:center; padding:40px; color:#999;">No rides yet. Take your first ride!</div>';
    } else {
        historyList.innerHTML = history.map(ride => `
            <div style="background:#f5f5f5; padding:15px; margin-bottom:10px; border-radius:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-weight:bold;">📍 ${ride.destination}</div>
                        <div style="font-size:12px; color:#666;">${ride.date}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-weight:bold; color:#4CAF50;">₱${ride.fare}</div>
                        <div style="font-size:11px; color:#999;">${ride.distance}km</div>
                    </div>
                </div>
            </div>
        `).join('');
    }
    
    document.getElementById('historyModal').style.display = 'block';
}

// Close history modal
function closeHistory() {
    document.getElementById('historyModal').style.display = 'none';
}

// Update the ride_completed handler to save history
// Find this section in handleServerMessage and add the saveToHistory line:
case 'ride_completed':
    console.log('Ride completed:', data);
    showStatus(`✅ Ride complete! Total: ₱${data.fare}`, 'success');
    
    // Save to history
    saveToHistory({
        destination: document.getElementById('destinationInput').value,
        fare: data.fare,
        distance: currentDistance ? currentDistance.toFixed(1) : '?'
    });
    
    // ★ SHOW RATING MODAL - ADD THIS ★
    // Get the driver ID from current ride
    if (currentRideId) {
        console.log('Showing rating modal for ride:', currentRideId);
        // Small delay to let the ride complete UI settle
        setTimeout(() => {
            showRatingModal(currentRideId, currentDriverId || 'unknown');
        }, 1000);
    }
    
    currentRideId = null;
    currentDriverId = null;
    driverMarker.setOpacity(0);
    document.getElementById('requestBtn').style.display = 'block';
    document.getElementById('cancelBtn').style.display = 'none';
    document.getElementById('requestBtn').disabled = false;
    document.getElementById('requestBtn').textContent = '🚲 Find a Bike';
    break;
// ============ RATING SYSTEM ============
let currentRating = 0;
let currentRideForRating = null;

function showRatingModal(rideId) {
    currentRideForRating = rideId;
    currentRating = 0;
    updateStarDisplay();
    document.getElementById('ratingModal').style.display = 'flex';
}

function updateStarDisplay() {
    const stars = '★'.repeat(currentRating) + '☆'.repeat(5 - currentRating);
    document.getElementById('starRating').innerHTML = stars;
}

// Setup star click handler (add this to your init function)
function setupStarRating() {
    const starDiv = document.getElementById('starRating');
    if (starDiv) {
        starDiv.onclick = (e) => {
            const rect = starDiv.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const starWidth = rect.width / 5;
            currentRating = Math.floor(x / starWidth) + 1;
            updateStarDisplay();
        };
    }
}

function submitRating() {
    const comment = document.getElementById('ratingComment').value;
    
    if (ws && ws.readyState === WebSocket.OPEN && currentRideForRating) {
        ws.send(JSON.stringify({
            type: 'submit_rating',
            ride_id: currentRideForRating,
            rating: currentRating,
            comment: comment
        }));
    }
    
    showNotification(`Thanks for rating ${currentRating} stars! ⭐`, 'success');
    closeRatingModal();
}

function closeRatingModal() {
    document.getElementById('ratingModal').style.display = 'none';
    document.getElementById('ratingComment').value = '';
}

// Call this when ride completes - add to ride_completed handler:
// showRatingModal(currentRideId);