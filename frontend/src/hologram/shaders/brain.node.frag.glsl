      uniform vec3 color; uniform vec3 core; uniform vec3 tint;
      varying float vGlow; varying float vFire;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float disc = smoothstep(0.5, 0.15, d);
        float a = clamp(disc * (vGlow + vFire), 0.0, 1.0);
        vec3 c = mix(color, core, clamp(vFire + smoothstep(0.2, 0.0, d) * 0.6, 0.0, 1.0)) * tint;
        gl_FragColor = vec4(c * a, a);
      }
