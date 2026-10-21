extends SceneTree

const Palette = preload("res://scripts/palette.gd")
const Net = preload("res://scripts/net_client.gd")
const Main = preload("res://scripts/main.gd")
const Hud = preload("res://scripts/hud.gd")
const Benchmark = preload("res://scripts/benchmark.gd")

func _initialize() -> void:
	var timing := Benchmark.distribution([1.0, 2.0, 3.0, 100.0])
	if timing.p95 != 100.0 or timing.mean != 26.5 or Benchmark.distribution([]).count != 0:
		push_error("Frame timing statistics discarded outliers or mishandled empty data")
		quit(1)
		return
	var invalid := [[1, 0, 0, 0, 0, 0, 0, 10, 1, 600], [2, 1, 0, 0, -1, 0, 0, 0],
		[3, 0, 0, 0, 0, 0, 0, 10, 1, 600, 2], [], [1], [2], [1, 0, 0, 0, -1, 0, 0, 10, 1, 600],
		[4, 0, 1, 0, -1, 0, 0, 0], [4, 0, NAN, 0, -1, 0, 0, 0],
		[4, 0, 0.5, 0, -1, 0, 0, 0]]
	var main := Main.new()
	for values in invalid:
		var packet := PackedFloat32Array(values)
		if Net.valid_packet(packet):
			push_error("Malformed packet accepted")
			quit(1)
			return
		main._on_state(packet)
		main._on_prediction(packet)
	main.pred_req = 7
	main.pred_radius = 10.0
	main._clear_prediction()
	main._on_prediction(PackedFloat32Array([4, 7, 0, 0, -1, 0, 0, 0, 99.0]))
	if main.pred_radius != 0.0:
		push_error("A stale forecast changed the new body's physical preview size")
		quit(1)
		return
	main.free()
	if not Net.valid_packet(PackedFloat32Array([4, 1, 0, 0, -1, 0, 0, 0, 0.0025])):
		quit(1)
		return
	var body = preload("res://scripts/body_view.gd").new()
	body.setup(1, Palette.ROCKY)
	body.set_physical(0.003, 0.0025, 0.0, 0.0)
	body.set_display_size(2.0, 1.0)
	if body.physical_radius != 0.0025 or body.rendered_radius < 1.0:
		push_error("Visual enlargement altered physical radius or failed to enlarge the mesh")
		quit(1)
		return
	body.set_display_size(0.0, 1.0)
	if body.rendered_radius != body.physical_radius or body.physical_radius != 0.0025:
		push_error("Physical size mode changed the authoritative radius")
		quit(1)
		return
	body.free()
	var masses := [1e-12, 0.00002, 0.003, 0.03, 1.0, 80.0, 1000.0, 20000.0]
	var radii := []
	for kind in range(Palette.TYPE_KEYS.size()):
		var row := []
		for mass in masses:
			row.append(Palette.illustrative_radius(kind, mass))
		radii.append(row)
	var presets := []
	for preset in Hud.PRESETS:
		presets.append(preset[0])
	var constants: Dictionary = Palette.new().get_script().get_script_constant_map()
	var ids := {}
	for key in constants:
		if key.begins_with("EV_") or key.to_lower() in Palette.TYPE_KEYS:
			ids[key] = constants[key]
	print("CONTRACT_JSON:", JSON.stringify({"ids": ids, "keys": Palette.TYPE_KEYS,
		"masses": Palette.DEFAULT_MASS, "samples": masses, "radii": radii,
		"presets": presets, "port": Net.SERVER_PORT, "protocol": Net.PROTOCOL_VERSION,
		"kinds": [Net.STATE_KIND, Net.PREDICTION_KIND],
		"layout": [Main.HEADER, Main.BODY, Main.EVENT]}))
	quit()
