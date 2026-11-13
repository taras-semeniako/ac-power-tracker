"""Battery Monitor using UPS-A CHG GPIO signal (alternative to I2C)."""
import json
import time
from machine import Pin

class BatteryMonitorCHG:
    """Monitor battery status using UPS-A CHG GPIO signal.
    
    The UPS-A has a CHG (charging) output that goes HIGH when AC is connected
    and LOW when running on battery.
    """
    
    def __init__(self, config_file="config.json"):
        """Initialize battery monitor with CHG signal.
        
        Args:
            config_file: Path to configuration file
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        pull_mode = str(self.config.get("chg_pin_pull", "up")).lower()
        if pull_mode == "up":
            pull = Pin.PULL_UP
        elif pull_mode == "down":
            pull = Pin.PULL_DOWN
        else:
            pull = None

        # CHG pin - HIGH when charging (AC on), LOW when on battery
        if pull is None:
            self.chg_pin = Pin(self.config.get("chg_pin", 1), Pin.IN)
        else:
            self.chg_pin = Pin(self.config.get("chg_pin", 1), Pin.IN, pull)
        self.chg_on_value = int(self.config.get("chg_on_value", 1))
        self.chg_debounce_samples = int(self.config.get("chg_debounce_samples", 5))
        self.chg_sample_delay_ms = int(self.config.get("chg_sample_delay_ms", 50))
        self.chg_blink_means_on = bool(self.config.get("chg_blink_means_on", True))
        self.chg_on_latch_seconds = float(self.config.get("chg_on_latch_seconds", 8))
        self.chg_irq_enabled = bool(self.config.get("chg_irq_enabled", True))
        self.chg_auto_detect_floating = bool(self.config.get("chg_auto_detect_floating", True))
        self.chg_floating_use_pulldown = bool(self.config.get("chg_floating_use_pulldown", True))
        self.chg_presence_mode = bool(self.config.get("chg_presence_mode", True))
        self.chg_pin_pull = pull_mode
        self.status_file = "battery_status.json"
        self.current_status = None
        # Provide common attributes so callers can query battery values
        self.battery_voltage = 0.0
        self.charging_current = 0.0
        self.last_high_time = None
        self.last_high_ticks = None
        self.last_edge_time = None
        self.chg_floating_hint = False
        
        print(f"[BatteryMonitor] Using CHG GPIO signal on pin {self.config.get('chg_pin', 1)}")
        print(f"[BatteryMonitor] CHG on-value configured as: {self.chg_on_value}")
        print(f"[BatteryMonitor] CHG debounce samples: {self.chg_debounce_samples}")
        print(f"[BatteryMonitor] CHG sample delay: {self.chg_sample_delay_ms} ms")
        print(f"[BatteryMonitor] CHG blink means AC ON: {self.chg_blink_means_on}")
        print(f"[BatteryMonitor] CHG ON latch seconds: {self.chg_on_latch_seconds}")
        print(f"[BatteryMonitor] CHG IRQ enabled: {self.chg_irq_enabled}")
        print(f"[BatteryMonitor] CHG floating auto-detect: {self.chg_auto_detect_floating}")
        print(f"[BatteryMonitor] CHG floating uses pulldown: {self.chg_floating_use_pulldown}")
        print(f"[BatteryMonitor] CHG presence mode: {self.chg_presence_mode}")
        print(f"[BatteryMonitor] CHG pin pull mode: {self.chg_pin_pull}")

        if self.chg_auto_detect_floating:
            self._detect_floating_input()

        if self.chg_irq_enabled:
            try:
                self.chg_pin.irq(
                    trigger=Pin.IRQ_RISING,
                    handler=self._on_chg_irq
                )
            except Exception as e:
                print(f"[BatteryMonitor] CHG IRQ setup failed: {e}")
                self.chg_irq_enabled = False

        if self.chg_pin.value() == 1:
            self._mark_high_seen()
        
        self.load_status()

    def _mark_high_seen(self, from_irq=False):
        """Mark that a HIGH pulse was observed on CHG."""
        try:
            self.last_high_ticks = time.ticks_ms()
        except Exception:
            self.last_high_ticks = None
        if not from_irq:
            self.last_high_time = time.time()

    def _detect_floating_input(self):
        """Detect whether CHG input looks floating under pull-up/pull-down."""
        try:
            pin_num = int(self.config.get("chg_pin", 1))
            pin_up = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            up_value = 1 if pin_up.value() == 1 else 0
            time.sleep_ms(5)
            pin_down = Pin(pin_num, Pin.IN, Pin.PULL_DOWN)
            down_value = 1 if pin_down.value() == 1 else 0
            time.sleep_ms(5)

            pull_mode = self.chg_pin_pull
            if pull_mode == "up":
                pull = Pin.PULL_UP
            elif pull_mode == "down":
                pull = Pin.PULL_DOWN
            else:
                pull = None

            if pull is None:
                self.chg_pin = Pin(pin_num, Pin.IN)
            else:
                self.chg_pin = Pin(pin_num, Pin.IN, pull)

            self.chg_floating_hint = (up_value == 1 and down_value == 0)
            if self.chg_floating_hint and self.chg_floating_use_pulldown:
                self.chg_pin = Pin(pin_num, Pin.IN, Pin.PULL_DOWN)
                self.chg_pin_pull = "down"
                print("[BatteryMonitor] CHG floating detected: forcing pull-down mode")
            print(f"[BatteryMonitor] CHG float probe: up={up_value}, down={down_value}, floating={self.chg_floating_hint}")
        except Exception as e:
            print(f"[BatteryMonitor] CHG float probe failed: {e}")
            self.chg_floating_hint = False

    def _on_chg_irq(self, pin):
        """IRQ callback to capture CHG pulses between polling cycles."""
        try:
            if pin.value() == 1:
                self._mark_high_seen(from_irq=True)
        except Exception:
            return
    
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
        """Check if AC power is present using CHG signal.
        
        Returns:
            str: "ON" if charging (AC present), "OFF" if on battery
        """
        # CHG polarity differs by board revision.
        # chg_on_value tells which GPIO value means AC ON.
        # Read several samples to avoid transient false triggers.
        # Some UPS boards output a blinking CHG signal while AC is present.
        # For those boards, mixed HIGH/LOW samples in one read window should
        # be interpreted as AC ON.
        high_count = 0
        low_count = 0
        toggles = 0
        prev_value = None
        sample_count = self.chg_debounce_samples if self.chg_debounce_samples > 0 else 1
        for i in range(sample_count):
            value = 1 if self.chg_pin.value() == 1 else 0
            if value == 1:
                high_count += 1
            else:
                low_count += 1

            if prev_value is not None and value != prev_value:
                toggles += 1
            prev_value = value

            if i + 1 < sample_count:
                time.sleep_ms(self.chg_sample_delay_ms)

        now = time.time()
        if high_count > 0:
            self._mark_high_seen()

        if self.chg_presence_mode:
            status = "ON" if high_count > 0 else "OFF"
            reason = "high-pulse" if high_count > 0 else "no-high"
        else:
            chg_value = 1 if high_count >= ((sample_count // 2) + 1) else 0
            status = "ON" if chg_value == self.chg_on_value else "OFF"
            reason = "majority"

            mixed_signal = high_count > 0 and low_count > 0
            if mixed_signal and self.chg_blink_means_on:
                status = "ON"
                reason = "blink-detected"

        if status != "ON" and self.last_high_time is not None:
            since_high = now - self.last_high_time
            in_latch_window = since_high <= self.chg_on_latch_seconds
            if (not in_latch_window) and (self.last_high_ticks is not None):
                try:
                    since_high_ms = time.ticks_diff(time.ticks_ms(), self.last_high_ticks)
                    in_latch_window = since_high_ms <= int(self.chg_on_latch_seconds * 1000)
                except Exception:
                    pass
            if in_latch_window:
                status = "ON"
                reason = "latched-high"
        else:
            since_high = 0 if self.last_high_time is not None else None

        if self.chg_floating_hint and not self.chg_presence_mode:
            if self.last_high_time is None:
                status = "OFF"
                reason = "floating-no-high"
            else:
                since_edge = now - self.last_high_time
                if since_edge <= self.chg_on_latch_seconds:
                    status = "ON"
                    reason = "floating-high-active"
                else:
                    status = "OFF"
                    reason = "floating-high-timeout"
        else:
            since_edge = None

        print(
            "[CHG] highs={}, lows={}, toggles={}, mode={}, on_value={}, since_high={}, since_edge={}, floating={}, AC Status: {}".format(
                high_count,
                low_count,
                toggles,
                reason,
                self.chg_on_value,
                since_high,
                since_edge,
                self.chg_floating_hint,
                status
            )
        )
        return status

    def get_battery_voltage(self):
        """Return a fallback battery voltage when I2C is not available."""
        return float(self.battery_voltage)

    def get_charging_current(self):
        """Return a fallback charging current when I2C is not available."""
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
            print(f"[CHG Monitor] Status changed: {old_status} -> {new_status}")
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
