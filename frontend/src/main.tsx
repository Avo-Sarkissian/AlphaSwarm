import React from 'react';
// Self-hosted fonts: no CDN request, which fits local-first.
import '@fontsource-variable/jetbrains-mono';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-sans/700.css';
import './styles.css';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import { getDataSource } from './data-source';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root missing from index.html');

// Choose the data source (and install the demo's request override) before any component fetches.
getDataSource();

createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
