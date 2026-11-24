      uniform float time; uniform vec2 gaze; uniform float dilate; uniform float glow; uniform float seed; uniform float open; uniform vec3 tint;
      varying vec2 vUv;
      void main() {
        vec4 e = eyeEmission(vUv, gaze, dilate, glow, time, seed);
        gl_FragColor = vec4(e.rgb * tint * open, e.a * open);
      }
