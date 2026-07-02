from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# 🔑 ضع مفتاحك هنا - تأكد إنه سطر واحد فقط
API_KEY = "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"

client = OpenAI(api_key=API_KEY)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": user_message}],
            max_tokens=500
        )
        
        return jsonify({"reply": response.choices[0].message.content})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return "✅ Tadawul AI Server is running!"

if __name__ == "__main__":
    print("🚀 Server running on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)