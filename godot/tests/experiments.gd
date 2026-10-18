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
	main.net.send({"cmd": "preset", "name": "binary"})
	main.net.send({"cmd": "pause", "value": true})
	if not await _until(func(): return main.views.size() == 6 and main.paused):
		_fail("Scene test: initial scene did not arrive")
		return
	main.rig.frame(Vector3(1, 2, 3), 240, 0.8)
	main.rig.target_yaw = -1.2
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
	if not await _request({"cmd": "restart"}):
		_fail("Scene test: restart failed")
		return
	if not await _until(func(): return main.views.size() == 6):
		_fail("Scene test: restart did not restore bodies")
		return
	main.net.send({"cmd": "clear"})
	if not await _until(func(): return main.views.is_empty()):
		_fail("Scene test: clear failed")
		return
	main.rig.frame(Vector3.ZERO, 1000, 0.2)
	if not await _request({"cmd": "load_scene", "path": path}):
		_fail("Scene test: load failed")
		return
	if not await _until(func(): return main.views.size() == 6 and main.paused):
		_fail("Scene test: load did not restore bodies and pause state")
		return
	if not main.rig.target_focus.is_equal_approx(camera_focus):
		_fail("Scene test: camera was not restored")
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string("{broken")
	file.close()
	if await _request({"cmd": "load_scene", "path": path}) or main.views.size() != 6:
		_fail("Scene test: invalid load changed the scene or succeeded")
		return
	print("Godot experiment save/load/restart check PASSED")
	_finish(0)
