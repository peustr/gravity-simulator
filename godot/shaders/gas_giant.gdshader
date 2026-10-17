// Banded gas giant with turbulent belts and a great storm.
shader_type spatial;
render_mode blend_mix, cull_back;

#include "res://shaders/noise.gdshaderinc"

uniform float seed = 0.0;
uniform float heat : hint_range(0.0, 1.0) = 0.0;
uniform vec3 color_a : source_color = vec3(0.85, 0.72, 0.55);
uniform vec3 color_b : source_color = vec3(0.62, 0.42, 0.28);
uniform vec3 color_c : source_color = vec3(0.95, 0.90, 0.80);
uniform float spin = 0.25;
uniform float band_freq = 14.0;

varying vec3 obj_pos;

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	vec3 p = normalize(obj_pos);
	float ang = TIME * spin;
	p.xz = mat2(vec2(cos(ang), sin(ang)), vec2(-sin(ang), cos(ang))) * p.xz;
	float lat = p.y;
	vec3 sp = p * vec3(2.0, 7.0, 2.0) + vec3(seed * 3.1, TIME * 0.02, seed * 1.7);
	float warp = fbm5(sp);
	float band = sin((lat + 0.09 * (warp - 0.5)) * band_freq + seed * 6.0) * 0.5 + 0.5;
	float fine = fbm3(vec3(p.x * 4.0, lat * 40.0, p.z * 4.0) + seed);
	vec3 col = mix(color_a, color_b, smoothstep(0.25, 0.75, band));
	col = mix(col, color_c, smoothstep(0.55, 0.95, fine) * 0.45);

	// Great storm
	vec3 storm_dir = normalize(vec3(cos(seed * 5.0), -0.35 + 0.2 * sin(seed), sin(seed * 5.0)));
	float d = length((p - storm_dir) * vec3(1.0, 2.2, 1.0));
	float storm = 1.0 - smoothstep(0.08, 0.16, d);
	col = mix(col, color_b * 1.25 + vec3(0.12, 0.02, 0.0), storm * 0.85);

	ALBEDO = col;
	ROUGHNESS = 0.85;
	SPECULAR = 0.15;
	RIM = 0.25;
	RIM_TINT = 0.5;
	float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
	EMISSION = color_c * fres * 0.04 + vec3(1.0, 0.4, 0.15) * heat * heat * 1.5;
}
