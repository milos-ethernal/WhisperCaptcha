# Import the required modules
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
import time
import json
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
import requests
import os
import whisper
import warnings
warnings.filterwarnings("ignore")

model = whisper.load_model("base")

def transcribe(url):
    with open('.temp', 'wb') as f:
        f.write(requests.get(url).content)
    result = model.transcribe('.temp')
    return result["text"].strip()

def click_checkbox(driver):
    wait = WebDriverWait(driver, 10)
    driver.switch_to.default_content()
    recaptcha_iframe = wait.until(
        EC.presence_of_element_located((By.XPATH, "//iframe[@title='reCAPTCHA']"))
    )
    driver.switch_to.frame(recaptcha_iframe)
    wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor-label"))).click()
    driver.switch_to.default_content()

def request_audio_version(driver):
    wait = WebDriverWait(driver, 10)
    driver.switch_to.default_content()
    challenge_iframe = wait.until(
        EC.presence_of_element_located((By.XPATH, "//iframe[contains(@title, 'recaptcha challenge')]"))
    )
    driver.switch_to.frame(challenge_iframe)
    wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-audio-button"))).click()

def solve_audio_captcha(driver):
    wait = WebDriverWait(driver, 10)
    text = transcribe(wait.until(EC.presence_of_element_located((By.ID, "audio-source"))).get_attribute('src'))
    wait.until(EC.element_to_be_clickable((By.ID, "audio-response"))).send_keys(text)
    wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-verify-button"))).click()

def enter_address(driver):
    wait = WebDriverWait(driver, 20)
    driver.switch_to.default_content()

    input_locators = [
        (By.XPATH, "/html/body/div[2]/div/div/div/div[3]/div/div[2]/input"),
        (By.ID, "address"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]

    address_input = None
    for locator in input_locators:
        try:
            address_input = wait.until(EC.element_to_be_clickable(locator))
            break
        except TimeoutException:
            continue

    if address_input is None:
        raise TimeoutException("Address input field not found with known selectors")

    address_input.clear()
    address_input.send_keys("0x3e4e4f63aFF7715e9909704F45775f6b7AF3C3d2")

    next_button_locators = [
        (By.ID, "next"),
        (By.XPATH, "//button[@id='next']"),
        (By.XPATH, "/html/body/div[2]/div/div/div/div[3]/div/div[2]/button"),
        (By.XPATH, "//button[contains(., 'Start Mining')]"),
    ]

    next_button = None
    for locator in next_button_locators:
        try:
            next_button = wait.until(EC.element_to_be_clickable(locator))
            break
        except TimeoutException:
            continue

    if next_button is None:
        raise TimeoutException("Next button not found with known selectors")

    try:
        next_button.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", next_button)

def start_mining(driver):
    wait = WebDriverWait(driver, 10)
    wait.until(
        EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div/div/div/div[3]/div/div[2]/div[2]/button"))
    ).click()

def check_balance(driver):
    wait = WebDriverWait(driver, 10)
    balance = wait.until(
        EC.presence_of_element_located((By.XPATH, "/html/body/div[2]/div/div/div/div[3]/div/div[1]/div/div[3]/div[1]/div[2]"))
    ).text
    return balance

def claim_reward(driver):
    wait = WebDriverWait(driver, 10)
    wait.until(
        EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div/div/div/div[3]/div/div[2]/button"))
    ).click()

if __name__ == "__main__":
    chrome_options = Options()
    if os.getenv("CI", "").lower() == "true":
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
  
    driver.get("https://sepolia-faucet.pk910.de/#/")
    click_checkbox(driver)
    time.sleep(1)
    request_audio_version(driver)
    time.sleep(1)
    solve_audio_captcha(driver)
    time.sleep(10)
    enter_address(driver)
    time.sleep(1)
    start_mining(driver)
    
    while True:
        time.sleep(100)
        balance = check_balance(driver)
        print(balance)
        if balance == "2.500 SepETH":
            break

    claim_reward(driver)