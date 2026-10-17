extends Node3D
## One-off visual effects for physics events: flashes, debris bursts,
## shock waves, supernova shells and gravitational-wave ripples.
## These are purely cosmetic - the real fragments come from the physics server.

const Palette = preload("res://scripts/palette.gd")
const SH_GLOW := preload("res://shaders/glow_sprite.gdshader")
const SH_RING := preload("res://shaders/ring.gdshader")

var rig  # camera rig, for screen shake
var _dot_tex: GradientTexture2D
var _particle_mat: StandardMaterial3D
var _quad: QuadMesh
var _spark_mesh: QuadMesh
var _active := 0


func _ready() -> void:
	var grad := Gradient.new()
	grad.set_color(0, Color(1, 1, 1, 1))
	grad.set_color(1, Color(1, 1, 1, 0))
	grad.add_point(0.35, Color(1, 1, 1, 0.45))
	_dot_tex = GradientTexture2D.new()
	_dot_tex.gradient = grad
	_dot_tex.fill = GradientTexture2D.FILL_RADIAL
	_dot_tex.fill_from = Vector2(0.5, 0.5)
	_dot_tex.fill_to = Vector2(1.0, 0.5)
	_dot_tex.width = 64
	_dot_tex.height = 64

	_particle_mat = StandardMaterial3D.new()
	_particle_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_particle_mat.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	_particle_mat.vertex_color_use_as_albedo = true
	_particle_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_particle_mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	_particle_mat.albedo_texture = _dot_tex
	_particle_mat.albedo_color = Color(3.0, 3.0, 3.0, 1.0)
	_particle_mat.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED

	_quad = QuadMesh.new()
	_quad.size = Vector2(2, 2)
	_spark_mesh = QuadMesh.new()
	_spark_mesh.size = Vector2(1, 1)


func spawn_event(kind: int, pos: Vector3, magnitude: float, size: float) -> void:
	if _active > 60:
		return  # keep things sane during huge debris storms
	match kind:
		Palette.EV_MERGE:
			_flash(pos, Color(1.0, 0.7, 0.4), size * 2.5, 0.6 + magnitude, 0.6)
			_burst(pos, Color(1.0, 0.75, 0.4), Color(0.9, 0.25, 0.05), int(20 + 40 * magnitude), size * 0.6, size * 2.0, 1.2)
		Palette.EV_SHATTER:
			_flash(pos, Color(1.0, 0.85, 0.6), size * 6.0, 2.0 + magnitude, 1.0)
			_burst(pos, Color(1.0, 0.9, 0.6), Color(1.0, 0.3, 0.05), int(120 + 60 * magnitude), size * 0.5, size * 5.0, 2.2)
			_ring(pos, Color(1.0, 0.6, 0.3), size * 8.0, 1.6, 2.0)
			_light(pos, Color(1.0, 0.6, 0.3), 6.0 * magnitude, size * 40.0, 1.2)
			_shake_near(pos, 0.6 * magnitude, size)
		Palette.EV_SWALLOW:
			_flash(pos, Color(0.85, 0.6, 1.0), size * 2.0, 1.2 + magnitude, 0.8)
			_burst(pos, Color(1.0, 0.8, 0.95), Color(0.5, 0.2, 1.0), int(30 + 30 * magnitude), size * 0.3, size * 1.2, 1.0)
		Palette.EV_TIDAL:
			_flash(pos, Color(1.0, 0.8, 0.6), size * 2.0, 1.8, 1.0)
			_burst(pos, Color(1.0, 0.85, 0.6), Color(1.0, 0.35, 0.1), 220, size * 0.4, size * 2.5, 3.0)
			_ring(pos, Color(1.0, 0.7, 0.4), size * 5.0, 1.8, 1.5)
			_shake_near(pos, 0.5, size)
		Palette.EV_SUPERNOVA:
			_flash(pos, Color(1.0, 0.95, 0.85), size * 1.4, 3.5, 1.6)
			_flash(pos, Color(0.6, 0.75, 1.0), size * 3.0, 1.0, 3.5)
			_burst(pos, Color(1.0, 0.95, 0.8), Color(0.8, 0.25, 0.6), 400, size * 0.05, size * 3.0, 5.0)
			_ring(pos, Color(1.0, 0.75, 0.5), size * 5.0, 3.0, 3.0)
			_ring(pos, Color(0.55, 0.7, 1.0), size * 9.0, 4.5, 2.0)
			_light(pos, Color(1.0, 0.85, 0.7), 25.0, 20000.0, 2.5)
			_shake_near(pos, 2.0, size * 5.0)
		Palette.EV_IGNITION:
			_flash(pos, Color(1.0, 0.9, 0.6), size * 2.5, 4.0, 2.0)
			_ring(pos, Color(1.0, 0.85, 0.4), size * 4.0, 2.5, 2.0)
			_light(pos, Color(1.0, 0.85, 0.6), 12.0, 4000.0, 2.0)
		Palette.EV_COLLAPSE:
			_flash(pos, Color(0.8, 0.6, 1.0), size * 1.5, 4.0, 1.5)
			_ring(pos, Color(0.7, 0.5, 1.0), size * 3.0, 2.0, 2.5)
			_shake_near(pos, 1.0, size)
		Palette.EV_BH_MERGER:
			_flash(pos, Color(0.85, 0.85, 1.0), size * 0.6, 5.0, 2.0)
			for k in range(4):
				_ring(pos, Color(0.55, 0.7, 1.0), size * (1.5 + k * 0.8), 3.5 + k * 0.6, 1.2, k * 0.35)
			_shake_near(pos, 2.5, size)
		Palette.EV_KILONOVA:
			_flash(pos, Color(1.0, 0.85, 0.45), size * 1.5, 3.5, 1.6)
			_burst(pos, Color(1.0, 0.9, 0.5), Color(1.0, 0.55, 0.1), 300, size * 0.05, size * 2.5, 4.0)
			_ring(pos, Color(1.0, 0.8, 0.35), size * 4.0, 2.5, 2.5)
			_light(pos, Color(1.0, 0.8, 0.4), 30.0, 10000.0, 2.5)
			_shake_near(pos, 1.5, size)


func _track(node: Node3D, lifetime: float) -> void:
	add_child(node)
	_active += 1
	get_tree().create_timer(lifetime).timeout.connect(func():
		_active -= 1
		if is_instance_valid(node):
			node.queue_free())


func _flash(pos: Vector3, color: Color, size: float, intensity: float, duration: float) -> void:
	var m := ShaderMaterial.new()
	m.shader = SH_GLOW
	m.set_shader_parameter("color", color)
	m.set_shader_parameter("intensity", intensity)
	m.set_shader_parameter("core", 1.5)
	m.set_shader_parameter("falloff", 4.0)
	var mi := MeshInstance3D.new()
	mi.mesh = _quad
	mi.material_override = m
	mi.position = pos
	mi.scale = Vector3.ONE * maxf(size, 0.1) * 0.3
	mi.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_track(mi, duration + 0.1)
	var tw := mi.create_tween().set_parallel(true)
	tw.tween_property(mi, "scale", Vector3.ONE * maxf(size, 0.1), duration).set_trans(Tween.TRANS_EXPO).set_ease(Tween.EASE_OUT)
	tw.tween_method(func(v: float): m.set_shader_parameter("intensity", v), intensity, 0.0, duration).set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)


func _burst(pos: Vector3, c0: Color, c1: Color, amount: int, emit_radius: float, speed: float, lifetime: float) -> void:
	var p := CPUParticles3D.new()
	p.position = pos
	p.amount = clampi(amount, 8, 500)
	p.lifetime = lifetime
	p.one_shot = true
	p.explosiveness = 0.95
	p.randomness = 0.6
	p.local_coords = false
	p.emission_shape = CPUParticles3D.EMISSION_SHAPE_SPHERE
	p.emission_sphere_radius = maxf(emit_radius, 0.01)
	p.direction = Vector3.UP
	p.spread = 180.0
	p.gravity = Vector3.ZERO
	p.initial_velocity_min = speed * 0.25 / lifetime
	p.initial_velocity_max = speed / lifetime
	p.damping_min = speed * 0.1 / lifetime
	p.damping_max = speed * 0.4 / lifetime
	p.scale_amount_min = maxf(emit_radius, 0.05) * 0.4
	p.scale_amount_max = maxf(emit_radius, 0.05) * 1.4
	var ramp := Gradient.new()
	ramp.set_color(0, c0)
	ramp.set_color(1, Color(c1.r, c1.g, c1.b, 0.0))
	ramp.add_point(0.4, c1)
	p.color_ramp = ramp
	p.mesh = _spark_mesh
	p.material_override = _particle_mat
	p.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	p.emitting = true
	_track(p, lifetime + 0.5)


func _ring(pos: Vector3, color: Color, size: float, intensity: float, duration: float, delay := 0.0) -> void:
	var m := ShaderMaterial.new()
	m.shader = SH_RING
	m.set_shader_parameter("color", color)
	m.set_shader_parameter("intensity", intensity)
	m.set_shader_parameter("progress", 0.0)
	m.set_shader_parameter("thickness", 0.05)
	var mi := MeshInstance3D.new()
	mi.mesh = _quad
	mi.material_override = m
	mi.position = pos
	mi.scale = Vector3.ONE * maxf(size, 0.1)
	mi.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	mi.visible = delay <= 0.0
	_track(mi, duration + delay + 0.1)
	var tw := mi.create_tween()
	if delay > 0.0:
		tw.tween_interval(delay)
		tw.tween_callback(func(): mi.visible = true)
	tw.tween_method(func(v: float): m.set_shader_parameter("progress", v), 0.0, 1.0, duration).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)


func _light(pos: Vector3, color: Color, energy: float, light_range: float, duration: float) -> void:
	var l := OmniLight3D.new()
	l.position = pos
	l.light_color = color
	l.light_energy = energy
	l.omni_range = light_range
	l.omni_attenuation = 0.6
	_track(l, duration + 0.1)
	var tw := l.create_tween()
	tw.tween_property(l, "light_energy", 0.0, duration).set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)


func _shake_near(pos: Vector3, amount: float, size: float) -> void:
	if rig == null:
		return
	var d: float = rig.camera.global_position.distance_to(pos)
	var reach := maxf(size * 60.0, 50.0)
	if d < reach:
		rig.add_shake(amount * (1.0 - d / reach))
