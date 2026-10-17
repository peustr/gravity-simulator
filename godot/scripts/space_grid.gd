extends MeshInstance3D
## The optional "rubber sheet" gravity grid (toggle with G). It follows the
## camera and sags under the heaviest bodies nearby.

const SH_GRID := preload("res://shaders/space_grid.gdshader")

var always_on := false
var placing := false
var _mat := ShaderMaterial.new()
var _opacity := 0.0


func _ready() -> void:
	var plane := PlaneMesh.new()
	plane.size = Vector2(2, 2)
	plane.subdivide_width = 180
	plane.subdivide_depth = 180
	mesh = plane
	_mat.shader = SH_GRID
	material_override = _mat
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	custom_aabb = AABB(Vector3(-1, -1e5, -1), Vector3(2, 2e5, 2))
	visible = false


func update_grid(focus: Vector3, cam_distance: float, views: Dictionary, delta: float) -> void:
	var target := 1.0 if (always_on or placing) else 0.0
	_opacity = move_toward(_opacity, target, delta * 3.0)
	visible = _opacity > 0.001
	if not visible:
		return
	var spacing := pow(10.0, floor(log(cam_distance * 0.06) / log(10.0)))
	spacing = maxf(spacing, 0.1)
	if cam_distance * 0.06 / spacing > 5.0:
		spacing *= 5.0
	elif cam_distance * 0.06 / spacing > 2.0:
		spacing *= 2.0
	var half := cam_distance * 2.2
	var snap := spacing * 5.0
	global_position = Vector3(round(focus.x / snap) * snap, focus.y, round(focus.z / snap) * snap)
	scale = Vector3(half, 1.0, half)

	# The heaviest bodies (by influence at the focus) become gravity wells.
	var cands := []
	for id in views:
		var v = views[id]
		if v.mass <= 0.0:
			continue
		var d: float = maxf(v.position.distance_to(focus), cam_distance * 0.05)
		cands.append([v.mass / d, v])
	cands.sort_custom(func(a, b): return a[0] > b[0])
	var wells := PackedVector4Array()
	var max_m := 0.0
	for k in range(mini(16, cands.size())):
		var v = cands[k][1]
		wells.append(Vector4(v.position.x, v.position.y, v.position.z, v.mass))
		max_m = maxf(max_m, v.mass)
	while wells.size() < 16:
		wells.append(Vector4.ZERO)
	var soft := maxf(spacing * 0.8, 1.0)
	var depth_scale := 0.0
	if max_m > 0.0:
		depth_scale = cam_distance * 0.35 / (max_m / soft)
	_mat.set_shader_parameter("wells", wells)
	_mat.set_shader_parameter("well_count", mini(16, cands.size()))
	_mat.set_shader_parameter("depth_scale", depth_scale)
	_mat.set_shader_parameter("spacing", spacing)
	_mat.set_shader_parameter("center", global_position)
	_mat.set_shader_parameter("fade_radius", half)
	_mat.set_shader_parameter("opacity", _opacity)
