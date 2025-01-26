import logging

logger = logging.getLogger("utils")
logging.basicConfig(level=logging.DEBUG)

def parse_webhook_to_payload(webhook_data):
    """
    Parse the incoming webhook data into a Binance order payload and determine trade type.
    """
    try:
        logger.info(f"Parsing webhook data: {webhook_data}")

        value = webhook_data["value"]
        trade_info = webhook_data["trade_info"]

        # e.g. "Order BUY @ 24.379 filled on LINKUSDT\nNew strategy position is 1"
        action = value.split(" ")[1].upper()  # Extract "BUY" or "SELL"

        # Extract "New strategy position is X"
        new_position_str = value.split("New strategy position is")[-1].strip().rstrip(".")
        new_position = float(new_position_str)

        # Determine trade_type
        if new_position == 0:
            trade_type = "EXIT"
        elif new_position < 0:
            trade_type = "SELL"
        else:
            trade_type = "BUY"

        ticker = trade_info["ticker"]        # e.g. "LINKUSDT"
        contracts = trade_info["contracts"]  # e.g. "1"
        leverage = trade_info["leverage"]    # e.g. "10"
        take_profit = trade_info.get("take_profit")  # e.g. "0.5"

        payload = {
            "symbol": ticker,
            "side": action,              # e.g. "BUY" or "SELL"
            "quantity": contracts,       # e.g. "1"
            "leverage": leverage,        # e.g. "10"
            "take_profit": take_profit,  # e.g. "0.5"
            "trade_type": trade_type,    # e.g. "BUY", "SELL", or "EXIT"
        }

        logger.info(f"Generated payload: {payload}")
        return payload

    except KeyError as e:
        logger.error(f"Missing key in webhook data: {e}")
        raise
    except ValueError as e:
        logger.error(f"Error parsing webhook data: {e}")
        raise
    except Exception as e:
        logger.error(f"Error parsing webhook data: {e}")
        raise
