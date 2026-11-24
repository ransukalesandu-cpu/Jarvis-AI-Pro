import { Bot, Boxes, Brain, Home, LayoutDashboard, Menu, MonitorCog, Network, Newspaper, Settings, Sparkles, Timer, Workflow, X } from 'lucide-react';
import { useUi, type Page } from '../store';
import { Presence } from '../motion/Presence';
import { Island } from './Island';
import { PAGE_WINDOWS, TITLES, type WinKind } from '../workspace/layout';
import { useWindows } from '../workspace/windows';
import { SPACE } from '../styles/tokens';

export const PAGES: { id: Page; label: string; icon: React.ReactNode }[] = [
    { id: 'home', label: 'Home', icon: <Home size={16} /> },
    { id: 'chat', label: 'Conversation Log', icon: <Bot size={16} /> },
    { id: 'activity', label: 'Activity Center', icon: <Sparkles size={16} /> },
    { id: 'tasks', label: 'Task Progress', icon: <Network size={16} /> },
    { id: 'models', label: 'AI Models', icon: <Brain size={16} /> },
    { id: 'monitor', label: 'System Monitor', icon: <MonitorCog size={16} /> },
];

/** Working windows that are not pages: listed in the menu too, so they are reachable without a keyboard (tablet). */
export const TOOL_WINDOWS: { kind: WinKind; icon: React.ReactNode }[] = [
    { kind: 'features', icon: <Boxes size={16} /> },
    { kind: 'bento', icon: <LayoutDashboard size={16} /> },
    { kind: 'news', icon: <Newspaper size={16} /> },
    { kind: 'jobs', icon: <Workflow size={16} /> },
    { kind: 'timer', icon: <Timer size={16} /> },
];

export function TopBar() {
    const { toggleNav, toggleSettings, navOpen, settingsOpen } = useUi();
    return (
        <header className="topbar">
            <button className="icon-btn glass" onClick={() => toggleNav()} aria-label="Navigation menu" aria-expanded={navOpen} aria-controls="nav-panel">
                {navOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <Island />
            <button
                className="icon-btn glass"
                onClick={() => toggleSettings()}
                aria-label="Settings"
                aria-expanded={settingsOpen}
                aria-controls="settings-panel"
            >
                <Settings size={18} />
            </button>
        </header>
    );
}

export function NavPanel() {
    const { navOpen, page, go, toggleNav } = useUi();
    const reduced = useUi((s) => s.reducedMotion);
    const openKinds = useWindows((s) => s.windows.map((w) => w.kind).join(' '));
    const kinds = openKinds.split(' ');
    const isOpen = (id: Page) => {
        const k = PAGE_WINDOWS[id];
        return k ? kinds.includes(k) : page === id;
    };
    return (
        <Presence<HTMLElement> show={navOpen} reduced={reduced} offset={{ x: -SPACE['space-5'] }}>
            {(ref) => (
                <nav ref={ref} id="nav-panel" className="panel left glass" aria-label="Pages">
                    <h2>NAVIGATE</h2>
                    {PAGES.map((p) => (
                        <button key={p.id} className="nav-item" aria-current={isOpen(p.id) ? 'page' : undefined} onClick={() => go(p.id)}>
                            {p.icon}
                            <span>{p.label}</span>
                        </button>
                    ))}
                    <h2>WINDOWS</h2>
                    {TOOL_WINDOWS.map((t) => (
                        <button
                            key={t.kind}
                            className="nav-item"
                            aria-current={kinds.includes(t.kind) ? 'page' : undefined}
                            onClick={() => {
                                useWindows.getState().open(t.kind);
                                toggleNav(false);
                            }}
                        >
                            {t.icon}
                            <span>{TITLES[t.kind]}</span>
                        </button>
                    ))}
                </nav>
            )}
        </Presence>
    );
}
