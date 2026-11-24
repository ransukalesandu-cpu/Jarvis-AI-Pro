import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/app.css';
import './styles/taskflow.css';
import './styles/holo-theme.css';
import './styles/components.css';
// Self-hosted Sinhala font (no CDN): only the Sinhala subset, regular and semibold.
import '@fontsource/noto-sans-sinhala/sinhala-400.css';
import '@fontsource/noto-sans-sinhala/sinhala-600.css';

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        <App />
    </StrictMode>,
);
