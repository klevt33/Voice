"""
diagnose_browser.py

Live diagnostic script for browser connectivity issues.
Tests each layer of the browser interaction stack independently:
  1. Chrome DevTools connection (localhost:9222)
  2. Tab enumeration and active tab detection
  3. Page domain check (is Perplexity open?)
  4. CSS selector availability (input, submit, new-thread buttons)
  5. New thread initiation
  6. Topic submission (prime + submit)

Run this while Chrome is open on a Perplexity page.
"""

import sys
import os
import time
import logging

# Add project root to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException, InvalidSessionIdException,
    TimeoutException, NoSuchElementException
)
from urllib.parse import urlparse

# ── Config ────────────────────────────────────────────────────────────────────
DEBUGGER_ADDRESS = "localhost:9222"

# Pull selectors directly from config.py so this script always stays in sync
from config import CHATS
PERPLEXITY_CONFIG = CHATS["Perplexity"]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("diagnose")

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
INFO = "ℹ️  INFO"

# ── Helpers ───────────────────────────────────────────────────────────────────

def section(title: str):
    log.info("")
    log.info("=" * 60)
    log.info(f"  {title}")
    log.info("=" * 60)


def check(label: str, ok: bool, detail: str = ""):
    status = PASS if ok else FAIL
    msg = f"{status}  {label}"
    if detail:
        msg += f"  →  {detail}"
    log.info(msg)
    return ok


# ── Step 1: Connect to Chrome ─────────────────────────────────────────────────

def step1_connect() -> webdriver.Chrome | None:
    section("STEP 1 – Connect to Chrome via DevTools Protocol")
    try:
        opts = webdriver.ChromeOptions()
        opts.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
        driver = webdriver.Chrome(options=opts)
        check("Chrome DevTools connection", True, f"session={driver.session_id}")
        return driver
    except WebDriverException as e:
        check("Chrome DevTools connection", False, str(e))
        log.info("")
        log.info("  Possible causes:")
        log.info("  • Chrome is not running with --remote-debugging-port=9222")
        log.info("  • Another process is already using port 9222")
        log.info("  • ChromeDriver version mismatch with installed Chrome")
        log.info("")
        log.info("  Fix: launch Chrome with:")
        log.info('    chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\ChromeDebug"')
        return None


# ── Step 2: Enumerate tabs ────────────────────────────────────────────────────

def step2_tabs(driver: webdriver.Chrome) -> bool:
    section("STEP 2 – Enumerate open tabs")
    try:
        handles = driver.window_handles
        check("window_handles accessible", True, f"{len(handles)} tab(s) found")

        active = driver.current_window_handle
        log.info(f"  Active handle: {active}")

        for i, h in enumerate(handles):
            try:
                driver.switch_to.window(h)
                url = driver.current_url
                title = driver.title
                marker = " ← active" if h == active else ""
                log.info(f"  Tab {i}: [{h}]  {url}  |  '{title}'{marker}")
            except Exception as e:
                log.info(f"  Tab {i}: [{h}]  ERROR reading tab – {e}")

        # Restore active tab
        driver.switch_to.window(active)
        return True

    except Exception as e:
        check("Tab enumeration", False, str(e))
        return False


# ── Step 3: Page domain check ─────────────────────────────────────────────────

def step3_page_check(driver: webdriver.Chrome) -> bool:
    section("STEP 3 – Verify active tab is on Perplexity")
    try:
        current_url = driver.current_url
        current_domain = urlparse(current_url).netloc.replace("www.", "")
        expected_domain = urlparse(PERPLEXITY_CONFIG["url"]).netloc.replace("www.", "")

        log.info(f"  Current URL   : {current_url}")
        log.info(f"  Current domain: {current_domain}")
        log.info(f"  Expected domain: {expected_domain}")

        ok = (current_domain == expected_domain)
        check("Active tab is on correct domain", ok,
              f"got '{current_domain}', expected '{expected_domain}'")

        if not ok:
            log.info("")
            log.info("  The app's navigate_to_initial_page() will return (True, False)")
            log.info("  meaning it won't block startup, but new_thread and submit will")
            log.info("  likely fail because the selectors won't exist on this page.")
            log.info("")
            log.info("  Fix: switch the active Chrome tab to https://www.perplexity.ai/")

        return ok

    except Exception as e:
        check("Page domain check", False, str(e))
        log.info(f"  Exception type: {type(e).__name__}")
        log.info("  This often means the active tab has no valid execution context")
        log.info("  (e.g. a chrome:// page, a PDF, or a crashed tab).")
        return False


# ── Step 4: CSS selector availability ────────────────────────────────────────

def step4_selectors(driver: webdriver.Chrome) -> dict:
    section("STEP 4 – Check CSS selectors defined in config")
    results = {}
    wait = WebDriverWait(driver, 7)

    # Note: submit_button_selector is intentionally excluded here because it only
    # appears after text is typed into the input (it's dynamically rendered).
    # It is verified in Step 6 (prime + ready check) instead.
    selectors = {
        "Input field":        PERPLEXITY_CONFIG["css_selector_input"],
        "Attach files btn":   PERPLEXITY_CONFIG["attach_files_button_selector"],
        "New thread button":  PERPLEXITY_CONFIG["new_thread_button_selector"],
    }

    for label, sel in selectors.items():
        try:
            el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            visible = el.is_displayed()
            enabled = el.is_enabled()
            tag = el.tag_name
            outer = el.get_attribute("outerHTML")[:120].replace("\n", " ")
            check(label, True,
                  f"tag=<{tag}> visible={visible} enabled={enabled}")
            log.info(f"    HTML: {outer}")
            results[label] = True
        except TimeoutException:
            check(label, False, f"selector '{sel}' not found within 7s")
            results[label] = False
        except Exception as e:
            check(label, False, f"{type(e).__name__}: {e}")
            results[label] = False

    return results


# ── Step 5: New thread ────────────────────────────────────────────────────────

def step5_new_thread(driver: webdriver.Chrome) -> bool:
    section("STEP 5 – Click 'New Thread' button")
    sel = PERPLEXITY_CONFIG["new_thread_button_selector"]
    input_sel = PERPLEXITY_CONFIG["css_selector_input"]
    nav_url = PERPLEXITY_CONFIG["url"]
    wait = WebDriverWait(driver, 10)

    try:
        btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
        log.info(f"  Button found. Clicking via JavaScript...")
        driver.execute_script("arguments[0].click();", btn)

        # Wait for URL to settle back to base and input to be ready
        log.info("  Waiting for page to settle after new thread click...")
        wait.until(
            lambda d: EC.element_to_be_clickable((By.CSS_SELECTOR, input_sel))(d)
                      and nav_url.rstrip("/") in d.current_url.rstrip("/")
        )
        time.sleep(0.75)
        check("New thread initiated", True, f"URL: {driver.current_url}")
        return True

    except TimeoutException:
        check("New thread initiated", False,
              "Timed out waiting for page to settle after click")
        log.info("  The button may have been clicked but the page didn't transition.")
        log.info("  Check if Perplexity's UI changed (new_thread_button_selector may be stale).")
        return False
    except Exception as e:
        check("New thread initiated", False, f"{type(e).__name__}: {e}")
        return False


# ── Step 6: Prime + submit ────────────────────────────────────────────────────

def step6_submit(driver: webdriver.Chrome) -> bool:
    section("STEP 6 – Prime input field and verify submit button activates")
    import pyperclip
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    input_sel  = PERPLEXITY_CONFIG["css_selector_input"]
    submit_sel = PERPLEXITY_CONFIG["submit_button_selector"]
    wait_long  = WebDriverWait(driver, 10)
    wait_short = WebDriverWait(driver, 5)

    # --- Prime ---
    try:
        input_el = wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_sel)))
        log.info("  Input field is clickable. Priming with 'Waiting...'")

        # Clear
        tag = input_el.tag_name.lower()
        if tag == "div":
            driver.execute_script("arguments[0].innerHTML = '';", input_el)
        else:
            input_el.send_keys(Keys.CONTROL + "a", Keys.DELETE)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
            input_el
        )

        # Paste
        pyperclip.copy("Waiting...")
        modifier = Keys.CONTROL
        ActionChains(driver).click(input_el)\
            .key_down(modifier).send_keys("a").key_up(modifier).perform()
        time.sleep(0.05)
        ActionChains(driver).key_down(modifier).send_keys("v").key_up(modifier).perform()

        check("Input field primed", True)
    except Exception as e:
        check("Input field primed", False, f"{type(e).__name__}: {e}")
        return False

    # --- Wait for submit button to become clickable ---
    try:
        wait_short.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_sel)))
        check("Submit button became active after priming", True)
    except TimeoutException:
        check("Submit button became active after priming", False,
              "Submit button did not become clickable within 5s after priming")
        log.info("  This is the 'prime_input' / 'is_ready_for_input' failure point.")
        log.info("  The submit_button_selector may be stale or Perplexity's UI changed.")
        # Dump submit button state
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, submit_sel)
            log.info(f"  Elements matching '{submit_sel}': {len(btns)}")
            for b in btns:
                log.info(f"    enabled={b.is_enabled()} displayed={b.is_displayed()} "
                         f"html={b.get_attribute('outerHTML')[:100]}")
        except Exception:
            pass
        return False

    log.info("")
    log.info(f"  {WARN}  NOT actually submitting to avoid polluting your Perplexity thread.")
    log.info("  If you want to test a full submit, re-run with --submit flag.")

    # Clear the primed text so we don't leave garbage in the input
    try:
        input_el = driver.find_element(By.CSS_SELECTOR, input_sel)
        tag = input_el.tag_name.lower()
        if tag == "div":
            driver.execute_script("arguments[0].innerHTML = '';", input_el)
        else:
            input_el.send_keys(Keys.CONTROL + "a", Keys.DELETE)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
            input_el
        )
        log.info("  Input field cleared after test.")
    except Exception:
        pass

    return True


# ── Step 7: Full submit (optional) ───────────────────────────────────────────

def step7_full_submit(driver: webdriver.Chrome):
    section("STEP 7 – Full submit test (TEST MESSAGE)")
    import pyperclip
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    test_message = "[DIAGNOSTIC TEST] This is an automated connectivity test. Please ignore."
    input_sel  = PERPLEXITY_CONFIG["css_selector_input"]
    submit_sel = PERPLEXITY_CONFIG["submit_button_selector"]
    wait_long  = WebDriverWait(driver, 10)

    try:
        input_el = wait_long.until(EC.element_to_be_clickable((By.CSS_SELECTOR, input_sel)))
        tag = input_el.tag_name.lower()
        if tag == "div":
            driver.execute_script("arguments[0].innerHTML = '';", input_el)
        else:
            input_el.send_keys(Keys.CONTROL + "a", Keys.DELETE)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
            input_el
        )
        pyperclip.copy(test_message)
        modifier = Keys.CONTROL
        ActionChains(driver).click(input_el)\
            .key_down(modifier).send_keys("a").key_up(modifier).perform()
        time.sleep(0.05)
        ActionChains(driver).key_down(modifier).send_keys("v").key_up(modifier).perform()

        log.info("  Message pasted. Pressing Enter to submit...")
        input_el.send_keys(Keys.ENTER)
        time.sleep(2)
        check("Full submit executed", True, "Message sent to Perplexity")
    except Exception as e:
        check("Full submit executed", False, f"{type(e).__name__}: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    do_full_submit = "--submit" in sys.argv

    log.info("")
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║         Browser Connectivity Diagnostic Tool            ║")
    log.info("╚══════════════════════════════════════════════════════════╝")
    log.info(f"  Debugger address : {DEBUGGER_ADDRESS}")
    log.info(f"  Target URL       : {PERPLEXITY_CONFIG['url']}")
    log.info(f"  Full submit test : {'YES' if do_full_submit else 'NO (pass --submit to enable)'}")

    # Step 1
    driver = step1_connect()
    if not driver:
        log.info("\nCannot continue without a Chrome connection. Exiting.")
        sys.exit(1)

    try:
        # Step 2
        step2_tabs(driver)

        # Step 3
        on_correct_page = step3_page_check(driver)

        if not on_correct_page:
            # Try to switch to the Perplexity tab automatically
            log.info("")
            log.info("  Attempting to switch to the Perplexity tab automatically...")
            switched = False
            expected_domain = urlparse(PERPLEXITY_CONFIG["url"]).netloc.replace("www.", "")
            for h in driver.window_handles:
                try:
                    driver.switch_to.window(h)
                    domain = urlparse(driver.current_url).netloc.replace("www.", "")
                    if domain == expected_domain:
                        log.info(f"  Switched to Perplexity tab: {driver.current_url}")
                        switched = True
                        on_correct_page = True
                        break
                except Exception:
                    pass

            if not switched:
                log.info("  No Perplexity tab found. Skipping selector / interaction tests.")
                log.info("  Please open https://www.perplexity.ai/ in Chrome and re-run.")
                sys.exit(0)

        # Step 4
        selector_results = step4_selectors(driver)
        all_selectors_ok = all(selector_results.values())

        if not all_selectors_ok:
            log.info("")
            log.info("  One or more selectors failed. This is likely the root cause.")
            log.info("  Perplexity may have updated their UI. Check the HTML above and")
            log.info("  update the selectors in config.py → CHATS['Perplexity'].")
            log.info("  Skipping interaction tests.")
            sys.exit(0)

        # Step 5
        thread_ok = step5_new_thread(driver)

        # Step 6
        if thread_ok:
            submit_ok = step6_submit(driver)
        else:
            log.info("  Skipping submit test because new thread failed.")
            submit_ok = False

        # Step 7 (optional)
        if do_full_submit and submit_ok:
            step7_full_submit(driver)

        # ── Summary ──────────────────────────────────────────────────────────
        section("SUMMARY")
        log.info(f"  Chrome connection   : {PASS}")
        log.info(f"  Correct page        : {PASS if on_correct_page else FAIL}")
        log.info(f"  All selectors found : {PASS if all_selectors_ok else FAIL}")
        log.info(f"  New thread          : {PASS if thread_ok else FAIL}")
        log.info(f"  Prime + ready check : {PASS if submit_ok else FAIL}")
        log.info("")

        if on_correct_page and all_selectors_ok and thread_ok and submit_ok:
            log.info("  All checks passed. The browser stack looks healthy.")
            log.info("  If the main app is still failing, the issue is likely in")
            log.info("  the threading / queue layer (BrowserManager communication loop).")
        else:
            log.info("  One or more checks failed — see details above for the fix.")

    finally:
        log.info("")
        log.info("  Browser left open for manual inspection.")
        # Do NOT call driver.quit() — we're attached to the user's existing session


if __name__ == "__main__":
    main()
