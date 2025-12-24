import logging
import re
import os
import csv
import io
import jwt
import datetime
from functools import wraps
from flask import Flask, request, jsonify, Response
from flask_pymongo import PyMongo
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "default_fallback_key")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise ValueError("No MONGO_URI found in environment variables.")
if not ADMIN_PASSWORD:
    raise ValueError("No ADMIN_PASSWORD found in environment variables.")

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
# Increase max content length for image uploads (e.g., 5MB)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 
CORS(app)

# --- RATE LIMITER ---
limiter = Limiter(get_remote_address, app=app, default_limits=["500 per day", "100 per hour"])

# --- DATABASE ---
app.config["MONGO_URI"] = MONGO_URI
mongo = PyMongo(app)

# Ensure Indexes
with app.app_context():
    try:
        mongo.db.volunteers.create_index("email", unique=True)
        mongo.db.volunteers.create_index("phone", unique=True)
        mongo.db.volunteers.create_index("registered_at")
        mongo.db.news.create_index("date")
    except Exception as e:
        logger.error(f"Index creation error: {e}")

# --- SECURITY DECORATOR ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({"message": "Token is missing!"}), 401

        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired!"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token!"}), 401
        
        return f(*args, **kwargs)
    return decorated

# --- AUDIT LOG HELPER ---
def log_audit(action, details=""):
    try:
        mongo.db.audit_logs.insert_one({
            "action": action,
            "details": details,
            "admin": ADMIN_USERNAME,
            "timestamp": datetime.datetime.utcnow()
        })
    except Exception as e:
        logger.error(f"Audit log failed: {e}")

# --- EXISTING ROUTES ---

@app.route('/api/admin/login', methods=['POST'])
@limiter.limit("5 per minute") 
def admin_login():
    data = request.json
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    if data['username'] == ADMIN_USERNAME and data['password'] == ADMIN_PASSWORD:
        token = jwt.encode({
            'user': ADMIN_USERNAME,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=2)
        }, SECRET_KEY, algorithm="HS256")
        
        log_audit("LOGIN", "Admin logged in successfully")
        return jsonify({"success": True, "token": token}), 200
    
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/admin/stats', methods=['GET'])
@token_required
def get_stats():
    try:
        now = datetime.datetime.utcnow()
        start_of_day = datetime.datetime(now.year, now.month, now.day)
        
        total = mongo.db.volunteers.count_documents({})
        today_count = mongo.db.volunteers.count_documents({"registered_at": {"$gte": start_of_day}})
        
        return jsonify({"success": True, "data": {"total": total, "today": today_count}}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/volunteers/export', methods=['GET'])
@token_required
def export_volunteers():
    try:
        log_audit("EXPORT_CSV", "Exported volunteer list")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Registered At', 'Name', 'Email', 'Phone', 'Message'])
        volunteers = mongo.db.volunteers.find().sort("registered_at", -1)
        for v in volunteers:
            writer.writerow([
                v['registered_at'].strftime("%Y-%m-%d %H:%M:%S"),
                v['name'],
                v['email'],
                v['phone'],
                v.get('message', '')
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=volunteers_list.csv"}
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/volunteers/<id>', methods=['DELETE'])
@token_required
def delete_volunteer(id):
    try:
        result = mongo.db.volunteers.delete_one({"_id": ObjectId(id)})
        if result.deleted_count == 1:
            log_audit("DELETE_VOLUNTEER", f"Deleted volunteer ID: {id}")
            return jsonify({"success": True, "message": "Volunteer deleted"}), 200
        else:
            return jsonify({"success": False, "message": "Volunteer not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/volunteers', methods=['GET'])
@token_required
def get_volunteers():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        search = request.args.get('search', '')
        skip = (page - 1) * limit

        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"phone": {"$regex": search, "$options": "i"}}
            ]

        cursor = mongo.db.volunteers.find(query).sort("registered_at", -1).skip(skip).limit(limit)
        total_volunteers = mongo.db.volunteers.count_documents(query)

        volunteers_list = []
        for v in cursor:
            volunteers_list.append({
                "id": str(v['_id']),
                "name": v['name'],
                "email": v['email'],
                "phone": v['phone'],
                "message": v.get('message', 'N/A'),
                "date": v['registered_at'].strftime("%Y-%m-%d %H:%M:%S")
            })

        return jsonify({
            "success": True,
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
        logger.error(f"Error: {e}")
        return jsonify({"success": False, "message": "Server Error"}), 500

@app.route('/api/register-volunteer', methods=['POST'])
@limiter.limit("5 per minute")
def register_volunteer():
    try:
        data = request.json
        if not data or not all(k in data for k in ('name', 'email', 'phone')):
            return jsonify({"success": False, "message": "Missing fields"}), 400
            
        mongo.db.volunteers.insert_one({
            "name": data['name'],
            "email": data['email'],
            "phone": data['phone'],
            "message": data.get('message', ''),
            "registered_at": datetime.datetime.utcnow()
        })
        return jsonify({"success": True, "message": "Registered!"}), 201
    except DuplicateKeyError:
        return jsonify({"success": False, "message": "Email/Phone already exists"}), 409
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# --- UPDATED NEWS ROUTES ---

@app.route('/api/news', methods=['GET'])
def get_news():
    """ Public endpoint to get news updates """
    try:
        # Sort by date descending
        cursor = mongo.db.news.find().sort("date", -1)
        news_list = []
        for n in cursor:
            news_list.append({
                "id": str(n['_id']),
                "title": n['title'],
                "content": n['content'],
                "image": n.get('image', None), # Retrieve image
                "date": n['date'].strftime("%B %d, %Y") # Friendly date format
            })
        return jsonify({"success": True, "data": news_list}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/news', methods=['POST'])
@token_required
def add_news():
    """ Admin only: Add a news item with optional image """
    try:
        data = request.json
        if not data or not data.get('title') or not data.get('content'):
            return jsonify({"success": False, "message": "Missing title or content"}), 400

        # Create document
        news_item = {
            "title": data['title'],
            "content": data['content'],
            "date": datetime.datetime.utcnow()
        }
        
        # Add image if present (Base64 string)
        if data.get('image'):
            news_item['image'] = data['image']

        mongo.db.news.insert_one(news_item)
        
        log_audit("ADD_NEWS", f"Added news: {data['title']}")
        return jsonify({"success": True, "message": "News added successfully"}), 201
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/news/<id>', methods=['DELETE'])
@token_required
def delete_news(id):
    try:
        result = mongo.db.news.delete_one({"_id": ObjectId(id)})
        if result.deleted_count == 1:
            log_audit("DELETE_NEWS", f"Deleted news ID: {id}")
            return jsonify({"success": True, "message": "News deleted"}), 200
        else:
            return jsonify({"success": False, "message": "News item not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)