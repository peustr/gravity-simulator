extends RefCounted

const History = preload("res://scripts/motion_history.gd")


static func _check(condition: bool, message: String) -> bool:
	if not condition:
		push_error(message)
	return condition


static func run() -> bool:
	var ok := true
	var h = History.new()
	ok = _check(h.position_for(1, Vector3.ONE) == Vector3.ONE, "Empty motion history lost fallback") and ok
	h.push(0.0, {1: Vector3.ZERO}, 0.0)
	h.push(1.0, {1: Vector3.RIGHT}, 1.0)
	h.time = 0.5
	h.advance(0.0, 1.0, false, false)
	ok = _check(h.position_for(1, Vector3.ZERO).is_equal_approx(Vector3(0.5, 0, 0)), "Linear motion interpolation is incorrect") and ok
	h.advance(10.0, 1.0, false, true)
	ok = _check(h.time == 1.0 and h.position_for(1, Vector3.ZERO) == Vector3.RIGHT, "A stalled connection extrapolated beyond the server") and ok
	h.push(0.5, {1: Vector3(999, 0, 0)}, 1.1)
	h.advance(1.0, 1.0, false, true)
	ok = _check(h.position_for(1, Vector3.ZERO) == Vector3.RIGHT, "A stale state rewound motion") and ok
	h.push(1.0, {1: Vector3(2, 0, 0)}, 1.2)
	h.advance(0.0, 1.0, true, true)
	ok = _check(h.position_for(1, Vector3.ZERO) == Vector3(2, 0, 0), "A paused edit was ignored") and ok
	ok = _check(h.position_for(2, Vector3.ONE) == Vector3.ONE, "A new body inherited another body's history") and ok
	h.clear()
	ok = _check(h.time == 0.0 and h.position_for(1, Vector3.ONE) == Vector3.ONE, "Clearing a scene retained its old motion") and ok
	for fps in [30, 60, 144]:
		ok = _orbit(fps, 1.0) and ok
		ok = _orbit(fps, 10.0) and ok
	ok = _slow_delivery() and ok
	if ok:
		print("Motion interpolation checks PASSED")
	return ok


static func _orbit(fps: int, speed: float) -> bool:
	# Io's physical orbit: 0.169 units, period ~0.447 units, at x0.1 and the former x1 default.
	# Its parent also moves, so interpolation must preserve relative motion.
	var h = History.new()
	var radius := 0.169
	var omega := TAU / 0.447
	var drift := Vector3(0.3, 0, 1.5)
	var origin := Vector3(195, 0, 244)
	var packet := 0
	var maximum_error := 0.0
	var last_time := 0.0
	for frame in range(fps * 4):
		var wall := float(frame) / fps
		while float(packet) / 60.0 <= wall:
			var t := float(packet) * speed / 60.0
			var parent := origin + drift * t
			var offset := radius * Vector3(cos(omega * t), 0, sin(omega * t))
			h.push(t, {1: parent, 2: parent + offset}, wall)
			packet += 1
		h.advance(1.0 / fps, speed, false, true)
		if not _check(h.time >= last_time and h.time <= float(packet - 1) * speed / 60.0, "Presentation clock left its authoritative interval"):
			return false
		last_time = h.time
		var relative: Vector3 = h.position_for(2, Vector3.ZERO) - h.position_for(1, Vector3.ZERO)
		var expected := radius * Vector3(cos(omega * h.time), 0, sin(omega * h.time))
		maximum_error = maxf(maximum_error, relative.distance_to(expected))
		if not _check(relative.length() <= radius * 1.02, "A rendered moon flew outside its physical orbit"):
			return false
	print("Io interpolation at ", fps, " FPS, speed ", speed, ": maximum error ", maximum_error)
	return _check(maximum_error < (0.002 if speed == 1.0 else radius), "Io interpolation failed the orbital error bound")


static func _slow_delivery() -> bool:
	var h = History.new()
	var packet := 0
	for frame in range(144 * 5):
		var wall := float(frame) / 144.0
		while float(packet) / 60.0 <= wall:
			# Physics achieves 20% of requested speed; includes a delivery gap.
			var t := float(packet) / 30.0
			if wall < 2.0 or wall > 2.3:
				h.push(t, {1: Vector3(t, 0, 0)}, wall)
			packet += 1
		h.advance(1.0 / 144.0, 10.0, false, true)
		if not _check(h.position_for(1, Vector3.ZERO).is_finite() and h.time <= float(packet - 1) / 30.0, "A slow server caused speculative motion"):
			return false
	var latest := float(packet - 1) / 30.0
	var before: Vector3 = h.position_for(1, Vector3.ZERO)
	h.advance(10.0, 10.0, false, false)
	return _check(h.position_for(1, Vector3.ZERO) == before and latest - h.time < 0.2, "Motion did not follow achieved speed or freeze on disconnect")
