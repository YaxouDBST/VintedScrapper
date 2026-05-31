import os
import logging
import asyncio
from typing import Dict, List, Tuple, Optional
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Force platform override for Playwright on Ubuntu 26.04 before import/launch
os.environ["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = "ubuntu24.04-x64"

logger = logging.getLogger("VintedBot.SessionManager")

class VintedSessionManager:
    """Handles Phase 1: Session initialization lifecycle.
    Launches a headless stealth browser to navigate Vinted, solve initial challenges,
    and extract fresh cookies, User-Agent, and Bearer authorization tokens.
    """
    def __init__(self, vinted_domain: str = "https://www.vinted.fr"):
        self.vinted_domain = vinted_domain.rstrip('/')
        self.cookies: List[Dict] = []
        self.user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
        self.access_token: Optional[str] = None
        self.cookie_dict: Dict[str, str] = {}

    async def initialize_session(self, retries: int = 3) -> bool:
        """Launches the heavy Playwright stealth browser to fetch cookies and authorization tokens."""
        logger.info(f"Initializing new stealth browser session for {self.vinted_domain}...")
        
        for attempt in range(1, retries + 1):
            try:
                # Wrap playwright in Stealth context manager
                async with Stealth().use_async(async_playwright()) as p:
                    # Launch native Chromium
                    browser = await p.chromium.launch(headless=True)
                    
                    # Create realistic browser context
                    context = await browser.new_context(
                        user_agent=self.user_agent,
                        viewport={"width": 1280, "height": 800},
                        device_scale_factor=1,
                        is_mobile=False,
                        has_touch=False
                    )
                    
                    page = await context.new_page()
                    
                    # To guarantee cookie extraction, we navigate to a search catalog page which
                    # triggers Vinted's complete state/cookie initialization
                    target_url = f"{self.vinted_domain}/catalog?search_text=nike"
                    logger.debug(f"Attempt {attempt}/{retries}: Loading page {target_url}...")
                    
                    await page.goto(target_url, wait_until="networkidle", timeout=60000)
                    
                    # Small grace sleep to allow any final async calls
                    await asyncio.sleep(2)
                    
                    # Extract page details
                    title = await page.title()
                    logger.debug(f"Successfully loaded Vinted FR homepage. Page Title: {title}")
                    
                    # Extract and structure cookies
                    raw_cookies = await context.cookies()
                    self.cookies = raw_cookies
                    self.cookie_dict = {c["name"]: c["value"] for c in raw_cookies}
                    
                    # Extract access_token_web (JWT) from cookies
                    self.access_token = self.cookie_dict.get("access_token_web")
                    
                    # Verify that we got essential cookies
                    essential_cookies = ["anon_id", "access_token_web", "datadome"]
                    missing = [c for c in essential_cookies if c not in self.cookie_dict]
                    
                    if missing:
                        logger.warning(f"Session initialized but missing some cookies: {missing}")
                    else:
                        logger.info("Session initialized successfully. All essential cookies extracted.")
                    
                    # Close browser immediately after cookie extraction
                    await browser.close()
                    logger.info("Heavy browser closed. Session initialization Phase 1 complete.")
                    return True
                    
            except Exception as e:
                logger.error(f"Attempt {attempt}/{retries} failed to initialize session: {e}")
                if attempt < retries:
                    wait_time = attempt * 5
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.critical("Failed to initialize session after all attempts.")
                    return False
        return False

    def get_cookies_and_headers(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Returns the cookies and request headers populated with the session data for Phase 2."""
        cookie_data = {}
        for c in self.cookies:
            # Match domain structure (e.g. .vinted.fr)
            cookie_data[c["name"]] = c["value"]
            
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.vinted_domain}/catalog?search_text=nike",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
        
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            
        return cookie_data, headers
