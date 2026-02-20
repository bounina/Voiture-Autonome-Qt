#!/usr/bin/env python3
"""
parking_detector.py — Détection de places de parking (scotch bleu).

Pipeline :
  1. Filtrage HSV pour isoler le scotch bleu → masque binaire
  2. Morphologie (erode/dilate) pour nettoyer le masque
  3. Détection de contours (findContours)
  4. Approximation polygonale → filtrage rectangles
  5. Retourne les places détectées (bbox + statut)

Utilisé par teleop_client.py en thread séparé.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

HSV_CONFIG_FILE = Path(__file__).parent / "hsv_config.json"

# Défauts HSV pour scotch bleu
_DEFAULT_HSV = {
    "h_min": 90, "s_min": 50, "v_min": 50,
    "h_max": 130, "s_max": 255, "v_max": 255,
}


class ParkingDetector:
    """Détecte les places de parking tracées au scotch bleu."""

    def __init__(self,
                 min_area: int = 3000,
                 max_area: int = 80000,
                 min_aspect: float = 0.3,
                 max_aspect: float = 3.5):
        """
        Args:
            min_area: surface minimale d'un contour pour être considéré (px²)
            max_area: surface maximale (px²)
            min_aspect: ratio largeur/hauteur minimum
            max_aspect: ratio largeur/hauteur maximum
        """
        self.min_area = min_area
        self.max_area = max_area
        self.min_aspect = min_aspect
        self.max_aspect = max_aspect

        # Charger la config HSV
        self.hsv_lower, self.hsv_upper = self._load_hsv()

        # Noyau morphologique
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

    def _load_hsv(self) -> tuple[np.ndarray, np.ndarray]:
        """Charge les seuils HSV depuis hsv_config.json ou utilise les défauts."""
        cfg = _DEFAULT_HSV.copy()
        if HSV_CONFIG_FILE.exists():
            try:
                with open(HSV_CONFIG_FILE) as f:
                    loaded = json.load(f)
                cfg.update(loaded)
                print(f"[PARKING] HSV chargé : {HSV_CONFIG_FILE}")
            except Exception:
                print("[PARKING] Erreur lecture HSV, utilisation des défauts")
        else:
            print("[PARKING] Pas de hsv_config.json, utilisation des défauts")
            print("  → Lance calibrate_hsv.py d'abord pour de meilleurs résultats !")

        lower = np.array([cfg["h_min"], cfg["s_min"], cfg["v_min"]])
        upper = np.array([cfg["h_max"], cfg["s_max"], cfg["v_max"]])
        return lower, upper

    def reload_hsv(self):
        """Recharge la config HSV (utile si on calibre en live)."""
        self.hsv_lower, self.hsv_upper = self._load_hsv()

    def _get_blue_mask(self, frame: np.ndarray) -> np.ndarray:
        """Segmentation HSV → masque binaire du scotch bleu."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)

        # Nettoyage morphologique
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)

        return mask

    def _find_line_segments(self, mask: np.ndarray) -> np.ndarray | None:
        """Détection de lignes via HoughLinesP sur le masque."""
        edges = cv2.Canny(mask, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                                threshold=40, minLineLength=30, maxLineGap=20)
        return lines

    def _find_rectangles(self, mask: np.ndarray) -> list[dict]:
        """Trouve les contours rectangulaires dans le masque."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)

        spots = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area or area > self.max_area:
                continue

            # Approximation polygonale
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

            # Rectangle si 4 côtés (ou 4-6 si angles arrondis)
            if len(approx) < 4 or len(approx) > 8:
                continue

            # Bounding box orientée
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (w_r, h_r), angle = rect
            if w_r == 0 or h_r == 0:
                continue

            aspect = max(w_r, h_r) / min(w_r, h_r)
            if aspect < self.min_aspect or aspect > self.max_aspect:
                continue

            # Box points pour le dessin
            box = cv2.boxPoints(rect)
            box = np.int32(box)

            spots.append({
                "center": (int(cx), int(cy)),
                "size": (int(max(w_r, h_r)), int(min(w_r, h_r))),
                "angle": angle,
                "box": box,
                "area": int(area),
                "contour": approx,
            })

        # Trier par taille (les plus grosses places en premier)
        spots.sort(key=lambda s: s["area"], reverse=True)
        return spots

    def detect(self, frame: np.ndarray) -> tuple[list[dict], np.ndarray]:
        """
        Pipeline complet de détection.
        
        Args:
            frame: image BGR de la caméra

        Returns:
            (spots, mask) — liste des places détectées + masque binaire
        """
        mask = self._get_blue_mask(frame)
        spots = self._find_rectangles(mask)
        return spots, mask

    def draw_detections(self, frame: np.ndarray,
                        spots: list[dict],
                        show_mask: bool = False,
                        mask: np.ndarray | None = None) -> None:
        """
        Dessine les places détectées sur le frame.
        
        Args:
            frame: image sur laquelle dessiner (modifiée in place)
            spots: liste des places trouvées par detect()
            show_mask: si True, affiche le masque en mini dans le coin
            mask: masque binaire (nécessaire si show_mask=True)
        """
        for i, spot in enumerate(spots):
            box = spot["box"]
            cx, cy = spot["center"]
            w, h = spot["size"]

            # Rectangle vert autour de la place
            cv2.drawContours(frame, [box], 0, (0, 255, 0), 2, cv2.LINE_AA)

            # Label
            label = f"P{i+1} ({w}x{h})"
            cv2.putText(frame, label, (cx - 30, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(frame, label, (cx - 30, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 255, 0), 1, cv2.LINE_AA)

            # Centre
            cv2.circle(frame, (cx, cy), 4, (0, 255, 0), -1, cv2.LINE_AA)

        # Compteur en haut à droite
        h_f, w_f = frame.shape[:2]
        n = len(spots)
        color = (0, 255, 0) if n > 0 else (0, 0, 255)
        cv2.putText(frame, f"PLACES: {n}", (w_f - 150, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        # Mini masque en bas à droite (debug)
        if show_mask and mask is not None:
            mini_h = h_f // 5
            mini_w = w_f // 5
            mini_mask = cv2.resize(mask, (mini_w, mini_h))
            mini_mask_bgr = cv2.cvtColor(mini_mask, cv2.COLOR_GRAY2BGR)
            frame[h_f - mini_h:, w_f - mini_w:] = mini_mask_bgr
