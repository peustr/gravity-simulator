extends CanvasLayer
## On-screen interface, built in code so it is easy to read and tweak.

signal tool_selected(tool: int)          # -1 = select / inspect
signal mass_changed(tool: int, mult: float)
signal pause_toggled
signal speed_step(direction: int)
signal preset_chosen(preset: String)
signal clear_requested
signal follow_requested
signal delete_requested
signal supernova_requested
signal relaunch_requested

const Palette = preload("res://scripts/palette.gd")

const PRESETS := [
	["solar", "Solar system", "A Sun, rocky planets, moons, an asteroid belt and ringed giants."],
	["binary", "Binary stars", "Two suns locked in orbit, with planets on the edge of chaos."],
	["black_hole", "Black hole feast", "A star on a plunging orbit gets spaghettified."],
	["smash", "Planet smash", "Two Earths on a collision course."],
	["formation", "Planet formation", "200 planetesimals collide and grow."],
	["galaxies", "Colliding galaxies", "Two black-hole-centred galaxies fly past each other and throw out tidal tails."],
	["empty", "Empty space", "Nothing but you and the void."],
]

const C_TEXT := Color(0.86, 0.90, 0.97)
const C_DIM := Color(0.60, 0.66, 0.78)
const C_ACCENT := Color(0.45, 0.65, 1.0)
const C_GOOD := Color(0.45, 0.9, 0.6)
const C_WARN := Color(1.0, 0.75, 0.35)
const C_BAD := Color(1.0, 0.45, 0.4)

var root: Control
var ui_visible := true
var tool_buttons := {}
var _tool_group := ButtonGroup.new()
var _mass_values := {}
var _current_tool := -1

var mass_box: VBoxContainer
var mass_slider: HSlider
var mass_label: Label
var status_dot: Panel
var status_label: Label
var pause_btn: Button
var speed_label: Label
var time_label: Label
var bodies_label: Label
var perf_label: Label
var inspector: PanelContainer
var insp_title: Label
var insp_type: Label
var insp_grid: GridContainer
var insp_values := {}
var nova_btn: Button
var follow_btn: Button
var feed: VBoxContainer
var hint_label: Label
var cursor_label: Label
var overlay: Control
var overlay_text: Label
var welcome: Control
var help: Control
var toast_label: Label
var _toast_tw: Tween


func _ready() -> void:
	layer = 10
	root = Control.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.theme = _make_theme()
	add_child(root)
	_build_top_bar()
	_build_toolbar()
	_build_inspector()
	_build_feed()
	_build_hint()
	_build_overlay()
	_build_welcome()
	_build_help()
	cursor_label = Label.new()
	cursor_label.add_theme_font_size_override("font_size", 13)
	cursor_label.add_theme_color_override("font_color", Color(1, 0.95, 0.8))
	cursor_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	cursor_label.add_theme_constant_override("outline_size", 4)
	cursor_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(cursor_label)
	toast_label = Label.new()
	toast_label.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	toast_label.position.y = 84
	toast_label.add_theme_font_size_override("font_size", 18)
	toast_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.9))
	toast_label.add_theme_constant_override("outline_size", 6)
	toast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	toast_label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	toast_label.modulate.a = 0.0
	toast_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(toast_label)
	select_tool(-1, false)


# ------------------------------------------------------------------ theme
func _make_theme() -> Theme:
	var t := Theme.new()
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Noto Sans", "DejaVu Sans", "Arial"])
	font.antialiasing = TextServer.FONT_ANTIALIASING_GRAY
	t.default_font = font
	t.default_font_size = 15

	var panel := StyleBoxFlat.new()
	panel.bg_color = Color(0.03, 0.045, 0.085, 0.82)
	panel.set_corner_radius_all(12)
	panel.set_border_width_all(1)
	panel.border_color = Color(0.5, 0.65, 1.0, 0.16)
	panel.set_content_margin_all(12)
	panel.shadow_color = Color(0, 0, 0, 0.35)
	panel.shadow_size = 10
	t.set_stylebox("panel", "PanelContainer", panel)

	for type_name in ["Button", "MenuButton"]:
		t.set_stylebox("normal", type_name, _btn_box(Color(1, 1, 1, 0.045), Color(1, 1, 1, 0.06)))
		t.set_stylebox("hover", type_name, _btn_box(Color(0.45, 0.62, 1.0, 0.16), Color(0.5, 0.7, 1.0, 0.3)))
		t.set_stylebox("pressed", type_name, _btn_box(Color(0.45, 0.62, 1.0, 0.30), Color(0.55, 0.75, 1.0, 0.7)))
		t.set_stylebox("hover_pressed", type_name, _btn_box(Color(0.45, 0.62, 1.0, 0.36), Color(0.6, 0.8, 1.0, 0.8)))
		t.set_stylebox("disabled", type_name, _btn_box(Color(1, 1, 1, 0.02), Color(1, 1, 1, 0.03)))
		t.set_stylebox("focus", type_name, StyleBoxEmpty.new())
		t.set_color("font_color", type_name, C_TEXT)
		t.set_color("font_hover_color", type_name, Color.WHITE)
		t.set_color("font_pressed_color", type_name, Color.WHITE)
		t.set_color("font_hover_pressed_color", type_name, Color.WHITE)
		t.set_color("font_disabled_color", type_name, Color(1, 1, 1, 0.3))
		t.set_constant("h_separation", type_name, 8)

	var popup := StyleBoxFlat.new()
	popup.bg_color = Color(0.04, 0.06, 0.11, 0.97)
	popup.set_corner_radius_all(10)
	popup.set_border_width_all(1)
	popup.border_color = Color(0.5, 0.65, 1.0, 0.2)
	popup.set_content_margin_all(8)
	t.set_stylebox("panel", "PopupMenu", popup)
	var hov := StyleBoxFlat.new()
	hov.bg_color = Color(0.45, 0.62, 1.0, 0.22)
	hov.set_corner_radius_all(6)
	t.set_stylebox("hover", "PopupMenu", hov)
	t.set_color("font_color", "PopupMenu", C_TEXT)
	t.set_color("font_hover_color", "PopupMenu", Color.WHITE)
	t.set_constant("v_separation", "PopupMenu", 8)
	t.set_stylebox("panel", "TooltipPanel", popup)
	t.set_color("font_color", "TooltipLabel", C_TEXT)

	t.set_color("font_color", "Label", C_TEXT)
	t.set_constant("separation", "HBoxContainer", 8)
	t.set_constant("separation", "VBoxContainer", 6)

	var track := StyleBoxFlat.new()
	track.bg_color = Color(1, 1, 1, 0.08)
	track.set_corner_radius_all(3)
	track.content_margin_top = 3
	track.content_margin_bottom = 3
	t.set_stylebox("slider", "HSlider", track)
	var fill := StyleBoxFlat.new()
	fill.bg_color = Color(0.45, 0.65, 1.0, 0.75)
	fill.set_corner_radius_all(3)
	fill.content_margin_top = 3
	fill.content_margin_bottom = 3
	t.set_stylebox("grabber_area", "HSlider", fill)
	t.set_stylebox("grabber_area_highlight", "HSlider", fill)
	var sep := StyleBoxLine.new()
	sep.color = Color(1, 1, 1, 0.08)
	sep.thickness = 1
	t.set_stylebox("separator", "HSeparator", sep)
	return t


func _btn_box(bg: Color, border: Color) -> StyleBoxFlat:
	var b := StyleBoxFlat.new()
	b.bg_color = bg
	b.set_corner_radius_all(8)
	b.set_border_width_all(1)
	b.border_color = border
	b.content_margin_left = 10
	b.content_margin_right = 10
	b.content_margin_top = 6
	b.content_margin_bottom = 6
	return b


func _button(text: String, tooltip := "") -> Button:
	var b := Button.new()
	b.text = text
	b.tooltip_text = tooltip
	b.focus_mode = Control.FOCUS_NONE
	return b


func _label(text: String, size := 15, color := C_TEXT) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


# ------------------------------------------------------------------ top bar
func _build_top_bar() -> void:
	var bar := PanelContainer.new()
	bar.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	bar.offset_left = 12
	bar.offset_right = -12
	bar.offset_top = 12
	root.add_child(bar)
	var h := HBoxContainer.new()
	h.add_theme_constant_override("separation", 10)
	bar.add_child(h)

	var title := _label("GRAVITY SIMULATOR", 16, Color(1, 1, 1))
	title.add_theme_constant_override("outline_size", 0)
	h.add_child(title)

	status_dot = Panel.new()
	status_dot.custom_minimum_size = Vector2(10, 10)
	status_dot.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	var dot_box := StyleBoxFlat.new()
	dot_box.bg_color = C_BAD
	dot_box.set_corner_radius_all(5)
	status_dot.add_theme_stylebox_override("panel", dot_box)
	h.add_child(status_dot)
	status_label = _label("Physics offline", 13, C_DIM)
	h.add_child(status_label)

	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	h.add_child(spacer)

	pause_btn = _button("Pause", "Pause / resume time  (Space)")
	pause_btn.custom_minimum_size.x = 84
	pause_btn.pressed.connect(func(): pause_toggled.emit())
	h.add_child(pause_btn)
	var slower := _button("-", "Slow down time  (minus key)")
	slower.pressed.connect(func(): speed_step.emit(-1))
	h.add_child(slower)
	speed_label = _label("x1", 15)
	speed_label.custom_minimum_size.x = 54
	speed_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	h.add_child(speed_label)
	var faster := _button("+", "Speed up time  (plus key)")
	faster.pressed.connect(func(): speed_step.emit(1))
	h.add_child(faster)

	time_label = _label("t = 0", 14, C_DIM)
	time_label.custom_minimum_size.x = 92
	h.add_child(time_label)
	bodies_label = _label("0 bodies", 14, C_DIM)
	bodies_label.custom_minimum_size.x = 92
	h.add_child(bodies_label)
	perf_label = _label("", 13, C_GOOD)
	perf_label.custom_minimum_size.x = 120
	h.add_child(perf_label)

	var scen := MenuButton.new()
	scen.text = "Scenarios"
	scen.focus_mode = Control.FOCUS_NONE
	scen.flat = false
	var pm := scen.get_popup()
	for i in range(PRESETS.size()):
		pm.add_item(PRESETS[i][1], i)
		pm.set_item_tooltip(i, PRESETS[i][2])
	pm.id_pressed.connect(func(i: int): preset_chosen.emit(PRESETS[i][0]))
	h.add_child(scen)
	var clear := _button("Clear", "Remove everything")
	clear.pressed.connect(func(): clear_requested.emit())
	h.add_child(clear)
	var help_btn := _button("Help", "Controls and tips  (H)")
	help_btn.pressed.connect(toggle_help)
	h.add_child(help_btn)


# ------------------------------------------------------------------ toolbar
func _build_toolbar() -> void:
	var panel := PanelContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER_LEFT)
	panel.offset_left = 12
	panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	panel.custom_minimum_size.x = 214
	root.add_child(panel)
	var v := VBoxContainer.new()
	panel.add_child(v)
	v.add_child(_label("CREATE", 12, C_DIM))

	var entries := [[-1, "Select", "Q"]]
	for i in range(Palette.TOOL_TYPES.size()):
		var t: int = Palette.TOOL_TYPES[i]
		entries.append([t, Palette.TYPE_LABELS[t], str(i + 1)])
	for e in entries:
		var t: int = e[0]
		var b := _button("  " + e[1], "%s  (key %s)" % [e[1], e[2]])
		b.toggle_mode = true
		b.button_group = _tool_group
		b.alignment = HORIZONTAL_ALIGNMENT_LEFT
		b.icon = _make_icon(t)
		b.expand_icon = false
		b.pressed.connect(func(): select_tool(t))
		var key := _label(e[2], 12, C_DIM)
		key.set_anchors_and_offsets_preset(Control.PRESET_CENTER_RIGHT)
		key.offset_left = -22
		key.offset_right = -10
		b.add_child(key)
		v.add_child(b)
		tool_buttons[t] = b

	mass_box = VBoxContainer.new()
	v.add_child(mass_box)
	mass_box.add_child(HSeparator.new())
	var mh := HBoxContainer.new()
	mh.add_child(_label("Mass", 13, C_DIM))
	mass_label = _label("", 13, C_TEXT)
	mass_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mass_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	mh.add_child(mass_label)
	mass_box.add_child(mh)
	mass_slider = HSlider.new()
	mass_slider.min_value = -1.0
	mass_slider.max_value = 1.0
	mass_slider.step = 0.01
	mass_slider.value = 0.0
	mass_slider.focus_mode = Control.FOCUS_NONE
	mass_slider.custom_minimum_size.y = 22
	mass_slider.value_changed.connect(_on_mass_slider)
	mass_box.add_child(mass_slider)
	var desc := _label("", 12, C_DIM)
	desc.name = "MassDesc"
	mass_box.add_child(desc)


func _on_mass_slider(value: float) -> void:
	if _current_tool < 0:
		return
	_mass_values[_current_tool] = value
	_refresh_mass_label()
	mass_changed.emit(_current_tool, pow(10.0, value))


func _refresh_mass_label() -> void:
	if _current_tool < 0:
		return
	var mult := pow(10.0, mass_slider.value)
	var m: float = Palette.DEFAULT_MASS[_current_tool] * mult
	mass_label.text = Palette.friendly_mass(m, _current_tool)
	(mass_box.get_node("MassDesc") as Label).text = "%s  ·  x%s default" % [Palette.describe_mass(_current_tool, mult), _fmt_mult(mult)]


func _fmt_mult(m: float) -> String:
	if m >= 10.0: return "%d" % int(round(m))
	if m >= 1.0: return "%.1f" % m
	return "%.2f" % m


func mass_mult(tool: int) -> float:
	return pow(10.0, _mass_values.get(tool, 0.0))


func select_tool(t: int, emit := true) -> void:
	_current_tool = t
	for key in tool_buttons:
		tool_buttons[key].set_pressed_no_signal(key == t)
	mass_box.visible = t >= 0
	if t >= 0:
		mass_slider.set_value_no_signal(_mass_values.get(t, 0.0))
		_refresh_mass_label()
	if emit:
		tool_selected.emit(t)


func _make_icon(t: int) -> ImageTexture:
	var s := 22
	var img := Image.create_empty(s, s, false, Image.FORMAT_RGBA8)
	var c := Vector2(s / 2.0 - 0.5, s / 2.0 - 0.5)
	for y in range(s):
		for x in range(s):
			var p := Vector2(x, y) - c
			var d := p.length()
			var col := Color(0, 0, 0, 0)
			match t:
				-1:
					var ring := absf(d - 7.0) < 1.0
					var cross := (x == 11 or y == 11) and d < 10.0 and d > 3.0
					if ring or cross:
						col = Color(0.8, 0.86, 1.0)
				Palette.ROCKY:
					if d < 8.5:
						var land := sin(p.x * 0.7) + cos(p.y * 0.9 + p.x * 0.3) > 0.6
						col = Color(0.35, 0.65, 0.35) if land else Color(0.2, 0.45, 0.95)
						col = col.darkened(clampf((p.x + p.y) / 24.0, 0.0, 0.5))
				Palette.GAS_GIANT:
					if d < 9.0:
						var band := sin(p.y * 1.1) > 0.0
						col = Color(0.92, 0.76, 0.52) if band else Color(0.7, 0.48, 0.3)
						col = col.darkened(clampf((p.x + p.y) / 24.0, 0.0, 0.5))
				Palette.STAR:
					var g := clampf(1.0 - d / 10.5, 0.0, 1.0)
					col = Color(1.0, 0.85 + 0.15 * g, 0.4 + 0.5 * g, clampf(g * 2.2, 0.0, 1.0))
				Palette.NEUTRON_STAR:
					var core := clampf(1.0 - d / 4.0, 0.0, 1.0)
					var beam := clampf(1.0 - absf(p.x + p.y * 0.4) / 1.5, 0.0, 1.0) * clampf(1.0 - d / 11.0, 0.0, 1.0)
					var a := maxf(core, beam * 0.8)
					col = Color(0.7, 0.88, 1.0, a)
				Palette.BLACK_HOLE:
					var ring := clampf(1.0 - absf(d - 7.0) / 2.2, 0.0, 1.0)
					if d < 5.5:
						col = Color(0, 0, 0, 1)
					elif ring > 0.0:
						col = Color(1.0, 0.6 + 0.3 * ring, 0.25, ring)
				Palette.ASTEROID:
					var rr := 6.5 + 1.5 * sin(atan2(p.y, p.x) * 3.0) + sin(atan2(p.y, p.x) * 7.0)
					if d < rr:
						col = Color(0.62, 0.6, 0.56).darkened(clampf((p.x + p.y) / 20.0, 0.0, 0.5))
			img.set_pixel(x, y, col)
	return ImageTexture.create_from_image(img)


# ------------------------------------------------------------------ inspector
func _build_inspector() -> void:
	inspector = PanelContainer.new()
	inspector.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	inspector.offset_right = -12
	inspector.offset_top = 76
	inspector.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	inspector.custom_minimum_size.x = 290
	inspector.visible = false
	root.add_child(inspector)
	var v := VBoxContainer.new()
	inspector.add_child(v)
	insp_title = _label("", 20, Color.WHITE)
	v.add_child(insp_title)
	insp_type = _label("", 13, C_ACCENT)
	v.add_child(insp_type)
	v.add_child(HSeparator.new())
	insp_grid = GridContainer.new()
	insp_grid.columns = 2
	insp_grid.add_theme_constant_override("h_separation", 14)
	insp_grid.add_theme_constant_override("v_separation", 4)
	v.add_child(insp_grid)
	for key in ["Mass", "Radius", "Speed", "Orbiting", "Distance", "Surface", "Age"]:
		insp_grid.add_child(_label(key, 13, C_DIM))
		var val := _label("", 13, C_TEXT)
		insp_grid.add_child(val)
		insp_values[key] = val
	v.add_child(HSeparator.new())
	var h := HBoxContainer.new()
	v.add_child(h)
	follow_btn = _button("Follow", "Keep the camera on this body  (F)")
	follow_btn.toggle_mode = true
	follow_btn.toggled.connect(func(_on: bool): follow_requested.emit())
	h.add_child(follow_btn)
	var del := _button("Delete", "Remove this body  (Delete)")
	del.pressed.connect(func(): delete_requested.emit())
	h.add_child(del)
	nova_btn = _button("Supernova!", "Make this star explode  (N)")
	nova_btn.add_theme_color_override("font_color", Color(1.0, 0.75, 0.5))
	nova_btn.pressed.connect(func(): supernova_requested.emit())
	h.add_child(nova_btn)


func show_inspector(info: Dictionary) -> void:
	if info.is_empty():
		inspector.visible = false
		return
	inspector.visible = ui_visible
	insp_title.text = info.get("name", "")
	insp_type.text = info.get("type", "")
	insp_type.add_theme_color_override("font_color", info.get("color", C_ACCENT))
	for key in insp_values:
		var val: String = info.get(key, "")
		insp_values[key].text = val
		insp_values[key].visible = val != ""
		var idx: int = insp_values[key].get_index()
		insp_grid.get_child(idx - 1).visible = val != ""
	nova_btn.visible = info.get("can_nova", false)
	follow_btn.set_pressed_no_signal(info.get("following", false))


# ------------------------------------------------------------------ feed / hint
func _build_feed() -> void:
	feed = VBoxContainer.new()
	feed.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	feed.offset_left = 18
	feed.offset_bottom = -64
	feed.grow_vertical = Control.GROW_DIRECTION_BEGIN
	feed.custom_minimum_size.x = 520
	feed.mouse_filter = Control.MOUSE_FILTER_IGNORE
	feed.add_theme_constant_override("separation", 4)
	root.add_child(feed)


func push_event(text: String, color := C_TEXT) -> void:
	for c in feed.get_children():
		if c is Label and c.text == text and c.modulate.a > 0.3:
			return
	var l := _label(text, 14, color)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	l.add_theme_constant_override("outline_size", 5)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.custom_minimum_size.x = 520
	feed.add_child(l)
	while feed.get_child_count() > 6:
		var old := feed.get_child(0)
		feed.remove_child(old)
		old.queue_free()
	var tw := l.create_tween()
	l.modulate.a = 0.0
	tw.tween_property(l, "modulate:a", 1.0, 0.25)
	tw.tween_interval(7.0)
	tw.tween_property(l, "modulate:a", 0.0, 1.5)
	tw.tween_callback(l.queue_free)


func toast(text: String) -> void:
	toast_label.text = text
	if _toast_tw != null and _toast_tw.is_valid():
		_toast_tw.kill()
	_toast_tw = toast_label.create_tween()
	toast_label.modulate.a = 1.0
	_toast_tw.tween_interval(1.4)
	_toast_tw.tween_property(toast_label, "modulate:a", 0.0, 0.6)


func _build_hint() -> void:
	var p := PanelContainer.new()
	p.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	p.offset_bottom = -14
	p.grow_horizontal = Control.GROW_DIRECTION_BOTH
	p.grow_vertical = Control.GROW_DIRECTION_BEGIN
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.03, 0.045, 0.085, 0.6)
	sb.set_corner_radius_all(16)
	sb.content_margin_left = 16
	sb.content_margin_right = 16
	sb.content_margin_top = 6
	sb.content_margin_bottom = 6
	p.add_theme_stylebox_override("panel", sb)
	root.add_child(p)
	hint_label = _label("", 13, C_DIM)
	p.add_child(hint_label)


func set_hint(text: String) -> void:
	hint_label.text = text


func set_cursor_text(text: String, pos: Vector2, color := Color(1, 0.95, 0.8)) -> void:
	cursor_label.text = text
	cursor_label.visible = text != "" and ui_visible
	cursor_label.position = pos + Vector2(18, 14)
	cursor_label.add_theme_color_override("font_color", color)


# ------------------------------------------------------------------ stats
func set_connection(state: String, detail: String) -> void:
	var col := C_GOOD if state == "online" else (C_WARN if state == "starting" else C_BAD)
	(status_dot.get_theme_stylebox("panel") as StyleBoxFlat).bg_color = col
	status_label.text = detail


func set_stats(sim_time: float, n: int, max_n: int, speed_mult: float, paused: bool, perf: float) -> void:
	pause_btn.text = "Play" if paused else "Pause"
	speed_label.text = "x" + _fmt_mult(speed_mult)
	time_label.text = "t = %s" % _fmt_time(sim_time)
	bodies_label.text = "%d bodies" % n
	bodies_label.add_theme_color_override("font_color", C_WARN if n > max_n * 0.85 else C_DIM)
	if status_label.text == "Physics offline":
		perf_label.text = ""
	elif paused:
		perf_label.text = "Paused"
		perf_label.add_theme_color_override("font_color", C_WARN)
	elif perf < 0.9:
		perf_label.text = "Physics at %d%%" % int(perf * 100.0)
		perf_label.tooltip_text = "The simulation can't keep up with the requested speed. Fewer bodies or a lower speed will help."
		perf_label.add_theme_color_override("font_color", C_WARN)
	else:
		perf_label.text = "Real-time"
		perf_label.add_theme_color_override("font_color", C_GOOD)


func _fmt_time(t: float) -> String:
	if t < 10000.0:
		return "%.1f" % t
	return "%dk" % int(t / 1000.0)


# ------------------------------------------------------------------ overlays
func _center_panel(width: float) -> Array:
	var cc := CenterContainer.new()
	cc.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	cc.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(cc)
	var p := PanelContainer.new()
	p.custom_minimum_size.x = width
	cc.add_child(p)
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 10)
	p.add_child(v)
	return [cc, v]


func _build_overlay() -> void:
	var parts := _center_panel(560)
	overlay = parts[0]
	var v: VBoxContainer = parts[1]
	v.add_child(_label("Waiting for the physics server...", 22, Color.WHITE))
	overlay_text = _label("", 14, C_TEXT)
	overlay_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	overlay_text.custom_minimum_size.x = 530
	v.add_child(overlay_text)
	var steps := _label(
		"The physics runs in a separate Python program. To start it by hand:\n" +
		"  1. Open the gravity-simulator folder.\n" +
		"  2. Double-click  start_physics_server.bat\n" +
		"     (first time only: run setup_physics_server.bat before that).\n" +
		"  3. Leave its window open - this screen will disappear by itself.\n\n" +
		"See README.md, section \"Troubleshooting\", if it still won't connect.", 13, C_DIM)
	steps.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	steps.custom_minimum_size.x = 530
	v.add_child(steps)
	var retry := _button("Try to start it automatically again")
	retry.pressed.connect(func(): relaunch_requested.emit())
	v.add_child(retry)
	overlay.visible = false


func show_overlay(show_it: bool, detail := "") -> void:
	overlay.visible = show_it
	if detail != "":
		overlay_text.text = detail


func _build_welcome() -> void:
	var parts := _center_panel(640)
	welcome = parts[0]
	var v: VBoxContainer = parts[1]
	v.add_child(_label("Welcome to Gravity Simulator", 26, Color.WHITE))
	var sub := _label("Every body pulls on every other body - real N-body physics by REBOUND. " +
		"Pick a body on the left and click into space to build your own system, or start with a scenario:", 14, C_TEXT)
	sub.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	sub.custom_minimum_size.x = 610
	v.add_child(sub)
	var g := GridContainer.new()
	g.columns = 2
	g.add_theme_constant_override("h_separation", 10)
	g.add_theme_constant_override("v_separation", 10)
	v.add_child(g)
	for pr in PRESETS:
		var b := _button(pr[1], pr[2])
		b.custom_minimum_size = Vector2(300, 44)
		var key: String = pr[0]
		b.pressed.connect(func(): preset_chosen.emit(key))
		g.add_child(b)
	var tip := _label("Tip: press H at any time for all controls.", 12, C_DIM)
	v.add_child(tip)
	welcome.visible = false


func show_welcome(show_it: bool) -> void:
	welcome.visible = show_it


func _build_help() -> void:
	var parts := _center_panel(720)
	help = parts[0]
	var v: VBoxContainer = parts[1]
	v.add_child(_label("Controls", 24, Color.WHITE))
	var g := GridContainer.new()
	g.columns = 2
	g.add_theme_constant_override("h_separation", 24)
	g.add_theme_constant_override("v_separation", 5)
	v.add_child(g)
	var rows := [
		["Left click (body tool)", "Place a body in a circular orbit around whatever pulls hardest there"],
		["Left drag (body tool)", "Launch it instead - the arrow sets direction and speed"],
		["Shift + click (Asteroid)", "Create an asteroid belt - near a planet, it makes a ring"],
		["Click / double-click", "Inspect a body / follow it with the camera (Select tool)"],
		["Right drag  or  Alt + left drag", "Orbit the camera"],
		["Middle drag  or  W A S D", "Pan the camera"],
		["Mouse wheel / pinch", "Zoom"],
		["1 - 6,   Q or Esc", "Choose a body tool,  back to Select"],
		["Space,   -  /  +", "Pause,  slow down / speed up time"],
		["F,  Delete,  N", "Follow,  delete,  supernova (selected star)"],
		["T,  G", "Trails (off / short / long),  gravity grid"],
		["R,  Tab,  F12", "Reset view,  hide interface,  save screenshot"],
	]
	for r in rows:
		g.add_child(_label(r[0], 13, C_ACCENT))
		var d := _label(r[1], 13, C_TEXT)
		d.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		d.custom_minimum_size.x = 400
		g.add_child(d)
	v.add_child(HSeparator.new())
	var notes := _label(
		"What you are seeing: gravity is computed between every pair of bodies with REBOUND's IAS15 integrator. " +
		"Slow impacts merge, fast ones shatter bodies into fragments, bodies that stray inside a Roche limit are torn apart, " +
		"gas giants that grow past ~80 Jupiters ignite into stars, and black holes swallow whatever crosses their horizon. " +
		"Sizes are exaggerated so you can see things - just like every space game.", 12, C_DIM)
	notes.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	notes.custom_minimum_size.x = 690
	v.add_child(notes)
	var close := _button("Close  (H)")
	close.pressed.connect(toggle_help)
	v.add_child(close)
	help.visible = false


func toggle_help() -> void:
	help.visible = not help.visible


func hide_help() -> bool:
	var was := help.visible
	help.visible = false
	return was


func toggle_ui() -> void:
	ui_visible = not ui_visible
	for c in root.get_children():
		if c == overlay or c == toast_label:
			continue
		if c == inspector:
			continue
		if c == welcome or c == help:
			if not ui_visible:
				c.visible = false
			continue
		c.visible = ui_visible
	if not ui_visible:
		inspector.visible = false
