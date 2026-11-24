vec3 holoDisplace(vec3 p, vec3 n, float time, float amount) {
  float w = sin(p.y * 9.0 + time * 1.7) * sin(p.x * 7.0 - time * 1.3);
  return p + n * w * amount;
}
