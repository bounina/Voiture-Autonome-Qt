import cv2
import numpy as np
from ultralytics import YOLO

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class ParkingDetectorYOLO:
    """
    Détecteur de places de parking utilisant YOLOv8 Instance Segmentation.
    Remplace l'ancienne logique basée sur la couleur (HSV) et la géométrie.
    """
    def __init__(self, model_path=None):
        if model_path is None:
            # Résoudre le chemin absolu vers le dossier modeles_et_donnees
            model_path = str(PROJECT_ROOT / "modeles_et_donnees" / "runs" / "segment" / "runs" / "parking_seg" / "train_yolov8n" / "weights" / "best.pt")
            
        # On charge le réseau de neurones entraîné (silencieux pour le stream)
        print(f"[YOLO] Chargement du modèle depuis {model_path}...")
        self.model = YOLO(model_path)
        print("[YOLO] Modèle chargé et prêt !")

    def detect(self, img):
        """
        Effectue l'inférence YOLO et retourne les places au même format
        que l'ancien détecteur pour être 100% compatible.
        """
        # Exécuter l'inférence YOLO (conf=0.6 pour éviter les faux positifs)
        results = self.model(img, conf=0.6, verbose=False)
        result = results[0]  # On prend la première image du batch

        spots = []

        # Si des masques ont été détectés
        if result.masks is not None:
            # result.masks.xy contient les listes de points [x, y] des contours
            for polygon in result.masks.xy:
                if len(polygon) < 3:
                    continue
                    
                pts = np.array(polygon, np.int32).reshape((-1, 1, 2))
                
                # --- Lissage très léger (retire les vagues sans casser la forme) ---
                # On utilise directement les points YOLO au lieu d'une enveloppe
                epsilon = 0.015 * cv2.arcLength(pts, True)
                approx = cv2.approxPolyDP(pts, epsilon, True)
                
                # Si l'approximation a trop peu de points, on garde le brut
                final_pts = approx if len(approx) >= 4 else pts
                
                # Calculer le centre géométrique
                M = cv2.moments(final_pts)
                if M['m00'] != 0:
                    cx = int(M['m10'] / M['m00'])
                    cy = int(M['m01'] / M['m00'])
                else:
                    x, y, w, h = cv2.boundingRect(final_pts)
                    cx = x + w // 2
                    cy = y + h // 2

                spots.append({
                    'contour': final_pts,
                    'center': (cx, cy)
                })

        # On retourne un tuple (spots, mask, rects, something) compatible avec teleop_client
        return spots, None, [], None

    def draw_detections(self, frame, spots, rects=None, show_mask=True, mask=None):
        """
        Dessine les polygones et les centres sur le frame.
        """
        for idx, spot in enumerate(spots):
            pts = spot['contour']
            cx, cy = spot['center']
            
            # 1. Remplir le polygone avec un bleu-cyan très doux et transparent
            color_fill = (220, 180, 80)    # BGR: Bleu clair/Gris
            color_border = (230, 200, 100) # Un peu plus vif pour le bord
            
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color_fill)
            # 15% d'opacité seulement pour le remplissage
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            
            # 2. Dessiner la bordure très fine (1 = discret) avec anti-aliasing
            cv2.polylines(frame, [pts], True, color_border, 1, cv2.LINE_AA)
            
            # 3. Dessiner le point central et le texte (plus petit et discret)
            cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(frame, f"P{idx+1}", (cx - 15, cy - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1, cv2.LINE_AA)

        if spots:
            cv2.putText(frame, f"PLACES: {len(spots)}", (20, h:=frame.shape[0] - 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 200, 100), 1, cv2.LINE_AA)
