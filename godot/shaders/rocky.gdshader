// Procedural rocky planet: continents, oceans, ice caps, a thin atmosphere,
// and glowing lava cracks when the planet is molten after an impact.
shader_type spatial;
render_mode blend_mix, cull_back;

#include "res://shaders/noise.gdshaderinc"

uniform float seed = 0.0;
uniform float heat : hint_range(0.0, 1.0) = 0.0;
uniform vec3 ocean_color : source_color = vec3(0.04, 0.16, 0.42);
uniform vec3 land_color : source_color = vec3(0.22, 0.42, 0.18);
uniform vec3 high_color : source_color = vec3(0.62, 0.54, 0.38);
uniform vec3 atmo_color : source_color = vec3(0.35, 0.6, 1.0);
uniform float water_level = 0.5;
uniform float spin = 0.15;

varying vec3 obj_pos;

void vertex() {
	obj_pos = VERTEX;
}

void fragment() {
	float ang = TIME * spin;
	vec3 p = normalize(obj_pos);
	p.xz = mat2(vec2(cos(ang), sin(ang)), vec2(-sin(ang), cos(ang))) * p.xz;
	vec3 q = p * 2.3 + vec3(seed * 13.1, seed * 7.7, seed * 3.3);
	float h = fbm5(q);
	float lat = abs(p.y);

	vec3 col;
	float wet = 1.0 - smoothstep(water_level - 0.01, water_level + 0.01, h);
	vec3 sea = mix(ocean_color * 0.55, ocean_color, smoothstep(water_level - 0.2, water_level, h));
	vec3 land = mix(land_color, high_color, smoothstep(water_level + 0.05, water_level + 0.3, h));
	col = mix(land, sea, wet);
	float ice = smoothstep(0.78, 0.9, lat + 0.12 * (h - 0.5));
	col = mix(col, vec3(0.92, 0.95, 1.0), ice);

	// Molten crust: darken and add glowing cracks.
	float cracks = 1.0 - smoothstep(0.0, 0.08, abs(fbm3(q * 3.0 + vec3(TIME * 0.05)) - 0.5));
	col = mix(col, col * 0.25, heat);

	ALBEDO = col;
	ROUGHNESS = mix(0.95, 0.35, wet * (1.0 - ice));
	SPECULAR = mix(0.2, 0.45, wet);
	float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 4.0);
	RIM = 0.4 * length(atmo_color);
	RIM_TINT = 0.6;
	vec3 lava = mix(vec3(1.0, 0.18, 0.02), vec3(1.0, 0.65, 0.2), cracks);
	EMISSION = atmo_color * fres * 0.06 + lava * heat * (0.3 + 3.5 * cracks) * heat;
}
