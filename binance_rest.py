import logging
import hmac
import hashlib
import time
import requests
import os
from dotenv import load_dotenv

logger = logging.getLogger("binance_rest")
logging.basicConfig(level=logging.INFO)

class BinanceRESTClient:
    def __init__(self):
        logger.info("Initializing Binance REST Client")
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.secret_key = os.getenv("BINANCE_SECRET_KEY")
        self.base_url = os.getenv("BASE_URL")  # e.g. https://fapi.binance.com
        if not all([self.api_key, self.secret_key, self.base_url]):
            raise ValueError("Missing required environment variables in .env")

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

    def set_leverage(self, symbol, leverage):
        """
        If you want to do this before your trade, call it
        separately from place_market_order().
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
            resp = requests.post(url, headers=headers, params=params)
            resp.raise_for_status()
            logger.info(f"Leverage set: {resp.json()}")
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to set leverage: {e}")
            raise

    def place_market_order(self, symbol, side, quantity):
        """
        Immediately places a MARKET order with minimal overhead.
        """
        try:
            adj_qty = self._adjust_quantity_precision(symbol, float(quantity))

            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "MARKET",
                "quantity": f"{adj_qty:.6f}",
                "timestamp": self.get_server_time(),
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/order"

            response = requests.post(url, headers=headers, params=params)
            response.raise_for_status()

            order_resp = response.json()
            logger.info(f"Market order response: {order_resp}")
            return order_resp

        except Exception as e:
            logger.error(f"Error placing market order: {e}", exc_info=True)
            raise

    def place_take_profit_order(self, symbol, side, quantity, tp_price):
        """
        TAKE_PROFIT_MARKET with reduceOnly=true, ensuring price & quantity
        match symbol's tickSize & stepSize.
        """
        try:
            adj_price = self._adjust_price_precision(symbol, tp_price)
            adj_qty = self._adjust_quantity_precision(symbol, float(quantity))

            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": f"{adj_price:.6f}",
                "quantity": f"{adj_qty:.6f}",
                "reduceOnly": "true",
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
                "workingType": "MARK_PRICE",  # or "CONTRACT_PRICE"
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/order"

            resp = requests.post(url, headers=headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Failed to place TAKE_PROFIT_MARKET: {resp.text}")
                resp.raise_for_status()

            data = resp.json()
            logger.info(f"Take-profit order placed successfully: {data}")
            return data.get("orderId")

        except Exception as e:
            logger.error(f"Error placing TP order: {e}", exc_info=True)
            return None

    def place_stop_loss_order(self, symbol, side, quantity, stop_loss_price):
        """
        STOP_MARKET with reduceOnly=true, ensuring price & quantity
        match symbol's tickSize & stepSize.
        """
        try:
            adj_price = self._adjust_price_precision(symbol, stop_loss_price)
            adj_qty = self._adjust_quantity_precision(symbol, float(quantity))

            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": "STOP_MARKET",
                "stopPrice": f"{adj_price:.6f}",
                "quantity": f"{adj_qty:.6f}",
                "reduceOnly": "true",
                "timestamp": self.get_server_time(),
                "recvWindow": 5000,
                "workingType": "MARK_PRICE",  # or "CONTRACT_PRICE"
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/order"

            resp = requests.post(url, headers=headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Failed to place STOP_MARKET: {resp.text}")
                resp.raise_for_status()

            data = resp.json()
            logger.info(f"Stop-loss order placed: {data}")
            return data.get("orderId")

        except Exception as e:
            logger.error(f"Error placing stop loss: {e}", exc_info=True)
            return None

    def cancel_all_orders(self, symbol):
        """
        Cancel all open orders for the symbol.
        """
        try:
            params = {"symbol": symbol, "timestamp": self.get_server_time()}
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/allOpenOrders"
            resp = requests.delete(url, headers=headers, params=params)
            resp.raise_for_status()
            logger.info(f"All open orders canceled for {symbol}.")
            return resp.json()
        except Exception as e:
            logger.error(f"Error canceling all orders for {symbol}: {e}", exc_info=True)
            return None

    def cancel_order_by_id(self, symbol, order_id):
        """
        Cancel a specific order by ID.
        """
        try:
            params = {
                "symbol": symbol,
                "orderId": order_id,
                "timestamp": self.get_server_time(),
            }
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            url = f"{self.base_url}/fapi/v1/order"
            resp = requests.delete(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Canceled order {order_id} for {symbol}: {data}")
            return data
        except Exception as e:
            logger.error(f"Error cancelling order {order_id} for {symbol}: {e}", exc_info=True)
            return None

    def close_position(self, symbol):
        """
        Closes the current position for the symbol using a MARKET order. 
        Checks positionAmt via /fapi/v2/positionRisk.
        """
        try:
            url = f"{self.base_url}/fapi/v2/positionRisk"
            params = {"timestamp": self.get_server_time()}
            params["signature"] = self.create_signature(params)
            headers = {"X-MBX-APIKEY": self.api_key}
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            positions = response.json()
            position = next((p for p in positions if p["symbol"] == symbol), None)
            if not position:
                raise ValueError(f"No position found for {symbol}.")
            position_amt = float(position["positionAmt"])
            if position_amt == 0:
                logger.info(f"No open position to close for {symbol}.")
                return {"message": f"No position to close for {symbol}", "status": "success"}

            close_side = "SELL" if position_amt > 0 else "BUY"
            quantity = abs(position_amt)

            # Place a market order to reduce to 0
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
            data = resp.json()
            logger.info(f"Position closed for {symbol}: {data}")
            return data
        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}", exc_info=True)
            raise

    def get_listen_key(self):
        """
        Retrieves a listen key for futures user data stream.
        """
        try:
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self.api_key}
            resp = requests.post(url, headers=headers)
            resp.raise_for_status()
            listen_key = resp.json().get("listenKey")
            if not listen_key:
                raise ValueError("Failed to retrieve listenKey.")
            logger.info(f"Obtained listenKey: {listen_key}")
            return listen_key
        except Exception as e:
            logger.error(f"Error fetching listen key: {e}", exc_info=True)
            raise

    def renew_listen_key(self, listen_key):
        """
        Renews an existing listen key before it expires.
        """
        try:
            url = f"{self.base_url}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self.api_key}
            resp = requests.put(url, headers=headers, params={"listenKey": listen_key})
            resp.raise_for_status()
            logger.info("Successfully renewed listen key.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error renewing listen key: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error renewing listen key: {e}", exc_info=True)
            raise

    def get_last_price(self, symbol):
        """
        Get the last price for the symbol from the /fapi/v1/ticker/price endpoint.
        """
        try:
            url = f"{self.base_url}/fapi/v1/ticker/price"
            params = {"symbol": symbol}
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            price = float(data["price"])
            logger.info(f"Last price for {symbol}: {price}")
            return price
        except Exception as e:
            logger.error(f"Error fetching last price for {symbol}: {e}", exc_info=True)
            return 0.0

    def _fetch_symbol_info(self, symbol):
        """
        Fetches exchange info for a given symbol. Cached to avoid repeated calls.
        """
        if not hasattr(self, "_symbol_info_cache"):
            self._symbol_info_cache = {}

        if symbol in self._symbol_info_cache:
            return self._symbol_info_cache[symbol]

        url = f"{self.base_url}/fapi/v1/exchangeInfo"
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()

        for s in data["symbols"]:
            if s["symbol"] == symbol:
                self._symbol_info_cache[symbol] = s
                return s

        raise ValueError(f"Symbol {symbol} not found in exchangeInfo.")

    def _adjust_price_precision(self, symbol, price):
        """
        Rounds the price to the symbol's 'tickSize' from PRICE_FILTER.
        """
        s_info = self._fetch_symbol_info(symbol)
        price_filter = next(
            (f for f in s_info["filters"] if f["filterType"] == "PRICE_FILTER"), None
        )
        if not price_filter:
            # fallback if no filter found
            return float(f"{price:.6f}")

        tick_size = float(price_filter["tickSize"])
        decimals = str(tick_size)[::-1].find('.')  # e.g. 0.001 => 3 decimals
        adjusted = round(price, decimals)
        return float(f"{adjusted:.{decimals}f}")

    def _adjust_quantity_precision(self, symbol, quantity):
        """
        Rounds the quantity to the symbol's 'stepSize' from LOT_SIZE filter.
        """
        s_info = self._fetch_symbol_info(symbol)
        lot_size_filter = next(
            (f for f in s_info["filters"] if f["filterType"] == "LOT_SIZE"), None
        )
        if not lot_size_filter:
            return float(f"{quantity:.6f}")  # fallback

        step_size = float(lot_size_filter["stepSize"])
        decimals = str(step_size)[::-1].find('.')  # e.g. 0.1 => 1 decimal
        adjusted = round(quantity, decimals)
        return float(f"{adjusted:.{decimals}f}")
