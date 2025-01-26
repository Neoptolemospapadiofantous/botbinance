import logging
from flask import Flask, request, jsonify
from binance_rest import BinanceRESTClient
from binance_websocket import BinanceWebSocket
from utils import parse_webhook_to_payload
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

# Initialize Binance REST and WebSocket clients
rest_client = BinanceRESTClient()
ws_client = BinanceWebSocket(rest_client)

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Handle incoming TradingView webhook and process orders based on the signal.
    
    Example:
    {
      "value": "Order BUY @ 24.379 filled on LINKUSDT\nNew strategy position is 1",
      "trade_info": {
        "ticker": "LINKUSDT",
        "contracts": "1",
        "leverage": "10",
        "take_profit": "0.5"
      }
    }
    """
    try:
        logger.info("Webhook received.")
        data = request.get_json()
        logger.debug(f"Webhook payload received: {data}")

        # Parse the payload into a consistent dict
        payload = parse_webhook_to_payload(data)
        logger.info(f"Parsed payload: {payload}")

        # Check what type of trade it is (BUY, SELL, or EXIT)
        trade_type = payload["trade_type"]

        if trade_type == "EXIT":
            logger.info(f"Exit signal received for {payload['symbol']}.")
            response = rest_client.close_position(payload["symbol"])
        elif trade_type == "SELL":
            logger.info(f"Sell signal received for {payload['symbol']}.")
            response = rest_client.place_market_order(
                symbol=payload["symbol"],
                side="SELL",
                quantity=payload["quantity"],
                leverage=payload["leverage"],
                take_profit_percent=payload.get("take_profit")
            )
        elif trade_type == "BUY":
            logger.info(f"Buy signal received for {payload['symbol']}.")
            response = rest_client.place_market_order(
                symbol=payload["symbol"],
                side="BUY",
                quantity=payload["quantity"],
                leverage=payload["leverage"],
                take_profit_percent=payload.get("take_profit")
            )
        else:
            raise ValueError(f"Unknown trade type: {trade_type}")

        logger.info(f"Order response: {response}")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"message": str(e), "status": "error"}), 500


if __name__ == "__main__":
    try:
        logger.info("Starting WebSocket connection...")
        ws_client.start()
    except Exception as e:
        logger.error(f"WebSocket failed to start: {e}", exc_info=True)

    # Run Flask app
    app.run(
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("FLASK_PORT", 8080))
    )
