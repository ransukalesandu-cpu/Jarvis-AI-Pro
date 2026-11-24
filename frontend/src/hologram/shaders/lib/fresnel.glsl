float holoFresnel(vec3 n, vec3 v, float power) {
  return pow(1.0 - abs(dot(normalize(n), normalize(v))), power);
}
