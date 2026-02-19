#!/usr/bin/env python3
"""
teleop_client.py — Client de téléopération RC (PC Windows).

Contrôles :
  Z = accélérer    S = reculer
  Q = gauche       D = droite
  Z+Q / Z+D = avancer ET tourner
  ESPACE = arrêt d'urgence
  T = test servo   R = recentrer direction
  O = overlay on/off    ESC = quitter

Dépendances : pip install opencv-python numpy
Usage :       python teleop_client.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import ctypes
import json
import socket
import struct
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# ═══════════════════════ KEYBOARD (Windows GetAsyncKeyState) ═══════════════
_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
_VK = {
    'z': 0x5A, 's': 0x53, 'q': 0x51, 'd': 0x44,
    'space': 0x20, 'esc': 0x1B,
    't': 0x54, 'r': 0x52, 'o': 0x4F,
}

def is_key(name: str) -> bool:
    vk = _VK.get(name)
    if vk is None:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

# ═══════════════════════ CONSTANTS ════════════════════════════════════════
WINDOW_NAME    = "Teleop - Voiture Autonome"

MAX_FWD_SPEED  = 0.18
MAX_BWD_SPEED  = -0.12
ACCEL_STEP     = 0.012
KICK_START     = 0.06
DECEL_FACTOR   = 0.90
DEAD_ZONE      = 0.015

ANGLE_STEP     = 0.08
MAX_ANGLE      = 1.0

CONTROL_HZ     = 30

# ═══════════════════════ CALIBRATION (from parking_calib.json) ════════════
CALIB_FILE = Path(__file__).parent / "parking_calib.json"

def _load_calib() -> list | None:
    if not CALIB_FILE.exists():
        return None
    try:
        with open(CALIB_FILE) as f:
            data = json.load(f)
        pts = data.get("points", [])
        return sorted(pts, key=lambda p: p["dist_cm"]) if len(pts) >= 2 else None
    except (json.JSONDecodeError, KeyError):
        return None

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _interp_y(h: int, pts: list, dist_cm: float) -> int:
    if dist_cm <= pts[0]["dist_cm"]:
        return int(h * pts[0]["y_frac"])
    if dist_cm >= pts[-1]["dist_cm"]:
        return int(h * pts[-1]["y_frac"])
    for i in range(len(pts) - 1):
        d0, d1 = pts[i]["dist_cm"], pts[i + 1]["dist_cm"]
        if d0 <= dist_cm <= d1:
            t = (dist_cm - d0) / (d1 - d0)
            return int(h * _lerp(pts[i]["y_frac"], pts[i + 1]["y_frac"], t))
    return int(h * pts[-1]["y_frac"])

def _interp_ppcm(pts: list, dist_cm: float) -> float:
    if dist_cm <= pts[0]["dist_cm"]:
        return pts[0]["px_per_cm"]
    if dist_cm >= pts[-1]["dist_cm"]:
        return pts[-1]["px_per_cm"]
    for i in range(len(pts) - 1):
        d0, d1 = pts[i]["dist_cm"], pts[i + 1]["dist_cm"]
        if d0 <= dist_cm <= d1:
            t = (dist_cm - d0) / (d1 - d0)
            return _lerp(pts[i]["px_per_cm"], pts[i + 1]["px_per_cm"], t)
    return pts[-1]["px_per_cm"]

# Overlay colors (BGR)
_RED    = (60, 55, 220)
_YELLOW = (50, 200, 240)
_GREEN  = (75, 195, 55)
_WHITE  = (240, 240, 240)
_ORANGE = (50, 160, 255)

# ═══════════════════════ NETWORK ══════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RC teleoperation client.")
    p.add_argument("--pi-ip", required=True)
    p.add_argument("--video-port", type=int, default=8885)
    p.add_argument("--cmd-port", type=int, default=8884)
    p.add_argument("--car-width-cm", type=float, default=20.0,
                   help="Largeur du véhicule en cm")
    p.add_argument("--overlay", action="store_true", default=True)
    return p.parse_args()

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

# ═══════════════════════ DRAWING ══════════════════════════════════════════

def draw_hud(frame: np.ndarray, fps: float, speed: float, angle: float,
             video_ok: bool, cmd_ok: bool, throttle_state: str) -> None:
    h, w = frame.shape[:2]

    # Dark bar at top
    sub = frame[0:130, 0:w]
    sub[:] = (sub * 0.4 + np.array([20, 20, 20]) * 0.6).astype(np.uint8)

    vid_color = (0, 255, 0) if video_ok else (0, 0, 255)
    cmd_color = (0, 255, 0) if cmd_ok else (0, 0, 255)
    cv2.putText(frame, f"FPS: {fps:.0f}", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, f"VIDEO: {'OK' if video_ok else 'LOST'}", (150, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, vid_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"CMD: {'OK' if cmd_ok else 'DISCONN'}", (370, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, cmd_color, 2, cv2.LINE_AA)

    speed_pct = abs(speed) / MAX_FWD_SPEED * 100
    sc = (0, 255, 0) if speed > 0 else ((0, 100, 255) if speed < 0 else (200, 200, 200))
    cv2.putText(frame, f"Speed: {speed_pct:.0f}% ({throttle_state})", (10, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, sc, 2, cv2.LINE_AA)
    cv2.putText(frame, f"Angle: {angle:+.2f}", (10, 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    # Steering bar
    bar_cx, bar_y, bar_hw = w // 2, 118, 150
    cv2.line(frame, (bar_cx - bar_hw, bar_y), (bar_cx + bar_hw, bar_y),
             (100, 100, 100), 3, cv2.LINE_AA)
    needle_x = int(bar_cx + angle * bar_hw)
    cv2.circle(frame, (needle_x, bar_y), 8, (0, 200, 255), -1, cv2.LINE_AA)

    cv2.putText(frame, "Z:Accel S:Recule Q+D:Direction ESPACE:Stop T:Test R:Centre O:Overlay ESC:Quit",
                (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 180, 180), 1, cv2.LINE_AA)


def draw_parking_overlay(frame: np.ndarray, steering: float,
                         car_half_cm: float, calib: list | None) -> None:
    """Overlay minimaliste style Toyota/Honda."""
    h, w = frame.shape[:2]
    cx = w // 2

    if calib is None or len(calib) < 2:
        cv2.putText(frame, "PAS DE CALIBRATION - python calibrate_parking.py --pi-ip ...",
                    (10, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 255), 1, cv2.LINE_AA)
        return

    d_min = calib[0]["dist_cm"]
    d_max = calib[-1]["dist_cm"]

    # Config : 3 lignes de distance (rouge/jaune/vert)
    lines_cfg = [
        (d_min,                _RED,    2),
        ((d_min + d_max) / 2,  _YELLOW, 2),
        (d_max,                _GREEN,  2),
    ]

    # ── Guide lines (largeur véhicule, convergentes) ──
    n = 30
    left_pts  = np.empty((n, 2), dtype=np.int32)
    right_pts = np.empty((n, 2), dtype=np.int32)
    for i in range(n):
        t = i / (n - 1)
        d = d_min + t * (d_max - d_min)
        y = _interp_y(h, calib, d)
        hw = int(car_half_cm * _interp_ppcm(calib, d))
        left_pts[i]  = (cx - hw, y)
        right_pts[i] = (cx + hw, y)

    cv2.polylines(frame, [left_pts],  False, _WHITE, 2, cv2.LINE_AA)
    cv2.polylines(frame, [right_pts], False, _WHITE, 2, cv2.LINE_AA)

    # ── Lignes de distance horizontales ──
    for dist, color, thick in lines_cfg:
        y = _interp_y(h, calib, dist)
        hw = int(car_half_cm * _interp_ppcm(calib, dist))
        xl, xr = cx - hw, cx + hw
        cv2.line(frame, (xl, y), (xr, y), color, thick, cv2.LINE_AA)
        cv2.putText(frame, f"{int(dist)}cm", (xr + 6, y + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)

    # ── Courbes de trajectoire dynamiques ──
    steer = max(-1.0, min(1.0, steering))
    if abs(steer) > 0.03:
        tl = np.empty((n, 2), dtype=np.int32)
        tr = np.empty((n, 2), dtype=np.int32)
        for i in range(n):
            t = i / (n - 1)
            d = d_min + t * (d_max - d_min)
            y = _interp_y(h, calib, d)
            hw = int(car_half_cm * _interp_ppcm(calib, d))
            x_off = int(steer * (t ** 2) * w * 0.20)
            tl[i] = (cx - hw + x_off, y)
            tr[i] = (cx + hw + x_off, y)
        cv2.polylines(frame, [tl], False, _ORANGE, 2, cv2.LINE_AA)
        cv2.polylines(frame, [tr], False, _ORANGE, 2, cv2.LINE_AA)


# ═══════════════════════ VIDEO RECEIVER ═══════════════════════════════════

class VideoReceiver(threading.Thread):
    """Thread receiving video frames from Pi."""

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
                self.fps = 1.0 / dt if dt > 0 else 0.0
                prev_t = now

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


# ═══════════════════════ MAIN ═════════════════════════════════════════════

def main() -> int:
    args = parse_args()

    video = VideoReceiver(args.pi_ip, args.video_port)
    video.start()

    cmd_sock = connect_cmd(args.pi_ip, args.cmd_port)
    cmd_ok = cmd_sock is not None

    # Load calibration from JSON
    calib = _load_calib()
    if calib:
        print(f"[CALIB] Loaded {len(calib)} points from {CALIB_FILE}")
    else:
        print("[CALIB] No calibration file — overlay will show warning")

    car_half_cm = args.car_width_cm / 2.0

    # Shared state
    state_lock = threading.Lock()
    state = {
        "speed": 0.0, "angle": 0.0, "tstate": "STOP",
        "cmd_ok": cmd_ok, "show_overlay": args.overlay, "quit": False,
    }

    # ── Control thread ──
    def control_loop():
        nonlocal cmd_sock, cmd_ok
        speed = angle = 0.0
        show_overlay = args.overlay
        test_angles = [-1.0, -0.5, 0.0, 0.5, 1.0]
        test_idx = -1
        t_prev = o_prev = False
        last_cmd_time = 0.0

        while not state["quit"]:
            tick_start = time.perf_counter()
            throttle_active = False

            if is_key('esc'):
                send_command(cmd_sock, "TELEOP:STOP")
                with state_lock:
                    state["quit"] = True
                break

            if is_key('space'):
                speed = angle = 0.0
                send_command(cmd_sock, "TELEOP:STOP")
            else:
                if is_key('z'):
                    speed = KICK_START if abs(speed) < DEAD_ZONE else min(speed + ACCEL_STEP, MAX_FWD_SPEED)
                    throttle_active = True
                if is_key('s'):
                    speed = -KICK_START if abs(speed) < DEAD_ZONE else max(speed - ACCEL_STEP, MAX_BWD_SPEED)
                    throttle_active = True
                if is_key('q'):
                    angle = max(-MAX_ANGLE, angle - ANGLE_STEP)
                if is_key('d'):
                    angle = min(MAX_ANGLE, angle + ANGLE_STEP)

                t_now = is_key('t')
                if t_now and not t_prev:
                    test_idx = (test_idx + 1) % len(test_angles)
                    angle, speed = test_angles[test_idx], 0.0
                t_prev = t_now

                if is_key('r'):
                    angle, test_idx = 0.0, -1

                o_now = is_key('o')
                if o_now and not o_prev:
                    show_overlay = not show_overlay
                o_prev = o_now

            if not throttle_active:
                speed *= DECEL_FACTOR
                if abs(speed) < DEAD_ZONE:
                    speed = 0.0

            tstate = "STOP" if abs(speed) < DEAD_ZONE else ("FWD" if speed > 0 else "BWD")

            with state_lock:
                state.update(speed=speed, angle=angle, tstate=tstate,
                             show_overlay=show_overlay)

            now = time.perf_counter()
            if now - last_cmd_time >= 0.05:
                ok = send_command(cmd_sock, f"TELEOP:DRIVE,{speed:.4f},{angle:.4f}")
                last_cmd_time = now
                if not ok and cmd_ok:
                    cmd_sock = connect_cmd(args.pi_ip, args.cmd_port)
                    cmd_ok = cmd_sock is not None
                elif ok:
                    cmd_ok = True
                with state_lock:
                    state["cmd_ok"] = cmd_ok

            remain = (1.0 / CONTROL_HZ) - (time.perf_counter() - tick_start)
            if remain > 0:
                time.sleep(remain)

    ctrl = threading.Thread(target=control_loop, daemon=True)
    ctrl.start()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    print("[TELEOP] Ready. Z/S/Q/D O=overlay ESC=quit")

    # ── Display loop (main thread) ──
    try:
        while not state["quit"]:
            frame = video.get_frame()
            if frame is not None:
                with state_lock:
                    s = state.copy()
                if s["show_overlay"]:
                    draw_parking_overlay(frame, float(s["angle"]),
                                         car_half_cm, calib)
                draw_hud(frame, video.fps, float(s["speed"]), float(s["angle"]),
                         video.connected, bool(s["cmd_ok"]), str(s["tstate"]))
                cv2.imshow(WINDOW_NAME, frame)

            if cv2.waitKey(15) & 0xFF == 27:
                with state_lock:
                    state["quit"] = True
                break
    except KeyboardInterrupt:
        send_command(cmd_sock, "TELEOP:STOP")
    finally:
        with state_lock:
            state["quit"] = True
        ctrl.join(timeout=2.0)
        video.stop()
        if cmd_sock:
            cmd_sock.close()
        cv2.destroyAllWindows()
        print("[TELEOP] Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
