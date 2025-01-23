import logging

logger = logging.getLogger("utils")
logging.basicConfig(level=logging.DEBUG)

def parse_webhook_to_payload(webhook_data):
    """
    Parse the incoming webhook data into a Binance order payload and determine trade type.
    """
    try:
        logger.info(f"Parsing webhook data: {webhook_data}")

        # Extract fields from webhook data
        value = webhook_data["value"]
        trade_info = webhook_data["trade_info"]

        # Extract action (BUY/SELL)
        action = value.split(" ")[1].upper()  # Extract "BUY" or "SELL"

        # Extract strategy position (New position: 0 for exit, <0 for sell, >0 for buy)
        new_position_str = value.split("New strategy position is")[-1].strip().rstrip(".")
        new_position = float(new_position_str)  # Change to float to handle decimals

        # Determine trade type
        if new_position == 0:
            trade_type = "EXIT"
        elif new_position < 0:
            trade_type = "SELL"
        else:
            trade_type = "BUY"

        # Prepare payload
        ticker = trade_info["ticker"]
        contracts = trade_info["contracts"]
        leverage = trade_info["leverage"]
        take_profit = trade_info.get("take_profit")  # Optional

        payload = {
            "symbol": ticker,
            "side": action,
            "quantity": contracts,
            "leverage": leverage,
            "take_profit": take_profit,
            "trade_type": trade_type,  # Add trade type to payload
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
