from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_cors import CORS
from datetime import datetime

# static_folder='.' tells Flask: "Look for HTML/Images in this same folder"
# static_url_path='' tells Flask: "Serve them at the main URL"
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- DATABASE CONFIGURATION ---
# Ensure your MongoDB is running locally on port 27017
app.config["MONGO_URI"] = "mongodb+srv://swayam_db_user:VWPgvIZjjNUKQ0mo@komalmemorial.uem6jht.mongodb.net/komal_memorial?retryWrites=true&w=majority"
mongo = PyMongo(app)

# ---------------------------------------------------------
# VOLUNTEER ROUTES
# ---------------------------------------------------------

@app.route('/api/register-volunteer', methods=['POST'])
def register_volunteer():
    try:
        data = request.json
        # Validate that required fields are present
        if not data or not all(k in data for k in ('name', 'email', 'phone')):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        volunteer_record = {
            "name": data['name'],
            "email": data['email'],
            "phone": data['phone'],
            "message": data.get('message', ''),
            "registered_at": datetime.utcnow()
        }
        
        # Insert into MongoDB
        mongo.db.volunteers.insert_one(volunteer_record)
        return jsonify({"success": True, "message": "Volunteer registered successfully!"}), 201
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/api/volunteers', methods=['GET'])
def get_volunteers():
    try:
        # Fetch all volunteers, sorted by newest first
        volunteers = mongo.db.volunteers.find().sort("registered_at", -1)
        output = []
        for v in volunteers:
            output.append({
                "name": v['name'],
                "email": v['email'],
                "phone": v['phone'],
                "message": v.get('message', 'N/A'),
                "date": v['registered_at'].strftime("%Y-%m-%d %H:%M:%S")
            })
        return jsonify(output), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=5000)


