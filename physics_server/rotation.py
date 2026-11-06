"""Exact torque-free orientation of a homogeneous sphere, in SI units."""

from dataclasses import dataclass
import math

from collision_outcomes import _vector


def angular_velocity(spin, mass, radius):
    """The same I=2MR²/5 used by the collision and energy budgets."""
    inertia = 0.4 * mass * radius**2
    return tuple(x / inertia for x in spin)


def multiply(a, b):
    x, y, z, w = a
    u, v, s, t = b
    return (
        w * u + x * t + y * s - z * v,
        w * v - x * s + y * t + z * u,
        w * s + x * v - y * u + z * t,
        w * t - x * u - y * v - z * s,
    )


@dataclass(frozen=True)
class Rotation:
    """Body-to-world quaternion (x,y,z,w) at an epoch, with inertial omega."""

    orientation: tuple = (0.0, 0.0, 0.0, 1.0)
    epoch_s: float = 0.0
    omega_rad_s: tuple = (0.0, 0.0, 0.0)

    def __post_init__(self):
        q = tuple(float(x) for x in self.orientation)
        if len(q) != 4 or not all(math.isfinite(x) for x in q) or abs(math.hypot(*q) - 1) > 1e-12:
            raise ValueError("Orientation must be a finite unit quaternion")
        if not math.isfinite(self.epoch_s) or self.epoch_s < 0:
            raise ValueError("Rotation epoch must be finite and nonnegative")
        object.__setattr__(self, "orientation", q)
        object.__setattr__(self, "omega_rad_s", _vector(self.omega_rad_s))

    def at(self, time_s):
        if not math.isfinite(time_s):
            raise ValueError("Orientation time must be finite")
        speed = math.hypot(*self.omega_rad_s)
        if speed == 0:
            return self.orientation
        angle = math.remainder(speed * (time_s - self.epoch_s), 4 * math.pi) / 2
        factor = math.sin(angle) / speed
        q = multiply((*[x * factor for x in self.omega_rad_s], math.cos(angle)), self.orientation)
        norm = math.hypot(*q)
        return tuple(x / norm for x in q)
