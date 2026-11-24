      attribute float along; attribute float arc; attribute vec3 side;
      uniform float time; uniform float amp; uniform float count;
      varying float vAlong; varying float vArc;
      float h(float n) { return fract(sin(n) * 43758.5453); }
      float n1(float x) { float i = floor(x), f = fract(x); return mix(h(i), h(i + 1.0), f * f * (3.0 - 2.0 * f)) * 2.0 - 1.0; }
      void main() {
        vAlong = along; vArc = arc;
        float tick = floor(time * 14.0);
        float pin = sin(3.14159 * along);                                   // fixed at both ends
        float j = n1(along * 9.0 + arc * 17.0 + tick * 3.1) * 0.7 + n1(along * 23.0 + tick * 7.7 + arc) * 0.3;
        vec3 p = position + side * j * amp * pin;
        if (arc >= count) p = vec3(0.0, 0.0, -100.0);                      // arcs beyond the profile's count
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }
