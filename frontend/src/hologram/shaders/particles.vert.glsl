        attribute float phase; attribute float radius; attribute float speed; attribute float spin;
        uniform float time; uniform float scale; uniform float size; uniform float y0; uniform float y1;
        varying float vA;
        void main() {
          float life = fract(time * speed + phase);
          float ang = time * spin + phase * 6.2831853;
          float rad = radius * sin(3.14159 * life) * (0.55 + 0.45 * life);
          vec3 p = vec3(cos(ang) * rad, mix(y0, y1, life), sin(ang) * rad * 0.6 + 0.1);
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vA = sin(3.14159 * life);
          gl_PointSize = size * scale / -mv.z;
          gl_Position = projectionMatrix * mv;
        }
