import time
import random
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional
import tls_client

from db_manager import DatabaseManager, ItemRepository
from session_manager import VintedSessionManager
from discord_notifier import DiscordNotifier

logger = logging.getLogger("VintedBot.Worker")

class VintedScraperWorker:
    """Orchestrates Phase 2 lightweight monitoring loops.
    Uses tls-client for request fingerprinting, follows the Zero-Item-Endpoint rule,
    maintains databases, schedules jittered delays, and handles automated token rotation.
    """
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.db_manager: Optional[DatabaseManager] = None
        self.item_repository: Optional[ItemRepository] = None
        self.session_manager: Optional[VintedSessionManager] = None
        self.notifier: Optional[DiscordNotifier] = None
        
        self.tls_session: Optional[tls_client.Session] = None
        self.request_count = 0
        self.rotation_threshold = 25
        self.is_running = False
        
        self.load_config()
        self.init_components()

    def load_config(self):
        """Loads configuration parameters from config.json."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file {self.config_path} not found.")
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        
        # Set a randomized rotation threshold between 25 and 30 requests
        limits = self.config.get("request_limits", {})
        min_lim = limits.get("rotation_frequency_min", 25)
        max_lim = limits.get("rotation_frequency_max", 30)
        self.rotation_threshold = random.randint(min_lim, max_lim)
        logger.info(f"Configuration loaded. Next token rotation scheduled in {self.rotation_threshold} successful requests.")

    def init_components(self):
        """Initializes database, notifier, and session manager components."""
        # Database Manager & Item Repository
        self.db_manager = DatabaseManager()
        self.item_repository = ItemRepository(self.db_manager)
        
        # Discord Notifier
        webhook_url = self.config.get("discord_webhook_url", "")
        self.notifier = DiscordNotifier(webhook_url)
        
        # Session Manager
        domain = self.config.get("vinted_domain", "https://www.vinted.fr")
        self.session_manager = VintedSessionManager(vinted_domain=domain)

    async def rotate_tokens(self) -> bool:
        """Executes Phase 1: Launches heavy browser to renew cookies and headers."""
        logger.info("🔄 Initiating Token Rotation sequence...")
        success = await self.session_manager.initialize_session()
        
        if success:
            logger.info("🔄 Session successfully rotated. Instantiating fresh tls-client session...")
            
            # Spin up a lightweight tls-client session mimicking Chrome 120
            self.tls_session = tls_client.Session(
                client_identifier="chrome_120",
                random_tls_extension_order=True
            )
            
            # Load fresh cookies and headers into tls-client
            cookies, headers = self.session_manager.get_cookies_and_headers()
            
            for name, value in cookies.items():
                # We apply the cookies to both main domain and subdomains to prevent missing cookies
                self.tls_session.cookies.set(name, value, domain=".vinted.fr", path="/")
                
            self.tls_session.headers.update(headers)
            
            # Reset request counters and randomize next threshold
            self.request_count = 0
            limits = self.config.get("request_limits", {})
            min_lim = limits.get("rotation_frequency_min", 25)
            max_lim = limits.get("rotation_frequency_max", 30)
            self.rotation_threshold = random.randint(min_lim, max_lim)
            logger.info(f"🔄 Token rotation complete. Reset request count. Next rotation threshold: {self.rotation_threshold} requests.")
            return True
        else:
            logger.critical("❌ Token rotation failed! Unable to acquire session credentials.")
            return False

    def execute_api_request(self, params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Performs a lightweight request to Vinted catalog search API using tls-client."""
        if not self.tls_session:
            logger.error("TLS Session is not initialized. Cannot execute requests.")
            return None

        url = f"{self.session_manager.vinted_domain}/api/v2/catalog/items"
        logger.debug(f"Sending API request to {url} with params: {params}...")
        
        try:
            response = self.tls_session.get(url, params=params, timeout_seconds=15)
            
            if response.status_code == 200:
                self.request_count += 1
                logger.debug(f"API request success (200 OK). Successful requests in current session: {self.request_count}/{self.rotation_threshold}")
                
                try:
                    payload = response.json()
                    return payload.get("items", [])
                except Exception as e:
                    logger.error(f"Failed to parse JSON catalog payload: {e}")
                    return None
                    
            elif response.status_code in (403, 429):
                logger.warning(f"⚠️ API blocked with HTTP {response.status_code} ({'Rate Limited' if response.status_code == 429 else 'Forbidden'}).")
                return "ROTATE"
                
            else:
                logger.error(f"Failed API request: HTTP {response.status_code}. Response: {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"Network error executing catalog API request: {e}")
            return None

    async def monitor_iteration(self) -> bool:
        """Runs a single monitoring cycle across all search criteria."""
        search_criteria: List[Dict[str, Any]] = self.config.get("search_criteria", [])
        
        if not search_criteria:
            logger.warning("No search criteria configured in config.json. Monitoring idle.")
            return True

        for criteria in search_criteria:
            name = criteria.get("name", "Unnamed Search")
            params = criteria.get("params", {})
            
            logger.info(f"🔍 Scraping criteria: '{name}' (Search Text: '{params.get('search_text')}')")
            
            # Check if token rotation is due BEFORE making a request
            if self.request_count >= self.rotation_threshold:
                logger.info(f"🔄 Request limit ({self.rotation_threshold}) reached. Triggering proactive token rotation.")
                rotation_success = await self.rotate_tokens()
                if not rotation_success:
                    logger.error("Token rotation failed. Aborting current iteration.")
                    return False
            
            # Execute request
            items = self.execute_api_request(params)
            
            if items == "ROTATE":
                # Encounted 403 or 429 block, trigger immediate session rotation
                logger.warning("🚨 Anti-bot block encountered. Initiating immediate emergency token rotation...")
                rotation_success = await self.rotate_tokens()
                if not rotation_success:
                    logger.error("Emergency token rotation failed. Stopping scraper loop.")
                    return False
                # Try executing the request again with fresh credentials
                logger.info("🔄 Retrying search request with fresh session...")
                items = self.execute_api_request(params)
                if items in ("ROTATE", None):
                    logger.error("Failed to execute request even after emergency token rotation. Skipping criteria.")
                    continue
            
            if items is None:
                logger.error(f"Skipping search criteria '{name}' due to API request failure.")
                continue

            # Process scraped items
            new_listings_count = 0
            duplicates_count = 0
            
            for item in items:
                item_id = item.get("id")
                if not item_id:
                    continue
                
                # Check for rapid indexed lookup in Database Manager
                if self.item_repository.exists(item_id):
                    duplicates_count += 1
                    logger.debug(f"Duplicate caught: Item ID {item_id} already indexed.")
                    continue
                
                # Extract all properties from catalog search payload (Zero-Item-Endpoint rule)
                title = item.get("title", "No Title")
                brand = item.get("brand_title") or "N/A"
                size = item.get("size_title") or ""
                condition = item.get("status") or "N/A"
                url = item.get("url", "#")
                
                # Apply size filter if configured (e.g. ['S', 'M'])
                allowed_sizes = self.config.get("allowed_sizes", [])
                if allowed_sizes:
                    clean_size = size.strip().upper() if size else ""
                    allowed_sizes_upper = [s.strip().upper() for s in allowed_sizes]
                    if clean_size not in allowed_sizes_upper:
                        logger.debug(f"Skipping item ID {item_id} due to size mismatch: size='{size}' (allowed: {allowed_sizes})")
                        continue
                
                price_obj = item.get("price") or {}
                price_str = f"{price_obj.get('amount', '0')} {price_obj.get('currency_code', 'EUR')}"
                
                logger.info(f"✨ NEW LISTING FOUND: [{brand}] {title} - {price_str} ({size})")
                
                # Log into the SQLite Database
                db_success = self.item_repository.add(
                    item_id=item_id,
                    title=title,
                    price=price_str,
                    url=url
                )
                
                if db_success:
                    new_listings_count += 1
                    # Dispatch to Discord Notification Pipeline
                    self.notifier.send_item_notification(item, search_name=name)
            
            logger.info(f"📊 Iteration Summary for '{name}': {new_listings_count} new items dispatched, {duplicates_count} duplicates skipped.")
            
        return True

    async def start(self):
        """Starts the infinite scraper worker loop with randomized jittered delays."""
        logger.info("🚀 Starting stealth Vinted monitoring bot...")
        self.is_running = True
        
        # Initial token fetch
        rotation_success = await self.rotate_tokens()
        if not rotation_success:
            logger.critical("❌ Initial token rotation failed! Monitoring bot cannot start.")
            self.is_running = False
            return
            
        logger.info("🚀 Monitoring bot started successfully. Entering scraper loop.")
        
        # Keep track of iteration index
        iteration = 1
        
        while self.is_running:
            try:
                logger.info(f"\n--- Monitoring Loop Iteration #{iteration} ---")
                success = await self.monitor_iteration()
                
                if not success:
                    logger.warning("⚠️ Some errors occurred during this iteration.")
                
                # SQLite maintenance cleanup (runs occasionally)
                if iteration % 50 == 0:
                    self.item_repository.cleanup_old_listings(days=7)
                
                iteration += 1
                
                # Jittered, randomized sleep intervals between loop cycles
                delays = self.config.get("delay_tolerances", {})
                min_sleep = delays.get("min_sleep_seconds", 45)
                max_sleep = delays.get("max_sleep_seconds", 90)
                sleep_duration = random.uniform(min_sleep, max_sleep)
                
                logger.info(f"😴 Sleeping for {sleep_duration:.2f} seconds to break predictable behavioral tracking...")
                await asyncio.sleep(sleep_duration)
                
            except KeyboardInterrupt:
                logger.info("Stopping scraper worker loop due to manual keyboard interrupt.")
                self.is_running = False
            except Exception as e:
                logger.error(f"Unexpected error in scraper worker loop: {e}")
                # Wait a bit before retrying after an exception
                await asyncio.sleep(10)
                
        # Cleanup
        if self.db_manager:
            self.db_manager.close()
        logger.info("Scraper worker stopped and database closed.")

    def stop(self):
        """Gracefully stops the worker loop."""
        self.is_running = False
        logger.info("Stop signal sent to scraper worker.")
