      attribute vec3 target; attribute float lobe; attribute float phase; attribute float wander;
      uniform float time; uniform float morph; uniform float firing; uniform float scale; uniform float size;
      varying float vGlow; varying float vFire;
      void main() {
        vec3 p = mix(drift(position, phase, wander, time), target, morph);
        float act = lobeAct(lobe) * (0.65 + 0.35 * sin(time * 2.0 + position.x * 5.0 + position.y * 3.0));
        float clock = fract(time * (0.35 + phase * 0.5) + phase * 17.0);
        float fire = (1.0 - smoothstep(0.0, 0.06, clock)) * step(phase, 0.15 + firing * 0.85);  // a share of nodes fire
        vGlow = 0.35 + 0.65 * act; vFire = fire;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = size * (1.0 + fire * 1.6 + act * 0.4) * scale / -mv.z;
        gl_Position = projectionMatrix * mv;
      }
