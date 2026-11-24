      uniform vec3 rim; uniform vec3 body; uniform float bodyAlpha; uniform float power; uniform float boost;
      uniform float shade; uniform float scan; uniform float pulse; uniform float time; uniform float glitch;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        float f = holoFresnel(vN, vV, power);
        float lit = shade * holoKeyLight(vN);
        vec3 c = mix(body, rim, f) + rim * lit;
        float a = clamp(bodyAlpha + lit * 0.55 + f * (0.85 + boost), 0.0, 1.0);
        a *= 1.0 - scan + scan * holoScanlines(vP.y, time, 28.0, 0.15);
        a *= 1.0 - pulse + pulse * surfacePulse(vP, time, 3.0);
        float g = glitchBand(vP.y, time, glitch);
        c = mix(c, vec3(1.0), g * 0.5); a = clamp(a + g * 0.4, 0.0, 1.0);
        gl_FragColor = vec4(c * a, a);
      }
