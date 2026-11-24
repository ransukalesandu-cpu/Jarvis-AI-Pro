      attribute float along; attribute float seed;
      varying float vAlong; varying float vSeed;
      void main() { vAlong = along; vSeed = seed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
