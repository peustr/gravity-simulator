// Camera-facing soft glow (star coronas, gas clouds, flashes).
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled;

#include "res://shaders/noise.gdshaderinc"

uniform vec3 color : source_color = vec3(1.0, 0.8, 0.5);
uniform float intensity = 1.0;
uniform float seed = 0.0;
uniform float core = 0.0;        // extra bright pinpoint in the centre
uniform float rays = 0.0;        // corona streamers
uniform float falloff = 5.0;

void vertex() {
	MODELVIEW_MATRIX = billboard_modelview(VIEW_MATRIX, INV_VIEW_MATRIX, MODEL_MATRIX);
}

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float d = length(c);
	if (d > 1.0) {
		discard;
	}
	float g = exp(-d * d * falloff) - exp(-falloff);
	float a = atan(c.y, c.x);
	float n = vnoise(vec3(c * 2.5, TIME * 0.15 + seed));
	float streak = pow(vnoise(vec3(cos(a) * 3.0, sin(a) * 3.0, seed + TIME * 0.05)), 3.0) * rays * exp(-d * 2.5);
	float pin = exp(-d * d * 120.0) * core;
	float v = g * (0.8 + 0.4 * n) + streak + pin;
	ALBEDO = color * intensity * v;
	ALPHA = clamp(v, 0.0, 1.0);
}
