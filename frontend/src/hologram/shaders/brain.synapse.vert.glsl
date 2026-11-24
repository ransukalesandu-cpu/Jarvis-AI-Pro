      attribute vec3 target; attribute float along; attribute float phase; attribute float rate; attribute float lobe; attribute float span;
      attribute float nphase; attribute float wander;
      uniform float time; uniform float morph;
      varying float vAlong; varying float vPhase; varying float vAct; varying float vLife; varying float vSpan;
      void main() {
        vAlong = along; vPhase = phase; vAct = lobeAct(lobe);
        vLife = fract(time * rate + phase);
        vSpan = span;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(mix(drift(position, nphase, wander, time), target, morph), 1.0);
      }
