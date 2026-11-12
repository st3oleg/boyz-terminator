#!/usr/bin/env python3
"""
Modulo Controllo Motori Cytron MDDS30 - INDEPENDENT BOTH (DIP: 00111111)
- RC1 (Motore SX) -> GPIO 23 (Pin Fisico 16)
- RC2 (Motore DX) -> GPIO 19 (Pin Fisico 35)

PWM RC standard a 50 Hz:
  1000 us = -100% (Retro max)
  1500 us = 0% (Neutro / Stop)
  2000 us = +100% (Avanti max)
"""

import time
import lgpio

class MotorDriver:
    NEUTRO_US = 1500
    START_PCT = 20  # Spunto iniziale consigliato da fermo

    def __init__(self, pin_sx: int = 23, pin_dx: int = 19, chip_num: int = 0):
        self.pin_sx = pin_sx
        self.pin_dx = pin_dx
        self.chip_num = chip_num
        self.chip = None
        self.pct_sx = 0
        self.pct_dx = 0

        self._init_gpio()

    def _init_gpio(self):
        """Inizializza la linea GPIO e i pin del Cytron."""
        try:
            self.chip = lgpio.gpiochip_open(self.chip_num)
        except Exception:
            self.chip = lgpio.gpiochip_open(4)

        lgpio.gpio_claim_output(self.chip, self.pin_sx, 0)
        lgpio.gpio_claim_output(self.chip, self.pin_dx, 0)
        self.stop()

    def _pct_to_us(self, pct: int) -> int:
        """Converte percentuale (-100..+100) nei microsecondi d'impulso."""
        clamped = max(-100, min(100, int(pct)))
        return int(self.NEUTRO_US + (clamped * 5))

    def set_motors(self, pct_sx: int, pct_dx: int):
        """
        Imposta direttamente le percentuali sui due motori:
        - pct_sx: -100 .. +100
        - pct_dx: -100 .. +100
        """
        self.pct_sx = max(-100, min(100, int(pct_sx)))
        self.pct_dx = max(-100, min(100, int(pct_dx)))

        us_sx = self._pct_to_us(self.pct_sx)
        us_dx = self._pct_to_us(self.pct_dx)

        lgpio.tx_servo(self.chip, self.pin_sx, us_sx, 50)
        lgpio.tx_servo(self.chip, self.pin_dx, us_dx, 50)

    def drive(self, throttle: int, steering: int):
        """
        Controllo differenziale (Arcade Drive):
        - throttle: -100 (retro) .. +100 (avanti)
        - steering: -100 (sinistra) .. +100 (destra)
        """
        sx = throttle + steering
        dx = throttle - steering

        mag = max(abs(sx), abs(dx))
        if mag > 100:
            sx = int((sx / mag) * 100)
            dx = int((dx / mag) * 100)

        self.set_motors(sx, dx)

    def stop(self):
        """Porta entrambi i motori a 1500 us (neutro immediato)."""
        self.set_motors(0, 0)

    def close(self):
        """Arresta i motori e rilascia il chip GPIO."""
        self.stop()
        time.sleep(0.1)
        try:
            lgpio.tx_pwm(self.chip, self.pin_sx, 0, 0)
            lgpio.tx_pwm(self.chip, self.pin_dx, 0, 0)
        except Exception:
            pass
        if self.chip is not None:
            lgpio.gpiochip_close(self.chip)
            self.chip = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    print("Test autonomo motor.py...")
    
    with MotorDriver() as motors:
        print("Avanti 20% per 1.5s...")
        motors.set_motors(20, 20)
        time.sleep(1.5)
        print("Arresto.")
        motors.stop()
        time.sleep(0.5)
    
    print("Fine test.")
