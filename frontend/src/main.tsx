import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App.tsx';
import './style.css';

const root = document.getElementById('root');
if (!root) throw new Error('Missing application root');
// https://react.dev/reference/react-dom/client/createRoot
createRoot(root).render(<StrictMode><App /></StrictMode>);
