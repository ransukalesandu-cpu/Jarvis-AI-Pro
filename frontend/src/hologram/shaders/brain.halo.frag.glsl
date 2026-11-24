      uniform vec3 color; uniform float strength; uniform vec3 tint; varying vec2 vUv;
      void main() { float d = length(vUv - 0.5) * 2.0; float a = pow(max(0.0, 1.0 - d), 2.2) * strength; gl_FragColor = vec4(color * tint * a, a); }
