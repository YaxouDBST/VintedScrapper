import json
import logging
import urllib.request
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("VintedBot.Notifier")

class DiscordNotifier:
    """Constructs and delivers highly polished Discord Rich Embed payloads via Webhooks."""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def format_price(self, price_obj: Dict[str, Any]) -> str:
        """Formats the price dictionary into a readable string (e.g., '15.00 €')."""
        if not price_obj:
            return "N/A"
        amount = price_obj.get("amount")
        currency = price_obj.get("currency_code", "EUR")
        
        # Friendly currency mapping
        currency_symbols = {
            "EUR": "€",
            "USD": "$",
            "GBP": "£",
            "CAD": "C$"
        }
        symbol = currency_symbols.get(currency, currency)
        
        try:
            return f"{float(amount):.2f} {symbol}"
        except (ValueError, TypeError):
            return f"{amount} {symbol}"

    def send_item_notification(self, item: Dict[str, Any], search_name: str) -> bool:
        """Constructs a Discord Rich Embed and dispatches it to the configured webhook."""
        if not self.webhook_url or "YOUR_DISCORD" in self.webhook_url:
            logger.warning("Discord webhook URL is not configured. Skipping notification.")
            return False

        # Extract data points
        item_id = item.get("id")
        title = item.get("title", "No Title")
        url = item.get("url", "#")
        brand = item.get("brand_title") or "N/A"
        size = item.get("size_title") or "N/A"
        condition = item.get("status") or "N/A"
        
        # Price formatting
        price_str = self.format_price(item.get("price"))
        
        # Primary photo extraction
        image_url = None
        photo_obj = item.get("photo")
        if photo_obj:
            image_url = photo_obj.get("url") or photo_obj.get("full_size_url")

        # Color hex: Eye-catching vibrant green (Hex: #2ecc71 -> Dec: 3066993)
        embed_color = 3066993 
        
        # Construct Discord Rich Embed payload
        embed = {
            "title": f"✨ {title}",
            "url": url,
            "color": embed_color,
            "fields": [
                {
                    "name": "💰 Price",
                    "value": f"**{price_str}**",
                    "inline": True
                },
                {
                    "name": "📐 Size",
                    "value": size,
                    "inline": True
                },
                {
                    "name": "🏷️ Brand",
                    "value": brand,
                    "inline": True
                },
                {
                    "name": "⭐ Condition",
                    "value": condition,
                    "inline": True
                }
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {
                "text": f"Vinted Monitor • Query: {search_name}",
            }
        }
        
        if image_url:
            embed["image"] = {"url": image_url}

        payload = {
            "username": "Vinted Hunter",
            "avatar_url": "https://images.vinted.net/styles/default/assets/meta/favicon.ico",
            "embeds": [embed]
        }

        # Dispatch via urllib (resilient and requires no external libraries for notifications)
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "VintedDiscordNotifier/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req) as response:
                status = response.status
                if status in (200, 204):
                    logger.info(f"Successfully sent Discord notification for item {item_id}.")
                    return True
                else:
                    logger.error(f"Unexpected response status from Discord webhook: {status}")
                    return False
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.error("Discord API Rate Limited! Webhook requests are being blocked.")
            else:
                logger.error(f"HTTP Error sending Discord notification: {e.code} - {e.reason}")
            return False
        except Exception as e:
            logger.error(f"Failed to dispatch Discord notification: {e}")
            return False
