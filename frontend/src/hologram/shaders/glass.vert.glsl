      uniform float time; uniform float displace;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        vec3 p = holoDisplace(position, normal, time, displace);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-mv.xyz);
        vP = position;
        gl_Position = projectionMatrix * mv;
      }
