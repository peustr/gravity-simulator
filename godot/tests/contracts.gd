extends SceneTree

const Net = preload("res://scripts/net_client.gd")
const Palette = preload("res://scripts/palette.gd")
const Main = preload("res://scripts/main.gd")
const Hud = preload("res://scripts/hud.gd")
var failures := 0

func check(condition: bool, label: String) -> void:
	if not condition:
		failures += 1
		printerr("FAIL: " + label)

func _initialize() -> void:
	var path := ProjectSettings.globalize_path("res://").path_join("../docs/contract.json")
	var contract = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not contract is Dictionary:
		printerr("Missing generated contract")
		quit(1)
		return
	check(Net.SERVER_PORT == contract.port, "port")
	check(Main.HEADER == contract.header and Main.BODY == contract.body and Main.EVENT == contract.event, "packet layout")
	for key in contract.types:
		var index := int(contract.types[key])
		check(Palette.TYPE_KEYS[index] == key, "body type " + key)
		check(Palette.DEFAULT_MASS[index] == contract.default_mass[index], "mass " + key)
	var constants = Palette.new().get_script().get_script_constant_map()
	for key in contract.events:
		check(constants[key] == contract.events[key], "event " + key)
	var presets: Array = []
	for preset in Hud.PRESETS:
		presets.append(preset[0])
	check(presets == contract.presets, "scenario names")
	for sample in contract.radius_samples:
		check(is_equal_approx(Palette.radius_for(int(sample[0]), sample[1]), sample[2]), "radius formula")
	check(Net.valid_packet(PackedFloat32Array([1, 0, 0, 0, 0, 0, 0, 10, 1, 600])), "empty state")
	check(Net.valid_packet(PackedFloat32Array([2, 0, 0, 0, -1, 0, 0, 0])), "empty forecast")
	for packet in [[], [1], [2], [1, 0, 0, 0, -1, 0, 0, 10, 1, 600],
		[1, 0, 0, 0, 0.5, 0, 0, 10, 1, 600], [2, 0, 1, 0, -1, 0, 0, 0],
		[1, 0, NAN, 0, 0, 0, 0, 10, 1, 600], [3, 0]]:
		check(not Net.valid_packet(PackedFloat32Array(packet)), "reject malformed packet")
	if failures == 0:
		print("Godot contract tests PASSED.")
	quit(1 if failures else 0)
