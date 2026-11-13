"""LED indicator control for WiFi connection status."""
import json
import time
from machine import Pin

class LEDIndicator:
    """Control LED blinking pattern based on WiFi status."""
    
    def __init__(self, config_file="config.json"):
        """Initialize LED indicator.
        
        Args:
            config_file: Path to configuration file
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Initialize LED with the pin from config
        led_pin_config = self.config["led_pin"]
        try:
            # Try using the config value directly (works for "LED", "WL_GPIO0", or numeric strings)
            self.led_pin = Pin(led_pin_config, Pin.OUT)
            print(f"[LED] Initialized with pin: {led_pin_config}")
        except Exception as e:
            print(f"[LED] Failed to initialize pin '{led_pin_config}': {e}")
            self.led_pin = None
        
        self.is_blinking = False
        self.status = None  # None, "connecting", "connected"
        self.last_toggle = 0
        self.blink_interval = 0
    
    def _check_and_toggle(self):
        """Check if it's time to toggle LED (non-blocking)."""
        if not self.is_blinking or self.led_pin is None:
            return
        
        current_time = time.time()
        if current_time - self.last_toggle >= self.blink_interval:
            self.led_pin.value(1 - self.led_pin.value())
            self.last_toggle = current_time
    
    def stop_blinking(self):
        """Stop LED blinking."""
        self.is_blinking = False
        if self.led_pin is not None:
            self.led_pin.off()
    
    def blink_connecting(self):
        """Blink LED with 0.5 second interval while connecting."""
        if self.led_pin is None:
            return
        if self.is_blinking and self.status == "connecting":
            return  # Already blinking
        
        self.is_blinking = True
        self.status = "connecting"
        self.blink_interval = 0.5  # Toggle every 0.5s for fast blink
        self.last_toggle = time.time()
        self.led_pin.on()
        print(f"[LED] Blink connecting (0.5s interval)")
    
    def blink_connected(self):
        """Blink LED with 1 second interval when connected."""
        if self.led_pin is None:
            return
        if self.is_blinking and self.status == "connected":
            return  # Already blinking
        
        self.is_blinking = True
        self.status = "connected"
        self.blink_interval = 1.0  # Toggle every 1s for slow blink
        self.last_toggle = time.time()
        self.led_pin.on()
        print(f"[LED] Blink connected (1.0s interval)")
    
    def update(self):
        """Call this regularly in main loop to update blinking state."""
        self._check_and_toggle()
    
    def on(self):
        """Turn LED on."""
        if self.led_pin is None:
            return
        self.stop_blinking()
        self.status = None
        self.led_pin.on()
        print(f"[LED] ON")
    
    def off(self):
        """Turn LED off."""
        if self.led_pin is None:
            return
        self.stop_blinking()
        self.status = None
        print(f"[LED] OFF")
