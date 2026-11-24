vec3 drift(vec3 p, float ph, float w, float t) {
  return p + w * 0.07 * vec3(sin(t * 0.37 + ph * 31.0), sin(t * 0.29 + ph * 17.0) * 0.8, sin(t * 0.33 + ph * 7.0));
}
