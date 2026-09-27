"""Which frames a render samples for the QA seam.

Not every frame -- storing 480p15 for a minute is nine hundred images nobody
reads. The rule is one sample per second plus the first and last frame of each
scene, which is enough for a QA stage to notice a scene that came up empty, lost
its subject off-frame, or never changed. The choice is deterministic so two
renders of the same plan sample the same instants and their manifests compare.
"""

from __future__ import annotations

__all__ = ["sample_frames"]


def sample_frames(duration_frames: int, fps: int, sample_rate_hz: float) -> tuple[int, ...]:
    """Frame indices to sample from a scene ``duration_frames`` long.

    Always includes frame 0 and the last frame; between them, one every
    ``fps / sample_rate_hz`` frames. A non-positive rate falls back to just the
    endpoints, which is the fewest that still bounds a scene at both ends.
    """
    last = duration_frames - 1
    if last <= 0:
        return (0,)
    marks = {0, last}
    if sample_rate_hz > 0.0:
        step = max(1, round(fps / sample_rate_hz))
        marks.update(range(0, duration_frames, step))
    return tuple(sorted(marks))
