// Small, fast value-noise helpers shared by the body shaders.

float hash13(vec3 p3) {
	p3 = fract(p3 * 0.1031);
	p3 += dot(p3, p3.zyx + 31.32);
	return fract((p3.x + p3.y) * p3.z);
}

vec3 hash33(vec3 p3) {
	p3 = fract(p3 * vec3(0.1031, 0.1030, 0.0973));
	p3 += dot(p3, p3.yxz + 33.33);
	return fract((p3.xxy + p3.yxx) * p3.zyx);
}

float vnoise(vec3 x) {
	vec3 i = floor(x);
	vec3 f = fract(x);
	f = f * f * (3.0 - 2.0 * f);
	float n000 = hash13(i);
	float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
	float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
	float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
	float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
	float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
	float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
	float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
	return mix(mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
	           mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y), f.z);
}

float fbm3(vec3 p) {
	float a = 0.5;
	float s = 0.0;
	for (int i = 0; i < 3; i++) {
		s += a * vnoise(p);
		p = p * 2.03 + vec3(1.7, 9.2, 3.1);
		a *= 0.5;
	}
	return s / 0.875;
}

float fbm5(vec3 p) {
	float a = 0.5;
	float s = 0.0;
	for (int i = 0; i < 5; i++) {
		s += a * vnoise(p);
		p = p * 2.03 + vec3(1.7, 9.2, 3.1);
		a *= 0.5;
	}
	return s / 0.96875;
}

// Billboard: face the camera, keep the node's uniform scale.
mat4 billboard_modelview(mat4 view, mat4 inv_view, mat4 model) {
	float s = length(model[0].xyz);
	return view * mat4(inv_view[0] * s, inv_view[1] * s, inv_view[2] * s, model[3]);
}

// Optional NDC-radius cap for cosmetic effects, including during camera motion.
// A zero limit preserves the physical/display size of normal body graphics.
mat4 limited_billboard_modelview(mat4 view, mat4 inv_view, mat4 model, float projection_y, float limit) {
	mat4 mv = billboard_modelview(view, inv_view, model);
	if (limit > 0.0) {
		float bound = max(0.0, -mv[3].z) * limit / max(projection_y, 0.000001);
		float factor = min(1.0, bound / max(length(model[0].xyz), 0.000000000001));
		mv[0] *= factor;
		mv[1] *= factor;
		mv[2] *= factor;
	}
	return mv;
}
