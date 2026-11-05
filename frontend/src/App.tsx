import { Suspense, useEffect } from 'react';
import { HologramScene } from './hologram/HologramScene';
import { startBridge, stopBridge } from './bridge/bridge';
import { useUi } from './store';
import { ActivityWidget, BatteryWidget, BrainWidget, ClockWidget, NetworkWidget, SystemWidget } from './ui/Widgets';
import { NavPanel, TopBar } from './ui/Chrome';
import { SettingsPanel } from './ui/Settings';
import { PageView } from './ui/Pages';

export default function App() {
  const link = useUi((s) => s.link);
  const pageOpen = useUi((s) => s.page !== 'home');
  const settingsOpen = useUi((s) => s.settingsOpen);
  const toggleNav = useUi((s) => s.toggleNav);
  const toggleSettings = useUi((s) => s.toggleSettings);
  useEffect(() => {
    void startBridge();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { toggleNav(false); toggleSettings(false); } };
    addEventListener('keydown', onKey);
    return () => { removeEventListener('keydown', onKey); stopBridge(); };
  }, [toggleNav, toggleSettings]);
  return (
    <div className="app" data-page={pageOpen ? 'open' : 'home'} data-settings={settingsOpen ? 'open' : 'closed'}>
      <div className="stage"><Suspense fallback={null}><HologramScene /></Suspense></div>
      <div className="vignette" />
      <TopBar />
      <div className="widgets left"><ClockWidget /><BatteryWidget /><SystemWidget /></div>
      <div className="widgets right"><BrainWidget /><NetworkWidget /><ActivityWidget /></div>
      {link === 'detached' && <div className="banner glass" role="status">Backend not connected: showing no live data</div>}
      <PageView />
      <NavPanel />
      <SettingsPanel />
    </div>
  );
}
