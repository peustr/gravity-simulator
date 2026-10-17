extends Node3D
## Orbit camera.
##   Right-drag (or Alt + left-drag)      orbit around the focus point
##   Middle-drag (or Shift + right-drag)  pan
##   Mouse wheel / touchpad pinch          zoom
##   W A S D / arrow keys                  pan / orbit with the keyboard

signal follow_broken

const MIN_DIST := 1.5
const MAX_DIST := 40000.0

var camera: Camera3D
var focus := Vector3.ZERO
var target_focus := Vector3.ZERO
var yaw := 0.5
var pitch := 0.55
var target_yaw := 0.5
var target_pitch := 0.55
var distance := 400.0
var target_distance := 400.0
var following := false
var _shake := 0.0
var _orbiting := false
var _panning := false
var _alt_orbit := false


func _ready() -> void:
	camera = Camera3D.new()
	camera.fov = 55.0
	camera.near = 0.05
	camera.far = 250000.0
	add_child(camera)
	camera.make_current()
	_apply()


func frame(p: Vector3, dist: float, new_pitch := NAN) -> void:
	target_focus = p
	target_distance = clampf(dist, MIN_DIST, MAX_DIST)
	if not is_nan(new_pitch):
		target_pitch = new_pitch
	following = false


func zoom(factor: float) -> void:
	target_distance = clampf(target_distance * factor, MIN_DIST, MAX_DIST)


func add_shake(amount: float) -> void:
	_shake = maxf(_shake, amount)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		match mb.button_index:
			MOUSE_BUTTON_RIGHT:
				if mb.pressed:
					if mb.shift_pressed:
						_panning = true
					else:
						_orbiting = true
				else:
					_orbiting = false
					_panning = false
			MOUSE_BUTTON_MIDDLE:
				_panning = mb.pressed
			MOUSE_BUTTON_LEFT:
				if mb.pressed and mb.alt_pressed:
					_orbiting = true
					_alt_orbit = true
					get_viewport().set_input_as_handled()
				elif not mb.pressed and _alt_orbit:
					_orbiting = false
					_alt_orbit = false
					get_viewport().set_input_as_handled()
			MOUSE_BUTTON_WHEEL_UP:
				if mb.pressed:
					zoom(pow(0.87, mb.factor if mb.factor > 0.0 else 1.0))
			MOUSE_BUTTON_WHEEL_DOWN:
				if mb.pressed:
					zoom(pow(1.0 / 0.87, mb.factor if mb.factor > 0.0 else 1.0))
	elif event is InputEventMouseMotion:
		var mm := event as InputEventMouseMotion
		if _orbiting:
			target_yaw -= mm.relative.x * 0.006
			target_pitch = clampf(target_pitch + mm.relative.y * 0.006, -1.52, 1.52)
		if _panning:
			_pan(mm.relative)
	elif event is InputEventPanGesture:
		zoom(pow(1.04, (event as InputEventPanGesture).delta.y))
	elif event is InputEventMagnifyGesture:
		zoom(1.0 / maxf((event as InputEventMagnifyGesture).factor, 0.01))


func _pan(rel: Vector2) -> void:
	var b := camera.global_transform.basis
	var s := distance * 0.0016
	target_focus += (-b.x * rel.x + b.y * rel.y) * s
	_break_follow()


func _break_follow() -> void:
	if following:
		following = false
		follow_broken.emit()


func _process(delta: float) -> void:
	# Keyboard: WASD pans along the ground plane, arrows orbit.
	if not _text_has_focus():
		var mv := Vector2.ZERO
		if Input.is_key_pressed(KEY_W): mv.y -= 1.0
		if Input.is_key_pressed(KEY_S): mv.y += 1.0
		if Input.is_key_pressed(KEY_A): mv.x -= 1.0
		if Input.is_key_pressed(KEY_D): mv.x += 1.0
		if mv != Vector2.ZERO:
			var fwd := Vector3(-sin(yaw), 0.0, -cos(yaw))
			var right := Vector3(cos(yaw), 0.0, -sin(yaw))
			target_focus += (right * mv.x + fwd * -mv.y) * distance * 0.9 * delta
			_break_follow()
		if Input.is_key_pressed(KEY_LEFT): target_yaw += 1.6 * delta
		if Input.is_key_pressed(KEY_RIGHT): target_yaw -= 1.6 * delta
		if Input.is_key_pressed(KEY_UP): target_pitch = clampf(target_pitch + 1.2 * delta, -1.52, 1.52)
		if Input.is_key_pressed(KEY_DOWN): target_pitch = clampf(target_pitch - 1.2 * delta, -1.52, 1.52)

	var k := 1.0 - exp(-delta * 10.0)
	yaw = lerpf(yaw, target_yaw, k)
	pitch = lerpf(pitch, target_pitch, k)
	distance = exp(lerpf(log(distance), log(target_distance), k))
	var kf := 1.0 - exp(-delta * (30.0 if following else 8.0))
	focus = focus.lerp(target_focus, kf)
	_shake = maxf(0.0, _shake - delta * 1.5)
	_apply()


func _apply() -> void:
	var offset := Vector3(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw)) * distance
	var shake_vec := Vector3.ZERO
	if _shake > 0.0:
		shake_vec = Vector3(randf_range(-1, 1), randf_range(-1, 1), randf_range(-1, 1)) * _shake * distance * 0.01
	camera.global_position = focus + offset + shake_vec
	camera.look_at(focus + shake_vec, Vector3.UP)


func _text_has_focus() -> bool:
	var f := get_viewport().gui_get_focus_owner()
	return f is LineEdit or f is TextEdit


func screen_ray(mouse: Vector2) -> Array:
	return [camera.project_ray_origin(mouse), camera.project_ray_normal(mouse)]
