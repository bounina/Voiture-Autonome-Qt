#!/usr/bin/env python3
"""
record_dataset.py — Outil de collecte d'images pour l'entraînement YOLOv8.

Se connecte au Raspberry Pi et sauvegarde automatiquement 1 frame toutes
les X secondes pour créer le dataset de la voiture en environnement réel.

Usage:
    python record_dataset.py --pi-ip 192.168.1.42 --interval 1.5
"""

import argparse
import os
import socket
import struct
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

DATASET_DIR = Path("dataset_raw")


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


class StreamGrabber:
    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while self.running:
            try:
                s = socket.socket()
                s.settimeout(5)
                s.connect((self.ip, self.port))
                self.connected = True
                print(f"[COLLECTE] 🟢 Connecté au flux {self.ip}:{self.port}")
                
                while self.running:
                    try:
                        size = struct.unpack(">I", recv_exact(s, 4))[0]
                        data = recv_exact(s, size)
                        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            with self.lock:
                                self.frame = frame
                    except socket.timeout:
                        pass
            except Exception as e:
                if self.connected:
                    print(f"[COLLECTE] 🔴 Perte de flux : {e}")
                    self.connected = False
                time.sleep(1)

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pi-ip", required=True, help="IP de la Raspberry")
    parser.add_argument("--video-port", type=int, default=8885)
    parser.add_argument("--interval", type=float, default=1.0, help="Secondes entre chaque photo")
    args = parser.parse_args()

    DATASET_DIR.mkdir(exist_ok=True)
    n_existing = len(list(DATASET_DIR.glob("*.jpg")))
    
    # Start stream
    stream = StreamGrabber(args.pi_ip, args.video_port)
    
    print("\n" + "="*50)
    print(" 📸 COLLECTE DE DATASET POUR YOLOv8")
    print("="*50)
    print(f" Intervalle     : {args.interval} secondes")
    print(f" Dossier        : {DATASET_DIR.absolute()}")
    print(f" Photos stockées: {n_existing}")
    print("\n Instructions :")
    print(" 1. Roule avec la voiture autour des places")
    print(" 2. Le script prend des captures automatiquement")
    print(" 3. Appuie sur [ESC] ou [Q] pour quitter et sauvegarder")
    print("="*50 + "\n")

    cv2.namedWindow("Collecte Live", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Collecte Live", 800, 600)

    last_save_time = time.time()
    saved_count = 0
    paused = False

    try:
        while True:
            frame = stream.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            
            now = time.time()
            display = frame.copy()

            if not paused and (now - last_save_time) >= args.interval:
                # Sauvegarder l'image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                filename = f"parking_{timestamp}.jpg"
                filepath = DATASET_DIR / filename
                cv2.imwrite(str(filepath), frame)
                
                saved_count += 1
                last_save_time = now
                print(f"[+] Sauvée : {filename} (Total session: {saved_count})")
                
                # Feedback visuel
                cv2.rectangle(display, (0, 0), (display.shape[1], display.shape[0]), (0, 255, 0), 10)

            # HUD
            color = (0, 0, 255) if paused else (0, 255, 0)
            status = "PAUSE (Espace)" if paused else f"Enregistre (Session: {saved_count})"
            cv2.putText(display, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(display, f"Total images ds dossier: {n_existing + saved_count}", 
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            cv2.imshow("Collecte Live", display)

            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord('q'), ord('Q')):
                break
            elif key == 32:  # Espace
                paused = not paused
                print(f"[{'PAUSE' if paused else 'REPRISE'}]")
    
    finally:
        stream.stop()
        cv2.destroyAllWindows()
        print(f"\n✅ Terminé. {saved_count} images recoltées.")
        print(f"📁 Ouvrir {DATASET_DIR.absolute()} pour les annoter sur Roboflow.")

if __name__ == "__main__":
    main()
