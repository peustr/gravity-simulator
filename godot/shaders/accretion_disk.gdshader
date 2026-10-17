// Accretion disk: Keplerian swirl (inner gas orbits fastest), a temperature
// gradient from white-hot to deep red, and relativistic Doppler beaming
// (the side rotating towards you is brighter).
// Drawn opaque (alpha scissor) so the lensing shader can bend it.
shader_type spatial;
render_mode unshaded, cull_disabled;

#include "res://shaders/noise.gdshaderinc"

uniform float seed = 0.0;
uniform float inner = 0.36;
uniform float outer = 1.0;
uniform float intensity = 2.2;
uniform float flare = 0.0;
uniform vec3 hot_color : source_color = vec3(1.0, 0.94, 0.82);
uniform vec3 warm_color : source_color = vec3(1.0, 0.55, 0.16);
uniform vec3 cool_color : source_color = vec3(0.55, 0.10, 0.03);

varying vec3 local_pos;

void vertex() {
	local_pos = VERTEX;
}

void fragment() {
	float r = length(local_pos.xz);
	float t = clamp((r - inner) / (outer - inner), 0.0, 1.0);
	float ang = atan(local_pos.z, local_pos.x);
	float omega = 0.9 / pow(max(r, 0.05), 1.5);
	float a2 = ang - TIME * omega;
	vec3 polar = vec3(cos(a2) * r * 5.0, sin(a2) * r * 5.0, r * 9.0 + seed);
	float swirl = fbm5(polar);
	float lanes = fbm3(vec3(cos(a2) * 2.0, sin(a2) * 2.0, r * 30.0 + seed));
	vec3 col = mix(hot_color, warm_color, smoothstep(0.0, 0.4, t));
	col = mix(col, cool_color, smoothstep(0.35, 1.0, t));

	// Doppler beaming: orbital direction (prograde) versus the view direction.
	vec3 tang_local = normalize(vec3(sin(ang), 0.0, -cos(ang)));
	vec3 tang_view = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(tang_local, 0.0)).xyz);
	float approach = dot(tang_view, VIEW) * sqrt(inner / max(r, inner));
	float beam = pow(clamp(1.0 + 0.75 * approach, 0.15, 2.0), 3.0);

	float bright = (0.35 + 0.9 * swirl) * (0.6 + 0.6 * lanes) * pow(1.0 - t, 1.2) * beam;
	ALBEDO = col * bright * intensity * (1.0 + 1.2 * min(flare, 1.5));

	// Soft, gassy edges via dithered alpha scissor (keeps the disk opaque).
	float edge = smoothstep(0.0, 0.05, t) * (1.0 - smoothstep(0.55, 1.0, t)) * (0.55 + 0.6 * swirl);
	ALPHA = clamp(edge, 0.0, 1.0);
	ALPHA_SCISSOR_THRESHOLD = hash13(vec3(FRAGCOORD.xy, TIME * 60.0));
}
