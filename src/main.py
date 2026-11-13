"""Main application for battery tracking and Telegram notifications."""
import json
import time
from modules.battery_monitor import BatteryMonitor
from modules.battery_monitor_chg import BatteryMonitorCHG
from modules.battery_monitor_manual import BatteryMonitorManual
from modules.wifi_manager import WiFiManager
from modules.telegram_notifier import TelegramNotifier
from modules.led_indicator import LEDIndicator

class BatteryTrackerApp:
    """Main application controller."""
    
    def __init__(self, mode="auto"):
        """Initialize the battery tracker application.
        
        Args:
            mode: "auto" (default), "i2c", "chg", or "manual"
        """
        # Load configuration
        with open("config.json", 'r') as f:
            self.config = json.load(f)
        
        self.debug = self.config.get("debug_mode", False)
        self.check_interval = self.config.get("battery_check_interval", 10)
        self.strict_i2c = self.config.get("strict_i2c", False)
        self.i2c_init_retries = int(self.config.get("i2c_init_retries", 5))
        if self.i2c_init_retries < 1:
            self.i2c_init_retries = 1
        self.i2c_init_retry_delay_s = float(self.config.get("i2c_init_retry_delay_s", 0.7))
        if self.i2c_init_retry_delay_s < 0:
            self.i2c_init_retry_delay_s = 0
        self.allow_emergency_fallback = bool(self.config.get("allow_emergency_fallback", False))
        self.mode = mode

        self.event_log_file = self.config.get("event_log_file", "battery_event.log")
        self.event_log_enabled = bool(self.config.get("event_log_enabled", True))
        
        # Initialize components
        self.led = LEDIndicator("config.json")
        self.battery_monitor = None  # Will be set in _init_battery_monitor()
        
        if self.debug:
            print(f"[LED] Initialized on GPIO {self.config.get('led_pin', 25)}")
            print(f"[Config] monitor_mode={self.mode}, strict_i2c={self.strict_i2c}")
        
        # Initialize battery monitor based on mode
        self._init_battery_monitor()

        # Optional emergency fallback: can be enabled for bring-up only.
        if self.battery_monitor is None and self.allow_emergency_fallback:
            self._log("Primary monitor init failed, attempting emergency fallback monitors...")
            for monitor_name, monitor_cls in (("CHG", BatteryMonitorCHG), ("manual", BatteryMonitorManual)):
                try:
                    self.battery_monitor = monitor_cls("config.json")
                    self._log(f"✓ Emergency fallback initialized: {monitor_name}")
                    break
                except Exception as e:
                    self._log(f"✗ Emergency fallback {monitor_name} failed: {e}")
        
        # Ensure a battery monitor implementation was selected
        if self.battery_monitor is None:
            raise RuntimeError("Failed to initialize any battery monitor mode. Check hardware and config.")

        # Aid static analyzers: guarantee battery_monitor is non-None beyond this point
        assert self.battery_monitor is not None, "battery_monitor must be initialized"

        # For static tools: battery_monitor should provide the common monitor API
        # (get_ac_status, check_status_change, get_cutoff_duration, get_battery_voltage, get_charging_current)
        
        self.wifi_manager = WiFiManager("wifi_config.json", led_indicator=self.led)
        self.telegram = TelegramNotifier("telegram_config.json")
        
        self.last_notification_time = 0
        self.notification_cooldown = 5  # Prevent duplicate notifications
        self.last_notified_status = self._load_last_notified_status()
        self.pending_notification_status = None
        self.status_confirm_checks = int(self.config.get("status_confirm_checks", 1))
        if self.status_confirm_checks < 1:
            self.status_confirm_checks = 1
        self.notification_attempts = int(self.config.get("notification_attempts", 3))
        if self.notification_attempts < 1:
            self.notification_attempts = 1
        self.notification_retry_delay_s = float(self.config.get("notification_retry_delay_s", 1))
        if self.notification_retry_delay_s < 0:
            self.notification_retry_delay_s = 0

        self.notify_startup_mismatch = bool(self.config.get("notify_startup_mismatch", False))
        
        self._log("Battery Tracker initialized")
        self._log(f"Check interval: {self.check_interval} seconds")
        self._log(f"Initial battery status: {self.battery_monitor.current_status}")
        self._log(f"Monitor class: {type(self.battery_monitor).__name__}")
        self._log(f"Last notified status: {self.last_notified_status}")
        self._log(f"Status confirmations required: {self.status_confirm_checks}")
        self._log(f"Notification attempts: {self.notification_attempts}, retry delay: {self.notification_retry_delay_s}s")
        self._log(f"Notify startup mismatch: {self.notify_startup_mismatch}")
        self._log(f"Allow emergency fallback: {self.allow_emergency_fallback}")

    def _format_timestamp(self):
        """Return local timestamp string for device log lines."""
        try:
            y, mo, d, h, mi, s, _, _ = time.localtime()
            return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(y, mo, d, h, mi, s)
        except Exception:
            return str(time.time())

    def _append_device_log(self, message):
        """Append a message to on-device log file."""
        if not self.event_log_enabled:
            return
        try:
            line = "[{}] {}\n".format(self._format_timestamp(), message)
            with open(self.event_log_file, 'a') as f:
                f.write(line)
        except Exception as e:
            print(f"Could not write device log: {e}")

    def _log(self, message):
        """Write message to console and device log."""
        if self.debug:
            print(message)
        self._append_device_log(message)

    def _load_last_notified_status(self):
        """Load last successfully notified status from persistent state."""
        try:
            with open("battery_status.json", 'r') as f:
                data = json.load(f)
                value = data.get("last_notified_status")
                if value in ("ON", "OFF"):
                    return value
        except Exception:
            pass
        return None

    def _save_last_notified_status(self, status):
        """Persist last successfully notified status."""
        if status not in ("ON", "OFF"):
            return

        try:
            data = {}
            try:
                with open("battery_status.json", 'r') as f:
                    data = json.load(f)
            except Exception:
                data = {}

            data["last_notified_status"] = status
            with open("battery_status.json", 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Could not persist last_notified_status: {e}")
    
    def _init_battery_monitor(self):
        """Initialize battery monitor with fallback logic."""
        def try_init_i2c():
            last_error = None
            for attempt in range(1, self.i2c_init_retries + 1):
                try:
                    self._log(f"Attempting I2C mode (attempt {attempt}/{self.i2c_init_retries})...")
                    self.battery_monitor = BatteryMonitor("config.json")
                    self._log("✓ I2C mode initialized")
                    return True
                except Exception as e:
                    last_error = e
                    self._log(f"✗ I2C attempt {attempt} failed: {e}")
                    if attempt < self.i2c_init_retries and self.i2c_init_retry_delay_s > 0:
                        time.sleep(self.i2c_init_retry_delay_s)
            if last_error is not None:
                self._log(f"I2C mode failed after retries: {last_error}")
            return False

        if self.mode == "auto":
            # Try I2C first (with retries)
            if try_init_i2c():
                return
            if self.strict_i2c:
                self._log("Strict I2C mode is enabled; skipping CHG/manual fallback.")
                return
            
            # Try CHG GPIO mode
            try:
                self._log("Attempting CHG GPIO mode...")
                self.battery_monitor = BatteryMonitorCHG("config.json")
                self._log("✓ CHG GPIO mode initialized")
                return
            except Exception as e:
                self._log(f"✗ CHG GPIO mode failed: {e}")
            
            # Fallback to manual mode
            try:
                self._log("Falling back to manual AC detection mode...")
                self.battery_monitor = BatteryMonitorManual("config.json")
                self._log("✓ Manual mode initialized")
                return
            except Exception as e:
                self._log(f"✗ Manual mode failed: {e}")
        
        elif self.mode == "i2c":
            try_init_i2c()
        
        elif self.mode == "chg":
            try:
                self.battery_monitor = BatteryMonitorCHG("config.json")
            except Exception as e:
                print(f"CHG mode failed: {e}")
        
        elif self.mode == "manual":
            try:
                self.battery_monitor = BatteryMonitorManual("config.json")
            except Exception as e:
                print(f"Manual mode failed: {e}")
    
    def _send_notification_for_status(self, status):
        """Send Telegram notification for a given status.

        Args:
            status: "ON" or "OFF"

        Returns:
            bool: True if notification was sent, False otherwise
        """
        if status == "OFF":
            self._log("Sending power OFF notification...")
            return self.telegram.send_power_off_notification(debug=True)
        if status == "ON":
            self._log("Sending power ON notification...")
            return self.telegram.send_power_on_notification(debug=True)
        return False

    def _send_notification_with_retries(self, status, attempts=None):
        """Send notification with retries and quick WiFi recovery between attempts."""
        max_attempts = attempts if attempts is not None else self.notification_attempts
        if max_attempts < 1:
            max_attempts = 1

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                self._log(f"Preparing retry {attempt}/{max_attempts} for {status} notification")
                self.wifi_manager.reconnect_if_needed(debug=self.debug, quick=True)
                if self.notification_retry_delay_s > 0:
                    time.sleep(self.notification_retry_delay_s)

            result = self._send_notification_for_status(status)
            self._log(f"Notification attempt {attempt}/{max_attempts} result: {result}")
            if result:
                return True

        return False

    def handle_status_change(self, new_status, old_status):
        """Handle battery status change.
        
        Args:
            new_status: New battery status
            old_status: Previous battery status
        """
        current_time = time.time()

        if new_status == old_status:
            return
        
        # Prevent duplicate notifications of the same state only.
        # Do not suppress real state flips (ON->OFF or OFF->ON).
        same_as_last_notified = (new_status == self.last_notified_status)
        in_cooldown = (current_time - self.last_notification_time < self.notification_cooldown)
        if same_as_last_notified and in_cooldown:
            self._log(f"Skipping duplicate {new_status} notification (cooldown: {self.notification_cooldown}s)")
            return
        
        self.last_notification_time = current_time
        
        self._log(f"✓ Status change detected: {old_status} -> {new_status}")

        # Do not block status detection loop with long reconnect here.
        # Try send immediately; retry logic handles WiFi recovery.
        result = self._send_notification_with_retries(new_status)
        self._log(f"Notification result: {result}")

        if not result:
            # Keep the newest pending status; retry on next loop.
            self.pending_notification_status = new_status
            self._log(f"Queued pending notification: {new_status}")
        else:
            self.last_notified_status = new_status
            self._save_last_notified_status(new_status)
            self.pending_notification_status = None
    
    def run(self):
        """Main application loop."""
        monitor = self.battery_monitor
        if monitor is None:
            raise RuntimeError("Battery monitor is not initialized")

        self._log("Starting main loop...")
        initial_status = monitor.get_ac_status()
        self._log(f"Current AC status: {initial_status}")
        stable_status = initial_status
        candidate_status = None
        candidate_count = 0

        # Reconcile persisted status vs real hardware status on startup.
        # This ensures immediate notification after reboot, e.g. OFF -> ON.
        persisted_status = monitor.current_status
        if persisted_status != initial_status:
            self._log(f"Startup status mismatch: persisted={persisted_status}, current={initial_status}")
            monitor.save_status(initial_status, persisted_status)
            if self.notify_startup_mismatch:
                self.handle_status_change(initial_status, persisted_status)
        
        wifi_check_interval = 0  # Counter to limit WiFi checks
        wifi_check_frequency = 1  # Check WiFi every battery check (every 10 seconds)
        last_battery_check = time.time()  # Track last battery check time
        
        try:
            while True:
                try:
                    # Update LED blinking state (runs every loop iteration for smooth blinking)
                    self.led.update()
                    
                    # Battery and status checks based on elapsed time
                    current_time = time.time()
                    if current_time - last_battery_check >= self.check_interval:
                        # Read battery info if available (only I2C mode has real data)
                        # Check if this is I2C mode by class name
                        if type(monitor).__name__ == 'BatteryMonitor':
                            try:
                                voltage = monitor.get_battery_voltage()
                                current = monitor.get_charging_current()
                                if self.debug:
                                    self._log(f"Battery: {voltage:.2f}V, Current: {current:.1f}mA")
                            except Exception as e:
                                if self.debug:
                                    self._log(f"Could not read battery info: {e}")
                        
                        # Read raw status and confirm transitions over multiple checks
                        # to avoid single-sample glitches.
                        observed_status = monitor.get_ac_status()

                        if observed_status == stable_status:
                            if candidate_status is not None:
                                self._log(
                                    f"Transition candidate cleared: {candidate_status} "
                                    f"(stable remains {stable_status})"
                                )
                            candidate_status = None
                            candidate_count = 0
                        else:
                            if observed_status == candidate_status:
                                candidate_count += 1
                            else:
                                candidate_status = observed_status
                                candidate_count = 1

                            self._log(
                                f"Transition candidate: {stable_status} -> {candidate_status} "
                                f"({candidate_count}/{self.status_confirm_checks})"
                            )

                            if candidate_count >= self.status_confirm_checks:
                                old_status = stable_status
                                new_status = candidate_status
                                stable_status = new_status
                                candidate_status = None
                                candidate_count = 0
                                self._log(f"✓ STATUS CHANGE CONFIRMED: {old_status} -> {new_status}")
                                monitor.save_status(new_status, old_status)
                                self.handle_status_change(new_status, old_status)

                        # Always log state for debugging on-device.
                        self._log(
                            f"[AC Status] Observed={observed_status}, Stable={stable_status}, "
                            f"Candidate={candidate_status}, Count={candidate_count}"
                        )

                        if (
                            self.last_notified_status is not None
                            and self.last_notified_status != stable_status
                            and self.pending_notification_status is None
                        ):
                            # Recovery path: stable power status and notification status diverge.
                            self._log(
                                "Notification state mismatch: "
                                f"stable={stable_status}, last_notified={self.last_notified_status}"
                            )
                            recovery_result = self._send_notification_with_retries(stable_status, attempts=2)
                            self._log(f"Recovery notification result: {recovery_result}")
                            if recovery_result:
                                self.last_notified_status = stable_status
                                self._save_last_notified_status(stable_status)
                            else:
                                self.pending_notification_status = stable_status
                        
                        # Periodic WiFi health check
                        wifi_check_interval += 1
                        if wifi_check_interval >= wifi_check_frequency:
                            try:
                                # Always log WiFi checks
                                wifi_connected = self.wifi_manager.reconnect_if_needed(debug=True, quick=True)
                                self._log(f"WiFi connection state: {'connected' if wifi_connected else 'not connected'}")

                                # Retry a pending notification once WiFi is back.
                                if self.pending_notification_status is not None:
                                    self._log(f"Retrying pending notification: {self.pending_notification_status}")
                                    pending_ok = self._send_notification_with_retries(
                                        self.pending_notification_status,
                                        attempts=2
                                    )
                                    self._log(f"Pending notification result: {pending_ok}")
                                    if pending_ok:
                                        self.last_notified_status = self.pending_notification_status
                                        self._save_last_notified_status(self.pending_notification_status)
                                        self.pending_notification_status = None
                            except Exception as e:
                                self._log(f"WiFi check error (continuing anyway): {e}")
                            wifi_check_interval = 0
                        
                        last_battery_check = current_time
                    
                except Exception as e:
                    if self.debug:
                        print(f"Error in loop iteration: {e}")
                    # Continue running instead of crashing
                
                # Sleep 0.1 seconds for smooth LED blinking without blocking battery checks
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("Shutting down...")
            self.cleanup()
        except Exception as e:
            print(f"Error in main loop: {e}")
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        if self.debug:
            print("Cleaning up resources...")
        self.led.off()
        self.wifi_manager.disconnect()
        print("Shutdown complete")

# Entry point
if __name__ == "__main__":
    with open("config.json", 'r') as _f:
        _cfg = json.load(_f)

    # Configurable startup mode:
    # - auto (default): try I2C, then fallback monitors
    # - i2c/chg/manual: force a specific monitor
    startup_mode = _cfg.get("monitor_mode", "auto")
    app = BatteryTrackerApp(mode=startup_mode)
    app.run()
