import logging

logger = logging.getLogger("utils")
logging.basicConfig(level=logging.DEBUG)

def parse_webhook_to_payload(webhook_data):
    """
    Parse the incoming TradingView webhook data.
    new_position: 0 -> EXIT; <0 -> SELL; >0 -> BUY.
    The 'side' is derived automatically from 'new_position'.
    """
    try:
        logger.info(f"Parsing webhook data: {webhook_data}")

        value = webhook_data["value"]
        trade_info = webhook_data["trade_info"]
        timestamp = webhook_data.get("timestamp")
        if not timestamp:
            raise ValueError("Missing 'timestamp' in webhook data.")

        # e.g., "Order BUY @ 24.379 filled on LINKUSDT\nNew strategy position is -1."
        # We'll IGNORE the second word ("BUY"/"SELL") to prevent contradictions.

        # 1) Identify new_position
        if "New strategy position is" in value:
            remainder = value.split("New strategy position is")[-1]
            new_position_str = remainder.strip().rstrip(".")
            new_position = float(new_position_str)
        else:
            new_position = 0.0

        # 2) Determine trade_type from new_position
        if new_position == 0:
            trade_type = "EXIT"
            side = "BUY"  # side not really used for EXIT, but just set something
        elif new_position < 0:
            trade_type = "SELL"
            side = "SELL"
        else:
            trade_type = "BUY"
            side = "BUY"

        ticker = trade_info["ticker"]
        contracts = trade_info["contracts"]
        leverage = trade_info.get("leverage", "1")
        take_profit = trade_info.get("take_profit")

        payload = {
            "symbol": ticker,
            "side": side,              # now in sync with new_position
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
        logger.error(f"Error parsing webhook data: {e}", exc_info=True)
        raise
