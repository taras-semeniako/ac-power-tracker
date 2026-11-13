"""WiFi connection management."""
import json
import time
import network

class WiFiManager:
    """Handle WiFi connection and reconnection."""

    QUICK_CONNECT_TIMEOUT_MS = 10000
    
    def __init__(self, config_file="wifi_config.json", led_indicator=None):
        """Initialize WiFi manager.
        
        Args:
            config_file: Path to WiFi configuration file
            led_indicator: LED indicator object (optional)
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        self.led = led_indicator
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(False)
        self.is_connected = False
        self.reconnect_attempts = int(self.config.get("reconnect_attempts", 10))
        self.reconnect_delay_s = int(self.config.get("reconnect_delay", 5))
        self.quick_connect_pending = False
        self.quick_connect_started_ms = None
    
    def connect(self, debug=False, max_attempts=None, attempt_delay_s=None):
        """Connect to WiFi network.
        
        Args:
            debug: Print debug messages
            max_attempts: Override retry attempts
            attempt_delay_s: Override delay per attempt
            
        Returns:
            bool: True if connected, False otherwise
        """
        try:
            print(f"Connecting to WiFi: {self.config['ssid']}")
            
            # Ensure LED is blinking during connection attempt
            if self.led and not self.led.is_blinking:
                self.led.blink_connecting()
            
            self.wlan.active(True)
            
            attempts = int(max_attempts) if max_attempts is not None else self.reconnect_attempts
            delay_s = float(attempt_delay_s) if attempt_delay_s is not None else float(self.reconnect_delay_s)
            if attempts < 1:
                attempts = 1
            if delay_s < 0:
                delay_s = 0
            
            for attempt in range(1, attempts + 1):
                if self.wlan.isconnected():
                    break
                print(f"  Attempt {attempt}/{attempts}...")
                self.wlan.connect(self.config['ssid'], self.config['password'])
                
                waited = 0
                while not self.wlan.isconnected() and waited < delay_s:
                    time.sleep(0.5)
                    waited += 0.5
            
            if self.wlan.isconnected():
                self.is_connected = True
                self.quick_connect_pending = False
                self.quick_connect_started_ms = None
                print(f"✓ WiFi connected! IP: {self.wlan.ifconfig()[0]}")
                if self.led:
                    self.led.blink_connected()
                return True
            else:
                self.is_connected = False
                self.quick_connect_pending = False
                self.quick_connect_started_ms = None
                print("✗ Failed to connect to WiFi")
                if self.led:
                    self.led.off()
                return False
        except Exception as e:
            print(f"Connection error: {e}")
            self.is_connected = False
            if self.led:
                self.led.off()
            return False
    
    def disconnect(self):
        """Disconnect from WiFi."""
        if self.wlan.isconnected():
            self.wlan.disconnect()
            self.wlan.active(False)
        self.is_connected = False
        self.quick_connect_pending = False
        self.quick_connect_started_ms = None
        if self.led:
            self.led.off()
    
    def reconnect_if_needed(self, debug=False, quick=False):
        """Reconnect to WiFi if connection is lost.
        
        Args:
            debug: Print debug messages
            quick: Use a short, non-blocking reconnect attempt
            
        Returns:
            bool: True if connected (or already connected), False otherwise
        """
        try:
            if self.wlan.isconnected():
                self.is_connected = True
                self.quick_connect_pending = False
                self.quick_connect_started_ms = None
                if debug:
                    print("✓ WiFi already connected")
                if self.led and self.led.status != "connected":
                    self.led.blink_connected()
                return True
        except Exception as e:
            print(f"WiFi status check error: {e}")
            return False
        
        print("WiFi disconnected, attempting to reconnect...")
        
        try:
            if quick:
                now = time.ticks_ms()
                if self.quick_connect_pending:
                    elapsed_ms = time.ticks_diff(now, self.quick_connect_started_ms)
                    timeout_ms = max(
                        self.QUICK_CONNECT_TIMEOUT_MS,
                        self.reconnect_delay_s * 1000
                    )
                    if elapsed_ms < timeout_ms:
                        return False
                    print("WiFi connection timed out, retrying...")

                if not self.wlan.active():
                    self.wlan.active(True)

                if self.led:
                    self.led.blink_connecting()

                print("Starting non-blocking WiFi connection attempt...")
                self.wlan.connect(self.config['ssid'], self.config['password'])
                self.quick_connect_pending = True
                self.quick_connect_started_ms = now
                return False

            # Start LED blinking before reconnection attempt
            if self.led:
                self.led.blink_connecting()
            
            self.wlan.active(False)
            time.sleep(0.2)
            self.quick_connect_pending = False
            self.quick_connect_started_ms = None
            return self.connect(debug=debug)
        except Exception as e:
            print(f"Reconnection error: {e}")
            return False
    
    def is_network_available(self):
        """Check if WiFi network is available.
        
        Returns:
            bool: True if connected
        """
        return self.wlan.isconnected()
