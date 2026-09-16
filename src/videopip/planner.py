"""Pure timing logic (no rendering): b-roll chunk walking and intro montage slots.

Kept free of I/O so it can be unit-tested and used by `videopip plan`.
"""
from __future__ import annotations

from dataclasses import dataclass

Chunk = tuple[int, float, float]  # (clip index within the segment, start, duration)


class PlanError(ValueError):
    pass


def plan_chunks(ranges_by_clip: list[list[tuple[float, float]]], total: float, reveal_start: float,
                reveal_len: float, chunk: float = 4.0,
                forced: list[tuple[int, float, float]] | None = None) -> list[Chunk]:
    """Fill `total` seconds by walking every clip's safe ranges in `chunk`-second cuts.

    The first cut is the reveal (clip 0 at `reveal_start`). `forced` takes play as
    unbroken takes right after it, and are subtracted from the walkable ranges so
    the filler never replays them.
    """
    ranges = [[ci, a, b] for ci, rs in enumerate(ranges_by_clip) for a, b in rs]
    if not ranges:
        raise PlanError("no safe footage to plan from")
    for fci, fs, fd in forced or []:
        if not any(fci == rci and ra - 1e-6 <= fs and fs + fd <= rb + 1e-6 for rci, ra, rb in ranges):
            raise PlanError(f"forced take (clip #{fci} {fs}+{fd}s) is not fully inside a safe range")
        cut = []
        for rci, ra, rb in ranges:
            if rci != fci or fs >= rb or fs + fd <= ra:
                cut.append([rci, ra, rb])
                continue
            if fs - ra >= 0.5:
                cut.append([rci, ra, fs])
            if rb - (fs + fd) >= 0.5:
                cut.append([rci, fs + fd, rb])
        ranges = cut
    if not ranges:
        raise PlanError("forced takes consumed every safe range - nothing left to fill with")

    start_idx = next((k for k, (ci, a, b) in enumerate(ranges) if ci == 0 and a <= reveal_start < b), 0)
    cursor = {k: r[1] for k, r in enumerate(ranges)}
    ci, a, b = ranges[start_idx]
    if not (a <= reveal_start < b):
        reveal_start = a
    first = max(0.5, min(reveal_len + 1.4, b - reveal_start, total))
    chunks: list[Chunk] = [(ci, round(reveal_start, 2), round(first, 2))]
    cursor[start_idx] = reveal_start + first
    acc, k = first, start_idx
    for fci, fs, fd in forced or []:
        fd = min(fd, max(0.0, total - acc))
        if fd >= 0.3:
            chunks.append((fci, round(fs, 2), round(fd, 2)))
            acc += fd
    guard = 0
    while acc < total - 1e-3 and guard < 2000:
        guard += 1
        k = (k + 1) % len(ranges)
        ci, a, b = ranges[k]
        s = cursor[k]
        if b - s < 1.2:
            s = a
        d = min(chunk, b - s, total - acc)
        if d < 0.5:
            if total - acc < 0.5 and chunks:
                # absorb a tiny remainder into the last cut when its range allows
                lci, ls, ld = chunks[-1]
                chunks[-1] = (lci, ls, round(ld + (total - acc), 2))
                acc = total
            continue
        chunks.append((ci, round(s, 2), round(d, 2)))
        cursor[k] = s + d
        acc += d
    return chunks


def footage_pool(ranges_by_clip) -> float:
    return round(sum(b - a for rs in ranges_by_clip for a, b in rs), 2)


def intersect(ranges, window):
    a0, b0 = window
    out = [(max(a, a0), min(b, b0)) for a, b in ranges]
    return [(a, b) for a, b in out if b - a > 0.05]


@dataclass
class MontagePlan:
    lengths: list[float]
    starts: list[float]
    total: float
    vo_start: float
    sub_at: float | None
    notes: list[str]


def plan_montage(shots, sentence_starts: list[float], vo_duration: float, *, cold_gap: float,
                 hero_hold: float, vo_deadline: float, cue_lead: float, sub_at: float | None,
                 sub_len: float, intro_len: float | None) -> MontagePlan:
    """Slot lengths for the intro montage.

    shots: list of (role, range_len, explicit_len). Order: hero, cue..., music...
    Cue shots cut on the sentence that names them (sentence 1 = hero, so cue i uses
    sentence i+1). Every slot is CLAMPED to its range - a range shorter than its slot
    would silently shift every later shot, so windows are never widened.
    """
    notes: list[str] = []
    roles = [s[0] for s in shots]
    caps = [s[1] for s in shots]
    cue_idx = [i for i, r in enumerate(roles) if r == "cue"]
    music_idx = [i for i, r in enumerate(roles) if r == "music"]
    vo_end = round(cold_gap + vo_duration, 2)
    if vo_end > vo_deadline + 1e-6:
        raise PlanError(f"intro VO ends at {vo_end}s, past the {vo_deadline}s deadline - cut words from intro.vo")

    if sub_at is not None:
        beat = round(max(sub_at, vo_end), 2)
        if beat > sub_at + 1e-6:
            notes.append(f"subscribe beat moved {sub_at}s -> {beat}s so it never talks over the VO")
    else:
        beat = round(vo_end + 1.0, 2) if intro_len is None else float(intro_len)
    music_total = (sub_len if sub_at is not None else 0.0)
    if intro_len is not None:
        music_total = max(0.0, intro_len - beat)
    lengths = [0.0] * len(shots)
    n = len(cue_idx)
    if n:
        # cue 0 starts when the hero hold ends; cue k>=1 cuts on sentence k+1
        # (sentence 0 = hero, sentence k = the k-th cue's tool)
        if len(sentence_starts) < n + 1:
            notes.append(f"intro.vo has {len(sentence_starts)} sentences for 1 hero + {n} cue shots; "
                         f"cuts are spread evenly instead")
            span = max(beat - hero_hold, 0.5)
            bounds = [round(hero_hold + span * k / n, 2) for k in range(n)]
        else:
            bounds = [hero_hold] + [round(max(cold_gap + sentence_starts[k + 1] - cue_lead, hero_hold + 0.8), 2)
                                    for k in range(1, n)]
        bnd = bounds + [beat]
        want = [round(bnd[k + 1] - bnd[k], 2) for k in range(n)]
        cue_len = [min(max(w, 1.0), caps[i]) for w, i in zip(want, cue_idx)]
        room = round(beat - min(hero_hold, beat - 0.5), 2)
        if sum(cue_len) > room > 0:
            sc = room / sum(cue_len)
            cue_len = [round(x * sc, 2) for x in cue_len]
        for w, l, i in zip(want, cue_len, cue_idx):
            if abs(w - l) > 0.05:
                notes.append(f"shot {i} wanted {w}s from the VO but its window holds {caps[i]}s -> "
                             f"{round(l, 2)}s (slack moved to the hero)")
            lengths[i] = round(l, 2)
        hero = round(beat - sum(lengths[i] for i in cue_idx), 2)
    else:
        hero = beat
    lengths[0] = hero
    if hero > caps[0] + 0.05:
        raise PlanError(f"hero shot needs {hero}s but its window holds {caps[0]}s - give the hero a "
                        f"longer range or add cue shots")
    # music shots share the post-beat time
    if music_idx:
        explicit = {i: shots[i][2] for i in music_idx if shots[i][2]}
        rest = [i for i in music_idx if i not in explicit]
        remaining = max(0.0, music_total - sum(explicit.values()))
        for i in music_idx:
            lengths[i] = round(explicit.get(i, remaining / max(1, len(rest))), 2)
        for i in music_idx:
            if lengths[i] > caps[i] + 0.05:
                raise PlanError(f"music shot {i} needs {lengths[i]}s but its window holds {caps[i]}s - "
                                f"give it an explicit shorter `length` and a longer neighbour")
    elif music_total > 0:
        # no music shots: hold the last shot through the subscribe beat
        last = len(shots) - 1
        extra = min(music_total, max(0.0, caps[last] - lengths[last]))
        lengths[last] = round(lengths[last] + extra, 2)
        if extra + 1e-6 < music_total:
            notes.append(f"no music shots and the last window is short: intro ends {round(music_total-extra,2)}s "
                         f"before the subscribe beat finishes")
    starts, acc = [], 0.0
    for l in lengths:
        starts.append(round(acc, 2))
        acc += l
    return MontagePlan(lengths, starts, round(acc, 2), cold_gap, beat if sub_at is not None else None, notes)


def segment_length(speech_start: float, vo_duration: float, tail: float) -> float:
    return round(speech_start + vo_duration + tail, 2)


def speech_start(reveal: float, gap: float) -> float:
    return round(reveal + 0.6 + gap, 2)


def stinger_len(reveal: float) -> float:
    return round(reveal + 0.6, 2)


def xfade_offsets(durs: list[float], trans: float) -> tuple[list[float], list[float], float]:
    """Return (per-transition duration, offset, total runtime) for a chained xfade."""
    ds, offs = [], []
    run = durs[0]
    for i in range(1, len(durs)):
        d = round(max(0.15, min(trans, durs[i - 1] * 0.4, durs[i] * 0.4)), 3)
        off = round(run - d, 3)
        ds.append(d)
        offs.append(off)
        run = round(run + durs[i] - d, 3)
    return ds, offs, run
