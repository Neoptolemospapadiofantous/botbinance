import logging
import json
from websocket import WebSocketApp
from threading import Thread
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("binance_ws")
logging.basicConfig(level=logging.INFO)

class BinanceWebSocket:
    """
    Binance WebSocket client to handle user data streams.
    """
    def __init__(self, rest_client):
        self.rest_client = rest_client
        self.listen_key = None
        self.ws = None
        self.ws_thread = None
        self.websocket_url = os.getenv("WEBSOCKET_URL")
        self.tp_tracker = {}  # Track if TP orders are already placed for symbols

    def start(self):
        """
        Start the WebSocket connection.
        """
        try:
            # Fetch listen key
            self.listen_key = self.rest_client.get_listen_key()
            if not self.listen_key:
                logger.error("Failed to get listenKey. WebSocket cannot start.")
                return

            ws_url = f"{self.websocket_url}/{self.listen_key}"
            logger.info(f"Connecting to WebSocket: {ws_url}")

            # Define WebSocket event handlers
            def on_message(ws, message):
                logger.debug(f"WebSocket message received: {message}")
                self.handle_message(json.loads(message))

            def on_open(ws):
                logger.info("WebSocket connection opened.")

            def on_close(ws, close_status_code, close_msg):
                logger.warning(f"WebSocket closed (Code: {close_status_code}, Message: {close_msg}). Reconnecting...")
                self.reconnect()

            def on_error(ws, error):
                logger.error(f"WebSocket error: {error}. Attempting to reconnect...")
                self.reconnect()

            # Initialize WebSocketApp
            self.ws = WebSocketApp(
                ws_url,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error
            )

            # Run WebSocket in a separate thread
            self.ws_thread = Thread(target=self.ws.run_forever, daemon=True)
            self.ws_thread.start()
            logger.info("WebSocket thread started.")

            # Start listen key renewal in a separate thread
            Thread(target=self.renew_listen_key, daemon=True).start()

        except Exception as e:
            logger.error(f"Error starting WebSocket: {e}", exc_info=True)

    def reconnect(self):
        """
        Reconnect the WebSocket with exponential backoff.
        """
        self.reconnect_attempts += 1
        wait_time = min(2 ** self.reconnect_attempts, 60)  # Max 60 seconds
        logger.info(f"Reconnecting WebSocket in {wait_time} seconds...")
        time.sleep(wait_time)
        self.start()

    def renew_listen_key(self):
        """
        Renew the listen key every 30 minutes to keep the WebSocket connection alive.
        """
        while True:
            try:
                time.sleep(1800)  # Renew every 30 minutes
                logger.info("Renewing listen key...")
                self.rest_client.renew_listen_key(self.listen_key)
                logger.info("Listen key renewed successfully.")
            except Exception as e:
                logger.error(f"Error renewing listen key: {e}", exc_info=True)
                self.reconnect()

    def handle_message(self, message):
        """
        Handle incoming WebSocket messages.
        """
        event_type = message.get("e")
        if event_type == "ACCOUNT_UPDATE":
            self.handle_account_update(message)
        elif event_type == "ORDER_TRADE_UPDATE":
            self.handle_order_trade_update(message)
        else:
            logger.info(f"Unhandled event type: {event_type}")

    def handle_account_update(self, data):
        """
        Process ACCOUNT_UPDATE events.
        """
        logger.info(f"Account update: {data}")
        positions = data.get("a", {}).get("P", [])
        for position in positions:
            logger.debug(f"Position update: {position}")

    def handle_order_trade_update(self, data):
        """
        Handle the ORDER_TRADE_UPDATE event from WebSocket.
        """
        logger.info(f"Order trade update: {data}")
        order_info = data.get("o", {})
        status = order_info.get("X")  # Order status (e.g., "FILLED")
        symbol = order_info.get("s")  # Symbol (e.g., "LINKUSDT")
        avg_price = float(order_info.get("ap", 0))  # Average fill price
        quantity = float(order_info.get("z", 0))  # Filled quantity
        side = order_info.get("S")  # Side (e.g., "BUY", "SELL")

        # Check if the order is FILLED and it's a MARKET order
        if status == "FILLED" and order_info.get("o") == "MARKET":
            logger.info(f"Market order filled for {symbol} at avg price: {avg_price}.")

            # Skip placing TP if the position was exited
            if symbol in self.tp_tracker and self.tp_tracker[symbol] == "EXIT":
                logger.info(f"Exit signal detected for {symbol}. Skipping TP placement.")
                del self.tp_tracker[symbol]  # Clean up tracker after exit
                return

            # Check if TP order is already placed
            if symbol in self.tp_tracker:
                logger.info(f"TP order already placed for {symbol}. Skipping.")
                return

            # Calculate TP price and place TP order
            try:
                take_profit_percent = 0.5  # Example TP percent; you can adjust dynamically
                if side == "BUY":
                    tp_price = avg_price * (1 + take_profit_percent / 100)
                    tp_side = "SELL"
                else:
                    tp_price = avg_price * (1 - take_profit_percent / 100)
                    tp_side = "BUY"

                logger.info(f"Placing TP order for {symbol}: Side={tp_side}, Price={tp_price}")
                tp_order_id = self.rest_client.place_take_profit_order(symbol, tp_side, quantity, tp_price)

                # Track the TP order with its orderId
                self.tp_tracker[symbol] = tp_order_id
                logger.info(f"Tracked TP order for {symbol}: {tp_order_id}")
            except Exception as e:
                logger.error(f"Failed to place TP order for {symbol}: {e}", exc_info=True)


    def stop(self):
        """
        Stop the WebSocket connection.
        """
        if self.ws:
            self.ws.close()
        logger.info("WebSocket connection stopped.")
