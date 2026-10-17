// Gravitational lensing for black holes.
//
// A camera-facing quad samples the already-rendered screen and bends it with
// the point-mass lens equation  beta = theta - theta_E^2 / theta,  which
// produces the Einstein ring, the flipped secondary image inside it, and the
// black "shadow" where light falls into the hole. The accretion disk is drawn
// as an opaque surface, so its far side gets lensed up and over the shadow -
// the look made famous by the film Interstellar.
shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;

#include "res://shaders/noise.gdshaderinc"

uniform sampler2D screen_tex : hint_screen_texture, filter_linear_mipmap, repeat_disable;
uniform float shadow_frac = 0.26;    // shadow radius / quad half-size
uniform float einstein_frac = 0.36;  // Einstein radius / quad half-size
uniform vec3 ring_color : source_color = vec3(1.0, 0.82, 0.55);
uniform float ring_intensity = 2.5;

void vertex() {
	MODELVIEW_MATRIX = billboard_modelview(VIEW_MATRIX, INV_VIEW_MATRIX, MODEL_MATRIX);
}

void fragment() {
	vec2 c = UV * 2.0 - 1.0;
	float r = length(c);
	if (r > 1.0) {
		discard;
	}
	// How quad coordinates map to screen UVs (robust to any flips/aspect).
	vec2 dcx = dFdx(c);
	vec2 dcy = dFdy(c);
	vec2 dsx = dFdx(SCREEN_UV);
	vec2 dsy = dFdy(SCREEN_UV);
	mat2 A = mat2(dcx, dcy);
	mat2 B = mat2(dsx, dsy);
	float det = A[0][0] * A[1][1] - A[1][0] * A[0][1];
	vec3 col;
	if (abs(det) < 1e-12) {
		col = texture(screen_tex, SCREEN_UV).rgb;
	} else {
		mat2 M = B * inverse(A);
		float fade = 1.0 - smoothstep(0.45, 1.0, r);
		float re2 = einstein_frac * einstein_frac;
		float beta = r - re2 / max(r, 1e-4) * fade;
		vec2 src = c * (beta / max(r, 1e-4));
		vec2 suv = SCREEN_UV + M * (src - c);
		col = texture(screen_tex, clamp(suv, vec2(0.001), vec2(0.999))).rgb;
	}
	float rs = shadow_frac;
	float shadow = 1.0 - smoothstep(rs * 0.94, rs * 1.0, r);
	float ring = exp(-pow((r - rs * 1.06) / (rs * 0.045), 2.0));
	float flicker = 0.85 + 0.3 * vnoise(vec3(c / max(r, 1e-4) * 2.0, TIME * 0.6));
	col = mix(col, vec3(0.0), shadow);
	col += ring_color * ring * ring_intensity * flicker;
	ALBEDO = col;
	ALPHA = 1.0 - smoothstep(0.92, 1.0, r);
}
