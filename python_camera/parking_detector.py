#!/usr/bin/env python3
"""
parking_detector.py — Détection de places de parking (scotch bleu).

Pipeline :
  1. Classifieur KNN (ou fallback seuils HSV) → masque binaire
  2. Morphologie (erode/dilate) pour nettoyer
  3. HoughLinesP pour détecter les segments de lignes
  4. Classification en lignes horizontales / verticales
  5. Appariement : chaque paire de verticales adjacentes = 1 place

Utilisé par teleop_client.py en thread séparé.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

HSV_CONFIG_FILE = Path(__file__).parent / "hsv_config.json"
KNN_MODEL_FILE = Path(__file__).parent / "knn_model.xml"

_DEFAULT_HSV = {
    "h_min": 90, "s_min": 50, "v_min": 50,
    "h_max": 130, "s_max": 255, "v_max": 255,
}


def _angle_deg(x1: int, y1: int, x2: int, y2: int) -> float:
    """Angle d'un segment en degrés (0=horizontal, 90=vertical)."""
    return abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))


def _merge_lines(lines: list[tuple], is_vertical: bool,
                 gap: int = 30) -> list[tuple]:
    """Fusionne les segments proches et colinéaires."""
    if not lines:
        return []

    if is_vertical:
        lines.sort(key=lambda l: (l[0] + l[2]) / 2)
    else:
        lines.sort(key=lambda l: (l[1] + l[3]) / 2)

    merged = []
    current = list(lines[0])

    for seg in lines[1:]:
        if is_vertical:
            cx_cur = (current[0] + current[2]) / 2
            cx_new = (seg[0] + seg[2]) / 2
            close = abs(cx_cur - cx_new) < gap
        else:
            cy_cur = (current[1] + current[3]) / 2
            cy_new = (seg[1] + seg[3]) / 2
            close = abs(cy_cur - cy_new) < gap

        if close:
            current[0] = min(current[0], seg[0])
            current[1] = min(current[1], seg[1])
            current[2] = max(current[2], seg[2])
            current[3] = max(current[3], seg[3])
        else:
            merged.append(tuple(current))
            current = list(seg)

    merged.append(tuple(current))
    return merged


class ParkingDetector:
    """Détecte les places de parking tracées au scotch bleu (pattern peigne)."""

    def __init__(self,
                 angle_thresh: float = 25.0,
                 min_line_length: int = 40,
                 max_line_gap: int = 25,
                 merge_gap: int = 35,
                 knn_k: int = 5):
        self.angle_thresh = angle_thresh
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap
        self.merge_gap = merge_gap
        self.knn_k = knn_k

        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

        # Charger le KNN ou fallback sur seuils HSV
        self.knn = None
        self.use_knn = False
        self._load_knn()

        if not self.use_knn:
            self.hsv_lower, self.hsv_upper = self._load_hsv()

    def _load_knn(self):
        """Charge le modèle KNN depuis knn_model.xml."""
        if KNN_MODEL_FILE.exists():
            try:
                self.knn = cv2.ml.KNearest_load(str(KNN_MODEL_FILE))
                self.use_knn = True
                print(f"[PARKING] ✅ Modèle KNN chargé : {KNN_MODEL_FILE}")
                print(f"[PARKING]    → Classification par apprentissage (K={self.knn_k})")
            except Exception as e:
                print(f"[PARKING] ⚠ Erreur chargement KNN : {e}")
                self.use_knn = False
        else:
            print(f"[PARKING] Pas de modèle KNN ({KNN_MODEL_FILE})")
            print(f"[PARKING]    → Fallback sur seuils HSV manuels")
            print(f"[PARKING]    → Pour de meilleurs résultats :")
            print(f"[PARKING]      1. python collect_pixels.py --pi-ip <IP>")
            print(f"[PARKING]      2. python train_knn.py")

    def _load_hsv(self) -> tuple[np.ndarray, np.ndarray]:
        cfg = _DEFAULT_HSV.copy()
        if HSV_CONFIG_FILE.exists():
            try:
                with open(HSV_CONFIG_FILE) as f:
                    loaded = json.load(f)
                cfg.update(loaded)
            except Exception:
                pass

        lower = np.array([cfg["h_min"], cfg["s_min"], cfg["v_min"]])
        upper = np.array([cfg["h_max"], cfg["s_max"], cfg["v_max"]])
        return lower, upper

    def _get_mask_knn(self, frame: np.ndarray) -> np.ndarray:
        """Masque binaire via le classifieur KNN (meilleur)."""
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Reshape pour KNN : (H*W, 3) float32
        pixels = hsv.reshape(-1, 3).astype(np.float32)

        # Prédiction
        _, results, _, _ = self.knn.findNearest(pixels, self.knn_k)
        mask = (results.flatten() == 1).astype(np.uint8) * 255
        mask = mask.reshape(h, w)

        # Nettoyage morphologique
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)

        return mask

    def _get_mask_hsv(self, frame: np.ndarray) -> np.ndarray:
        """Masque binaire via seuils HSV (fallback)."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)
        return mask

    def _get_blue_mask(self, frame: np.ndarray) -> np.ndarray:
        """Masque binaire — KNN si disponible, sinon seuils HSV."""
        if self.use_knn:
            return self._get_mask_knn(frame)
        else:
            return self._get_mask_hsv(frame)

    def _detect_lines(self, mask: np.ndarray) -> tuple[list, list]:
        edges = cv2.Canny(mask, 50, 150)
        raw = cv2.HoughLinesP(edges, 1, np.pi / 180,
                              threshold=30,
                              minLineLength=self.min_line_length,
                              maxLineGap=self.max_line_gap)

        h_lines: list[tuple] = []
        v_lines: list[tuple] = []

        if raw is None:
            return h_lines, v_lines

        for line in raw:
            x1, y1, x2, y2 = line[0]
            angle = _angle_deg(x1, y1, x2, y2)

            if angle < self.angle_thresh:
                h_lines.append((x1, y1, x2, y2))
            elif angle > (90 - self.angle_thresh):
                v_lines.append((x1, y1, x2, y2))

        h_lines = _merge_lines(h_lines, is_vertical=False, gap=self.merge_gap)
        v_lines = _merge_lines(v_lines, is_vertical=True, gap=self.merge_gap)

        return h_lines, v_lines

    def _find_spots(self, h_lines: list, v_lines: list,
                    img_h: int, img_w: int) -> list[dict]:
        if len(v_lines) < 2:
            return []

        v_sorted = sorted(v_lines, key=lambda l: (l[0] + l[2]) / 2)

        spots = []
        for i in range(len(v_sorted) - 1):
            left = v_sorted[i]
            right = v_sorted[i + 1]

            lx = int((left[0] + left[2]) / 2)
            rx = int((right[0] + right[2]) / 2)

            width = rx - lx
            if width < 20 or width > img_w * 0.8:
                continue

            top_y = min(left[1], left[3], right[1], right[3])
            bot_y = max(left[1], left[3], right[1], right[3])
            height = bot_y - top_y

            if height < 20:
                continue

            cx = (lx + rx) // 2
            cy = (top_y + bot_y) // 2

            spots.append({
                "id": i + 1,
                "rect": (lx, top_y, rx, bot_y),
                "center": (cx, cy),
                "size": (width, height),
            })

        return spots

    def detect(self, frame: np.ndarray) -> tuple[list[dict], np.ndarray,
                                                   list, list]:
        mask = self._get_blue_mask(frame)
        h_lines, v_lines = self._detect_lines(mask)
        spots = self._find_spots(h_lines, v_lines, *frame.shape[:2])
        return spots, mask, h_lines, v_lines

    def draw_detections(self, frame: np.ndarray,
                        spots: list[dict],
                        h_lines: list | None = None,
                        v_lines: list | None = None,
                        show_mask: bool = False,
                        mask: np.ndarray | None = None) -> None:
        h_f, w_f = frame.shape[:2]

        if h_lines:
            for x1, y1, x2, y2 in h_lines:
                cv2.line(frame, (x1, y1), (x2, y2), (255, 200, 0), 2, cv2.LINE_AA)
        if v_lines:
            for x1, y1, x2, y2 in v_lines:
                cv2.line(frame, (x1, y1), (x2, y2), (0, 200, 255), 2, cv2.LINE_AA)

        for spot in spots:
            lx, ty, rx, by = spot["rect"]
            cx, cy = spot["center"]
            sid = spot["id"]

            overlay = frame.copy()
            cv2.rectangle(overlay, (lx, ty), (rx, by), (0, 255, 0), -1)
            cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
            cv2.rectangle(frame, (lx, ty), (rx, by), (0, 255, 0), 2, cv2.LINE_AA)

            label = f"P{sid}"
            cv2.putText(frame, label, (cx - 12, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, label, (cx - 12, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 0), 2, cv2.LINE_AA)

        n = len(spots)
        color = (0, 255, 0) if n > 0 else (0, 0, 255)
        mode = "KNN" if self.use_knn else "HSV"
        cv2.putText(frame, f"PLACES: {n} [{mode}]", (w_f - 220, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, f"PLACES: {n} [{mode}]", (w_f - 220, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        # Legend
        cv2.putText(frame, f"H={len(h_lines or [])}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 0), 1)
        cv2.putText(frame, f"V={len(v_lines or [])}", (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)

        if show_mask and mask is not None:
            mini_h = h_f // 5
            mini_w = w_f // 5
            mini_mask = cv2.resize(mask, (mini_w, mini_h))
            mini_bgr = cv2.cvtColor(mini_mask, cv2.COLOR_GRAY2BGR)
            frame[h_f - mini_h:, w_f - mini_w:] = mini_bgr
