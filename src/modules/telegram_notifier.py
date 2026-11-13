"""Telegram notification handler."""
import json
import urequests

class TelegramNotifier:
    """Send notifications via Telegram bot."""
    
    def __init__(self, config_file="telegram_config.json"):
        """Initialize Telegram notifier.
        
        Args:
            config_file: Path to Telegram configuration file
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        self.bot_token = self.config.get("bot_token")
        self.chat_id = self.config.get("chat_id")
        self.enabled = self.config.get("enabled", True)
        self.power_on_message = self.config.get("power_on_message", "Electricity turned ON")
        self.power_off_message = self.config.get("power_off_message", "Electricity turned OFF")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    def send_message(self, message, debug=False):
        """Send message via Telegram.
        
        Args:
            message: Message text to send
            debug: Print debug messages
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not self.enabled:
            print("Telegram notifications disabled")
            return False
        
        if not self.bot_token or not self.chat_id:
            print("Telegram config incomplete: bot_token={}, chat_id={}".format(
                "set" if self.bot_token else "missing",
                "set" if self.chat_id else "missing"
            ))
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message
            }
            payload = json.dumps(data).encode("utf-8")
            
            print("[Telegram] Sending notification")
            response = urequests.post(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                print("[Telegram] Message sent successfully (HTTP {})".format(response.status_code))
                response.close()
                return True
            else:
                print("[Telegram] HTTP error: {}".format(response.status_code))
                print("[Telegram] Response bytes: {}".format(response.text[:200].encode("utf-8")))
                response.close()
                return False
                
        except Exception as e:
            print("[Telegram] Exception: {}".format(e))
            return False
    
    def send_power_off_notification(self, debug=False):
        """Send power off notification.
        
        Args:
            debug: Print debug messages
            
        Returns:
            bool: True if sent successfully
        """
        return self.send_message(self.power_off_message, debug=debug)
    
    def send_power_on_notification(self, debug=False):
        """Send power on notification.
        
        Args:
            debug: Print debug messages
            
        Returns:
            bool: True if sent successfully
        """
        return self.send_message(self.power_on_message, debug=debug)
