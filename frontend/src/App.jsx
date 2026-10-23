import { Route, Routes } from 'react-router-dom';
import { ToastProvider } from './components/Toast.jsx';
import Launcher from './launcher/Launcher.jsx';
import OwnerApp from './owner/OwnerApp.jsx';
import ReviewApp from './review/ReviewApp.jsx';
import ClientApp from './client/ClientApp.jsx';
import ConnectDone from './client/ConnectDone.jsx';
import './launcher/launcher.css';

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/" element={<Launcher />} />
        <Route path="/owner/*" element={<OwnerApp />} />
        <Route path="/review/*" element={<ReviewApp />} />
        <Route path="/client/*" element={<ClientApp />} />
        <Route path="/connect/done" element={<ConnectDone />} />
        <Route path="*" element={<Launcher />} />
      </Routes>
    </ToastProvider>
  );
}
