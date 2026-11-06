extends RefCounted
## A moving physical-size target must remain centred at every playback rate.

const Rig = preload("res://scripts/camera_rig.gd")


static func check(tree: SceneTree) -> bool:
	var rig = Rig.new()
	tree.root.add_child(rig)
	await tree.process_frame
	rig.distance = .003
	rig.target_distance = rig.distance
	rig.following = true
	var centre := tree.root.get_visible_rect().get_center()
	for fps in [30,60,144]:
		for speed in [.005,1.0,10.0]:
			for frame in range(60):
				var phase: float = speed*frame/float(fps)
				rig.target_focus = 60*Vector3(cos(phase),0,sin(phase))
				rig._process(1.0/fps)
				if rig.camera.is_position_behind(rig.target_focus) or rig.camera.unproject_position(rig.target_focus).distance_to(centre) > 1.0:
					push_error("Physical-size follow target left the screen centre")
					rig.free()
					return false
	var previous: Vector3 = rig.focus
	rig.following = false
	rig.target_focus += Vector3(10,0,0)
	rig._process(1.0/60)
	var eased: bool = rig.focus.x > previous.x and rig.focus.x < rig.target_focus.x
	rig.free()
	if not eased:
		push_error("Free camera pan lost its easing")
	return eased
