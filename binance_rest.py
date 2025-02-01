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
        if not all([self.api_key, self.secret_key, self.base_url]):
            raise ValueError("Missing required environment variables. Check your .env file.")

    def create_signature(self, params):
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
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
        try:
            if leverage:
                self.set_leverage(symbol, leverage)
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
            return order_response
        except Exception as e:
            logger.error(f"Failed to place market order: {e}", exc_info=True)
            raise

    def set_leverage(self, symbol, leverage):
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
        try:
            tp_params = {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": f"{take_profit_price:.2f}",
                "quantity": f"{float(quantity):.1f}",
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

    def place_stop_loss_order(self, symbol, side, quantity, stop_loss_price):
        try:
            formatted_qty = f"{float(quantity):.1f}"
            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "STOP_MARKET",
                "stopPrice": f"{stop_loss_price:.2f}",
                "quantity": formatted_qty,
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/order"
            resp = requests.post(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Stop loss order placed for {symbol}: {data}")
            return data.get("orderId")
        except Exception as e:
            logger.error(f"Error placing stop loss order for {symbol}: {e}", exc_info=True)
            return None

    def cancel_all_orders(self, symbol):
        """
        Cancel all open orders for the given symbol.
        """
        try:
            params = {
                "symbol": symbol,
                "timestamp": self.get_server_time()
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/allOpenOrders"
            response = requests.delete(url, headers=headers, params=params)
            response.raise_for_status()
            logger.info(f"All open orders canceled for {symbol}.")
            return response.json()
        except Exception as e:
            logger.error(f"Error canceling all orders for {symbol}: {e}", exc_info=True)
            return None

    def get_listen_key(self):
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
        try:
            logger.info(f"Fetching position info for symbol: {symbol}")
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
        try:
            logger.info(f"Cancelling existing order {tp_order_id} for {symbol}.")
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
                logger.info(f"Successfully canceled order {tp_order_id} for {symbol}.")
            else:
                logger.error(f"Failed to cancel order: {response.text}")
        except Exception as e:
            logger.error(f"Error cancelling order for {symbol}: {e}", exc_info=True)

    def renew_listen_key(self, listen_key):
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

    def get_last_price(self, symbol):
        try:
            url = f"{self.base_url}/fapi/v1/ticker/price"
            params = {"symbol": symbol}
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            price = float(data["price"])
            logger.info(f"Retrieved current market price for {symbol}: {price}")
            return price
        except Exception as e:
            logger.error(f"Error fetching last price for {symbol}: {e}", exc_info=True)
            return 0.0
