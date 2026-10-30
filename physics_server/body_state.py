"""Persistent intrinsic body inventories and SI collision snapshots."""
from dataclasses import dataclass
import math

from collision_outcomes import SphereState, _vector
import units


@dataclass(frozen=True)
class GravitySource:
    """External spherical gravity geometry; no claim about spin or heat."""
    mass_kg: float
    radius_m: float
    position_m: tuple[float, float, float]

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.mass_kg, self.radius_m)):
            raise ValueError('External gravity mass and radius must be finite and positive')
        object.__setattr__(self, 'position_m', _vector(self.position_m))


@dataclass(frozen=True)
class BodyInventory:
    """Spin angular momentum and energy above the fixed material reference.

    Zero is an explicit initial condition, not a temperature inferred from the
    visual heat value. Use None for inventories that have not been accounted for.
    """

    spin_kg_m2_s: tuple[float, float, float] = (0.0, 0.0, 0.0)
    internal_energy_j: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, 'spin_kg_m2_s', _vector(self.spin_kg_m2_s))
        energy = float(self.internal_energy_j)
        if not math.isfinite(energy) or energy < 0:
            raise ValueError('Internal energy must be finite and nonnegative')
        object.__setattr__(self, 'internal_energy_j', energy)


def capture_sphere(particle, inventory, unit_system):
    """Copy a live particle; unknown inventories/legacy units have no SI state."""
    if unit_system != units.SYSTEM or inventory is None:
        return None
    try:
        return SphereState(
            particle.m * units.MASS_KG, particle.r * units.LENGTH_M,
            tuple(x * units.LENGTH_M for x in particle.xyz),
            tuple(v * units.VELOCITY_M_S for v in particle.vxyz),
            inventory.spin_kg_m2_s, inventory.internal_energy_j)
    except (ValueError, OverflowError):
        # An unrepresentable sphere must not break the existing collision path.
        return None
