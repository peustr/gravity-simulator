extends Node
## Scene dialogs and acknowledged, retry-safe requests to the local physics server.

var main
var dialog: FileDialog
var confirm: ConfirmationDialog
var pending := {}
var _confirmed := {}
var _elapsed := 0.0
var _retry := 0.0


func _ready() -> void:
	dialog = FileDialog.new()
	dialog.access = FileDialog.ACCESS_FILESYSTEM
	dialog.filters = PackedStringArray(["*.gravity.json ; Gravity Simulator scene"])
	dialog.size = Vector2i(760, 480)
	var directory := OS.get_user_data_dir().path_join("scenes")
	DirAccess.make_dir_recursive_absolute(directory)
	dialog.current_dir = directory
	add_child(dialog)
	dialog.file_selected.connect(_file_selected)
	confirm = ConfirmationDialog.new()
	add_child(confirm)
	confirm.confirmed.connect(_accept_confirmation)
	confirm.canceled.connect(func(): _confirmed.clear())
	main.net.message_received.connect(_on_message)


func replace_scene(command: Dictionary) -> void:
	if not pending.is_empty():
		main.hud.toast("Waiting for the current scene operation...")
		return
	if not main.net.connected:
		main.hud.toast("Connect to the physics server first.")
		return
	if command.cmd == "preset" and main.views.is_empty():
		main.apply_scene_change(command)
		return
	_confirmed = command.duplicate(true)
	confirm.dialog_text = "Clear the current scene?" if command.cmd == "clear" else "Replace the current scene with this scenario?"
	confirm.dialog_text += "\nUnsaved changes will be discarded and the restart point will be replaced."
	confirm.popup_centered()


func _accept_confirmation() -> void:
	var command := _confirmed.duplicate(true)
	_confirmed.clear()
	if command.is_empty():
		return
	if not main.net.connected or not pending.is_empty():
		main.hud.toast("Scene unchanged. Wait for the connection or current operation, then try again.")
		return
	if command.cmd in ["clear", "preset"]:
		main.apply_scene_change(command)
	else:
		request(command)


func choose(action: String) -> void:
	if not pending.is_empty():
		main.hud.toast("Waiting for the current scene operation...")
		return
	if not main.net.connected:
		main.hud.toast("Connect to the physics server first.")
		return
	match action:
		"save_scene", "load_scene":
			dialog.file_mode = FileDialog.FILE_MODE_SAVE_FILE if action == "save_scene" else FileDialog.FILE_MODE_OPEN_FILE
			dialog.title = "Save scene" if action == "save_scene" else "Load scene"
			dialog.current_file = "experiment.gravity.json" if action == "save_scene" else ""
			dialog.popup_centered()
		"restart":
			_confirmed = {"cmd": "restart"}
			confirm.dialog_text = "Return to the last saved, loaded, or set restart point?\nChanges since that point will be discarded."
			confirm.popup_centered()
		"checkpoint":
			request({"cmd": action})


func _file_selected(path: String) -> void:
	if dialog.file_mode == FileDialog.FILE_MODE_SAVE_FILE:
		request({"cmd": "save_scene", "path": path})
	else:
		_confirmed = {"cmd": "load_scene", "path": path}
		confirm.dialog_text = "Replace the current scene with this file?\nUnsaved changes will be discarded."
		confirm.popup_centered()


func request(command: Dictionary) -> void:
	if not pending.is_empty():
		return
	pending = command.duplicate(true)
	pending["request"] = "%s-%s" % [Time.get_ticks_usec(), randi()]
	if pending.cmd in ["save_scene", "checkpoint"]:
		var f: Vector3 = main.rig.focus
		pending["camera"] = {"focus": [f.x, f.y, f.z], "distance": main.rig.distance,
			"pitch": main.rig.pitch, "yaw": main.rig.yaw}
	_elapsed = 0.0
	_retry = 0.0
	main.net.send(pending)
	main.hud.toast("Working...")


func _process(delta: float) -> void:
	if pending.is_empty():
		return
	_elapsed += delta
	_retry += delta
	if _elapsed >= 10.0:
		pending.clear()
		main.hud.toast("No confirmation received. Check the connection and scene file before retrying.")
	elif _retry >= 1.0:
		_retry = 0.0
		main.net.send(pending)


func _on_message(message: Dictionary) -> void:
	if message.get("type") != "scene_result" or pending.is_empty() or message.get("request") != pending.get("request"):
		return
	var action: String = pending.cmd
	pending.clear()
	if not message.get("ok", false):
		main.hud.toast(str(message.get("error", "Scene operation failed.")))
		return
	if action in ["load_scene", "restart"]:
		main.restore_scene_view(message.camera)
	var labels := {"save_scene": "Scene saved. Restart point updated.",
		"load_scene": "Scene loaded. Restart point updated.",
		"checkpoint": "Restart point set for this session.", "restart": "Experiment restarted."}
	main.hud.toast(labels[action])
