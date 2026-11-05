extends Node3D
## Localized cosmetic flashes and rings. Material comes from the physics server.

const Palette = preload("res://scripts/palette.gd")
const SH_GLOW := preload("res://shaders/glow_sprite.gdshader")
const SH_RING := preload("res://shaders/ring.gdshader")

var rig  # camera rig, for screen shake
var _quad: QuadMesh
var _active := 0


func _ready() -> void:
	_quad = QuadMesh.new()
	_quad.size = Vector2(2, 2)


func spawn_event(kind: int, pos: Vector3, magnitude: float, size: float) -> void:
	if _active > 60:
		return  # keep things sane during huge debris storms
	match kind:
		Palette.EV_MERGE, Palette.EV_ACCRETION:
			_flash(pos, Color(1.0, 0.7, 0.4), size * 2.5, 0.6 + magnitude, 0.6)
		Palette.EV_SHATTER:
			_flash(pos, Color(1.0, 0.85, 0.6), size * 3.0, 1.0 + magnitude, 0.25)
			_ring(pos, Color(1.0, 0.6, 0.3), size * 8.0, 1.6, 2.0)
			_shake_near(pos, 0.6 * magnitude, size)
		Palette.EV_HIT_AND_RUN:
			_flash(pos, Color(1.0, 0.85, 0.6), size * 2.0, 0.6 + magnitude, 0.6)
		Palette.EV_EROSION:
			_flash(pos, Color(1.0, 0.75, 0.5), size * 3.0, 1.0 + magnitude, 0.8)
		Palette.EV_SWALLOW:
			_flash(pos, Color(0.85, 0.6, 1.0), size * 2.0, 1.2 + magnitude, 0.8)
		Palette.EV_TIDAL:
			_flash(pos, Color(1.0, 0.8, 0.6), size * 2.0, 1.8, 1.0)
			_ring(pos, Color(1.0, 0.7, 0.4), size * 5.0, 1.8, 1.5)
			_shake_near(pos, 0.5, size)
		Palette.EV_SUPERNOVA:
			_flash(pos, Color(1.0, 0.95, 0.85), size * 1.4, 3.5, 1.6)
			_flash(pos, Color(0.6, 0.75, 1.0), size * 3.0, 1.0, 3.5)
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
	intensity = minf(intensity, 1.0)
	var m := ShaderMaterial.new()
	m.shader = SH_GLOW
	m.set_shader_parameter("color", color)
	m.set_shader_parameter("intensity", intensity)
	m.set_shader_parameter("core", 0.2)
	m.set_shader_parameter("max_screen_radius", 0.12)
	m.set_shader_parameter("falloff", 4.0)
	var mi := MeshInstance3D.new()
	mi.mesh = _quad
	mi.material_override = m
	mi.position = pos
	mi.scale = Vector3.ONE * maxf(size, 1e-7) * 0.3
	mi.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_track(mi, duration + 0.1)
	var tw := mi.create_tween().set_parallel(true)
	tw.tween_property(mi, "scale", Vector3.ONE * maxf(size, 1e-7), duration).set_trans(Tween.TRANS_EXPO).set_ease(Tween.EASE_OUT)
	tw.tween_method(func(v: float): m.set_shader_parameter("intensity", v), intensity, 0.0, duration).set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)


func _ring(pos: Vector3, color: Color, size: float, intensity: float, duration: float, delay := 0.0) -> void:
	var m := ShaderMaterial.new()
	m.shader = SH_RING
	m.set_shader_parameter("color", color)
	m.set_shader_parameter("intensity", intensity)
	m.set_shader_parameter("progress", 0.0)
	m.set_shader_parameter("thickness", 0.05)
	m.set_shader_parameter("max_screen_radius", 0.2)
	var mi := MeshInstance3D.new()
	mi.mesh = _quad
	mi.material_override = m
	mi.position = pos
	mi.scale = Vector3.ONE * maxf(size, 1e-7)
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
