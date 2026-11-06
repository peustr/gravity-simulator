// Camera-facing ring: shock waves, gravitational-wave ripples, and the
// selection highlight. `progress` 0..1 expands and fades the ring.
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;

#include "res://shaders/noise.gdshaderinc"

uniform vec3 color : source_color = vec3(1.0, 0.7, 0.4);
uniform float intensity = 2.0;
uniform float progress = 0.5;
uniform float thickness = 0.06;
uniform float pulse = 0.0;
uniform bool billboard = true;
uniform float max_screen_radius = 0.0;

void vertex() {
	if (billboard) {
		MODELVIEW_MATRIX = limited_billboard_modelview(VIEW_MATRIX, INV_VIEW_MATRIX, MODEL_MATRIX, PROJECTION_MATRIX[1][1], max_screen_radius);
	}
}

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float d = length(c);
	float radius = mix(0.05, 0.95, progress);
	float w = thickness * (1.0 - 0.6 * progress) + 0.004;
	float ring = exp(-pow((d - radius) / w, 2.0));
	float life = pow(1.0 - progress, 1.5);
	if (pulse > 0.0) {
		life = 0.65 + 0.35 * sin(TIME * 4.0);
	}
	float v = ring * life;
	ALBEDO = color * intensity * v;
	ALPHA = clamp(v, 0.0, 1.0);
}
