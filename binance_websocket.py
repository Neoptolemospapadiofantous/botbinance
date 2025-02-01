import logging
import json
import requests
from websocket import WebSocketApp
from threading import Thread
import time
import os
from dotenv import load_dotenv

load_dotenv()

TRAILING_STOP_PERCENT = float(os.getenv("TRAILING_STOP_PERCENT", "0.2"))

logger = logging.getLogger("binance_ws")
logging.basicConfig(level=logging.INFO)

class BinanceWebSocket:
    """
    Binance WebSocket client to handle user data streams and update trailing stop loss orders.

    For BUY/SELL trades:
      - If an EXIT signal arrives within 3 seconds of the entry signal, trailing stop loss is enabled.
      - The WebSocket continuously updates a STOP_MARKET order (trailing stop loss) based on the best price.
      - When the trailing stop order is filled, the position is closed.
      - For normal trades, a take profit order is placed and if an EXIT signal arrives after 3 sec, all orders are canceled and the position is closed.
    """
    def __init__(self, rest_client):
        self.rest_client = rest_client
        self.listen_key = None
        self.ws = None
        self.ws_thread = None
        self.websocket_url = os.getenv("WEBSOCKET_URL")
        self.sl_tracker = {}             # Active stop loss order IDs per symbol.
        self.best_price = {}             # Best price tracked per symbol.
        self.trailing_stop_enabled = {}  # Flag per symbol.
        self.reconnect_attempts = 0

    def start(self):
        try:
            self.listen_key = self.rest_client.get_listen_key()
            if not self.listen_key:
                logger.error("Failed to get listenKey. WebSocket cannot start.")
                return
            ws_url = f"{self.websocket_url}/{self.listen_key}"
            logger.info(f"Connecting to WebSocket: {ws_url}")

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

            self.ws = WebSocketApp(
                ws_url,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error
            )
            self.ws_thread = Thread(target=self.ws.run_forever, daemon=True)
            self.ws_thread.start()
            logger.info("WebSocket thread started.")
            Thread(target=self.renew_listen_key, daemon=True).start()
            Thread(target=self.log_trailing_status, daemon=True).start()
        except Exception as e:
            logger.error(f"Error starting WebSocket: {e}", exc_info=True)

    def reconnect(self):
        self.reconnect_attempts += 1
        wait_time = min(2 ** self.reconnect_attempts, 60)
        logger.info(f"Reconnecting WebSocket in {wait_time} seconds...")
        time.sleep(wait_time)
        self.start()

    def renew_listen_key(self):
        while True:
            try:
                time.sleep(1800)
                logger.info("Renewing listen key...")
                self.rest_client.renew_listen_key(self.listen_key)
                logger.info("Listen key renewed successfully.")
            except Exception as e:
                logger.error(f"Error renewing listen key: {e}", exc_info=True)
                self.reconnect()

    def log_trailing_status(self):
        while True:
            logger.info("Trailing Stop Status:")
            logger.info(f"Trailing Enabled: {self.trailing_stop_enabled}")
            logger.info(f"Best Price: {self.best_price}")
            logger.info(f"Active Stop Loss Orders: {self.sl_tracker}")
            time.sleep(10)

    def handle_message(self, message):
        event_type = message.get("e")
        if event_type == "ACCOUNT_UPDATE":
            self.handle_account_update(message)
        elif event_type == "ORDER_TRADE_UPDATE":
            self.handle_order_trade_update(message)
        else:
            logger.info(f"Unhandled event type: {event_type}")

    def handle_account_update(self, data):
        logger.info(f"Account update: {data}")

    def handle_order_trade_update(self, data):
        logger.info(f"Order trade update: {data}")
        order_info = data.get("o", {})
        status = order_info.get("X")
        symbol = order_info.get("s")
        avg_price = float(order_info.get("ap", 0))
        quantity = float(order_info.get("z", 0))
        side = order_info.get("S")
        order_type = order_info.get("ot")

        # For filled market BUY orders when trailing is enabled:
        if status == "FILLED" and order_info.get("o") == "MARKET":
            logger.info(f"Market order filled for {symbol} at avg price: {avg_price}.")
            if side == "BUY" and self.trailing_stop_enabled.get(symbol, False):
                if symbol not in self.best_price or avg_price > self.best_price[symbol]:
                    self.best_price[symbol] = avg_price
                trailing_stop_percent = TRAILING_STOP_PERCENT
                self.update_trailing_stop(symbol, self.best_price[symbol], trailing_stop_percent, quantity)

        # For filled STOP_MARKET orders (trailing stop triggered):
        if order_type == "STOP_MARKET" and status == "FILLED":
            logger.info(f"Trailing stop loss triggered for {symbol} at avg price: {avg_price}.")
            self.trailing_stop_enabled[symbol] = False
            try:
                close_resp = self.rest_client.close_position(symbol)
                logger.info(f"Position closed via trailing stop for {symbol}: {close_resp}")
            except Exception as e:
                logger.error(f"Error closing position for {symbol} via trailing stop: {e}", exc_info=True)
            if symbol in self.sl_tracker:
                del self.sl_tracker[symbol]

    def update_trailing_stop(self, symbol, current_price, trailing_stop_percent, quantity):
        # Calculate new stop loss price: new_stop_price = current_price * (1 - trailing_stop_percent/100)
        new_stop_price = current_price * (1 - trailing_stop_percent / 100)
        logger.info(f"Updating trailing stop for {symbol}: new stop price {new_stop_price:.2f}")
        if symbol in self.sl_tracker:
            old_sl_id = self.sl_tracker[symbol]
            logger.info(f"Existing stop loss for {symbol} (orderId={old_sl_id}) found. Cancelling it.")
            try:
                self.rest_client.cancel_existing_tp(symbol, old_sl_id)
            except Exception as e:
                logger.error(f"Failed to cancel old SL for {symbol}: {e}", exc_info=True)
            del self.sl_tracker[symbol]
        try:
            new_sl_id = self.rest_client.place_stop_loss_order(symbol, "SELL", quantity, new_stop_price)
            if new_sl_id:
                self.sl_tracker[symbol] = new_sl_id
                logger.info(f"Tracked new stop loss for {symbol} = {new_sl_id}")
            else:
                logger.warning(f"Failed to place new stop loss for {symbol}")
        except Exception as e:
            logger.error(f"Error placing SL order for {symbol}: {e}", exc_info=True)

    def get_position_amt(self, symbol):
        try:
            url = f"{self.rest_client.base_url}/fapi/v2/positionRisk"
            params = {"timestamp": self.rest_client.get_server_time()}
            params["signature"] = self.rest_client.create_signature(params)
            headers = {"X-MBX-APIKEY": self.rest_client.api_key}
            resp = requests.get(url, headers=headers, params=params)
            resp.raise_for_status()
            positions = resp.json()
            pos_data = next((p for p in positions if p["symbol"] == symbol), None)
            if not pos_data:
                return 0.0
            return float(pos_data["positionAmt"])
        except Exception as e:
            logger.error(f"Error fetching positionAmt for {symbol}: {e}", exc_info=True)
            return 0.0

    def stop(self):
        if self.ws:
            self.ws.close()
        logger.info("WebSocket connection stopped.")
