extends "res://tests/experiments.gd"
## Continuous default-scene recordings, including every rendered peak event.

var output := ""
var active := ""
var stage := ""
var started := 0
var previous := 0
var next_frame := 0
var frames: Array = []
var records: Array = []
var peak := -1.0
var peak_path := ""
var max_white := 0.0
var overlays := 0
var visible_initial := -1.0
var capture_errors := 0
var seed_value := 42


func _run() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--qa-output="):
			output = arg.trim_prefix("--qa-output=")
		if arg.begins_with("--qa-seed="):
			seed_value = int(arg.trim_prefix("--qa-seed="))
	if output.is_empty() or DisplayServer.get_name() == "headless":
		push_error("Scene quality requires an output directory and a real display")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(output)
	main = Main.new()
	root.add_child(main)
	path = OS.get_user_data_dir().path_join("quality-check-%s.gravity.json" % Time.get_ticks_usec())
	main.net.message_received.connect(func(msg: Dictionary):
		if msg.get("type") == "scene_result": result = msg)
	if not await _until(func(): return main.net.connected):
		_fail("Scene quality could not connect to physics")
		return
	RenderingServer.frame_post_draw.connect(_capture)
	for preset in ["solar", "binary", "black_hole", "smash", "formation", "galaxies", "empty"]:
		active = ""
		main.net.send({"cmd": "pause", "value": true})
		if not await _until(func(): return main.paused):
			_fail("Could not pause before scene switch")
			return
		var version: int = main.sim_version
		main.hud.preset_chosen.emit(preset)
		main.scene_files.confirm.get_ok_button().pressed.emit()
		if not await _until(func(): return main.sim_version > version and main.paused):
			_fail("Scene did not load: " + preset)
			return
		DirAccess.make_dir_recursive_absolute(output.path_join(preset))
		frames = []
		peak = -1
		max_white = 0
		overlays = 0
		visible_initial = -1
		capture_errors = 0
		started = Time.get_ticks_usec()
		previous = started
		next_frame = started
		stage = "initial"
		active = preset
		await create_timer(1.0).timeout
		if not await _request({"cmd":"save_scene","path":output.path_join(preset).path_join("initial.gravity.json")}):
			_fail("Could not save reproducible initial state: " + preset)
			return
		stage = "watch"
		var initial_time: float = main.packet_time
		main.hud.pause_btn.pressed.emit()
		var watch_seconds := 40 if preset == "formation" else 12
		var end := Time.get_ticks_usec() + watch_seconds*1000000
		while Time.get_ticks_usec() < end:
			await process_frame
		stage = "aftermath"
		main.net.send({"cmd": "pause", "value": true})
		await create_timer(.5).timeout
		var problems: Array = []
		if main.packet_time <= initial_time: problems.append("watch_did_not_advance")
		if preset == "empty":
			stage = "placement"
			main.hud.select_tool(main.Palette.ROCKY)
			main.mouse_pos = main.get_viewport().get_visible_rect().size * Vector2(.62, .5)
			await create_timer(.5).timeout
			for pressed in [true, false]:
				var click := InputEventMouseButton.new()
				click.button_index = MOUSE_BUTTON_LEFT
				click.pressed = pressed
				click.position = main.mouse_pos
				Input.parse_input_event(click)
			if not await _until(func(): return main.views.size() == 1):
				problems.append("placement_failed")
		if not main.views.is_empty():
			stage = "follow_zoom"
			var selected: int = main.views.keys()[0]
			var survivor: int = main.hud.impact_panel.report.get("survivor_id", -1)
			if main.views.has(survivor):
				selected = survivor
			if preset == "solar":
				for id in main.views:
					if main.views[id].body_type == main.Palette.ROCKY and main.views[id].mass < .0001:
						selected = id
						break
			if selected == survivor:
				main.hud.impact_panel.inspect.pressed.emit()
				if not await _until(func(): return main.server_speed <= .005):
					problems.append("inspect_speed_failed")
			else:
				main._select(selected)
				main._start_follow(selected)
			main.rig.zoom(.5)
			main.hud.select_tool(-1)
			main.hud.pause_btn.pressed.emit()
			main._speed_step(1)
			await create_timer(1).timeout
			if not main.views.has(main.follow_id) or not main.rig.camera.is_position_in_frustum(main.views[main.follow_id].position):
				problems.append("follow_target_not_visible")
			main._speed_step(-1)
			main.net.send({"cmd":"pause","value":true})
			if not await _until(func(): return main.paused): problems.append("pause_failed")
			main.rig.zoom(2)
		stage = "save_edit_restart_load"
		var saved_count: int = main.views.size()
		if not await _request({"cmd":"save_scene","path":path}):
			problems.append("save_failed")
		else:
			if saved_count > 0:
				main._select(main.views.keys()[0])
				main.hud.delete_requested.emit()
				if not await _until(func(): return main.views.size() == saved_count-1): problems.append("delete_failed")
			if not await _request({"cmd":"restart"}) or not await _until(func(): return main.views.size() == saved_count and main.paused):
				problems.append("restart_failed")
			if not await _request({"cmd":"load_scene","path":path}) or not await _until(func(): return main.views.size() == saved_count and main.paused):
				problems.append("load_failed")
		if preset == "formation":
			stage = "system_overview"
			main._reset_view()
			await create_timer(1).timeout
		if max_white > .35: problems.append("viewport_whiteout")
		if capture_errors > 0: problems.append("capture_write_failed")
		if overlays > 0: problems.append("unexpected_overlay")
		if preset == "formation" and visible_initial < .8:
			problems.append("disk_context_missing")
		records.append({"scene": preset, "frames": frames.duplicate(), "peak_white_fraction": max_white,
			"peak_frame": peak_path, "initial_visible_fraction": visible_initial,
			"overlay_frames": overlays, "issues": problems,
			"status": "PASS" if problems.is_empty() else "FAIL"})
		print("Recorded scene: ", preset, " peak white=",max_white," issues=",problems)
	active = ""
	# Reuse the application's existing all-preset interaction suite, rather than
	# replacing it with direct assertions on the Python world.
	var controls: bool = await _check_presets()
	if controls: controls = await _check_collision_demos()
	if controls: controls = await _check_formation()
	if controls:
		controls = accretion_snapshot != null and accretion_snapshot.save_png(output.path_join("formation-bound-sticking.png")) == OK
	var version_info := Engine.get_version_info()
	var report := {"format": "scene-render-quality", "version": 1, "scenes": records,
		"seed": seed_value,
		"controls_passed": controls, "godot": Engine.get_version_info().string,
		"control_evidence": {"formation_bound_sticking": "formation-bound-sticking.png", "manual_body_addition": true},
		"engine_version": {"major": version_info.major, "minor": version_info.minor, "patch": version_info.patch},
		"renderer": RenderingServer.get_current_rendering_method(),
		"gpu": RenderingServer.get_video_adapter_name(), "display": DisplayServer.get_name(),
		"capture_note": "Every displayed frame analysed; timed PNG sequence sampled at up to 10 Hz. Recording adds overhead."}
	var file := FileAccess.open(output.path_join("render.json"), FileAccess.WRITE)
	file.store_string(JSON.stringify(report, "\t"))
	file.close()
	_finish(0 if controls else 1)


func _capture() -> void:
	if active.is_empty(): return
	var now := Time.get_ticks_usec()
	var picture := root.get_texture().get_image()
	var reduced := picture.duplicate() as Image
	reduced.resize(160, 90, Image.INTERPOLATE_NEAREST)
	reduced.convert(Image.FORMAT_RGB8)
	var bytes := reduced.get_data()
	var white := 0
	for pixel in range(0, bytes.size(), 3):
		if mini(bytes[pixel], mini(bytes[pixel+1], bytes[pixel+2])) > 242:
			white += 1
	var fraction := float(white) / (160 * 90)
	max_white = maxf(max_white, fraction)
	var new_peak := fraction > peak
	if main.hud.welcome.visible or main.hud.overlay.visible:
		if overlays == 0:
			print("Unexpected overlay: ",active," stage=",stage," online=",main.net.connected," welcome=",main.hud.welcome.visible," packet_age=",main.net._now()-main.net._last_packet)
		overlays += 1
	if stage == "initial" and absf(log(main.rig.distance / main.rig.target_distance)) < .01:
		var visible := 0
		for id in main.views:
			if main.rig.camera.is_position_in_frustum(main.views[id].position): visible += 1
		visible_initial = float(visible) / main.views.size() if not main.views.is_empty() else 1.0
	if new_peak:
		peak = fraction
		peak_path = active.path_join("peak.png")
		if picture.save_png(output.path_join(peak_path)) != OK: capture_errors += 1
	if now >= next_frame or new_peak:
		var relative := active.path_join("frame-%05d.png" % frames.size())
		if picture.save_png(output.path_join(relative)) != OK: capture_errors += 1
		frames.append({"path": relative, "time_s": float(now-started)/1e6,
			"sim_time": main.packet_time, "stage": stage, "white_fraction": fraction,
			"frame_ms": float(now-previous)/1000, "display_time": main.display_time,
			"camera": [main.rig.camera.position.x,main.rig.camera.position.y,main.rig.camera.position.z],
			"bodies": main.views.size()})
		next_frame = now + 100000
	previous = now
