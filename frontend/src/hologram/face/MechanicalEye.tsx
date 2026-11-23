import { useEffect, useMemo } from 'react';
import { AdditiveBlending, Color, MeshBasicMaterial, RingGeometry, type ShaderMaterial } from 'three';
import { COLORS } from '../palette';
import { MASK_INNER } from './iris';
import { irisGeometry, irisMaterial, poseIris } from './irisMaterial';

/** Eye-space radius 1 = this many world units. */
export const EYE_SCALE = 0.13;

export interface IrisParts {
    geometry: ReturnType<typeof irisGeometry>;
    material: ShaderMaterial;
}

export function makeIris(): IrisParts {
    const geometry = irisGeometry();
    poseIris(geometry, 0.55);
    return { geometry, material: irisMaterial() };
}

/**
 * A mechanical eye: the shader emission (iris glow, pupil, scan ring) behind a nine-blade aperture
 * iris (one mesh, posed by the head every frame), inside a dark socket ring with an orange rim.
 * Drawn over the face plates (no depth test), like the circuit eyes, because it sits in the socket.
 */
export function MechanicalEye({ emission, iris }: { emission: ShaderMaterial; iris: IrisParts }) {
    const ring = useMemo(
        () => ({
            mask: new RingGeometry(MASK_INNER, 1.3, 64),
            maskMat: new MeshBasicMaterial({ color: new Color('#15171b'), transparent: true, depthTest: false, depthWrite: false }),
            rim: new RingGeometry(MASK_INNER - 0.03, MASK_INNER + 0.01, 64),
            outer: new RingGeometry(1.26, 1.3, 64),
            rimMat: new MeshBasicMaterial({
                color: new Color(COLORS.eye),
                transparent: true,
                opacity: 0.9,
                blending: AdditiveBlending,
                depthTest: false,
                depthWrite: false,
            }),
        }),
        [],
    );
    useEffect(
        () => () => {
            Object.values(ring).forEach((r) => r.dispose());
        },
        [ring],
    );
    return (
        <group scale={EYE_SCALE}>
            <mesh material={emission} renderOrder={6}>
                <planeGeometry args={[2.6, 2.6]} />
            </mesh>
            <mesh geometry={iris.geometry} material={iris.material} renderOrder={7} />
            <mesh geometry={ring.mask} material={ring.maskMat} renderOrder={8} />
            <mesh geometry={ring.rim} material={ring.rimMat} renderOrder={9} />
            <mesh geometry={ring.outer} material={ring.rimMat} renderOrder={9} />
        </group>
    );
}
