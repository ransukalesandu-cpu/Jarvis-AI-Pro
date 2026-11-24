      attribute float edge; attribute float blade;
      varying float vEdge; varying float vBlade; varying vec2 vEye;
      void main() { vEdge = edge; vBlade = blade; vEye = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
