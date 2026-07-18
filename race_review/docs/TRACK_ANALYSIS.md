# Track, Lap, and Corner Analysis

This note describes the implemented GPS algorithms, the Sonoma Raceway benchmark,
and the limits of automatic start/finish inference. All distances below are measured
along the driven line, not a surveyor's centerline.

## Sonoma benchmark and map comparison

The test recording `data/GX020115.MP4` starts at approximately 38.16535,
-122.45973. Its two complete projected laps are about 3.99 km long and 147.7 s and
148.7 s in duration. The shape follows the Carousel/full-course layout rather than
the shorter Chute layout.

The venue's [official track information](https://www.sonomaraceway.com/media/)
lists the Carousel road course as 2.52 mi (4.06 km). Sonoma's
[official description of the restored original layout](https://www.sonomaraceway.com/media/news/sonoma-raceway-marks-50th-anniversary-with-return-original-nascar-circuit.html)
calls it a 12-turn, 2.52-mile course and describes the Carousel running from Turn 4
through Turns 5 and 6 before the Turn 7 hairpin. The
[official facility map](https://www.sonomaraceway.com/documents/sonoma-raceway_facility-map-2024.pdf)
provides the labeled spatial reference, including sub-turn labels such as 3A, 4A,
7A, 8A, and 9A.

The telemetry length is about 1.7% shorter than the published nominal length. That is
reasonable for a GPS-derived racing line: the published distance describes a track
configuration, while the car cuts apexes, and smoothing/projecting samples changes
arc length slightly. Shape, scale, the Carousel, and the final hairpin agree with the
official map. This is a configuration comparison, not a geodetic survey of the venue.

Before consensus filtering, this sample produced 14 regions. Several were isolated
16--32 m threshold fragments. The implemented multi-lap method produces 12 sustained
regions on the sample:

| Region | Start--end distance (m) |
| ---: | ---: |
| 1 | 492--582 |
| 2 | 618--756 |
| 3 | 900--978 |
| 4 | 1008--1062 |
| 5 | 1188--1284 |
| 6 | 1362--1500 |
| 7 | 1656--1920 |
| 8 | 2352--2508 |
| 9 | 2748--2808 |
| 10 | 2862--2928 |
| 11 | 3354--3444 |
| 12 | 3762--3876 |

Matching the official count is a useful regression, not an instruction to force every
track to a published number. A sanctioning body may label a complex as several turns,
or one functional steering event as a single turn. The detector therefore contains no
Sonoma coordinates or expected corner count, and detected regions remain editable.

## Kinematics

WGS84 positions are projected into local east/north/up meters and smoothed only within
valid, contiguous recording segments. For adjacent samples, heading and curvature are

```text
psi_i   = atan2(delta north_i, delta east_i)
kappa_i = unwrap(psi_i - psi_(i-1)) / delta s_i
```

where `kappa` is signed inverse meters. GPS-derived lateral acceleration is

```text
a_lateral = v^2 kappa
```

This relation is why curvature and lateral acceleration are used together: curvature
alone can classify slow GPS wandering as a corner, while acceleration alone cannot
distinguish road curvature from a noisy speed/heading estimate.

## Multi-lap corner consensus

Newly projected rows carry `lap_complete` and `lap_excluded`. Complete,
non-excluded laps are used; legacy artifacts without those fields must cover at least
99.5% of the longest positive-numbered lap. This prevents a long in-lap from becoming
the reference merely because it contains many samples.

For two or more laps, each lap's curvature and lateral acceleration are linearly
interpolated onto a common distance grid with spacing 6 m. At each grid position `s`,
the robust signals are the pointwise medians

```text
kappa_hat(s) = median_laps(kappa_lap(s))
a_hat(s)     = median_laps(a_lateral,lap(s)).
```

A point also needs a strict majority of laps to agree on turn direction and exceed
the relaxed evidence thresholds `|kappa| >= 0.004 1/m` and
`|a_lateral| >= 1.0 m/s^2`. With two laps, both must agree; with three, two must
agree. The final active threshold is

```text
|kappa_hat| >= 0.006 1/m  and  |a_hat| >= 1.5 m/s^2.
```

Active regions separated by at most 32 m are joined only when the curvature sign on
both sides agrees. This closes a brief dropout within one steering event without
joining opposite-direction esses. A region is retained only when it is at least 18 m
long and its integrated heading change is at least 8 degrees:

```text
Delta psi = abs(sum_i 0.5 * (kappa_i + kappa_(i+1)) * delta s_i).
```

The fastest eligible lap supplies entry/apex/exit timestamps and vehicle metrics; the
consensus signal supplies stable distance boundaries. If only one lap exists, the
older conservative single-lap thresholds remain in use because consensus is
impossible.

## Start/finish inference and crossing time

The initial timing-gate seed is a forward loop closure: two points must be within 12 m,
within 35 degrees of heading, in the same direction, and separated by at least the
configured minimum lap time. Once a seed is selected, adjacent matches are grouped as
single passages. The gate center is the component-wise median of the closest points
from all passages. Heading uses a circular mean, which avoids the discontinuity at
plus/minus pi:

```text
psi_gate = arg(mean_j(exp(i * psi_j))).
```

For center `c`, the line normal is `n = (-sin(psi_gate), cos(psi_gate))`; endpoints
are `c - 18 n` and `c + 18 n`. On the Sonoma sample, refinement places the center near
ENU `(592.84, -597.80)` or WGS84 `(38.15996, -122.45297)`. The resulting complete laps
start near 45.704 s and 193.391 s.

For endpoint `a`, line vector `l = b - a`, and car position `p(t)`, the signed side is

```text
q(t) = l_east * (p_north(t) - a_north)
     - l_north * (p_east(t) - a_east).
```

A directed sign change is a candidate crossing. The intersection must lie within the
finite gate, not merely its infinite line. If consecutive signed values are `q0` and
`q1`, the crossing time is linearly interpolated with
`alpha = -q0 / (q1 - q0)` and `t_cross = t0 + alpha * (t1 - t0)`. Segment continuity,
direction, and minimum-lap-time checks reject GPS gaps and nearby recrossings.

### What GPS alone cannot determine

A bare closed route is invariant under a cyclic shift of lap distance. Every suitable
straight cross-section repeats once per lap, so loop closure can find a stable timing
gate but cannot prove which stripe an organizer calls the official start/finish line.
The current manual endpoint override is therefore the authoritative correction.

More reliable future options, in priority order, are:

1. map-match the route to a versioned circuit catalog containing surveyed timing-line
   endpoints and configuration metadata;
2. let the user click a route location, then snap the gate perpendicular to the local
   consensus heading;
3. fuse pit-lane topology or video detection of the painted line/gantry with GPS time;
4. expose loop-closure dispersion, heading spread, and lap-period variation as a
   confidence score instead of implying the inferred location is official.

These approaches should supplement the generic loop-closure fallback rather than add
venue-specific coordinates to the detector.
