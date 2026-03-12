#!/usr/bin/env python3
"""
train_yolo.py — Lance l'entraînement du modèle YOLOv8 Segmentation.

Prérequis :
1. pip install ultralytics
2. Avoir téléchargé le dataset depuis Roboflow (format "YOLOv8 PyTorch")
3. Extraire le dossier du dataset ici.

Usage:
    python train_yolo.py --data dataset/data.yaml --epochs 100
"""

import argparse
from pathlib import Path

try:
    from ultralytics import YOLO
except ImportError:
    print("❌ ERREUR : La librairie 'ultralytics' n'est pas installée.")
    print("👉 Tape dans ton terminal : pip install ultralytics")
    exit(1)


def main():
    parser = argparse.ArgumentParser(description="Entraînement YOLOv8-seg pour Parking")
    parser.add_argument("--data", required=True, help="Chemin vers le data.yaml du dataset Roboflow")
    parser.add_argument("--epochs", type=int, default=100, help="Nombre de cycles d'apprentissage")
    parser.add_argument("--batch", type=int, default=8, help="Taille du batch (baisser à 4 si erreur de RAM)")
    parser.add_argument("--imgsz", type=int, default=320, help="Taille des images pour l'entraînement")
    args = parser.parse_args()

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        print(f"❌ Fichier introuvable : {data_yaml}")
        return

    print("=" * 60)
    print(" 🔥 DÉMARRAGE DE L'ENTRAÎNEMENT YOLOv8-SEG")
    print("=" * 60)
    print(f" Dataset : {args.data}")
    print(f" Modèle  : yolov8n-seg.pt (Nano, ultra-rapide)")
    print(f" Epochs  : {args.epochs}")
    print(f" Taille  : {args.imgsz}x{args.imgsz}")
    print("=" * 60)

    # 1. Charger le petit modèle pré-entraîné
    model = YOLO("yolov8n-seg.pt")

    # 2. Lancer l'entraînement
    results = model.train(
        data=str(data_yaml.absolute()),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        project="runs/parking_seg",
        name="train_yolov8n",
        device="cpu",  # On force le CPU car pas de CUDA installé
        plots=True     # Générer des graphiques de performance
    )

    print("\n" + "=" * 60)
    print(" ✅ ENTRAÎNEMENT TERMINÉ !")
    print("=" * 60)
    print(f" 📂 Le meilleur modèle est sauvegardé ici :\n runs/parking_seg/train_yolov8n/weights/best.pt")
    print(" 💡 Copie ce fichier 'best.pt' pour l'utiliser dans ton client !")


if __name__ == "__main__":
    main()
