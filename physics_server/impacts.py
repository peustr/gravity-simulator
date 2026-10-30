"""Immutable pre-merge collision measurements in simulation units.

These are pair kinematics and physical-mass inventory scales, not a calibrated
outcome law. They also describe mass-bearing tracers, whose gravitational force
model need not conserve the corresponding Newtonian inventories.
"""
from dataclasses import dataclass
import math


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class Impact:
    mass_a: float
    mass_b: float
    radius_a: float
    radius_b: float
    relative_position: tuple[float, float, float]
    relative_velocity: tuple[float, float, float]
    gravity: float

    @property
    def total_mass(self):
        return self.mass_a + self.mass_b

    @property
    def reduced_mass(self):
        return self.mass_a / self.total_mass * self.mass_b if self.total_mass > 0 else 0.0

    @property
    def separation(self):
        return math.hypot(*self.relative_position)

    @property
    def contact_distance(self):
        return self.radius_a + self.radius_b

    @property
    def speed(self):
        return math.hypot(*self.relative_velocity)

    @property
    def normal(self):
        """Direction from A to B, undefined at coincident centres."""
        return tuple(x / self.separation for x in self.relative_position) if self.separation > 0 else None

    @property
    def radial_speed(self):
        """Signed rate of separation; approaching bodies have negative values."""
        if self.separation == 0:
            return None
        return sum(x * v for x, v in zip(self.relative_position, self.relative_velocity, strict=True)) / self.separation

    @property
    def impact_parameter(self):
        """sin(theta) at the sampled contact: 0 head-on, 1 tangential.

        A zero speed or coincident centres leaves the angle undefined. Direct
        overlap detection samples slightly inside the surface; no trajectory
        extrapolation or hit-and-run classification is implied here.
        """
        scale = self.separation * self.speed
        if scale == 0:
            return None
        return min(1.0, math.hypot(*_cross(self.relative_position, self.relative_velocity)) / scale)

    @property
    def kinetic_energy(self):
        """Relative kinetic energy in the pair's centre-of-mass frame."""
        return 0.5 * self.reduced_mass * self.speed**2

    @property
    def specific_energy(self):
        """Q_R: relative kinetic energy divided by total physical mass."""
        return self.kinetic_energy / self.total_mass if self.total_mass > 0 else 0.0

    @property
    def angular_momentum(self):
        """Pair orbital angular momentum about its centre of mass; excludes spin."""
        return tuple(self.reduced_mass * x for x in _cross(self.relative_position, self.relative_velocity))

    @property
    def escape_speed(self):
        """Mutual surface escape scale using physical masses, including tracers."""
        if self.contact_distance == 0:
            return None
        return math.sqrt(2 * self.gravity * self.total_mass / self.contact_distance)


def capture(a, b, gravity):
    """Copy particle values before merging or reallocating native particle data."""
    return Impact(float(a.m), float(b.m), float(a.r), float(b.r),
                  tuple(y - x for x, y in zip(a.xyz, b.xyz, strict=True)),
                  tuple(y - x for x, y in zip(a.vxyz, b.vxyz, strict=True)), float(gravity))
