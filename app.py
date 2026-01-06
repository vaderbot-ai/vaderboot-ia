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
        
        # VALIDACIÓN DE CAMPOS REQUERIDOS
        required_fields = ['ticker', 'plot_0', 'plot_1', 'plot_2']
        if not all(field in data for field in required_fields):
            return jsonify({
                "status": "error", 
                "message": f"Campos requeridos: {required_fields}"
            }), 400
        
        ticker = data['ticker']
        action = data.get('action', 'buy')
        close_price = float(data.get('close', 0))
        
        # ANÁLISIS TÉCNICO (plots Pine v6)
        plot_0 = float(data['plot_0'])  # RSI
        plot_1 = float(data['plot_1'])  # MACD
        plot_2 = float(data['plot_2'])  # RVOL
        
        # Score técnico
        technical_score = min(1.0, (plot_0/70 + plot_2/1.5 + (1 if plot_1>0 else 0))/3)
        
        # ANÁLISIS FUNDAMENTAL HISTÓRICO (NUEVO)
        fund = fundamental_analysis_historical(ticker)
        
        # SCORE COMBINADO (técnico + fundamental integrados)
        combined_score = (technical_score * 0.7) + (fund['fundamental_score'] * 0.3)
        ml_prob = 0.5 + combined_score * 0.3  # Probabilidad [50%, 80%]
        
        # CUANTITATIVO (Kelly Criterion)
        quant = quant_analysis(ml_prob)
        
        # FILTRO: Rechazar si Kelly < 1%
        if quant['kelly_pct'] < 0.01:
            msg = f"⚠️ {ticker}: Señal rechazada (Kelly={quant['kelly_pct']:.2%}, Prob={ml_prob:.1%})"
            send_telegram(msg)
            logging.warning(f"Señal filtrada por Kelly bajo: {ticker}")
            return jsonify({
                "status": "filtered",
                "reason": "Kelly too low",
                "kelly": quant['kelly_pct'],
                "ml_prob": ml_prob
            })
        
        # DECISIÓN FINAL
        THRESHOLD = 0.60
        should_trade = ml_prob >= THRESHOLD
        
        # TELEGRAM
        msg = build_telegram_msg(ticker, action, close_price, ml_prob, fund, quant, should_trade)
        send_telegram(msg)
        
        logging.info(f"Señal procesada: {ticker} | Prob={ml_prob:.1%} | Kelly={quant['kelly_pct']:.2%} | Decisión={'TRADE' if should_trade else 'SKIP'}")
        
        return jsonify({
            "status": "processed",
            "ticker": ticker,
            "ml_prob": round(ml_prob, 3),
            "technical_score": round(technical_score, 3),
            "fundamental_score": round(fund['fundamental_score'], 3),
            "kelly": round(quant['kelly_pct'], 4),
            "decision": "TRADE" if should_trade else "SKIP"
        })
        
    except Exception as e:
        logging.error(f"Error webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


def fundamental_analysis_historical(ticker):
    """
    Análisis fundamental ROBUSTO con datos históricos de yfinance
    
    Analiza:
    - Crecimiento de ingresos (últimos años disponibles)
    - Tendencia de márgenes (últimos trimestres)
    - Flujo de caja libre histórico
    - Volatilidad histórica de precios
    - Métricas actuales (P/E, ROE, Debt/Equity)
    
    Returns:
        dict con fundamental_score [0, 1] y métricas detalladas
    """
    try:
        stock = yf.Ticker(ticker)
        score = 0
        max_score = 10  # Score máximo posible
        
        # ========== 1. DATOS HISTÓRICOS DE PRECIOS ==========
        try:
            hist_prices = stock.history(period="1y")
            if not hist_prices.empty:
                returns = hist_prices['Close'].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)  # Anualizada
                
                # Scoring: menor volatilidad = mejor para fundamental
                if volatility < 0.20:  # <20% volatilidad anual
                    score += 1
                elif volatility < 0.35:  # <35%
                    score += 0.5
            else:
                volatility = None
        except Exception as e:
            logging.warning(f"{ticker} - Error precios históricos: {e}")
            volatility = None
        
        # ========== 2. CRECIMIENTO DE INGRESOS (HISTÓRICO) ==========
        try:
            financials = stock.financials  # Estados anuales (últimos 4 años)
            revenue_growth = None
            
            if not financials.empty and 'Total Revenue' in financials.index:
                revenues = financials.loc['Total Revenue'].dropna().sort_index()
                
                if len(revenues) >= 2:
                    # CAGR (Compound Annual Growth Rate)
                    years = len(revenues) - 1
                    revenue_growth = (revenues.iloc[-1] / revenues.iloc[0]) ** (1/years) - 1
                    
                    # Scoring
                    if revenue_growth > 0.20:  # >20% CAGR
                        score += 2
                    elif revenue_growth > 0.10:  # >10% CAGR
                        score += 1
                    elif revenue_growth > 0:  # Positivo
                        score += 0.5
        except Exception as e:
            logging.warning(f"{ticker} - Error ingresos históricos: {e}")
            revenue_growth = None
        
        # ========== 3. TENDENCIA DE MÁRGENES (TRIMESTRAL) ==========
        try:
            qtr_financials = stock.quarterly_financials
            margin_trend = None
            
            if not qtr_financials.empty:
                if 'Net Income' in qtr_financials.index and 'Total Revenue' in qtr_financials.index:
                    net_income = qtr_financials.loc['Net Income'].dropna()
                    total_revenue = qtr_financials.loc['Total Revenue'].dropna()
                    
                    # Alinear índices
                    common_dates = net_income.index.intersection(total_revenue.index)
                    if len(common_dates) >= 2:
                        margins = (net_income[common_dates] / total_revenue[common_dates]).sort_index()
                        margin_trend = margins.iloc[-1] - margins.iloc[0]  # Cambio en margen
                        
                        # Scoring
                        if margin_trend > 0.05:  # Márgenes mejorando >5%
                            score += 2
                        elif margin_trend > 0:  # Mejorando
                            score += 1
        except Exception as e:
            logging.warning(f"{ticker} - Error márgenes: {e}")
            margin_trend = None
        
        # ========== 4. FLUJO DE CAJA LIBRE (HISTÓRICO) ==========
        try:
            cashflow = stock.cashflow
            fcf_growth = None
            
            if not cashflow.empty and 'Free Cash Flow' in cashflow.index:
                fcf = cashflow.loc['Free Cash Flow'].dropna().sort_index()
                
                if len(fcf) >= 2:
                    # Crecimiento FCF
                    years = len(fcf) - 1
                    fcf_growth = (fcf.iloc[-1] / fcf.iloc[0]) ** (1/years) - 1
                    
                    # Scoring
                    if fcf_growth > 0.15:  # >15% crecimiento
                        score += 2
                    elif fcf_growth > 0:  # Positivo
                        score += 1
        except Exception as e:
            logging.warning(f"{ticker} - Error cash flow: {e}")
            fcf_growth = None
        
        # ========== 5. MÉTRICAS ACTUALES (SNAPSHOT) ==========
        try:
            info = stock.info
            
            # P/E Ratio
            pe = info.get('forwardPE', info.get('trailingPE', 999))
            if pe < 15:
                score += 2
            elif pe < 25:
                score += 1
            
            # ROE (Return on Equity)
            roe = info.get('returnOnEquity', 0)
            if roe > 0.20:  # >20%
                score += 1
            elif roe > 0.15:  # >15%
                score += 0.5
            
            # Debt to Equity
            debt = info.get('debtToEquity', 999)
            if debt < 50:  # Deuda baja
                score += 1
            elif debt < 100:
                score += 0.5
        except Exception as e:
            logging.warning(f"{ticker} - Error métricas actuales: {e}")
            pe = 999
            roe = 0
            debt = 999
        
        # ========== NORMALIZACIÓN DEL SCORE ==========
        fundamental_score = min(1.0, score / max_score)
        
        return {
            'fundamental_score': round(fundamental_score, 3),
            'revenue_growth_cagr': f"{revenue_growth:.1%}" if revenue_growth is not None else 'N/A',
            'margin_trend': f"{margin_trend:.2%}" if margin_trend is not None else 'N/A',
            'fcf_growth': f"{fcf_growth:.1%}" if fcf_growth is not None else 'N/A',
            'volatility': f"{volatility:.1%}" if volatility is not None else 'N/A',
            'pe_ratio': round(pe, 1) if pe != 999 else 'N/A',
            'roe': f"{roe:.1%}" if roe else 'N/A',
            'debt_equity': round(debt, 1) if debt != 999 else 'N/A'
        }
        
    except Exception as e:
        logging.error(f"{ticker} - Error fundamental_analysis: {e}", exc_info=True)
        # Retornar valores por defecto en caso de error total
        return {
            'fundamental_score': 0,
            'revenue_growth_cagr': 'N/A',
            'margin_trend': 'N/A',
            'fcf_growth': 'N/A',
            'volatility': 'N/A',
            'pe_ratio': 'N/A',
            'roe': 'N/A',
            'debt_equity': 'N/A'
        }


def quant_analysis(prob, rr=2.8):
    """
    Kelly Criterion para gestión de capital
    
    Args:
        prob: Probabilidad de éxito [0, 1]
        rr: Risk/Reward ratio (default 2.8:1)
    
    Returns:
        dict con kelly_pct y position_size
    """
    kelly = max(0, (prob * (rr + 1) - 1) / rr)
    return {
        'kelly_pct': round(kelly, 4),
        'position_size': f"{kelly:.1%} capital"
    }


def build_telegram_msg(ticker, action, price, ml_prob, fund, quant, should_trade):
    """
    Construye mensaje enriquecido para Telegram
    """
    THRESHOLD = 0.60
    stars = "⭐⭐⭐" if ml_prob >= THRESHOLD + 0.10 else "⭐⭐" if ml_prob >= THRESHOLD else "⭐"
    
    action_emoji = "🟢 COMPRA" if action == 'buy' else "🔴 VENTA"
    decision = f"{action_emoji}" if should_trade else "🟡 ESPERAR"
    
    return f"""🚀 VADERBOOT-IA CLOUD 24/7

📈 {action_emoji} {ticker} @${price}

🧠 Score Combinado: {ml_prob:.1%} {stars}
📊 Técnico: 70% | Fundamental: 30%

💰 FUNDAMENTAL HISTÓRICO:
├─ Revenue Growth: {fund['revenue_growth_cagr']}
├─ Margin Trend: {fund['margin_trend']}
├─ FCF Growth: {fund['fcf_growth']}
├─ Volatility: {fund['volatility']}
└─ P/E: {fund['pe_ratio']} | ROE: {fund['roe']}

📐 KELLY CRITERION:
└─ Position Size: {quant['position_size']}

🎯 DECISIÓN: {decision}
{"⚠️ Validar antes de operar" if ml_prob < 0.65 else "✅ Alta confianza"}"""


def send_telegram(msg):
    """Envía mensaje a Telegram con manejo de errores"""
    if not TELEGRAM_TOKEN:
        logging.warning("No TELEGRAM_TOKEN configurado")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        if response.status_code == 200:
            logging.info(f"Telegram enviado exitosamente")
        else:
            logging.error(f"Telegram error: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Error Telegram: {str(e)}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

