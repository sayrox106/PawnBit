from selenium.webdriver.remote.webdriver import WebDriver
from selenium import webdriver


# Converts a chess character into an int
# Examples: a -> 1, b -> 2, h -> 8, etc.
def char_to_num(char):
    return ord(char) - ord("a") + 1


from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver

# ── ATTACH TO SESSION (Selenium 4) ─────────────────────────
class ReusableWebDriver(RemoteWebDriver):
    """
    Subclass that bypasses start_session to attach to an existing
    browser instance using its executor_url and session_id.
    """
    def start_session(self, capabilities, browser_profile=None):
        # Do nothing - we already have a session
        pass

def attach_to_session(executor_url, session_id):
    """
    Attaches to a running browser session.
    Returns the WebDriver instance.
    """
    options = ChromeOptions()
    # Simply instantiate our subclass with the known executor,
    # options, and manually assign the session_id.
    driver = ReusableWebDriver(command_executor=executor_url, options=options)
    driver.session_id = session_id
    return driver
