// Star surface: boiling granulation, sunspots and limb darkening.
// Brightness above 1.0 feeds the glow (bloom) post-process.
shader_type spatial;
render_mode unshaded, cull_back;

#include "res://shaders/noise.gdshaderinc"

uniform float seed = 0.0;
uniform vec3 star_color : source_color = vec3(1.0, 0.9, 0.7);
uniform float intensity = 4.0;

varying vec3 obj_pos;

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	vec3 p = normalize(obj_pos);
	float t = TIME * 0.04;
	float n = fbm5(p * 5.0 + vec3(seed, t, -t));
	float g = fbm3(p * 22.0 + vec3(t * 3.0, seed, 0.0));
	float spots = smoothstep(0.62, 0.72, fbm3(p * 3.0 + vec3(seed * 2.0, t * 0.3, 0.0)));
	float mu = clamp(dot(NORMAL, VIEW), 0.0, 1.0);
	float limb = 0.35 + 0.65 * pow(mu, 0.45);
	vec3 c = star_color * (0.7 + 0.45 * n + 0.25 * g) * (1.0 - 0.55 * spots);
	ALBEDO = c * limb * intensity;
}
