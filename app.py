from flask import Flask, request, jsonify
import numpy as np
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import os
import logging

app = Flask(__name__)

# Config (desde Environment Variable)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = "-1003300471808"

# Logging
logging.basicConfig(level=logging.INFO)

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "VADERBOOT-IA 24/7 LIVE ✅",
        "webhook": "/webhook",
        "timestamp": datetime.now().isoformat()
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logging.info(f"Webhook recibido: {data}")
        
        ticker = data.get('ticker', 'UNKNOWN')
        action = data.get('action', 'buy')
        close_price = float(data.get('close', 0))
        
        # ANÁLISIS TÉCNICO (plots Pine v6)
        plot_0 = float(data.get('plot_0', 50))  # RSI
        plot_1 = float(data.get('plot_1', 0))   # MACD
        plot_2 = float(data.get('plot_2', 1.0)) # RVOL
        
        # ML SIMPLIFICADO (sin XGBoost por ahora)
        technical_score = min(1.0, (plot_0/70 + plot_2/1.5 + (1 if plot_1>0 else 0))/3)
        ml_prob = 0.5 + technical_score * 0.3  # 50-80%
        
        # FUNDAMENTAL
        fund = fundamental_analysis(ticker)
        
        # CUANTITATIVO
        quant = quant_analysis(ml_prob)
        
        # TELEGRAM
        msg = build_telegram_msg(ticker, action, close_price, ml_prob, fund, quant)
        send_telegram(msg)
        
        logging.info(f"Señal procesada: {ticker} {ml_prob:.1%}")
        
        return jsonify({
            "status": "processed", 
            "ticker": ticker,
            "ml_prob": ml_prob,
            "fundamental": fund['fundamental_score']
        })
        
    except Exception as e:
        logging.error(f"Error webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
            'pe_ratio': round(pe, 1) if pe != 999 else 'N/A',
            'roe': f"{roe:.1%}" if roe else 'N/A',
            'debt_equity': debt if debt != 999 else 'N/A',
            'fundamental_score': round(score/3, 2)
        }
    except:
        return {'pe_ratio': 'N/A', 'roe': 'N/A', 'fundamental_score': 0}

def quant_analysis(prob, rr=2.8):
    kelly = max(0, (prob * (rr - 1) - (1 - prob)) / (rr - 1))
    return {
        'kelly_pct': round(kelly, 3),
        'position_size': f"{kelly:.1%} capital"
    }

def build_telegram_msg(ticker, action, price, ml_prob, fund, quant):
    stars = "⭐⭐⭐" if ml_prob > 0.65 else "⭐⭐" if ml_prob > 0.55 else "⭐"
    action_emoji = "🟢 COMPRA" if action == 'buy' else "🔴 VENTA"
    
    return f"""🚀 VADERBOOT-IA CLOUD 24/7

📈 {action_emoji} {ticker} @{price}

🧠 ML Técnico: {ml_prob:.1%} {stars}
💰 Fundamental: P/E {fund['pe_ratio']} | ROE {fund['roe']}
📊 Kelly Criterion: {quant['position_size']}

🎯 {action_emoji if ml_prob>0.6 else '🟡 ESPERAR'}"""

def send_telegram(msg):
    if not TELEGRAM_TOKEN:
        logging.warning("No TELEGRAM_TOKEN configurado")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        logging.info(f"Telegram enviado: {response.status_code}")
    except Exception as e:
        logging.error(f"Error Telegram: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
