#!/usr/bin/env python3
"""
video_streamer.py — Serveur de streaming vidéo JPEG (TCP + UDP).

Tourne sur la Raspberry Pi. Capture les frames via Picamera2,
les encode en JPEG et les envoie :
  - En TCP (port 8885) vers teleop_client.py
  - En UDP (port 4444) vers l'interface CarPlay Qt (optionnel)

Protocole TCP : [4 bytes uint32 big-endian = taille JPEG] [N bytes = données JPEG]
Protocole UDP : [N bytes = données JPEG] (paquet unique, pas de header)

Usage (sur la Pi via SSH) :
    python3 video_streamer.py
    python3 video_streamer.py --rotate 180
    python3 video_streamer.py --rotate 180 --udp-ip 192.168.1.196
"""

from __future__ import annotations

import argparse
import signal
import socket
import struct
import sys
import time

import cv2
import numpy as np
from picamera2 import Picamera2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JPEG-over-TCP video streamer for Raspberry Pi.")
    parser.add_argument("--port", type=int, default=8885, help="TCP port to listen on (default: 8885)")
    parser.add_argument("--width", type=int, default=640, help="Output width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Output height (default: 480)")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality 1-100 (default: 70)")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=180,
                        help="Rotation in degrees (default: 180)")
    parser.add_argument("--flip", choices=["none", "h", "v", "hv"], default="none",
                        help="Flip mode (default: none)")
    parser.add_argument("--fps-cap", type=int, default=30, help="Max FPS (default: 30)")
    parser.add_argument("--swap-rb", action="store_true", default=False,
                        help="Force swap Red/Blue channels (use if colors are wrong)")
    parser.add_argument("--fov", choices=["normal", "wide"], default="wide",
                        help="FOV mode: 'wide' uses full sensor for max angle (default: wide)")
    # UDP dual output (pour CarPlay Qt)
    parser.add_argument("--udp-ip", type=str, default=None,
                        help="IP cible pour l'envoi UDP (ex: 192.168.1.196). Sans cet arg, UDP désactivé.")
    parser.add_argument("--udp-port", type=int, default=4444,
                        help="Port UDP cible (default: 4444)")
    return parser.parse_args()


def apply_orientation(frame: np.ndarray, rotate: int, flip: str) -> np.ndarray:
    """Apply rotation and flip to a frame."""
    if rotate == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotate == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotate == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if flip == "h":
        frame = cv2.flip(frame, 1)
    elif flip == "v":
        frame = cv2.flip(frame, 0)
    elif flip == "hv":
        frame = cv2.flip(frame, -1)
    return frame


def try_configure(picam2: Picamera2, width: int, height: int, fov_mode: str) -> None:
    """Configure the camera. In 'wide' mode, use full sensor for widest FOV."""
    sensor_res = picam2.sensor_resolution
    print(f"[STREAMER] Sensor native resolution: {sensor_res[0]}x{sensor_res[1]}")

    # RGB888 first — gives true RGB, easy to convert to BGR for OpenCV
    for fmt in ["RGB888", "XRGB8888", "RGBX"]:
        try:
            if fov_mode == "wide":
                # Use full sensor → widest FOV, downscaled to output size
                cfg = picam2.create_preview_configuration(
                    main={"format": fmt, "size": (width, height)},
                    raw={"size": sensor_res},
                )
            else:
                cfg = picam2.create_preview_configuration(
                    main={"format": fmt, "size": (width, height)}
                )
            picam2.configure(cfg)
            print(f"[STREAMER] Configured: {fmt} @ {width}x{height} (FOV: {fov_mode})")
            return
        except Exception as exc:
            print(f"[STREAMER] Format {fmt} unavailable: {exc}")
    raise RuntimeError("No compatible camera format found")


def convert_to_bgr(frame: np.ndarray, swap_rb: bool = False) -> np.ndarray:
    """Auto-convert captured frame to BGR for JPEG encoding."""
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    channels = frame.shape[2]
    if channels == 4:
        # XRGB8888 from Picamera2 is actually BGRA in memory
        result = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    elif channels == 3:
        # Direct copy — Picamera2 RGB888 may already be BGR in memory
        result = frame.copy()
    else:
        result = frame
    # If --swap-rb is set, force a channel swap
    if swap_rb:
        result = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
    return result


def main() -> int:
    args = parse_args()

    # --- Signal handling ---
    stop = False
    def _on_signal(_sig, _frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # --- Camera init ---
    picam2 = Picamera2()
    try_configure(picam2, args.width, args.height, args.fov)
    picam2.start()

    # In wide mode, ensure full sensor is used (no digital crop)
    if args.fov == "wide":
        sensor_res = picam2.sensor_resolution
        picam2.set_controls({"ScalerCrop": (0, 0, sensor_res[0], sensor_res[1])})
        print(f"[STREAMER] ScalerCrop set to full sensor: {sensor_res}")

    time.sleep(1.0)  # warmup
    # Flush initial frames
    for _ in range(5):
        picam2.capture_array()
    print("[STREAMER] Camera ready.")

    # --- TCP server ---
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.settimeout(1.0)
    server.bind(("0.0.0.0", args.port))
    server.listen(1)
    print(f"[STREAMER] Listening TCP on 0.0.0.0:{args.port}")

    # --- UDP socket (optionnel, pour CarPlay) ---
    udp_sock = None
    if args.udp_ip:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"[STREAMER] UDP activé → {args.udp_ip}:{args.udp_port}")
    else:
        print("[STREAMER] UDP désactivé (utilise --udp-ip pour activer)")

    min_frame_time = 1.0 / args.fps_cap if args.fps_cap > 0 else 0.0
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, args.quality]

    try:
        client = None
        frame_count = 0
        t_start = time.perf_counter()

        while not stop:
            t0 = time.perf_counter()

            # --- Accepter un client TCP (non bloquant) ---
            if client is None:
                try:
                    client, addr = server.accept()
                    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    print(f"[STREAMER] Client TCP connecté : {addr}")
                except socket.timeout:
                    pass  # Pas de client, on continue quand même

            # --- Capturer un frame ---
            raw = picam2.capture_array()
            bgr = convert_to_bgr(raw, swap_rb=args.swap_rb)
            bgr = apply_orientation(bgr, args.rotate, args.flip)

            if frame_count == 0:
                print(f"[DIAG] Raw frame: shape={raw.shape}, dtype={raw.dtype}")
                print(f"[DIAG] swap_rb = {args.swap_rb}")

            ok, jpeg = cv2.imencode(".jpg", bgr, encode_params)
            if not ok:
                continue

            data = jpeg.tobytes()

            # --- Envoi TCP (si un client est connecté) ---
            if client is not None:
                header = struct.pack(">I", len(data))
                try:
                    client.sendall(header + data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    print("[STREAMER] Client TCP déconnecté.")
                    client.close()
                    client = None

            # --- Envoi UDP (toujours, même sans client TCP) ---
            if udp_sock and len(data) < 65000:
                try:
                    udp_sock.sendto(data, (args.udp_ip, args.udp_port))
                except OSError:
                    pass

            frame_count += 1
            if frame_count % 100 == 0:
                elapsed = time.perf_counter() - t_start
                fps = frame_count / elapsed if elapsed > 0 else 0
                tcp_status = "TCP:✓" if client else "TCP:—"
                udp_status = f" UDP→{args.udp_ip}" if udp_sock else ""
                print(f"[STREAMER] {fps:.1f} FPS, ~{len(data)//1024}KB [{tcp_status}{udp_status}]")

            # FPS cap
            elapsed = time.perf_counter() - t0
            if elapsed < min_frame_time:
                time.sleep(min_frame_time - elapsed)

    finally:
        picam2.stop()
        server.close()
        print("[STREAMER] Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
