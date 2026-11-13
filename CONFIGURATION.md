# Configuration Guide

## WiFi Setup

Edit `wifi_config.json` and replace the placeholders with your actual WiFi credentials:

```json
{
    "ssid": "YOUR_WIFI_SSID",
    "password": "YOUR_WIFI_PASSWORD",
    "reconnect_attempts": 5,
    "reconnect_delay": 2
}
```

**Example:**
```json
{
    "ssid": "MyHomeWiFi",
    "password": "MyPassword123",
    "reconnect_attempts": 5,
    "reconnect_delay": 2
}
```

While monitoring, Wi-Fi reconnect attempts run without blocking battery checks. The Pico leaves the WLAN active while connecting and starts another attempt only after at least 10 seconds, or the configured `reconnect_delay` if it is longer.

## Telegram Setup

Edit `telegram_config.json` and add your Telegram bot token and chat ID:

```json
{
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "chat_id": "YOUR_CHAT_ID_HERE",
    "enabled": true,
    "power_on_message": "Electricity turned ON",
    "power_off_message": "Electricity turned OFF"
}
```

`power_on_message` is sent when electricity returns; `power_off_message` is sent when an outage is detected. Both messages support UTF-8 text, including emoji. If either field is omitted, the default message is used. Set `enabled` to `false` to disable Telegram notifications.

### How to get Telegram credentials:

1. **Create a Telegram Bot:**
   - Talk to @BotFather on Telegram
   - Send `/newbot` and follow the prompts
   - You'll receive a bot token (looks like: `123456789:ABCdefGHIjklmnoPQRstuvWXYZ`)

2. **Get your Chat ID:**
   - Message your bot anything
   - Go to: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Replace `<YOUR_BOT_TOKEN>` with your actual token
   - Find your chat ID in the JSON response (under `message.chat.id`)

**Example:**
```json
{
    "bot_token": "123456789:ABCdefGHIjklmnoPQRstuvWXYZ",
    "chat_id": "987654321"
}
```

## Operating Modes

The app automatically tries these detection methods in order:

1. **I2C Mode** (preferred) — Reads UPS-A via INA219 chip
   - Requires UPS-A to be powered from battery
   - Not active when powered via USB

2. **CHG GPIO Mode** (fallback) — Reads UPS-A CHG signal on GPIO 1
   - Works as backup if I2C fails
   - Simpler than I2C but less detailed

3. **Manual AC Detection** (final fallback) — Reads external AC detection circuit on GPIO 2
   - Requires external hardware circuit to detect mains

### Recommended for stable ON/OFF notifications

Use I2C-based detection first:

```json
{
    "monitor_mode": "i2c",
    "strict_i2c": true,
    "i2c_init_retries": 5,
    "i2c_init_retry_delay_s": 0.7,
    "i2c_current_samples": 5,
    "i2c_current_sample_delay_ms": 20,
    "discharge_off_threshold_ma": -40,
    "charge_on_threshold_ma": -20,
    "off_to_on_delta_ma": 15,
    "enable_chg_assist": true
}
```

- `discharge_off_threshold_ma`: current at or below this value means AC OFF.
- `charge_on_threshold_ma`: current at or above this value means AC ON.
- `off_to_on_delta_ma`: recovery margin from OFF. Effective ON threshold uses the less strict value between
  `charge_on_threshold_ma` and `discharge_off_threshold_ma + off_to_on_delta_ma`.
- Between those values, the app keeps previous state (hysteresis) to avoid false flips.
- `enable_chg_assist`: when `true`, CHG signal can force AC ON if I2C current still looks OFF.
- `i2c_init_retries` / `i2c_init_retry_delay_s`: retry I2C startup before falling back to CHG/manual.
- `allow_emergency_fallback`: when `false`, startup does not silently switch to CHG/manual after I2C failure.

## Debugging

Enable debug mode in `config.json`:

```json
{
    "debug_mode": true
}
```

This will print detailed logs for WiFi, battery detection, and Telegram messages.

For reliable power transition capture, keep `battery_check_interval` low (recommended 2-3 seconds).

For Pico 2W + Pico-UPS-A, use I2C bus settings from the vendor demo:

```json
{
    "i2c_bus": 1,
    "i2c_sda_pin": 6,
    "i2c_scl_pin": 7,
    "i2c_address": 67,
    "invert_current_polarity": true
}
```

### Stable transition detection + on-device event log

You can make power on/off detection more stable and keep logs on the Pico:

```json
{
    "status_confirm_checks": 1,
    "event_log_enabled": true,
    "event_log_file": "battery_event.log",
    "chg_sample_delay_ms": 50,
    "chg_blink_means_on": true
}
```

- `status_confirm_checks`: how many consecutive checks must confirm a new AC state before it is accepted.
  - `1` (recommended with CHG sampling) = fastest reaction
  - `2` = additional filtering, slower reaction
  - `3+` = strongest filtering, slower reaction
- `event_log_enabled`: when `true`, important events are appended to a file on device storage.
- `event_log_file`: path/name of that log file (for example `battery_event.log`).
- `chg_sample_delay_ms`: delay between CHG samples when reading one AC status.
- `chg_blink_means_on`: if `true`, mixed HIGH/LOW CHG samples in one read window are treated as AC ON.
- `chg_on_latch_seconds`: if any CHG HIGH is seen, keep AC state as ON for this many seconds (helps with short/sparse pulses).
- `chg_irq_enabled`: capture CHG rising/falling edges between polling cycles (recommended `true`).
- `chg_auto_detect_floating`: probes CHG with pull-up/pull-down and switches to edge-based logic when input appears floating.
- `chg_floating_use_pulldown`: when floating is detected, force pull-down and treat only recent HIGH pulses as AC ON.
- `chg_presence_mode`: treat any observed CHG HIGH pulse as AC ON; if no HIGH pulse is seen for latch timeout, state is OFF.
- `chg_pin_pull`: CHG input pull mode (`"up"`, `"down"`, or `"none"`). For floating CHG outputs, use `"none"` with auto-detect enabled.
- `chg_on_value`: CHG value that means AC ON. Typical UPS-A uses `1`.
- `notification_attempts`: how many send attempts are made per status event.
- `notification_retry_delay_s`: delay between notification retries.
- `notify_startup_mismatch`: if `true`, sends a notification when saved status differs from measured status on boot.

## Hardware Checklist

- [ ] Pico 2W connected to UPS-A via I2C (GPIO 6=SDA, GPIO 7=SCL) or CHG signal (GPIO 1)
- [ ] LED on GPIO 25 (built-in)
- [ ] WiFi credentials in `wifi_config.json`
- [ ] Telegram bot token and chat ID in `telegram_config.json`
- [ ] UPS-A powered from battery (not USB) for I2C detection to work

## Troubleshooting

**"I2C mode failed"**
- Ensure UPS-A is powered from battery, not USB
- Check GPIO 6/7 connections
- Run `i2c_advanced_test.py` for diagnostics

**"WiFi failed to connect"**
- Verify SSID and password in `wifi_config.json`
- Check WiFi signal strength
- Restart WiFi router if needed

**"Telegram error -2"**
- WiFi must be connected first
- Check bot token and chat ID in `telegram_config.json`
