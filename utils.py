# utils.py
import logging

logger = logging.getLogger("utils")
logging.basicConfig(level=logging.DEBUG)

def parse_webhook_to_payload(webhook_data):
    """
    Parse the incoming webhook data into a Binance order payload.
    """
    try:
        logger.info(f"Parsing webhook data: {webhook_data}")

        value = webhook_data["value"]
        trade_info = webhook_data["trade_info"]

        action = value.split(" ")[1].upper()  # Extract "BUY" or "SELL"

        ticker = trade_info["ticker"]
        contracts = trade_info["contracts"]
        leverage = trade_info["leverage"]

        payload = {
            "symbol": ticker,
            "side": action,
            "quantity": contracts,
            "leverage": leverage,
            "take_profit": trade_info.get("take_profit")  # Optional
        }
        logger.info(f"Generated payload: {payload}")
        return payload

    except KeyError as e:
        logger.error(f"Missing key in webhook data: {e}")
        raise
    except Exception as e:
        logger.error(f"Error parsing webhook data: {e}")
        raise