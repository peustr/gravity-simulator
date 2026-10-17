extends Node3D
## Gravity Simulator - main scene.
##
## Builds the scene in code, receives the physics state from the Python
## server (REBOUND), draws it smoothly at your screen's frame rate, and turns
## mouse/keyboard input into commands for the server.

const Palette = preload("res://scripts/palette.gd")
const BodyView = preload("res://scripts/body_view.gd")
const NetClient = preload("res://scripts/net_client.gd")
const CameraRig = preload("res://scripts/camera_rig.gd")
const Hud = preload("res://scripts/hud.gd")
const Trails = preload("res://scripts/trails.gd")
const Effects = preload("res://scripts/effects.gd")
const Placement = preload("res://scripts/placement.gd")
const SpaceGrid = preload("res://scripts/space_grid.gd")
const SH_STARFIELD := preload("res://shaders/starfield.gdshader")
const SH_RING := preload("res://shaders/ring.gdshader")

const DEFAULT_SPEED := 10.0
const SPEED_STEPS := [0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]
const HEADER := 10
const BODY := 12
const EVENT := 8
const MAX_LIGHTS := 6
const G := 1.0

var net
var rig
var hud
var trails
var effects
var placement
var grid
var env: Environment
var bodies_root: Node3D
var views := {}
var selection_ring: MeshInstance3D

# Timing
var sim_version := -1
var packet_time := 0.0
var display_time := 0.0
var server_speed := DEFAULT_SPEED
var paused := false
var perf := 1.0
var max_bodies := 600

# Interaction state
var tool := -1
var selected_id := -1
var follow_id := -1
var mouse_pos := Vector2.ZERO
var hover_point = null
var drag_active := false
var drag_start_screen := Vector2.ZERO
var drag_anchor := Vector3.ZERO
var drag_world := Vector3.ZERO

# Prediction
var pred_req := 0
var pred_applied := 0
var pred_timer := 0.0
var pred_key := ""
var pred_refresh := 0.0
var pred_rel := PackedVector3Array()
var pred_hit := false
var pred_attractor := -1
var pred_vel := Vector3.ZERO

var _light_timer := 0.0
var _stats_timer := 0.0
var _welcome_shown := false
var _first_state := true
var _auto := {}
var _auto_time := 0.0
var _auto_done := false
var _alive := 0.0


func _ready() -> void:
	_parse_cmdline()
	_setup_environment()
	bodies_root = Node3D.new()
	bodies_root.name = "Bodies"
	add_child(bodies_root)
	rig = CameraRig.new()
	rig.name = "CameraRig"
	add_child(rig)
	trails = Trails.new()
	add_child(trails)
	grid = SpaceGrid.new()
	add_child(grid)
	effects = Effects.new()
	effects.rig = rig
	add_child(effects)
	placement = Placement.new()
	add_child(placement)
	_make_selection_ring()
	hud = Hud.new()
	add_child(hud)
	net = NetClient.new()
	add_child(net)

	net.state_received.connect(_on_state)
	net.prediction_received.connect(_on_prediction)
	net.message_received.connect(_on_message)
	net.connection_changed.connect(_on_connection)
	hud.tool_selected.connect(_set_tool)
	hud.mass_changed.connect(func(_t, _m): pred_key = "")
	hud.pause_toggled.connect(_toggle_pause)
	hud.speed_step.connect(_speed_step)
	hud.preset_chosen.connect(_load_preset)
	hud.clear_requested.connect(func():
		net.send({"cmd": "clear"})
		trails.clear_all()
		_select(-1))
	hud.follow_requested.connect(_toggle_follow)
	hud.delete_requested.connect(_delete_selected)
	hud.supernova_requested.connect(_supernova_selected)
	hud.relaunch_requested.connect(func():
		net.retry_launch()
		hud.show_overlay(true, "Trying to start the physics server..."))
	rig.follow_broken.connect(func(): follow_id = -1)
	_update_hint()
	hud.set_connection("offline", "Physics offline")


func _parse_cmdline() -> void:
	# Optional: --preset=solar --screenshot=out.png --wait=4 --cam=dist,pitch,yaw
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--") and "=" in a:
			var kv: PackedStringArray = a.substr(2).split("=", true, 1)
			_auto[kv[0]] = kv[1]
		elif a.begins_with("--"):
			_auto[a.substr(2)] = "1"


func _setup_environment() -> void:
	var we := WorldEnvironment.new()
	env = Environment.new()
	env.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	var sky_mat := ShaderMaterial.new()
	sky_mat.shader = SH_STARFIELD
	sky.sky_material = sky_mat
	sky.radiance_size = Sky.RADIANCE_SIZE_64
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.05, 0.06, 0.09)
	env.ambient_light_energy = 1.0
	env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	env.tonemap_mode = Environment.TONE_MAPPER_ACES
	env.tonemap_exposure = 1.0
	env.tonemap_white = 6.0
	env.glow_enabled = true
	env.glow_intensity = 0.85
	env.glow_strength = 1.1
	env.glow_bloom = 0.03
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
	env.glow_hdr_threshold = 0.9
	env.glow_hdr_scale = 2.0
	var levels := [0.0, 0.7, 0.9, 1.0, 0.8, 0.6, 0.4]
	for i in range(levels.size()):
		env.set_glow_level(i, levels[i])
	we.environment = env
	add_child(we)


func _make_selection_ring() -> void:
	var quad := QuadMesh.new()
	quad.size = Vector2(2, 2)
	var m := ShaderMaterial.new()
	m.shader = SH_RING
	m.set_shader_parameter("color", Color(0.55, 0.8, 1.0))
	m.set_shader_parameter("progress", 0.88)
	m.set_shader_parameter("pulse", 1.0)
	m.set_shader_parameter("thickness", 0.025)
	m.set_shader_parameter("intensity", 1.6)
	selection_ring = MeshInstance3D.new()
	selection_ring.mesh = quad
	selection_ring.material_override = m
	selection_ring.custom_aabb = AABB(Vector3(-1, -1, -1), Vector3(2, 2, 2))
	selection_ring.visible = false
	add_child(selection_ring)


# =================================================================== network
func _on_connection(is_connected: bool) -> void:
	if is_connected:
		var info: Dictionary = net.server_info
		var detail := "Physics online"
		if info.has("rebound"):
			detail = "Physics online  ·  REBOUND %s  ·  %s" % [info.rebound, info.get("integrator", "IAS15")]
		hud.set_connection("online", detail)
		hud.show_overlay(false)
		if _auto.has("preset"):
			_load_preset(_auto["preset"])
			_auto.erase("preset")
	else:
		hud.set_connection("offline", "Physics offline")
		hud.show_overlay(true, net.launch_status)


func _on_message(msg: Dictionary) -> void:
	match msg.get("type", ""):
		"info":
			if net.connected:
				_on_connection(true)
		"preset":
			var cam: Dictionary = msg.get("camera", {})
			var f: Array = cam.get("focus", [0, 0, 0])
			rig.frame(Vector3(f[0], f[1], f[2]), float(cam.get("distance", 400.0)), float(cam.get("pitch", 0.6)))
			trails.clear_all()
			_select(-1)
			follow_id = -1
		"notice":
			hud.push_event(str(msg.get("text", "")), Color(1.0, 0.85, 0.5))


func _max_tau() -> float:
	return maxf(server_speed * 0.35, 0.05)


func _on_state(f: PackedFloat32Array) -> void:
	if not NetClient.valid_packet(f) or f[0] != 1.0:
		return
	var n := int(f[4])
	var ne := int(f[5])
	if f.size() < HEADER + n * BODY + ne * EVENT:
		return
	paused = f[6] > 0.5
	server_speed = f[7]
	perf = f[8]
	max_bodies = int(f[9])

	# Events first, while the bodies involved still have their views.
	var eo := HEADER + n * BODY
	for k in range(ne):
		var o := eo + k * EVENT
		_on_event(int(f[o]), Vector3(f[o + 1], f[o + 2], f[o + 3]), f[o + 4], f[o + 5], int(f[o + 6]), int(f[o + 7]))

	if not _welcome_shown and net.connected:
		_welcome_shown = true
		if n == 0 and not _auto.has("preset") and (not _auto.has("screenshot") or _auto.has("welcome")):
			hud.show_welcome(true)

	var version := int(f[1])
	if version == sim_version:
		return
	sim_version = version
	var t := float(f[2]) + float(f[3])
	if _first_state or t < packet_time - 1.0:
		display_time = t
		_first_state = false
	packet_time = t
	display_time = clampf(display_time, t, t + _max_tau())
	var tau := display_time - packet_time

	var seen := {}
	var heavy: Array = []
	for i in range(n):
		var o := HEADER + i * BODY
		var id := int(f[o])
		var btype := int(f[o + 1])
		var pos := Vector3(f[o + 2], f[o + 3], f[o + 4])
		var view = views.get(id)
		var is_new := view == null
		if is_new:
			view = BodyView.new()
			bodies_root.add_child(view)
			view.setup(id, btype)
			view.position = pos
			views[id] = view
		elif view.body_type != btype:
			view.set_type(btype)
		view.set_meta("old_render", view.position)
		view.set_meta("is_new", is_new)
		view.base_pos = pos
		view.vel = Vector3(f[o + 5], f[o + 6], f[o + 7])
		view.set_physical(f[o + 8], f[o + 9], f[o + 10], f[o + 11])
		seen[id] = true
		if view.mass > 0.0:
			heavy.append(view)

	# Bodies the server no longer reports have merged, broken up or escaped.
	for id in views.keys():
		if not seen.has(id):
			_remove_view(id)

	# Accelerations from the heaviest bodies let us draw smooth curved motion
	# between physics updates (x + v t + a t^2 / 2).
	heavy.sort_custom(func(a, b): return a.mass > b.mass)
	if heavy.size() > 10:
		heavy.resize(10)
	var max_jump: float = rig.distance * 0.15
	for id in views:
		var v = views[id]
		var acc := Vector3.ZERO
		for h in heavy:
			if h == v:
				continue
			var d: Vector3 = h.base_pos - v.base_pos
			var soft: float = h.radius * h.radius
			var r2 := d.length_squared() + soft
			acc += d * (G * h.mass / (r2 * sqrt(r2)))
		v.acc = acc
		var predicted: Vector3 = v.base_pos + v.vel * tau + 0.5 * acc * tau * tau
		if v.get_meta("is_new"):
			v.offset = Vector3.ZERO
			v.position = predicted
		else:
			var off: Vector3 = v.get_meta("old_render") - predicted
			v.offset = off if off.length() < max_jump else Vector3.ZERO



func _remove_view(id: int) -> void:
	var v = views[id]
	views.erase(id)
	trails.forget(id)
	v.queue_free()
	if id == selected_id:
		_select(-1)
	if id == follow_id:
		follow_id = -1
		rig.following = false


func _on_event(kind: int, pos: Vector3, magnitude: float, size: float, a: int, b: int) -> void:
	effects.spawn_event(kind, pos, magnitude, size)
	# Keep following / inspecting the survivor of a merger.
	if kind in [Palette.EV_MERGE, Palette.EV_SHATTER, Palette.EV_SWALLOW]:
		if b == follow_id and a >= 0:
			follow_id = a
		if b == selected_id and a >= 0:
			selected_id = a
	if views.has(a) and views[a].body_type == Palette.BLACK_HOLE:
		if kind == Palette.EV_SWALLOW:
			views[a].add_flare(0.08 * magnitude)
		elif kind == Palette.EV_TIDAL:
			views[a].add_flare(1.0)
		elif kind == Palette.EV_BH_MERGER:
			views[a].add_flare(2.5)
	var msg := _event_text(kind, a, b)
	if msg.size() == 2:
		hud.push_event(msg[0], msg[1])


func _name_of(id: int) -> String:
	return views[id].display_name if views.has(id) else ""


func _type_of(id: int) -> int:
	return views[id].body_type if views.has(id) else -1


func _event_text(kind: int, a: int, b: int) -> Array:
	var na := _name_of(a)
	var nb := _name_of(b)
	var tb := _type_of(b)
	var small := tb in [Palette.ASTEROID, Palette.PLASMA, -1]
	match kind:
		Palette.EV_MERGE:
			if small or na == "" or _type_of(a) in [Palette.ASTEROID, Palette.PLASMA]:
				return []
			return ["%s and %s merged into one body" % [na, nb], Color(0.85, 0.9, 1.0)]
		Palette.EV_SHATTER:
			if na != "" and nb != "" and not small:
				return ["Catastrophic impact! %s and %s shattered" % [na, nb], Color(1.0, 0.65, 0.4)]
			return ["Catastrophic impact - debris everywhere!", Color(1.0, 0.65, 0.4)]
		Palette.EV_SWALLOW:
			if small or na == "":
				return []
			if _type_of(a) == Palette.BLACK_HOLE:
				return ["%s fell into the black hole %s" % [nb, na], Color(0.8, 0.6, 1.0)]
			return ["%s was engulfed by %s" % [nb, na], Color(1.0, 0.8, 0.55)]
		Palette.EV_TIDAL:
			if na == "" or nb == "":
				return ["A body was torn apart by tides!", Color(1.0, 0.7, 0.5)]
			return ["%s was torn apart by the tides of %s" % [nb, na], Color(1.0, 0.7, 0.5)]
		Palette.EV_SUPERNOVA:
			var rest := "A black hole was born." if b == 1 else "A neutron star remains."
			return ["%s went supernova! %s" % [na, rest], Color(1.0, 0.85, 0.6)]
		Palette.EV_IGNITION:
			return ["%s ignited - a new star is born!" % na, Color(1.0, 0.9, 0.5)]
		Palette.EV_COLLAPSE:
			return ["%s collapsed into a black hole" % na, Color(0.8, 0.6, 1.0)]
		Palette.EV_BH_MERGER:
			return ["Black holes merged! 5% of their mass left as gravitational waves", Color(0.6, 0.75, 1.0)]
		Palette.EV_KILONOVA:
			return ["Kilonova! Colliding neutron stars forge heavy elements like gold", Color(1.0, 0.85, 0.4)]
	return []


func _on_prediction(f: PackedFloat32Array) -> void:
	if not NetClient.valid_packet(f) or f[0] != 2.0:
		return
	var req := int(f[1])
	if req < pred_applied:
		return
	pred_applied = req
	var n := int(f[2])
	if f.size() < 8 + n * 3:
		return
	pred_hit = f[3] > 0.5
	pred_attractor = int(f[4])
	pred_vel = Vector3(f[5], f[6], f[7])
	var origin := Vector3.ZERO
	if views.has(pred_attractor):
		origin = views[pred_attractor].position
	pred_rel = PackedVector3Array()
	for k in range(n):
		var o := 8 + k * 3
		var p := Vector3(f[o], f[o + 1], f[o + 2])
		if not p.is_finite():
			break
		pred_rel.append(p - origin)


# =================================================================== frame loop
func _process(delta: float) -> void:
	_alive += delta
	if not paused and net.connected:
		display_time += delta * server_speed
	display_time = clampf(display_time, packet_time, packet_time + _max_tau())
	var tau := display_time - packet_time
	var decay := exp(-delta / 0.12)
	for id in views:
		var v = views[id]
		v.offset *= decay
		v.position = v.base_pos + v.vel * tau + 0.5 * v.acc * tau * tau + v.offset

	if follow_id >= 0 and views.has(follow_id):
		rig.target_focus = views[follow_id].position
		rig.following = true

	_update_selection_ring()
	_update_placement(delta)
	trails.set_reference(follow_id if views.has(follow_id) else -1)
	trails.update_trails(views, rig.distance, delta)
	grid.placing = tool >= 0
	grid.update_grid(rig.target_focus, rig.distance, views, delta)

	_light_timer -= delta
	if _light_timer <= 0.0:
		_light_timer = 0.5
		_assign_lights()

	_stats_timer -= delta
	if _stats_timer <= 0.0:
		_stats_timer = 0.2
		hud.set_stats(display_time, views.size(), max_bodies, server_speed / DEFAULT_SPEED, paused, perf)
		_update_inspector()
		if not net.connected and _alive > 1.6:
			var why: String = net.launch_status
			if why == "":
				why = "Looking for the physics server on this computer..."
			hud.show_overlay(true, why)
			hud.show_welcome(false)

	_run_auto(delta)


func _assign_lights() -> void:
	var stars := []
	for id in views:
		var v = views[id]
		if v.light != null:
			stars.append(v)
	stars.sort_custom(func(a, b): return a.mass > b.mass)
	for i in range(stars.size()):
		stars[i].light.visible = i < MAX_LIGHTS


func _update_selection_ring() -> void:
	if selected_id >= 0 and views.has(selected_id):
		var v = views[selected_id]
		selection_ring.visible = true
		selection_ring.position = v.position
		var min_world := _world_per_px(v.position) * 14.0
		selection_ring.scale = Vector3.ONE * maxf(v.pick_radius() * 1.6, min_world)
	else:
		selection_ring.visible = false


func _world_per_px(p: Vector3) -> float:
	var cam: Camera3D = rig.camera
	var dist := cam.global_position.distance_to(p)
	var h := get_viewport().get_visible_rect().size.y
	return 2.0 * dist * tan(deg_to_rad(cam.fov) * 0.5) / maxf(h, 1.0)


# =================================================================== placement
func _plane_point(screen: Vector2):
	var ray: Array = rig.screen_ray(screen)
	var o: Vector3 = ray[0]
	var d: Vector3 = ray[1]
	var plane_y: float = rig.target_focus.y
	if absf(d.y) < 1e-5:
		return null
	var t := (plane_y - o.y) / d.y
	if t <= 0.0:
		return null
	t = minf(t, rig.distance * 8.0)
	return o + d * t


func _update_placement(delta: float) -> void:
	if tool < 0 or not net.connected:
		placement.hide_all()
		hud.set_cursor_text("", mouse_pos)
		return
	hover_point = _plane_point(mouse_pos)
	var anchor = drag_anchor if drag_active else hover_point
	if anchor == null:
		placement.hide_all()
		hud.set_cursor_text("", mouse_pos)
		return
	var mult: float = hud.mass_mult(tool)
	var mass: float = Palette.DEFAULT_MASS[tool] * mult
	var r := Palette.radius_for(tool, mass)
	placement.set_ghost(anchor, r, tool)

	var launching := false
	if drag_active:
		var cur = _plane_point(mouse_pos)
		if cur != null:
			drag_world = cur - drag_anchor
		launching = mouse_pos.distance_to(drag_start_screen) > 6.0
	placement.set_arrow(anchor, anchor + drag_world, launching)

	var belt := tool == Palette.ASTEROID and Input.is_key_pressed(KEY_SHIFT) and not launching
	# Ask the server (REBOUND) to forecast the path, a few times per second.
	pred_timer -= delta
	pred_refresh -= delta
	var mode := "launch" if launching else "orbit"
	var key := "%d|%s|%.2f,%.2f,%.2f|%.2f,%.2f,%.2f|%.3f" % [tool, mode, anchor.x, anchor.y, anchor.z, drag_world.x, drag_world.y, drag_world.z, mult]
	if pred_timer <= 0.0 and (key != pred_key or pred_refresh <= 0.0) and not belt:
		pred_key = key
		pred_timer = 0.06
		pred_refresh = 0.4
		pred_req += 1
		net.send({"cmd": "predict", "req": pred_req, "type": Palette.TYPE_KEYS[tool],
			"pos": [anchor.x, anchor.y, anchor.z], "mode": mode,
			"drag": [drag_world.x, drag_world.y, drag_world.z], "mass_mult": mult})

	# Draw the forecast relative to the (moving) attractor.
	var origin := Vector3.ZERO
	var have_attr: bool = views.has(pred_attractor)
	if have_attr:
		origin = views[pred_attractor].position
	var pts := PackedVector3Array()
	if not belt:
		pts.resize(pred_rel.size())
		for k in range(pred_rel.size()):
			pts[k] = pred_rel[k] + origin
		if pts.size() > 0:
			pts[0] = anchor
	placement.set_path(pts, pred_hit and not belt)
	placement.set_impact_scale(_world_per_px(anchor) * 12.0)
	if have_attr:
		var av = views[pred_attractor]
		placement.set_attractor(av.position, maxf(av.pick_radius() * 1.5, _world_per_px(av.position) * 16.0), true)
	else:
		placement.set_attractor(Vector3.ZERO, 1.0, false)
	placement.redraw()

	# Cursor caption
	var text := ""
	var col := Color(1, 0.95, 0.8)
	if belt:
		text = "Asteroid belt around %s" % (_name_of(pred_attractor) if have_attr else "this point")
	elif have_attr:
		var av = views[pred_attractor]
		var d: float = anchor.distance_to(av.position)
		var v_circ := sqrt(G * (av.mass + mass) / maxf(d, 1e-6))
		if launching:
			var rel_speed: float = (pred_vel - av.vel).length()
			text = "Launch at %.1fx orbital speed" % (rel_speed / maxf(v_circ, 1e-9))
		else:
			text = "Orbit %s" % av.display_name
		if pred_hit:
			text += "  -  collision course!"
			col = Color(1.0, 0.6, 0.5)
	else:
		text = "Launch" if launching else "Place at rest"
	hud.set_cursor_text(text, mouse_pos, col)


func _place_body() -> void:
	if tool < 0 or not net.connected:
		return
	var mult: float = hud.mass_mult(tool)
	var p := drag_anchor
	var launching := mouse_pos.distance_to(drag_start_screen) > 6.0
	if tool == Palette.ASTEROID and Input.is_key_pressed(KEY_SHIFT) and not launching:
		net.send({"cmd": "belt", "pos": [p.x, p.y, p.z], "count": 80, "mass_mult": mult})
	elif launching:
		net.send({"cmd": "add", "type": Palette.TYPE_KEYS[tool], "pos": [p.x, p.y, p.z], "mode": "launch",
			"drag": [drag_world.x, drag_world.y, drag_world.z], "mass_mult": mult})
	else:
		net.send({"cmd": "add", "type": Palette.TYPE_KEYS[tool], "pos": [p.x, p.y, p.z], "mode": "orbit", "mass_mult": mult})
	pred_key = ""
	hud.show_welcome(false)


# =================================================================== input
func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		mouse_pos = (event as InputEventMouseMotion).position
	elif event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		mouse_pos = mb.position
		if mb.button_index == MOUSE_BUTTON_LEFT and not mb.alt_pressed:
			if mb.pressed:
				hud.show_welcome(false)
				hud.hide_help()
				if tool < 0:
					var hit := _pick_body(mb.position)
					_select(hit)
					if hit >= 0 and mb.double_click:
						_start_follow(hit)
				elif _plane_point(mb.position) != null:
					drag_active = true
					drag_start_screen = mb.position
					drag_anchor = _plane_point(mb.position)
					drag_world = Vector3.ZERO
			elif drag_active:
				drag_active = false
				_place_body()
				drag_world = Vector3.ZERO
		elif mb.button_index == MOUSE_BUTTON_RIGHT and mb.pressed and drag_active:
			drag_active = false
			drag_world = Vector3.ZERO
	elif event is InputEventKey:
		var k := event as InputEventKey
		if not k.pressed or k.echo:
			return
		match k.keycode:
			KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6:
				hud.select_tool(Palette.TOOL_TYPES[k.keycode - KEY_1])
			KEY_Q:
				hud.select_tool(-1)
			KEY_ESCAPE:
				if hud.hide_help():
					pass
				elif drag_active:
					drag_active = false
					drag_world = Vector3.ZERO
				elif tool >= 0:
					hud.select_tool(-1)
				else:
					_select(-1)
			KEY_SPACE:
				_toggle_pause()
			KEY_MINUS, KEY_KP_SUBTRACT:
				_speed_step(-1)
			KEY_EQUAL, KEY_PLUS, KEY_KP_ADD:
				_speed_step(1)
			KEY_T:
				hud.toast("Trails: " + trails.cycle_mode())
			KEY_G:
				grid.always_on = not grid.always_on
				hud.toast("Gravity grid: " + ("on" if grid.always_on else "off"))
			KEY_H, KEY_F1:
				hud.toggle_help()
			KEY_TAB:
				hud.toggle_ui()
			KEY_F:
				_toggle_follow()
			KEY_DELETE, KEY_BACKSPACE:
				_delete_selected()
			KEY_N:
				_supernova_selected()
			KEY_R:
				_reset_view()
			KEY_F12:
				_save_screenshot()


func _pick_body(screen: Vector2) -> int:
	var cam: Camera3D = rig.camera
	var best := -1
	var best_score := INF
	for id in views:
		var v = views[id]
		if cam.is_position_behind(v.position):
			continue
		var sp := cam.unproject_position(v.position)
		var r_px: float = v.pick_radius() / _world_per_px(v.position)
		var tol := maxf(r_px, 10.0)
		var d := sp.distance_to(screen)
		if d <= tol:
			var score := d / tol - 0.001 * log(maxf(v.mass, 1e-12))
			if score < best_score:
				best_score = score
				best = id
	return best


func _set_tool(t: int) -> void:
	tool = t
	drag_active = false
	drag_world = Vector3.ZERO
	pred_key = ""
	pred_rel = PackedVector3Array()
	pred_attractor = -1
	if t >= 0:
		hud.show_welcome(false)
	_update_hint()


func _update_hint() -> void:
	if tool < 0:
		hud.set_hint("Click a body to inspect it  ·  double-click to follow  ·  keys 1-6 to create  ·  right-drag to rotate  ·  H for help")
	elif tool == Palette.ASTEROID:
		hud.set_hint("Click: place in orbit  ·  drag: launch  ·  Shift+click: asteroid belt or planetary ring  ·  Esc: back to Select")
	else:
		hud.set_hint("Click: place in orbit around the strongest pull  ·  drag: launch with the arrow  ·  right-drag: rotate  ·  Esc: back to Select")


func _select(id: int) -> void:
	selected_id = id
	_update_inspector()


func _start_follow(id: int) -> void:
	if not views.has(id):
		return
	follow_id = id
	rig.following = true
	var v = views[id]
	rig.target_distance = clampf(v.pick_radius() * 14.0, 6.0, 4000.0)


func _toggle_follow() -> void:
	if follow_id >= 0 and follow_id == selected_id:
		follow_id = -1
		rig.following = false
	elif selected_id >= 0:
		_start_follow(selected_id)
	_update_inspector()


func _delete_selected() -> void:
	if selected_id >= 0:
		net.send({"cmd": "remove", "id": selected_id})


func _supernova_selected() -> void:
	if selected_id >= 0 and views.has(selected_id) and views[selected_id].body_type == Palette.STAR:
		net.send({"cmd": "supernova", "id": selected_id})


func _toggle_pause() -> void:
	net.send({"cmd": "pause", "value": not paused})
	paused = not paused


func _speed_step(direction: int) -> void:
	var mult := server_speed / DEFAULT_SPEED
	var idx := 0
	var best := INF
	for i in range(SPEED_STEPS.size()):
		var d := absf(log(SPEED_STEPS[i]) - log(maxf(mult, 1e-6)))
		if d < best:
			best = d
			idx = i
	idx = clampi(idx + direction, 0, SPEED_STEPS.size() - 1)
	var new_speed: float = SPEED_STEPS[idx] * DEFAULT_SPEED
	net.send({"cmd": "speed", "value": new_speed})
	server_speed = new_speed
	hud.toast("Time speed x%s" % hud._fmt_mult(SPEED_STEPS[idx]))


func _load_preset(preset: String) -> void:
	net.send({"cmd": "preset", "name": preset})
	hud.show_welcome(false)
	hud.select_tool(-1)


func _reset_view() -> void:
	# Frame the heaviest bodies.
	var total := 0.0
	var c := Vector3.ZERO
	for id in views:
		var v = views[id]
		total += v.mass
		c += v.position * v.mass
	if total <= 0.0:
		rig.frame(Vector3.ZERO, 400.0, 0.6)
		return
	c /= total
	var extent := 50.0
	for id in views:
		var v = views[id]
		if v.mass > total * 1e-4:
			extent = maxf(extent, v.position.distance_to(c))
	follow_id = -1
	rig.frame(c, extent * 2.4, 0.6)


func _save_screenshot(path := "") -> void:
	var img := get_viewport().get_texture().get_image()
	if path == "":
		DirAccess.make_dir_recursive_absolute(OS.get_user_data_dir().path_join("screenshots"))
		path = OS.get_user_data_dir().path_join("screenshots/gravity_%s.png" % Time.get_datetime_string_from_system().replace(":", "-"))
	elif path.is_relative_path():
		# Relative to the repository root (the folder that contains godot/),
		# because Godot itself changes directory into the project folder.
		path = ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir().path_join(path)
	var base := path.get_base_dir()
	if base != "" and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	var err := img.save_png(path)
	if err != OK:
		push_error("Could not save screenshot to %s (error %d)" % [path, err])
		return
	if hud != null:
		hud.toast("Screenshot saved")
	print("Saved screenshot: ", path)


# =================================================================== inspector
func _update_inspector() -> void:
	if selected_id < 0 or not views.has(selected_id):
		hud.show_inspector({})
		return
	var v = views[selected_id]
	var info := {}
	info["name"] = v.display_name
	var tlabel: String = Palette.TYPE_LABELS[v.body_type]
	if v.body_type == Palette.STAR:
		var k := Palette.star_temperature(v.mass)
		tlabel = "%s-type star  ·  %d K" % [Palette.spectral_class(k), int(round(k / 100.0) * 100)]
	info["type"] = tlabel
	info["color"] = Palette.TYPE_COLORS[v.body_type]
	info["Mass"] = Palette.friendly_mass(v.mass, v.body_type)
	info["Radius"] = "%.2f" % v.radius
	info["Speed"] = "%.2f" % v.vel.length()
	# What is it orbiting? (the strongest pull, m / d^2)
	var best = null
	var best_s := 0.0
	for id in views:
		var o = views[id]
		if o == v or o.mass <= v.mass:
			continue
		var d2: float = o.position.distance_squared_to(v.position) + 1e-6
		var s: float = o.mass / d2
		if s > best_s:
			best_s = s
			best = o
	if best != null:
		info["Orbiting"] = best.display_name
		info["Distance"] = "%.1f" % best.position.distance_to(v.position)
	if v.heat > 0.05:
		info["Surface"] = "Molten (%d%%)" % int(v.heat * 100)
	info["Age"] = "%.0f" % v.age
	info["can_nova"] = v.body_type == Palette.STAR
	info["following"] = follow_id == selected_id
	hud.show_inspector(info)


# =================================================================== automation
func _run_auto(delta: float) -> void:
	## Command-line helpers for screenshots and testing, e.g.
	## godot --path . -- --preset=black_hole --wait=6 --screenshot=shot.png
	if _auto.is_empty() or _auto_done or (not net.connected and not _auto.has("offline_ok")):
		return
	_auto_time += delta
	if _auto.has("smoke") and views.size() > 0 and _auto_time > 2.0:
		print("Godot live state check PASSED")
		get_tree().quit()
		return
	if _auto.has("follow_type") and follow_id < 0 and _auto_time > 0.3:
		for id in views:
			if views[id].body_type == int(_auto["follow_type"]):
				_select(id)
				_start_follow(id)
				break
	if _auto.has("cam") and _auto_time > 0.5 and not _auto.has("_cam_set"):
		var c: PackedStringArray = str(_auto["cam"]).split(",")
		rig.target_distance = float(c[0])
		rig.distance = rig.target_distance
		if c.size() > 1:
			rig.target_pitch = float(c[1])
			rig.pitch = rig.target_pitch
		if c.size() > 2:
			rig.target_yaw = float(c[2])
			rig.yaw = rig.target_yaw
		_auto["_cam_set"] = "1"
	if _auto.has("pause_at") and _auto_time > float(_auto["pause_at"]) and not _auto.has("_paused"):
		_auto["_paused"] = "1"
		net.send({"cmd": "pause", "value": true})
	if _auto.has("grid") and not grid.always_on:
		grid.always_on = true
	if _auto.has("tool") and tool < 0 and _auto_time > 0.5:
		hud.select_tool(int(_auto["tool"]))
		mouse_pos = get_viewport().get_visible_rect().size * Vector2(0.62, 0.5)
	if _auto.has("nova_at") and _auto_time > float(_auto["nova_at"]) and not _auto.has("_nova"):
		_auto["_nova"] = "1"
		var biggest = null
		for id in views:
			if views[id].body_type == Palette.STAR and (biggest == null or views[id].mass > biggest.mass):
				biggest = views[id]
		if biggest != null:
			net.send({"cmd": "supernova", "id": biggest.id})
	if _auto.has("click") and _auto_time > 1.5 and not _auto.has("_clicked"):
		_auto["_clicked"] = "1"
		for pressed in [true, false]:
			var ev := InputEventMouseButton.new()
			ev.button_index = MOUSE_BUTTON_LEFT
			ev.pressed = pressed
			ev.position = mouse_pos
			Input.parse_input_event(ev)
	if _auto.has("keys") and _auto_time > 2.0 and not _auto.has("_keys"):
		_auto["_keys"] = "1"
		for key_name in str(_auto["keys"]).split(","):
			var ev := InputEventKey.new()
			ev.keycode = OS.find_keycode_from_string(key_name)
			ev.pressed = true
			Input.parse_input_event(ev)
	if _auto.has("select_type") and selected_id < 0:
		for id in views:
			if views[id].body_type == int(_auto["select_type"]):
				_select(id)
				break
	if _auto.has("screenshot") and _auto_time > float(_auto.get("wait", "3")):
		_auto_done = true
		if _auto.has("debug"):
			var list := views.values()
			list.sort_custom(func(a, b): return a.mass > b.mass)
			for v in list.slice(0, 6):
				print("  body ", v.id, " type ", v.body_type, " mass ", v.mass, " r ", v.radius, " pos ", v.position)
			print("  camera ", rig.camera.global_position, " focus ", rig.focus, " dist ", rig.distance)
		_save_screenshot(str(_auto["screenshot"]))
		if _auto.has("quit"):
			get_tree().quit()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST or what == NOTIFICATION_PREDELETE:
		if net != null and is_instance_valid(net):
			net.shutdown()
