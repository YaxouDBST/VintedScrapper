import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger("VintedBot.Database")

class DatabaseManager:
    """Manages the lifecycle of the SQLite database connection."""
    def __init__(self, db_path: str = "listings.db"):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a database connection with dictionary-like row factory."""
        if not self.conn:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def init_db(self):
        """Initializes the database schema if it doesn't already exist."""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS listings (
                        item_id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        price TEXT NOT NULL,
                        url TEXT NOT NULL,
                        timestamp_found TEXT NOT NULL
                    )
                """)
                # Create an index on timestamp_found for potential cleanup query optimization
                conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_timestamp ON listings(timestamp_found)")
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing SQLite database: {e}")
            raise e

    def close(self):
        """Safely closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed.")


class ItemRepository:
    """Handles data access operations for listings in the database."""
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def exists(self, item_id: int) -> bool:
        """Rapidly checks if an item exists by its primary key ID using index lookup."""
        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM listings WHERE item_id = ? LIMIT 1", (item_id,))
            row = cursor.fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"Error checking item existence for ID {item_id}: {e}")
            return False

    def add(self, item_id: int, title: str, price: str, url: str) -> bool:
        """Inserts a new item listing into the database."""
        conn = self.db_manager.get_connection()
        timestamp = datetime.utcnow().isoformat()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO listings (item_id, title, price, url, timestamp_found) VALUES (?, ?, ?, ?, ?)",
                    (item_id, title, price, url, timestamp)
                )
            logger.debug(f"Logged new item ID {item_id} into SQLite.")
            return True
        except sqlite3.IntegrityError:
            # Handle rare race condition case where item might have been inserted in between checks
            logger.warning(f"IntegrityError: Item {item_id} already exists in DB.")
            return False
        except Exception as e:
            logger.error(f"Error inserting item ID {item_id} into DB: {e}")
            return False

    def cleanup_old_listings(self, days: int = 7) -> int:
        """Deletes listings older than a specified number of days to manage database size."""
        conn = self.db_manager.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM listings WHERE datetime(timestamp_found) < datetime('now', ?)",
                    (f"-{days} days",)
                )
                deleted_count = cursor.rowcount
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} older listings from SQLite database.")
            return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old listings: {e}")
            return 0
