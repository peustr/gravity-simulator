extends RefCounted
## Buffered presentation of authoritative states. Never predicts gravitational forces.

const DELAY := 0.05
const MAX_SNAPSHOTS := 64

var time := 0.0
var _frames: Array[Dictionary] = []
var _started := false
var _rate := 0.0
var _lower := 0
var _upper := 0


func clear() -> void:
	_frames.clear()
	_started = false
	_rate = 0.0
	_lower = 0
	_upper = 0
	time = 0.0


func push(t: float, positions: Dictionary, received: float) -> void:
	var frame := {"time": t, "positions": positions, "received": received}
	if _frames.is_empty():
		time = t
	elif t < float(_frames[-1].time):
		return # A delayed UDP packet must not rewind presentation.
	elif t == float(_frames[-1].time):
		frame.received = _frames[-1].received
		_frames[-1] = frame
		return
	_frames.append(frame)
	while _frames.size() > MAX_SNAPSHOTS:
		_frames.pop_front()


func advance(delta: float, requested_speed: float, paused: bool, connected: bool) -> void:
	if _frames.is_empty():
		return
	var latest: Dictionary = _frames[-1]
	if paused:
		time = latest.time
	elif connected:
		# Measure achieved simulation speed over a short receipt-time window.
		# Batched packets share a receipt time; do not divide by their zero gap.
		var observed := requested_speed
		for frame in _frames:
			var elapsed: float = latest.received - frame.received
			if elapsed >= 0.1:
				observed = (float(latest.time) - float(frame.time)) / elapsed
				if elapsed <= 0.25:
					break
		observed = clampf(observed, 0.0, requested_speed)
		if _rate == 0.0:
			_rate = observed
		_rate = minf(requested_speed, lerpf(_rate, observed, 1.0 - exp(-delta / 0.1)))
		var lag := _rate * DELAY
		if not _started:
			_started = float(latest.time) - time >= lag and _frames.size() > 1
		if _started:
			# Gently absorb delivery jitter without jumping to a new clock or
			# running ahead of the newest authoritative state during a stall.
			var error: float = latest.time - lag - time
			var correction := clampf(1.0 + error / maxf(_rate * 0.2, 1e-12), 0.8, 1.2)
			time = minf(time + delta * _rate * correction, latest.time)
	time = clampf(time, _frames[0].time, latest.time)
	_lower = 0
	while _lower + 1 < _frames.size() and float(_frames[_lower + 1].time) <= time:
		_lower += 1
	_upper = mini(_lower + 1, _frames.size() - 1)


func position_for(id: int, fallback: Vector3) -> Vector3:
	if _frames.is_empty():
		return fallback
	var a: Dictionary = _frames[_lower]
	var b: Dictionary = _frames[_upper]
	if not a.positions.has(id) or not b.positions.has(id):
		return fallback # New bodies have no earlier state to interpolate.
	var p: Vector3 = a.positions[id]
	var q: Vector3 = b.positions[id]
	var duration: float = b.time - a.time
	if duration <= 0.0:
		return p
	var u := clampf((time - float(a.time)) / duration, 0.0, 1.0)
	# Convex interpolation cannot fling a body beyond its samples. In
	# particular, relative moon positions stay between the sampled relative
	# positions even while their parent translates. Curved extrapolation can
	# fail catastrophically when a fast orbit is undersampled.
	return p.lerp(q, u)
