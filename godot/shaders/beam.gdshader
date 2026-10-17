// Light beams: pulsar beams on neutron stars and relativistic jets on
// feeding black holes. Mesh is a cone along +Y from 0 (base) to 1 (tip).
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;

#include "res://shaders/noise.gdshaderinc"

uniform vec3 color : source_color = vec3(0.6, 0.85, 1.0);
uniform float intensity = 1.0;
uniform float seed = 0.0;

varying vec3 lp;

void vertex() {
	lp = VERTEX;
}

void fragment() {
	float along = clamp(lp.y + 0.5, 0.0, 1.0);
	float edge = pow(abs(dot(NORMAL, VIEW)), 1.5);
	float n = vnoise(vec3(lp.x * 3.0, along * 6.0 - TIME * 3.0, lp.z * 3.0 + seed));
	float v = edge * pow(1.0 - along, 1.6) * (0.6 + 0.6 * n);
	ALBEDO = color * intensity * v;
	ALPHA = clamp(v, 0.0, 1.0);
}
