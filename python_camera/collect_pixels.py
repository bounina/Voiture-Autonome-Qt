#!/usr/bin/env python3
"""
collect_pixels.py — Collecte d'échantillons de pixels pour entraîner le KNN.

Mode d'emploi :
  1. Lance le script → il capture un frame depuis la caméra Pi
  2. CLIC GAUCHE sur des pixels de scotch bleu (positifs)
  3. CLIC DROIT sur des pixels du sol/mur/autre (négatifs)
  4. Appuie N pour capturer un nouveau frame (angle/lumière différente)
  5. Appuie ENTRÉE pour sauvegarder, ESC pour annuler

Features : 6 canaux (H, S, V, L, a, b) pour chaque pixel.
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

# Taille du carré de pixels collectés autour du clic (ex: 1 = carré 3×3)
DEFAULT_PATCH_RADIUS = 1

# Nombre de features par pixel (H, S, V, L, a, b)
N_FEATURES = 6


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

    for _ in range(10):
        header = recv_exact(s, 4)
        frame_size = struct.unpack(">I", header)[0]
        jpeg_data = recv_exact(s, frame_size)

    frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
    s.close()
    print(f"[COLLECT] Frame capturée : {frame.shape[1]}x{frame.shape[0]}")
    return frame


def extract_features(bgr_patch: np.ndarray) -> np.ndarray:
    """Extrait les 6 features HSV+LAB d'un patch BGR.
    
    Returns: array (N, 6) avec colonnes [H, S, V, L, a, b].
    """
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2LAB)
    # Concaténer H,S,V,L,a,b
    return np.hstack([
        hsv.reshape(-1, 3),
        lab.reshape(-1, 3),
    ]).astype(np.float32)


class PixelCollector:
    """Gère les clics souris et la collecte de pixels."""

    def __init__(self, frame: np.ndarray):
        self.frame = frame.copy()
        self.display = frame.copy()
        self.h, self.w = frame.shape[:2]

        self.positives: list[np.ndarray] = []
        self.negatives: list[np.ndarray] = []

        self.n_pos = 0
        self.n_neg = 0
        self.radius = DEFAULT_PATCH_RADIUS

        # Historique pour undo : [(label, n_pixels, (x0,y0,x1,y1))]
        self.history: list[tuple] = []

        # Position souris pour le curseur
        self.mouse_x = -1
        self.mouse_y = -1

        # Drag support
        self._dragging = False
        self._drag_label = 0
        self._last_drag_pos = (-100, -100)

    def on_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._collect_patch(x, y, label=1)
            self._dragging = True
            self._drag_label = 1
            self._last_drag_pos = (x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._collect_patch(x, y, label=0)
            self._dragging = True
            self._drag_label = 0
            self._last_drag_pos = (x, y)
        elif event in (cv2.EVENT_LBUTTONUP, cv2.EVENT_RBUTTONUP):
            self._dragging = False
        elif event == cv2.EVENT_MOUSEMOVE:
            self.mouse_x, self.mouse_y = x, y
            if self._dragging:
                # Collecter si assez loin du dernier point
                dx = x - self._last_drag_pos[0]
                dy = y - self._last_drag_pos[1]
                spacing = max(2 * self.radius + 1, 5)
                if dx * dx + dy * dy >= spacing * spacing:
                    self._collect_patch(x, y, label=self._drag_label)
                    self._last_drag_pos = (x, y)

    def _collect_patch(self, cx: int, cy: int, label: int):
        r = self.radius
        y0 = max(0, cy - r)
        y1 = min(self.h, cy + r + 1)
        x0 = max(0, cx - r)
        x1 = min(self.w, cx + r + 1)

        bgr_patch = self.frame[y0:y1, x0:x1]
        features = extract_features(bgr_patch)
        n_px = len(features)

        if label == 1:
            self.positives.append(features)
            self.n_pos += n_px
            color = (0, 255, 0)
            tag = "+"
        else:
            self.negatives.append(features)
            self.n_neg += n_px
            color = (0, 0, 255)
            tag = "-"

        self.history.append((label, n_px, (x0, y0, x1, y1)))

        cv2.rectangle(self.display, (x0, y0), (x1, y1), color, 2)
        cv2.putText(self.display, tag, (cx - 5, cy - r - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        hsv_mean = features[:, :3].mean(axis=0).astype(int)
        lab_mean = features[:, 3:].mean(axis=0).astype(int)
        print(f"  [{tag}] ({cx},{cy}) HSV:{hsv_mean} LAB:{lab_mean}"
              f"  |  Total: {self.n_pos} bleus, {self.n_neg} sol")

    def undo(self):
        """Annule le dernier clic."""
        if not self.history:
            print("  [UNDO] Rien à annuler")
            return
        label, n_px, _rect = self.history.pop()
        if label == 1:
            self.positives.pop()
            self.n_pos -= n_px
        else:
            self.negatives.pop()
            self.n_neg -= n_px
        # Redessiner depuis zéro
        self._redraw()
        tag = "+bleu" if label == 1 else "-sol"
        print(f"  [UNDO] {tag} ({n_px}px) annulé → {self.n_pos} bleus, {self.n_neg} sol")

    def _redraw(self):
        """Redessine tous les marqueurs depuis l'historique."""
        self.display = self.frame.copy()
        for label, _n, (x0, y0, x1, y1) in self.history:
            color = (0, 255, 0) if label == 1 else (0, 0, 255)
            tag = "+" if label == 1 else "-"
            cv2.rectangle(self.display, (x0, y0), (x1, y1), color, 2)
            cx = (x0 + x1) // 2
            cv2.putText(self.display, tag, (cx - 5, y0 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

    def update_frame(self, frame: np.ndarray):
        self.frame = frame.copy()
        self.display = frame.copy()
        self.h, self.w = frame.shape[:2]

    def get_display(self) -> np.ndarray:
        img = self.display.copy()
        r = self.radius
        sz = 2 * r + 1

        # Curseur : rectangle suivant la souris
        if self.mouse_x >= 0 and self.mouse_y >= 0:
            mx, my = self.mouse_x, self.mouse_y
            cv2.rectangle(img, (mx - r, my - r), (mx + r, my + r),
                          (255, 255, 0), 1)

        # HUD
        info = f"BLEU(G):{self.n_pos}  SOL(D):{self.n_neg}  {sz}x{sz}(+/-)  U=undo  N=frame  ENTREE=sauver"
        cv2.putText(img, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (255, 255, 255), 1, cv2.LINE_AA)
        return img

    def get_samples(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.positives and not self.negatives:
            return np.empty((0, N_FEATURES)), np.empty(0)

        pos = np.vstack(self.positives) if self.positives else np.empty((0, N_FEATURES))
        neg = np.vstack(self.negatives) if self.negatives else np.empty((0, N_FEATURES))

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
    print("  COLLECTE DE PIXELS – Features HSV + LAB (6D)")
    print("=" * 60)
    print("  CLIC GAUCHE  = pixel SCOTCH BLEU (positif)")
    print("  CLIC DROIT   = pixel SOL / MUR (négatif)")
    print("  U            = UNDO (annuler le dernier clic)")
    print("  N            = capturer un NOUVEAU frame")
    print("  +/-          = agrandir/réduire le curseur")
    print("  ENTRÉE       = sauvegarder et quitter")
    print("  ESC          = annuler")
    print("=" * 60)
    print(f"  6 features/pixel : H, S, V, L, a, b")
    print(f"  Rayon initial : {collector.radius}px (ajustable +/-)")
    print("=" * 60 + "\n")

    while True:
        cv2.imshow(win, collector.get_display())
        key = cv2.waitKey(30) & 0xFF

        if key == 27:
            print("[COLLECT] Annulé.")
            break

        elif key in (13, 10):
            X, y = collector.get_samples()
            if len(X) == 0:
                print("[COLLECT] Aucun pixel collecté !")
                continue

            if SAMPLES_FILE.exists():
                old = np.load(SAMPLES_FILE)
                X_old, y_old = old["X"], old["y"]
                if X_old.shape[1] == N_FEATURES:
                    X = np.vstack([X_old, X])
                    y = np.hstack([y_old, y])
                    print(f"[COLLECT] Fusionné avec {len(X_old)} pixels existants")
                else:
                    print(f"[COLLECT] Ancien format ({X_old.shape[1]}D) → remplacé par 6D")

            np.savez(SAMPLES_FILE, X=X, y=y)
            n_pos = int(np.sum(y == 1))
            n_neg = int(np.sum(y == 0))
            print(f"\n✅ Sauvegardé dans : {SAMPLES_FILE}")
            print(f"   Total : {n_pos} bleus + {n_neg} sol = {len(X)} pixels ({N_FEATURES}D)")
            print(f"\n→ Prochaine étape : python train_knn.py")
            break

        elif key == ord('n') or key == ord('N'):
            print("[COLLECT] Capture d'un nouveau frame...")
            try:
                frame = capture_frame(args.pi_ip, args.video_port)
                collector.update_frame(frame)
                print("[COLLECT] Nouveau frame chargé !")
            except Exception as e:
                print(f"[COLLECT] Erreur capture : {e}")

        elif key in (ord('+'), ord('=')):
            collector.radius = min(collector.radius + 1, 15)
            sz = 2 * collector.radius + 1
            print(f"[COLLECT] Curseur → {sz}×{sz}px")

        elif key == ord('-'):
            collector.radius = max(collector.radius - 1, 0)
            sz = 2 * collector.radius + 1
            print(f"[COLLECT] Curseur → {sz}×{sz}px")

        elif key in (ord('u'), ord('U')):
            collector.undo()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
