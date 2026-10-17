extends Node
## Talks to the Python physics server over UDP on 127.0.0.1.
##
## Sends small JSON commands; receives binary state packets (float32 arrays)
## about 60 times a second, plus occasional JSON messages. Also starts the
## physics server automatically if it finds the virtual environment that
## setup_physics_server.bat creates.

signal state_received(packet: PackedFloat32Array)
signal prediction_received(packet: PackedFloat32Array)
signal message_received(msg: Dictionary)
signal connection_changed(is_connected: bool)

const SERVER_HOST := "127.0.0.1"
const SERVER_PORT := 47810
const HELLO_INTERVAL := 0.5
const TIMEOUT := 1.5

var udp := PacketPeerUDP.new()
var connected := false
var server_info: Dictionary = {}
var server_pid := -1
var launch_status := ""   # human-readable note about auto-launch
var _last_packet := -1000.0
var _hello_timer := 0.0
var _launch_tried := false
var _start_time := 0.0


func _ready() -> void:
	var err := udp.bind(0, "127.0.0.1", 1 << 22)
	if err != OK:
		push_warning("Could not open a UDP socket (error %d)" % err)
	udp.set_dest_address(SERVER_HOST, SERVER_PORT)
	_start_time = _now()


func _now() -> float:
	return Time.get_ticks_msec() / 1000.0


func send(cmd: Dictionary) -> void:
	if not udp.is_bound():
		return
	udp.put_packet(JSON.stringify(cmd).to_utf8_buffer())


func _process(delta: float) -> void:
	_hello_timer -= delta
	if _hello_timer <= 0.0:
		send({"cmd": "hello"})
		_hello_timer = HELLO_INTERVAL

	var latest_state := PackedFloat32Array()
	var have_state := false
	while udp.get_available_packet_count() > 0:
		var pkt := udp.get_packet()
		if udp.get_packet_ip() != SERVER_HOST or udp.get_packet_port() != SERVER_PORT:
			continue
		if pkt.size() == 0:
			continue
		if pkt[0] == 123:  # '{' -> JSON message
			var msg = JSON.parse_string(pkt.get_string_from_utf8())
			if msg is Dictionary:
				if msg.get("type", "") == "info":
					if msg.get("protocol", -1) != 1:
						continue
					server_info = msg
					_last_packet = _now()
				message_received.emit(msg)
			continue
		if pkt.size() % 4 != 0:
			continue
		var f := pkt.to_float32_array()
		if not valid_packet(f):
			continue
		_last_packet = _now()
		var kind := int(f[0])
		if kind == 1:
			# Every state packet may carry one-off events, so pass them all on,
			# but only the newest one needs to update positions.
			if have_state:
				state_received.emit(latest_state)
			latest_state = f
			have_state = true
		elif kind == 2:
			prediction_received.emit(f)
	if have_state:
		state_received.emit(latest_state)

	var now_connected := _now() - _last_packet < TIMEOUT
	if now_connected != connected:
		connected = now_connected
		connection_changed.emit(connected)

	if not connected and not _launch_tried and _now() - _start_time > 1.2:
		_launch_tried = true
		try_launch_server()


func find_server_dir() -> String:
	## Looks for physics_server/ next to the Godot project (editor) or next
	## to the exported .exe.
	var candidates: Array[String] = []
	var project_dir := ProjectSettings.globalize_path("res://").trim_suffix("/")
	if project_dir != "":
		candidates.append(project_dir.get_base_dir().path_join("physics_server"))
	var exe_dir := OS.get_executable_path().get_base_dir()
	candidates.append(exe_dir.path_join("physics_server"))
	candidates.append(exe_dir.get_base_dir().path_join("physics_server"))
	for c in candidates:
		for marker in ["server.py", "server.exe", "dist/server.exe"]:
			if FileAccess.file_exists(c.path_join(marker)):
				return c
	return ""


func try_launch_server() -> bool:
	var dir := find_server_dir()
	if dir == "":
		launch_status = "Couldn't find the physics_server folder next to the project."
		return false
	# A stand-alone build made with PyInstaller (see README) needs no Python.
	for exe in [dir.path_join("server.exe"), dir.path_join("dist/server.exe")]:
		if FileAccess.file_exists(exe):
			server_pid = OS.create_process(exe, ["--exit-when-idle", "10", "--log", dir.path_join("server.log")])
			if server_pid > 0:
				launch_status = "Starting the physics server automatically..."
				return true
	var pythons := [
		dir.path_join(".venv/Scripts/pythonw.exe"),
		dir.path_join(".venv/Scripts/python.exe"),
		dir.path_join(".venv/bin/python3"),
		dir.path_join(".venv/bin/python"),
	]
	for py in pythons:
		if FileAccess.file_exists(py):
			var args := [dir.path_join("server.py"), "--exit-when-idle", "10", "--log", dir.path_join("server.log")]
			server_pid = OS.create_process(py, args)
			if server_pid > 0:
				launch_status = "Starting the physics server automatically..."
				return true
	launch_status = "The physics server isn't set up yet (no .venv found). Run setup_physics_server.bat once."
	return false


func retry_launch() -> void:
	_launch_tried = false
	_start_time = _now() - 1.2


func shutdown() -> void:
	send({"cmd": "bye"})
	if server_pid > 0:
		OS.kill(server_pid)
		server_pid = -1


static func valid_packet(f: PackedFloat32Array) -> bool:
	# Validate before converting counts or indexing either header.
	if f.is_empty():
		return false
	for value in f:
		if not is_finite(value):
			return false
	if f[0] == 1.0:
		if f.size() < 10:
			return false
		var n := int(f[4])
		var events := int(f[5])
		if n < 0 or n > 1321 or events < 0 or events > 64 or f[4] != n or f[5] != events:
			return false
		if f.size() != 10 + n * 12 + events * 8:
			return false
		for i in range(n):
			var offset := 10 + i * 12
			if f[offset + 1] < 0 or f[offset + 1] > 6 or f[offset + 1] != int(f[offset + 1]):
				return false
			if f[offset + 8] <= 0 or f[offset + 9] <= 0:
				return false
		return true
	if f[0] == 2.0:
		if f.size() < 8 or f[2] < 0 or f[2] > 221 or f[2] != int(f[2]):
			return false
		return f.size() == 8 + int(f[2]) * 3
	return false
