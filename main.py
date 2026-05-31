import asyncio
import logging
import sys
from scraper_worker import VintedScraperWorker

def setup_logging():
    """Configures highly verbose, readable console and file loggers."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot.log", encoding="utf-8")
        ]
    )
    
    # Adjust verbosity of third-party libraries
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlite3").setLevel(logging.WARNING)

async def main():
    setup_logging()
    logger = logging.getLogger("VintedBot.Main")
    
    logger.info("==================================================")
    logger.info("👑 Vinted Stealth Monitoring Bot Started 👑")
    logger.info("==================================================")
    
    try:
        worker = VintedScraperWorker(config_path="config.json")
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Manual shutdown signal received. Shutting down gracefully...")
    except Exception as e:
        logger.critical(f"Fatal exception occurred in application thread: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        # Check Python version compatibility
        if sys.version_info < (3, 7):
            print("Error: Python 3.7 or higher is required.")
            sys.exit(1)
            
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Scraper terminated by user. Goodbye!")
        sys.exit(0)
