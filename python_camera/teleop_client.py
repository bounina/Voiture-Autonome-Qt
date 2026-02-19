#!/usr/bin/env python3
"""
teleop_client.py — Client de téléopération RC (PC Windows).

Utilise la bibliothèque 'keyboard' pour détecter les touches simultanées
et éviter de bloquer le flux vidéo.

Contrôles :
  Z = accélérer (rampe progressive, kick-start au démarrage)
  S = reculer
  Q = tourner à gauche      D = tourner à droite
  Z+Q / Z+D = avancer ET tourner en même temps
  ESPACE = arrêt d'urgence
  T = test servo (cycle angles)
  R = recentrer direction
  ESC = quitter

Dépendances : pip install opencv-python numpy keyboard

Usage :
    python teleop_client.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
import time

import cv2
import numpy as np

try:
    import keyboard
except ImportError:
    print("ERREUR: Installe le module keyboard :")
    print("  pip install keyboard")
    sys.exit(1)

WINDOW_NAME = "Teleop - Voiture Autonome"

# ======== PARAMÈTRES DE CONDUITE RC ========
MAX_FWD_SPEED  = 0.18     # vitesse max avant
MAX_BWD_SPEED  = -0.12    # vitesse max arrière
ACCEL_STEP     = 0.012    # accélération par tick normal
KICK_START     = 0.06     # boost initial pour vaincre l'inertie
DECEL_FACTOR   = 0.90     # décélération auto (×0.90 par tick)
DEAD_ZONE      = 0.015    # en-dessous, on met à 0

ANGLE_STEP     = 0.08     # incrément direction par tick
MAX_ANGLE      = 1.0
ANGLE_RETURN   = 0.04     # rappel au centre par tick

CONTROL_HZ     = 30       # fréquence de la boucle de contrôle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RC-style teleoperation client.")
    parser.add_argument("--pi-ip", required=True, help="IP of the Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    parser.add_argument("--cmd-port", type=int, default=8884)
    return parser.parse_args()


def recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


def connect_video(ip: str, port: int) -> socket.socket:
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((ip, port))
            s.settimeout(2.0)
            print(f"[VIDEO] Connected to {ip}:{port}")
            return s
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            print(f"[VIDEO] Waiting ({e})... retry in 2s")
            time.sleep(2)


def connect_cmd(ip: str, port: int) -> socket.socket | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((ip, port))
        s.setblocking(False)
        print(f"[CMD] Connected to {ip}:{port}")
        return s
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print(f"[CMD] Could not connect: {e}")
        return None


def send_command(sock: socket.socket | None, cmd: str) -> bool:
    if sock is None:
        return False
    try:
        sock.sendall((cmd + "\n").encode("utf-8"))
        return True
    except (BrokenPipeError, ConnectionResetError, BlockingIOError, OSError):
        return False


def draw_hud(frame: np.ndarray, fps: float, speed: float, angle: float,
             video_ok: bool, cmd_ok: bool, throttle_state: str) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]

    # Dark bar
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 130), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, out, 0.4, 0, out)

    # Status
    vid_color = (0, 255, 0) if video_ok else (0, 0, 255)
    cmd_color = (0, 255, 0) if cmd_ok else (0, 0, 255)
    cv2.putText(out, f"FPS: {fps:.0f}", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(out, f"VIDEO: {'OK' if video_ok else 'LOST'}", (150, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, vid_color, 2, cv2.LINE_AA)
    cv2.putText(out, f"CMD: {'OK' if cmd_ok else 'DISCONN'}", (370, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, cmd_color, 2, cv2.LINE_AA)

    # Speed
    speed_pct = abs(speed) / MAX_FWD_SPEED * 100
    speed_color = (0, 255, 0) if speed > 0 else ((0, 100, 255) if speed < 0 else (200, 200, 200))
    cv2.putText(out, f"Speed: {speed_pct:.0f}% ({throttle_state})", (10, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, speed_color, 2, cv2.LINE_AA)

    # Angle
    cv2.putText(out, f"Angle: {angle:+.2f}", (10, 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    # Steering bar
    bar_cx, bar_y, bar_hw = w // 2, 118, 150
    cv2.line(out, (bar_cx - bar_hw, bar_y), (bar_cx + bar_hw, bar_y),
             (100, 100, 100), 3, cv2.LINE_AA)
    needle_x = int(bar_cx + angle * bar_hw)
    cv2.circle(out, (needle_x, bar_y), 8, (0, 200, 255), -1, cv2.LINE_AA)

    # Help
    cv2.putText(out, "Z:Accel S:Recule Q+D:Direction ESPACE:Stop T:Test R:Centre ESC:Quit",
                (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)

    return out


class VideoReceiver(threading.Thread):
    """Thread qui reçoit les frames vidéo sans bloquer la boucle principale."""

    def __init__(self, ip: str, port: int):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.frame: np.ndarray | None = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self.fps = 0.0

    def run(self):
        sock = connect_video(self.ip, self.port)
        self.connected = True
        prev_t = time.perf_counter()

        while self.running:
            try:
                header = recv_exact(sock, 4)
                frame_size = struct.unpack(">I", header)[0]
                if frame_size > 5_000_000:
                    raise ConnectionError("Frame too large")
                jpeg_data = recv_exact(sock, frame_size)

                decoded = cv2.imdecode(
                    np.frombuffer(jpeg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if decoded is not None:
                    with self.lock:
                        self.frame = decoded

                    now = time.perf_counter()
                    dt = now - prev_t
                    prev_t = now
                    if dt > 0:
                        self.fps = 0.9 * self.fps + 0.1 / dt

            except (ConnectionError, socket.timeout, OSError):
                print("[VIDEO] Lost, reconnecting...")
                self.connected = False
                try:
                    sock.close()
                except Exception:
                    pass
                sock = connect_video(self.ip, self.port)
                self.connected = True
                prev_t = time.perf_counter()

    def get_frame(self) -> np.ndarray | None:
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False


def main() -> int:
    args = parse_args()

    # Video receiver thread (non-bloquant)
    video = VideoReceiver(args.pi_ip, args.video_port)
    video.start()

    # Command connection
    cmd_sock = connect_cmd(args.pi_ip, args.cmd_port)
    cmd_ok = cmd_sock is not None

    # State
    speed = 0.0
    angle = 0.0
    test_angles = [-1.0, -0.5, 0.0, 0.5, 1.0]
    test_idx = -1

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    print("[TELEOP] Ready. Controls: Z/S/Q/D + simultaneous. ESC=quit.")

    tick_interval = 1.0 / CONTROL_HZ
    last_cmd_time = 0.0
    CMD_INTERVAL = 0.05  # 20 Hz max commands

    try:
        while True:
            tick_start = time.perf_counter()

            # ── Keyboard (simultaneous via keyboard library) ──
            throttle_active = False

            if keyboard.is_pressed('esc'):
                send_command(cmd_sock, "TELEOP:STOP")
                break

            if keyboard.is_pressed('space'):
                speed = 0.0
                angle = 0.0
                send_command(cmd_sock, "TELEOP:STOP")

            else:
                # Accélération / décélération
                if keyboard.is_pressed('z'):
                    if abs(speed) < DEAD_ZONE:
                        speed = KICK_START  # boost initial
                    else:
                        speed = min(speed + ACCEL_STEP, MAX_FWD_SPEED)
                    throttle_active = True

                if keyboard.is_pressed('s'):
                    if abs(speed) < DEAD_ZONE:
                        speed = -KICK_START
                    else:
                        speed = max(speed - ACCEL_STEP, MAX_BWD_SPEED)
                    throttle_active = True

                # Direction (peut être combiné avec Z/S !)
                if keyboard.is_pressed('q'):
                    angle = max(-MAX_ANGLE, angle - ANGLE_STEP)

                if keyboard.is_pressed('d'):
                    angle = min(MAX_ANGLE, angle + ANGLE_STEP)

                # Test servo
                if keyboard.is_pressed('t'):
                    test_idx = (test_idx + 1) % len(test_angles)
                    angle = test_angles[test_idx]
                    speed = 0.0
                    time.sleep(0.3)  # anti-rebond

                if keyboard.is_pressed('r'):
                    angle = 0.0
                    test_idx = -1

            # Décélération auto si aucune touche gaz
            if not throttle_active:
                speed *= DECEL_FACTOR
                if abs(speed) < DEAD_ZONE:
                    speed = 0.0
                # Rappel direction au centre (léger)
                if angle > 0.01:
                    angle = max(0.0, angle - ANGLE_RETURN)
                elif angle < -0.01:
                    angle = min(0.0, angle + ANGLE_RETURN)

            # Throttle state pour HUD
            if abs(speed) < DEAD_ZONE:
                tstate = "STOP"
            elif speed > 0:
                tstate = "FWD"
            else:
                tstate = "BWD"

            # ── Send command ──
            now = time.perf_counter()
            if now - last_cmd_time >= CMD_INTERVAL:
                cmd = f"TELEOP:DRIVE,{speed:.4f},{angle:.4f}"
                ok = send_command(cmd_sock, cmd)
                last_cmd_time = now
                if not ok and cmd_ok:
                    print("[CMD] Reconnecting...")
                    cmd_sock = connect_cmd(args.pi_ip, args.cmd_port)
                    cmd_ok = cmd_sock is not None
                elif ok:
                    cmd_ok = True

            # ── Display ──
            frame = video.get_frame()
            if frame is not None:
                view = draw_hud(frame, video.fps, speed, angle,
                                video.connected, cmd_ok, tstate)
                cv2.imshow(WINDOW_NAME, view)

            # cv2.waitKey(1) ONLY for window events, NOT for key capture
            if cv2.waitKey(1) == -1:
                pass  # window event processed

            # Rate limit control loop
            elapsed = time.perf_counter() - tick_start
            sleep_time = tick_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        send_command(cmd_sock, "TELEOP:STOP")
    finally:
        video.stop()
        if cmd_sock:
            cmd_sock.close()
        cv2.destroyAllWindows()
        print("[TELEOP] Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
