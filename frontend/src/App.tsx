import { Suspense, useEffect } from 'react';
import { HologramScene } from './hologram/HologramScene';
import { startBridge, stopBridge } from './bridge/bridge';
import { useUi } from './store';
import { ActivityWidget, BatteryWidget, BrainWidget, ClockWidget, NetworkWidget, SystemWidget } from './ui/Widgets';
import { NavPanel, TopBar } from './ui/Chrome';
import { SettingsPanel } from './ui/Settings';
import { PageView } from './ui/Pages';
import { Tray, Windows } from './ui/Windows';
import { Palette } from './ui/Palette';
import { useWindows } from './workspace/windows';
import { sendRequest } from './bridge/bridge';

export default function App() {
  const link = useUi((s) => s.link);
  const pageOpen = useUi((s) => s.page !== 'home');
  const settingsOpen = useUi((s) => s.settingsOpen);
  const toggleNav = useUi((s) => s.toggleNav);
  const toggleSettings = useUi((s) => s.toggleSettings);
  const page = useUi((s) => s.page);
  const wins = useWindows((s) => s.windows);
  const setPalette = useUi((s) => s.setPalette);
  useEffect(() => {
    const sync = () => useWindows.getState().setViewport({ w: innerWidth, h: innerHeight });
    sync();
    addEventListener('resize', sync);
    return () => removeEventListener('resize', sync);
  }, []);
  useEffect(() => {                       // autosave the layout (debounced) once the backend link is up
    if (link !== 'connected') return;
    const id = setTimeout(() => sendRequest({ kind: 'workspace.save', name: '_last', layout: useWindows.getState().snapshot(page) }), 700);
    return () => clearTimeout(id);
  }, [wins, page, link]);
  useEffect(() => {
    void startBridge();
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(); }
      else if (e.key === 'Escape') { toggleNav(false); toggleSettings(false); }
    };
    addEventListener('keydown', onKey);
    return () => { removeEventListener('keydown', onKey); stopBridge(); };
  }, [toggleNav, toggleSettings, setPalette]);
  return (
    <div className="app" data-page={pageOpen ? 'open' : 'home'} data-settings={settingsOpen ? 'open' : 'closed'}>
      <div className="stage"><Suspense fallback={null}><HologramScene /></Suspense></div>
      <div className="vignette" />
      <TopBar />
      <div className="widgets left"><ClockWidget /><BatteryWidget /><SystemWidget /></div>
      <div className="widgets right"><BrainWidget /><NetworkWidget /><ActivityWidget /></div>
      {link === 'detached' && <div className="banner glass" role="status">Backend not connected: showing no live data</div>}
      <PageView />
      <Windows />
      <Tray />
      <Palette />
      <NavPanel />
      <SettingsPanel />
    </div>
  );
}
