"""
Simple Flask server to generate LiveKit tokens for web clients
Run this alongside your agent.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from livekit import api
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# LiveKit configuration
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://localhost:7880")

if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
    print("⚠️  WARNING: LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")


@app.route("/api/token", methods=["POST"])
def generate_token():
    """Generate a LiveKit access token for a participant"""
    try:
        data = request.json
        room_name = data.get("room", "resh-thosh-agent")
        participant_identity = data.get("identity", f"user-{os.urandom(4).hex()}")
        participant_name = data.get("name", "Guest")
        
        # Create access token
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.with_identity(participant_identity)
        token.with_name(participant_name)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
        
        # 🔥 FIXED: Use timedelta for TTL (1 hour)
        token.with_ttl(timedelta(hours=1))
        
        jwt_token = token.to_jwt()
        
        print(f"✅ Generated token for {participant_identity} in room {room_name}")
        
        return jsonify({
            "token": jwt_token,
            "url": LIVEKIT_URL,
            "room": room_name,
            "identity": participant_identity
        })
        
    except Exception as e:
        print(f"❌ Token generation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "livekit_url": LIVEKIT_URL})


if __name__ == "__main__":
    print("🚀 Starting LiveKit Token Server...")
    print(f"📍 LiveKit URL: {LIVEKIT_URL}")
    print(f"🔑 API Key: {LIVEKIT_API_KEY[:10]}..." if LIVEKIT_API_KEY else "❌ No API Key")
    print("🌐 Server running on http://localhost:5000")
    
    app.run(host="0.0.0.0", port=5000, debug=True)