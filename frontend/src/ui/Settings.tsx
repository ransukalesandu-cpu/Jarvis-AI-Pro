import { useUi } from '../store';
import { motion, AnimatePresence } from 'motion/react';

const LATER = ['Voice & Audio', 'AI Provider', 'Adaptive Performance', 'Notifications', 'Privacy & Security', 'Permissions', 'Workspace Preferences'];

/** Only settings that actually do something are interactive; the rest are listed as not yet connected. */
export function SettingsPanel() {
  const { settingsOpen, reducedMotion, setReducedMotion, clock24, setClock24, persona, link } = useUi();
  return (
    <AnimatePresence>
      {settingsOpen && (
        <motion.aside id="settings-panel" className="panel right glass" aria-label="Settings"
          initial={{ opacity: 0, x: reducedMotion ? 0 : 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: reducedMotion ? 0 : 24 }} transition={{ duration: reducedMotion ? 0 : 0.22 }}>
          <h2>APPEARANCE &amp; GLASS UI</h2>
          <div className="row"><span>Reduced motion</span><button className="toggle" aria-pressed={reducedMotion} onClick={() => setReducedMotion(!reducedMotion)}>{reducedMotion ? 'On' : 'Off'}</button></div>
          <div className="row"><span>24-hour clock</span><button className="toggle" aria-pressed={clock24} onClick={() => setClock24(!clock24)}>{clock24 ? 'On' : 'Off'}</button></div>
          <h2>HOLOGRAM</h2>
          <div className="row"><span>Persona</span><span>{persona}</span></div>
          <h2>CONNECTION</h2>
          <div className="row"><span>Backend link</span><span>{link}</span></div>
          <h2>NOT YET CONNECTED</h2>
          {LATER.map((l) => <div className="row" key={l}><span style={{ color: 'var(--text-faint)' }}>{l}</span><span>Phase 3</span></div>)}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
