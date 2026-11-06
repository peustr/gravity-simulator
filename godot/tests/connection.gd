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
	var still_connected: bool = client.connected
	while sender.get_available_packet_count() > 0:
		sender.get_packet()
	client.clock += 5.0  # The UI did not poll while a shader/window stalled.
	client._process(.01)
	var resumed: bool = client.connected
	deadline = Time.get_ticks_msec()+1000
	while sender.get_available_packet_count() == 0 and Time.get_ticks_msec()<deadline:
		await tree.process_frame
	var heartbeat: bool = sender.get_available_packet_count() > 0 and JSON.parse_string(sender.get_packet().get_string_from_utf8()).get("cmd") == "hello"
	# A second stall must not renew an unanswered probe indefinitely.
	client.clock += TIMEOUT+.1
	client._process(.01)
	var timed_out: bool = not client.connected
	# Regular polling must still detect a loss after TIMEOUT, without a stall.
	sender.put_packet(JSON.stringify({"type":"info", "protocol":PROTOCOL_VERSION}).to_utf8_buffer())
	deadline = Time.get_ticks_msec()+1000
	while client.udp.get_available_packet_count() == 0 and Time.get_ticks_msec()<deadline:
		await tree.process_frame
	client._process(0)
	var reconnected: bool = client.connected
	for elapsed in [.5,.5,.6]:
		client.clock += elapsed
		client._process(elapsed)
	var regular_timeout: bool = not client.connected
	client.udp.close()
	sender.close()
	client.free()
	if not received or not still_connected or not resumed or not heartbeat or not timed_out or not reconnected or not regular_timeout:
		push_error("Slow packet handling caused a false timeout or hid a real disconnect")
	return received and still_connected and resumed and heartbeat and timed_out and reconnected and regular_timeout
