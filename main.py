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

def detect_captcha_provider(driver):
    driver.switch_to.default_content()
    wait = WebDriverWait(driver, 15)

    def check_provider(_driver):
        # hCaptcha indicators
        hcaptcha_selectors = [
            "iframe[src*='hcaptcha.com']",
            "iframe[title*='hCaptcha']",
            "script[src*='hcaptcha.com']",
            ".h-captcha",
        ]
        for selector in hcaptcha_selectors:
            if _driver.find_elements(By.CSS_SELECTOR, selector):
                return "hcaptcha"

        # reCAPTCHA indicators
        recaptcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[title*='reCAPTCHA']",
            "script[src*='recaptcha']",
            ".g-recaptcha",
            "textarea#g-recaptcha-response",
        ]
        for selector in recaptcha_selectors:
            if _driver.find_elements(By.CSS_SELECTOR, selector):
                return "recaptcha"

        page_html = _driver.page_source.lower()
        if "hcaptcha" in page_html:
            return "hcaptcha"
        if "recaptcha" in page_html:
            return "recaptcha"
        return None

    try:
        return wait.until(check_provider)
    except TimeoutException:
        return "unknown"

def click_checkbox(driver):
    wait = WebDriverWait(driver, 10)
    driver.switch_to.default_content()
    recaptcha_iframe = wait.until(
        EC.presence_of_element_located((By.XPATH, "//iframe[@title='reCAPTCHA']"))
    )
    driver.switch_to.frame(recaptcha_iframe)
    wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor-label"))).click()
    driver.switch_to.default_content()

def click_at_page_coordinates(driver, x, y):
    driver.switch_to.default_content()
    script = """
    const x = arguments[0];
    const y = arguments[1];
    const target = document.elementFromPoint(x, y);
    if (!target) return false;

    const eventOptions = {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        view: window
    };

    target.dispatchEvent(new MouseEvent("mousemove", eventOptions));
    target.dispatchEvent(new MouseEvent("mousedown", eventOptions));
    target.dispatchEvent(new MouseEvent("mouseup", eventOptions));
    target.dispatchEvent(new MouseEvent("click", eventOptions));
    return true;
    """
    return bool(driver.execute_script(script, x, y))

def request_audio_version(driver):
    wait = WebDriverWait(driver, 20)
    driver.switch_to.default_content()
    challenge_iframe = wait.until(
        EC.presence_of_element_located((By.XPATH, "//iframe[contains(@title, 'recaptcha challenge')]"))
    )
    driver.switch_to.frame(challenge_iframe)
    audio_button = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-audio-button")))
    try:
        audio_button.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", audio_button)

def solve_audio_captcha(driver):
    wait = WebDriverWait(driver, 20)

    try:
        audio_source = wait.until(EC.presence_of_element_located((By.ID, "audio-source")))
    except TimeoutException:
        # reCAPTCHA can suppress the audio challenge in bot-like sessions (headless/CI/VPN).
        status_locators = [
            (By.CLASS_NAME, "rc-doscaptcha-header-text"),
            (By.CLASS_NAME, "rc-audiochallenge-error-message"),
        ]
        for locator in status_locators:
            try:
                status_element = driver.find_element(*locator)
                status_text = status_element.text.strip()
                if status_text:
                    print(f"Audio challenge unavailable: {status_text}")
                    return False
            except Exception:
                continue

        print("Audio challenge unavailable: #audio-source did not appear in time.")
        return False

    text = transcribe(audio_source.get_attribute("src"))
    answer_input = wait.until(EC.element_to_be_clickable((By.ID, "audio-response")))
    answer_input.clear()
    answer_input.send_keys(text)
    wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-verify-button"))).click()
    return True

def enter_address(driver):
    wait = WebDriverWait(driver, 20)
    driver.switch_to.default_content()

    input_locators = [
        (By.CSS_SELECTOR, ".faucet-inputs input.form-control"),
        (By.ID, "address"),
        (By.CSS_SELECTOR, "input[placeholder*='ETH address']"),
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
    address_input.send_keys("0xa7D082d8C5952d2BCE4E8984f5B467429346d6F5")

def start_mining(driver):
    wait = WebDriverWait(driver, 20)
    driver.switch_to.default_content()

    start_button_locators = [
        (By.CSS_SELECTOR, ".faucet-actions button.start-action"),
        (By.CSS_SELECTOR, "button.btn.btn-success.start-action"),
        (By.XPATH, "//button[normalize-space()='Start Mining']"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Start Mining')]"),
    ]

    start_button = None
    for locator in start_button_locators:
        try:
            start_button = wait.until(EC.element_to_be_clickable(locator))
            if start_button.is_displayed() and start_button.is_enabled():
                break
            start_button = None
        except TimeoutException:
            continue

    if start_button is None:
        raise TimeoutException("Start mining button not found with known selectors")

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", start_button)

    try:
        start_button.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", start_button)
    except Exception:
        # Last-resort DOM lookup from the HTML structure provided by the page.
        clicked = driver.execute_script("""
            const btn = document.querySelector('.faucet-actions button.start-action')
                || Array.from(document.querySelectorAll('button')).find(
                    b => (b.textContent || '').trim().includes('Start Mining')
                );
            if (!btn) return false;
            btn.scrollIntoView({block: 'center'});
            btn.click();
            return true;
        """)
        if not clicked:
            raise TimeoutException("Start mining button was located but could not be clicked")

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
    is_ci = os.getenv("CI", "").lower() == "true"
    run_full_flow = os.getenv("RUN_FULL_FLOW", "false").lower() == "true"

    chrome_options = Options()
    if is_ci:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
  
    try:
        driver.get("https://sepolia-faucet.pk910.de/#/")
        captcha_provider = detect_captcha_provider(driver)
        print(f"Detected captcha provider: {captcha_provider}")

        if captcha_provider == "hcaptcha":
            print("Stopping flow because hCaptcha is not supported by this script.")
            raise SystemExit(0)

        if is_ci and not run_full_flow:
            print("CI mode: skipping captcha/mining flow. Set RUN_FULL_FLOW=true to run full automation.")
        else:
            print("Running full flow")
            click_checkbox(driver)
            time.sleep(1)
            request_audio_version(driver)
            time.sleep(1)
            if not solve_audio_captcha(driver):
                print("Stopping flow because audio captcha could not be solved.")
                raise SystemExit(0)
            time.sleep(5)
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
    finally:
        driver.quit()