extends RefCounted
## Shared constants, colours, names and formulas for body types.
## Body type numbers must match physics_server/world.py.

const ROCKY := 0
const GAS_GIANT := 1
const STAR := 2
const NEUTRON_STAR := 3
const BLACK_HOLE := 4
const ASTEROID := 5
const PLASMA := 6

const TYPE_KEYS := ["rocky", "gas_giant", "star", "neutron_star", "black_hole", "asteroid", "plasma"]
const TYPE_LABELS := ["Rocky planet", "Gas giant", "Star", "Neutron star", "Black hole", "Asteroid", "Gas cloud"]
const TOOL_TYPES := [ROCKY, GAS_GIANT, STAR, NEUTRON_STAR, BLACK_HOLE, ASTEROID]
const DEFAULT_MASS := [0.003, 1.0, 1000.0, 1400.0, 20000.0, 2e-5, 1.0]

const TYPE_COLORS := [
	Color(0.40, 0.68, 1.00),   # rocky
	Color(0.92, 0.74, 0.50),   # gas giant
	Color(1.00, 0.86, 0.48),   # star
	Color(0.62, 0.86, 1.00),   # neutron star
	Color(0.78, 0.52, 1.00),   # black hole
	Color(0.68, 0.66, 0.62),   # asteroid
	Color(1.00, 0.58, 0.34),   # plasma
]

# Event codes (must match world.py)
const EV_MERGE := 1
const EV_SHATTER := 2
const EV_SWALLOW := 3
const EV_TIDAL := 4
const EV_SUPERNOVA := 5
const EV_IGNITION := 6
const EV_COLLAPSE := 7
const EV_BH_MERGER := 8
const EV_KILONOVA := 9

const _SYL_A := ["Ka", "Ve", "Lo", "Ri", "Tha", "Zo", "Mi", "Ar", "En", "Sol", "Dra", "Ny", "Or", "Pe", "Qua", "Ul", "Ys", "Tor", "Ae", "Bel", "Cy", "Del", "Fen", "Gal", "Hy", "Io", "Jun", "Kor", "Lyr", "Mor"]
const _SYL_B := ["ra", "lon", "vis", "dor", "nae", "mir", "tis", "ka", "rus", "phe", "lia", "xen", "on", "ber", "dia", "gos", "lux", "ris", "the", "vax"]
const _SYL_C := ["", "", "", "a", "ion", "is", "or", "us", "e", "ar"]


static func hash01(id: int, salt: int = 0) -> float:
	var h := (id * 374761393 + salt * 668265263) & 0x7fffffff
	h = ((h ^ (h >> 13)) * 1274126177) & 0x7fffffff
	h = h ^ (h >> 16)
	return float(h & 0xffffff) / float(0xffffff)


static func pick(arr: Array, id: int, salt: int):
	return arr[int(hash01(id, salt) * arr.size()) % arr.size()]


static func body_name(id: int, body_type: int) -> String:
	if body_type == ASTEROID:
		return "Asteroid %d" % id
	if body_type == PLASMA:
		return "Gas cloud %d" % id
	var n: String = pick(_SYL_A, id, 1) + pick(_SYL_B, id, 2) + pick(_SYL_C, id, 3)
	return n


static func radius_for(body_type: int, m: float) -> float:
	## Mirror of world.radius_for (used for the placement ghost).
	m = maxf(m, 1e-12)
	match body_type:
		ROCKY, ASTEROID:
			return maxf(0.2, pow(m / 0.003, 1.0 / 3.0))
		GAS_GIANT:
			return 2.8 * pow(maxf(m, 0.03), 0.08)
		STAR:
			return maxf(2.4, 5.0 * pow(m / 1000.0, 0.55))
		NEUTRON_STAR:
			return 0.6
		BLACK_HOLE:
			return maxf(0.6, 3.0 * m / 10000.0)
		PLASMA:
			return clampf(0.35 * pow(m, 1.0 / 3.0), 0.08, 4.0)
	return 1.0


static func star_temperature(m: float) -> float:
	return clampf(5800.0 * pow(m / 1000.0, 0.55), 2300.0, 45000.0)


static func blackbody(kelvin: float) -> Color:
	## Approximate colour of a black body (Tanner Helland's fit).
	var t := clampf(kelvin, 1000.0, 40000.0) / 100.0
	var r: float
	var g: float
	var b: float
	if t <= 66.0:
		r = 255.0
		g = 99.4708025861 * log(t) - 161.1195681661
	else:
		r = 329.698727446 * pow(t - 60.0, -0.1332047592)
		g = 288.1221695283 * pow(t - 60.0, -0.0755148492)
	if t >= 66.0:
		b = 255.0
	elif t <= 19.0:
		b = 0.0
	else:
		b = 138.5177312231 * log(t - 10.0) - 305.0447927307
	return Color(clampf(r, 0, 255) / 255.0, clampf(g, 0, 255) / 255.0, clampf(b, 0, 255) / 255.0)


static func star_color(m: float) -> Color:
	return blackbody(star_temperature(m))


static func spectral_class(kelvin: float) -> String:
	if kelvin >= 30000.0: return "O"
	if kelvin >= 10000.0: return "B"
	if kelvin >= 7500.0: return "A"
	if kelvin >= 6000.0: return "F"
	if kelvin >= 5200.0: return "G"
	if kelvin >= 3700.0: return "K"
	return "M"


static func friendly_mass(m: float, body_type: int) -> String:
	if body_type in [STAR, NEUTRON_STAR, BLACK_HOLE] or m >= 80.0:
		return "%s Suns" % _sig(m / 1000.0)
	if m >= 0.03:
		return "%s Jupiters" % _sig(m)
	return "%s Earths" % _sig(m / 0.003)


static func _sig(v: float) -> String:
	if v >= 100.0:
		return "%d" % int(round(v))
	if v >= 10.0:
		return "%.1f" % v
	if v >= 0.1:
		return "%.2f" % v
	if v >= 0.001:
		return "%.3f" % v
	return "%.1e" % v


static func describe_mass(body_type: int, mult: float) -> String:
	var m: float = DEFAULT_MASS[body_type] * mult
	match body_type:
		ROCKY:
			if m < 0.0005: return "Mars-like"
			if m < 0.006: return "Earth-like"
			return "Super-Earth"
		GAS_GIANT:
			if m < 0.1: return "Neptune-like"
			if m < 3.0: return "Jupiter-like"
			return "Super-Jupiter"
		STAR:
			var k := star_temperature(m)
			if k < 3700.0: return "Red dwarf"
			if k < 5200.0: return "Orange dwarf"
			if k < 6000.0: return "Sun-like"
			if k < 10000.0: return "White star"
			return "Blue giant"
		NEUTRON_STAR:
			return "Pulsar"
		BLACK_HOLE:
			return "Stellar black hole" if m < 100000.0 else "Monster black hole"
		ASTEROID:
			return "Space rock"
	return ""


static func rocky_palette(seed: float) -> Dictionary:
	var kinds := [
		# ocean, land, highland, water level, atmosphere
		[Color(0.04, 0.16, 0.42), Color(0.22, 0.42, 0.18), Color(0.62, 0.54, 0.38), 0.52, Color(0.35, 0.6, 1.0)],
		[Color(0.30, 0.12, 0.06), Color(0.62, 0.30, 0.14), Color(0.85, 0.60, 0.38), 0.30, Color(1.0, 0.6, 0.4)],
		[Color(0.55, 0.62, 0.70), Color(0.78, 0.84, 0.90), Color(0.95, 0.97, 1.0), 0.45, Color(0.7, 0.85, 1.0)],
		[Color(0.18, 0.17, 0.16), Color(0.45, 0.42, 0.38), Color(0.66, 0.64, 0.60), 0.25, Color(0.0, 0.0, 0.0)],
		[Color(0.05, 0.30, 0.32), Color(0.30, 0.50, 0.30), Color(0.80, 0.78, 0.55), 0.58, Color(0.4, 0.9, 0.8)],
		[Color(0.20, 0.08, 0.20), Color(0.55, 0.25, 0.45), Color(0.90, 0.70, 0.60), 0.40, Color(0.9, 0.5, 1.0)],
	]
	var k: Array = kinds[int(seed * 997.0) % kinds.size()]
	return {"ocean": k[0], "land": k[1], "high": k[2], "water": k[3], "atmo": k[4]}


static func gas_palette(seed: float) -> Dictionary:
	var kinds := [
		[Color(0.85, 0.72, 0.55), Color(0.62, 0.42, 0.28), Color(0.95, 0.90, 0.80)],
		[Color(0.35, 0.55, 0.90), Color(0.20, 0.32, 0.70), Color(0.70, 0.85, 1.00)],
		[Color(0.92, 0.85, 0.62), Color(0.78, 0.66, 0.42), Color(1.00, 0.96, 0.85)],
		[Color(0.55, 0.85, 0.85), Color(0.30, 0.60, 0.65), Color(0.85, 1.00, 0.98)],
		[Color(0.88, 0.55, 0.62), Color(0.55, 0.25, 0.40), Color(1.00, 0.85, 0.80)],
	]
	var k: Array = kinds[int(seed * 991.0) % kinds.size()]
	return {"a": k[0], "b": k[1], "c": k[2]}
