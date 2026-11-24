      attribute float phase; uniform float size; uniform float time; varying float vA;
      uniform float base; uniform float gain;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float tw = 0.5 + 0.5 * sin(time * (1.2 + fract(phase * 7.3) * 2.0) + phase * 6.283);
        vA = (base + (1.0 - base) * pow(tw, 3.0)) * gain;
        gl_PointSize = size * (300.0 / -mv.z) * (0.6 + 0.8 * tw);
        gl_Position = projectionMatrix * mv;
      }
