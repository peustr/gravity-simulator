extends Node
## Opt-in rendered frame intervals and observed state-delivery gaps.
## Invoked by tools/dev.py benchmark-visual, with its own seeded physics server.

var main
var output_path := ""
var scenario := ""
var seconds := 10.0
var seed_value := 42
var _started := 0
var _warmup_started := 0
var _sampling := 0
var _last_frame := 0
var _last_state := 0
var _frames: Array[float] = []
var _state_gaps: Array[float] = []
var _physics_perf: Array[float] = []
var _initial_sim_time := 0.0


func _ready() -> void:
	_started = Time.get_ticks_usec()
	if DisplayServer.get_name() == "headless":
		_fail("Rendered benchmarks require a display; headless frame rates are not valid.")
		return
	main.net.state_received.connect(_on_state)


func _fail(message: String) -> void:
	set_process(false)
	push_error(message)
	get_tree().quit(1)


func _on_state(_packet: PackedFloat32Array) -> void:
	if _sampling == 0:
		return
	var now := Time.get_ticks_usec()
	if _last_state > 0:
		_state_gaps.append((now - _last_state) / 1000.0)
	_last_state = now


func _process(_delta: float) -> void:
	var now := Time.get_ticks_usec()
	if now - _started > (seconds + 120.0) * 1000000.0:
		_fail("Rendered benchmark timed out waiting for live physics.")
		return
	if _sampling == 0:
		if not main.net.connected or main.views.is_empty():
			_warmup_started = 0
			return
		if _warmup_started == 0:
			_warmup_started = now
		if now - _warmup_started < 3000000:
			return
		_sampling = now
		_last_frame = now
		_initial_sim_time = main.packet_time
		return
	if not main.net.connected:
		_fail("Physics disconnected during the rendered benchmark.")
		return
	_frames.append((now - _last_frame) / 1000.0)
	_physics_perf.append(main.perf)
	_last_frame = now
	if now - _sampling >= seconds * 1000000.0:
		_finish()


static func distribution(values: Array[float]) -> Dictionary:
	if values.is_empty():
		return {"count": 0}
	var ordered := values.duplicate()
	ordered.sort()
	var total := 0.0
	for value in ordered:
		total += value
	return {"count": ordered.size(), "mean": total / ordered.size(),
		"p50": ordered[ceili(ordered.size() * 0.5) - 1],
		"p95": ordered[ceili(ordered.size() * 0.95) - 1],
		"p99": ordered[ceili(ordered.size() * 0.99) - 1], "max": ordered[-1], "min": ordered[0]}


func _finish() -> void:
	set_process(false)
	if _frames.size() < 2 or _state_gaps.is_empty() or main.packet_time <= _initial_sim_time:
		_fail("Insufficient live data for a rendered benchmark.")
		return
	var frame_stats := distribution(_frames)
	var over_60 := 0
	var over_30 := 0
	for interval in _frames:
		if interval > 1000.0 / 60.0:
			over_60 += 1
		if interval > 1000.0 / 30.0:
			over_30 += 1
	var report := {"format": "gravity-render-baseline", "version": 1,
		"scenario": scenario, "seed": seed_value, "warmup_seconds": 3.0,
		"sample_seconds": (Time.get_ticks_usec() - _sampling) / 1000000.0,
		"frame_intervals_ms": frame_stats, "average_fps": 1000.0 / frame_stats.mean,
		"frames_over_60fps_budget": over_60, "frames_over_30fps_budget": over_30,
		"observed_state_gaps_ms": distribution(_state_gaps),
		"achieved_requested_physics_ratio": distribution(_physics_perf),
		"simulated_time_advanced": main.packet_time - _initial_sim_time,
		"final_bodies": main.views.size(), "godot": Engine.get_version_info().string,
		"cpu": OS.get_processor_name(), "logical_cpus": OS.get_processor_count(),
		"memory": OS.get_memory_info(), "gpu": RenderingServer.get_video_adapter_name(),
		"renderer": RenderingServer.get_current_rendering_method(),
		"display": DisplayServer.get_name(), "window_size": str(DisplayServer.window_get_size()),
		"vsync_mode": DisplayServer.window_get_vsync_mode(), "engine_max_fps": Engine.max_fps,
		"notes": ["Frame intervals include CPU, GPU, scheduling and VSync; they are not isolated GPU timings.",
			"State gaps are client observations, not input-to-display latency.",
			"Percentiles use nearest rank. Initial conditions are seeded; wall-budget evolution can vary."]}
	var file := FileAccess.open(output_path, FileAccess.WRITE)
	if file == null:
		_fail("Could not write rendered benchmark: " + output_path)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("Rendered benchmark complete: ", output_path)
	get_tree().quit()
