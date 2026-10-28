extends SceneTree
## Exercise the real scene UI controller, UDP transport, and Python filesystem path.

const Main = preload("res://scripts/main.gd")
var main
var result := {}
var path: String


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


func _until(predicate: Callable) -> bool:
	for i in range(150):
		if predicate.call():
			return true
		await create_timer(0.05).timeout
	return false


func _request(command: Dictionary) -> bool:
	result = {}
	main.scene_files.request(command)
	if not await _until(func(): return not result.is_empty()):
		return false
	return result.get("ok", false)


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
	if not await _until(func(): return main.hud.physics_settings.get("collisions") == "isolated_impacts"):
		_fail("Calibrated collision control did not reach the server")
		return
	if not main.hud.physics_menu.is_item_disabled(main.hud.physics_menu.get_item_index(10)):
		_fail("Calibrated mode allowed tracer gravity")
		return
	main.hud.physics_menu.id_pressed.emit(14)
	if not await _until(func(): return main.hud.physics_settings.get("collisions") == "heuristic"):
		_fail("Could not return to heuristic mode")
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
	var legacy := FileAccess.get_file_as_string(path).replace('"version":4', '"version":1')
	var migration_file := FileAccess.open(path, FileAccess.WRITE)
	migration_file.store_string(legacy)
	migration_file.close()
	if not await _request({"cmd": "load_scene", "path": path}) or not await _until(func(): return main.legacy_units):
		_fail("Legacy scene's unit flag did not reach the client")
		return
	if not main._physical_value(1.0, "length_m", "km").ends_with("legacy units"):
		_fail("Legacy values were silently labelled as physical measurements")
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string("{broken")
	file.close()
	if await _request({"cmd": "load_scene", "path": path}) or main.views.size() != 6:
		_fail("Scene test: invalid load changed the scene or succeeded")
		return
	main.hud.preset_chosen.emit("smash")
	main.scene_files.confirm.get_ok_button().pressed.emit()
	if not await _until(func(): return main.views.size() == 2 and is_equal_approx(main.server_speed, 0.05)):
		_fail("Confirmed scenario change did not apply")
		return
	print("Godot experiment save/load/restart check PASSED")
	_finish(0)
