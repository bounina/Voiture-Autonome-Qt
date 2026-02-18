# 🏎️ Voiture Autonome — Projet SAE

> Système de voiture autonome basé sur Raspberry Pi avec pilotage LIDAR, PID, et téléopération manuelle en temps réel.

---

## 📋 Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture matérielle](#architecture-matérielle)
- [Architecture logicielle](#architecture-logicielle)
- [Mode Téléopération Manuelle](#mode-téléopération-manuelle)
- [Mode Autonome (PID)](#mode-autonome-pid)
- [Installation et Déploiement](#installation-et-déploiement)
- [Mode d'emploi](#mode-demploi)
- [Structure des dépôts](#structure-des-dépôts)
- [Workflow Git](#workflow-git)

---

## Vue d'ensemble

Ce projet implémente un véhicule autonome miniature capable de :

1. **Conduite autonome** — Suivi de murs via un LIDAR 360° et un contrôleur PID (désactivé temporairement)
2. **Téléopération manuelle** — Pilotage en temps réel depuis un PC distant avec retour vidéo fluide (~30 FPS)
3. **Calibration de parking** — Projection d'une zone de stationnement virtuelle au sol par homographie

Le système est réparti sur **deux machines** reliées par WiFi :

| Machine | Rôle |
|---------|------|
| **Raspberry Pi** | Cerveau embarqué (C++ Qt) + caméra + capteurs |
| **PC Windows** | Interface opérateur (vidéo + clavier) |

---

## Architecture matérielle

```
┌─────────────────────────────────────────────────────┐
│                  RASPBERRY PI                        │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ LIDAR    │  │ TFmini   │  │ Picamera2        │  │
│  │ RPLidar  │  │ (dist.)  │  │ (caméra arrière) │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                 │             │
│  ┌────▼──────────────▼─────────────────▼──────────┐ │
│  │           sae_sbc (Qt C++)                     │ │
│  │  • Serveur TCP port 8884                       │ │
│  │  • Controleur PID / Mode Manuel                │ │
│  │  • Pilote moteur I2C (MD04)                    │ │
│  │  • Pilote servo PWM (direction)                │ │
│  └────┬───────────────────────────────┬───────────┘ │
│       │                               │             │
│  ┌────▼─────┐                   ┌─────▼──────┐     │
│  │ Moteur   │                   │ Servomoteur│     │
│  │ MD04 I2C │                   │ Direction  │     │
│  └──────────┘                   └────────────┘     │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │      video_streamer.py (Python)                │  │
│  │  • Capture Picamera2 640x480                   │  │
│  │  • Encode JPEG, stream TCP port 8885           │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                        │ WiFi
                        ▼
┌─────────────────────────────────────────────────────┐
│                  PC WINDOWS                          │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │      teleop_client.py (Python)                 │  │
│  │  • Reçoit flux vidéo JPEG (port 8885)          │  │
│  │  • Affiche cv2.imshow natif                    │  │
│  │  • Capture clavier Z/Q/S/D/Espace             │  │
│  │  • Envoie commandes TELEOP:* (port 8884)       │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## Architecture logicielle

### Communication réseau

| Port | Direction | Protocole | Contenu |
|------|-----------|-----------|---------|
| **8884** | PC → Pi | TCP texte `\n` | Commandes moteur (`TELEOP:FWD`, `on`, `off`...) |
| **8885** | Pi → PC | TCP binaire | Frames JPEG (préfixe 4 bytes longueur) |

### Protocole vidéo (port 8885)

```
┌──────────────┬────────────────────────────────────┐
│ 4 bytes      │ N bytes                            │
│ uint32 BE    │ Données JPEG                       │
│ = taille N   │                                    │
└──────────────┴────────────────────────────────────┘
  ← répétition en boucle continue →
```

### Protocole commandes (port 8884)

| Commande | Action | Détail |
|----------|--------|--------|
| `TELEOP:FWD` | Avancer | vitesse = 0.15 |
| `TELEOP:BWD` | Reculer | vitesse = -0.10 |
| `TELEOP:LEFT` | Gauche | angle -= 0.1 (borné [-1, 1]) |
| `TELEOP:RIGHT` | Droite | angle += 0.1 (borné [-1, 1]) |
| `TELEOP:STOP` | Arrêt | vitesse = 0, angle = 0 |
| `on` / `off` | Legacy | Active/désactive la boucle |

---

## Mode Téléopération Manuelle

### Fonctionnement

Le **pilotage est progressif** : chaque appui sur Q ou D incrémente ou décrémente l'angle de ±0.1 (borné entre -1.0 et 1.0). La consigne est **mémorisée** entre les appuis — pas besoin de maintenir la touche.

**Espace** effectue un arrêt complet : remet vitesse ET angle à zéro.

### Comment l'autonomie est désactivée

Dans `controleur.cpp`, la méthode `newDatas()` (appelée à chaque scan LIDAR) vérifie le flag `modeManuel` :

```cpp
if (modeManuel) {
    emit deplacer(manualSpeed, manualAngle);
    return;  // court-circuite le PID
}
// ... code PID intact ci-dessous ...
```

Le code PID (`computeError()`, `pid.update()`, `speedCtrl.update()`) est **100% conservé** et sera réactivable en basculant `modeManuel = false`.

---

## Mode Autonome (PID)

> ⚠️ Temporairement désactivé (`modeManuel = true` par défaut)

Le mode autonome utilise :
- **LIDAR RPLidar** — Scan 360° des distances aux obstacles
- **PID** — Calcul de l'erreur gauche/droite pour le suivi de murs
- **SpeedController** — Adaptation de la vitesse selon l'angle de braquage
- **TFmini** — Capteur de distance frontal complémentaire

Pour réactiver : mettre `modeManuel{false}` dans `controleur.h` ou ajouter une commande TCP `AUTO:ON`.

---

## Installation et Déploiement

### Prérequis

**Raspberry Pi :**
- Raspbian / Raspberry Pi OS
- Qt 5.x (pour compiler sae_sbc)
- Python 3.9+, `picamera2`, `opencv-python`, `numpy`

**PC Windows :**
- Python 3.9+
- `pip install opencv-python numpy`

### Compilation C++ (sur la Pi)

```bash
cd ~/Voiture-Autonome-Qt
mkdir -p build && cd build
qmake ../sae_sbc.pro
make -j4
```

---

## Mode d'emploi

### Étape 1 — Sur la Raspberry Pi (via SSH)

```bash
# Terminal 1 : Le cerveau C++ (moteurs + serveur commandes)
cd ~/Voiture-Autonome-Qt/build
./sae_sbc

# Terminal 2 : Le streaming vidéo
cd ~/Camera_arriere/python_camera
python3 video_streamer.py --rotate 180
```

### Étape 2 — Sur le PC Windows

```bash
cd C:\...\Camera_arriere\python_camera
python teleop_client.py --pi-ip 192.168.1.42
```

> Remplacer `192.168.1.42` par l'IP de votre Pi (`hostname -I` sur la Pi).

### Étape 3 — Piloter !

| Touche | Action |
|--------|--------|
| **Z** | Avancer |
| **S** | Reculer |
| **Q** | Tourner à gauche (progressif) |
| **D** | Tourner à droite (progressif) |
| **Espace** | Arrêt total |
| **ESC** | Quitter le client |

---

## Structure des dépôts

### 📁 [Voiture-Autonome-Qt](https://github.com/bounina/Voiture-Autonome-Qt)

Code C++ Qt embarqué (tourne sur la Raspberry Pi) :

```
Voiture-Autonome-Qt/
├── controleur.cpp/h      ← Logique PID + mode manuel
├── serveurtcp.cpp/h      ← Serveur TCP port 8884
├── mainwindow.cpp/h      ← Câblage signaux/slots
├── materielreel.cpp/h    ← Pilotes I2C moteur + servo
├── servomoteur.cpp/h     ← PWM direction
├── pwm.cpp/h             ← Accès GPIO PWM
├── tfmini.cpp/h          ← Capteur distance
├── sae_sbc.pro           ← Fichier projet Qt
└── RESUME_ARCHITECTURE.txt
```

### 📁 [Camera_arriere](https://github.com/bounina/Camera_arriere)

Scripts Python (divisés entre Pi et PC) :

```
Camera_arriere/
├── python_camera/
│   ├── video_streamer.py    ← [PI] Serveur streaming JPEG-over-TCP
│   ├── teleop_client.py     ← [PC] Client téléopération + affichage
│   └── phase3_calibrate     ← [PI] Calibration homographie parking
├── configs/
│   └── parking_calib.json   ← Paramètres calibration sauvegardés
└── README.md
```

---

## Workflow Git

Les deux dépôts sont **indépendants**. Voici comment synchroniser :

### Après modification sur le PC

```bash
# 1. Pousser les modifications C++ (si modifiés)
cd C:\...\Voiture-Autonome-Qt
git add controleur.cpp controleur.h RESUME_ARCHITECTURE.txt
git commit -m "feat: mode teleop manuelle (PID court-circuité)"
git push origin main

# 2. Pousser les scripts Python
cd C:\...\Camera_arriere
git add python_camera/video_streamer.py python_camera/teleop_client.py
git commit -m "feat: streaming JPEG-over-TCP + client teleop"
git push origin main
```

### Sur la Raspberry Pi (pour récupérer les changements)

```bash
# 1. Mettre à jour le code C++
cd ~/Voiture-Autonome-Qt
git pull origin main
# Recompiler
cd build && make -j4

# 2. Mettre à jour les scripts Python
cd ~/Camera_arriere
git pull origin main
# Pas de compilation nécessaire, Python est interprété
```

### Résumé du flux

```
PC Windows                           Raspberry Pi
   │                                      │
   │  git push (C++ et/ou Python)         │
   │─────────────────────────────────►    │
   │                        GitHub        │
   │                                      │
   │                        git pull ◄────│
   │                                      │
   │                        make (C++)    │
   │                                      │
   │  python teleop_client.py             │
   │◄─────── vidéo TCP:8885 ─────────────│  python3 video_streamer.py
   │──────── cmds  TCP:8884 ─────────────►│  ./sae_sbc
```

---

## Licence

Projet académique SAE — IUT.
