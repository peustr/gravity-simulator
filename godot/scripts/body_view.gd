extends Node3D
## The visual representation of one simulated body. Physics lives in the
## Python server; this node only draws what the server reports.

const Palette = preload("res://scripts/palette.gd")
const SH_ROCKY := preload("res://shaders/rocky.gdshader")
const SH_GAS := preload("res://shaders/gas_giant.gdshader")
const SH_STAR := preload("res://shaders/star.gdshader")
const SH_GLOW := preload("res://shaders/glow_sprite.gdshader")
const SH_LENS := preload("res://shaders/black_hole_lens.gdshader")
const SH_DISK := preload("res://shaders/accretion_disk.gdshader")
const SH_ROCK := preload("res://shaders/asteroid.gdshader")
const SH_MARKER := preload("res://shaders/marker.gdshader")
const SH_BEAM := preload("res://shaders/beam.gdshader")

const BIG_AABB := AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))

static var _sphere_hi: SphereMesh
static var _sphere_lo: SphereMesh
static var _quad: QuadMesh
static var _annulus: ArrayMesh
static var _cone: CylinderMesh

var id := 0
var body_type := -1
var mass := 0.0
var physical_radius := 1.0
var rendered_radius := 1.0
var heat := 0.0
var age := 0.0
var seed := 0.0
var display_name := ""

# Motion (filled in by main.gd)
var base_pos := Vector3.ZERO
var vel := Vector3.ZERO

var light: OmniLight3D
var flare := 0.0

var _surface: MeshInstance3D
var _surface_mat: ShaderMaterial
var _glow: MeshInstance3D
var _glow_mat: ShaderMaterial
var _marker: MeshInstance3D
var _marker_mat: ShaderMaterial
var _disk: MeshInstance3D
var _disk_mat: ShaderMaterial
var _lens: MeshInstance3D
var _lens_mat: ShaderMaterial
var _beams: Node3D
var _beam_mats: Array[ShaderMaterial] = []
var _jets: Node3D
var _jet_mats: Array[ShaderMaterial] = []
var _visual_root: Node3D
var _last_heat := -1.0
var _last_color_mass := -1.0
var _spin_axis := Vector3.UP


static func _ensure_meshes() -> void:
	if _sphere_hi != null:
		return
	_sphere_hi = SphereMesh.new()
	_sphere_hi.radius = 1.0
	_sphere_hi.height = 2.0
	_sphere_hi.radial_segments = 64
	_sphere_hi.rings = 32
	_sphere_lo = SphereMesh.new()
	_sphere_lo.radius = 1.0
	_sphere_lo.height = 2.0
	_sphere_lo.radial_segments = 12
	_sphere_lo.rings = 7
	_quad = QuadMesh.new()
	_quad.size = Vector2(2, 2)
	_cone = CylinderMesh.new()
	_cone.top_radius = 1.0
	_cone.bottom_radius = 0.02
	_cone.height = 1.0
	_cone.radial_segments = 24
	_cone.rings = 1
	_cone.cap_top = false
	_cone.cap_bottom = false
	_annulus = _make_annulus(0.36, 1.0, 160, 6)


static func _make_annulus(r_in: float, r_out: float, segs: int, rings: int) -> ArrayMesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for ri in range(rings):
		var a0 := lerpf(r_in, r_out, float(ri) / rings)
		var a1 := lerpf(r_in, r_out, float(ri + 1) / rings)
		for s in range(segs):
			var t0 := TAU * s / segs
			var t1 := TAU * (s + 1) / segs
			var p00 := Vector3(cos(t0) * a0, 0, sin(t0) * a0)
			var p01 := Vector3(cos(t1) * a0, 0, sin(t1) * a0)
			var p10 := Vector3(cos(t0) * a1, 0, sin(t0) * a1)
			var p11 := Vector3(cos(t1) * a1, 0, sin(t1) * a1)
			for v in [p00, p10, p11, p00, p11, p01]:
				st.set_normal(Vector3.UP)
				st.add_vertex(v)
	return st.commit()


func setup(p_id: int, p_type: int) -> void:
	_ensure_meshes()
	id = p_id
	seed = Palette.hash01(id, 7) * 100.0
	var tilt := Vector3(Palette.hash01(id, 11) - 0.5, 0.0, Palette.hash01(id, 12) - 0.5) * 0.5
	_spin_axis = (Vector3.UP + tilt).normalized()
	set_type(p_type)


func set_type(t: int) -> void:
	if t == body_type:
		return
	body_type = t
	display_name = Palette.body_name(id, t)
	if _visual_root != null:
		_visual_root.queue_free()
	_visual_root = Node3D.new()
	add_child(_visual_root)
	_surface = null
	_glow = null
	_disk = null
	_lens = null
	_beams = null
	_jets = null
	_beam_mats.clear()
	_jet_mats.clear()
	light = null
	_last_heat = -1.0
	_last_color_mass = -1.0
	match body_type:
		Palette.ROCKY: _build_rocky()
		Palette.GAS_GIANT: _build_gas()
		Palette.STAR: _build_star()
		Palette.NEUTRON_STAR: _build_neutron()
		Palette.BLACK_HOLE: _build_black_hole()
		Palette.ASTEROID: _build_asteroid()
		Palette.PLASMA: _build_plasma()
	_build_marker()
	_apply_radius()
	set_process(body_type in [Palette.NEUTRON_STAR, Palette.BLACK_HOLE])


func _mesh_instance(mesh: Mesh, mat: Material, parent: Node3D = null) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = mat
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	(parent if parent != null else _visual_root).add_child(mi)
	return mi


func _shader_mat(sh: Shader) -> ShaderMaterial:
	var m := ShaderMaterial.new()
	m.shader = sh
	m.set_shader_parameter("seed", seed)
	return m


func _build_rocky() -> void:
	var pal := Palette.rocky_palette(Palette.hash01(id, 3))
	_surface_mat = _shader_mat(SH_ROCKY)
	_surface_mat.set_shader_parameter("ocean_color", pal.ocean)
	_surface_mat.set_shader_parameter("land_color", pal.land)
	_surface_mat.set_shader_parameter("high_color", pal.high)
	_surface_mat.set_shader_parameter("water_level", pal.water)
	_surface_mat.set_shader_parameter("atmo_color", pal.atmo)
	_surface_mat.set_shader_parameter("spin", 0.08 + 0.2 * Palette.hash01(id, 4))
	_surface = _mesh_instance(_sphere_hi, _surface_mat)


func _build_gas() -> void:
	var pal := Palette.gas_palette(Palette.hash01(id, 5))
	_surface_mat = _shader_mat(SH_GAS)
	_surface_mat.set_shader_parameter("color_a", pal.a)
	_surface_mat.set_shader_parameter("color_b", pal.b)
	_surface_mat.set_shader_parameter("color_c", pal.c)
	_surface_mat.set_shader_parameter("band_freq", 10.0 + 10.0 * Palette.hash01(id, 6))
	_surface_mat.set_shader_parameter("spin", 0.15 + 0.2 * Palette.hash01(id, 8))
	_surface = _mesh_instance(_sphere_hi, _surface_mat)


func _build_star() -> void:
	_surface_mat = _shader_mat(SH_STAR)
	_surface = _mesh_instance(_sphere_hi, _surface_mat)
	_glow_mat = _shader_mat(SH_GLOW)
	_glow_mat.set_shader_parameter("rays", 0.6)
	_glow_mat.set_shader_parameter("falloff", 4.5)
	_glow = _mesh_instance(_quad, _glow_mat)
	_glow.custom_aabb = BIG_AABB
	light = OmniLight3D.new()
	light.omni_range = 9000.0
	light.omni_attenuation = 0.5
	light.light_specular = 0.3
	light.shadow_enabled = false
	light.visible = false
	_visual_root.add_child(light)
	_update_star_colors()


func _build_neutron() -> void:
	_surface_mat = _shader_mat(SH_STAR)
	_surface_mat.set_shader_parameter("star_color", Color(0.75, 0.88, 1.0))
	_surface_mat.set_shader_parameter("intensity", 9.0)
	_surface = _mesh_instance(_sphere_hi, _surface_mat)
	_glow_mat = _shader_mat(SH_GLOW)
	_glow_mat.set_shader_parameter("color", Color(0.55, 0.75, 1.0))
	_glow_mat.set_shader_parameter("intensity", 2.5)
	_glow_mat.set_shader_parameter("core", 1.0)
	_glow_mat.set_shader_parameter("falloff", 7.0)
	_glow = _mesh_instance(_quad, _glow_mat)
	_glow.custom_aabb = BIG_AABB
	# Pulsar beams, tilted from the spin axis and swept round as it rotates.
	_beams = Node3D.new()
	_visual_root.add_child(_beams)
	var tilted := Node3D.new()
	tilted.rotation = Vector3(0.0, 0.0, 0.45)
	_beams.add_child(tilted)
	for dir in [1.0, -1.0]:
		var m := _shader_mat(SH_BEAM)
		m.set_shader_parameter("color", Color(0.6, 0.82, 1.0))
		m.set_shader_parameter("intensity", 2.0)
		var b := _mesh_instance(_cone, m, tilted)
		b.custom_aabb = AABB(Vector3(-1, -0.5, -1), Vector3(2, 1, 2))
		b.set_meta("dir", dir)
		_beam_mats.append(m)
	light = OmniLight3D.new()
	light.omni_range = 4000.0
	light.omni_attenuation = 0.8
	light.light_color = Color(0.7, 0.85, 1.0)
	light.light_energy = 3.0
	light.visible = false
	_visual_root.add_child(light)


func _build_black_hole() -> void:
	# Accretion disk (opaque, so the lens can bend it), tilted per body.
	_disk_mat = _shader_mat(SH_DISK)
	_disk = _mesh_instance(_annulus, _disk_mat)
	_disk.rotation = Vector3((Palette.hash01(id, 21) - 0.5) * 0.5, Palette.hash01(id, 22) * TAU, (Palette.hash01(id, 23) - 0.5) * 0.5)
	# Relativistic jets along the disk axis (only visible while feeding).
	_jets = Node3D.new()
	_jets.rotation = _disk.rotation
	_visual_root.add_child(_jets)
	for dir in [1.0, -1.0]:
		var m := _shader_mat(SH_BEAM)
		m.set_shader_parameter("color", Color(0.65, 0.55, 1.0))
		m.set_shader_parameter("intensity", 0.0)
		m.render_priority = 1  # draw over the lens so the jets start at the hole
		var j := _mesh_instance(_cone, m, _jets)
		j.custom_aabb = AABB(Vector3(-1, -0.5, -1), Vector3(2, 1, 2))
		j.set_meta("dir", dir)
		_jet_mats.append(m)
	# Gravitational lens + shadow + photon ring.
	_lens_mat = ShaderMaterial.new()
	_lens_mat.shader = SH_LENS
	_lens = _mesh_instance(_quad, _lens_mat)
	_lens.custom_aabb = BIG_AABB


func _build_asteroid() -> void:
	_surface_mat = _shader_mat(SH_ROCK)
	var g := 0.35 + 0.25 * Palette.hash01(id, 9)
	_surface_mat.set_shader_parameter("base_color", Color(g * 1.05, g, g * 0.92))
	_surface = _mesh_instance(_sphere_lo, _surface_mat)
	_surface.rotation = Vector3(Palette.hash01(id, 1), Palette.hash01(id, 2), Palette.hash01(id, 3)) * TAU


func _build_plasma() -> void:
	_glow_mat = _shader_mat(SH_GLOW)
	_glow_mat.set_shader_parameter("falloff", 5.0)
	_glow = _mesh_instance(_quad, _glow_mat)
	_glow.custom_aabb = BIG_AABB


func _build_marker() -> void:
	_marker_mat = ShaderMaterial.new()
	_marker_mat.shader = SH_MARKER
	var c: Color = Palette.TYPE_COLORS[body_type]
	_marker_mat.set_shader_parameter("color", c)
	_marker = _mesh_instance(_quad, _marker_mat)
	_marker.custom_aabb = AABB(Vector3(-1e5, -1e5, -1e5), Vector3(2e5, 2e5, 2e5))
	if body_type == Palette.BLACK_HOLE:
		_marker_mat.set_shader_parameter("px_size", 11.0)
	elif body_type == Palette.STAR:
		_marker_mat.set_shader_parameter("px_size", 12.0)
		_marker_mat.set_shader_parameter("boost", 1.6)
	elif body_type in [Palette.ASTEROID, Palette.PLASMA]:
		_marker_mat.set_shader_parameter("px_size", 5.0)
		_marker_mat.set_shader_parameter("boost", 0.6)


func set_physical(m: float, r: float, h: float, a: float) -> void:
	mass = m
	age = a
	physical_radius = r
	if absf(h - _last_heat) > 0.02 or (h == 0.0 and _last_heat != 0.0):
		heat = h
		_last_heat = h
		if _surface_mat != null and body_type in [Palette.ROCKY, Palette.GAS_GIANT, Palette.ASTEROID]:
			_surface_mat.set_shader_parameter("heat", h)
		if body_type == Palette.PLASMA:
			_update_plasma()
	if body_type == Palette.STAR and absf(m - _last_color_mass) > 0.005 * maxf(m, 1e-6):
		_update_star_colors()


func set_display_size(enlargement: float, world_per_px: float) -> void:
	var r := Palette.rendered_radius(body_type, mass, physical_radius, enlargement, world_per_px)
	if absf(r - rendered_radius) > 1e-4 * maxf(r, 1e-12):
		rendered_radius = r
		_apply_radius()


func _update_star_colors() -> void:
	_last_color_mass = mass if mass > 0.0 else 1000.0
	var c := Palette.star_color(_last_color_mass)
	var lum := clampf(pow(_last_color_mass / 1000.0, 0.8), 0.3, 6.0)
	if _surface_mat != null:
		_surface_mat.set_shader_parameter("star_color", c)
		_surface_mat.set_shader_parameter("intensity", 3.2 + 1.2 * sqrt(lum))
	if _glow_mat != null:
		_glow_mat.set_shader_parameter("color", c)
		_glow_mat.set_shader_parameter("intensity", 1.1 + 0.4 * sqrt(lum))
	if light != null:
		light.light_color = c
		light.light_energy = 11.0 * lum


func _update_plasma() -> void:
	var hot := Color(1.0, 0.85, 0.65)
	var warm := Color(1.0, 0.45, 0.2)
	var cool := Color(0.75, 0.8, 1.0)
	var c: Color
	if heat > 0.02:
		c = warm.lerp(hot, clampf(heat, 0.0, 1.0))
	else:
		c = cool.lerp(Color(1.0, 0.9, 0.75), Palette.hash01(id, 4) * 0.6)
	_glow_mat.set_shader_parameter("color", c)
	_glow_mat.set_shader_parameter("intensity", 0.9 + 2.5 * heat)
	_glow_mat.set_shader_parameter("core", 0.6 + heat)


func _apply_radius() -> void:
	var r := rendered_radius
	match body_type:
		Palette.STAR:
			_surface.scale = Vector3.ONE * r
			_glow.scale = Vector3.ONE * r * 3.2
		Palette.NEUTRON_STAR:
			_surface.scale = Vector3.ONE * r
			_glow.scale = Vector3.ONE * r * 9.0
			for b in _beams.get_child(0).get_children():
				var mi := b as MeshInstance3D
				var d: float = mi.get_meta("dir")
				var length := r * 60.0
				mi.scale = Vector3(r * 6.0, length, r * 6.0)
				mi.position = Vector3(0, d * length * 0.5, 0)
				mi.rotation = Vector3(0.0 if d > 0 else PI, 0, 0)
		Palette.BLACK_HOLE:
			_disk.scale = Vector3.ONE * r * 8.0
			_lens.scale = Vector3.ONE * r * 10.0
			for j in _jets.get_children():
				var mi := j as MeshInstance3D
				var d: float = mi.get_meta("dir")
				var length := r * 30.0
				mi.scale = Vector3(r * 2.2, length, r * 2.2)
				mi.position = Vector3(0, d * length * 0.5, 0)
				mi.rotation = Vector3(0.0 if d > 0 else PI, 0, 0)
		Palette.PLASMA:
			_glow.scale = Vector3.ONE * maxf(r * 5.0, 0.6)
			_update_plasma()
		_:
			if _surface != null:
				_surface.scale = Vector3.ONE * r
	if _marker_mat != null:
		var eff_r := r
		if body_type == Palette.BLACK_HOLE:
			eff_r = r * 6.0
		elif body_type == Palette.STAR:
			eff_r = r * 2.0
		_marker_mat.set_shader_parameter("body_radius", eff_r)


func pick_radius() -> float:
	## Radius used for mouse picking and the selection ring.
	match body_type:
		Palette.BLACK_HOLE: return rendered_radius * 4.0
		Palette.STAR: return rendered_radius * 1.3
		Palette.PLASMA: return maxf(rendered_radius * 3.0, 0.5)
	return rendered_radius


func add_flare(amount: float) -> void:
	flare = clampf(flare + amount, 0.0, 3.0)


func _process(delta: float) -> void:
	if body_type == Palette.NEUTRON_STAR and _beams != null:
		_beams.rotate(_spin_axis, delta * 9.0)
	elif body_type == Palette.BLACK_HOLE:
		flare = maxf(0.0, flare - delta * 0.6)
		if _disk_mat != null:
			_disk_mat.set_shader_parameter("flare", flare)
		var jet := clampf(flare, 0.0, 1.5) * 1.1
		for m in _jet_mats:
			m.set_shader_parameter("intensity", jet)
