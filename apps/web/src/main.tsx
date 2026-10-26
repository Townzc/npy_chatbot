import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';

// Remove credentials persisted by the pre-session UI. Never migrate an owner
// secret into the short-lived session token slot.
sessionStorage.removeItem('chattwin.auth.v1');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
