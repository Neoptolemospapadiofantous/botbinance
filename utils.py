import logging

logger = logging.getLogger("utils")
logging.basicConfig(level=logging.DEBUG)

def parse_webhook_to_payload(webhook_data):
    """
    Parse the incoming webhook data into a standardized Binance order payload and determine trade type.
    
    Expected format:
      {
        "value": "Order BUY @ 24.379 filled on LINKUSDT\nNew strategy position is 1",
        "trade_info": {
            "ticker": "LINKUSDT",
            "contracts": "1",
            "leverage": "10",
            "take_profit": "0.5"   // percentage for normal trades
        },
        "timestamp": "1681253674.000"
      }
    """
    try:
        logger.info(f"Parsing webhook data: {webhook_data}")

        value = webhook_data["value"]
        trade_info = webhook_data["trade_info"]

        # Extract the timestamp.
        timestamp = webhook_data.get("timestamp")
        if timestamp is None:
            raise ValueError("Webhook payload is missing the 'timestamp' field.")

        action = value.split(" ")[1].upper()  # "BUY" or "SELL"

        # Extract "New strategy position is X" and convert to float.
        new_position_str = value.split("New strategy position is")[-1].strip().rstrip(".")
        new_position = float(new_position_str)

        # Determine trade type.
        if new_position == 0:
            trade_type = "EXIT"
        elif new_position < 0:
            trade_type = "SELL"
        else:
            trade_type = "BUY"

        ticker = trade_info["ticker"]
        contracts = trade_info["contracts"]
        leverage = trade_info["leverage"]
        take_profit = trade_info.get("take_profit")  # For normal trades

        payload = {
            "symbol": ticker,
            "side": action,
            "quantity": contracts,
            "leverage": leverage,
            "take_profit": take_profit,
            "trade_type": trade_type,
            "timestamp": timestamp
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
