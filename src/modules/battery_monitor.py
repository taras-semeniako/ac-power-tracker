"""Battery and AC detection module using UPS-A via I2C."""
import json
import time
from machine import Pin, I2C

class BatteryMonitor:
    """Monitor battery status via Pico-UPS-A I2C interface."""
    
    # INA219 Register addresses
    REG_CONFIG = 0x00        # Configuration register
    REG_SHUNT_VOLTAGE = 0x01 # Shunt voltage register
    REG_VOLTAGE = 0x02       # Bus voltage register
    REG_POWER = 0x03         # Power register
    REG_CURRENT = 0x04       # Current register
    REG_CALIBRATION = 0x05   # Calibration register

    # INA219 calibration/config tuned to Waveshare Pico-UPS-A demo defaults
    INA219_CALIBRATION_VALUE = 0x1000  # 4096
    INA219_CONFIG_VALUE = 0x3EEF       # 32V, gain /8, 12-bit 32 samples, continuous
    
    # Default thresholds if config values are missing.
    DEFAULT_DISCHARGE_OFF_THRESHOLD_MA = -40  # current <= this => AC OFF
    DEFAULT_CHARGE_ON_THRESHOLD_MA = -20      # current >= this => AC ON
    
    def __init__(self, config_file="config.json"):
        """Initialize battery monitor with I2C UPS-A.
        
        Args:
            config_file: Path to configuration file
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # I2C configuration
        self.i2c_bus = int(self.config.get("i2c_bus", 1))
        self.i2c_sda = self.config.get("i2c_sda_pin", 4)
        self.i2c_scl = self.config.get("i2c_scl_pin", 5)
        self.i2c_address = self.config.get("i2c_address", 0x43)
        self.i2c_frequency = self.config.get("i2c_frequency", 400000)
        self.invert_current_polarity = bool(self.config.get("invert_current_polarity", False))
        self.current_samples = int(self.config.get("i2c_current_samples", 5))
        self.current_sample_delay_ms = int(self.config.get("i2c_current_sample_delay_ms", 20))
        self.discharge_off_threshold_ma = float(
            self.config.get("discharge_off_threshold_ma", self.DEFAULT_DISCHARGE_OFF_THRESHOLD_MA)
        )
        self.charge_on_threshold_ma = float(
            self.config.get("charge_on_threshold_ma", self.DEFAULT_CHARGE_ON_THRESHOLD_MA)
        )
        self.off_to_on_delta_ma = float(self.config.get("off_to_on_delta_ma", 15))
        if self.charge_on_threshold_ma < self.discharge_off_threshold_ma:
            self.charge_on_threshold_ma = self.discharge_off_threshold_ma

        self.enable_chg_assist = bool(self.config.get("enable_chg_assist", True))
        self.chg_pin_num = int(self.config.get("chg_pin", 1))
        self.chg_on_value = int(self.config.get("chg_on_value", 1))
        self.chg_debounce_samples = int(self.config.get("chg_debounce_samples", 5))
        self.chg_sample_delay_ms = int(self.config.get("chg_sample_delay_ms", 50))
        self.chg_blink_means_on = bool(self.config.get("chg_blink_means_on", True))
        self.chg_calibration_margin_ma = float(self.config.get("chg_calibration_margin_ma", 10))
        self.chg_assist_off_guard_ma = float(self.config.get("chg_assist_off_guard_ma", 20))
        
        print(f"[BatteryMonitor] Initializing I2C...")
        print(f"  I2C bus: {self.i2c_bus}")
        print(f"  SDA: GPIO {self.i2c_sda}, SCL: GPIO {self.i2c_scl}")
        print(f"  Address: 0x{self.i2c_address:02x}, Frequency: {self.i2c_frequency} Hz")
        print(f"  Invert current polarity: {self.invert_current_polarity}")
        print(f"  Current samples: {self.current_samples}, delay: {self.current_sample_delay_ms} ms")
        print(
            "  Thresholds (mA): OFF<= {:.1f}, ON>= {:.1f}".format(
                self.discharge_off_threshold_ma,
                self.charge_on_threshold_ma
            )
        )
        print(f"  CHG assist enabled: {self.enable_chg_assist}")
        
        self.i2c = I2C(self.i2c_bus, scl=Pin(self.i2c_scl), sda=Pin(self.i2c_sda), freq=self.i2c_frequency)
        
        # Scan for devices
        devices = self.i2c.scan()
        device_strs = [f"0x{d:02x}" for d in devices]
        print(f"[BatteryMonitor] I2C scan result: {device_strs}")
        
        if self.i2c_address not in devices:
            print(f"[BatteryMonitor] WARNING: Expected device at 0x{self.i2c_address:02x} not found!")
            if devices:
                device_strs = [f"0x{d:02x}" for d in devices]
                print(f"[BatteryMonitor] Found devices: {device_strs}")
                print(f"[BatteryMonitor] Attempting to use first device: 0x{devices[0]:02x}")
                self.i2c_address = devices[0]
            else:
                raise RuntimeError("No I2C devices found on bus")

        self._configure_ina219()
        
        self.status_file = "battery_status.json"
        self.current_status = None
        self.battery_voltage = 0
        self.charging_current = 0
        self.last_eval_status = None
        self.chg_pin = None
        self.chg_calibrated_on_value = None

        if self.enable_chg_assist:
            pull_mode = str(self.config.get("chg_pin_pull", "up")).lower()
            if pull_mode == "up":
                pull = Pin.PULL_UP
            elif pull_mode == "down":
                pull = Pin.PULL_DOWN
            else:
                pull = None

            if pull is None:
                self.chg_pin = Pin(self.chg_pin_num, Pin.IN)
            else:
                self.chg_pin = Pin(self.chg_pin_num, Pin.IN, pull)
            print(f"  CHG assist pin: GPIO {self.chg_pin_num}, on_value={self.chg_on_value}, pull={pull_mode}")
        
        self.load_status()
        self.last_eval_status = self.current_status
        print(f"[BatteryMonitor] Initialization complete")
    
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
    
    def read_register(self, reg, num_bytes=2):
        """Read bytes from I2C register with retry logic.
        
        Args:
            reg: Register address
            num_bytes: Number of bytes to read
            
        Returns:
            bytes or int: Register value
        """
        try:
            data = self.i2c.readfrom_mem(self.i2c_address, reg, num_bytes)
            if num_bytes == 2:
                value = (data[0] << 8) | data[1]
                return value
            return data
        except Exception as e:
            print(f"[I2C Error] Reg 0x{reg:02x}: {e}")
            return 0

    def write_register(self, reg, value):
        """Write a 16-bit value to an I2C register."""
        try:
            data = bytes([(int(value) >> 8) & 0xFF, int(value) & 0xFF])
            self.i2c.writeto_mem(self.i2c_address, reg, data)
            return True
        except Exception as e:
            print(f"[I2C Error] Write reg 0x{reg:02x}: {e}")
            return False

    def _configure_ina219(self):
        """Initialize INA219 calibration and measurement mode."""
        ok_cal = self.write_register(self.REG_CALIBRATION, self.INA219_CALIBRATION_VALUE)
        ok_cfg = self.write_register(self.REG_CONFIG, self.INA219_CONFIG_VALUE)
        if ok_cal and ok_cfg:
            print(
                "[BatteryMonitor] INA219 configured: "
                f"CAL=0x{self.INA219_CALIBRATION_VALUE:04x}, CFG=0x{self.INA219_CONFIG_VALUE:04x}"
            )
        else:
            print("[BatteryMonitor] WARNING: INA219 configuration write failed")
    
    def get_battery_voltage(self):
        """Read battery voltage from UPS-A.
        
        Returns:
            float: Voltage in volts
        """
        try:
            raw_data = self.read_register(self.REG_VOLTAGE)
            raw_voltage = int(raw_data)
            # Bus voltage: bits 15-3 give voltage in 4mV steps
            voltage_mv = (int(raw_voltage) >> 3) * 4  # in millivolts
            self.battery_voltage = float(voltage_mv) / 1000.0  # convert to volts
            return self.battery_voltage
        except Exception as e:
            print(f"Error reading voltage: {e}")
            return 0.0
    
    def get_charging_current(self):
        """Read current from UPS-A to determine if charging.
        
        Returns:
            float: Current in mA (negative = discharging, positive = charging)
        """
        try:
            raw_data = self.read_register(self.REG_CURRENT)
            raw_current = int(raw_data) & 0xFFFF
            # Convert unsigned 16-bit register value to signed integer.
            if raw_current >= 0x8000:
                signed_current = raw_current - 0x10000
            else:
                signed_current = raw_current

            if self.invert_current_polarity:
                signed_current = -signed_current

            self.charging_current = signed_current
            return float(self.charging_current)
        except Exception as e:
            print(f"Error reading current: {e}")
            return 0.0

    def get_filtered_charging_current(self):
        """Read current multiple times and return averaged value."""
        sample_count = self.current_samples if self.current_samples > 0 else 1
        total = 0.0
        valid_samples = 0
        for i in range(sample_count):
            current = self.get_charging_current()
            total += float(current)
            valid_samples += 1
            if i + 1 < sample_count and self.current_sample_delay_ms > 0:
                time.sleep_ms(self.current_sample_delay_ms)

        if valid_samples <= 0:
            return 0.0
        return total / valid_samples

    def get_chg_assist_status(self, current_ma):
        """Read CHG signal and derive AC status hint with polarity auto-calibration."""
        if self.chg_pin is None:
            return None

        high_count = 0
        low_count = 0
        sample_count = self.chg_debounce_samples if self.chg_debounce_samples > 0 else 1

        for i in range(sample_count):
            value = 1 if self.chg_pin.value() == 1 else 0
            if value == 1:
                high_count += 1
            else:
                low_count += 1

            if i + 1 < sample_count and self.chg_sample_delay_ms > 0:
                time.sleep_ms(self.chg_sample_delay_ms)

        mixed_signal = high_count > 0 and low_count > 0
        if mixed_signal and self.chg_blink_means_on:
            return "ON"

        majority_value = 1 if high_count >= ((sample_count // 2) + 1) else 0

        if current_ma >= (self.charge_on_threshold_ma + self.chg_calibration_margin_ma):
            self.chg_calibrated_on_value = majority_value
        elif current_ma <= (self.discharge_off_threshold_ma - self.chg_calibration_margin_ma):
            self.chg_calibrated_on_value = 1 - majority_value

        effective_on_value = (
            self.chg_calibrated_on_value
            if self.chg_calibrated_on_value in (0, 1)
            else self.chg_on_value
        )

        status = "ON" if majority_value == effective_on_value else "OFF"
        print(
            "[CHG assist] highs={}, lows={}, majority={}, cfg_on={}, cal_on={}, eff_on={}, status={}".format(
                high_count,
                low_count,
                majority_value,
                self.chg_on_value,
                self.chg_calibrated_on_value,
                effective_on_value,
                status
            )
        )
        return status
    
    def get_ac_status(self):
        """Determine if AC power is present based on charging current.
        
        Returns:
            str: "ON" if charging (AC present), "OFF" if discharging (battery)
        """
        try:
            current = self.get_filtered_charging_current()

            previous_status = self.last_eval_status if self.last_eval_status in ("ON", "OFF") else self.current_status
            if previous_status not in ("ON", "OFF"):
                previous_status = "ON"

            # OFF -> ON often recovers to a mildly negative current first.
            # Use a relaxed ON threshold during recovery to avoid sticky OFF.
            off_to_on_threshold = self.discharge_off_threshold_ma + self.off_to_on_delta_ma
            if off_to_on_threshold > self.charge_on_threshold_ma:
                effective_on_threshold = self.charge_on_threshold_ma
            else:
                effective_on_threshold = off_to_on_threshold

            if current <= self.discharge_off_threshold_ma:
                status = "OFF"
            elif current >= effective_on_threshold:
                status = "ON"
            else:
                # Hysteresis window: preserve previous stable state.
                status = previous_status

            chg_status = self.get_chg_assist_status(current)
            # If CHG indicates AC is present, treat as authoritative for ON.
            # I2C current can remain negative for some time right after AC returns.
            if chg_status == "ON":
                if status != "ON":
                    print("[I2C] CHG assist override: forcing ON")
                status = "ON"
            elif chg_status == "OFF":
                # Only force OFF when current strongly confirms discharge.
                if current <= (self.discharge_off_threshold_ma - self.chg_assist_off_guard_ma):
                    status = "OFF"

            self.last_eval_status = status

            print(
                "[I2C] current={:.1f}mA, thresholds(off<= {:.1f}, on>= {:.1f}), prev={}, chg_hint={}, status={}".format(
                    current,
                    self.discharge_off_threshold_ma,
                    effective_on_threshold,
                    previous_status,
                    chg_status,
                    status
                )
            )
            return status
        except Exception as e:
            print(f"Error getting AC status: {e}")
            return "OFF"
    
    def check_status_change(self):
        """Check if battery status has changed.
        
        Returns:
            tuple: (status_changed, new_status, old_status)
        """
        new_status = self.get_ac_status()
        old_status = self.current_status
        
        if new_status != old_status:
            self.save_status(new_status, old_status)
            return True, new_status, old_status
        
        return False, new_status, old_status
    
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
