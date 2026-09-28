import { createRoot } from 'react-dom/client';
import './index.css';
import './demo.css';
import './sangam.css';
import './design-system.css';
import { ToastProvider } from './components/ui';
import App from './App';
createRoot(document.getElementById('root')).render(<ToastProvider><App /></ToastProvider>);
