"""
Production Configuration
"""

import os

# Database - use SQLite file (will work on Render)
DATABASE_PATH = os.getenv('DATABASE_PATH', 'boda_system.db')

# CORS - allow your Netlify URLs
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5500",
    "https://*.netlify.app",
    "https://*.onrender.com"
]

# Production settings
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'