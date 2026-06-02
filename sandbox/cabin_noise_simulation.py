#!/usr/bin/env python3
"""
Basic in-cabin noise simulation for microphone-array experiments.

What it does:
1) Synthesizes several independent vehicle noise sources in different locations.
2) Propagates each source to each microphone with a simple model:
   distance delay + distance attenuation + mild distance-dependent low-pass filtering.
3) Plots intuitive diagnostics for algorithm prototyping:
   - 3D cabin geometry plus 2D projections
   - source waveforms
   - microphone waveforms
   - microphone spectrograms
   - source-to-microphone RMS heatmap
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

# Keep matplotlib/font caches inside the sandbox so the script runs in restricted envs.
_SANDBOX_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(_SANDBOX_DIR / ".mplconfig"))
os.environ.setdefault("XDG_CACHE_HOME", str(_SANDBOX_DIR / ".cache"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

import matplotlib.pyplot as plt
import numpy as np
from scipy import signal
from scipy.io import wavfile


@dataclass(frozen=True)
class NoiseSource:
    name: str
    kind: str
    position: np.ndarray  # (x, y, z) meters
    level: float


@dataclass(frozen=True)
class Microphone:
    name: str
    position: np.ndarray  # (x, y, z) meters


@dataclass(frozen=True)
class ReflectionSurface:
    name: str
    axis: int
    coordinate: float
    reflection_gain: float


@dataclass(frozen=True)
class PropagationConfig:
    sound_speed: float = 343.0
    air_absorb: float = 0.11
    include_reflections: bool = True
    reflection_hf_damping: float = 0.72


def build_scene() -> tuple[list[NoiseSource], list[Microphone], tuple[float, float, float]]:
    # Cabin box in meters. x: front->rear, y: driver->passenger, z: floor->roof.
    cabin_size = (2.6, 1.5, 1.15)  # (length, width, height)

    sources = [
        NoiseSource("Engine", "engine", np.array([-0.60, 0.75, 0.35]), 1.0),
        NoiseSource("Road", "road", np.array([0.20, 0.20, -0.18]), 0.7),
        NoiseSource("AC Vent", "ac", np.array([0.35, 1.20, 0.95]), 0.45),
        NoiseSource("Transmission", "trans", np.array([1.20, 0.75, 0.18]), 0.55),
    ]

    mics = [
        Microphone("Mic 1 (Drv)", np.array([0.70, 0.35, 0.78])),
        Microphone("Mic 2 (Pas)", np.array([0.70, 1.15, 0.78])),
        Microphone("Mic 3 (RL)", np.array([1.90, 0.35, 0.74])),
        Microphone("Mic 4 (RR)", np.array([1.90, 1.15, 0.74])),
    ]
    return sources, mics, cabin_size


def build_reflection_surfaces(cabin_size: tuple[float, float, float]) -> list[ReflectionSurface]:
    length, width, _ = cabin_size
    return [
        ReflectionSurface("Floor", axis=2, coordinate=0.0, reflection_gain=0.55),
        ReflectionSurface("Driver Window", axis=1, coordinate=0.0, reflection_gain=0.48),
        ReflectionSurface("Passenger Window", axis=1, coordinate=width, reflection_gain=0.48),
        ReflectionSurface("Windshield", axis=0, coordinate=0.0, reflection_gain=0.42),
    ]


def _pinkish_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    # Simple 1/sqrt(f) spectral shaping for road-like broadband noise.
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / np.sqrt(freqs[1:])
    colored = np.fft.irfft(spectrum * scale, n=n)
    return colored / (np.std(colored) + 1e-12)


def synthesize_source(source: NoiseSource, t: np.ndarray, fs: int, rng: np.random.Generator) -> np.ndarray:
    n = len(t)

    if source.kind == "engine":
        # Fundamental order wobble to mimic RPM drift while cruising.
        f0 = 120.0 + 8.0 * np.sin(2 * np.pi * 0.15 * t)
        phase = 2 * np.pi * np.cumsum(f0) / fs
        x = (
            np.sin(phase)
            + 0.45 * np.sin(2 * phase + 0.4)
            + 0.25 * np.sin(3 * phase + 1.1)
        )
        x += 0.08 * rng.standard_normal(n)
    elif source.kind == "road":
        x = _pinkish_noise(n, rng)
        b, a = signal.butter(4, 700 / (fs / 2), btype="low")
        x = signal.lfilter(b, a, x)
        x += 0.22 * np.sin(2 * np.pi * 35 * t)  # low-frequency rumble component
    elif source.kind == "ac":
        x = rng.standard_normal(n)
        b, a = signal.butter(3, [300 / (fs / 2), 2500 / (fs / 2)], btype="band")
        x = signal.lfilter(b, a, x)
        x += 0.35 * np.sin(2 * np.pi * 420 * t)
    elif source.kind == "trans":
        tone = np.sin(2 * np.pi * 1600 * t)
        sidebands = 0.30 * np.sin(2 * np.pi * (1600 + 90 * np.sin(2 * np.pi * 0.8 * t)) * t)
        x = tone + sidebands + 0.05 * rng.standard_normal(n)
    else:
        raise ValueError(f"Unknown source kind: {source.kind}")

    x = source.level * x
    return x / (np.max(np.abs(x)) + 1e-12)


def fractional_delay(x: np.ndarray, delay_samples: float) -> np.ndarray:
    n = np.arange(len(x))
    return np.interp(n - delay_samples, n, x, left=0.0, right=0.0)


def mirror_point(point: np.ndarray, surface: ReflectionSurface) -> np.ndarray:
    mirrored = point.copy()
    mirrored[surface.axis] = 2.0 * surface.coordinate - mirrored[surface.axis]
    return mirrored


def propagate_along_path(
    src_sig: np.ndarray,
    path_length: float,
    fs: int,
    config: PropagationConfig,
    path_gain: float = 1.0,
    extra_hf_rolloff: float = 1.0,
) -> tuple[np.ndarray, float]:
    delay_samples = fs * path_length / config.sound_speed
    delayed = fractional_delay(src_sig, delay_samples)

    # Geometric spreading + mild absorption.
    gain = path_gain * np.exp(-config.air_absorb * path_length) / (0.35 + path_length)

    # Crude path coloration: longer paths and reflections lose high-frequency detail.
    cutoff_hz = np.clip(extra_hf_rolloff * 9000.0 / (1.0 + 1.3 * path_length), 450.0, 8000.0)
    b, a = signal.butter(2, cutoff_hz / (fs / 2), btype="low")
    colored = signal.lfilter(b, a, delayed)
    return gain * colored, path_length


def propagate_to_mic(
    src_sig: np.ndarray,
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    fs: int,
    config: PropagationConfig,
    reflection_surfaces: list[ReflectionSurface],
) -> tuple[np.ndarray, dict[str, float]]:
    direct_path, direct_dist = propagate_along_path(
        src_sig,
        path_length=float(np.linalg.norm(src_pos - mic_pos)),
        fs=fs,
        config=config,
    )
    propagated = direct_path
    path_summary = {"direct_distance_m": direct_dist, "reflection_count": 0.0}

    if not config.include_reflections:
        return propagated, path_summary

    for surface in reflection_surfaces:
        image_source = mirror_point(src_pos, surface)
        reflected_dist = float(np.linalg.norm(image_source - mic_pos))
        reflected_sig, _ = propagate_along_path(
            src_sig,
            path_length=reflected_dist,
            fs=fs,
            config=config,
            path_gain=surface.reflection_gain,
            extra_hf_rolloff=config.reflection_hf_damping,
        )
        propagated += reflected_sig
        path_summary["reflection_count"] += 1.0

    return propagated, path_summary


def simulate(
    duration_s: float = 6.0,
    fs: int = 16000,
    seed: int = 12,
    include_reflections: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[NoiseSource], list[Microphone], np.ndarray]:
    sources, mics, cabin_size = build_scene()
    reflection_surfaces = build_reflection_surfaces(cabin_size)
    config = PropagationConfig(include_reflections=include_reflections)
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration_s * fs)) / fs

    src_signals = np.stack([synthesize_source(src, t, fs, rng) for src in sources], axis=0)
    contrib = np.zeros((len(mics), len(sources), len(t)), dtype=float)

    for m_idx, mic in enumerate(mics):
        for s_idx, src in enumerate(sources):
            y, _ = propagate_to_mic(
                src_signals[s_idx],
                src.position,
                mic.position,
                fs,
                config,
                reflection_surfaces,
            )
            contrib[m_idx, s_idx] = y

    mic_noise = 0.01 * rng.standard_normal((len(mics), len(t)))
    mic_signals = contrib.sum(axis=1) + mic_noise

    # Normalize for stable plotting/listening.
    mic_signals /= np.max(np.abs(mic_signals)) + 1e-12
    src_signals /= np.max(np.abs(src_signals)) + 1e-12

    return src_signals, mic_signals, sources, mics, contrib / (np.max(np.abs(mic_signals)) + 1e-12)


def plot_scene(
    sources: list[NoiseSource],
    mics: list[Microphone],
    cabin_size: tuple[float, float, float],
    output_dir: Path,
) -> None:
    fig = plt.figure(figsize=(13, 5.2))
    ax3d = fig.add_subplot(1, 3, 1, projection="3d")
    ax_xy = fig.add_subplot(1, 3, 2)
    ax_xz = fig.add_subplot(1, 3, 3)
    length, width, height = cabin_size

    src_color = "#d95f02"
    mic_color = "#1b9e77"

    cuboid = np.array(
        [
            [0.0, 0.0, 0.0],
            [length, 0.0, 0.0],
            [length, width, 0.0],
            [0.0, width, 0.0],
            [0.0, 0.0, height],
            [length, 0.0, height],
            [length, width, height],
            [0.0, width, height],
        ]
    )
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    for i0, i1 in edges:
        seg = cuboid[[i0, i1]]
        ax3d.plot(seg[:, 0], seg[:, 1], seg[:, 2], color="0.65", linewidth=1.2)

    for src in sources:
        x, y, z = src.position
        ax3d.scatter(x, y, z, marker="x", s=80, linewidths=2, color=src_color)
        ax3d.text(x + 0.03, y + 0.02, z + 0.02, src.name, fontsize=8)
        ax_xy.scatter(x, y, marker="x", s=90, linewidths=2, color=src_color)
        ax_xy.text(x + 0.03, y + 0.03, src.name, fontsize=8)
        ax_xz.scatter(x, z, marker="x", s=90, linewidths=2, color=src_color)
        ax_xz.text(x + 0.03, z + 0.02, src.name, fontsize=8)

    for mic in mics:
        x, y, z = mic.position
        ax3d.scatter(x, y, z, marker="o", s=45, color=mic_color)
        ax3d.text(x + 0.03, y - 0.05, z + 0.02, mic.name, fontsize=8)
        ax_xy.scatter(x, y, marker="o", s=45, color=mic_color)
        ax_xy.text(x + 0.03, y - 0.07, mic.name, fontsize=8)
        ax_xz.scatter(x, z, marker="o", s=45, color=mic_color)
        ax_xz.text(x + 0.03, z - 0.04, mic.name, fontsize=8)

    ax3d.set_title("3D Cabin Layout")
    ax3d.set_xlabel("x (m)")
    ax3d.set_ylabel("y (m)")
    ax3d.set_zlabel("z (m)")
    ax3d.set_xlim(-0.9, length + 0.1)
    ax3d.set_ylim(-0.1, width + 0.2)
    ax3d.set_zlim(-0.25, height + 0.1)
    ax3d.view_init(elev=20, azim=-62)

    ax_xy.set_title("Top-Down Projection (x-y)")
    ax_xy.set_xlabel("x (m), front to rear")
    ax_xy.set_ylabel("y (m), driver to passenger")
    ax_xy.set_xlim(-0.9, length + 0.1)
    ax_xy.set_ylim(-0.1, width + 0.2)
    ax_xy.set_aspect("equal")
    ax_xy.add_patch(plt.Rectangle((0, 0), length, width, fill=False, linewidth=2, color="0.4"))
    ax_xy.grid(alpha=0.25)

    ax_xz.set_title("Side Projection (x-z)")
    ax_xz.set_xlabel("x (m), front to rear")
    ax_xz.set_ylabel("z (m), floor to roof")
    ax_xz.set_xlim(-0.9, length + 0.1)
    ax_xz.set_ylim(-0.25, height + 0.1)
    ax_xz.add_patch(plt.Rectangle((0, 0), length, height, fill=False, linewidth=2, color="0.4"))
    ax_xz.grid(alpha=0.25)

    fig.suptitle("Cabin Source and Microphone Geometry")
    fig.tight_layout()
    fig.savefig(output_dir / "01_geometry.png", dpi=160)
    plt.close(fig)


def plot_time_and_spectral(
    src_signals: np.ndarray,
    mic_signals: np.ndarray,
    contrib: np.ndarray,
    sources: list[NoiseSource],
    mics: list[Microphone],
    fs: int,
    output_dir: Path,
) -> None:
    t = np.arange(src_signals.shape[1]) / fs
    t_short = t <= 0.12

    # Source waveforms.
    fig, axs = plt.subplots(len(sources), 1, figsize=(10, 7), sharex=True)
    for i, src in enumerate(sources):
        axs[i].plot(t[t_short], src_signals[i, t_short], linewidth=1.0)
        axs[i].set_ylabel(src.name)
        axs[i].grid(alpha=0.2)
    axs[-1].set_xlabel("Time (s)")
    fig.suptitle("Source Waveforms (First 120 ms)")
    fig.tight_layout()
    fig.savefig(output_dir / "02_source_waveforms.png", dpi=160)
    plt.close(fig)

    # Mic waveforms.
    fig, axs = plt.subplots(len(mics), 1, figsize=(10, 7), sharex=True)
    for i, mic in enumerate(mics):
        axs[i].plot(t[t_short], mic_signals[i, t_short], linewidth=1.0)
        axs[i].set_ylabel(mic.name)
        axs[i].grid(alpha=0.2)
    axs[-1].set_xlabel("Time (s)")
    fig.suptitle("Microphone Signals After Propagation (First 120 ms)")
    fig.tight_layout()
    fig.savefig(output_dir / "03_mic_waveforms.png", dpi=160)
    plt.close(fig)

    # Spectrograms.
    fig, axs = plt.subplots(2, 2, figsize=(12, 7), sharex=True, sharey=True)
    axs = axs.ravel()
    for i, mic in enumerate(mics):
        f, tt, z = signal.stft(mic_signals[i], fs=fs, nperseg=512, noverlap=384)
        db = 20 * np.log10(np.abs(z) + 1e-8)
        im = axs[i].pcolormesh(tt, f, db, shading="gouraud", cmap="magma")
        axs[i].set_title(mic.name)
        axs[i].set_ylim(0, 3000)
        axs[i].set_xlabel("Time (s)")
        axs[i].set_ylabel("Frequency (Hz)")
    cbar = fig.colorbar(im, ax=axs.tolist(), fraction=0.02, pad=0.02)
    cbar.set_label("Magnitude (dB)")
    fig.suptitle("Microphone Spectrograms")
    fig.subplots_adjust(left=0.07, right=0.93, bottom=0.08, top=0.90, wspace=0.22, hspace=0.25)
    fig.savefig(output_dir / "04_mic_spectrograms.png", dpi=160)
    plt.close(fig)

    # Source-to-mic RMS contribution matrix.
    rms = np.sqrt(np.mean(contrib**2, axis=2))
    fig, ax = plt.subplots(figsize=(8, 4.8))
    im = ax.imshow(rms, aspect="auto", cmap="viridis")
    ax.set_xticks(np.arange(len(sources)))
    ax.set_xticklabels([s.name for s in sources], rotation=25, ha="right")
    ax.set_yticks(np.arange(len(mics)))
    ax.set_yticklabels([m.name for m in mics])
    ax.set_title("RMS Contribution of Each Source at Each Microphone")
    for i in range(rms.shape[0]):
        for j in range(rms.shape[1]):
            ax.text(j, i, f"{rms[i, j]:.3f}", ha="center", va="center", color="w", fontsize=8)
    fig.colorbar(im, ax=ax, label="RMS amplitude")
    fig.tight_layout()
    fig.savefig(output_dir / "05_source_to_mic_rms.png", dpi=160)
    plt.close(fig)

    # PSD overlay to compare mic spectra quickly.
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for i, mic in enumerate(mics):
        f, pxx = signal.welch(mic_signals[i], fs=fs, nperseg=2048)
        ax.semilogy(f, pxx + 1e-12, label=mic.name)
    ax.set_xlim(0, 3500)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Power Spectral Density")
    ax.set_title("Microphone PSD Comparison")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_dir / "06_mic_psd_overlay.png", dpi=160)
    plt.close(fig)


def save_outputs(
    src_signals: np.ndarray,
    mic_signals: np.ndarray,
    sources: list[NoiseSource],
    mics: list[Microphone],
    cabin_size: tuple[float, float, float],
    include_reflections: bool,
    fs: int,
    output_dir: Path,
) -> None:
    np.savez(
        output_dir / "simulated_cabin_audio.npz",
        fs=fs,
        cabin_size=np.array(cabin_size, dtype=np.float32),
        include_reflections=np.array(include_reflections),
        source_names=np.array([s.name for s in sources], dtype=object),
        source_positions=np.stack([s.position for s in sources]).astype(np.float32),
        mic_names=np.array([m.name for m in mics], dtype=object),
        mic_positions=np.stack([m.position for m in mics]).astype(np.float32),
        source_signals=src_signals.astype(np.float32),
        mic_signals=mic_signals.astype(np.float32),
    )

    # Export microphone channels as WAV for listening/debugging.
    wav = (0.95 * mic_signals.T / (np.max(np.abs(mic_signals)) + 1e-12)).astype(np.float32)
    wavfile.write(output_dir / "mic_signals.wav", fs, wav)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate in-cabin multi-microphone noise recordings.")
    parser.add_argument("--duration", type=float, default=6.0, help="Signal duration in seconds (default: 6.0)")
    parser.add_argument("--fs", type=int, default=16000, help="Sample rate in Hz (default: 16000)")
    parser.add_argument("--seed", type=int, default=12, help="Random seed for reproducibility")
    parser.add_argument(
        "--disable-reflections",
        action="store_true",
        help="Disable first-order cabin reflections and keep only direct-path propagation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "sim_output",
        help="Directory for plots and data output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    src_signals, mic_signals, sources, mics, contrib = simulate(
        duration_s=args.duration,
        fs=args.fs,
        seed=args.seed,
        include_reflections=not args.disable_reflections,
    )
    _, _, cabin_size = build_scene()

    plot_scene(sources, mics, cabin_size, output_dir)
    plot_time_and_spectral(src_signals, mic_signals, contrib, sources, mics, args.fs, output_dir)
    save_outputs(
        src_signals,
        mic_signals,
        sources,
        mics,
        cabin_size,
        not args.disable_reflections,
        args.fs,
        output_dir,
    )

    print(f"Simulation complete. Outputs written to: {output_dir}")
    print("Generated files:")
    for p in sorted(output_dir.glob("*")):
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
