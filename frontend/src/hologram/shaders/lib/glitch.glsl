#include "lygia/generative/random.glsl"
float glitchBand(float y, float time, float chance) {
  float slot = floor(time * 8.0);
  if (random(slot) > chance) return 0.0;
  float centre = random(slot + 17.0) * 2.0 - 1.0;
  float width = 0.02 + 0.05 * random(slot + 31.0);
  return 1.0 - smoothstep(0.0, width, abs(y - centre));
}
