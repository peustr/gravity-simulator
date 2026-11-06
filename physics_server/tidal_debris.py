"""Local volume samples for the pressureless tidal-breakup approximation.

Antipodal pairs preserve the source centroid. Effective parcel volumes sum to
the source volume; overlapping gas samples are not colliding solid fragments.
No random impulse, pre-stretched stream, pressure or thermal model is supplied.
"""
import math


def source_samples(radius, count, *, point=False):
    """Return equal-mass samples (offset, effective radius), inside the source."""
    if not math.isfinite(radius) or radius <= 0 or type(count) is not int or count < 4 or count % 2:
        raise ValueError('Expected a positive source radius and an even sample count >= 4')
    parcel_radius = radius / count**(1 / 3)
    pairs = count // 2
    golden_angle = math.pi * (3 - math.sqrt(5))
    samples = []
    for k in range(pairs):
        # Independent low-discrepancy radial and polar coordinates. Coupling
        # radius to latitude would retain an anisotropic density as N grows.
        index, z, factor = k+1, 0., 1/3
        while index:
            index, digit = divmod(index, 3)
            z += digit*factor
            factor /= 3
        radial = (radius if point else radius-parcel_radius) * ((k + .5) / pairs)**(1 / 3)
        xy = math.sqrt(1 - z*z)
        direction = (xy*math.cos(k*golden_angle), xy*math.sin(k*golden_angle), z)
        offset = tuple(radial * x for x in direction)
        samples.extend(((offset, parcel_radius), (tuple(-x for x in offset), parcel_radius)))
    return samples
