extends "res://scripts/net_client.gd"
## A state receiver can spend longer than TIMEOUT building the first scene.

var clock := 10.0


func _now() -> float:
	return clock


static func check(tree: SceneTree) -> bool:
	var client = load("res://tests/connection.gd").new()
	client._ready()
	client._launch_tried = true
	client.message_received.connect(func(_message: Dictionary): client.clock += TIMEOUT+1)
	var sender := PacketPeerUDP.new()
	if sender.bind(SERVER_PORT, SERVER_HOST) != OK:
		client.udp.close()
		client.free()
		push_error("Close the physics server before running the connection contract")
		return false
	sender.set_dest_address("127.0.0.1", client.udp.get_local_port())
	sender.put_packet(JSON.stringify({"type":"info", "protocol":PROTOCOL_VERSION}).to_utf8_buffer())
	var deadline := Time.get_ticks_msec()+1000
	while client.udp.get_available_packet_count() == 0 and Time.get_ticks_msec()<deadline:
		await tree.process_frame
	client._process(0)
	var received: bool = client.connected
	client._process(0)
	var timed_out: bool = not client.connected
	client.udp.close()
	sender.close()
	client.free()
	if not received or not timed_out:
		push_error("Slow packet handling caused a false timeout or hid a real disconnect")
	return received and timed_out
