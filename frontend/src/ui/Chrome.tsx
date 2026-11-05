import { Bot, Brain, Clock, FolderOpen, Globe, Home, Menu, MonitorCog, Settings, Shield, Sparkles, Workflow, AppWindow, X } from 'lucide-react';
import { useUi, type Page } from '../store';
import { motion, AnimatePresence } from 'motion/react';
import { Island } from './Island';

export const PAGES: { id: Page; label: string; icon: React.ReactNode; ready: boolean; phase?: string }[] = [
  { id: 'home', label: 'Home', icon: <Home size={16} />, ready: true },
  { id: 'chat', label: 'Conversation Log', icon: <Bot size={16} />, ready: true },
  { id: 'activity', label: 'Activity Center', icon: <Sparkles size={16} />, ready: true },
  { id: 'models', label: 'AI Models', icon: <Brain size={16} />, ready: true },
  { id: 'research', label: 'Web Research', icon: <Globe size={16} />, ready: false, phase: 'Phase 2' },
  { id: 'reminders', label: 'Reminders', icon: <Clock size={16} />, ready: false, phase: 'Phase 2' },
  { id: 'apps', label: 'Applications', icon: <AppWindow size={16} />, ready: false, phase: 'Phase 2' },
  { id: 'files', label: 'Files & Media', icon: <FolderOpen size={16} />, ready: false, phase: 'Phase 2' },
  { id: 'memory', label: 'Memory', icon: <Brain size={16} />, ready: false, phase: 'Phase 2' },
  { id: 'automation', label: 'Automation', icon: <Workflow size={16} />, ready: false, phase: 'Phase 3' },
  { id: 'monitor', label: 'System Monitor', icon: <MonitorCog size={16} />, ready: true },
  { id: 'security', label: 'Security', icon: <Shield size={16} />, ready: false, phase: 'Phase 3' },
];

export function TopBar() {
  const { toggleNav, toggleSettings, navOpen, settingsOpen } = useUi();
  return (
    <header className="topbar">
      <button className="icon-btn glass" onClick={() => toggleNav()} aria-label="Navigation menu" aria-expanded={navOpen} aria-controls="nav-panel">
        {navOpen ? <X size={18} /> : <Menu size={18} />}
      </button>
      <Island />
      <button className="icon-btn glass" onClick={() => toggleSettings()} aria-label="Settings" aria-expanded={settingsOpen} aria-controls="settings-panel"><Settings size={18} /></button>
    </header>
  );
}

export function NavPanel() {
  const { navOpen, page, go } = useUi();
  const reduced = useUi((s) => s.reducedMotion);
  return (
    <AnimatePresence>
      {navOpen && (
        <motion.nav id="nav-panel" className="panel left glass" aria-label="Pages"
          initial={{ opacity: 0, x: reduced ? 0 : -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: reduced ? 0 : -24 }} transition={{ duration: reduced ? 0 : 0.22 }}>
          <h2>NAVIGATE</h2>
          {PAGES.map((p) => (
            <button key={p.id} className="nav-item" aria-current={page === p.id ? 'page' : undefined} disabled={!p.ready} onClick={() => go(p.id)}
              style={!p.ready ? { opacity: 0.45, cursor: 'not-allowed' } : undefined} title={p.ready ? undefined : `${p.phase}: needs a backend connection that does not exist yet`}>
              {p.icon}<span>{p.label}</span>{!p.ready && <span style={{ marginLeft: 'auto', fontSize: 10, letterSpacing: '0.1em' }}>{p.phase}</span>}
            </button>
          ))}
        </motion.nav>
      )}
    </AnimatePresence>
  );
}
