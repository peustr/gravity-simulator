extends SceneTree
## Exercise the real scene UI controller, UDP transport, and Python filesystem path.

const Main = preload("res://scripts/main.gd")
var main
var result := {}
var path: String
var accretion_snapshot: Image


func _initialize() -> void:
	_run.call_deferred()


func _fail(message: String) -> void:
	push_error(message)
	_finish(1)


func _finish(code: int) -> void:
	main.net.shutdown()
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)
	quit(code)


func _until(predicate: Callable, timeout_s := 7.5, context := "interaction") -> bool:
	var deadline := Time.get_ticks_usec() + int(timeout_s*1000000)
	while Time.get_ticks_usec() < deadline:
		if predicate.call():
			return true
		await create_timer(0.05).timeout
	push_error("Live check timed out (%s): bodies=%d, t=%s, paused=%s, follow=%d, online=%s, distance=%s, impact=%s" % [context,main.views.size(),str(main.packet_time),str(main.paused),main.follow_id,str(main.net.connected),str(main.rig.distance),str(main.hud.impact_panel.report.get("regime","none"))])
	return false


func _request(command: Dictionary) -> bool:
	result = {}
	main.scene_files.request(command)
	if not await _until(func(): return not result.is_empty()):
		return false
	return result.get("ok", false)


func _check_presets() -> bool:
	var forecasts: Array[PackedFloat32Array] = []
	var receive := func(packet: PackedFloat32Array): forecasts.append(packet)
	main.net.prediction_received.connect(receive)
	main.net.send({"cmd": "pause", "value": true})
	if not await _until(func(): return main.paused):
		return false
	for preset in ["solar", "binary", "black_hole", "smash", "formation", "galaxies", "empty"]:
		var previous_version: int = main.sim_version
		main.hud.preset_chosen.emit(preset)
		main.scene_files.confirm.get_ok_button().pressed.emit()
		if not await _until(func(): return main.sim_version > previous_version and main.packet_time == 0 and main.paused):
			push_error("Preset did not load: " + preset)
			return false
		if main.cloud_count != 0 or (main.views.is_empty() != (preset == "empty")):
			push_error("Preset retained stale bodies/clouds: " + preset)
			return false
		if not main.views.is_empty():
			var id: int = main.views.keys()[0]
			main._select(id)
			main._start_follow(id)
			if main.selected_id != id or main.follow_id != id or not main.hud.insp_values["Physical radius"].text.ends_with(" km"):
				push_error("Preset selection/follow failed: " + preset)
				return false
		main.hud.conservation_report = {}
		main.net.send({"cmd": "conservation"})
		if not await _until(func(): return not main.hud.conservation_report.is_empty()):
			return false
		if not main.hud.conservation_report.get("ok", false):
			return false
		main.hud.conservation_dialog.hide()
		forecasts.clear()
		main.net.send({"cmd": "predict", "req": 1000, "type": "rocky", "pos": [400, 50, 0], "mode": "orbit", "drag": [0, 0, 0]})
		if not await _until(func(): return not forecasts.is_empty()):
			return false
		if forecasts[0][1] != 1000 or not main.NetClient.valid_packet(forecasts[0]):
			push_error("Preset forecast failed: " + preset)
			return false
		main.net.send({"cmd": "pause", "value": false})
		if not await _until(func(): return main.packet_time > 0 and not main.paused):
			return false
		main.net.send({"cmd": "pause", "value": true})
		if not await _until(func(): return main.paused):
			return false
		print("Live preset controls PASSED: ", preset)
	main.net.prediction_received.disconnect(receive)
	return true


func _check_collision_demos() -> bool:
	var distance: float = main.rig.distance
	for zoom in [0.0001, 0.001, 0.04, 40000.0]:
		main.rig.distance = zoom
		main.rig._apply()
		for plane in main.rig.camera.get_frustum():
			if not plane.normal.is_finite() or plane.normal.length_squared() < 0.5:
				push_error("Camera frustum degenerated at close/wide zoom")
				return false
	main.rig.distance = distance
	main.rig._apply()
	if main.hud._fmt_mult(0.0005) != "0.0005" or main.hud._fmt_mult(0.000001) != "0.000001":
		return false
	var cases := ["merging", "hit_and_run", "disruption"]
	var regimes := ["merging", "hit_and_run", "supercatastrophic_disruption"]
	for i in range(cases.size()):
		main.hud.collision_menu.id_pressed.emit(i)
		main.scene_files.confirm.get_ok_button().pressed.emit()
		if not await _until(func(): return main.paused and main.views.size() == 2 and main.hud.impact_panel.demo.get("case") == cases[i]):
			return false
		if main.display_scale != 0 or main.rig.target_distance >= 1.5:
			push_error("Collision camera did not use physical close view: " + cases[i])
			return false
		main.net.send({"cmd": "pause", "value": false})
		if not await _until(func(): return main.hud.impact_panel.report.get("regime") == regimes[i]):
			push_error("Collision menu did not produce expected live outcome: " + cases[i])
			return false
		main.net.send({"cmd": "pause", "value": true})
		if not await _until(func(): return main.paused):
			return false
		if not main.hud.impact_panel.details.text.contains("kg"):
			push_error("Collision report omitted remnant masses: " + cases[i])
			return false
		var survivor: int = main.hud.impact_panel.report.get("survivor_id", -1)
		main.hud.impact_panel.inspect.pressed.emit()
		if not await _until(func(): return main.follow_id == survivor and main.selected_id == survivor and main.server_speed <= .005):
			return false
		if main.display_scale != 0 or main.rig.target_distance > 14.01*main.views[survivor].physical_radius:
			push_error("Inspect did not frame the physical remnant: " + cases[i])
			return false
		main.hud.conservation_report = {}
		main.hud.impact_panel.budgets_requested.emit()
		if not await _until(func(): return not main.hud.conservation_report.is_empty()):
			return false
		if absf(main.hud.conservation_report.relative_conservation_residual) > 1e-8:
			return false
		main.hud.conservation_dialog.hide()
		print("Live collision menu PASSED: ", cases[i])
	main.hud.impact_panel.replay.pressed.emit()
	main.scene_files.confirm.get_ok_button().pressed.emit()
	if not await _until(func(): return main.views.size() == 2 and main.packet_time < .015 and not main.paused):
		return false
	main.net.send({"cmd": "pause", "value": true})
	return await _until(func(): return main.paused)


func _largest_rocky() -> int:
	var best := -1
	for id in main.views:
		if main.views[id].body_type == main.Palette.ROCKY and (best < 0 or main.views[id].mass > main.views[best].mass):
			best = id
	return best


func _check_formation() -> bool:
	main.hud.preset_chosen.emit("formation")
	main.scene_files.confirm.get_ok_button().pressed.emit()
	if not await _until(func(): return main.views.size() == 65 and main.paused and main.follow_id == -1 and absf(log(main.rig.distance / 150.0)) < .01, 7.5, "formation load/camera"):
		return false
	var embryo: int = main.views.keys()[1]
	main._select(embryo)
	main._start_follow(embryo)
	var followed: int = main.follow_id
	if main.selected_id != followed:
		return false
	if main.display_scale != 0 or not await _request({"cmd": "checkpoint"}):
		return false
	var initial_max := 0.0
	for view in main.views.values():
		if view.body_type == main.Palette.ROCKY: initial_max = maxf(initial_max,view.mass)
	main.net.send({"cmd": "pause", "value": false})
	if not await _until(func(): return _largest_rocky() >= 0 and main.views[_largest_rocky()].mass > 2.0*initial_max, 45.0):
		push_error("Planet formation did not demonstrate natural growth from at least three embryos")
		return false
	main.net.send({"cmd": "pause", "value": true})
	if not await _until(func(): return main.paused, 7.5, "formation growth pause"):
		return false
	var grown := _largest_rocky()
	main._select(grown)
	main._start_follow(grown)
	main.net.send({"cmd":"speed", "value":.005})
	var remnant = main.views[grown]
	var count: int = main.views.size()
	var added_mass: float = .5*remnant.mass
	var added_radius: float = remnant.physical_radius * pow(added_mass/remnant.mass, 1.0/3.0)
	var contact_radius: float = remnant.physical_radius + added_radius
	var position: Vector3 = remnant.base_pos + Vector3(2.0*contact_radius, 0, 0)
	var initial_mass: float = remnant.mass
	main.net.send({"cmd":"add", "type":"rocky", "pos":[position.x,position.y,position.z],
		"mode":"launch", "drag":[-.3*contact_radius,0,0], "mass_mult":added_mass/.003})
	if not await _until(func(): return main.views.size() == count+1, 7.5, "formation placement"):
		return false
	main.net.send({"cmd":"pause","value":false})
	if not await _until(func(): return main.views.size() == count and main.views.has(grown) and main.views[grown].mass > initial_mass+.99*added_mass):
		push_error("Spinning formation remnant did not accept a subsequent bound accretion")
		return false
	if not await _until(func(): return main.hud.impact_panel.report.get("regime") in ["bound_sticking","gentle_sticking"], 7.5, "formation impact report"):
		return false
	main.net.send({"cmd":"pause","value":true})
	if not await _until(func(): return main.paused):
		return false
	main.hud.conservation_report = {}
	main.net.send({"cmd":"conservation"})
	if not await _until(func(): return not main.hud.conservation_report.is_empty()):
		return false
	var residual = main.hud.conservation_report.get("relative_conservation_residual")
	if residual == null or absf(float(residual)) > 1e-8:
		push_error("Formation accretion did not close physical budgets")
		return false
	main.hud.conservation_dialog.hide()
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		accretion_snapshot = root.get_texture().get_image()
	if not await _request({"cmd": "restart"}):
		return false
	if not await _until(func(): return main.views.size() == 65 and main.paused and main.follow_id == followed, 7.5, "formation restart/follow"):
		return false
	print("Live formation growth/follow/restart PASSED")
	return true


func _run() -> void:
	main = Main.new()
	root.add_child(main)
	path = OS.get_user_data_dir().path_join("scene-test-%s.gravity.json" % Time.get_ticks_usec())
	main.net.message_received.connect(func(msg: Dictionary):
		if msg.get("type") == "scene_result": result = msg)
	if not await _until(func(): return main.net.connected):
		_fail("Scene test: physics connection timed out")
		return
	var initial_time: float = main.packet_time
	if not await _until(func(): return main.packet_time > initial_time + 1.0):
		_fail("Empty sandbox clock did not advance")
		return
	main.net.send({"cmd": "pause", "value": true})
	if not await _until(func(): return main.paused):
		_fail("Empty sandbox did not pause")
		return
	var paused_time: float = main.packet_time
	await create_timer(0.2).timeout
	if main.packet_time != paused_time:
		_fail("Empty sandbox clock advanced while paused")
		return
	main.net.send({"cmd": "pause", "value": false})
	if not await _until(func(): return main.packet_time > paused_time + 0.5):
		_fail("Empty sandbox clock did not resume")
		return
	main.net.send({"cmd": "preset", "name": "binary"})
	main.net.send({"cmd": "pause", "value": true})
	if not await _until(func(): return main.views.size() == 6 and main.paused):
		_fail("Scene test: initial scene did not arrive")
		return
	if main.hud.physics_settings.get("collisions") != "auto":
		_fail("Preset did not enable automatic collision models")
		return
	main.hud.physics_menu.id_pressed.emit(15)
	if not await _until(func(): return not main.hud.conservation_report.is_empty()):
		_fail("Conservation report did not arrive")
		return
	if not main.hud.conservation_report.get("ok", false) or main.hud.conservation_report.current.bodies != 6:
		_fail("Conservation report lost the current scene")
		return
	if not "Internal energy" in main.hud.conservation_text.text:
		_fail("Conservation report omitted intrinsic energy")
		return
	main.hud.conservation_dialog.hide()
	main.hud.conservation_report = {}
	main.hud.physics_menu.id_pressed.emit(16)
	if not await _until(func(): return not main.hud.conservation_report.is_empty()):
		_fail("Conservation baseline reset did not arrive")
		return
	if main.hud.conservation_report.relative_energy_change != 0:
		_fail("Reset baseline retained an energy difference")
		return
	main.hud.conservation_dialog.hide()
	main.follow_id = 2
	main.selected_id = 2
	main._on_event(main.Palette.EV_HIT_AND_RUN, Vector3.ZERO, 1.0, 0.01, 1, 2)
	if main.follow_id != 2 or main.selected_id != 2:
		_fail("Hit-and-run switched focus away from the surviving runner")
		return
	if not "both bodies survived" in main._event_text(main.Palette.EV_HIT_AND_RUN, 1, 2)[0]:
		_fail("Hit-and-run was labelled as destruction")
		return
	main.follow_id = -1
	main.selected_id = -1
	main.hud.physics_menu.id_pressed.emit(10)
	if not await _until(func(): return main.hud.physics_settings.get("gravity") == "tracers"):
		_fail("Tracer comparison control did not reach the server")
		return
	main.hud.physics_menu.id_pressed.emit(10)
	if not await _until(func(): return main.hud.physics_settings.get("gravity") == "full"):
		_fail("Full gravity control did not reach the server")
		return
	main.hud.physics_menu.id_pressed.emit(11)
	if not await _until(func(): return main.hud.physics_settings.get("forecast_limit") == 0):
		_fail("All-body forecast control did not reach the server")
		return
	main.hud.physics_menu.id_pressed.emit(12)
	if not await _until(func(): return main.hud.physics_settings.get("escape_distance") == null):
		_fail("Removal boundary control did not reach the server")
		return
	main.hud.physics_menu.id_pressed.emit(14)
	if not await _until(func(): return main.hud.physics_settings.get("collisions") == "heuristic"):
		_fail("Could not select heuristic comparison mode")
		return
	main.hud.physics_menu.id_pressed.emit(14)
	if not await _until(func(): return main.hud.physics_settings.get("collisions") == "auto"):
		_fail("Could not restore automatic collision models")
		return
	if main.hud.physics_menu.is_item_disabled(main.hud.physics_menu.get_item_index(12)):
		_fail("Automatic mode disabled the independent removal control")
		return
	if not await _request({"cmd": "checkpoint"}):
		_fail("Could not set paused restart point for cancellation test")
		return
	for action in ["preset", "clear"]:
		if action == "preset":
			main.hud.preset_chosen.emit("smash")
		else:
			main.hud.clear_requested.emit()
		await create_timer(0.2).timeout
		if not main.scene_files.confirm.visible or main.views.size() != 6:
			_fail("Destructive action ran before confirmation: " + action)
			return
		main.scene_files.confirm.get_cancel_button().pressed.emit()
		await create_timer(0.2).timeout
		if main.scene_files.confirm.visible or main.views.size() != 6:
			_fail("Cancel did not preserve scene: " + action)
			return
	if not await _request({"cmd": "restart"}):
		_fail("Restart point lost after cancelling scene changes")
		return
	if not await _until(func(): return main.views.size() == 6):
		_fail("Cancelled scene changes replaced the restart point")
		return
	main.rig.frame(Vector3(1, 2, 3), 240, 0.8)
	main.rig.target_yaw = -1.2
	main.display_scale = 2.0
	await create_timer(1).timeout
	var camera_focus: Vector3 = main.rig.focus
	if not await _request({"cmd": "save_scene", "path": path}):
		_fail("Scene test: save failed")
		return
	if not FileAccess.file_exists(path):
		_fail("Scene test: save file missing")
		return
	main.net.send({"cmd": "remove", "id": main.views.keys()[0]})
	if not await _until(func(): return main.views.size() == 5):
		_fail("Scene test: body removal failed")
		return
	main.hud.physics_menu.id_pressed.emit(10)
	if not await _until(func(): return main.hud.physics_settings.get("gravity") == "tracers"):
		_fail("Tracer mode control did not reach the server")
		return
	if not await _request({"cmd": "restart"}):
		_fail("Scene test: restart failed")
		return
	if not await _until(func(): return main.views.size() == 6):
		_fail("Scene test: restart did not restore bodies")
		return
	if not await _until(func(): return main.hud.physics_settings.get("gravity") == "full"):
		_fail("Restart did not restore gravity settings")
		return
	main.hud.clear_requested.emit()
	main.scene_files.confirm.get_ok_button().pressed.emit()
	if not await _until(func(): return main.views.is_empty()):
		_fail("Scene test: clear failed")
		return
	main.rig.frame(Vector3.ZERO, 1000, 0.2)
	main.display_scale = 0.0
	if not await _request({"cmd": "load_scene", "path": path}):
		_fail("Scene test: load failed")
		return
	if not await _until(func(): return main.views.size() == 6 and main.paused):
		_fail("Scene test: load did not restore bodies and pause state")
		return
	if not await _until(func(): return main.hud.physics_settings.get("forecast_limit") == 0 and main.hud.physics_settings.get("escape_distance") == null):
		_fail("Load did not restore forecast and boundary settings")
		return
	if main.display_scale != 2.0 or main.legacy_units or not main._physical_value(1000, "mass_kg", "kg").contains("e30 kg"):
		_fail("Physical units or display size setting did not round trip")
		return
	if not main.rig.target_focus.is_equal_approx(camera_focus):
		_fail("Scene test: camera was not restored")
		return
	main._select(main.views.keys()[0])
	main._update_inspector()
	if not main.hud.insp_values["Physical radius"].text.ends_with(" km") or main.hud.insp_values["Display"].text != "Enlarged x2":
		_fail("Physical inspector fields did not reach the HUD")
		return
	# Preserve integer tokens; Godot parses JSON numbers as floats.
	var legacy := FileAccess.get_file_as_string(path).replace('"version":7', '"version":1')
	var migration_file := FileAccess.open(path, FileAccess.WRITE)
	migration_file.store_string(legacy)
	migration_file.close()
	if not await _request({"cmd": "load_scene", "path": path}) or not await _until(func(): return main.legacy_units):
		_fail("Legacy scene's unit flag did not reach the client")
		return
	if not main._physical_value(1.0, "length_m", "km").ends_with("legacy units"):
		_fail("Legacy values were silently labelled as physical measurements")
		return
	if main.gas_capture_scale != 0:
		_fail("Legacy restore retained the physical inner-flow scale")
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string("{broken")
	file.close()
	if await _request({"cmd": "load_scene", "path": path}) or main.views.size() != 6:
		_fail("Scene test: invalid load changed the scene or succeeded")
		return
	main.hud.preset_chosen.emit("smash")
	main.scene_files.confirm.get_ok_button().pressed.emit()
	if not await _until(func(): return main.views.size() == 2 and is_equal_approx(main.server_speed, 0.005)):
		_fail("Confirmed scenario change did not apply")
		return
	if not await _check_presets():
		_fail("Live preset control checks failed")
		return
	if not await _check_collision_demos():
		_fail("Collision menu/replay checks failed")
		return
	if not await _check_formation():
		_fail("Planet formation growth/restart checks failed")
		return
	var cloud_camera := {"focus": [0, 0, 0], "distance": 3.0, "pitch": 0.3, "yaw": 0.5}
	main.restore_scene_view(cloud_camera)
	await create_timer(0.05).timeout
	# Compact clouds share playback even though they cannot be selected as bodies.
	var cloud := PackedFloat32Array([3, main.sim_version + 1, 0, 1, 1, 0, 1, 1, 1, 600, 1,
		-2, 6, 0, 0, 0, 1, 0, 0, 0.001, 0.01, 0.5, 0])
	main._on_state(cloud)
	cloud[1] += 1
	cloud[3] = 2
	cloud[13] = 3
	main._on_state(cloud)
	main._update_motion(0)
	if main.cloud_count != 1 or not main.views[-2].position.is_equal_approx(Vector3(3, 0, 0)):
		_fail("Compact cloud view did not follow its authoritative position")
		return
	cloud[1] += 1
	cloud[3] = 3
	cloud[4] = 2
	cloud[13] = 0
	cloud.append_array(PackedFloat32Array([1, 0, 0, 0, 0, 0, 0, 0, 0.0001, 0.001, 0, 0]))
	main._on_state(cloud)
	main._update_motion(0)
	if main._pick_body(main.rig.camera.unproject_position(Vector3.ZERO)) != 1:
		_fail("Compact cloud intercepted selection of the resolved remnant")
		return
	main.restore_scene_view(cloud_camera)
	if main.cloud_count != 0 or not main.views.is_empty():
		_fail("Restoring a scene retained the previous compact-cloud count")
		return
	if not _check_scene_replacement():
		_fail("Scene replacement retained old camera, bodies or events")
		return
	print("Godot experiment save/load/restart check PASSED")
	_finish(0)


func _check_scene_replacement() -> bool:
	var version: int = main.sim_version + 10
	var cam := {"focus": [60, 0, 0], "distance": 0.03, "pitch": 0.6}
	main._on_event(main.Palette.EV_TIDAL, Vector3.ZERO, 1, 1, -1, -1)
	main.hud.push_event("Previous scene event")
	main.hud.toast("Previous scene operation")
	main.hud.conservation_report = {"old": true}
	var previous_effects = main.effects
	main._on_message({"type": "preset", "name": "formation", "camera": cam, "version": version})
	if previous_effects.is_inside_tree() or main.effects.get_child_count() != 0:
		return false
	if main.hud.feed.get_child_count() != 0 or not main.hud.conservation_report.is_empty() or main.hud.toast_label.modulate.a != 0:
		return false
	if main.rig.focus != Vector3(60, 0, 0) or not is_equal_approx(main.rig.distance, .03):
		return false
	if not main.rig.camera.position.is_equal_approx(main.rig.focus + Vector3(cos(.6) * sin(main.rig.yaw), sin(.6), cos(.6) * cos(main.rig.yaw)) * .03):
		return false
	# An old queued state carries both a reused ID and a one-off effect. Neither
	# may enter the replacement scene, even before its first state has arrived.
	var stale := PackedFloat32Array([3, version - 1, 0, 1, 1, 1, 1, 1, 1, 600, 1,
		1, 2, 0, 0, 0, 0, 0, 0, 1000, 1, 0, 0,
		main.Palette.EV_TIDAL, 0, 0, 0, 1, 1, -1, -1])
	main._on_state(stale)
	if not main.views.is_empty() or main.effects.get_child_count() != 0:
		return false
	var current := stale.duplicate()
	current[1] = version
	current[3] = 0
	current[5] = 0
	current.resize(23)
	main._on_state(current)
	if main.views.size() != 1 or main.sim_version != version:
		return false
	var view = main.views[1]
	main._on_message({"type": "preset", "camera": cam, "version": version - 1})
	main._on_message({"type": "preset", "camera": cam, "version": version})
	if main.views.get(1) != view:
		return false
	main._server_pid = 1
	main._on_message({"type": "info", "pid": 2})
	current[1] = 0
	main._on_state(current)
	return main.sim_version == 0 and main.views.size() == 1
