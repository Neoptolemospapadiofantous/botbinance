import logging
import hmac
import hashlib
import time
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("binance_rest")
logging.basicConfig(level=logging.INFO)

class BinanceRESTClient:
    def __init__(self):
        logger.info("Initializing Binance REST Client")
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")
        self.base_url = os.getenv("BASE_URL")
        # self.tp_tracker = {}  # Track TP orders by symbol
        
        if not all([self.api_key, self.secret_key, self.base_url]):
            raise ValueError("Missing required environment variables. Check your .env file.")

    def create_signature(self, params):
        # Build a query string
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        # Sign it with HMAC-SHA256 using self.secret_key
        return hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def get_server_time(self):
        url = f"{self.base_url}/fapi/v1/time"
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("serverTime")

    def place_market_order(self, symbol, side, quantity, leverage=None, take_profit_percent=None):
        """
        Places a MARKET order. 
        If you want a quick TP, you can still call place_take_profit_order,
        but do NOT store anything in self.tp_tracker. 
        The WebSocket will do that.
        """
        try:
            # 1) Set leverage if desired
            if leverage:
                self.set_leverage(symbol, leverage)

            # 2) Place the MARKET order
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": quantity,
                "timestamp": self.get_server_time(),
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}

            url = f"{self.base_url}/fapi/v1/order"
            response = requests.post(url, headers=headers, params=params)
            response.raise_for_status()

            order_response = response.json()
            logger.info(f"Market order response: {order_response}")

            # If there's a TP percent, we can place a quick TP
            # but do not track it here, the WebSocket tracks TPs
            avg_price = float(order_response.get("avgPrice", 0))
            if take_profit_percent and avg_price != 0:
                if side.upper() == "BUY":
                    tp_price = avg_price * (1 + take_profit_percent / 100)
                    tp_side = "SELL"
                else:
                    tp_price = avg_price * (1 - take_profit_percent / 100)
                    tp_side = "BUY"

                self.place_take_profit_order(symbol, tp_side, quantity, tp_price)

            return order_response

        except Exception as e:
            logger.error(f"Failed to place market order: {e}", exc_info=True)
            raise


    def set_leverage(self, symbol, leverage):
        """
        Set leverage for a given symbol.
        """
        try:
            url = f"{self.base_url}/fapi/v1/leverage"
            params = {
                "symbol": symbol,
                "leverage": leverage,
                "timestamp": self.get_server_time(),
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            response = requests.post(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to set leverage: {e}", exc_info=True)
            raise

    def place_take_profit_order(self, symbol, side, quantity, take_profit_price):
        """
        Places a TAKE_PROFIT_MARKET order at the given stopPrice.
        Does NOT store or track this order locally. The WebSocket does that.
        """
        try:
            tp_params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": f"{take_profit_price:.2f}",
                "quantity": f"{quantity:.1f}",
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
            }
            tp_params["signature"] = self.create_signature(tp_params)
            headers = {"X-MBX-APIKEY": self.api_key}

            url = f"{self.base_url}/fapi/v1/order"
            resp = requests.post(url, headers=headers, data=tp_params)
            logger.debug(f"Take-profit response: {resp.text}")

            if resp.status_code == 200:
                data = resp.json()
                tp_order_id = data["orderId"]
                logger.info(f"Take-profit order successfully placed: {data}")
                return tp_order_id
            else:
                logger.error(f"Failed to place take-profit order: {resp.text}")
                return None

        except Exception as e:
            logger.error(f"Error placing take-profit order: {e}", exc_info=True)
            return None

    def get_listen_key(self):
        """
        Obtain a listen key for the user data stream.
        """
        try:
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self.api_key}
            response = requests.post(url, headers=headers)
            response.raise_for_status()
            listen_key = response.json().get("listenKey")
            if not listen_key:
                raise ValueError("Failed to retrieve listen key from Binance API.")
            logger.info(f"Successfully obtained listen key: {listen_key}")
            return listen_key
        except Exception as e:
            logger.error(f"Error fetching listen key: {e}", exc_info=True)
            raise

    def close_position(self, symbol):
        """
        Close an open position by placing a MARKET order in the opposite direction.
        No local tp_tracker usage; we rely on the WebSocket for all TP logic.
        """
        try:
            logger.info(f"Fetching position info for symbol: {symbol}")

            # 1) Fetch position details
            url = f"{self.base_url}/fapi/v2/positionRisk"
            params = {"timestamp": self.get_server_time()}
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}

            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()

            positions = response.json()
            position = next((p for p in positions if p["symbol"] == symbol), None)
            if not position:
                raise ValueError(f"No position found for symbol: {symbol}")

            position_amt = float(position["positionAmt"])
            if position_amt == 0:
                logger.info(f"No open position to close for {symbol}")
                return {"message": f"No position to close for {symbol}", "status": "success"}

            # 2) Flatten the position with a MARKET order in the opposite side
            close_side = "SELL" if position_amt > 0 else "BUY"
            quantity = abs(position_amt)
            logger.info(f"Placing MARKET order to close position: {symbol}, side={close_side}, qty={quantity}")

            order_url = f"{self.base_url}/fapi/v1/order"
            close_params = {
                "symbol": symbol,
                "side": close_side,
                "type": "MARKET",
                "quantity": f"{quantity:.6f}",
                "timestamp": self.get_server_time(),
            }
            close_params["signature"] = self.create_signature(close_params)
            close_headers = {"X-MBX-APIKEY": self.api_key}

            resp = requests.post(order_url, headers=close_headers, params=close_params)
            resp.raise_for_status()

            close_response = resp.json()
            logger.info(f"Position closed successfully for {symbol}: {close_response}")
            return close_response

        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}", exc_info=True)
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

    def renew_listen_key(self, listen_key):
        """
        Renew the listen key to keep the WebSocket connection alive.
        """
        try:
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self.api_key}
            response = requests.put(url, headers=headers, params={"listenKey": listen_key})
            response.raise_for_status()
            logger.info("Successfully renewed listen key.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error renewing listen key: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error renewing listen key: {e}", exc_info=True)
            raise
