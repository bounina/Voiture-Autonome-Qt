#!/usr/bin/env python3
"""
calibrate_overlay.py — Calibration interactive du trapèze d'overlay.

Capture un frame du flux vidéo Pi, puis l'utilisateur déplace
les 4 coins du trapèze à la souris. Les positions sont sauvegardées
dans overlay_calib.json, utilisé ensuite par teleop_client.py.

Usage :
    python calibrate_overlay.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

# Configuration files
OVERLAY_CALIB_FILE = PROJECT_ROOT / "config" / "overlay_calib.json"

# Valeurs par défaut (fractions d'écran)
DEFAULT_CORNERS = {
    "top_left":     [0.30, 0.35],
    "top_right":    [0.70, 0.35],
    "bottom_left":  [0.00, 0.95],
    "bottom_right": [1.00, 0.95],
}

# ── Réseau ──

def recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


def capture_frame(ip: str, port: int) -> np.ndarray:
    """Connect to video stream and grab one good frame."""
    print(f"[CALIB] Connexion à {ip}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)
    s.connect((ip, port))
    s.settimeout(5.0)
    print("[CALIB] Connecté, capture en cours...")

    # Skip first frames (warmup)
    for _ in range(10):
        header = recv_exact(s, 4)
        frame_size = struct.unpack(">I", header)[0]
        jpeg_data = recv_exact(s, frame_size)

    frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
    s.close()
    print(f"[CALIB] Frame capturée : {frame.shape[1]}x{frame.shape[0]}")
    return frame

# ── Calibration interactive ──

CORNER_NAMES = ["top_left", "top_right", "bottom_right", "bottom_left"]
CORNER_COLORS = [
    (0, 200, 0),    # top_left = vert
    (0, 200, 200),  # top_right = jaune
    (0, 0, 255),    # bottom_right = rouge
    (255, 100, 0),  # bottom_left = bleu
]

_dragging: int = -1  # index du coin en cours de drag
_corners: list[list[int]] = []  # [[x,y], ...] en pixels


def _mouse_cb(event, x, y, flags, param):
    global _dragging
    if event == cv2.EVENT_LBUTTONDOWN:
        # Trouver le coin le plus proche
        best_i, best_d = -1, 999999
        for i, (cx, cy) in enumerate(_corners):
            d = (x - cx)**2 + (y - cy)**2
            if d < best_d:
                best_i, best_d = i, d
        if best_d < 40**2:  # seuil de clic (40px)
            _dragging = best_i
    elif event == cv2.EVENT_MOUSEMOVE and _dragging >= 0:
        _corners[_dragging] = [x, y]
    elif event == cv2.EVENT_LBUTTONUP:
        _dragging = -1


def run_calibration(frame: np.ndarray) -> dict:
    global _corners
    h, w = frame.shape[:2]

    # Charger les coins existants ou utiliser les défauts
    if OVERLAY_CALIB_FILE.exists():
        try:
            with open(OVERLAY_CALIB_FILE) as f:
                existing = json.load(f)
            _corners = [
                [int(existing[n][0] * w), int(existing[n][1] * h)]
                for n in CORNER_NAMES
            ]
            print("[CALIB] Calibration existante chargée comme point de départ")
        except Exception:
            _corners = [
                [int(DEFAULT_CORNERS[n][0] * w), int(DEFAULT_CORNERS[n][1] * h)]
                for n in CORNER_NAMES
            ]
    else:
        _corners = [
            [int(DEFAULT_CORNERS[n][0] * w), int(DEFAULT_CORNERS[n][1] * h)]
            for n in CORNER_NAMES
        ]

    cv2.namedWindow("Calibration Overlay", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Calibration Overlay", min(w, 1280), min(h, 720))
    cv2.setMouseCallback("Calibration Overlay", _mouse_cb)

    print("\n" + "=" * 55)
    print("  CALIBRATION DU TRAPÈZE D'OVERLAY")
    print("=" * 55)
    print(f"  Image : {w}x{h}")
    print()
    print("  Glisse les 4 coins du trapèze avec la souris.")
    print("  ENTRÉE = sauvegarder    ESC = annuler")
    print("=" * 55)

    while True:
        display = frame.copy()

        # Dessiner le trapèze rempli avec transparence
        overlay = display.copy()
        pts = np.array(_corners, np.int32)
        cv2.fillPoly(overlay, [pts], (180, 50, 50))
        cv2.addWeighted(overlay, 0.35, display, 0.65, 0, display)

        # Dessiner les arêtes
        for i in range(4):
            p1 = tuple(_corners[i])
            p2 = tuple(_corners[(i + 1) % 4])
            cv2.line(display, p1, p2, (255, 255, 255), 2, cv2.LINE_AA)

        # Dessiner les coins (gros cercles colorés + label)
        for i, (cx, cy) in enumerate(_corners):
            color = CORNER_COLORS[i]
            cv2.circle(display, (cx, cy), 12, color, -1, cv2.LINE_AA)
            cv2.circle(display, (cx, cy), 14, (255, 255, 255), 2, cv2.LINE_AA)
            label = CORNER_NAMES[i].replace("_", " ").upper()
            cv2.putText(display, label, (cx + 18, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Instructions en bas
        cv2.rectangle(display, (0, h - 35), (w, h), (30, 30, 30), -1)
        cv2.putText(display, "Glisse les coins | ENTREE = sauvegarder | ESC = annuler",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 255, 255), 1, cv2.LINE_AA)

        cv2.imshow("Calibration Overlay", display)

        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            print("[CALIB] Annulé.")
            cv2.destroyAllWindows()
            sys.exit(0)
        elif key == 13 or key == 10:  # ENTER
            break

    cv2.destroyAllWindows()

    # Convertir en fractions d'écran
    result = {}
    for i, name in enumerate(CORNER_NAMES):
        result[name] = [
            round(_corners[i][0] / w, 4),
            round(_corners[i][1] / h, 4),
        ]
    return result


def main():
    parser = argparse.ArgumentParser(description="Calibration interactive overlay trapèze")
    parser.add_argument("--pi-ip", required=True, help="IP du Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    args = parser.parse_args()

    frame = capture_frame(args.pi_ip, args.video_port)
    calib = run_calibration(frame)

    # Save
    with open(OVERLAY_CALIB_FILE, "w") as f:
        json.dump(calib, f, indent=2)

    print(f"\n✅ Calibration sauvegardée dans : {OVERLAY_CALIB_FILE}")
    print(json.dumps(calib, indent=2))


if __name__ == "__main__":
    main()
