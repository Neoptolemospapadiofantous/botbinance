import logging
import json
import requests
from websocket import WebSocketApp
from threading import Thread
import time
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("binance_ws")
logging.basicConfig(level=logging.INFO)

class BinanceWebSocket:
    def __init__(self, rest_client):
        self.rest_client = rest_client
        self.listen_key = None
        self.ws = None
        self.ws_thread = None
        self.websocket_url = os.getenv("WEBSOCKET_URL")

        # Tracking
        self.sl_tracker = {}
        self.best_price = {}
        self.trailing_stop_enabled = {}
        self.entry_price = {}
        self.tp_target_price = {}         # <-- store final TP price
        self.trailing_progress = {}       # how many 25% intervals we've crossed
        self.break_even_triggered = {}

        self.reconnect_attempts = 0

        # Read from .env
        self.trailing_stop_percent = float(os.getenv("TRAILING_STOP_PERCENT", "0.2"))
        self.enable_trailing_threshold = float(os.getenv("ENABLE_TRAILING_THRESHOLD", "50"))
        self.trailing_step_interval = float(os.getenv("TRAILING_STEP_INTERVAL", "25"))
        
    def start(self):
        try:
            self.listen_key = self.rest_client.get_listen_key()
            if not self.listen_key:
                logger.error("Failed to get listenKey. Cannot start WebSocket.")
                return
            ws_url = f"{self.websocket_url}/{self.listen_key}"
            logger.info(f"Connecting to WebSocket: {ws_url}")

            def on_message(ws, message):
                self.handle_message(json.loads(message))

            def on_open(ws):
                logger.info("WebSocket opened.")

            def on_close(ws, close_status_code, close_msg):
                logger.warning(f"WebSocket closed (Code: {close_status_code}, Msg: {close_msg}). Reconnecting...")
                self.reconnect()

            def on_error(ws, error):
                logger.error(f"WebSocket error: {error}. Attempting reconnect.")
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

            Thread(target=self.renew_listen_key, daemon=True).start()
            Thread(target=self.log_trailing_status, daemon=True).start()

        except Exception as e:
            logger.error(f"Error starting WebSocket: {e}", exc_info=True)

    def reconnect(self):
        self.reconnect_attempts += 1
        wait = min(2 ** self.reconnect_attempts, 60)
        logger.info(f"Reconnecting in {wait} seconds...")
        time.sleep(wait)
        self.start()

    def renew_listen_key(self):
        while True:
            try:
                time.sleep(1800)
                if self.listen_key:
                    logger.info("Renewing listen key...")
                    self.rest_client.renew_listen_key(self.listen_key)
            except Exception as e:
                logger.error(f"Error renewing listen key: {e}", exc_info=True)
                self.reconnect()

    def log_trailing_status(self):
        while True:
            logger.info("===== Trailing Stop Status =====")
            logger.info(f"sl_tracker: {self.sl_tracker}")
            logger.info(f"best_price: {self.best_price}")
            logger.info(f"entry_price: {self.entry_price}")
            logger.info(f"tp_target_price: {self.tp_target_price}")
            logger.info(f"trailing_progress: {self.trailing_progress}")
            time.sleep(10)

    def handle_message(self, msg):
        event_type = msg.get("e")
        if event_type == "ORDER_TRADE_UPDATE":
            self.handle_order_trade_update(msg)
        elif event_type == "ACCOUNT_UPDATE":
            self.handle_account_update(msg)
        else:
            logger.debug(f"Unhandled event: {event_type}")

    def handle_account_update(self, data):
        logger.debug(f"ACCOUNT_UPDATE: {data}")

    def handle_order_trade_update(self, data):
        logger.info(f"ORDER_TRADE_UPDATE: {data}")
        info = data.get("o", {})
        symbol = info.get("s")
        status = info.get("X")       # e.g. "FILLED"
        order_type = info.get("ot")  # "MARKET", "STOP_MARKET", etc.
        side = info.get("S")
        avg_price = float(info.get("ap", 0))
        filled_qty = float(info.get("z", 0))

        if order_type == "MARKET" and status == "FILLED":
            logger.info(f"Market order FILLED for {symbol} at {avg_price}. side={side}")
            pos_amt = self.get_position_amt(symbol)

            # Determine if long or short
            if pos_amt > 0:
                logger.info(f"[{symbol}] LONG position detected")
                self.entry_price[symbol] = avg_price
                # Suppose we stored the user TP in self.tp_percent[symbol] previously (not shown).
                # For simplicity, let's do a fixed or 0.5 read from .env
                take_profit_pct = float(os.getenv("DEFAULT_TAKE_PROFIT_PERCENT", "0.5"))
                self.tp_target_price[symbol] = avg_price * (1 + take_profit_pct / 100.0)
            elif pos_amt < 0:
                logger.info(f"[{symbol}] SHORT position detected")
                self.entry_price[symbol] = avg_price
                take_profit_pct = float(os.getenv("DEFAULT_TAKE_PROFIT_PERCENT", "0.5"))
                self.tp_target_price[symbol] = avg_price * (1 - take_profit_pct / 100.0)
            else:
                # Possibly partial fill or position closed
                self.entry_price.pop(symbol, None)
                self.tp_target_price.pop(symbol, None)
                return

            # Reset trailing progress to 0
            self.trailing_progress[symbol] = 0

        # If the user has a price feed for real-time updates, we call check_trailing_progress in that loop
        # For demonstration, if your user data feed doesn't have real-time price, you'll need a ticker feed.

        if order_type == "STOP_MARKET" and status == "FILLED":
            logger.info(f"[{symbol}] STOP_MARKET filled => trailing triggered? Closing pos.")
            # You can close or handle as needed

        if order_type == "TAKE_PROFIT_MARKET" and status == "FILLED":
            logger.info(f"[{symbol}] TAKE_PROFIT_MARKET filled => final exit or partial exit?")

    def check_trailing_progress(self, symbol, current_price):
        """
        Once progress_pct >= self.enable_trailing_threshold (e.g. 50),
        place (or update) the trailing stop a single time.
        """
        if symbol not in self.entry_price or symbol not in self.tp_target_price:
            return

        pos_amt = self.get_position_amt(symbol)
        if pos_amt == 0:
            return

        entry = self.entry_price[symbol]
        target = self.tp_target_price[symbol]
        is_long = (pos_amt > 0)

        distance = (target - entry) if is_long else (entry - target)
        if distance <= 0:
            return

        current_distance = (current_price - entry) if is_long else (entry - current_price)
        progress_pct = (current_distance / distance) * 100.0
        logger.debug(f"[{symbol}] progress_pct={progress_pct:.2f}%")

        # If we haven't reached the 50% threshold => do nothing
        if progress_pct < self.enable_trailing_threshold:
            return

        # If we've never updated trailing_progress beyond 0, it means
        # we haven't placed the trailing stop yet, so do it once.
        if self.trailing_progress.get(symbol, 0) == 0:
            # Mark that we've done our one-time trailing stop update
            self.trailing_progress[symbol] = 1

            logger.info(
                f"[{symbol}] Reached {progress_pct:.2f}% (>= {self.enable_trailing_threshold}%) => "
                "placing trailing stop."
            )
            self.enable_or_update_trailing(symbol, current_price, abs(pos_amt))


    def enable_or_update_trailing(self, symbol, current_price, quantity):
        """
        Actually sets or updates the trailing stop behind the current price.
        """
        # Mark trailing_stop_enabled
        self.trailing_stop_enabled[symbol] = True

        # Then call update_trailing_stop
        self.update_trailing_stop(symbol, current_price, self.trailing_stop_percent, quantity)

    def update_trailing_stop(self, symbol, current_price, trailing_stop_percent, quantity):
        position_amt = self.get_position_amt(symbol)
        if position_amt == 0:
            return

        is_long = (position_amt > 0)
        if is_long:
            stop_price = current_price * (1 - trailing_stop_percent / 100.0)
            sl_side = "SELL"
        else:
            stop_price = current_price * (1 + trailing_stop_percent / 100.0)
            sl_side = "BUY"

        logger.info(f"[{symbol}] Setting trailing stop => price={stop_price:.6f}, side={sl_side}")
        if symbol in self.sl_tracker:
            old_id = self.sl_tracker[symbol]
            logger.info(f"[{symbol}] Cancel old stop id={old_id}")
            self.rest_client.cancel_order_by_id(symbol, old_id)
            del self.sl_tracker[symbol]

        sl_id = self.rest_client.place_stop_loss_order(symbol, sl_side, quantity, stop_price)
        if sl_id:
            self.sl_tracker[symbol] = sl_id
            logger.info(f"[{symbol}] Updated trailing stop => ID={sl_id}")
        else:
            logger.warning(f"[{symbol}] Failed to place trailing stop")

    def get_position_amt(self, symbol):
        """
        Return float positionAmt. + for long, - for short, 0 for none.
        """
        try:
            url = f"{self.rest_client.base_url}/fapi/v2/positionRisk"
            params = {"timestamp": self.rest_client.get_server_time()}
            params["signature"] = self.rest_client.create_signature(params)
            headers = {"X-MBX-APIKEY": self.rest_client.api_key}
            resp = requests.get(url, headers=headers, params=params)
            resp.raise_for_status()
            positions = resp.json()
            data = next((p for p in positions if p["symbol"] == symbol), None)
            if not data:
                return 0.0
            return float(data["positionAmt"])
        except Exception as e:
            logger.error(f"Error getting positionAmt for {symbol}: {e}", exc_info=True)
            return 0.0

    def stop(self):
        if self.ws:
            self.ws.close()
        logger.info("WebSocket stopped.")
