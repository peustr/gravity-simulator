extends Node
## Talks to the Python physics server over UDP on 127.0.0.1.
##
## Sends small JSON commands; receives binary state packets (float32 arrays)
## about 60 times a second, plus occasional JSON messages. Also starts the
## physics server automatically if it finds the virtual environment that
## setup_physics_server.bat creates.

signal state_received(packet: PackedFloat32Array)
signal prediction_received(packet: PackedFloat32Array)
signal rotation_received(packet: PackedFloat32Array)
signal message_received(msg: Dictionary)
signal connection_changed(is_connected: bool)

const PROTOCOL_VERSION := 2
const STATE_KIND := 3
const PREDICTION_KIND := 4
const ROTATION_KIND := 5

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
var _next_hello := 0.0
var _last_poll := -1.0
var _resume_probe := false
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
	cmd = cmd.duplicate()
	cmd["protocol"] = PROTOCOL_VERSION
	udp.put_packet(JSON.stringify(cmd).to_utf8_buffer())


func _process(_delta: float) -> void:
	var received := false
	var now := _now()
	# Godot caps frame delta during shader compilation or a suspended window.
	# Resume heartbeats immediately and give one probe a normal response window.
	# An unanswered probe cannot repeatedly renew that window on slow frames.
	if connected and _last_poll >= 0 and now-_last_poll > TIMEOUT and not _resume_probe:
		_resume_probe = true
		_last_packet = now
		_next_hello = 0.0
	if now >= _next_hello:
		send({"cmd": "hello"})
		_next_hello = now+HELLO_INTERVAL

	var states: Array[PackedFloat32Array] = []
	var rotations: Array[PackedFloat32Array] = []
	var tides: Array[Dictionary] = []
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
					if msg.get("protocol", -1) != PROTOCOL_VERSION:
						launch_status = "Physics protocol mismatch. Update the client and server together."
						_launch_tried = true
						continue
					server_info = msg
					_last_packet = _now()
					received = true
				elif msg.get("type", "") == "protocol_error":
					launch_status = str(msg.get("text", "Physics protocol mismatch."))
					_launch_tried = true
				if msg.get("type", "") == "tides":
					tides.append(msg)
				else:
					message_received.emit(msg)
			continue
		if pkt.size() % 4 != 0:
			continue
		var f := pkt.to_float32_array()
		if not valid_packet(f):
			continue
		_last_packet = _now()
		received = true
		var kind := int(f[0])
		if kind == STATE_KIND:
			# Apply scene/camera acknowledgements before queued state packets.
			# The client can then reject states from the replaced scene, including
			# their one-off events, without showing it through the new camera.
			states.append(f)
		elif kind == PREDICTION_KIND:
			prediction_received.emit(f)
		elif kind == ROTATION_KIND:
			rotations.append(f)
	for state in states:
		state_received.emit(state)
	for pose in rotations:
		rotation_received.emit(pose)
	for report in tides:
		message_received.emit(report)

	# State callbacks may compile shaders or build hundreds of views. Their
	# processing time must not consume the next poll's disconnect window.
	if received:
		_last_packet = _now()
		_resume_probe = false
	_last_poll = _now()
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
	if f[0] == STATE_KIND:
		if f.size() < 11 or f[4] < 0 or f[4] > 1329 or f[5] < 0 or f[5] > 64:
			return false
		var n := int(f[4])
		var events := int(f[5])
		if n < 0 or n > 1329 or events < 0 or events > 64 or f[4] != n or f[5] != events:
			return false
		if f.size() != 11 + n * 12 + events * 8:
			return false
		if f[10] != 0.0 and f[10] != 1.0:
			return false
		for i in range(n):
			var offset := 11 + i * 12
			if f[offset + 1] < 0 or f[offset + 1] > 6 or f[offset + 1] != int(f[offset + 1]):
				return false
			if f[offset + 8] <= 0 or f[offset + 9] <= 0:
				return false
		return true
	if f[0] == PREDICTION_KIND:
		if f.size() < 9 or f[2] < 0 or f[2] > 221 or f[2] != int(f[2]):
			return false
		return f.size() == 9 + int(f[2]) * 3 and f[8] > 0.0
	if f[0] == ROTATION_KIND:
		if f.size() < 5 or f[4] < 0 or f[4] > 1321 or f[4] != int(f[4]) or f.size() != 5+10*int(f[4]):
			return false
		if f[1] < 0 or f[1] >= 16000000 or f[1] != int(f[1]) or f[2]+f[3] < 0:
			return false
		for i in range(int(f[4])):
			var o := 5+10*i
			if f[o] <= 0 or f[o] > 16000000 or f[o] != int(f[o]) or f[o+1] not in [0.0,1.0,2.0] or f[o+9] < 0:
				return false
			var q := Quaternion(f[o+2],f[o+3],f[o+4],f[o+5])
			if absf(q.length_squared()-1.0) > .00001:
				return false
		return true
	return false
