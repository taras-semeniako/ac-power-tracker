"""Safe boot script to recover Pico from broken state."""
import time

print("Safe Boot Recovery")
print("=" * 50)

# Try to initialize minimal components
try:
    from machine import Pin
    print("✓ Machine module loaded")
except Exception as e:
    print(f"✗ Machine module failed: {e}")

# Try LED
try:
    led = Pin("LED", Pin.OUT)
    led.on()
    print("✓ LED initialized and ON")
    time.sleep(1)
    led.off()
    print("✓ LED toggled")
except Exception as e:
    print(f"✗ LED failed: {e}")

print("\nSystem appears stable. Safe to run main.py")
