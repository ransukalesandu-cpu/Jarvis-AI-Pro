float circuitFlow(float along, float time, float speed, float density) {
  float x = fract(along * density - time * speed);
  return smoothstep(0.0, 0.08, x) * (1.0 - smoothstep(0.08, 0.35, x));
}
