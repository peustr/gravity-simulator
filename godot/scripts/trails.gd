extends MeshInstance3D
## Fading orbit trails for every body, drawn as one line mesh.

const Palette = preload("res://scripts/palette.gd")

const SAMPLE_INTERVAL := 1.0 / 25.0
const MODES := ["Off", "Short", "Long"]
const LENGTH_BY_MODE := [0, 70, 260]

var mode := 2
var _trails := {}           # id -> PackedVector3Array
var _timer := 0.0
var _mesh := ArrayMesh.new()
var _min_step := 0.1
var _ref_id := -1            # trails are drawn relative to this body (the one being followed)


func set_reference(id: int) -> void:
	if id != _ref_id:
		_ref_id = id
		_trails.clear()


func _ready() -> void:
	mesh = _mesh
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	mat.no_depth_test = false
	mat.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
	material_override = mat
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	custom_aabb = AABB(Vector3(-1e6, -1e6, -1e6), Vector3(2e6, 2e6, 2e6))


func cycle_mode() -> String:
	mode = (mode + 1) % MODES.size()
	if mode == 0:
		clear_all()
	return MODES[mode]


func clear_all() -> void:
	_trails.clear()
	_mesh.clear_surfaces()


func forget(id: int) -> void:
	_trails.erase(id)


func max_points(body_type: int) -> int:
	var n: int = LENGTH_BY_MODE[mode]
	if body_type in [Palette.ASTEROID, Palette.PLASMA]:
		return int(n / 6.0)
	return n


func update_trails(views: Dictionary, cam_distance: float, delta: float) -> void:
	if mode == 0:
		return
	_timer -= delta
	if _timer > 0.0:
		return
	_timer = SAMPLE_INTERVAL
	_min_step = cam_distance * 0.0015

	var ref := Vector3.ZERO
	if _ref_id >= 0 and views.has(_ref_id):
		ref = views[_ref_id].position
	var verts := PackedVector3Array()
	var cols := PackedColorArray()
	for id in views:
		var v = views[id]
		var limit := max_points(v.body_type)
		if limit < 2:
			continue
		var pts: PackedVector3Array = _trails.get(id, PackedVector3Array())
		if id == _ref_id:
			continue
		var p: Vector3 = v.position - ref
		if pts.is_empty() or pts[pts.size() - 1].distance_to(p) > _min_step:
			pts.append(p)
			while pts.size() > limit:
				pts.remove_at(0)
			_trails[id] = pts
		var n := pts.size()
		if n < 2:
			continue
		var base: Color = Palette.TYPE_COLORS[v.body_type]
		var strength := 0.9
		if v.body_type == Palette.ASTEROID:
			strength = 0.18
		elif v.body_type == Palette.PLASMA:
			strength = 0.4
		for k in range(n - 1):
			var a0 := pow(float(k) / n, 1.6) * strength
			var a1 := pow(float(k + 1) / n, 1.6) * strength
			verts.append(pts[k] + ref)
			verts.append(pts[k + 1] + ref)
			cols.append(Color(base.r, base.g, base.b, a0))
			cols.append(Color(base.r, base.g, base.b, a1))
		verts.append(pts[n - 1] + ref)
		verts.append(p + ref)
		cols.append(Color(base.r, base.g, base.b, strength))
		cols.append(Color(base.r, base.g, base.b, strength))

	# Forget trails of bodies that no longer exist.
	for id in _trails.keys():
		if not views.has(id):
			_trails.erase(id)

	_mesh.clear_surfaces()
	if verts.size() >= 2:
		var arrays := []
		arrays.resize(Mesh.ARRAY_MAX)
		arrays[Mesh.ARRAY_VERTEX] = verts
		arrays[Mesh.ARRAY_COLOR] = cols
		_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_LINES, arrays)
