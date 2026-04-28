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
import zipfile
import string
from datetime import datetime
warnings.filterwarnings("ignore")

model = whisper.load_model("base")

address = "0x721a6a568e78588e8226e8AeEeBa77f8ce7Db62e"

def transcribe(url):
    with open('.temp', 'wb') as f:
        f.write(requests.get(url).content)
    result = model.transcribe('.temp')
    return result["text"].strip()

def maybe_capture_screenshot(driver, label, enabled, output_dir):
    if not enabled:
        return None
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
    screenshot_path = os.path.join(output_dir, f"{timestamp}_{safe_label}.png")
    driver.save_screenshot(screenshot_path)
    print(f"Saved screenshot: {screenshot_path}")
    return screenshot_path

def detect_recaptcha_block_reason(driver):
    """
    Returns a human-readable block reason when reCAPTCHA is in a blocked/rate-limited
    state (e.g. "Try again later"), otherwise returns None.
    """
    driver.switch_to.default_content()

    challenge_frames = driver.find_elements(By.XPATH, "//iframe[contains(@title, 'recaptcha challenge')]")
    for frame in challenge_frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)

            message_selectors = [
                (By.CSS_SELECTOR, ".rc-doscaptcha-header-text"),
                (By.CSS_SELECTOR, ".rc-doscaptcha-body-text"),
                (By.CSS_SELECTOR, ".rc-audiochallenge-error-message"),
            ]
            message_parts = []
            for by, selector in message_selectors:
                for element in driver.find_elements(by, selector):
                    text = element.text.strip()
                    if text:
                        message_parts.append(text)

            if message_parts:
                combined = " | ".join(dict.fromkeys(message_parts))
                lowered = combined.lower()
                blocked_markers = [
                    "try again later",
                    "automated queries",
                    "can't process your request right now",
                    "unusual traffic",
                    "doscaptcha",
                ]
                if any(marker in lowered for marker in blocked_markers):
                    return combined
        except Exception:
            continue
        finally:
            driver.switch_to.default_content()

    return None

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

def has_audio_challenge(driver, timeout=10):
    """
    Returns True if the audio challenge button is present and clickable,
    False if reCAPTCHA has suppressed it (bot detection, rate limiting, etc.)
    """
    wait = WebDriverWait(driver, timeout)
    driver.switch_to.default_content()

    challenge_frames = driver.find_elements(
        By.XPATH, "//iframe[contains(@title, 'recaptcha challenge')]"
    )
    if not challenge_frames:
        print("No challenge iframe found - captcha may not have opened yet.")
        return False

    try:
        driver.switch_to.frame(challenge_frames[0])

        # Check for hard block first
        block_selectors = [
            ".rc-doscaptcha-header-text",
            ".rc-doscaptcha-body-text",
        ]
        for sel in block_selectors:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els and any(e.text.strip() for e in els):
                print(f"reCAPTCHA hard block detected: {els[0].text.strip()}")
                return False

        # Check audio button exists and is visible
        audio_buttons = driver.find_elements(By.ID, "recaptcha-audio-button")
        if not audio_buttons:
            print("Audio button not present in challenge iframe.")
            return False

        is_visible = audio_buttons[0].is_displayed()
        is_enabled = audio_buttons[0].is_enabled()
        print(f"Audio button found - visible: {is_visible}, enabled: {is_enabled}")
        return is_visible and is_enabled

    except Exception as e:
        print(f"Error checking audio challenge availability: {e}")
        return False
    finally:
        driver.switch_to.default_content()

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
    address_input.send_keys(address)

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
    screenshots_enabled = os.getenv("CAPTURE_SCREENSHOTS", "true" if is_ci else "false").lower() == "true"
    screenshots_dir = os.getenv("SCREENSHOT_DIR", "ci-screenshots")

    def create_proxy_auth_extension(host, port, username, password):
        manifest = json.dumps({
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Proxy Auth",
            "permissions": ["proxy", "tabs", "unlimitedStorage", "storage",
                            "<all_urls>", "webRequest", "webRequestBlocking"],
            "background": {"scripts": ["background.js"]},
            "minimum_chrome_version": "22.0.0"
        })
        background = string.Template("""
        var config = {
            mode: "fixed_servers",
            rules: {
                singleProxy: { scheme: "http", host: "$host", port: parseInt("$port") },
                bypassList: []
            }
        };
        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
        chrome.webRequest.onAuthRequired.addListener(
            function(details) {
                return { authCredentials: { username: "$user", password: "$pass" } };
            },
            { urls: ["<all_urls>"] },
            ["blocking"]
        );
        """).substitute(host=host, port=port, user=username, password=password)

        ext_path = ".proxy_auth_ext.zip"
        with zipfile.ZipFile(ext_path, "w") as zp:
            zp.writestr("manifest.json", manifest)
            zp.writestr("background.js", background)
        return ext_path

    chrome_options = Options()
    if is_ci:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")

    # Bright Data proxy
    brightdata_host = "brd.superproxy.io"
    brightdata_port = "33335"
    brightdata_user = os.getenv("BRIGHTDATA_USERNAME", "")
    brightdata_pass = os.getenv("BRIGHTDATA_PASSWORD", "")

    chrome_options.add_argument(f"--proxy-server=http://{brightdata_host}:{brightdata_port}")
    chrome_options.add_argument("--ignore-certificate-errors")

    if brightdata_user and brightdata_pass:
        ext = create_proxy_auth_extension(
            brightdata_host,
            brightdata_port,
            brightdata_user,
            brightdata_pass,
        )
        chrome_options.add_extension(ext)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
  
    try:
        driver.get("https://sepolia-faucet.pk910.de/#/")
        maybe_capture_screenshot(driver, "page_loaded", screenshots_enabled, screenshots_dir)
        captcha_provider = detect_captcha_provider(driver)
        print(f"Detected captcha provider: {captcha_provider}")
        maybe_capture_screenshot(driver, f"captcha_{captcha_provider}", screenshots_enabled, screenshots_dir)

        if captcha_provider == "hcaptcha":
            print("Stopping flow because hCaptcha is not supported by this script.")
            maybe_capture_screenshot(driver, "stopped_hcaptcha", screenshots_enabled, screenshots_dir)
            raise SystemExit(0)

        if is_ci and not run_full_flow:
            print("CI mode: skipping captcha/mining flow. Set RUN_FULL_FLOW=true to run full automation.")
            maybe_capture_screenshot(driver, "ci_skipped_full_flow", screenshots_enabled, screenshots_dir)
        else:
            print("Running full flow")
            click_checkbox(driver)
            maybe_capture_screenshot(driver, "after_checkbox_click", screenshots_enabled, screenshots_dir)
            block_reason = detect_recaptcha_block_reason(driver)
            if block_reason:
                print(f"Detected reCAPTCHA block: {block_reason}")
                maybe_capture_screenshot(driver, "recaptcha_blocked_after_checkbox", screenshots_enabled, screenshots_dir)
                raise SystemExit(0)
            time.sleep(1)

            if not has_audio_challenge(driver):
                print("Audio challenge not available - stopping. Try a different IP or session.")
                maybe_capture_screenshot(driver, "audio_not_available", screenshots_enabled, screenshots_dir)
                raise SystemExit(0)

            request_audio_version(driver)
            maybe_capture_screenshot(driver, "after_audio_request", screenshots_enabled, screenshots_dir)
            block_reason = detect_recaptcha_block_reason(driver)
            if block_reason:
                print(f"Detected reCAPTCHA block: {block_reason}")
                maybe_capture_screenshot(driver, "recaptcha_blocked_after_audio_request", screenshots_enabled, screenshots_dir)
                raise SystemExit(0)
            time.sleep(1)
            if not solve_audio_captcha(driver):
                print("Stopping flow because audio captcha could not be solved.")
                block_reason = detect_recaptcha_block_reason(driver)
                if block_reason:
                    print(f"Detected reCAPTCHA block: {block_reason}")
                    maybe_capture_screenshot(driver, "recaptcha_blocked_during_audio", screenshots_enabled, screenshots_dir)
                maybe_capture_screenshot(driver, "audio_captcha_failed", screenshots_enabled, screenshots_dir)
                raise SystemExit(0)
            time.sleep(5)
            enter_address(driver)
            maybe_capture_screenshot(driver, "after_enter_address", screenshots_enabled, screenshots_dir)
            time.sleep(1)
            start_mining(driver)
            maybe_capture_screenshot(driver, "after_start_mining_click", screenshots_enabled, screenshots_dir)

            while True:
                time.sleep(100)
                balance = check_balance(driver)
                print(balance)
                if balance == "2.500 SepETH":
                    break

            claim_reward(driver)
            maybe_capture_screenshot(driver, "after_claim_reward", screenshots_enabled, screenshots_dir)
    except Exception:
        maybe_capture_screenshot(driver, "unhandled_exception", screenshots_enabled, screenshots_dir)
        raise
    finally:
        driver.quit()