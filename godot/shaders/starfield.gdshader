// Procedural night sky: three layers of stars with real-ish colours, a faint
// Milky Way band with dust lanes, and a couple of distant nebulae.
shader_type sky;

#include "res://shaders/noise.gdshaderinc"

uniform float star_brightness = 1.0;
uniform float milky_way = 1.0;

vec3 star_tint(float h) {
	// From cool red to hot blue, weighted towards white/yellow.
	vec3 red = vec3(1.0, 0.62, 0.45);
	vec3 yellow = vec3(1.0, 0.9, 0.75);
	vec3 white = vec3(0.95, 0.97, 1.0);
	vec3 blue = vec3(0.7, 0.8, 1.0);
	if (h < 0.2) return mix(red, yellow, h / 0.2);
	if (h < 0.7) return mix(yellow, white, (h - 0.2) / 0.5);
	return mix(white, blue, (h - 0.7) / 0.3);
}

vec3 star_layer(vec3 dir, float scale, float density, float size, float bright) {
	vec3 p = dir * scale;
	vec3 cell = floor(p);
	float h = hash13(cell);
	if (h > density) {
		return vec3(0.0);
	}
	vec3 jitter = hash33(cell) * 0.4 + 0.3;
	vec3 sdir = normalize(cell + jitter);
	float d = length(cross(dir, sdir)) * scale;
	float b = exp(-d * d / (size * size));
	float mag = pow(hash13(cell + 17.0), 8.0) * 3.0 + 0.15;
	return star_tint(hash13(cell + 5.0)) * b * mag * bright;
}

void sky() {
	vec3 dir = normalize(EYEDIR);
	vec3 col = vec3(0.0);
	col += star_layer(dir, 90.0, 0.025, 0.16, 1.3);
	col += star_layer(dir, 220.0, 0.02, 0.18, 0.6);
	col += star_layer(dir, 480.0, 0.02, 0.2, 0.3);
	col *= star_brightness;

	// Milky Way band
	vec3 axis = normalize(vec3(0.25, 1.0, 0.35));
	float band = exp(-pow(dot(dir, axis) * 3.2, 2.0));
	float clouds = fbm5(dir * 4.0 + vec3(3.0));
	float dust = smoothstep(0.45, 0.75, fbm5(dir * 7.0 + vec3(11.0)));
	vec3 mw = mix(vec3(0.35, 0.38, 0.55), vec3(0.6, 0.5, 0.42), clouds) * band * (0.3 + 0.7 * clouds) * (1.0 - 0.75 * dust);
	col += mw * 0.07 * milky_way;
	// dense star haze inside the band
	col += star_layer(dir, 900.0, 0.08 * band, 0.25, 0.18) * band;

	// Nebulae
	float neb1 = smoothstep(0.55, 0.85, fbm5(dir * 2.2 + vec3(5.0, 1.0, 2.0)));
	float neb2 = smoothstep(0.6, 0.9, fbm5(dir * 2.6 + vec3(-4.0, 7.0, 1.0)));
	col += vec3(0.45, 0.12, 0.35) * neb1 * 0.035 * milky_way;
	col += vec3(0.08, 0.25, 0.45) * neb2 * 0.03 * milky_way;

	COLOR = col;
}
