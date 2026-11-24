float holoKeyLight(vec3 n) {
  float lam = max(dot(normalize(n), normalize(vec3(-0.45, 0.55, 0.75))), 0.0);
  return 0.30 * lam + 0.70 * pow(lam, 4.0);
}
