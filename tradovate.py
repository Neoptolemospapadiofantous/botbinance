import logging
import os
import json
import time
import re
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()

# Tradovate Website Credentials
USERNAME = os.getenv("TRADOVATE_USERNAME")
PASSWORD = os.getenv("TRADOVATE_PASSWORD")

# Initialize Flask app
app = Flask(__name__)
logger = logging.getLogger("tradovate")
logging.basicConfig(level=logging.INFO)

# Selenium WebDriver Setup
def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode for performance
    options.add_argument("--start-maximized")  
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=options)
    driver.get("https://trader.tradovate.com/welcome")
    return driver

def login(driver):
    try:
        wait = WebDriverWait(driver, 15)
        
        time.sleep(5)  # Allow time for page to load
        logger.info("Checking page source for debugging")
        
        username_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text']")))
        username_field.send_keys(USERNAME)

        password_field = driver.find_element(By.XPATH, "//input[@type='password']")
        password_field.send_keys(PASSWORD)
        password_field.send_keys(Keys.RETURN)
        
        time.sleep(5)  # Allow for page transition
        wait.until(EC.url_contains("trading-mode"))
        logger.info("Navigated to Trading Mode page.")
        
        simulation_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[span[contains(text(),'Access Simulation')]]")))
        simulation_button.click()
        
        wait.until(EC.url_to_be("https://trader.tradovate.com/"))
        logger.info("Successfully logged in to Tradovate.")

    except Exception as e:
        logger.error(f"Login failed: {e}")
        driver.quit()
        raise

# Start browser and login before waiting for signals
driver = setup_driver()
login(driver)

# Click Buy or Sell Button based on position size
def execute_trade(position_size):
    try:
        if position_size > 0:
            buy_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'btn-success') and contains(text(), 'Buy Mkt')]"))
            )
            buy_button.click()
            logger.info("Buy order executed successfully.")
        elif position_size < 0:
            sell_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'btn-danger') and contains(text(), 'Sell Mkt')]"))
            )
            sell_button.click()
            logger.info("Sell order executed successfully.")

        time.sleep(3)  # Allow action to complete
    except Exception as e:
        logger.error(f"Error executing trade: {e}")

# Webhook Route
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        # Extract position size and sanitize input
        position_line = data["value"].split("New strategy position is ")[-1]
        position_size = int(re.sub(r"[^\d-]", "", position_line.strip()))  # Remove unwanted characters

        if position_size != 0:
            execute_trade(position_size)

        return jsonify({"message": f"Trade executed for position {position_size}", "status": "success"})
    
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({"message": str(e), "status": "error"}), 500

# Ensure Selenium WebDriver is properly closed when script ends
import atexit
@atexit.register
def cleanup():
    driver.quit()
    logger.info("WebDriver closed successfully.")

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8080)
