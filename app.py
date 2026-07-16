from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
from openai import OpenAI
import os
import json
import re
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

# ------------------------------------------------------------------
# 1. SECURELY READ OPENAI KEY FROM ENVIRONMENT
# ------------------------------------------------------------------
API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=API_KEY) if API_KEY else None

if not API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY not set. AI features will fallback to rule-based logic.")

# ------------------------------------------------------------------
# 2. SAUDI TICKER MAPPINGS & COMPANY NAMES
# ------------------------------------------------------------------
TICKER_MAPPING = {
    "2222": "2222.SR", "1120": "1120.SR", "2010": "2010.SR",
    "4001": "7010.SR", "1180": "1180.SR", "1010": "1010.SR",
    "1020": "1020.SR", "1080": "1080.SR", "1150": "1150.SR",
    "1211": "1211.SR", "2020": "2020.SR", "2030": "2030.SR",
    "2050": "2050.SR", "3002": "3002.SR", "4002": "4002.SR",
    "4190": "4190.SR", "4200": "4200.SR", "5110": "5110.SR",
}

COMPANY_NAMES = {
    "2222": "Aramco", "1120": "Al Rajhi Bank", "2010": "SABIC",
    "4001": "STC", "1180": "Al Jazirah", "1010": "Riyad Bank",
    "1020": "Al Bilad Bank", "1080": "Arab National Bank", "1150": "Alinma Bank",
    "1211": "Maaden", "2020": "SABIC Agri-Nutrients", "2030": "Saudi Mining Co.",
    "2050": "Savola Group", "3002": "Almarai", "4002": "Mouwasat Medical",
    "4190": "Jarir Marketing", "4200": "Aldrees", "5110": "Saudi Electricity"
}

# ------------------------------------------------------------------
# 3. FETCH REAL-TIME DATA FROM YAHOO FINANCE
# ------------------------------------------------------------------
def get_real_time_data(ticker):
    try:
        yahoo_symbol = TICKER_MAPPING.get(ticker, f"{ticker}.SR")
        stock = yf.Ticker(yahoo_symbol)
        info = stock.info
        price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('bid')
        prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
        if price is None:
            return {'error': f'No price data for {ticker}'}
        change = ((price - prev_close) / prev_close * 100) if prev_close and prev_close != 0 else None
        return {
            'price': round(price, 2),
            'volume': info.get('regularMarketVolume') or info.get('volume'),
            'change': round(change, 2) if change is not None else None
        }
    except Exception as e:
        return {'error': str(e)}

# ------------------------------------------------------------------
# 4. ENDPOINTS
# ------------------------------------------------------------------

# 4a. Stock data
@app.route("/stock/<ticker>", methods=["GET"])
def stock_data(ticker):
    data = get_real_time_data(ticker.upper())
    return jsonify(data)

# 4b. Chat (with budget logic and OpenAI fallback)
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").lower()

    # ---- Budget recommendation logic ----
    budget_keywords = ['budget', 'sar', 'riyal', 'cost', 'price', 'afford']
    if any(kw in user_message for kw in budget_keywords) and ('buy' in user_message or 'recommend' in user_message or 'suggest' in user_message):
        budget_match = re.search(r'(\d+(?:\.\d+)?)', user_message)
        if budget_match:
            budget = float(budget_match.group(1))
            def fetch_one(symbol):
                data = get_real_time_data(symbol)
                if 'error' not in data and data['price']:
                    return {'symbol': symbol, 'price': data['price'], 'change': data['change'] or 0}
                return None
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(fetch_one, TICKER_MAPPING.keys()))
            valid = [r for r in results if r and r['price'] <= budget]
            if not valid:
                min_price = min([r['price'] for r in results if r]) if results else 0
                reply = f"No company in our list is priced at {budget} SAR or less. The cheapest stock is around {min_price:.2f} SAR. Please try a higher budget."
            else:
                valid.sort(key=lambda x: x['change'], reverse=True)
                top = valid[:3]
                reply = f"With a budget of {budget} SAR, here are the best stocks you can buy:\n\n"
                for s in top:
                    name = COMPANY_NAMES.get(s['symbol'], s['symbol'])
                    reply += f"- {name} ({s['symbol']}) - {s['price']:.2f} SAR, daily change {s['change']:+.2f}%\n"
                reply += "\nClick 'Analyze' on any ticker above to get our full AI recommendation."
            return jsonify({"reply": reply})

    # ---- If no OpenAI client, fallback ----
    if client is None:
        reply = "The AI assistant is not available because no OpenAI API key was provided. Please set the OPENAI_API_KEY environment variable to enable full AI responses."
        return jsonify({"reply": reply})

    # ---- Normal OpenAI chat ----
    system_prompt = """You are a friendly Saudi stock market assistant.
    - Always give a clear recommendation: BUY, HOLD, or SELL when asked about a specific stock.
    - If the user mentions a budget, politely explain that you need a specific ticker to analyze.
    - Keep answers short (2-3 sentences) and end with a reason.
    - Never say "I cannot give advice". Be helpful."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=300,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        print("OpenAI error, falling back to rules:", e)
        # Fallback response
        if any(w in user_message for w in ["buy", "sell", "hold"]):
            reply = "To get a BUY/HOLD/SELL recommendation, enter a ticker (e.g., 2222) and click 'Analyze'."
        elif "2222" in user_message or "aramco" in user_message:
            reply = "Aramco (2222) – use the Analyze button to see the current Smart Score."
        else:
            reply = "I'm your Tadawul AI assistant. Enter a ticker above and click Analyze."
        return jsonify({"reply": reply})

# 4c. AI analysis for a specific ticker
@app.route("/analyze/<ticker>", methods=["GET"])
def ai_analysis(ticker):
    data = get_real_time_data(ticker.upper())
    if 'error' in data:
        return jsonify(data)
    price = data['price']
    change = data['change'] or 0
    volume = data['volume'] or 0

    # ---- If no OpenAI client, use rule-based ----
    if client is None:
        pred = "UP" if change > 0.3 else ("DOWN" if change < -0.3 else "NEUTRAL")
        conf = 65 if abs(change) > 0.5 else 50
        return jsonify({
            "prediction": pred,
            "confidence": conf,
            "keyFactors": ["Price momentum", "Volume analysis", "Market sentiment"],
            "bestReason": "Based on current data, the stock shows balanced risk/reward."
        })

    # ---- Use OpenAI for smart analysis ----
    prompt = f"""Stock {ticker} has price {price} SAR, daily change {change}%, volume {volume}.
    Return ONLY a JSON object (no extra text) with these fields:
    {{"prediction":"UP/DOWN/NEUTRAL", "confidence":0-100, "keyFactors":["factor1","factor2","factor3"], "bestReason":"..."}}"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200
        )
        content = resp.choices[0].message.content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            raise ValueError("No JSON")
        return jsonify(result)
    except Exception as e:
        # Fallback to rule-based if OpenAI fails
        pred = "UP" if change > 0.3 else ("DOWN" if change < -0.3 else "NEUTRAL")
        conf = 65 if abs(change) > 0.5 else 50
        return jsonify({
            "prediction": pred,
            "confidence": conf,
            "keyFactors": ["Price momentum", "Volume analysis", "Market sentiment"],
            "bestReason": "Based on current data, the stock shows balanced risk/reward."
        })

# 4d. Root endpoint (health check)
@app.route("/", methods=["GET"])
def home():
    return "Tadawul AI server is running. Use /stock/<ticker>, /chat, and /analyze/<ticker>."

# ------------------------------------------------------------------
# 5. RUN THE APP
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Server running on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)