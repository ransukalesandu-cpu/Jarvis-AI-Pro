import { useControls } from 'leva';
import { useEffect } from 'react';
import { useUi } from '../../store';

/** Development only (npm run dev): live knobs for the stage. Never part of a production build. */
export default function StageTweaks() {
    const { tier, centre, face } = useControls('Stage', {
        tier: { value: useUi.getState().perfTier ?? 'balanced', options: ['full', 'balanced', 'lite'] },
        centre: { value: useUi.getState().centerStyle, options: ['brain', 'hologram'] },
        face: { value: useUi.getState().faceStyle, options: ['circuit', 'mechanical'] },
    });
    useEffect(() => {
        useUi.setState({
            perfTier: tier as 'full' | 'balanced' | 'lite',
            centerStyle: centre as 'brain' | 'hologram',
            faceStyle: face as 'circuit' | 'mechanical',
        });
    }, [tier, centre, face]);
    return null;
}
