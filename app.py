import logging
from flask import Flask, request, jsonify
from binance_rest import BinanceRESTClient
from binance_websocket import BinanceWebSocket
from utils import parse_webhook_to_payload
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Set trailing stop percent from environment (e.g., 0.2 means 0.2%)
TRAILING_STOP_PERCENT = float(os.getenv("TRAILING_STOP_PERCENT", "0.2"))

app = Flask(__name__)

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

rest_client = BinanceRESTClient()
ws_client = BinanceWebSocket(rest_client)

# Global dictionary to track the last BUY/SELL signal payload per symbol.
last_signal = {}

def process_buy_sell_signal(payload):
    symbol = payload["symbol"]
    # Place the market order (TP orders are handled separately)
    response = rest_client.place_market_order(
        symbol=symbol,
        side=payload["side"],
        quantity=payload["quantity"],
        leverage=payload["leverage"]
    )
    # Store both the payload and the market order response for later use.
    last_signal[symbol] = {"payload": payload, "order_response": response}
    
    # If a take profit percentage is provided, place a TP order.
    tp_percent = payload.get("take_profit")
    if tp_percent:
        try:
            avg_price = float(response.get("avgPrice", 0))
            if avg_price == 0:
                avg_price = rest_client.get_last_price(symbol)
            if avg_price != 0:
                if payload["side"] == "BUY":
                    tp_side = "SELL"
                    tp_price = avg_price * (1 + float(tp_percent) / 100)
                else:
                    tp_side = "BUY"
                    tp_price = avg_price * (1 - float(tp_percent) / 100)
                rest_client.place_take_profit_order(symbol, tp_side, payload["quantity"], tp_price)
                logger.info(f"Take profit order placed for {symbol} at {tp_price:.2f}")
        except Exception as e:
            logger.error(f"Error placing take profit order for {symbol}: {e}", exc_info=True)
    return response

def process_exit_signal(payload):
    symbol = payload["symbol"]
    current_ts = float(payload["timestamp"])
    if symbol in last_signal:
        stored = last_signal[symbol]
        prev_payload = stored["payload"]
        prev_ts = float(prev_payload["timestamp"])
        diff = current_ts - prev_ts

        if diff < 3:
            # Instant EXIT: enable trailing stop loss.
            ws_client.trailing_stop_enabled[symbol] = True
            order_resp = stored.get("order_response", {})
            avg_price = float(order_resp.get("avgPrice", 0))
            if avg_price == 0:
                avg_price = rest_client.get_last_price(symbol)
            if avg_price > 0:
                ws_client.best_price[symbol] = avg_price
                logger.info(f"Setting best price for {symbol} to {avg_price:.2f}.")
            trailing_stop_percent = TRAILING_STOP_PERCENT
            quantity = stored["payload"]["quantity"]
            # If no active SL order exists for this symbol, update trailing stop.
            if symbol not in ws_client.sl_tracker:
                ws_client.update_trailing_stop(symbol, ws_client.best_price[symbol], trailing_stop_percent, quantity)
            logger.info(f"Instant EXIT signal (diff={diff:.2f} sec) for {symbol}; trailing stop enabled.")
            response = {"message": f"Trailing stop enabled for {symbol}", "status": "trailing_enabled"}
        else:
            # Normal EXIT: cancel all active orders and close the position.
            rest_client.cancel_all_orders(symbol)
            response = rest_client.close_position(symbol)
            logger.info(f"Normal EXIT signal for {symbol}; position closed.")
        del last_signal[symbol]
    else:
        response = rest_client.close_position(symbol)
    return response

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Process incoming TradingView webhooks.
    
    Expected payload example:
      {
        "value": "Order BUY @ 24.379 filled on LINKUSDT\nNew strategy position is 1",
        "trade_info": {
            "ticker": "LINKUSDT",
            "contracts": "1",
            "leverage": "10",
            "take_profit": "0.5"
        },
        "timestamp": "1681253674.000"
      }
    
    Behavior:
      - BUY/SELL signals: Place a market order with TP and store the signal.
      - EXIT signals:
          * If the EXIT signal occurs within 3 seconds of the stored signal, enable trailing stop loss.
          * Otherwise, cancel any active orders and close the position.
    """
    try:
        logger.info("Webhook received.")
        data = request.get_json()
        logger.debug(f"Webhook payload received: {data}")

        payload = parse_webhook_to_payload(data)
        logger.info(f"Parsed payload: {payload}")

        trade_type = payload["trade_type"]

        if trade_type in ("BUY", "SELL"):
            response_out = process_buy_sell_signal(payload)
        elif trade_type == "EXIT":
            response_out = process_exit_signal(payload)
        else:
            raise ValueError(f"Unknown trade type: {trade_type}")

        logger.info(f"Order response: {response_out}")
        return jsonify(response_out)
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
