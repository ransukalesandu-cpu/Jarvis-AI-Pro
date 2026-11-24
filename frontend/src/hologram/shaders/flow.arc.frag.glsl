      uniform vec3 color; uniform float time; uniform float energy;
      varying float vAlong; varying float vArc;
      float h(float n) { return fract(sin(n) * 43758.5453); }
      void main() {
        float on = step(1.0 - energy, h(floor(time * 6.0) + vArc * 13.0));  // flicker: more arcs live with more energy
        float a = on * (0.75 + 0.25 * h(floor(time * 20.0) + vArc));
        vec3 c = mix(color, vec3(1.0, 0.95, 0.85), 0.55);
        gl_FragColor = vec4(c * a, a);
      }
