# Battery Tracker

Battery Tracker is a personal home pet project for tracking electricity outages. Running on a Raspberry Pi Pico W/2 W with a Pico-UPS-A, it detects when mains power goes out or is restored and sends a Telegram alert. It reads the UPS-A's INA219 current sensor over I²C and retries alerts if Wi-Fi or Telegram is temporarily unavailable.

The project is written for MicroPython. The UPS-A vendor archive/source is not required at runtime; the project contains its own INA219 access code.

## Hardware

The active configuration is for a **Pico 2 W + Pico-UPS-A**:

| Connection | Pico GPIO / setting | Notes |
| --- | --- | --- |
| UPS-A I²C SDA | GPIO 6 | `i2c_sda_pin` |
| UPS-A I²C SCL | GPIO 7 | `i2c_scl_pin` |
| UPS-A I²C address | `0x43` (decimal `67`) | `i2c_address` |
| UPS-A CHG signal | GPIO 1 | Optional; CHG assistance is disabled in the active config |
| Built-in LED | `"LED"` | Used to indicate Wi-Fi connection activity |

Use the UPS board's intended connection to the Pico and check that the board is powered as expected for I²C readings. The active profile selects `monitor_mode: "i2c"` and has emergency fallback disabled, so startup fails rather than switching monitors if I²C initialization fails. In `"auto"` mode, `strict_i2c` controls whether the normal CHG/manual fallbacks are skipped.

Alternative monitor modes are available for a CHG signal or an external AC-detection circuit. See [Battery detection](#battery-detection) and [CONFIGURATION.md](CONFIGURATION.md) before changing wiring or mode.

## First setup

### Tools and requirements

- Raspberry Pi Pico W or Pico 2 W, Pico-UPS-A, and a USB **data** cable.
- A computer with VS Code and the recommended Pico-W-Go extension, or another MicroPython uploader such as Thonny or `mpremote`.
- A compatible MicroPython firmware installed on the Pico.
- A Wi-Fi network with internet access.
- A Telegram account for creating a bot and obtaining its chat ID.
- The MicroPython `urequests` module on the device; install/upload a compatible copy if the firmware does not provide it.

### Prepare and run

1. Install MicroPython firmware for the board and connect it to the computer over USB.
2. Upload the project files to the Pico's filesystem, preserving the `modules/` directory:
   - `main.py`
   - `config.json`
   - `wifi_config.json`
   - `telegram_config.json`
   - `modules/`
   - `battery_status.json` (optional; the program can initialize without it)
3. Edit `wifi_config.json` with the network name and password.
4. Create a Telegram bot with [@BotFather](https://t.me/BotFather), obtain the bot token and chat ID, and enter them in `telegram_config.json`.
5. Run `main.py` from the editor/uploader and check the serial console for startup and I²C messages. Once it is working, leaving `main.py` at the MicroPython filesystem root makes it the normal application entry point on board startup.

Do not upload the sample placeholders as real credentials. Keep Wi-Fi passwords and Telegram bot tokens private.

## Configuration

The project reads three JSON configuration files from the Pico filesystem. Keep valid JSON syntax: quote string values and do not add trailing commas.

### `config.json` — monitor, timing, and notifications

The checked-in configuration is tuned for I²C on GPIO 6/7. These are the key settings to understand:

| Setting | Current value | Purpose |
| --- | --- | --- |
| `monitor_mode` | `"i2c"` | Selects `"auto"`, `"i2c"`, `"chg"`, or `"manual"` monitoring. |
| `strict_i2c` | `true` | In `"auto"` mode, skip CHG/manual fallback if I²C initialization fails. |
| `allow_emergency_fallback` | `false` | Controls the additional CHG/manual fallback if the selected monitor could not be initialized. |
| `battery_check_interval` | `3` seconds | Interval between power-status checks. |
| `i2c_bus`, `i2c_sda_pin`, `i2c_scl_pin` | `1`, `6`, `7` | I²C bus and Pico pins. |
| `i2c_address`, `i2c_frequency` | `67`, `400000` | INA219 address and I²C clock frequency. |
| `invert_current_polarity` | `false` | Reverse the measured current sign if the board reports the opposite polarity. |
| `i2c_init_retries`, `i2c_init_retry_delay_s` | `5`, `0.7` | I²C initialization retry count and delay. |
| `i2c_current_samples`, `i2c_current_sample_delay_ms` | `5`, `20` | Number of current readings averaged and the delay between them. |
| `discharge_off_threshold_ma` | `-40` | At or below this current, classify mains as OFF. |
| `charge_on_threshold_ma` | `-20` | Candidate ON threshold. |
| `off_to_on_delta_ma` | `15` | Relaxes the ON threshold when recovering from OFF; the effective threshold is the lower of this setting's derived threshold and `charge_on_threshold_ma`. |
| `enable_chg_assist` | `false` | Allow the CHG input to assist the I²C current decision. |
| `chg_pin` | `1` | CHG input GPIO for CHG mode or I²C CHG assistance. |
| `status_confirm_checks` | `1` | Consecutive observations required to accept a state transition. |
| `notification_attempts`, `notification_retry_delay_s` | `3`, `1` | Send attempts and delay between retries. |
| `notify_startup_mismatch` | `true` | Send an alert if the measured startup status differs from the saved status. |
| `debug_mode` | `false` | Suppresses many application diagnostic messages; some modules still print directly. |
| `event_log_enabled` | `false` | Disables appending messages to the on-device event log. |
| `event_log_file` | `"battery_event.log"` | File used when event logging is enabled. |

Additional CHG-mode settings (`chg_on_value`, `chg_debounce_samples`, `chg_sample_delay_ms`, `chg_blink_means_on`, `chg_on_latch_seconds`, `chg_irq_enabled`, `chg_auto_detect_floating`, `chg_floating_use_pulldown`, `chg_presence_mode`, and `chg_pin_pull`) tune CHG polarity, sampling, pulse handling, and floating-input behavior. `chg_calibration_margin_ma` and `chg_assist_off_guard_ma` apply when CHG assistance is enabled. `ac_detection_pin` selects the external input used by manual mode. `led_pin` selects the LED pin.

### `wifi_config.json` — network access

```json
{
  "ssid": "YOUR_WIFI_NAME",
  "password": "YOUR_WIFI_PASSWORD",
  "reconnect_attempts": 5,
  "reconnect_delay": 2
}
```

The application checks Wi-Fi during its monitoring loop and attempts to reconnect when disconnected. Reconnection starts asynchronously and leaves the WLAN active while it associates, so a connection attempt does not block battery polling. If it has not connected after 10 seconds (or the configured reconnect delay, if longer), the next check starts another attempt.

### `telegram_config.json` — alert destination

```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": "YOUR_CHAT_ID",
  "enabled": true,
  "power_on_message": "Electricity turned ON",
  "power_off_message": "Electricity turned OFF"
}
```

Set `power_on_message` and `power_off_message` to customize the text sent when electricity returns or goes out. If either setting is omitted, the default text shown above is used. Start a conversation with the bot (or add it to the intended group) before testing. The bot token is a secret; anyone who obtains it may control the bot. Set `enabled` to `false` to disable Telegram sending without changing the monitor.

The message fields support Unicode, including emoji; the notifier encodes the JSON request body explicitly as UTF-8.

For detailed setup guidance and the extended configuration notes, see [CONFIGURATION.md](CONFIGURATION.md).

## Battery detection

### Active I²C monitor

The active monitor reads the INA219 current several times and averages the samples. Negative current represents discharging and positive current represents charging unless `invert_current_polarity` is enabled. With the current thresholds:

- Current at or below `-40 mA` indicates mains OFF.
- Current at or above the effective ON threshold indicates mains ON. With the current values, the recovery threshold is `-25 mA`.
- Between thresholds, the previous state is retained (hysteresis) to reduce false transitions.

The app also requires the configured number of consecutive matching observations (`status_confirm_checks`) before accepting a new state. In the active configuration CHG assistance is off, so the I²C current decision is used by itself.

### Optional monitor modes

- **CHG** — samples the UPS-A CHG pin (GPIO 1 by default); supports debounce, pulse/latch handling, and floating-input detection.
- **Manual** — reads an external AC-present digital signal (GPIO 2 by default; HIGH means ON).
- **Auto** — tries I²C first. If I²C fails, fallback behavior depends on `strict_i2c` and `allow_emergency_fallback`.

Select the mode in `config.json`. CHG and manual modes need the appropriate signal/wiring; selecting them does not create that hardware connection.

## Wi-Fi, state, and Telegram alerts

- The alert text is configured by `power_on_message` and `power_off_message` in `telegram_config.json`.
- On startup, the app compares the measured status with the saved monitor status. If they differ, it updates the saved status and can notify, controlled by `notify_startup_mismatch`.
- Each confirmed transition is saved in `battery_status.json`. The last successfully notified status is also stored there to help recover after a restart.
- If sending fails, the newest pending status is retained and retried after connectivity checks. Each notification also has a limited retry sequence.
- The built-in LED blinks quickly while connecting and more slowly when connected. It indicates Wi-Fi state, not mains state.

## Logs and troubleshooting

- `event_log_enabled: false` disables the app's on-device event-file logging. It does not erase an existing `battery_event.log`.
- With event logging enabled, each poll records whether Wi-Fi is connected; connection errors and detailed radio messages are still printed to the USB serial console.
- `debug_mode: false` reduces application debug output, but does **not** silence all serial output; monitor, Wi-Fi, LED, and Telegram modules also print status/errors directly.
- **I²C device not found:** check the UPS-A/Pico connection, GPIO 6/7 assignment, address `0x43`, board power, and that compatible MicroPython firmware is running.
- **Status appears reversed:** verify the physical setup and current polarity; change `invert_current_polarity` only if measured current polarity is reversed.
- **No Telegram alert:** confirm Wi-Fi internet access, `telegram_config.json`, bot token/chat ID, and that the bot can message the destination.
- **Wi-Fi does not connect:** verify SSID/password and signal strength.
- **Startup fails on I²C:** with the active strict I²C configuration, check I²C hardware and console output; fallback is intentionally not automatic.

For expanded configuration and troubleshooting details, see [CONFIGURATION.md](CONFIGURATION.md).
