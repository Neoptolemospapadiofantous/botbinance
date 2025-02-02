import logging
from flask import Flask, request, jsonify
from binance_rest import BinanceRESTClient
from binance_websocket import BinanceWebSocket
from utils import parse_webhook_to_payload
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Convert environment to float with a default
DEFAULT_STOP_LOSS_PERCENT = float(os.getenv("DEFAULT_STOP_LOSS_PERCENT", "1.0"))
DEFAULT_TAKE_PROFIT_PERCENT = float(os.getenv("DEFAULT_TAKE_PROFIT_PERCENT", "0.5"))

app = Flask(__name__)

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

rest_client = BinanceRESTClient()
ws_client = BinanceWebSocket(rest_client)

# Global dictionary for last signal
last_signal = {}

def process_buy_sell_signal(payload):
    symbol = payload["symbol"]
    side = payload["side"].upper()  # "BUY" or "SELL"
    quantity = payload["quantity"]

    # 1) Place the market order
    response = rest_client.place_market_order(symbol=symbol, side=side, quantity=quantity)
    last_signal[symbol] = {"payload": payload, "order_response": response}

    # 2) Calculate average fill price
    avg_price = float(response.get("avgPrice", 0))
    if avg_price == 0:
        avg_price = rest_client.get_last_price(symbol)

    # 3) Retrieve SL/TP from payload or .env
    sl_percent = float(payload.get("stop_loss", DEFAULT_STOP_LOSS_PERCENT))
    tp_percent = float(payload.get("take_profit", DEFAULT_TAKE_PROFIT_PERCENT))

    if avg_price > 0:
        # Stop-loss
        try:
            if side == "BUY":
                sl_side = "SELL"
                sl_price = avg_price * (1 - sl_percent / 100.0)
            else:
                sl_side = "BUY"
                sl_price = avg_price * (1 + sl_percent / 100.0)
            rest_client.place_stop_loss_order(symbol, sl_side, quantity, sl_price)
            logger.info(f"[{symbol}] Stop-loss placed at {sl_price:.6f}")
        except Exception as e:
            logger.error(f"[{symbol}] Error placing stop-loss: {e}", exc_info=True)

        # Take-profit
        try:
            if side == "BUY":
                tp_side = "SELL"
                tp_price = avg_price * (1 + tp_percent / 100.0)
            else:
                tp_side = "BUY"
                tp_price = avg_price * (1 - tp_percent / 100.0)
            rest_client.place_take_profit_order(symbol, tp_side, quantity, tp_price)
            logger.info(f"[{symbol}] Take-profit placed at {tp_price:.6f}")
        except Exception as e:
            logger.error(f"[{symbol}] Error placing take-profit: {e}", exc_info=True)

    return response

def process_exit_signal(payload):
    symbol = payload["symbol"]
    current_ts = float(payload["timestamp"])

    if symbol in last_signal:
        stored = last_signal[symbol]
        prev_ts = float(stored["payload"]["timestamp"])
        diff = current_ts - prev_ts

        if diff < 2:
            # (A) Instant EXIT => DO NOT close. Instead enable trailing logic
            ws_client.trailing_stop_enabled[symbol] = True
            logger.info(f"[{symbol}] Instant EXIT (<2s). We do NOT close; we enable trailing_stop_enabled.")
            response = {"message": f"Trailing stop logic enabled for {symbol}", "status": "trailing_pending"}

        else:
            # (B) Normal EXIT => close position
            rest_client.cancel_all_orders(symbol)
            response = rest_client.close_position(symbol)
            logger.info(f"[{symbol}] EXIT; position closed normally (diff={diff:.2f}s).")

        # Remove the stored signal so we can't do "instant exit" again
        del last_signal[symbol]
    else:
        # If we have no record => just close
        response = rest_client.close_position(symbol)

    return response



@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        logger.info("Webhook received.")
        data = request.get_json()
        logger.debug(f"Webhook payload: {data}")

        payload = parse_webhook_to_payload(data)
        logger.info(f"Parsed payload: {payload}")

        ttype = payload["trade_type"]
        if ttype in ("BUY", "SELL"):
            resp_out = process_buy_sell_signal(payload)
        elif ttype == "EXIT":
            resp_out = process_exit_signal(payload)
        else:
            raise ValueError(f"Unknown trade type: {ttype}")

        logger.info(f"Response: {resp_out}")
        return jsonify(resp_out)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"message": str(e), "status": "error"}), 500

if __name__ == "__main__":
    try:
        logger.info("Starting WebSocket connection...")
        ws_client.start()
    except Exception as e:
        logger.error(f"WebSocket failed to start: {e}", exc_info=True)

    app.run(
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("FLASK_PORT", 8080))
    )
