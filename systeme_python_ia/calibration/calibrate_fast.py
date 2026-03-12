#!/usr/bin/env python3
"""
calibrate_fast.py — Calibration live des seuils FAST (HSV + LAB) sur le flux Pi.

Affiche le flux vidéo en direct avec trackbars pour régler en temp réel les
seuils HSV ET LAB. La détection de contours est appliquée en direct pour voir
exactement ce que le détecteur verra.

Usage :
    python calibrate_fast.py --pi-ip 192.168.X.X [--video-port 8885]
    
Commandes :
    ENTREE = sauvegarder dans knn_thresholds.json
    R      = recharger le frame courant
    ESC    = quitter sans sauvegarder
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import time
from pathlib import Path

import cv2
import numpy as np

THRESHOLDS_FILE = Path(__file__).parent / "knn_thresholds.json"

DEFAULT = {
    "H_min": 95, "H_max": 125,
    "S_min": 60,  "S_max": 255,
    "V_min": 100, "V_max": 255,
    "L_min": 70,  "L_max": 180,
    "a_min": 110, "a_max": 155,
    "b_min": 40,  "b_max": 115,
}


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


class LiveStream:
    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while self.running:
            try:
                s = socket.socket()
                s.settimeout(10)
                s.connect((self.ip, self.port))
                s.settimeout(5)
                while self.running:
                    size = struct.unpack(">I", recv_exact(s, 4))[0]
                    data = recv_exact(s, size)
                    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        with self.lock:
                            self.frame = frame
            except Exception:
                time.sleep(1)

    def get(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False


def nothing(_):
    pass


def main():
    parser = argparse.ArgumentParser(description="Calibration FAST live — seuils HSV+LAB")
    parser.add_argument("--pi-ip", required=True)
    parser.add_argument("--video-port", type=int, default=8885)
    args = parser.parse_args()

    # Charger les valeurs existantes
    t = DEFAULT.copy()
    if THRESHOLDS_FILE.exists():
        try:
            t.update(json.loads(THRESHOLDS_FILE.read_text()))
            print(f"[FAST-CALIB] Seuils charges depuis {THRESHOLDS_FILE}")
        except Exception:
            pass

    stream = LiveStream(args.pi_ip, args.video_port)
    print(f"[FAST-CALIB] Connexion à {args.pi_ip}:{args.video_port}...")

    # Fenêtre trackbars HSV
    cv2.namedWindow("HSV Reglages", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("HSV Reglages", 500, 260)
    cv2.createTrackbar("H min", "HSV Reglages", t["H_min"], 179, nothing)
    cv2.createTrackbar("H max", "HSV Reglages", t["H_max"], 179, nothing)
    cv2.createTrackbar("S min", "HSV Reglages", t["S_min"], 255, nothing)
    cv2.createTrackbar("S max", "HSV Reglages", t["S_max"], 255, nothing)
    cv2.createTrackbar("V min", "HSV Reglages", t["V_min"], 255, nothing)
    cv2.createTrackbar("V max", "HSV Reglages", t["V_max"], 255, nothing)

    # Fenêtre trackbars LAB
    cv2.namedWindow("LAB Reglages", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("LAB Reglages", 500, 200)
    cv2.createTrackbar("L min", "LAB Reglages", t["L_min"], 255, nothing)
    cv2.createTrackbar("L max", "LAB Reglages", t["L_max"], 255, nothing)
    cv2.createTrackbar("a min", "LAB Reglages", t["a_min"], 255, nothing)
    cv2.createTrackbar("a max", "LAB Reglages", t["a_max"], 255, nothing)
    cv2.createTrackbar("b min", "LAB Reglages", t["b_min"], 255, nothing)
    cv2.createTrackbar("b max", "LAB Reglages", t["b_max"], 255, nothing)

    cv2.namedWindow("Masque FAST", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Live + Contours", cv2.WINDOW_NORMAL)

    print("\n" + "=" * 55)
    print("  CALIBRATION FAST — SEUILS HSV + LAB EN DIRECT")
    print("=" * 55)
    print("  ENTREE = sauvegarder    R = refresh    ESC = quitter")
    print("  Blanc dans le masque = pixels detectes comme bleu")
    print("  Rectangles jaunes = bandes de scotch detectees")
    print("=" * 55)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    kernel_far = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))

    while True:
        frame = stream.get()
        if frame is None:
            print("[FAST-CALIB] En attente du flux...")
            time.sleep(0.2)
            continue

        # Lire les curseurs
        h_min = cv2.getTrackbarPos("H min", "HSV Reglages")
        h_max = cv2.getTrackbarPos("H max", "HSV Reglages")
        s_min = cv2.getTrackbarPos("S min", "HSV Reglages")
        s_max = cv2.getTrackbarPos("S max", "HSV Reglages")
        v_min = cv2.getTrackbarPos("V min", "HSV Reglages")
        v_max = cv2.getTrackbarPos("V max", "HSV Reglages")
        l_min = cv2.getTrackbarPos("L min", "LAB Reglages")
        l_max = cv2.getTrackbarPos("L max", "LAB Reglages")
        a_min = cv2.getTrackbarPos("a min", "LAB Reglages")
        a_max = cv2.getTrackbarPos("a max", "LAB Reglages")
        b_min = cv2.getTrackbarPos("b min", "LAB Reglages")
        b_max = cv2.getTrackbarPos("b max", "LAB Reglages")

        # Calculer le masque combiné HSV ET LAB
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)

        mask_hsv = cv2.inRange(hsv,
            np.array([h_min, s_min, v_min]),
            np.array([h_max, s_max, v_max]))
        mask_lab = cv2.inRange(lab,
            np.array([l_min, a_min, b_min]),
            np.array([l_max, a_max, b_max]))
        # Idem que parking_detector : OR union + pre-dilation pour les fragments lointains
        mask_union = cv2.bitwise_or(mask_hsv, mask_lab)
        mask_union = cv2.dilate(mask_union, kernel_far, iterations=1)
        mask = mask_union
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        # Trouver les contours allongés
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        display = frame.copy()
        n_stripes = 0
        for c in contours:
            area = cv2.contourArea(c)
            if area < 30:  # identique au detecteur
                continue
            rect = cv2.minAreaRect(c)
            w, h = rect[1]
            if min(w, h) < 1:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect >= 2.0:  # identique au detecteur
                box = cv2.boxPoints(rect).astype(int)
                cv2.drawContours(display, [box], 0, (0, 200, 255), 2)
                n_stripes += 1

        # Stats
        n_px = cv2.countNonZero(mask)
        cv2.putText(display, f"Pixels: {n_px}  Bandes: {n_stripes}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(display, "ENTREE=save  ESC=quitter", (10, display.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.imshow("Masque FAST", mask)
        cv2.imshow("Live + Contours", display)

        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            print("[FAST-CALIB] Annule sans sauvegarde.")
            break
        elif key in (13, 10):  # ENTREE
            result = {
                "H_min": h_min, "H_max": h_max,
                "S_min": s_min, "S_max": s_max,
                "V_min": v_min, "V_max": v_max,
                "L_min": l_min, "L_max": l_max,
                "a_min": a_min, "a_max": a_max,
                "b_min": b_min, "b_max": b_max,
            }
            THRESHOLDS_FILE.write_text(json.dumps(result, indent=2))
            print(f"\n[OK] Seuils sauvegardes dans {THRESHOLDS_FILE}")
            print(json.dumps(result, indent=2))
            break

    stream.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
