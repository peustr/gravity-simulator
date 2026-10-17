extends Node3D
## Visual helpers while placing a new body: a ghost preview, the launch
## arrow, the predicted path (computed by REBOUND on the server) and a ring
## around the body it will orbit.

const Palette = preload("res://scripts/palette.gd")
const SH_RING := preload("res://shaders/ring.gdshader")

var _ghost: MeshInstance3D
var _ghost_mat: StandardMaterial3D
var _lines: MeshInstance3D
var _line_mesh := ImmediateMesh.new()
var _attractor_ring: MeshInstance3D
var _attractor_mat: ShaderMaterial
var _impact: MeshInstance3D
var _impact_mat: ShaderMaterial

var _path := PackedVector3Array()
var _hit := false
var _arrow_from := Vector3.ZERO
var _arrow_to := Vector3.ZERO
var _show_arrow := false
var _color := Color.WHITE


func _ready() -> void:
	var sphere := SphereMesh.new()
	sphere.radius = 1.0
	sphere.height = 2.0
	_ghost_mat = StandardMaterial3D.new()
	_ghost_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_ghost_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_ghost_mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	_ghost_mat.rim_enabled = false
	_ghost = MeshInstance3D.new()
	_ghost.mesh = sphere
	_ghost.material_override = _ghost_mat
	_ghost.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_ghost)

	var line_mat := StandardMaterial3D.new()
	line_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	line_mat.vertex_color_use_as_albedo = true
	line_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	line_mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	line_mat.no_depth_test = true
	_lines = MeshInstance3D.new()
	_lines.mesh = _line_mesh
	_lines.material_override = line_mat
	_lines.custom_aabb = AABB(Vector3(-1e6, -1e6, -1e6), Vector3(2e6, 2e6, 2e6))
	_lines.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(_lines)

	var quad := QuadMesh.new()
	quad.size = Vector2(2, 2)
	_attractor_mat = ShaderMaterial.new()
	_attractor_mat.shader = SH_RING
	_attractor_mat.set_shader_parameter("progress", 0.9)
	_attractor_mat.set_shader_parameter("pulse", 1.0)
	_attractor_mat.set_shader_parameter("thickness", 0.03)
	_attractor_mat.set_shader_parameter("intensity", 1.2)
	_attractor_ring = MeshInstance3D.new()
	_attractor_ring.mesh = quad
	_attractor_ring.material_override = _attractor_mat
	_attractor_ring.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	add_child(_attractor_ring)

	_impact_mat = ShaderMaterial.new()
	_impact_mat.shader = SH_RING
	_impact_mat.set_shader_parameter("color", Color(1.0, 0.25, 0.2))
	_impact_mat.set_shader_parameter("progress", 0.6)
	_impact_mat.set_shader_parameter("pulse", 1.0)
	_impact_mat.set_shader_parameter("thickness", 0.12)
	_impact_mat.set_shader_parameter("intensity", 2.5)
	_impact = MeshInstance3D.new()
	_impact.mesh = quad
	_impact.material_override = _impact_mat
	_impact.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	add_child(_impact)
	hide_all()


func hide_all() -> void:
	_ghost.visible = false
	_attractor_ring.visible = false
	_impact.visible = false
	_path = PackedVector3Array()
	_show_arrow = false
	_line_mesh.clear_surfaces()


func set_ghost(pos: Vector3, r: float, body_type: int) -> void:
	_color = Palette.TYPE_COLORS[body_type]
	_ghost.visible = true
	_ghost.position = pos
	var vis_r := r
	if body_type == Palette.BLACK_HOLE:
		vis_r = r * 2.6
	_ghost.scale = Vector3.ONE * vis_r
	var pulse := 0.25 + 0.1 * sin(Time.get_ticks_msec() / 200.0)
	_ghost_mat.albedo_color = Color(_color.r, _color.g, _color.b, pulse)


func set_arrow(from: Vector3, to: Vector3, show_it: bool) -> void:
	_arrow_from = from
	_arrow_to = to
	_show_arrow = show_it


func set_path(points: PackedVector3Array, hit: bool) -> void:
	_path = points
	_hit = hit
	if hit and points.size() > 0:
		_impact.visible = true
		_impact.position = points[points.size() - 1]
	else:
		_impact.visible = false


func set_attractor(pos: Vector3, r: float, visible_ring: bool) -> void:
	_attractor_ring.visible = visible_ring
	if visible_ring:
		_attractor_ring.position = pos
		_attractor_ring.scale = Vector3.ONE * r
		_attractor_mat.set_shader_parameter("color", Color(0.6, 0.8, 1.0))


func set_impact_scale(s: float) -> void:
	_impact.scale = Vector3.ONE * s


func redraw() -> void:
	_line_mesh.clear_surfaces()
	var have_path := _path.size() >= 2
	if not have_path and not _show_arrow:
		return
	_line_mesh.surface_begin(Mesh.PRIMITIVE_LINES)
	if have_path:
		var n := _path.size()
		var c := Color(0.75, 0.9, 1.0) if not _hit else Color(1.0, 0.55, 0.4)
		for k in range(n - 1):
			# dashed: skip every third segment, fade towards the end
			if k % 3 == 2:
				continue
			var a := 0.9 * (1.0 - 0.75 * float(k) / n)
			_line_mesh.surface_set_color(Color(c.r, c.g, c.b, a))
			_line_mesh.surface_add_vertex(_path[k])
			_line_mesh.surface_set_color(Color(c.r, c.g, c.b, a))
			_line_mesh.surface_add_vertex(_path[k + 1])
	if _show_arrow:
		var col := Color(1.0, 0.9, 0.5, 1.0)
		var d := _arrow_to - _arrow_from
		var dl := d.length()
		if dl > 1e-4:
			_line_mesh.surface_set_color(col)
			_line_mesh.surface_add_vertex(_arrow_from)
			_line_mesh.surface_set_color(col)
			_line_mesh.surface_add_vertex(_arrow_to)
			var dir := d / dl
			var side := dir.cross(Vector3.UP)
			if side.length() < 1e-3:
				side = dir.cross(Vector3.RIGHT)
			side = side.normalized()
			var head := dl * 0.18
			for s in [1.0, -1.0]:
				_line_mesh.surface_set_color(col)
				_line_mesh.surface_add_vertex(_arrow_to)
				_line_mesh.surface_set_color(col)
				_line_mesh.surface_add_vertex(_arrow_to - dir * head + side * head * 0.5 * s)
	_line_mesh.surface_end()


func _process(_delta: float) -> void:
	if _ghost.visible:
		var pulse := 0.25 + 0.1 * sin(Time.get_ticks_msec() / 200.0)
		_ghost_mat.albedo_color = Color(_color.r, _color.g, _color.b, pulse)
