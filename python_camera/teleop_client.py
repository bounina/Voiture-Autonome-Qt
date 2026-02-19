#!/usr/bin/env python3
"""
teleop_client.py — Client de téléopération RC (PC Windows).

Utilise l'API Windows GetAsyncKeyState pour détecter les touches simultanées
sans bloquer le flux vidéo (zéro hook, zéro thread, zéro latence).

Contrôles :
  Z = accélérer (rampe progressive, kick-start au démarrage)
  S = reculer
  Q = tourner à gauche      D = tourner à droite
  Z+Q / Z+D = avancer ET tourner en même temps
  ESPACE = arrêt d'urgence
  T = test servo (cycle angles)
  R = recentrer direction
  O = overlay parking on/off
  ESC = quitter

Dépendances : pip install opencv-python numpy

Usage :
    python teleop_client.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import ctypes
import socket
import struct
import sys
import threading
import time

import cv2
import numpy as np

# ======== KEYBOARD — Windows GetAsyncKeyState (zero overhead) ========
_user32 = ctypes.windll.user32  # type: ignore[attr-defined]

# Virtual-key codes for AZERTY layout
_VK = {
    'z': 0x5A, 's': 0x53, 'q': 0x51, 'd': 0x44,
    'space': 0x20, 'esc': 0x1B,
    't': 0x54, 'r': 0x52, 'o': 0x4F,
}

def is_key(name: str) -> bool:
    """Check if a key is currently held down (direct Windows API, non-blocking)."""
    vk = _VK.get(name)
    if vk is None:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

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

# ======== OVERLAY PARKING ========
# Distances en pixels (proportionnelles à la hauteur de l'image)
# Zone verte = loin, jaune = moyen, rouge = proche
OVERLAY_COLORS = {
    "green":  (0, 200, 80),
    "yellow": (0, 220, 255),
    "red":    (0, 50, 255),
    "guide":  (255, 255, 255),
    "marker": (200, 200, 200),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RC-style teleoperation client.")
    parser.add_argument("--pi-ip", required=True, help="IP of the Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    parser.add_argument("--cmd-port", type=int, default=8884)
    parser.add_argument("--car-width-cm", type=float, default=20.0,
                        help="Largeur du véhicule en cm (default: 20)")
    parser.add_argument("--overlay", action="store_true", default=True,
                        help="Afficher l'overlay parking au démarrage")
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
             video_ok: bool, cmd_ok: bool, throttle_state: str) -> None:
    """Draw HUD in-place (no copy)."""
    h, w = frame.shape[:2]

    # Dark bar (lightweight: just draw a filled rect with low alpha)
    sub = frame[0:130, 0:w]
    sub[:] = (sub * 0.4 + np.array([20, 20, 20]) * 0.6).astype(np.uint8)

    # Status
    vid_color = (0, 255, 0) if video_ok else (0, 0, 255)
    cmd_color = (0, 255, 0) if cmd_ok else (0, 0, 255)
    cv2.putText(frame, f"FPS: {fps:.0f}", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, f"VIDEO: {'OK' if video_ok else 'LOST'}", (150, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, vid_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"CMD: {'OK' if cmd_ok else 'DISCONN'}", (370, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, cmd_color, 2, cv2.LINE_AA)

    # Speed
    speed_pct = abs(speed) / MAX_FWD_SPEED * 100
    speed_color = (0, 255, 0) if speed > 0 else ((0, 100, 255) if speed < 0 else (200, 200, 200))
    cv2.putText(frame, f"Speed: {speed_pct:.0f}% ({throttle_state})", (10, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, speed_color, 2, cv2.LINE_AA)

    # Angle
    cv2.putText(frame, f"Angle: {angle:+.2f}", (10, 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    # Steering bar
    bar_cx, bar_y, bar_hw = w // 2, 118, 150
    cv2.line(frame, (bar_cx - bar_hw, bar_y), (bar_cx + bar_hw, bar_y),
             (100, 100, 100), 3, cv2.LINE_AA)
    needle_x = int(bar_cx + angle * bar_hw)
    cv2.circle(frame, (needle_x, bar_y), 8, (0, 200, 255), -1, cv2.LINE_AA)

    # Help
    cv2.putText(frame, "Z:Accel S:Recule Q+D:Direction ESPACE:Stop O:Overlay ESC:Quit",
                (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)


def draw_parking_overlay(frame: np.ndarray, steering: float,
                         car_width_ratio: float = 0.30) -> None:
    """Draw OEM-style parking overlay in-place (no copy)."""
    h, w = frame.shape[:2]
    cx = w // 2
    n_samples = 40  # reduced for performance

    zone_bottom = h
    red_top     = int(h * 0.80)
    yellow_top  = int(h * 0.65)
    green_top   = int(h * 0.50)
    half_car = int(w * car_width_ratio / 2)

    # ── Colored zones (draw directly with low-alpha blend on ROI) ──
    # Red zone
    roi_red = frame[red_top:zone_bottom, cx - half_car:cx + half_car]
    if roi_red.size > 0:
        roi_red[:] = cv2.addWeighted(roi_red, 0.85, np.full_like(roi_red, OVERLAY_COLORS["red"]), 0.15, 0)

    # Yellow zone (approximate as rectangle)
    spread_y = int(half_car * 1.05)
    y_left = min(cx - spread_y, cx - half_car)
    y_right = max(cx + spread_y, cx + half_car)
    roi_yellow = frame[yellow_top:red_top, y_left:y_right]
    if roi_yellow.size > 0:
        roi_yellow[:] = cv2.addWeighted(roi_yellow, 0.85, np.full_like(roi_yellow, OVERLAY_COLORS["yellow"]), 0.15, 0)

    # Green zone
    spread_g = int(half_car * 1.12)
    g_left = min(cx - spread_g, y_left)
    g_right = max(cx + spread_g, y_right)
    roi_green = frame[green_top:yellow_top, g_left:g_right]
    if roi_green.size > 0:
        roi_green[:] = cv2.addWeighted(roi_green, 0.85, np.full_like(roi_green, OVERLAY_COLORS["green"]), 0.15, 0)

    # ── Guide lines (vehicle width) ──
    left_pts = np.empty((n_samples, 2), dtype=np.int32)
    right_pts = np.empty((n_samples, 2), dtype=np.int32)
    for i in range(n_samples):
        t = i / (n_samples - 1)
        y = int(zone_bottom - t * (zone_bottom - green_top))
        spread = half_car * (1.0 + t * 0.15)
        left_pts[i] = (int(cx - spread), y)
        right_pts[i] = (int(cx + spread), y)
    cv2.polylines(frame, [left_pts], False, OVERLAY_COLORS["guide"], 2, cv2.LINE_AA)
    cv2.polylines(frame, [right_pts], False, OVERLAY_COLORS["guide"], 2, cv2.LINE_AA)

    # ── Distance markers ──
    for y_frac, label, color in [(0.85, "10cm", OVERLAY_COLORS["red"]),
                                  (0.75, "20cm", OVERLAY_COLORS["yellow"]),
                                  (0.65, "30cm", OVERLAY_COLORS["yellow"]),
                                  (0.55, "40cm", OVERLAY_COLORS["green"])]:
        y_px = int(h * y_frac)
        t = (zone_bottom - y_px) / max(1, zone_bottom - green_top)
        sp = half_car * (1.0 + t * 0.15)
        xl, xr = int(cx - sp), int(cx + sp)
        cv2.line(frame, (xl, y_px), (xr, y_px), color, 1, cv2.LINE_AA)
        cv2.putText(frame, label, (xr + 5, y_px + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1, cv2.LINE_AA)

    # ── Dynamic trajectory curves ──
    steer_norm = max(-1.0, min(1.0, steering))
    if abs(steer_norm) > 0.02:
        tl = np.empty((n_samples, 2), dtype=np.int32)
        tr = np.empty((n_samples, 2), dtype=np.int32)
        tc = np.empty((n_samples, 2), dtype=np.int32)
        for i in range(n_samples):
            t = i / (n_samples - 1)
            y = int(zone_bottom - t * (zone_bottom - green_top))
            x_off = int(steer_norm * (t ** 2) * w * 0.25)
            spread = half_car * (1.0 + t * 0.15)
            tl[i] = (int(cx - spread + x_off), y)
            tr[i] = (int(cx + spread + x_off), y)
            tc[i] = (cx + x_off, y)
        cv2.polylines(frame, [tl], False, (0, 180, 255), 2, cv2.LINE_AA)
        cv2.polylines(frame, [tr], False, (0, 180, 255), 2, cv2.LINE_AA)
        cv2.polylines(frame, [tc], False, (255, 255, 0), 1, cv2.LINE_AA)


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

    # Video receiver thread
    video = VideoReceiver(args.pi_ip, args.video_port)
    video.start()

    # Command connection
    cmd_sock = connect_cmd(args.pi_ip, args.cmd_port)
    cmd_ok = cmd_sock is not None

    # Shared state (accessed from control thread + display thread)
    state_lock = threading.Lock()
    state = {
        "speed": 0.0,
        "angle": 0.0,
        "tstate": "STOP",
        "cmd_ok": cmd_ok,
        "show_overlay": args.overlay,
        "quit": False,
    }
    car_w_ratio = args.car_width_cm / 65.0

    # ── Control thread (keyboard + commands, 30 Hz) ──
    def control_loop():
        nonlocal cmd_sock, cmd_ok
        speed = 0.0
        angle = 0.0
        show_overlay = args.overlay
        test_angles = [-1.0, -0.5, 0.0, 0.5, 1.0]
        test_idx = -1
        t_prev = False
        o_prev = False
        last_cmd_time = 0.0
        CMD_INTERVAL = 0.05

        while not state["quit"]:
            tick_start = time.perf_counter()
            throttle_active = False

            if is_key('esc'):
                send_command(cmd_sock, "TELEOP:STOP")
                with state_lock:
                    state["quit"] = True
                break

            if is_key('space'):
                speed = 0.0
                angle = 0.0
                send_command(cmd_sock, "TELEOP:STOP")
            else:
                if is_key('z'):
                    if abs(speed) < DEAD_ZONE:
                        speed = KICK_START
                    else:
                        speed = min(speed + ACCEL_STEP, MAX_FWD_SPEED)
                    throttle_active = True

                if is_key('s'):
                    if abs(speed) < DEAD_ZONE:
                        speed = -KICK_START
                    else:
                        speed = max(speed - ACCEL_STEP, MAX_BWD_SPEED)
                    throttle_active = True

                if is_key('q'):
                    angle = max(-MAX_ANGLE, angle - ANGLE_STEP)
                if is_key('d'):
                    angle = min(MAX_ANGLE, angle + ANGLE_STEP)

                # Test servo (edge detection)
                t_now = is_key('t')
                if t_now and not t_prev:
                    test_idx = (test_idx + 1) % len(test_angles)
                    angle = test_angles[test_idx]
                    speed = 0.0
                t_prev = t_now

                if is_key('r'):
                    angle = 0.0
                    test_idx = -1

                o_now = is_key('o')
                if o_now and not o_prev:
                    show_overlay = not show_overlay
                o_prev = o_now

            # Auto deceleration
            if not throttle_active:
                speed *= DECEL_FACTOR
                if abs(speed) < DEAD_ZONE:
                    speed = 0.0
                if angle > 0.01:
                    angle = max(0.0, angle - ANGLE_RETURN)
                elif angle < -0.01:
                    angle = min(0.0, angle + ANGLE_RETURN)

            # Throttle state
            if abs(speed) < DEAD_ZONE:
                tstate = "STOP"
            elif speed > 0:
                tstate = "FWD"
            else:
                tstate = "BWD"

            # Publish state for display thread
            with state_lock:
                state["speed"] = speed
                state["angle"] = angle
                state["tstate"] = tstate
                state["show_overlay"] = show_overlay

            # Send command
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
                with state_lock:
                    state["cmd_ok"] = cmd_ok

            # 30 Hz rate limit
            elapsed = time.perf_counter() - tick_start
            remain = (1.0 / CONTROL_HZ) - elapsed
            if remain > 0:
                time.sleep(remain)

    # Start control thread
    ctrl_thread = threading.Thread(target=control_loop, daemon=True)
    ctrl_thread.start()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    print("[TELEOP] Ready. Controls: Z/S/Q/D + simultaneous. O=overlay. ESC=quit.")

    # ── Main thread: display only (as fast as frames arrive) ──
    try:
        while not state["quit"]:
            frame = video.get_frame()
            if frame is not None:
                # Read shared state (quick snapshot)
                with state_lock:
                    s = state.copy()

                if s["show_overlay"]:
                    draw_parking_overlay(frame, s["angle"], car_w_ratio)
                draw_hud(frame, video.fps, s["speed"], s["angle"],
                         video.connected, s["cmd_ok"], s["tstate"])
                cv2.imshow(WINDOW_NAME, frame)

            # Pump window events; ~33ms wait = ~30 FPS display
            if cv2.waitKey(15) & 0xFF == 27:  # ESC via OpenCV too
                with state_lock:
                    state["quit"] = True
                break

    except KeyboardInterrupt:
        send_command(cmd_sock, "TELEOP:STOP")
    finally:
        with state_lock:
            state["quit"] = True
        ctrl_thread.join(timeout=2.0)
        video.stop()
        if cmd_sock:
            cmd_sock.close()
        cv2.destroyAllWindows()
        print("[TELEOP] Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
