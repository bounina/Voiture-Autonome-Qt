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
    overlay_txt = "O:Overlay" if True else ""
    cv2.putText(out, f"Z:Accel S:Recule Q+D:Direction ESPACE:Stop T:Test R:Centre {overlay_txt} ESC:Quit",
                (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)

    return out


def draw_parking_overlay(frame: np.ndarray, steering: float,
                         car_width_ratio: float = 0.30) -> np.ndarray:
    """Draw OEM-style parking overlay with distance zones and dynamic curves.

    Args:
        frame: BGR frame
        steering: normalized steering angle [-1.0, +1.0]
        car_width_ratio: car width as fraction of frame width (~0.30)
    """
    out = frame.copy()
    h, w = out.shape[:2]
    cx = w // 2

    # ── Zone proportions (from bottom of frame) ──
    # Red zone:   bottom 20% of frame
    # Yellow zone: next 15%
    # Green zone:  next 15%
    zone_bottom = h          # bottom of frame
    red_top     = int(h * 0.80)
    yellow_top  = int(h * 0.65)
    green_top   = int(h * 0.50)

    # Car width in pixels
    half_car = int(w * car_width_ratio / 2)

    # ── Draw colored zones (semi-transparent) ──
    overlay_layer = out.copy()

    # Red zone
    pts_red = np.array([
        [cx - half_car, zone_bottom],
        [cx + half_car, zone_bottom],
        [cx + half_car, red_top],
        [cx - half_car, red_top],
    ], np.int32)
    cv2.fillPoly(overlay_layer, [pts_red], OVERLAY_COLORS["red"])

    # Yellow zone (slightly wider at top due to perspective)
    spread_y = int(half_car * 1.05)
    pts_yellow = np.array([
        [cx - half_car, red_top],
        [cx + half_car, red_top],
        [cx + spread_y, yellow_top],
        [cx - spread_y, yellow_top],
    ], np.int32)
    cv2.fillPoly(overlay_layer, [pts_yellow], OVERLAY_COLORS["yellow"])

    # Green zone (wider still)
    spread_g = int(half_car * 1.12)
    pts_green = np.array([
        [cx - spread_y, yellow_top],
        [cx + spread_y, yellow_top],
        [cx + spread_g, green_top],
        [cx - spread_g, green_top],
    ], np.int32)
    cv2.fillPoly(overlay_layer, [pts_green], OVERLAY_COLORS["green"])

    # Blend zones
    cv2.addWeighted(overlay_layer, 0.18, out, 0.82, 0, out)

    # ── Guide lines (vehicle width, fixed) ──
    # Left guide
    left_pts = []
    right_pts = []
    n_samples = 60
    for i in range(n_samples):
        t = i / (n_samples - 1)  # 0 = bottom, 1 = top
        y = int(zone_bottom - t * (zone_bottom - green_top))
        # Slight perspective convergence
        spread = half_car * (1.0 + t * 0.15)
        left_pts.append((int(cx - spread), y))
        right_pts.append((int(cx + spread), y))

    left_arr = np.array(left_pts, dtype=np.int32)
    right_arr = np.array(right_pts, dtype=np.int32)
    cv2.polylines(out, [left_arr], False, OVERLAY_COLORS["guide"], 2, cv2.LINE_AA)
    cv2.polylines(out, [right_arr], False, OVERLAY_COLORS["guide"], 2, cv2.LINE_AA)

    # ── Distance markers (horizontal lines) ──
    marker_positions = [
        (0.85, "10cm", OVERLAY_COLORS["red"]),
        (0.75, "20cm", OVERLAY_COLORS["yellow"]),
        (0.65, "30cm", OVERLAY_COLORS["yellow"]),
        (0.55, "40cm", OVERLAY_COLORS["green"]),
    ]
    for y_frac, label, color in marker_positions:
        y_px = int(h * y_frac)
        t = (zone_bottom - y_px) / max(1, zone_bottom - green_top)
        spread = half_car * (1.0 + t * 0.15)
        x_left = int(cx - spread)
        x_right = int(cx + spread)
        cv2.line(out, (x_left, y_px), (x_right, y_px), color, 1, cv2.LINE_AA)
        # Label with background
        (tw, th_txt), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        lx = x_right + 5
        ly = y_px + 4
        cv2.rectangle(out, (lx - 2, ly - th_txt - 2), (lx + tw + 2, ly + 4),
                      (20, 20, 20), -1)
        cv2.putText(out, label, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (230, 230, 230), 1, cv2.LINE_AA)

    # ── Dynamic trajectory curves (follow steering angle) ──
    steer_norm = max(-1.0, min(1.0, steering))
    if abs(steer_norm) > 0.02:  # Don't draw curves when nearly straight
        traj_left = []
        traj_right = []
        for i in range(n_samples):
            t = i / (n_samples - 1)
            y = int(zone_bottom - t * (zone_bottom - green_top))
            # Quadratic displacement: more curve at distance
            x_offset = int(steer_norm * (t ** 2) * w * 0.25)
            spread = half_car * (1.0 + t * 0.15)
            traj_left.append((int(cx - spread + x_offset), y))
            traj_right.append((int(cx + spread + x_offset), y))

        tl_arr = np.array(traj_left, dtype=np.int32)
        tr_arr = np.array(traj_right, dtype=np.int32)
        # Draw dashed dynamic curves
        traj_color = (0, 180, 255)  # orange
        cv2.polylines(out, [tl_arr], False, traj_color, 2, cv2.LINE_AA)
        cv2.polylines(out, [tr_arr], False, traj_color, 2, cv2.LINE_AA)

        # Trajectory center line
        center_pts = []
        for i in range(n_samples):
            t = i / (n_samples - 1)
            y = int(zone_bottom - t * (zone_bottom - green_top))
            x_offset = int(steer_norm * (t ** 2) * w * 0.25)
            center_pts.append((cx + x_offset, y))
        center_arr = np.array(center_pts, dtype=np.int32)
        cv2.polylines(out, [center_arr], False, (255, 255, 0), 1, cv2.LINE_AA)

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
    show_overlay = args.overlay
    car_w_ratio = args.car_width_cm / 65.0  # rough cm-to-ratio (65cm ≈ full width)

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

                if keyboard.is_pressed('o'):
                    show_overlay = not show_overlay
                    time.sleep(0.3)  # anti-rebond

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
                if show_overlay:
                    frame = draw_parking_overlay(frame, angle, car_w_ratio)
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
