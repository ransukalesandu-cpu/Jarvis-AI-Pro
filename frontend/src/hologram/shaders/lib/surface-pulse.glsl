float surfacePulse(vec3 p, float time, float freq) {
  return 0.5 + 0.5 * sin(p.y * freq - time * 2.0 + sin(p.x * freq * 0.5) * 0.6);
}
