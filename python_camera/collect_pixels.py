#!/usr/bin/env python3
"""
collect_pixels.py — Collecte d'échantillons de pixels pour entraîner le KNN.

Mode d'emploi :
  1. Lance le script → il capture un frame depuis la caméra Pi
  2. CLIC GAUCHE sur des pixels de scotch bleu (positifs)
  3. CLIC DROIT sur des pixels du sol/mur/autre (négatifs)
  4. Appuie N pour capturer un nouveau frame (angle/lumière différente)
  5. Appuie ENTRÉE pour sauvegarder, ESC pour annuler

Les pixels sont stockés en HSV + label dans pixel_samples.npz.
Relance le script pour AJOUTER des pixels (il charge les anciens).

Usage :
    python collect_pixels.py --pi-ip 192.168.1.42
"""

from __future__ import annotations

import argparse
import socket
import struct
from pathlib import Path

import cv2
import numpy as np

SAMPLES_FILE = Path(__file__).parent / "pixel_samples.npz"

# Taille du carré de pixels collectés autour du clic (ex: 5 = carré 11×11)
PATCH_RADIUS = 5


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
    print(f"[COLLECT] Connexion à {ip}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)
    s.connect((ip, port))
    s.settimeout(5.0)

    # Skip warmup
    for _ in range(10):
        header = recv_exact(s, 4)
        frame_size = struct.unpack(">I", header)[0]
        jpeg_data = recv_exact(s, frame_size)

    frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
    s.close()
    print(f"[COLLECT] Frame capturée : {frame.shape[1]}x{frame.shape[0]}")
    return frame


class PixelCollector:
    """Gère les clics souris et la collecte de pixels."""

    def __init__(self, frame: np.ndarray):
        self.frame = frame.copy()
        self.display = frame.copy()
        self.hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        self.h, self.w = frame.shape[:2]

        # Listes de pixels collectés
        self.positives: list[np.ndarray] = []  # HSV des pixels bleus
        self.negatives: list[np.ndarray] = []  # HSV des pixels non-bleus

        self.n_pos = 0
        self.n_neg = 0

    def on_click(self, event, x, y, flags, param):
        """Callback de la souris."""
        if event == cv2.EVENT_LBUTTONDOWN:
            self._collect_patch(x, y, label=1)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._collect_patch(x, y, label=0)

    def _collect_patch(self, cx: int, cy: int, label: int):
        """Collecte un carré de pixels autour du clic."""
        r = PATCH_RADIUS
        y0 = max(0, cy - r)
        y1 = min(self.h, cy + r + 1)
        x0 = max(0, cx - r)
        x1 = min(self.w, cx + r + 1)

        patch = self.hsv[y0:y1, x0:x1].reshape(-1, 3)

        if label == 1:
            self.positives.append(patch)
            self.n_pos += len(patch)
            color = (0, 255, 0)  # Vert = bleu collecté
            tag = "+"
        else:
            self.negatives.append(patch)
            self.n_neg += len(patch)
            color = (0, 0, 255)  # Rouge = non-bleu collecté
            tag = "-"

        # Dessiner le marqueur
        cv2.rectangle(self.display, (x0, y0), (x1, y1), color, 2)
        cv2.putText(self.display, tag, (cx - 5, cy - r - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        print(f"  [{tag}] Pixel ({cx},{cy}) HSV moy: {patch.mean(axis=0).astype(int)}"
              f"  |  Total: {self.n_pos} bleus, {self.n_neg} autres")

    def update_frame(self, frame: np.ndarray):
        """Change le frame (nouvelle capture)."""
        self.frame = frame.copy()
        self.display = frame.copy()
        self.hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        self.h, self.w = frame.shape[:2]

    def get_display(self) -> np.ndarray:
        """Retourne le frame avec les marqueurs."""
        img = self.display.copy()
        # Barre d'info en haut
        info = f"BLEU(clic G): {self.n_pos}   SOL(clic D): {self.n_neg}   N=nouveau frame   ENTREE=sauver   ESC=annuler"
        cv2.putText(img, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1, cv2.LINE_AA)
        return img

    def get_samples(self) -> tuple[np.ndarray, np.ndarray]:
        """Retourne (X, y) — features HSV et labels."""
        if not self.positives and not self.negatives:
            return np.empty((0, 3)), np.empty(0)

        pos = np.vstack(self.positives) if self.positives else np.empty((0, 3))
        neg = np.vstack(self.negatives) if self.negatives else np.empty((0, 3))

        X = np.vstack([pos, neg])
        y = np.hstack([np.ones(len(pos)), np.zeros(len(neg))])
        return X, y


def main():
    parser = argparse.ArgumentParser(description="Collecte de pixels pour KNN")
    parser.add_argument("--pi-ip", required=True, help="IP du Raspberry Pi")
    parser.add_argument("--video-port", type=int, default=8885)
    args = parser.parse_args()

    frame = capture_frame(args.pi_ip, args.video_port)
    collector = PixelCollector(frame)

    win = "Collecte Pixels — Clic G=bleu  Clic D=sol"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, collector.on_click)

    print("\n" + "=" * 60)
    print("  COLLECTE DE PIXELS POUR LE CLASSIFIEUR KNN")
    print("=" * 60)
    print("  CLIC GAUCHE  = pixel SCOTCH BLEU (positif)")
    print("  CLIC DROIT   = pixel SOL / MUR (négatif)")
    print("  N            = capturer un NOUVEAU frame")
    print("  ENTRÉE       = sauvegarder et quitter")
    print("  ESC          = annuler")
    print("=" * 60)
    print(f"  Rayon de collecte : {PATCH_RADIUS}px → carré {2*PATCH_RADIUS+1}×{2*PATCH_RADIUS+1}")
    print("=" * 60 + "\n")

    while True:
        cv2.imshow(win, collector.get_display())
        key = cv2.waitKey(30) & 0xFF

        if key == 27:  # ESC
            print("[COLLECT] Annulé.")
            break

        elif key in (13, 10):  # ENTER
            X, y = collector.get_samples()
            if len(X) == 0:
                print("[COLLECT] Aucun pixel collecté !")
                continue

            # Charger les anciens si existants
            if SAMPLES_FILE.exists():
                old = np.load(SAMPLES_FILE)
                X_old, y_old = old["X"], old["y"]
                X = np.vstack([X_old, X])
                y = np.hstack([y_old, y])
                print(f"[COLLECT] Fusionné avec {len(X_old)} pixels existants")

            np.savez(SAMPLES_FILE, X=X, y=y)
            n_pos = int(np.sum(y == 1))
            n_neg = int(np.sum(y == 0))
            print(f"\n✅ Sauvegardé dans : {SAMPLES_FILE}")
            print(f"   Total : {n_pos} pixels bleus + {n_neg} pixels sol = {len(X)} pixels")
            print(f"\n→ Prochaine étape : python train_knn.py")
            break

        elif key == ord('n') or key == ord('N'):
            print("[COLLECT] Capture d'un nouveau frame...")
            try:
                frame = capture_frame(args.pi_ip, args.video_port)
                collector.update_frame(frame)
                print("[COLLECT] Nouveau frame chargé — continue à cliquer !")
            except Exception as e:
                print(f"[COLLECT] Erreur capture : {e}")

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
