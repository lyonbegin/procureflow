import React from 'react';
import { createRoot } from 'react-dom/client';
import '@xyflow/react/dist/style.css';
import './styles.css';
import App from './App.jsx';

const root = document.getElementById('root');
createRoot(root).render(<React.StrictMode><App /></React.StrictMode>);
