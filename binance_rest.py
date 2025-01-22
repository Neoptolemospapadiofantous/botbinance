import logging
import hmac
import hashlib
import time
import requests
import json
import websocket
from threading import Thread

# ==============================================================================
# CAUTION: DO NOT hardcode your real API keys in production!
# Use environment variables or a secure vault.
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
        self.order_map = {}

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
        Place a MARKET order on Binance Futures.
        """
        try:
            if leverage:
                self.set_leverage(symbol, leverage)

            url = f"{self.base_url}/fapi/v1/order"
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": "{:.1f}".format(float(quantity)),  # Adjust precision if needed
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
            else:
                logger.error(f"Failed to place market order: {response.text}")

            return response.json()

        except Exception as e:
            logger.error(f"An error occurred while placing the market order: {str(e)}", exc_info=True)
            raise


class BinanceWebSocket:
    def __init__(self, rest_client):
        logger.info("Initializing Binance WebSocket Client")
        self.rest_client = rest_client
        self.listen_key = self.rest_client.get_listen_key()
        self.ws = None
        self.ws_thread = None

    def start(self):
        """
        Start WebSocket connection.
        """
        if not self.listen_key:
            logger.error("No listenKey available. Cannot start WebSocket.")
            return

        ws_url = f"{WEBSOCKET_URL}/{self.listen_key}"
        logger.info(f"Connecting to WebSocket: {ws_url}")

        def on_message(ws, message):
            logger.debug(f"WebSocket message received: {message}")
            data = json.loads(message)

            # Check for order updates
            if data.get("e") == "ORDER_TRADE_UPDATE":
                order_info = data["o"]
                order_id = order_info["i"]
                status = order_info["X"]  # Status of the order
                avg_price = float(order_info.get("ap", 0))  # Average price
                quantity = float(order_info.get("z", 0))  # Cumulative filled quantity
                symbol = order_info["s"]  # Symbol (e.g., LINKUSDT)
                side = order_info["S"]  # Side (BUY/SELL)

                # Check if the order is fully filled
                if status == "FILLED":
                    logger.info(f"Order {order_id} for {symbol} filled at avg price: {avg_price}.")

                    # Example take-profit percentage
                    take_profit_percent = 0.5  # Replace with dynamic value if needed

                    # Calculate take-profit price
                    if side == "BUY":
                        take_profit_price = avg_price * (1 + take_profit_percent / 100)
                        tp_side = "SELL"
                    else:  # For SELL orders
                        take_profit_price = avg_price * (1 - take_profit_percent / 100)
                        tp_side = "BUY"

                    logger.info(f"Calculated take-profit price: {take_profit_price} for {symbol}.")

                    # Place the take-profit order
                    try:
                        tp_params = {
                            "symbol": symbol,
                            "side": tp_side,
                            "type": "TAKE_PROFIT_MARKET",
                            "stopPrice": "{:.2f}".format(take_profit_price),
                            "quantity": "{:.1f}".format(quantity),
                            "timestamp": self.rest_client.get_server_time(),
                            "recvWindow": 5000
                        }
                        tp_params["signature"] = self.rest_client.create_signature(tp_params)
                        headers = {"X-MBX-APIKEY": self.rest_client.api_key}

                        url = f"{self.rest_client.base_url}/fapi/v1/order"
                        response = requests.post(url, headers=headers, data=tp_params)
                        logger.debug(f"Take-profit response: {response.text}")

                        if response.status_code == 200:
                            logger.info(f"Take-profit order successfully placed: {response.json()}")
                        else:
                            logger.error(f"Failed to place take-profit order: {response.text}")

                    except Exception as e:
                        logger.error(f"Error placing take-profit order: {e}", exc_info=True)

        def on_open(ws):
            logger.info("WebSocket connection opened.")

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.warning(f"WebSocket closed with code: {close_status_code}, message: {close_msg}")
            logger.info("Attempting to reconnect...")
            self.start()

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close
        )
        self.ws_thread = Thread(target=self.ws.run_forever, daemon=True)
        self.ws_thread.start()
        logger.info("WebSocket thread started.")