"""Local volume samples for the pressureless tidal-breakup approximation.

Antipodal pairs preserve the source centroid. Effective parcel volumes sum to
the source volume; overlapping gas samples are not colliding solid fragments.
No random impulse, pre-stretched stream, pressure or thermal model is supplied.
"""
import math


def source_samples(radius, count):
    """Return equal-mass samples (offset, effective radius), inside the source."""
    if not math.isfinite(radius) or radius <= 0 or type(count) is not int or count < 4 or count % 2:
        raise ValueError('Expected a positive source radius and an even sample count >= 4')
    parcel_radius = radius / count**(1 / 3)
    pairs = count // 2
    golden_angle = math.pi * (3 - math.sqrt(5))
    samples = []
    for k in range(pairs):
        z = (k + .5) / pairs
        radial = (radius - parcel_radius) * z**(1 / 3)
        xy = math.sqrt(1 - z*z)
        direction = (xy*math.cos(k*golden_angle), xy*math.sin(k*golden_angle), z)
        offset = tuple(radial * x for x in direction)
        samples.extend(((offset, parcel_radius), (tuple(-x for x in offset), parcel_radius)))
    return samples
