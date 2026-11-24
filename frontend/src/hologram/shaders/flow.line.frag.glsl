      uniform vec3 color; uniform vec3 core; uniform float time; uniform float speed; uniform float base; uniform float gain;
      varying float vAlong; varying float vSeed;
      void main() {
        float f = circuitFlow(vAlong + vSeed, time, speed, 2.0);
        vec3 c = mix(color, core, f);
        float a = clamp(base * (0.8 + 0.2 * sin(time * 0.9 + vSeed * 11.0)) + f * gain, 0.0, 1.0);
        gl_FragColor = vec4(c * a, a);
      }
