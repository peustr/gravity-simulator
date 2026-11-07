extends RefCounted
## Resampling authoritative poses must preserve whole turns and stop at data ends.
const View = preload("res://scripts/body_view.gd")
const Net = preload("res://scripts/net_client.gd")


static func check(tree: SceneTree) -> bool:
	var view = View.new()
	tree.root.add_child(view)
	view.setup(1,0)
	view.set_physical(.003,.0025,0,0)
	var start := Quaternion(Vector3.RIGHT,.3)
	var rate := TAU*10+.7
	view.set_rotation_state(0,start,Vector3.UP*rate,1,1)
	view.set_rotation_state(1,Quaternion(Vector3.UP,rate)*start,Vector3.UP*rate,1,1)
	for t in [0.0,.25,.7,1.0,2.0]:
		view.present_rotation(t)
		var expected := Quaternion(Vector3.UP,rate*minf(t,1))*start
		var actual: Quaternion = view._surface.quaternion
		if (actual*Vector3.RIGHT-expected*Vector3.RIGHT).length() > .00001 or (actual*Vector3.UP-expected*Vector3.UP).length() > .00001:
			push_error("Orientation resampling aliased a whole turn or advanced beyond its snapshots")
			view.free()
			return false
	view.present_rotation(.7)
	var paused: Quaternion = view._surface.quaternion
	view._process(10)
	view.present_rotation(.7)
	if view._surface.quaternion != paused:
		push_error("Paused orientation used wall time")
		view.free()
		return false
	view.set_rotation_state(1,start,Vector3.ZERO,0,0)
	if view.spin_status != 0:
		view.free()
		return false
	view.set_type(1)
	var cleared: bool = view._rotations.is_empty()
	view.free()
	var packet := PackedFloat32Array([5,1,0,2,1, 1,1,0,0,0,1,0,2,0,100])
	if not cleared or not Net.valid_packet(packet):
		return false
	for i in [1,3,4,6,10,14]:
		var bad := packet.duplicate()
		bad[i] = 2 if i == 10 else -1
		if Net.valid_packet(bad):
			push_error("Malformed orientation packet was accepted")
			return false
	return true
