// A constant-size dot (in pixels) for every body, so you can still see tiny
// or distant objects when zoomed out. It fades away once the real body is
// big enough on screen.
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;

uniform vec3 color : source_color = vec3(1.0);
uniform float px_size = 8.0;
uniform float body_radius = 1.0;
uniform float boost = 1.0;

varying float fade;

void vertex() {
	vec3 center = (VIEW_MATRIX * vec4(MODEL_MATRIX[3].xyz, 1.0)).xyz;
	float dist = max(-center.z, 0.001);
	float world_per_px = 2.0 * dist / (abs(PROJECTION_MATRIX[1][1]) * VIEWPORT_SIZE.y);
	float size = px_size * world_per_px;
	float body_px = body_radius / world_per_px;
	fade = 1.0 - smoothstep(2.0, 5.0, body_px);
	MODELVIEW_MATRIX = VIEW_MATRIX * mat4(INV_VIEW_MATRIX[0] * size, INV_VIEW_MATRIX[1] * size, INV_VIEW_MATRIX[2] * size, MODEL_MATRIX[3]);
}

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float d = length(c);
	float g = exp(-d * d * 6.0) - exp(-6.0);
	ALBEDO = color * g * fade * 1.6 * boost;
	ALPHA = clamp(g * fade, 0.0, 1.0);
}
