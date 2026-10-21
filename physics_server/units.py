"""Physical scale shared by all new scenes; SI definitions live here.

IAU 2012 AU, IAU 2015 nominal solar radius and GM, CODATA 2022 G.
Jovian volumetric mean radius: NASA/JPL planetary physical parameters.
Nominal GM is exact by convention; masses inferred using measured G are not.
"""
import math

SYSTEM = 'au60-solar1000-v1'
LEGACY = 'legacy-sandbox-v1'
G_SI = 6.67430e-11                 # m^3 kg^-1 s^-2
C_SI = 299_792_458.0               # m s^-1 (exact)
AU_M = 149_597_870_700.0           # m (exact)
SOLAR_GM = 1.3271244e20            # m^3 s^-2 (nominal)
SOLAR_RADIUS_M = 6.957e8           # m (nominal)
JUPITER_RADIUS_M = 6.9911e7        # m, volumetric mean (not equatorial)
JUPITER_MASS = 0.954594234         # in simulation mass units
LENGTH_M = AU_M / 60.0
MASS_KG = SOLAR_GM / G_SI / 1000.0
TIME_S = math.sqrt(LENGTH_M**3 / (G_SI * MASS_KG))
VELOCITY_M_S = LENGTH_M / TIME_S
DENSITY_KG_M3 = MASS_KG / LENGTH_M**3
G = G_SI * MASS_KG * TIME_S**2 / LENGTH_M**3


def metadata():
    return dict(id=SYSTEM, length_m=LENGTH_M, mass_kg=MASS_KG, time_s=TIME_S,
                velocity_m_s=VELOCITY_M_S, density_kg_m3=DENSITY_KG_M3)


def physical_radius(kind, mass):
    """Effective contact radius, in simulation length units.

    Bulk-density solids; constant-density ice giants up to a Jovian radius;
    broken-power-law main sequence; fixed 12 km neutron star; Schwarzschild BH.
    Plasma is an effective pressureless parcel at 1 kg/m^3, not hydrodynamics.
    These approximations do not include composition, age, or an equation of state.
    """
    mass = max(mass, 1e-30)
    if kind in (0, 5, 6):
        density = {0: 5514.0, 5: 2000.0, 6: 1.0}[kind]
        return (3 * mass * MASS_KG / (4 * math.pi * density))**(1 / 3) / LENGTH_M
    if kind == 1:
        # A deliberately simple cold giant model. No unphysical minimum radius.
        return JUPITER_RADIUS_M / LENGTH_M * min(1.0, (mass / JUPITER_MASS)**(1 / 3))
    if kind == 2:
        solar_mass = mass / 1000.0
        return SOLAR_RADIUS_M / LENGTH_M * solar_mass**(0.8 if solar_mass <= 1 else 0.57)
    if kind == 3:
        return 12_000.0 / LENGTH_M
    if kind == 4:
        return 2 * G_SI * mass * MASS_KG / C_SI**2 / LENGTH_M
    raise ValueError('Unknown body type')
