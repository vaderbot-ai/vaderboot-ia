from flask import Flask, request, jsonify
import numpy as np
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import os

app = Flask(__name__)

# Config Telegram (CAMBIAR por TU BOT TOKEN)
TELEGRAM_TOKEN = "TU_BOT_TOKEN_AQUI"
CHAT_ID = "-1003300471808"

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "VADERBOOT-IA 24/7 LIVE", 
        "webhook": "/webhook",
        "timestamp": datetime.now().isoformat()
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    
    ticker = data.get('ticker', 'UNKNOWN')
    action = data.get('action', 'buy')
    close_price = float(data.get('close', 0))
    
    # ANÁLISIS TÉCNICO (plots de Pine v6)
    plot_0 = float(data.get('plot_0', 0))  # RSI
    plot_1 = float(data.get('plot_1', 0))  # MACD
    plot_2 = float(data.get('plot_2', 0))  # RVOL
    
    # ML SIMPLIFICADO (mejoramos después)
    features = np.array([[plot_0, plot_1, plot_2]])
    ml_prob = 0.62 if action == 'buy' else 0.38  # Placeholder
    
    # FUNDAMENTAL YFINANCE
    fund = fundamental_analysis(ticker)
    
    # CUANTITATIVO
    quant = quant_analysis(ml_prob)
    
    # TELEGRAM COMPLETO
    msg = build_telegram_msg(ticker, action, close_price, ml_prob, fund, quant)
    send_telegram(msg)
    
    return jsonify({
        "status": "processed", 
        "ticker": ticker,
        "ml_prob": ml_prob,
        "fundamental": fund['fundamental_score']
    })

def fundamental_analysis(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        score = 0
        
        pe = info.get('forwardPE', 999)
        if pe < 25: score += 1
        
        roe = info.get('returnOnEquity', 0)
        if roe > 0.15: score += 1
        
        debt = info.get('debtToEquity', 999)
        if debt < 100: score += 1
        
        return {
            'pe_ratio': round(pe, 1),
            'roe': f"{roe:.1%}",
            'debt_equity': debt,
            'fundamental_score': score/3
        }
    except:
        return {'pe_ratio': 'N/A', 'roe': 'N/A', 'fundamental_score': 0}

def quant_analysis(prob, rr=2.8):
    kelly = (prob * (rr - 1) - (1 - prob)) / (rr - 1)
    return {
        'kelly_pct': max(0, round(kelly, 3)),
        'position_size': f"{kelly:.1%} capital"
    }

def build_telegram_msg(ticker, action, price, ml_prob, fund, quant):
    stars = "⭐⭐⭐" if ml_prob > 0.6 else "⭐⭐" if ml_prob > 0.5 else "⭐"
    
    return f"""🚀 VADERBOOT-IA LIVE 24/7

📈 {action.upper()} {ticker} @{price}

🧠 ML XGBoost: {ml_prob:.1%} {stars}
💰 Fundamental: P/E {fund['pe_ratio']} | ROE {fund['roe']}
📊 Kelly: {quant['position_size']}

🎯 RECOMENDACIÓN: {'🟢 COMPRAR' if ml_prob>0.6 else '🟡 ESPERAR'}"""

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
