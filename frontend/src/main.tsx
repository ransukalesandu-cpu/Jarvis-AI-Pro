import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/app.css';
import './styles/taskflow.css';
import './styles/holo-theme.css';

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
