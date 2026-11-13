"""Battery Monitor - Manual AC Detection via external signal."""
import json
import time
from machine import Pin

class BatteryMonitorManual:
    """Monitor battery status using external AC detection signal.
    
    This mode expects an external circuit to detect AC presence and signal it.
    The circuit should connect AC detection to GPIO 2 (configurable).
    
    Detection logic:
    - GPIO HIGH (3.3V) = AC power present (electricity ON)
    - GPIO LOW (0V) = No AC, running on battery (electricity OFF)
    """
    
    def __init__(self, config_file="config.json"):
        """Initialize battery monitor with external AC signal.
        
        Args:
            config_file: Path to configuration file
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # AC detection pin - configure which GPIO to use
        self.ac_pin = self.config.get("ac_detection_pin", 2)
        self.ac = Pin(self.ac_pin, Pin.IN)
        
        self.status_file = "battery_status.json"
        self.current_status = None
        # Common attributes so callers can query battery values
        self.battery_voltage = 0.0
        self.charging_current = 0.0
        
        print(f"[BatteryMonitor] Using manual AC detection on GPIO {self.ac_pin}")
        print(f"[BatteryMonitor] GPIO HIGH = AC ON, GPIO LOW = AC OFF")
        
        self.load_status()
    
    def load_status(self):
        """Load last known battery status from file."""
        try:
            with open(self.status_file, 'r') as f:
                data = json.load(f)
                self.current_status = data.get("current_status", "ON")
        except Exception as e:
            print(f"Error loading status: {e}")
            self.current_status = "ON"
    
    def save_status(self, status, last_status=None):
        """Save battery status to file.
        
        Args:
            status: Current status "ON" or "OFF"
            last_status: Previous status (optional)
        """
        try:
            current_time = time.time()
            data = {
                "current_status": status,
                "last_status": last_status or status,
                "last_change_time": current_time,
                "cutoff_duration": 0
            }
            with open(self.status_file, 'w') as f:
                json.dump(data, f)
            self.current_status = status
        except Exception as e:
            print(f"Error saving status: {e}")
    
    def get_ac_status(self):
        """Check if AC power is present.
        
        Returns:
            str: "ON" if AC present (GPIO high), "OFF" if on battery (GPIO low)
        """
        # GPIO high (1) = AC present, GPIO low (0) = on battery
        ac_value = self.ac.value()
        status = "ON" if ac_value == 1 else "OFF"
        print(f"[AC Detection] GPIO {self.ac_pin} value: {ac_value}, AC Status: {status}")
        return status

    def get_battery_voltage(self):
        """Fallback battery voltage when no I2C available."""
        return float(self.battery_voltage)

    def get_charging_current(self):
        """Fallback charging current when no I2C available."""
        return float(self.charging_current)
    
    def check_status_change(self):
        """Check if battery status has changed.
        
        Returns:
            tuple: (status_changed, new_status, old_status)
        """
        new_status = self.get_ac_status()
        old_status = self.current_status
        
        status_changed = new_status != old_status
        
        if status_changed:
            print(f"[Manual Monitor] Status changed: {old_status} -> {new_status}")
            self.save_status(new_status, old_status)
        
        return status_changed, new_status, old_status
    
    def get_cutoff_duration(self):
        """Calculate duration of current power cutoff.
        
        Returns:
            int: Duration in seconds
        """
        try:
            with open(self.status_file, 'r') as f:
                data = json.load(f)
                if self.current_status == "ON":
                    duration = int(time.time() - data.get("last_change_time", time.time()))
                    return duration
        except Exception as e:
            print(f"Error calculating duration: {e}")
        
        return 0
    
    @staticmethod
    def format_duration(seconds):
        """Format duration in human-readable format.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            str: Formatted duration string
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")
        
        return " ".join(parts)
