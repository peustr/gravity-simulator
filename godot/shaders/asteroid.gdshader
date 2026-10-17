// Lumpy, faceted space rock that glows when freshly made in an impact.
shader_type spatial;
render_mode blend_mix, cull_back;

#include "res://shaders/noise.gdshaderinc"

uniform float seed = 0.0;
uniform float heat : hint_range(0.0, 1.0) = 0.0;
uniform vec3 base_color : source_color = vec3(0.45, 0.42, 0.38);

varying vec3 obj_dir;

void vertex() {
	vec3 n = normalize(VERTEX);
	float d = fbm3(n * 2.2 + vec3(seed * 5.0));
	VERTEX = n * (0.7 + 0.6 * d);
	obj_dir = n;
}

void fragment() {
	NORMAL = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
	float f = fbm3(obj_dir * 6.0 + vec3(seed));
	ALBEDO = base_color * (0.55 + 0.7 * f) * (1.0 - 0.7 * heat);
	ROUGHNESS = 0.95;
	SPECULAR = 0.1;
	vec3 glow = mix(vec3(1.0, 0.2, 0.03), vec3(1.0, 0.75, 0.35), heat);
	EMISSION = glow * heat * heat * 3.0;
}
