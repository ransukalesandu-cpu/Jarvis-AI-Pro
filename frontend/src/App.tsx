import { useEffect } from 'react';
import { HologramScene } from './hologram/HologramScene';
import { PerfOverlay } from './hologram/engine/PerfOverlay';
import { hasWebGL2 } from './hologram/engine/capability';
import { RendererGuard } from './hologram/engine/RendererGuard';
import { startBridge, stopBridge } from './bridge/bridge';
import { useUi } from './store';
import { ActivityWidget, BatteryWidget, BrainWidget, ClockWidget, NetworkWidget, SystemWidget, VoiceLinkWidget } from './ui/Widgets';
import { NavPanel, TopBar } from './ui/Chrome';
import { SettingsPanel } from './ui/Settings';
import { Tray, Windows } from './ui/Windows';
import { Palette } from './ui/Palette';
import { CommandBar } from './ui/CommandBar';
import { ReplyPanel } from './ui/Reply';
import { Controls } from './ui/Controls';
import { PendingWatch, StartupSkeleton, useStartupLoading, SyncStatus, Toast } from './ui/Feedback';
import { useWindows } from './workspace/windows';
import { gutterCovered } from './workspace/layout';
import { sendRequest } from './bridge/bridge';
import { TaskFlowWindow } from './taskflow/TaskFlowWindow';
import { useFlows } from './taskflow/flows';

export default function App() {
    const link = useUi((s) => s.link);
    const settingsOpen = useUi((s) => s.settingsOpen);
    const toggleNav = useUi((s) => s.toggleNav);
    const toggleSettings = useUi((s) => s.toggleSettings);
    const page = useUi((s) => s.page);
    const wins = useWindows((s) => s.windows);
    const setPalette = useUi((s) => s.setPalette);
    const loading = useStartupLoading();
    const pageRequested = useFlows((s) => s.pageRequested);
    const reducedMotion = useUi((s) => s.reducedMotion);
    const gutters = {
        left: useWindows((s) => gutterCovered(s.windows, s.viewport, 'left')),
        right: useWindows((s) => gutterCovered(s.windows, s.viewport, 'right')),
    };
    const clock24 = useUi((s) => s.clock24);
    const prefsLoaded = useUi((s) => s.prefsLoaded);
    const taskflowAutoShow = useFlows((s) => s.autoShow);
    const centerStyle = useUi((s) => s.centerStyle);
    const faceStyle = useUi((s) => s.faceStyle);
    useEffect(() => {
        // save UI prefs in Python: the page's own storage is wiped every launch
        if (link !== 'connected' || !prefsLoaded) return;
        const id = setTimeout(() => sendRequest({ kind: 'prefs.save', prefs: { reducedMotion, clock24, taskflowAutoShow, centerStyle, faceStyle } }), 300);
        return () => clearTimeout(id);
    }, [link, prefsLoaded, reducedMotion, clock24, taskflowAutoShow, centerStyle, faceStyle]);
    useEffect(() => {
        if (pageRequested) useUi.getState().go('tasks');
    }, [pageRequested]); // "open the task progress page"
    useEffect(() => {
        const sync = () => useWindows.getState().setViewport({ w: innerWidth, h: innerHeight });
        sync();
        addEventListener('resize', sync);
        return () => removeEventListener('resize', sync);
    }, []);
    useEffect(() => {
        // autosave the layout (debounced) once the backend link is up
        if (link !== 'connected') return;
        const id = setTimeout(() => sendRequest({ kind: 'workspace.save', name: '_last', layout: useWindows.getState().snapshot(page) }), 700);
        return () => clearTimeout(id);
    }, [wins, page, link]);
    useEffect(() => {
        void startBridge();
        const onKey = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setPalette();
            } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
                e.preventDefault();
                dispatchEvent(new Event('jarvis:focus-command'));
            } else if (e.key === 'Escape') {
                toggleNav(false);
                toggleSettings(false);
            }
        };
        addEventListener('keydown', onKey);
        return () => {
            removeEventListener('keydown', onKey);
            stopBridge();
        };
    }, [toggleNav, toggleSettings, setPalette]);
    return (
        <div
            className="app"
            data-reduced={reducedMotion ? 'true' : 'false'}
            data-settings={settingsOpen ? 'open' : 'closed'}
            data-left-covered={gutters.left ? 'true' : 'false'}
            data-right-covered={gutters.right ? 'true' : 'false'}
            data-loading={loading ? 'true' : 'false'}
        >
            <div className="stage" role="region" aria-label="JARVIS hologram">
                <RendererGuard webgl2={hasWebGL2()} scene={(onLost) => <HologramScene onContextLost={onLost} />} />
                <PerfOverlay />
            </div>
            <div className="vignette" />
            <TopBar />
            <div className="widgets left">
                <ClockWidget />
                <BatteryWidget />
                <SystemWidget />
                <VoiceLinkWidget />
            </div>
            <div className="widgets right">
                <BrainWidget />
                <NetworkWidget />
                <ActivityWidget />
            </div>
            {link === 'detached' && (
                <div className="banner glass" role="status">
                    Backend not connected: showing no live data
                </div>
            )}
            <StartupSkeleton />
            <SyncStatus />
            <Windows />
            <TaskFlowWindow />
            <Tray />
            <ReplyPanel />
            <CommandBar />
            <Controls />
            <Palette />
            <NavPanel />
            <SettingsPanel />
            <Toast />
            <PendingWatch />
        </div>
    );
}
