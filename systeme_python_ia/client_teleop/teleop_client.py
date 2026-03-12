#!/usr/bin/env python3
"""
teleop_client.py — Client de téléopération RC (PC Windows).

Contrôles :
  Z = accélérer    S = reculer
  Q = gauche       D = droite
  Z+Q / Z+D = avancer ET tourner
  ESPACE = arrêt d'urgence
  T = test servo   R = recentrer direction
  O = overlay on/off    P = parking detection    ESC = quitter

Dépendances : pip install opencv-python numpy
Usage :       python teleop_client.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import ctypes
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

# Ajouter la racine du projet systeme_python_ia au PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

import cv2
import numpy as np

# ═══════════════════════ KEYBOARD (Windows GetAsyncKeyState) ═══════════════
_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
_VK = {
    'z': 0x5A, 's': 0x53, 'q': 0x51, 'd': 0x44,
    'space': 0x20, 'esc': 0x1B,
    't': 0x54, 'r': 0x52, 'o': 0x4F, 'p': 0x50,
    'u': 0x55, 'i': 0x49,
}

def is_key(name: str) -> bool:
    vk = _VK.get(name)
    if vk is None:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

# ═══════════════════════ CONSTANTS ════════════════════════════════════════
WINDOW_NAME    = "Teleop - Voiture Autonome"

MAX_FWD_SPEED  = 0.18
MAX_BWD_SPEED  = -0.15
ACCEL_STEP     = 0.012
KICK_START     = 0.08
DECEL_FACTOR   = 0.90
DEAD_ZONE      = 0.015

ANGLE_STEP     = 0.08
MAX_ANGLE      = 1.0

CONTROL_HZ     = 30

# ═══════════════════════ CALIBRATION (from parking_calib.json) ════════════
CALIB_FILE = PROJECT_ROOT / "config" / "parking_calib.json"
OVERLAY_CALIB_FILE = PROJECT_ROOT / "config" / "overlay_calib.json"

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

# Valeurs par défaut du trapèze (fractions d'écran)
_DEFAULT_OVERLAY = {
    "top_left":     [0.30, 0.35],
    "top_right":    [0.70, 0.35],
    "bottom_left":  [0.00, 0.95],
    "bottom_right": [1.00, 0.95],
}

def _load_overlay_calib() -> dict:
    if OVERLAY_CALIB_FILE.exists():
        try:
            with open(OVERLAY_CALIB_FILE) as f:
                data = json.load(f)
            # Vérifier que les 4 clés existent
            for k in ("top_left", "top_right", "bottom_left", "bottom_right"):
                if k not in data or len(data[k]) != 2:
                    return _DEFAULT_OVERLAY.copy()
            return data
        except (json.JSONDecodeError, KeyError):
            pass
    return _DEFAULT_OVERLAY.copy()

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
    # UDP relay vers CarPlay (envoie le frame AVEC overlay)
    p.add_argument("--udp-ip", type=str, default=None,
                   help="IP cible pour relayer le flux avec overlay en UDP (ex: 192.168.1.196)")
    p.add_argument("--udp-port", type=int, default=4444,
                   help="Port UDP cible (default: 4444)")
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
             video_ok: bool, cmd_ok: bool, throttle_state: str,
             curvature: float = 130.0) -> None:
    h, w = frame.shape[:2]

    # Dark gradient/transparent bar at top
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 40), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    vid_color = (0, 255, 0) if video_ok else (0, 0, 255)
    cmd_color = (0, 255, 0) if cmd_ok else (0, 0, 255)
    
    cv2.putText(frame, f"FPS: {fps:.0f}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(frame, f"VID: {'OK' if video_ok else 'LOST'}", (120, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, vid_color, 1, cv2.LINE_AA)
    cv2.putText(frame, f"CMD: {'OK' if cmd_ok else 'LOST'}", (240, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, cmd_color, 1, cv2.LINE_AA)

    speed_pct = abs(speed) / MAX_FWD_SPEED * 100
    sc = (0, 255, 0) if speed > 0 else ((0, 150, 255) if speed < 0 else (150, 150, 150))
    cv2.putText(frame, f"{speed_pct:.0f}%", (w - 70, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, sc, 2, cv2.LINE_AA)
    cv2.putText(frame, throttle_state, (w - 130, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, sc, 1, cv2.LINE_AA)

    # Steering indicator at the bottom
    bar_cx, bar_y, bar_hw = w // 2, h - 30, 100
    cv2.line(frame, (bar_cx - bar_hw, bar_y), (bar_cx + bar_hw, bar_y),
             (100, 100, 100), 2, cv2.LINE_AA)
    cv2.line(frame, (bar_cx, bar_y - 6), (bar_cx, bar_y + 6),
             (150, 150, 150), 1, cv2.LINE_AA)
    
    needle_x = int(bar_cx + angle * bar_hw)
    cv2.circle(frame, (needle_x, bar_y), 7, (0, 200, 255), -1, cv2.LINE_AA)

    # Info texte pour la calibration
    cv2.putText(frame, f"ANGLE: {angle:.2f}  |  CURVE (U/I): {curvature:.0f}",
                (bar_cx - 200, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

    cv2.putText(frame, "Z:Fwd S:Bwd Q:L D:R ESP:Stop O:Overlay ESC:Quit",
                (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)


def draw_parking_overlay(frame: np.ndarray, steering: float,
                         car_half_cm: float, calib: list | None,
                         overlay_cfg: dict | None = None,
                         curvature_factor: float = 130.0) -> None:
    """Overlay premium style OEM Audi/VW.
    Utilise overlay_calib.json (4 coins) si disponible, sinon défauts."""
    h, w = frame.shape[:2]
    cx = w // 2

    cfg = overlay_cfg if overlay_cfg else _DEFAULT_OVERLAY

    # Coins du trapèze (en pixels)
    tl_x, tl_y = int(cfg["top_left"][0] * w),     int(cfg["top_left"][1] * h)
    tr_x, tr_y = int(cfg["top_right"][0] * w),    int(cfg["top_right"][1] * h)
    bl_x, bl_y = int(cfg["bottom_left"][0] * w),  int(cfg["bottom_left"][1] * h)
    br_x, br_y = int(cfg["bottom_right"][0] * w), int(cfg["bottom_right"][1] * h)

    # On divise le trapèze en 3 zones (bas=proche, haut=loin)
    # L'interpolation se fait point par point sur les segments gauche et droit
    def get_pt(p_bottom, p_top, t):
        """t=0: bottom, t=1: top"""
        return (int(p_bottom[0] + t * (p_top[0] - p_bottom[0])),
                int(p_bottom[1] + t * (p_top[1] - p_bottom[1])))

    bl = (bl_x, bl_y)
    br = (br_x, br_y)
    tl = (tl_x, tl_y)
    tr = (tr_x, tr_y)

    overlay = frame.copy()

    # 1. Zones colorées (3 bandes dans le trapèze)
    # Zone 1 : 0% → 33%  (t de 0.0 à 0.33)
    l0, r0 = get_pt(bl, tl, 0.0), get_pt(br, tr, 0.0)
    l1, r1 = get_pt(bl, tl, 0.33), get_pt(br, tr, 0.33)
    poly_z1 = np.array([l0, r0, r1, l1], np.int32)
    cv2.fillPoly(overlay, [poly_z1], (220, 60, 60))

    # Zone 2 : 33% → 66% 
    l2, r2 = get_pt(bl, tl, 0.66), get_pt(br, tr, 0.66)
    poly_z2 = np.array([l1, r1, r2, l2], np.int32)
    cv2.fillPoly(overlay, [poly_z2], (180, 50, 50))

    # Zone 3 : 66% → 100%
    l3, r3 = get_pt(bl, tl, 1.0), get_pt(br, tr, 1.0)
    poly_z3 = np.array([l2, r2, r3, l3], np.int32)
    cv2.fillPoly(overlay, [poly_z3], (140, 40, 40))

    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

    # 2. Ligne critique pare-chocs (Rouge épais, en bas)
    cv2.line(frame, l0, r0, (0, 0, 255), 4, cv2.LINE_AA)

    # 3. Lignes de séparation noires
    cv2.line(frame, l1, r1, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.line(frame, l2, r2, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.line(frame, l3, r3, (0, 0, 0), 1, cv2.LINE_AA)

    # 4. Courbes de trajectoire dynamiques (Orange)
    # Inversion du signe : caméra arrière → D (steer>0) donne courbe à gauche
    steer = -max(-1.0, min(1.0, steering))
    n = 30
    l_dyn = np.empty((n, 2), dtype=np.int32)
    r_dyn = np.empty((n, 2), dtype=np.int32)

    for i in range(n):
        t = i / (n - 1)  # 0 = bas, 1 = haut
        l_pt = get_pt(bl, tl, t)
        r_pt = get_pt(br, tr, t)

        # Décalage latéral dû au braquage (quadratique, doux)
        lat_off = int(steer * (t ** 2) * curvature_factor)

        l_dyn[i] = (l_pt[0] + lat_off, l_pt[1])
        r_dyn[i] = (r_pt[0] + lat_off, r_pt[1])

    dyn_color = (0, 165, 255)  # Orange (BGR)
    cv2.polylines(frame, [l_dyn], False, dyn_color, 3, cv2.LINE_AA)
    cv2.polylines(frame, [r_dyn], False, dyn_color, 3, cv2.LINE_AA)


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
        print("[CALIB] No calibration file — overlay will use defaults")

    # Load overlay trapezoid calibration
    overlay_cfg = _load_overlay_calib()
    if OVERLAY_CALIB_FILE.exists():
        print(f"[OVERLAY] Loaded corners from {OVERLAY_CALIB_FILE}")
    else:
        print("[OVERLAY] Using default trapezoid (run calibrate_overlay.py to customize)")

    car_half_cm = args.car_width_cm / 2.0

    # UDP relay socket (pour CarPlay — envoie le frame avec overlay)
    udp_relay = None
    if args.udp_ip:
        udp_relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"[UDP] Relay activé → {args.udp_ip}:{args.udp_port} (avec overlay)")

    # Parking detection
    try:
        from detecteurs.parking_detector_yolo import ParkingDetectorYOLO as ParkingDetector
        detector = ParkingDetector()
        print("[PARKING] Détecteur YOLO initialisé (touche P pour activer)")
    except ImportError as e:
        print(f"[PARKING] YOLO non disponible ({e}), tentative module classique...")
        try:
            from detecteurs.parking_detector_classic import ParkingDetector
            detector = ParkingDetector()
            print("[PARKING] Détecteur CLASSIC initialisé (touche P)")
        except ImportError:
            detector = None
            print("[PARKING] Détection désactivée")

    detect_lock = threading.Lock()
    detect_results: dict = {"spots": [], "mask": None, "h_lines": [], "v_lines": [], "active": False}

    # Shared state
    state_lock = threading.Lock()
    state = {
        "speed": 0.0, "angle": 0.0, "tstate": "STOP",
        "cmd_ok": cmd_ok, "show_overlay": args.overlay, "show_parking": False, "quit": False,
    }

    # ── Control thread ──
    def control_loop():
        nonlocal cmd_sock, cmd_ok
        speed = angle = 0.0
        curvature = 130.0
        show_overlay = args.overlay
        show_parking = False
        test_angles = [-1.0, -0.5, 0.0, 0.5, 1.0]
        test_idx = -1
        t_prev = o_prev = False
        p_prev = False
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

                p_now = is_key('p')
                if p_now and not p_prev:
                    show_parking = not show_parking
                p_prev = p_now
                
                if is_key('u'):
                    curvature = max(0.0, curvature - 5.0)
                if is_key('i'):
                    curvature += 5.0

            if not throttle_active:
                speed *= DECEL_FACTOR
                if abs(speed) < DEAD_ZONE:
                    speed = 0.0

            tstate = "STOP" if abs(speed) < DEAD_ZONE else ("FWD" if speed > 0 else "BWD")

            with state_lock:
                state.update(speed=speed, angle=angle, tstate=tstate, show_parking=show_parking,
                             show_overlay=show_overlay, curvature=curvature)

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
    # ── Detection thread ── 
    def detection_loop():
        while not state["quit"]:
            with state_lock:
                active = state.get("show_parking", False)
            if not active or detector is None:
                time.sleep(0.1)
                continue
            fr = video.get_frame()
            if fr is not None:
                spots, mask, rects, _ = detector.detect(fr)
                with detect_lock:
                    detect_results["spots"] = spots
                    detect_results["mask"] = mask
                    detect_results["rects"] = rects
                    detect_results["active"] = True
            time.sleep(1.0)  # ~1 Hz — priorité au contrôle

    det_thread = threading.Thread(target=detection_loop, daemon=True)
    det_thread.start()

    print("[TELEOP] Ready. Z/S/Q/D O=overlay P=parking ESC=quit")

    # ── Display loop (main thread) ──
    try:
        while not state["quit"]:
            frame = video.get_frame()
            if frame is not None:
                with state_lock:
                    s = state.copy()
                if s["show_overlay"]:
                    draw_parking_overlay(frame, float(s["angle"]),
                                         car_half_cm, calib, overlay_cfg,
                                         float(s.get("curvature", 130.0)))
                if s.get("show_parking") and detector is not None:
                    with detect_lock:
                        sp = detect_results["spots"]
                        mk = detect_results["mask"]
                        rt = detect_results.get("rects", [])
                    detector.draw_detections(frame, sp, rects=rt,
                                             show_mask=True, mask=mk)
                draw_hud(frame, video.fps, float(s["speed"]), float(s["angle"]),
                         video.connected, bool(s["cmd_ok"]), str(s["tstate"]),
                         float(s.get("curvature", 130.0)))

                # Relay UDP vers CarPlay (frame complet avec overlay)
                if udp_relay is not None:
                    ok, jpeg = cv2.imencode(".jpg", frame,
                                            [cv2.IMWRITE_JPEG_QUALITY, 50])
                    if ok:
                        udp_data = jpeg.tobytes()
                        if len(udp_data) < 65000:
                            try:
                                udp_relay.sendto(udp_data,
                                                 (args.udp_ip, args.udp_port))
                            except OSError:
                                pass

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
