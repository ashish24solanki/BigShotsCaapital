from flask import Flask, request
import os

app = Flask(__name__)

# CHANGE THIS — must match your bot's SECRET_KEY
SECRET_KEY = "BigShotsCapital_06"

# CHANGE THIS — path where auto_login.py writes the token
ACCESS_TOKEN_PATH = "/root/access_token.txt"


@app.route("/token", methods=["GET"])
def get_token():
    try:
        # Validate secret key
        key = request.args.get("key")
        if key != SECRET_KEY:
            return "Unauthorized", 403

        # Read token file
        if not os.path.exists(ACCESS_TOKEN_PATH):
            return "Token file not found", 404

        with open(ACCESS_TOKEN_PATH, "r") as f:
            token = f.read().strip()

        if not token:
            return "Token file empty", 500

        return token, 200

    except Exception as e:
        return str(e), 500


if __name__ == "__main__":
    print("🚀 Token server running on http://0.0.0.0:5000/token")
    print("➡ Example: http://your-server-ip:5000/token?key=BigShotsCapital_06")
    app.run(host="0.0.0.0", port=5000, threaded=True)
