import logging
from flask import Flask, request, jsonify
from binance_rest import BinanceRESTClient, BinanceWebSocket
from utils import parse_webhook_to_payload

# Initialize the Flask app
app = Flask(__name__)

# Set up logging for the application
logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

# Initialize Binance REST and WebSocket Client
rest_client = BinanceRESTClient()
ws_client = BinanceWebSocket(rest_client)

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Handle incoming TradingView webhook and place orders.
    """
    try:
        logger.info("Received webhook.")
        data = request.get_json()
        logger.debug(f"Webhook payload received: {data}")

        # Convert webhook data to the payload format expected by the Binance client
        payload = parse_webhook_to_payload(data)
        logger.info(f"Parsed payload: {payload}")

        # Place the order using Binance REST Client
        response = rest_client.place_market_order(
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=payload["quantity"],
            leverage=payload["leverage"],
            take_profit_percent=payload.get("take_profit")
        )
        logger.info(f"Order response: {response}")

        # Return the Binance order response as JSON
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"message": str(e), "status": "error"}), 500


if __name__ == "__main__":
    try:
        # Initialize the WebSocket connection before starting the Flask app
        logger.info("Starting WebSocket connection...")
        ws_client.start()
    except Exception as e:
        logger.error(f"Failed to start WebSocket: {e}", exc_info=True)

    # Start the Flask app
    app.run(debug=True, host="0.0.0.0", port=8080)
