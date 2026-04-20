import React from 'react';
import './styles.css';
import { createRoot } from 'react-dom/client';
import { App } from './App';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root missing from index.html');

createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
