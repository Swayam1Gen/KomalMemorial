import logging
import re
from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo.errors import DuplicateKeyError
from datetime import datetime

# --- 1. LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- 2. RATE LIMITER SETUP ---
# Uses the user's IP address to track limits
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# --- DATABASE CONFIGURATION ---
app.config["MONGO_URI"] = "mongodb+srv://swayam_db_user:VWPgvIZjjNUKQ0mo@komalmemorial.uem6jht.mongodb.net/komal_memorial?retryWrites=true&w=majority"
mongo = PyMongo(app)

# --- 3. DATABASE INDEX SETUP ---
# We create indexes on startup to ensure DB-level uniqueness (prevents race conditions)
def create_indexes():
    try:
        # Create unique index for email
        mongo.db.volunteers.create_index("email", unique=True)
        # Create unique index for phone
        mongo.db.volunteers.create_index("phone", unique=True)
        logger.info("Database indexes created/verified successfully.")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")

# Run index creation inside app context
with app.app_context():
    create_indexes()

# --- VALIDATION HELPERS ---
def is_valid_email(email):
    # Standard regex for email validation
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_phone(phone):
    # Check if digits only and length is 10 or 12 (e.g., 919876543210)
    return phone.isdigit() and len(phone) in [10, 12]

# --- ROUTES ---

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for monitoring."""
    return jsonify({"success": True, "message": "System Operational", "data": {"status": "OK"}}), 200

@app.route('/api/register-volunteer', methods=['POST'])
@limiter.limit("5 per minute")  # Rate limit specific to this route
def register_volunteer():
    try:
        data = request.json
        
        # 1. Basic Field Check
        if not data or not all(k in data for k in ('name', 'email', 'phone')):
            return jsonify({
                "success": False, 
                "message": "Missing required fields (name, email, phone)",
                "data": {}
            }), 400

        # 2. Input Validation
        if not is_valid_email(data['email']):
            return jsonify({
                "success": False, 
                "message": "Invalid email format",
                "data": {}
            }), 400

        if not is_valid_phone(data['phone']):
            return jsonify({
                "success": False, 
                "message": "Invalid phone number (must be 10 or 12 digits)",
                "data": {}
            }), 400

        volunteer_record = {
            "name": data['name'],
            "email": data['email'],
            "phone": data['phone'],
            "message": data.get('message', ''),
            "registered_at": datetime.utcnow()
        }
        
        # 3. Database Insertion with Duplicate Handling
        mongo.db.volunteers.insert_one(volunteer_record)
        
        # We don't return the full object ID to frontend usually, just success
        return jsonify({
            "success": True, 
            "message": "Volunteer registered successfully!",
            "data": {"email": data['email']}
        }), 201

    except DuplicateKeyError:
        # This catches the Unique Index violation safely
        return jsonify({
            "success": False, 
            "message": "Email or phone already registered.",
            "data": {}
        }), 409

    except Exception as e:
        logger.error(f"Server Error in register_volunteer: {e}")
        return jsonify({
            "success": False, 
            "message": "Internal Server Error",
            "data": {}
        }), 500

@app.route('/api/volunteers', methods=['GET'])
def get_volunteers():
    try:
        # 1. Pagination Parameters
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit

        # 2. Query with Sort, Skip, Limit
        cursor = mongo.db.volunteers.find().sort("registered_at", -1).skip(skip).limit(limit)
        
        # Get total count for frontend pagination logic
        total_volunteers = mongo.db.volunteers.count_documents({})

        volunteers_list = []
        for v in cursor:
            volunteers_list.append({
                "name": v['name'],
                "email": v['email'],
                "phone": v['phone'],
                "message": v.get('message', 'N/A'),
                "date": v['registered_at'].strftime("%Y-%m-%d %H:%M:%S")
            })

        return jsonify({
            "success": True,
            "message": "Volunteers fetched successfully",
            "data": {
                "volunteers": volunteers_list,
                "pagination": {
                    "current_page": page,
                    "limit": limit,
                    "total_records": total_volunteers
                }
            }
        }), 200

    except Exception as e:
        logger.error(f"Error fetching volunteers: {e}")
        return jsonify({
            "success": False, 
            "message": "Failed to fetch data", 
            "data": {}
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
