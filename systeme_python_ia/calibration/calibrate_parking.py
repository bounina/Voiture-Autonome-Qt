#!/usr/bin/env python3
"""
calibrate_parking.py — Outil de calibration interactif pour l'overlay de recul.

Capture un frame du flux vidéo Pi, puis l'utilisateur clique sur les bandes
de scotch à distances connues. Les coordonnées sont sauvegardées dans
parking_calib.json, utilisé ensuite par teleop_client.py.

Instructions :
  1. Place du scotch au sol à 20cm, 40cm, 60cm de la caméra (tu l'as déjà)
  2. Lance ce script, il capture un frame
  3. Clique sur le BORD GAUCHE puis BORD DROIT de chaque bande de scotch
  4. Appuie sur une touche pour confirmer chaque point
  5. Les données sont sauvegardées dans parking_calib.json

Usage :
    python calibrate_parking.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np

CALIB_FILE = Path(__file__).parent / "parking_calib.json"


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


# Global state for mouse callback
_click_points: list[tuple[int, int]] = []
_current_frame: np.ndarray | None = None


def _mouse_cb(event, x, y, flags, param):
    global _current_frame
    if event == cv2.EVENT_LBUTTONDOWN:
        _click_points.append((x, y))
        print(f"  → Point cliqué : ({x}, {y})")
        # Draw marker
        if _current_frame is not None:
            cv2.circle(_current_frame, (x, y), 6, (0, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(_current_frame, (x, y), 8, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.imshow("Calibration", _current_frame)


def collect_point(frame: np.ndarray, label: str) -> tuple[int, int]:
    """Ask user to click a point, return (x, y)."""
    global _current_frame
    _click_points.clear()

    _current_frame = frame.copy()
    h, w = frame.shape[:2]

    # Draw instruction
    cv2.rectangle(_current_frame, (0, h - 45), (w, h), (30, 30, 30), -1)
    cv2.putText(_current_frame, f"Clique sur : {label}",
                (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 255), 2, cv2.LINE_AA)

    cv2.imshow("Calibration", _current_frame)

    while len(_click_points) == 0:
        if cv2.waitKey(50) & 0xFF == 27:  # ESC to abort
            print("[CALIB] Annulé.")
            sys.exit(0)

    return _click_points[0]


def run_calibration(frame: np.ndarray) -> dict:
    """Interactive calibration: user clicks on tape marks."""
    cv2.namedWindow("Calibration", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Calibration", 960, 720)
    cv2.setMouseCallback("Calibration", _mouse_cb)

    h, w = frame.shape[:2]
    distances = [20, 40, 60]  # cm
    calib_points = []

    print("\n" + "=" * 55)
    print("  CALIBRATION OVERLAY DE RECUL")
    print("=" * 55)
    print(f"  Image : {w}x{h}")
    print(f"  Distances : {distances} cm")
    print()
    print("  Pour chaque distance, clique sur le CENTRE de la")
    print("  bande de scotch, puis le BORD DROIT de la bande.")
    print("  ESC pour annuler.")
    print("=" * 55)

    for dist in distances:
        print(f"\n--- Distance {dist} cm ---")

        # Click center of tape
        center = collect_point(frame, f"{dist}cm — CENTRE de la bande")
        print(f"  Centre : {center}")

        # Click right edge of tape
        right = collect_point(frame, f"{dist}cm — BORD DROIT de la bande")
        print(f"  Bord droit : {right}")

        # Compute: y position and px/cm ratio
        # Tape is 20cm wide, right edge is 10cm from center
        half_tape_px = abs(right[0] - center[0])
        px_per_cm = half_tape_px / 10.0  # 10cm = half of 20cm tape

        y_frac = center[1] / h

        calib_points.append({
            "dist_cm": dist,
            "y_frac": round(y_frac, 4),
            "center_x": center[0],
            "center_y": center[1],
            "px_per_cm": round(px_per_cm, 2),
        })
        print(f"  → y={y_frac:.3f}, {px_per_cm:.1f} px/cm")

        # Draw confirmed marker on frame
        cv2.line(frame, (center[0] - half_tape_px, center[1]),
                 (center[0] + half_tape_px, center[1]),
                 (0, 255, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, f"{dist}cm", (center[0] + half_tape_px + 10, center[1] + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

    cv2.destroyAllWindows()

    calib_data = {
        "image_size": [w, h],
        "tape_width_cm": 20,
        "points": calib_points,
    }
    return calib_data


def main():
    parser = argparse.ArgumentParser(description="Calibration interactive overlay recul")
    parser.add_argument("--pi-ip", required=True, help="IP du Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    args = parser.parse_args()

    frame = capture_frame(args.pi_ip, args.video_port)
    calib = run_calibration(frame)

    # Save
    with open(CALIB_FILE, "w") as f:
        json.dump(calib, f, indent=2)

    print(f"\n✅ Calibration sauvegardée dans : {CALIB_FILE}")
    print(json.dumps(calib, indent=2))


if __name__ == "__main__":
    main()
