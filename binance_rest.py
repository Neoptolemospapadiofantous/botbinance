import logging
import hmac
import hashlib
import time
import requests
import json
import websocket
from threading import Thread, Lock
from websocket import WebSocketApp
# ==============================================================================

BINANCE_API_KEY = "1cZ7h508rBXAdn0jM0mMYnCO214OiI80eFjZFgN78ySzWVtar9lWT5GDfDCvm10E"
BINANCE_SECRET_KEY = "OE3DN4tbXi2iOOVSiKmuBINGyP5lw5IApgXKI9Nz6mebrGu3jwmZ5mQZj05QkM4F"

# Binance API URLs
BASE_URL = "https://fapi.binance.com"
WEBSOCKET_URL = "wss://fstream.binance.com/ws"

# Configure logging
logger = logging.getLogger("binance_rest")
logging.basicConfig(level=logging.DEBUG)


class BinanceRESTClient:
    def __init__(self):
        logger.info("Initializing Binance REST Client")
        self.api_key = BINANCE_API_KEY
        self.secret_key = BINANCE_SECRET_KEY
        self.base_url = BASE_URL
        self.order_map = {}  # To track orders if needed

    def create_signature(self, params: dict):
        """
        Create HMAC SHA256 signature for Binance API requests.
        """
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def get_server_time(self):
        """
        Fetch Binance server time to ensure timestamp accuracy.
        """
        try:
            url = f"{self.base_url}/fapi/v1/time"
            response = requests.get(url)
            if response.status_code == 200:
                server_time = response.json()["serverTime"]
                logger.debug(f"Fetched Binance server time: {server_time}")
                return server_time
            else:
                logger.error(f"Failed to fetch server time: {response.text}")
                raise Exception("Could not fetch Binance server time.")
        except Exception as e:
            logger.error(f"Error fetching server time: {e}", exc_info=True)
            raise

    def get_listen_key(self):
        """
        Obtain a listenKey for the user data stream.
        """
        url = f"{self.base_url}/fapi/v1/listenKey"
        headers = {"X-MBX-APIKEY": self.api_key}
        response = requests.post(url, headers=headers)

        logger.debug(f"ListenKey response: {response.text}")

        if response.status_code == 200:
            listen_key = response.json()["listenKey"]
            logger.info(f"Obtained listenKey: {listen_key}")
            return listen_key
        else:
            logger.error(f"Failed to get listenKey: {response.text}")
            return None

    def get_open_orders(self, symbol):
        """
        Get all open orders for a specific symbol.
        """
        try:
            url = f"{self.base_url}/fapi/v1/openOrders"
            params = {
                "symbol": symbol,
                "timestamp": self.get_server_time(),
                "recvWindow": 5000
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}

            response = requests.get(url, headers=headers, params=params)
            logger.debug(f"Open orders response: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to fetch open orders: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching open orders for {symbol}: {e}", exc_info=True)
            return []

    def set_leverage(self, symbol, leverage):
        """
        Set leverage for a given trading symbol.
        """
        try:
            url = f"{self.base_url}/fapi/v1/leverage"
            params = {
                "symbol": symbol,
                "leverage": leverage,
                "timestamp": self.get_server_time(),
                "recvWindow": 5000
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}

            logger.info(f"Sending set leverage request to Binance API. URL: {url}")
            logger.debug(f"Parameters for leverage request: {params}")

            response = requests.post(url, headers=headers, data=params)
            logger.debug(f"Leverage response: {response.text}")

            if response.status_code == 200:
                logger.info(f"Leverage successfully set: {response.json()}")
            else:
                logger.error(f"Failed to set leverage: {response.text}")
            return response.json()

        except Exception as e:
            logger.error(f"An error occurred while setting leverage: {str(e)}", exc_info=True)
            raise

    def place_market_order(self, symbol, side, quantity, leverage=None, take_profit_percent=None):
        """
        Place a MARKET order on Binance Futures. Optionally sets leverage and calculates a take-profit order.
        """
        try:
            # Set leverage if provided
            if leverage:
                self.set_leverage(symbol, leverage)

            # Create the market order
            url = f"{self.base_url}/fapi/v1/order"
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": "{:.1f}".format(float(quantity)),  # Ensure proper precision
                "timestamp": self.get_server_time(),
                "recvWindow": 5000
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}

            logger.info(f"Sending market order request to Binance API. URL: {url}")
            logger.debug(f"Signed parameters: {params}")

            response = requests.post(url, headers=headers, data=params)
            logger.debug(f"Response content: {response.text}")

            if response.status_code == 200:
                logger.info(f"Market order successfully placed: {response.json()}")

                # If take_profit_percent is provided, calculate the TP price and place a TP order
                if take_profit_percent:
                    avg_price = float(response.json().get("fills", [{}])[0].get("price", 0))  # Get average price from response
                    if avg_price > 0:
                        if side.upper() == "BUY":
                            tp_price = avg_price * (1 + take_profit_percent / 100)
                            tp_side = "SELL"
                        else:  # SELL order
                            tp_price = avg_price * (1 - take_profit_percent / 100)
                            tp_side = "BUY"

                        logger.info(f"Calculated take-profit price: {tp_price} for {symbol}. Placing TP order.")
                        self.place_take_profit_order(symbol, tp_side, quantity, tp_price)
                    else:
                        logger.warning("Average price not found in the order response. Skipping TP order.")
                return response.json()
            else:
                logger.error(f"Failed to place market order: {response.text}")
                return None

        except Exception as e:
            logger.error(f"An error occurred while placing the market order: {str(e)}", exc_info=True)
            raise

    def cancel_existing_tp(self, symbol, tp_order_id):
        """
        Cancel an existing TP order for a symbol.
        """
        try:
            logger.info(f"Cancelling existing TP order {tp_order_id} for {symbol}.")
            cancel_params = {
                "symbol": symbol,
                "orderId": tp_order_id,
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
            }
            cancel_params["signature"] = self.create_signature(cancel_params)
            headers = {"X-MBX-APIKEY": self.api_key}

            url = f"{self.base_url}/fapi/v1/order"
            response = requests.delete(url, headers=headers, params=cancel_params)

            if response.status_code == 200:
                logger.info(f"Successfully canceled TP order {tp_order_id} for {symbol}.")
            else:
                logger.error(f"Failed to cancel TP order: {response.text}")
        except Exception as e:
            logger.error(f"Error cancelling TP order for {symbol}: {e}", exc_info=True)

    def place_take_profit_order(self, symbol, side, quantity, take_profit_price):
        """
        Place a TAKE_PROFIT_MARKET order.
        """
        try:
            tp_params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": "{:.2f}".format(take_profit_price),
                "quantity": "{:.1f}".format(quantity),
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
            }
            tp_params["signature"] = self.create_signature(tp_params)
            headers = {"X-MBX-APIKEY": self.api_key}

            url = f"{self.base_url}/fapi/v1/order"
            response = requests.post(url, headers=headers, data=tp_params)
            logger.debug(f"Take-profit response: {response.text}")

            if response.status_code == 200:
                logger.info(f"Take-profit order successfully placed: {response.json()}")
                return response.json()
            else:
                logger.error(f"Failed to place take-profit order: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error placing take-profit order: {e}", exc_info=True)


class BinanceWebSocket:
    def __init__(self, rest_client):
        logger.info("Initializing Binance WebSocket Client")
        self.rest_client = rest_client
        self.listen_key = self.rest_client.get_listen_key()
        self.ws = None
        self.ws_thread = None

        # Track active take-profit orders
        self.tp_tracker = {}  # Format: {"symbol": "tp_order_id"}
        self.tp_tracker_lock = Lock()  # Thread safety

    def start(self):
        """
        Start the WebSocket connection.
        """
        if not self.listen_key:
            logger.error("No listenKey available. Cannot start WebSocket.")
            return

        ws_url = f"{WEBSOCKET_URL}/{self.listen_key}"
        logger.info(f"Connecting to WebSocket: {ws_url}")

        def on_message(ws, message):
            logger.debug(f"WebSocket message received: {message}")
            data = json.loads(message)

            # Handle ORDER_TRADE_UPDATE events
            if data.get("e") == "ORDER_TRADE_UPDATE":
                self.handle_order_trade_update(data)

            # Handle ACCOUNT_UPDATE events
            if data.get("e") == "ACCOUNT_UPDATE":
                self.handle_account_update(data)

        def on_open(ws):
            logger.info("WebSocket connection opened.")

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.warning(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")
            logger.info("Attempting to reconnect...")
            self.start()

        self.ws = WebSocketApp(
            ws_url,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close
        )
        self.ws_thread = Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()
        logger.info("WebSocket thread started.")

    def update_tp_tracker(self, symbol, order_id):
        with self.tp_tracker_lock:
            self.tp_tracker[symbol] = order_id

    def remove_tp_tracker(self, symbol):
        with self.tp_tracker_lock:
            if symbol in self.tp_tracker:
                del self.tp_tracker[symbol]

    def get_tp_tracker(self, symbol):
        with self.tp_tracker_lock:
            return self.tp_tracker.get(symbol)

    def ensure_single_tp_order(self, symbol, side, quantity, take_profit_price):
        """
        Ensure only one TP order exists for a symbol.
        """
        tp_order_id = self.get_tp_tracker(symbol)
        if tp_order_id:
            logger.info(f"Existing TP order found for {symbol}. Cancelling.")
            self.rest_client.cancel_existing_tp(symbol, tp_order_id)

        self.place_take_profit_order(symbol, side, quantity, take_profit_price)

    def place_take_profit_order(self, symbol, side, quantity, take_profit_price):
        """
        Place a TAKE_PROFIT_MARKET order and track it in the TP tracker.
        """
        try:
            tp_params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": "{:.2f}".format(take_profit_price),
                "quantity": "{:.1f}".format(quantity),
                "timestamp": self.rest_client.get_server_time(),
                "recvWindow": 5000,
            }
            tp_params["signature"] = self.rest_client.create_signature(tp_params)
            headers = {"X-MBX-APIKEY": self.rest_client.api_key}

            url = f"{self.rest_client.base_url}/fapi/v1/order"
            response = requests.post(url, headers=headers, data=tp_params)

            logger.debug(f"Take-profit response: {response.text}")

            if response.status_code == 200:
                tp_order_id = response.json()["orderId"]
                self.update_tp_tracker(symbol, tp_order_id)
                logger.info(f"Take-profit order successfully placed: {response.json()}")
            else:
                logger.error(f"Failed to place take-profit order: {response.text}")

        except Exception as e:
            logger.error(f"Error placing take-profit order: {e}", exc_info=True)

    def handle_order_trade_update(self, data):
        """
        Handle the ORDER_TRADE_UPDATE event from WebSocket.
        """
        order_info = data["o"]
        status = order_info["X"]
        avg_price = float(order_info.get("ap", 0))
        quantity = float(order_info.get("z", 0))
        symbol = order_info["s"]
        side = order_info["S"]

        if status == "FILLED" and order_info["o"] == "MARKET":
            logger.info(f"Order filled for {symbol} at avg price: {avg_price}.")

            take_profit_percent = 0.5  # Adjust as needed
            tp_price = avg_price * (1 + take_profit_percent / 100) if side == "BUY" else avg_price * (1 - take_profit_percent / 100)
            tp_side = "SELL" if side == "BUY" else "BUY"

            self.ensure_single_tp_order(symbol, tp_side, quantity, tp_price)

    def handle_account_update(self, data):
        """
        Handle the ACCOUNT_UPDATE event from WebSocket.
        """
        positions = data["a"]["P"]
        for position in positions:
            symbol = position["s"]
            position_size = float(position["pa"])  # Position size

            # If the position size is zero, remove the TP tracker for this symbol
            if position_size == 0 and symbol in self.tp_tracker:
                logger.info(f"Position closed for {symbol}. Removing TP tracker.")
                self.remove_tp_tracker(symbol)
