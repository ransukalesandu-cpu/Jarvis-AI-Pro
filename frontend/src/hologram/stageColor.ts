import { Color } from 'three';
import { STAGE_TOKENS, type TokenName } from '../styles/tokens';

/** A stage colour from the shared tokens (tokens/core.json, `stage-*`). The 3D stage always uses the dark set. */
export const stageHex = (name: TokenName): number => STAGE_TOKENS.dark[name].hex;
export const stageColor = (name: TokenName): Color => new Color(stageHex(name));
/** CSS hex string, for 2D canvas drawing (FaceData). */
export const stageCss = (name: TokenName): string => '#' + stageHex(name).toString(16).padStart(6, '0');
