# Offline Sound Localization Study Pack

This directory is meant to be usable without internet for a long flight.

## What is here

- `pdfs/`: papers on TDOA, localization, DOA, and modern SSL variants
- `docs/`: official SciPy and NumPy reference pages saved as local HTML
- `code/pyroomacoustics-master/`: offline code snapshot of a major reference implementation

## Suggested reading order

1. `pdfs/01_gannot_dvorkind_2006_spatial_temporal_localizers.pdf`
   - Why first: it gives a strong systems view of TDOA-based localization and explains why range is harder than azimuth/elevation.
   - Focus on: TDOA geometry, recursive Gauss updates, EKF/UKF tracking, error behavior.
2. `pdfs/02_grundin_glass_2019_svd_phat.pdf`
   - Why next: it is a practical bridge from GCC/SRP-PHAT to efficient multi-source localization.
   - Focus on: PHAT weighting, spatial scans, dimensionality reduction ideas.
3. `pdfs/03_scheibler_bezzam_dokmanic_2017_pyroomacoustics.pdf`
   - Why next: it connects theory to a Python implementation ecosystem and room acoustics simulation.
   - Focus on: image-source model, DOA algorithms, simulation workflow.
4. `pdfs/04_diaz_guerra_2022_icosahedral_cnn_doa.pdf`
   - Why next: it shows a modern learning-based DOA pipeline built on SRP-style power maps.
   - Focus on: representation choices and what classical front ends survive in learned systems.
5. `pdfs/05_berghi_jackson_2023_audio_inputs_active_speaker_localization.pdf`
   - Why next: it compares useful spatial features such as GCC-PHAT and spectrogram-derived representations.
   - Focus on: feature engineering tradeoffs and array aperture effects.
6. `pdfs/06_hu_song_he_yu_2023_ssl_resnet_channel_attention.pdf`
   - Why last: it is a modern deep-learning reference if you want to compare classical methods against learned models.

## Methods map

- `TDOA / multilateration`
  - Start from pairwise arrival-time differences.
  - Each mic pair defines a hyperbolic constraint in 3D.
  - Solve for the source that best fits all pairwise delays.
  - Useful local docs: `docs/scipy_signal_correlate.html`, `docs/scipy_signal_correlation_lags.html`, `docs/scipy_optimize_least_squares.html`, `docs/numpy_linalg_lstsq.html`

- `GCC-PHAT`
  - Estimate delay in the frequency domain with phase emphasis to reduce coloration/reverb sensitivity.
  - Good first practical algorithm for your simulated cabin data.
  - Useful local docs: `docs/scipy_signal_correlate.html`, `docs/scipy_signal_csd.html`, `docs/numpy_fft_rfft.html`, `docs/numpy_fft_rfftfreq.html`

- `SRP-PHAT / grid search`
  - Scan candidate 3D points and sum alignment scores across microphone pairs.
  - Easier to get working than direct closed-form triangulation in reverberant settings.
  - Useful local docs: `docs/scipy_signal_stft.html`, `docs/scipy_signal_istft.html`, `docs/scipy_optimize_least_squares.html`

- `DOA / beamforming / subspace methods`
  - Estimate direction first, then possibly combine multiple directional constraints.
  - More natural with compact arrays; your current cabin-wide layout is closer to near-field localization than pure far-field DOA.
  - Useful local code: `code/pyroomacoustics-main/`

- `Tracking`
  - Once you have framewise position hypotheses, smooth them over time with EKF/UKF or simpler temporal filters.
  - Read this after the first paper.

## Equations to pay attention to

- Cross-correlation and lag selection
- Generalized cross-correlation with PHAT normalization
- Hyperbolic TDOA constraints
- Least-squares residual between measured and predicted delays
- SRP objective over a 3D spatial grid
- If you reach tracking: state update and measurement update equations for EKF/UKF

## Local SciPy / NumPy references

- `docs/scipy_signal_overview.html`
- `docs/scipy_signal_correlate.html`
- `docs/scipy_signal_correlation_lags.html`
- `docs/scipy_signal_stft.html`
- `docs/scipy_signal_istft.html`
- `docs/scipy_signal_welch.html`
- `docs/scipy_signal_csd.html`
- `docs/scipy_signal_spectrogram.html`
- `docs/scipy_signal_butter.html`
- `docs/scipy_signal_sosfilt.html`
- `docs/scipy_signal_hilbert.html`
- `docs/scipy_optimize_least_squares.html`
- `docs/numpy_fft_rfft.html`
- `docs/numpy_fft_rfftfreq.html`
- `docs/numpy_linalg_lstsq.html`
- `docs/numpy_linalg_norm.html`

## Practical code to inspect offline

- `../cabin_noise_simulation.py`
- `../noise_estimation.ipynb`
- `code/pyroomacoustics-master/pyroomacoustics/doa/`
- `code/pyroomacoustics-master/examples/`

## Good 10-hour flight plan

1. Read paper 1 and sketch the TDOA geometry by hand.
2. Read paper 2 and write down how PHAT changes the correlation logic.
3. Open `../noise_estimation.ipynb` and compare its current approach against those papers.
4. Inspect `pyroomacoustics/doa/` to see how mature libraries organize steering vectors, grids, and scoring.
5. Write your own minimal GCC-PHAT and compare it against plain correlation on your simulated data.
6. If time remains, prototype a coarse 3D SRP-PHAT heatmap over the cabin volume.

## Notes

- The original Knapp-Carter GCC paper is a foundational citation, but I did not place a local PDF here because the openly accessible source quality is inconsistent. The Gannot and SVD-PHAT papers both point back to it and are enough to get you moving offline.
- The deep papers are optional. If the goal is significant progress on this project during the flight, prioritize TDOA, GCC-PHAT, SRP-PHAT, and the pyroomacoustics codebase.
