      uniform vec3 color; uniform vec3 core; uniform vec3 tint; uniform float time; uniform float growth; uniform float flow; uniform float morph; uniform float boost;
      varying float vAlong; varying float vPhase; varying float vAct; varying float vLife; varying float vSpan;
      void main() {
        // A synapse is alive for a share (growth) of its cycle: it grows out from its node, holds, dissolves.
        if (vLife > growth) discard;
        float grown = clamp(vLife / (growth * 0.25 + 0.001), 0.0, 1.0);
        if (vAlong > grown) discard;
        float fade = smoothstep(growth, growth * 0.75, vLife);
        float pulse = circuitFlow(vAlong + vPhase, time, flow * 0.5, 1.0);
        float a = fade * (0.05 + boost + 0.25 * vAct + pulse * (0.45 + vAct)) * (1.0 - morph * smoothstep(0.05, 0.12, vSpan));   // in a shape only very short links stay
        vec3 c = mix(color, core, pulse) * tint;
        gl_FragColor = vec4(c * a, a);
      }
