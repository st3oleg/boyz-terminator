#!/usr/bin/env python3
"""
Test Diretto Cytron MDDS30 - INDEPENDENT BOTH (DIP: 00111111)
- RC1 (Motore SX) -> GPIO 19 (Pin Fisico 35)
- RC2 (Motore DX) -> GPIO 23 (Pin Fisico 16)
Controllo a step quantizzati su multipli del 10% (0, 20, 30, 40... 100%).
"""

import os
import sys
import time
import termios
import tty
import select
import threading
import subprocess
import re

# Riduce la latenza Linux assegnando priorità alta al processo
try:
    os.nice(-10)
except Exception:
    pass

try:
    import lgpio
except ImportError:
    print("ERRORE: lgpio non trovato! Esegui: sudo apt install -y python3-lgpio")
    sys.exit(1)

# =========================================================================
# PARAMETRI PERCENTUALE E GRADINI
# =========================================================================
START_PCT = 20  # Primo gradino da fermo per vincere l'attrito (20%)
STEP_PCT  = 10  # Incremento/decremento a ogni pressione tasto (10%)
NEUTRO_US = 1500

PIN_SX = 23  # RC1 -> Motore SX (Pin 35)
PIN_DX = 19  # RC2 -> Motore DX (Pin 16)

# --- 1. RILEVAMENTO CLIENT IP PER IL MONITOR PING ---
def detect_client_ip():
    for var in ("SSH_CLIENT", "SSH_CONNECTION"):
        val = os.environ.get(var)
        if val:
            return val.split()[0]
    try:
        res = subprocess.run(["who", "-m"], stdout=subprocess.PIPE, text=True, timeout=1)
        m = re.search(r"\(([\d\.]+)\)", res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "127.0.0.1"

TARGET_IP = detect_client_ip()
current_ping_str = "CALC..."
is_running = True

def ping_worker():
    global current_ping_str
    while is_running:
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", "1", TARGET_IP],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode == 0:
                m = re.search(r"time=([\d\.]+)\s*ms", res.stdout)
                current_ping_str = f"{float(m.group(1)):.1f}ms" if m else "<1ms"
            else:
                current_ping_str = "LOST"
        except Exception:
            current_ping_str = "ERR"
        time.sleep(0.5)

ping_thread = threading.Thread(target=ping_worker, daemon=True)
ping_thread.start()

# --- 2. INIZIALIZZAZIONE HARDWARE LGPIO ---
chip = None
for c in [0, 4]:
    try:
        chip = lgpio.gpiochip_open(c)
        print(f"[OK] Inizializzato /dev/gpiochip{c}")
        break
    except Exception:
        pass

if chip is None:
    print("ERRORE: Impossibile aprire gpiochip!")
    sys.exit(1)

lgpio.gpio_claim_output(chip, PIN_SX, 0)
lgpio.gpio_claim_output(chip, PIN_DX, 0)

def pct_to_us(pct):
    """Converte una percentuale intera (-100..+100) nei microsecondi esatti."""
    return int(NEUTRO_US + (pct * 5))

def send_motors(pct_sx, pct_dx):
    """Invia gli impulsi PWM corrispondenti alle percentuali impostate."""
    us_sx = pct_to_us(pct_sx)
    us_dx = pct_to_us(pct_dx)
    lgpio.tx_servo(chip, PIN_SX, us_sx, 50)
    lgpio.tx_servo(chip, PIN_DX, us_dx, 50)
    return us_sx, us_dx

# Inizializza entrambi i motori a fermo (0% = 1500 us)
pct_sx = 0
pct_dx = 0
send_motors(pct_sx, pct_dx)

print("\n" + "="*68)
print(f" CYTRON MDDS30 ATTIVO | STEP: {STEP_PCT}% | PARTENZA DA FERMO: {START_PCT}%")
print(f" RC1 (SX) -> GPIO 19  | RC2 (DX) -> GPIO 23 | PING TARGET: {TARGET_IP}")
print("="*68)
print("COMANDI:")
print("  W / Freccia Su   : Avanti (+10%)")
print("  S / Freccia Giù  : Retro   (-10%)")
print("  A / Freccia SX   : Ruota a Sinistra")
print("  D / Freccia DX   : Ruota a Destra")
print("  1                : Solo Motore Sinistro")
print("  2                : Solo Motore Destro")
print("  T                : >>> TEST AUTOMATICO A STEP (0 -> 60%) <<<")
print("  SPAZIO           : STOP IMMEDIATO (0%)")
print("  Q                : Esci dallo script\n")

# --- FUNZIONI DI SCALATA PERFETTAMENTE SIMMETRICHE ---
def step_up(val):
    """Aumenta la percentuale verso +100% passando per i multipli di 10."""
    if val == 0:
        return START_PCT
    elif val == -START_PCT:
        return 0
    elif val < 0:
        return val + STEP_PCT
    else:
        return min(100, val + STEP_PCT)

def step_down(val):
    """Diminuisce la percentuale verso -100% passando per i multipli di 10."""
    if val == 0:
        return -START_PCT
    elif val == START_PCT:
        return 0
    elif val > 0:
        return val - STEP_PCT
    else:
        return max(-100, val - STEP_PCT)

def check_abort_key():
    """Rileva se l'utente preme SPAZIO o Q durante il test a step."""
    rlist, _, _ = select.select([sys.stdin], [], [], 0)
    if rlist:
        k = sys.stdin.read(1).lower()
        if k in (' ', 'q'):
            return k
    return None

def execute_step_test():
    """Rampa a step progressivi a multipli di 10% (0 -> 20 -> 30 -> 40 -> 50 -> 60 -> 0%)."""
    global pct_sx, pct_dx
    step_sequence = [0, 20, 30, 40, 50, 60, 0]
    step_duration = 1.5

    print("\n\n--- TEST A STEP MOTORE SX (RC1 / GPIO 19) ---")
    pct_dx = 0
    send_motors(0, 0)

    for p in step_sequence:
        pct_sx = p
        us_sx, _ = send_motors(pct_sx, 0)
        t_end = time.time() + step_duration
        while time.time() < t_end:
            sys.stdout.write(f"\r[STEP SX] {pct_sx:+3d}% ({us_sx}us) | DX: STOP (0%) | PING: {current_ping_str:<6} ")
            sys.stdout.flush()
            abort = check_abort_key()
            if abort:
                print(f"\n[INTERROTTO DA UTENTE]")
                pct_sx, pct_dx = 0, 0
                send_motors(0, 0)
                return

    time.sleep(0.5)
    print("\n--- TEST A STEP MOTORE DX (RC2 / GPIO 23) ---")
    pct_sx = 0
    send_motors(0, 0)

    for p in step_sequence:
        pct_dx = p
        _, us_dx = send_motors(0, pct_dx)
        t_end = time.time() + step_duration
        while time.time() < t_end:
            sys.stdout.write(f"\rSX: STOP (0%) | [STEP DX] {pct_dx:+3d}% ({us_dx}us) | PING: {current_ping_str:<6} ")
            sys.stdout.flush()
            abort = check_abort_key()
            if abort:
                print(f"\n[INTERROTTO DA UTENTE]")
                pct_sx, pct_dx = 0, 0
                send_motors(0, 0)
                return

    pct_sx, pct_dx = 0, 0
    send_motors(0, 0)
    print("\n--- TEST A STEP COMPLETATO. CONTROLLO MANUALE RIPRISTINATO ---\n")

fd = sys.stdin.fileno()
old_settings = termios.tcgetattr(fd)

try:
    tty.setraw(fd)

    while True:
        rlist, _, _ = select.select([sys.stdin], [], [], 0.05)

        if rlist:
            ch = sys.stdin.read(1)

            if ch == '\x1b':
                r2, _, _ = select.select([sys.stdin], [], [], 0.01)
                if r2:
                    seq = sys.stdin.read(2)
                    if seq == '[A': ch = 'w'
                    elif seq == '[B': ch = 's'
                    elif seq == '[D': ch = 'a'
                    elif seq == '[C': ch = 'd'

            ch = ch.lower()

            if ch == 'q':
                break
            elif ch == ' ':
                pct_sx, pct_dx = 0, 0
            elif ch == 't':
                execute_step_test()
                continue
            elif ch == 'w':
                pct_sx = step_up(pct_sx)
                pct_dx = step_up(pct_dx)
            elif ch == 's':
                pct_sx = step_down(pct_sx)
                pct_dx = step_down(pct_dx)
            elif ch == 'a':
                pct_sx = step_down(pct_sx)
                pct_dx = step_up(pct_dx)
            elif ch == 'd':
                pct_sx = step_up(pct_sx)
                pct_dx = step_down(pct_dx)
            elif ch == '1':
                pct_sx = step_up(pct_sx)
            elif ch == '2':
                pct_dx = step_up(pct_dx)

            send_motors(pct_sx, pct_dx)

        us_sx = pct_to_us(pct_sx)
        us_dx = pct_to_us(pct_dx)
        stato = "STOP" if (pct_sx == 0 and pct_dx == 0) else "RUN "

        sys.stdout.write(
            f"\r[{stato}] SX: {pct_sx:+4d}% ({us_sx}us) | DX: {pct_dx:+4d}% ({us_dx}us) | PING: {current_ping_str:<7} "
        )
        sys.stdout.flush()

except KeyboardInterrupt:
    pass
finally:
    is_running = False
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Arresto sicuro al neutro (1500 us) e rilascio GPIO
    send_motors(0, 0)
    time.sleep(0.2)
    try:
        lgpio.tx_pwm(chip, PIN_SX, 0, 0)
        lgpio.tx_pwm(chip, PIN_DX, 0, 0)
    except Exception:
        pass
    lgpio.gpiochip_close(chip)
    print("\n\nTest terminato. Motori arrestati al neutro.\n")

