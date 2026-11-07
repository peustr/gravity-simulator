"""Linear quadrupolar equilibrium tides with a constant material time lag.

The full tidal tensor includes every resolved perturber. Its material-frame
derivative gives forces, reaction torque and positive dissipation together.
SI units throughout; spherical inertia agrees with the collision budgets.
"""

from dataclasses import dataclass
import math

import numpy as np

import units as U

MAX_TIDAL_BODIES = 16


@dataclass(frozen=True)
class Tide:
    k2: float
    lag_s: float
    heat_j: float = 0.0

    def __post_init__(self):
        for key, limit in (("k2", 1.5), ("lag_s", 1e6), ("heat_j", 1e100)):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= limit:
                raise ValueError("Invalid tidal Love number, lag or deposited heat")


def geometry(masses, positions, index, radius):
    keep = np.arange(len(masses)) != index
    r = positions[keep] - positions[index]
    distance = np.linalg.norm(r, axis=1)
    if np.any(distance <= radius):
        raise ValueError("Equilibrium tides require exterior perturbers")
    n = r / distance[:, None]
    nn = n[:, :, None] * n[:, None, :]
    field = np.sum((U.G_SI * masses[keep] / distance**3)[:, None, None] * (3 * nn - np.eye(3)), axis=0)
    if float(np.sum(masses[keep] / masses[index] * (radius / distance) ** 3)) > 0.01:
        raise ValueError("Equilibrium tides exceed the 1% deformation domain")
    return keep, distance, n, nn, field


def potential(masses, positions, index, radius, material):
    field = geometry(masses, positions, index, radius)[4]
    return float(-material.k2 * radius**5 / (12 * U.G_SI) * np.sum(field**2))


def validate_motion(mass, radius, omega, lag, derivative, norm):
    frequency2 = U.G_SI * mass / radius**3
    if np.dot(omega, omega) / frequency2 > 0.01:
        raise ValueError("Equilibrium tides exceed the 1% deformation domain")
    if np.linalg.norm(derivative) > 0.2 * math.sqrt(frequency2) * norm:
        raise ValueError("Equilibrium tides exceed the quasistatic domain")
    if lag * np.linalg.norm(derivative) > 0.1 * norm:
        raise ValueError("Equilibrium tides exceed the small-lag domain")


def linear_response(masses, positions, index, radius, material):
    """Map inertial velocities/spin to the material tidal-tensor derivative.

    Columns contain every Cartesian body velocity, followed by source omega.
    This also supplies the common potential and Rayleigh-function gradients.
    """
    keep, distance, n, nn, field = geometry(masses, positions, index, radius)
    identity = np.eye(3)
    gradient = (3 * U.G_SI * masses[keep] / distance**4)[:, None, None, None] * (
        identity[None, :, :, None] * n[:, None, None, :]
        + n[:, None, :, None] * identity[None, :, None, :]
        - 5 * n[:, :, None, None] * nn[:, None, :, :]
        + n[:, :, None, None] * identity
    )
    mapping = np.zeros((len(masses), 3, 3, 3))
    mapping[keep] = gradient
    mapping[index] = -np.sum(gradient, axis=0)
    mapping = mapping.reshape(-1, 9).T
    crosses = np.array([((0, -z, y), (z, 0, -x), (-y, x, 0)) for x, y, z in identity])
    spin = -(crosses @ field - field @ crosses)
    mapping = np.column_stack((mapping, spin.reshape(3, 9).T))
    coefficient = material.k2 * radius**5 / (6 * U.G_SI)
    potential = float(-0.5 * coefficient * np.sum(field**2))
    static = coefficient * (mapping.T @ field.reshape(9))
    return mapping, static, coefficient, potential, float(np.linalg.norm(field))


def response(masses, positions, velocities, index, radius, omega, material):
    """Forces, source reaction torque, nonnegative heating, stored potential."""
    if material.k2 == 0:
        return np.zeros_like(positions), np.zeros(3), 0.0, 0.0
    mapping, static, coefficient, potential, norm = linear_response(masses, positions, index, radius, material)
    velocity = np.concatenate((velocities.reshape(-1), omega))
    derivative = mapping @ velocity
    validate_motion(masses[index], radius, omega, material.lag_s, derivative, norm)
    generalized = static - coefficient * material.lag_s * (mapping.T @ derivative)
    force = generalized[:-3].reshape(-1, 3)
    torque = -np.sum(np.cross(positions - positions[index], force), axis=0)
    power = float(coefficient * material.lag_s * np.dot(derivative, derivative))
    return force, torque, power, potential


def orbit(masses, positions, velocities, index):
    """Osculating orbit relative to the strongest external tidal source."""
    keep = np.arange(len(masses)) != index
    if not np.any(keep):
        return None
    ids = np.flatnonzero(keep)
    distances = np.linalg.norm(positions[keep] - positions[index], axis=1)
    partner = int(ids[np.argmax(masses[keep] / distances**3)])
    r = positions[index] - positions[partner]
    v = velocities[index] - velocities[partner]
    mu = U.G_SI * (masses[index] + masses[partner])
    h = np.cross(r, v)
    length = np.linalg.norm(h)
    inverse_a = 2 / np.linalg.norm(r) - np.dot(v, v) / mu
    if inverse_a <= 0 or length == 0:
        return None
    e = np.linalg.norm(np.cross(v, h) / mu - r / np.linalg.norm(r))
    return dict(partner=partner, eccentricity=float(e), mean_motion=math.sqrt(mu * inverse_a**3), axis=h / length)
