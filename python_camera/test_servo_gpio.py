#!/usr/bin/env python3
"""
test_servo_gpio.py — Test script to find which GPIO the servo is connected to.

Tests both PWM channels available from the pwm-2chan overlay.
Run on the Pi with sudo. Stop the C++ app first (Ctrl+C).

Usage:
    sudo python3 test_servo_gpio.py
"""
import time
import os
import sys

PWM_BASE = "/sys/class/pwm/pwmchip0"
PERIOD_NS = 20_000_000   # 50 Hz (standard servo)
CENTER_NS = 1_500_000    # 1500 µs = centre
LEFT_NS   = 1_000_000    # 1000 µs = gauche max
RIGHT_NS  = 2_000_000    # 2000 µs = droite max

def write_file(path, value):
    """Write a value to a sysfs file."""
    try:
        with open(path, 'w') as f:
            f.write(str(value))
        return True
    except Exception as e:
        print(f"  [ERREUR] {path}: {e}")
        return False

def test_channel(channel):
    """Test a single PWM channel with a servo sweep."""
    pwm_dir = f"{PWM_BASE}/pwm{channel}"
    export_file = f"{PWM_BASE}/export"

    print(f"\n{'='*50}")
    print(f"  TEST CANAL {channel} ({pwm_dir})")
    print(f"{'='*50}")

    # Export the channel
    if not os.path.exists(pwm_dir):
        print(f"  Exporting channel {channel}...")
        if not write_file(export_file, channel):
            print(f"  IMPOSSIBLE d'exporter le canal {channel}")
            return
        time.sleep(0.3)

    if not os.path.exists(pwm_dir):
        print(f"  Le canal {channel} n'existe pas après export.")
        return

    # Set period
    print(f"  Period = {PERIOD_NS} ns (50 Hz)")
    write_file(f"{pwm_dir}/period", PERIOD_NS)
    time.sleep(0.1)

    # Enable
    write_file(f"{pwm_dir}/enable", 1)
    time.sleep(0.1)

    # Sweep test
    positions = [
        ("CENTRE", CENTER_NS),
        ("GAUCHE", LEFT_NS),
        ("CENTRE", CENTER_NS),
        ("DROITE", RIGHT_NS),
        ("CENTRE", CENTER_NS),
    ]

    for name, duty in positions:
        print(f"  -> {name}: duty = {duty} ns ({duty//1000} µs)")
        write_file(f"{pwm_dir}/duty_cycle", duty)
        time.sleep(1.0)  # 1 seconde par position

    # Disable
    write_file(f"{pwm_dir}/enable", 0)
    print(f"  Canal {channel} désactivé.")

    # Ask user
    print()
    response = input("  >>> Les roues ont bougé ? (o/n) : ").strip().lower()
    if response == 'o':
        print(f"\n  ✅ TROUVÉ ! Le servo est sur le canal {channel}")
        return True
    return False


def main():
    if os.geteuid() != 0:
        print("❌ Ce script doit être lancé avec sudo !")
        print("   sudo python3 test_servo_gpio.py")
        sys.exit(1)

    print("=" * 50)
    print("  TEST SERVO — Recherche du bon canal PWM")
    print("=" * 50)
    print()
    print("Configuration actuelle du dtoverlay pwm-2chan:")
    print("  Canal 0 → GPIO 12 (pin physique 32)")
    print("  Canal 1 → GPIO 13 (pin physique 33)")
    print()
    print("⚠️  Arrête le programme C++ (Ctrl+C) avant de lancer ce test !")
    print()
    input("Appuie sur Entrée pour commencer...")

    # Test channel 0 (GPIO 12)
    found = test_channel(0)
    if found:
        print("\n" + "=" * 50)
        print("  Le servo est sur GPIO 12 (canal 0)")
        print("  Le code C++ utilise déjà le bon canal !")
        print("=" * 50)
        return

    # Test channel 1 (GPIO 13)
    found = test_channel(1)
    if found:
        print("\n" + "=" * 50)
        print("  Le servo est sur GPIO 13 (canal 1)")
        print("  → Change dans materielreel.h : direction{1,...}")
        print("=" * 50)
        return

    # Neither worked
    print("\n" + "=" * 50)
    print("  ❌ Aucun canal n'a fait bouger les roues !")
    print()
    print("  Le servo est peut-être sur GPIO 18 ou GPIO 19.")
    print("  Pour tester, modifie /boot/firmware/config.txt :")
    print()
    print("  Remplace :")
    print("    dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4")
    print("  Par :")
    print("    dtoverlay=pwm-2chan,pin=18,func=2,pin2=19,func2=2")
    print()
    print("  Puis reboot (sudo reboot) et relance ce script.")
    print("=" * 50)


if __name__ == "__main__":
    main()
