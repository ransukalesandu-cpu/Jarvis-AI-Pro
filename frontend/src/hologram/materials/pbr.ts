/**
 * Lit materials for the mechanical face: titanium, black chrome and carbon fibre. MeshPhysicalMaterial
 * lit by a RoomEnvironment PMREM map (built into Three, nothing downloaded) plus a key and a rim
 * light. Every factory takes a typed params object so palettes and personas can swap them.
 */
import { Color, DataTexture, MeshPhysicalMaterial, PMREMGenerator, RepeatWrapping, RGBAFormat, type Texture, type WebGLRenderer } from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { stageCss } from '../stageColor';

export interface MetalParams {
    color?: string;
    roughness?: number;
    clearcoat?: number;
    emissive?: string;
    emissiveIntensity?: number;
}

export function titanium(p: MetalParams = {}): MeshPhysicalMaterial {
    return new MeshPhysicalMaterial({
        color: new Color(p.color ?? stageCss('stage-pbr-metal')),
        metalness: 1,
        roughness: p.roughness ?? 0.38,
        clearcoat: p.clearcoat ?? 0.25,
        clearcoatRoughness: 0.4,
        emissive: new Color(p.emissive ?? stageCss('stage-black')),
        emissiveIntensity: p.emissiveIntensity ?? 0,
    });
}

export function blackChrome(p: MetalParams = {}): MeshPhysicalMaterial {
    return new MeshPhysicalMaterial({
        color: new Color(p.color ?? stageCss('stage-pbr-chrome')),
        metalness: 1,
        roughness: p.roughness ?? 0.16,
        clearcoat: p.clearcoat ?? 1,
        clearcoatRoughness: 0.08,
        emissive: new Color(p.emissive ?? stageCss('stage-black')),
        emissiveIntensity: p.emissiveIntensity ?? 0,
    });
}

/** A 2x2 twill weave as a tangent-space normal map, generated once (64 x 64, no file). */
export function weaveNormalMap(size = 64): DataTexture {
    const data = new Uint8Array(size * size * 4);
    const cell = size / 4;
    for (let y = 0; y < size; y++)
        for (let x = 0; x < size; x++) {
            const cx = Math.floor(x / cell),
                cy = Math.floor(y / cell);
            const warp = (cx + cy) % 2 === 0; // which tow is on top
            const u = ((warp ? y : x) % cell) / cell; // across the tow
            const slope = Math.cos(u * Math.PI) * 0.6; // rounded tow profile
            const nx = warp ? 0 : slope,
                ny = warp ? slope : 0,
                nz = Math.sqrt(Math.max(0, 1 - slope * slope));
            const o = (y * size + x) * 4;
            data[o] = Math.round((nx * 0.5 + 0.5) * 255);
            data[o + 1] = Math.round((ny * 0.5 + 0.5) * 255);
            data[o + 2] = Math.round((nz * 0.5 + 0.5) * 255);
            data[o + 3] = 255;
        }
    const tex = new DataTexture(data, size, size, RGBAFormat);
    tex.wrapS = tex.wrapT = RepeatWrapping;
    tex.needsUpdate = true;
    return tex;
}

export function carbon(normalMap: Texture, p: MetalParams = {}): MeshPhysicalMaterial {
    return new MeshPhysicalMaterial({
        color: new Color(p.color ?? stageCss('stage-pbr-black')),
        metalness: 0.2,
        roughness: p.roughness ?? 0.45,
        clearcoat: p.clearcoat ?? 0.8,
        clearcoatRoughness: 0.15,
        normalMap,
    });
}

/** The studio reflection map for the lit parts; dispose the returned texture with the scene. */
export function roomEnvironment(gl: WebGLRenderer): Texture {
    const pm = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const tex = pm.fromScene(room, 0.04).texture;
    room.dispose?.();
    pm.dispose();
    return tex;
}
