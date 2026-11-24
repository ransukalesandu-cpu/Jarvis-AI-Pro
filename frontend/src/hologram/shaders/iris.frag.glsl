      uniform float glow; uniform vec3 tint;
      varying float vEdge; varying float vBlade; varying vec2 vEye;
      void main() {
        if (length(vEye) > 1.28) discard;                         // under the socket ring
        float shade = 0.10 + 0.05 * fract(vBlade * 0.37) + 0.10 * (1.0 - vEdge);
        vec3 metal = vec3(0.16, 0.17, 0.20) * (0.6 + shade * 3.0);
        float lip = smoothstep(0.10, 0.0, vEdge);                 // glowing inner edge
        vec3 c = metal + vec3(1.0, 0.45, 0.08) * tint * lip * (0.5 + 0.8 * glow);
        float shadow = smoothstep(0.75, 1.0, vEdge) * 0.6;        // the next blade's shadow line
        gl_FragColor = vec4(c * (1.0 - shadow), 1.0);
      }
