// The "rubber sheet" picture of gravity: a grid that sags into the
// gravitational potential (proportional to -sum of m / r) of the heaviest
// nearby bodies. It is a teaching picture, not literal spacetime curvature,
// but it shows at a glance where the deep gravity wells are.
shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled, fog_disabled, shadows_disabled;

uniform vec4 wells[16];          // xyz = position, w = mass
uniform int well_count = 0;
uniform float depth_scale = 0.0;
uniform float spacing = 10.0;
uniform vec3 center = vec3(0.0);
uniform float fade_radius = 500.0;
uniform float opacity = 0.0;
uniform vec3 line_color : source_color = vec3(0.35, 0.55, 1.0);

varying vec3 wpos;
varying float sag;

void vertex() {
	vec3 w = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float pot = 0.0;
	for (int i = 0; i < 16; i++) {
		if (i >= well_count) {
			break;
		}
		vec4 b = wells[i];
		vec2 d = w.xz - b.xz;
		float soft = max(spacing * 0.8, 1.0);
		pot += b.w / sqrt(dot(d, d) + soft * soft);
	}
	sag = pot * depth_scale;
	w.y -= sag;
	wpos = w;
	POSITION = PROJECTION_MATRIX * VIEW_MATRIX * vec4(w, 1.0);
}

void fragment() {
	vec2 coord = wpos.xz / spacing;
	vec2 g = abs(fract(coord - 0.5) - 0.5) / max(fwidth(coord), vec2(1e-5));
	float minor = 1.0 - min(min(g.x, g.y), 1.0);
	vec2 coord5 = coord / 5.0;
	vec2 g5 = abs(fract(coord5 - 0.5) - 0.5) / max(fwidth(coord5), vec2(1e-5));
	float major = 1.0 - min(min(g5.x, g5.y), 1.0);
	float dist = length(wpos.xz - center.xz);
	float fade = 1.0 - smoothstep(fade_radius * 0.35, fade_radius, dist);
	float deep = clamp(sag / (fade_radius * 0.25), 0.0, 1.0);
	vec3 col = mix(line_color, vec3(0.85, 0.5, 1.0), deep);
	float a = max(minor * 0.18, major * 0.45) * fade * opacity;
	ALBEDO = col * a;
	ALPHA = clamp(a, 0.0, 1.0);
}
