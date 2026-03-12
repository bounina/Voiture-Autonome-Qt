import cv2
import sys
import numpy as np
from parking_detector import ParkingDetector
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_detection_offline.py <image.jpg>")
        sys.exit(1)

    img_path = sys.argv[1]
    if not Path(img_path).exists():
        print(f"File not found: {img_path}")
        sys.exit(1)

    # Charger l'image complète
    frame = cv2.imread(img_path)
    if frame is None:
        print(f"Failed to load image: {img_path}")
        sys.exit(1)

    print(f"Testing on {img_path} ({frame.shape[1]}x{frame.shape[0]})")

    try:
        # Initialiser le détecteur
        detector = ParkingDetector()
        
        # Run the full pipeline
        spots, mask, rects, v_lines = detector.detect(frame)
        
        # Draw results
        display = frame.copy()
        detector.draw_detections(display, spots, rects=rects, show_mask=True, mask=mask)
        
        # Affichage
        out_path = Path(img_path).with_name(f"debug_{Path(img_path).name}")
        cv2.imwrite(str(out_path), display)
        
        print(f"Found {len(rects)} stripes and {len(spots)} parking spots.")
        print(f"Saved debug image to {out_path}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
