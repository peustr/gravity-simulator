extends PanelContainer
## Session encounter summary from the authoritative collision model.

signal replay_requested(case: String)
signal budgets_requested
signal inspect_requested(id: int)

var demo := {}
var report := {}
var title: Label
var details: Label
var replay: Button
var model: Label
var inspect: Button


func _ready() -> void:
	var box := VBoxContainer.new()
	add_child(box)
	title = Label.new()
	title.add_theme_font_size_override("font_size", 16)
	box.add_child(title)
	details = Label.new()
	details.add_theme_font_size_override("font_size", 13)
	details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	details.custom_minimum_size.x = 340
	box.add_child(details)
	model = Label.new()
	model.text = "Calibrated masses · prescribed rebound/ejecta"
	model.add_theme_font_size_override("font_size", 12)
	box.add_child(model)
	var buttons := HBoxContainer.new()
	box.add_child(buttons)
	replay = Button.new()
	replay.text = "Replay"
	replay.focus_mode = Control.FOCUS_NONE
	replay.pressed.connect(func(): replay_requested.emit(demo.case))
	buttons.add_child(replay)
	var budgets := Button.new()
	budgets.text = "Conservation report"
	budgets.focus_mode = Control.FOCUS_NONE
	budgets.pressed.connect(func(): budgets_requested.emit())
	buttons.add_child(budgets)
	inspect = Button.new()
	inspect.text = "Inspect · slow motion"
	inspect.focus_mode = Control.FOCUS_NONE
	inspect.pressed.connect(func(): inspect_requested.emit(int(report.get("survivor_id", -1))))
	buttons.add_child(inspect)
	hide()


func set_state(context, outcome) -> void:
	demo = context if context is Dictionary else {}
	report = outcome if outcome is Dictionary else {}
	visible = not demo.is_empty() or not report.is_empty()
	if not visible:
		return
	match report.get("regime"):
		"bound_sticking", "gentle_sticking": model.text = "Sticking assumption · conserved spin/energy"
		"contact_rebound": model.text = "Contact impulse · both bodies retained"
		"gentle_rebound": model.text = "Elastic contact assumption · both bodies retained"
		_: model.text = "Calibrated masses · prescribed rebound/ejecta"
	replay.visible = not demo.is_empty()
	inspect.visible = report.has("survivor_id")
	title.text = "Planet smash · " + str(demo.case).capitalize().replace("_", " ") if not demo.is_empty() else "Last solid impact"
	var source: Dictionary = report if not report.is_empty() else demo
	details.text = "Contact: %.2f km/s · %.1f°\n" % [float(source.speed_m_s)/1000.0, float(source.angle_deg)]
	if report.is_empty():
		details.text += "Ready · press Play to approach contact"
	else:
		var masses: Array = report.remnant_masses_kg
		var total := 0.0
		for mass in masses:
			total += float(mass)
		details.text += str(report.regime).capitalize().replace("_", " ")
		details.text += "\n%d remnants · largest %.1f%% of mass" % [masses.size(), 100.0*float(masses[0])/total]
		details.text += "\nLargest: " + _mass_label(float(masses[0]))
		if masses.size() > 1:
			details.text += "\nNext: " + _mass_label(float(masses[1]))
		if report.unresolved_fragments > 0:
			details.text += "\n%d fragments retained in compact ejecta" % report.unresolved_fragments


func _mass_label(mass: float) -> String:
	var exponent := int(floor(log(mass) / log(10.0)))
	return "%.2f × 10^%d kg" % [mass / pow(10.0, exponent), exponent]
