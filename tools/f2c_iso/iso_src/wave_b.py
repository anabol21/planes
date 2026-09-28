"""Wave B packer for the isolated Fields2Cover contour.

Pure Python: no fields2cover, shapely, or ``planes.*`` imports. The
isolated worker and unit tests both load this file directly.

Team heuristics (not customer claims):

- ``OPEN-011`` — repeated sorties and recharge gaps.
- ``OPEN-013`` — horizontal space–time separation, not certified traffic.
- ``OPEN-015`` — greedy pad choice / delay; not a global optimum.
- ``OPEN-008`` — endurance is ``flight_time_s`` with reserve, not Wh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable


class CoverageInfeasible(Exception):
    """Coverage leftover under the current endurance / recharge flag."""

    def __init__(
        self,
        reason: str,
        uncovered: int = 0,
        limitations: tuple[str, ...] = (),
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.uncovered = int(uncovered)
        self.limitations = tuple(limitations)


@dataclass(frozen=True)
class WaveBFlags:
    """Scenario knobs for the isolated Wave B packer."""

    allow_recharge: bool = True
    allow_foreign_landing: bool = True
    allow_foreign_takeoff: bool = False
    min_separation_m: float = 50.0
    time_window_s: float = 0.0
    recharge_time_s_override: float | None = None


@dataclass(frozen=True)
class Pad:
    id: str
    xy: tuple[float, float]


@dataclass(frozen=True)
class Swath:
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float

    def flipped(self) -> "Swath":
        return Swath(self.end, self.start, self.length_m)


@dataclass
class PackedSortie:
    uav_id: str
    takeoff_pad_id: str
    landing_pad_id: str
    takeoff_xy: tuple[float, float]
    landing_xy: tuple[float, float]
    swaths: list[Swath]
    flight_time_s: float
    start_time_s: float = 0.0
    recharge_before_s: float = 0.0


@dataclass
class PackBoardResult:
    sorties: list[PackedSortie]
    uncovered: list[Swath]
    limitations: list[str] = field(default_factory=list)


def read_wave_b_flags(scenario: dict[str, Any] | None) -> WaveBFlags:
    """Read Wave B flags from a v0 scenario object.

    Accepted keys (first hit wins):

    - recharge allow: ``power.allow_recharge``, ``allow_recharge``
    - recharge seconds override: ``power.recharge_time_s``, ``recharge_time_s``
    - foreign landing: ``allow_foreign_landing``, ``landing.allow_foreign``
    - foreign first takeoff: ``allow_foreign_takeoff``, ``takeoff.allow_foreign``
    - separation: ``separation.min_horizontal_m``, ``min_separation_m``
    - time window: ``separation.time_window_s``
    """
    src = scenario if isinstance(scenario, dict) else {}
    power = src.get("power") if isinstance(src.get("power"), dict) else {}
    landing = src.get("landing") if isinstance(src.get("landing"), dict) else {}
    takeoff = src.get("takeoff") if isinstance(src.get("takeoff"), dict) else {}
    sep = src.get("separation") if isinstance(src.get("separation"), dict) else {}
    override = _optional_float(power.get("recharge_time_s"))
    if override is None:
        override = _optional_float(src.get("recharge_time_s"))
    sep_m = _optional_float(sep.get("min_horizontal_m"))
    if sep_m is None:
        sep_m = _optional_float(src.get("min_separation_m"))
    if sep_m is None:
        sep_m = 50.0
    window = _optional_float(sep.get("time_window_s"))
    if window is None:
        window = 0.0
    return WaveBFlags(
        allow_recharge=_as_bool(
            power.get("allow_recharge", src.get("allow_recharge")),
            True,
        ),
        allow_foreign_landing=_as_bool(
            src.get("allow_foreign_landing", landing.get("allow_foreign")),
            True,
        ),
        allow_foreign_takeoff=_as_bool(
            src.get("allow_foreign_takeoff", takeoff.get("allow_foreign")),
            False,
        ),
        min_separation_m=float(sep_m),
        time_window_s=float(window),
        recharge_time_s_override=override,
    )


def read_recharge_time_s(
    model: dict[str, Any] | None,
    card: dict[str, Any] | None,
    flags: WaveBFlags,
) -> float:
    """Catalog / board recharge seconds. Override from the scenario wins."""
    if flags.recharge_time_s_override is not None:
        return max(0.0, float(flags.recharge_time_s_override))
    for record in (card, model):
        if not isinstance(record, dict):
            continue
        value = _optional_float(record.get("recharge_time_s"))
        if value is not None:
            return max(0.0, value)
    return 0.0


def choose_pad(
    point: tuple[float, float],
    pads: list[Pad],
    home_id: str,
    *,
    allowed: bool,
) -> Pad:
    """Closest pad to ``point``. Home wins a distance tie. Home if not allowed."""
    home = _home(pads, home_id)
    if not allowed or not pads:
        return home
    best = home
    best_key = (_hypot(point, home.xy), 0, home.id)
    for pad in pads:
        key = (_hypot(point, pad.xy), 0 if pad.id == home_id else 1, pad.id)
        if key < best_key:
            best = pad
            best_key = key
    return best


def path_length_m(
    takeoff_xy: tuple[float, float],
    swaths: Iterable[Swath],
    landing_xy: tuple[float, float],
) -> float:
    cursor = takeoff_xy
    total = 0.0
    for swath in swaths:
        total += _hypot(cursor, swath.start)
        total += float(swath.length_m)
        cursor = swath.end
    total += _hypot(cursor, landing_xy)
    return total


def sortie_duration_s(
    takeoff_xy: tuple[float, float],
    swaths: Iterable[Swath],
    landing_xy: tuple[float, float],
    speed_m_s: float,
) -> float:
    if speed_m_s <= 0:
        raise ValueError("speed_m_s is not positive")
    return path_length_m(takeoff_xy, swaths, landing_xy) / speed_m_s


def pack_board(
    uav_id: str,
    swaths: list[Swath],
    pads: list[Pad],
    home_pad_id: str,
    endurance_s: float,
    speed_m_s: float,
    *,
    allow_foreign_landing: bool = True,
    allow_foreign_takeoff: bool = False,
    allow_recharge: bool = True,
) -> PackBoardResult:
    """Greedy endurance pack with optional foreign pads.

    Tries the given swath order and the reversed/flipped order; keeps the
    result with fewer uncovered swaths, then fewer sorties, then less air
    time. Not a global optimum.
    """
    if not swaths:
        return PackBoardResult(sorties=[], uncovered=[])
    forward = _pack_ordered(
        uav_id,
        swaths,
        pads,
        home_pad_id,
        endurance_s,
        speed_m_s,
        allow_foreign_landing=allow_foreign_landing,
        allow_foreign_takeoff=allow_foreign_takeoff,
        allow_recharge=allow_recharge,
    )
    backward = _pack_ordered(
        uav_id,
        _reversed_block(swaths),
        pads,
        home_pad_id,
        endurance_s,
        speed_m_s,
        allow_foreign_landing=allow_foreign_landing,
        allow_foreign_takeoff=allow_foreign_takeoff,
        allow_recharge=allow_recharge,
    )
    return _better_pack(forward, backward)


def apply_recharge_timeline(
    sorties: list[PackedSortie],
    recharge_s_by_uav: dict[str, float],
) -> float:
    """Place same-board sorties end-to-end with catalog charge gaps.

    ``mission_time_s`` consumers should use ``makespan_s`` (this return
    value after later delays) — charge gaps are inside the makespan, not
    inside ``total_flight_time_s``.
    """
    by_uav: dict[str, list[PackedSortie]] = {}
    for sortie in sorties:
        by_uav.setdefault(sortie.uav_id, []).append(sortie)
    makespan = 0.0
    for uav_id, items in by_uav.items():
        gap = max(0.0, float(recharge_s_by_uav.get(uav_id, 0.0)))
        t = 0.0
        for index, sortie in enumerate(items):
            before = gap if index > 0 else 0.0
            sortie.recharge_before_s = before
            sortie.start_time_s = t + before
            t = sortie.start_time_s + float(sortie.flight_time_s)
        makespan = max(makespan, t)
    return makespan


def makespan_s(sorties: Iterable[PackedSortie]) -> float:
    end = 0.0
    for sortie in sorties:
        end = max(end, float(sortie.start_time_s) + float(sortie.flight_time_s))
    return end


def total_flight_time_s(sorties: Iterable[PackedSortie]) -> float:
    return sum(float(sortie.flight_time_s) for sortie in sorties)


def recharge_gap_s(sorties: Iterable[PackedSortie]) -> float:
    return sum(float(sortie.recharge_before_s) for sortie in sorties)


def airborne_samples(
    sortie: PackedSortie,
    speed_m_s: float,
    sample_dt_s: float = 1.0,
) -> list[tuple[float, float, float]]:
    """``(t_s, x_m, y_m)`` along the airborne polyline (pads excluded)."""
    points = _polyline(sortie)
    if len(points) < 2 or speed_m_s <= 0:
        return []
    lengths = [_hypot(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lengths)
    if total <= 0:
        return []
    duration = total / speed_m_s
    dt = max(0.05, float(sample_dt_s))
    out: list[tuple[float, float, float]] = []
    t = dt
    while t < duration - 1e-9:
        out.append((sortie.start_time_s + t, *_point_on_path(points, lengths, t * speed_m_s)))
        t += dt
    # Interior vertices so a crossing is not missed between samples.
    walked = 0.0
    for index, seg_len in enumerate(lengths[:-1]):
        walked += seg_len
        if 0.0 < walked < total:
            out.append(
                (
                    sortie.start_time_s + walked / speed_m_s,
                    points[index + 1][0],
                    points[index + 1][1],
                )
            )
    out.sort(key=lambda item: item[0])
    return out


def detect_conflicts(
    sorties: list[PackedSortie],
    speed_m_s_by_uav: dict[str, float],
    min_separation_m: float,
    time_window_s: float = 0.0,
    sample_dt_s: float = 1.0,
) -> list[tuple[str, str, float]]:
    """Pairs ``(uav_a, uav_b, t_s)`` that violate horizontal separation."""
    if min_separation_m <= 0 or len(sorties) < 2:
        return []
    tracks: dict[str, list[tuple[float, float, float]]] = {}
    for sortie in sorties:
        speed = float(speed_m_s_by_uav.get(sortie.uav_id, 0.0))
        tracks.setdefault(sortie.uav_id, []).extend(
            airborne_samples(sortie, speed, sample_dt_s)
        )
    for uav_id in list(tracks):
        tracks[uav_id].sort(key=lambda item: item[0])
    uavs = sorted(tracks)
    found: list[tuple[str, str, float]] = []
    for i, a in enumerate(uavs):
        for b in uavs[i + 1 :]:
            hit = _first_conflict(tracks[a], tracks[b], min_separation_m, time_window_s)
            if hit is not None:
                found.append((a, b, hit))
    return found


def resolve_separation(
    sorties: list[PackedSortie],
    speed_m_s_by_uav: dict[str, float],
    min_separation_m: float,
    time_window_s: float = 0.0,
    sample_dt_s: float = 1.0,
) -> tuple[list[PackedSortie], int, float, list[str]]:
    """Heuristic: try reversing later UAV blocks, then delay until clean.

    Earlier ``uav_id`` (lexicographic) stays frozen. Delay is a documented
    makespan heuristic, not a globally optimal schedule.
    """
    notes: list[str] = [
        "UAV–UAV separation is a horizontal space–time heuristic (OPEN-013); "
        "not certified traffic management and not 3D overfly",
    ]
    if min_separation_m <= 0:
        notes.append("min_separation_m<=0: separation resolver disabled")
        return sorties, 0, 0.0, notes

    conflicts_before = detect_conflicts(
        sorties, speed_m_s_by_uav, min_separation_m, time_window_s, sample_dt_s
    )
    if not conflicts_before:
        notes.append("no UAV–UAV horizontal conflict at the requested buffer")
        return sorties, 0, 0.0, notes

    uavs = sorted({sortie.uav_id for sortie in sorties})
    by_uav: dict[str, list[PackedSortie]] = {uav: [] for uav in uavs}
    for sortie in sorties:
        by_uav[sortie.uav_id].append(sortie)

    total_delay = 0.0
    for uav in uavs[1:]:
        original = [ _copy_sortie(item) for item in by_uav[uav] ]
        reversed_try = [_copy_sortie(item) for item in _reversed_uav_block(by_uav[uav])]
        best_items = original
        best_delay = _delay_until_clean(
            sorties,
            uav,
            original,
            speed_m_s_by_uav,
            min_separation_m,
            time_window_s,
            sample_dt_s,
        )
        rev_delay = _delay_until_clean(
            sorties,
            uav,
            reversed_try,
            speed_m_s_by_uav,
            min_separation_m,
            time_window_s,
            sample_dt_s,
        )
        if rev_delay < best_delay:
            best_items = reversed_try
            best_delay = rev_delay
            notes.append(f"{uav}: reversed swath block to cut separation delay")
        _replace_uav(sorties, uav, best_items)
        if best_delay > 0:
            for item in best_items:
                item.start_time_s += best_delay
            _replace_uav(sorties, uav, best_items)
            total_delay += best_delay
            notes.append(f"{uav}: delayed {best_delay:.1f}s to clear horizontal buffer")

    conflicts_after = detect_conflicts(
        sorties, speed_m_s_by_uav, min_separation_m, time_window_s, sample_dt_s
    )
    if conflicts_after:
        notes.append(
            f"separation unresolved after delay ({len(conflicts_after)} pair(s)); "
            "plan is still returned — caller may treat as limitation"
        )
    return sorties, len(conflicts_before), total_delay, notes


def _pack_ordered(
    uav_id: str,
    swaths: list[Swath],
    pads: list[Pad],
    home_pad_id: str,
    endurance_s: float,
    speed_m_s: float,
    *,
    allow_foreign_landing: bool,
    allow_foreign_takeoff: bool,
    allow_recharge: bool,
) -> PackBoardResult:
    home = _home(pads, home_pad_id)
    takeoff = (
        choose_pad(
            swaths[0].start,
            pads,
            home_pad_id,
            allowed=allow_foreign_takeoff,
        )
        if swaths
        else home
    )
    sorties: list[PackedSortie] = []
    uncovered: list[Swath] = []
    current: list[Swath] = []
    current_takeoff = takeoff
    limitations: list[str] = []

    def landing_of(block: list[Swath]) -> Pad:
        return choose_pad(
            block[-1].end,
            pads,
            home_pad_id,
            allowed=allow_foreign_landing,
        )

    def close(block: list[Swath], takeoff_pad: Pad) -> PackedSortie:
        land = landing_of(block)
        return PackedSortie(
            uav_id=uav_id,
            takeoff_pad_id=takeoff_pad.id,
            landing_pad_id=land.id,
            takeoff_xy=takeoff_pad.xy,
            landing_xy=land.xy,
            swaths=list(block),
            flight_time_s=sortie_duration_s(
                takeoff_pad.xy, block, land.xy, speed_m_s
            ),
        )

    remaining = list(swaths)
    while remaining:
        swath = remaining[0]
        trial = [*current, swath]
        land = landing_of(trial)
        duration = sortie_duration_s(
            current_takeoff.xy, trial, land.xy, speed_m_s
        )
        if current and duration > endurance_s:
            if not allow_recharge:
                uncovered.extend(remaining)
                limitations.append(
                    "allow_recharge=false: leftover swaths not packed into a "
                    "second sortie"
                )
                remaining = []
                break
            sorties.append(close(current, current_takeoff))
            current_takeoff = choose_pad(
                current[-1].end,
                pads,
                home_pad_id,
                allowed=allow_foreign_landing,
            )
            current = []
            continue
        if not current and duration > endurance_s:
            recovered = _try_all_pads(
                uav_id,
                swath,
                pads,
                home_pad_id,
                endurance_s,
                speed_m_s,
                allow_foreign_landing=allow_foreign_landing,
                allow_foreign_takeoff=True,
            )
            if recovered is not None:
                sorties.append(recovered)
                current_takeoff = Pad(recovered.landing_pad_id, recovered.landing_xy)
                remaining.pop(0)
                continue
            uncovered.append(swath)
            remaining.pop(0)
            limitations.append(
                f"{uav_id}: one swath exceeds endurance even with best pads"
            )
            continue
        current = trial
        remaining.pop(0)

    if current:
        sorties.append(close(current, current_takeoff))
    return PackBoardResult(sorties=sorties, uncovered=uncovered, limitations=limitations)


def _try_all_pads(
    uav_id: str,
    swath: Swath,
    pads: list[Pad],
    home_pad_id: str,
    endurance_s: float,
    speed_m_s: float,
    *,
    allow_foreign_landing: bool,
    allow_foreign_takeoff: bool,
) -> PackedSortie | None:
    """Last-chance single-swath pack from any takeoff / landing pair."""
    takeoff_pads = pads if allow_foreign_takeoff else [_home(pads, home_pad_id)]
    landing_pads = pads if allow_foreign_landing else [_home(pads, home_pad_id)]
    best: PackedSortie | None = None
    for takeoff in takeoff_pads:
        for landing in landing_pads:
            duration = sortie_duration_s(
                takeoff.xy, [swath], landing.xy, speed_m_s
            )
            if duration > endurance_s:
                continue
            candidate = PackedSortie(
                uav_id=uav_id,
                takeoff_pad_id=takeoff.id,
                landing_pad_id=landing.id,
                takeoff_xy=takeoff.xy,
                landing_xy=landing.xy,
                swaths=[swath],
                flight_time_s=duration,
            )
            if best is None or candidate.flight_time_s < best.flight_time_s:
                best = candidate
    return best


def _better_pack(a: PackBoardResult, b: PackBoardResult) -> PackBoardResult:
    key_a = (
        len(a.uncovered),
        len(a.sorties),
        total_flight_time_s(a.sorties),
    )
    key_b = (
        len(b.uncovered),
        len(b.sorties),
        total_flight_time_s(b.sorties),
    )
    return a if key_a <= key_b else b


def _reversed_block(swaths: list[Swath]) -> list[Swath]:
    return [swath.flipped() for swath in reversed(swaths)]


def _reversed_uav_block(sorties: list[PackedSortie]) -> list[PackedSortie]:
    """Reverse swaths inside each sortie and swap takeoff/landing pads."""
    out: list[PackedSortie] = []
    for sortie in sorties:
        flipped = _reversed_block(sortie.swaths)
        out.append(
            PackedSortie(
                uav_id=sortie.uav_id,
                takeoff_pad_id=sortie.landing_pad_id,
                landing_pad_id=sortie.takeoff_pad_id,
                takeoff_xy=sortie.landing_xy,
                landing_xy=sortie.takeoff_xy,
                swaths=flipped,
                flight_time_s=sortie.flight_time_s,
                start_time_s=sortie.start_time_s,
                recharge_before_s=sortie.recharge_before_s,
            )
        )
    return out


def _copy_sortie(sortie: PackedSortie) -> PackedSortie:
    return PackedSortie(
        uav_id=sortie.uav_id,
        takeoff_pad_id=sortie.takeoff_pad_id,
        landing_pad_id=sortie.landing_pad_id,
        takeoff_xy=sortie.takeoff_xy,
        landing_xy=sortie.landing_xy,
        swaths=list(sortie.swaths),
        flight_time_s=sortie.flight_time_s,
        start_time_s=sortie.start_time_s,
        recharge_before_s=sortie.recharge_before_s,
    )


def _replace_uav(
    sorties: list[PackedSortie],
    uav_id: str,
    items: list[PackedSortie],
) -> None:
    sorties[:] = [sortie for sortie in sorties if sortie.uav_id != uav_id] + items


def _delay_until_clean(
    all_sorties: list[PackedSortie],
    uav_id: str,
    candidate: list[PackedSortie],
    speed_m_s_by_uav: dict[str, float],
    min_separation_m: float,
    time_window_s: float,
    sample_dt_s: float,
) -> float:
    frozen = [sortie for sortie in all_sorties if sortie.uav_id != uav_id]
    trial = [_copy_sortie(item) for item in candidate]
    delay = 0.0
    max_delay = 0.0
    for sortie in frozen + trial:
        speed = float(speed_m_s_by_uav.get(sortie.uav_id, 1.0)) or 1.0
        max_delay = max(
            max_delay,
            float(sortie.start_time_s) + float(sortie.flight_time_s) + 2.0,
        )
    max_delay = max(max_delay * 4.0, 60.0)
    dt = max(0.05, float(sample_dt_s))
    while delay <= max_delay + 1e-9:
        for item, src in zip(trial, candidate):
            item.start_time_s = src.start_time_s + delay
        hits = detect_conflicts(
            frozen + trial,
            speed_m_s_by_uav,
            min_separation_m,
            time_window_s,
            sample_dt_s,
        )
        involving = [hit for hit in hits if uav_id in hit[:2]]
        if not involving:
            return delay
        # Jump this UAV to just after the other UAV's current airborne end.
        others = [hit[0] if hit[1] == uav_id else hit[1] for hit in involving]
        other_end = 0.0
        for sortie in frozen:
            if sortie.uav_id in others:
                other_end = max(
                    other_end,
                    float(sortie.start_time_s) + float(sortie.flight_time_s),
                )
        next_delay = other_end - min(item.start_time_s for item in candidate) + dt
        if next_delay <= delay + 1e-9:
            delay += dt
        else:
            delay = next_delay
    return max_delay


def _first_conflict(
    a: list[tuple[float, float, float]],
    b: list[tuple[float, float, float]],
    min_separation_m: float,
    time_window_s: float,
) -> float | None:
    if not a or not b:
        return None
    times = sorted({item[0] for item in a} | {item[0] for item in b})
    window = max(0.0, float(time_window_s))
    for t in times:
        checks = [t] if window <= 0 else [t - window, t, t + window]
        for tchk in checks:
            pa = _pos_at(a, tchk)
            pb = _pos_at(b, tchk)
            if pa is None or pb is None:
                continue
            if _hypot(pa, pb) + 1e-9 < min_separation_m:
                return tchk
    return None


def _pos_at(
    samples: list[tuple[float, float, float]],
    t: float,
) -> tuple[float, float] | None:
    if not samples:
        return None
    if t < samples[0][0] - 1e-9 or t > samples[-1][0] + 1e-9:
        return None
    if len(samples) == 1:
        return (samples[0][1], samples[0][2])
    for index in range(len(samples) - 1):
        t0, x0, y0 = samples[index]
        t1, x1, y1 = samples[index + 1]
        if t0 - 1e-9 <= t <= t1 + 1e-9:
            if abs(t1 - t0) < 1e-12:
                return (x0, y0)
            frac = (t - t0) / (t1 - t0)
            return (x0 + frac * (x1 - x0), y0 + frac * (y1 - y0))
    return (samples[-1][1], samples[-1][2])


def _polyline(sortie: PackedSortie) -> list[tuple[float, float]]:
    points = [sortie.takeoff_xy]
    for swath in sortie.swaths:
        points.append(swath.start)
        points.append(swath.end)
    points.append(sortie.landing_xy)
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if cleaned and _hypot(cleaned[-1], point) < 1e-6:
            continue
        cleaned.append(point)
    return cleaned


def _point_on_path(
    points: list[tuple[float, float]],
    lengths: list[float],
    distance_m: float,
) -> tuple[float, float]:
    remain = max(0.0, float(distance_m))
    for index, seg_len in enumerate(lengths):
        if remain <= seg_len or index == len(lengths) - 1:
            start = points[index]
            end = points[index + 1]
            if seg_len <= 1e-12:
                return start
            frac = min(1.0, remain / seg_len)
            return (
                start[0] + frac * (end[0] - start[0]),
                start[1] + frac * (end[1] - start[1]),
            )
        remain -= seg_len
    return points[-1]


def _home(pads: list[Pad], home_id: str) -> Pad:
    for pad in pads:
        if pad.id == home_id:
            return pad
    if not pads:
        return Pad(home_id, (0.0, 0.0))
    return pads[0]


def _hypot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _optional_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, dict):
        raw = raw.get("value")
        if raw is None or isinstance(raw, bool):
            return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None
