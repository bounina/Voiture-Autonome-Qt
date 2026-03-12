#!/usr/bin/env python3
"""
calibrate_hsv.py — Calibration interactive des seuils HSV pour le scotch bleu.

Capture un frame du flux vidéo Pi, puis affiche des trackbars pour ajuster
les bornes HSV en live. Le masque résultant est affiché en temps réel.
Sauvegarde dans hsv_config.json.

Usage :
    python calibrate_hsv.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
from pathlib import Path

import cv2
import numpy as np

HSV_CONFIG_FILE = Path(__file__).parent / "hsv_config.json"

# Défauts pour scotch bleu de peintre
DEFAULT_HSV = {
    "h_min": 90, "s_min": 50, "v_min": 50,
    "h_max": 130, "s_max": 255, "v_max": 255,
}


def recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


def capture_frame(ip: str, port: int) -> np.ndarray:
    """Capture un frame depuis le flux vidéo Pi."""
    print(f"[HSV] Connexion à {ip}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)
    s.connect((ip, port))
    s.settimeout(5.0)

    # Skip warmup frames
    for _ in range(10):
        header = recv_exact(s, 4)
        frame_size = struct.unpack(">I", header)[0]
        jpeg_data = recv_exact(s, frame_size)

    frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
    s.close()
    print(f"[HSV] Frame capturée : {frame.shape[1]}x{frame.shape[0]}")
    return frame


def nothing(x):
    pass


def main():
    parser = argparse.ArgumentParser(description="Calibration HSV pour scotch bleu")
    parser.add_argument("--pi-ip", required=True, help="IP du Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    args = parser.parse_args()

    frame = capture_frame(args.pi_ip, args.video_port)

    # Charger les valeurs existantes ou défauts
    if HSV_CONFIG_FILE.exists():
        try:
            with open(HSV_CONFIG_FILE) as f:
                cfg = json.load(f)
            print(f"[HSV] Config existante chargée : {HSV_CONFIG_FILE}")
        except Exception:
            cfg = DEFAULT_HSV.copy()
    else:
        cfg = DEFAULT_HSV.copy()

    cv2.namedWindow("Original", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Masque HSV", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Resultat", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Reglages", cv2.WINDOW_NORMAL)

    cv2.resizeWindow("Reglages", 400, 300)

    # Créer les trackbars
    cv2.createTrackbar("H min", "Reglages", cfg["h_min"], 179, nothing)
    cv2.createTrackbar("H max", "Reglages", cfg["h_max"], 179, nothing)
    cv2.createTrackbar("S min", "Reglages", cfg["s_min"], 255, nothing)
    cv2.createTrackbar("S max", "Reglages", cfg["s_max"], 255, nothing)
    cv2.createTrackbar("V min", "Reglages", cfg["v_min"], 255, nothing)
    cv2.createTrackbar("V max", "Reglages", cfg["v_max"], 255, nothing)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    print("\n" + "=" * 50)
    print("  CALIBRATION HSV — SCOTCH BLEU")
    print("=" * 50)
    print("  Ajuste les curseurs pour isoler le scotch bleu.")
    print("  Le masque blanc = pixels détectés.")
    print("  ENTRÉE = sauvegarder    ESC = annuler")
    print("=" * 50)

    while True:
        h_min = cv2.getTrackbarPos("H min", "Reglages")
        h_max = cv2.getTrackbarPos("H max", "Reglages")
        s_min = cv2.getTrackbarPos("S min", "Reglages")
        s_max = cv2.getTrackbarPos("S max", "Reglages")
        v_min = cv2.getTrackbarPos("V min", "Reglages")
        v_max = cv2.getTrackbarPos("V max", "Reglages")

        lower = np.array([h_min, s_min, v_min])
        upper = np.array([h_max, s_max, v_max])

        mask = cv2.inRange(hsv, lower, upper)

        # Nettoyage morphologique
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask_clean = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_OPEN, kernel)

        result = cv2.bitwise_and(frame, frame, mask=mask_clean)

        # Afficher le nombre de pixels détectés
        n_pixels = cv2.countNonZero(mask_clean)
        info = frame.copy()
        cv2.putText(info, f"Pixels bleus: {n_pixels}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("Original", info)
        cv2.imshow("Masque HSV", mask_clean)
        cv2.imshow("Resultat", result)

        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            print("[HSV] Annulé.")
            break
        elif key in (13, 10):  # ENTER
            result_cfg = {
                "h_min": h_min, "s_min": s_min, "v_min": v_min,
                "h_max": h_max, "s_max": s_max, "v_max": v_max,
            }
            with open(HSV_CONFIG_FILE, "w") as f:
                json.dump(result_cfg, f, indent=2)
            print(f"\n✅ Config HSV sauvegardée dans : {HSV_CONFIG_FILE}")
            print(json.dumps(result_cfg, indent=2))
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
