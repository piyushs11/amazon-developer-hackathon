import { Route, Routes } from 'react-router-dom';
import { ToastProvider } from './components/Toast.jsx';
import Launcher from './launcher/Launcher.jsx';
import OwnerApp from './owner/OwnerApp.jsx';
import './launcher/launcher.css';

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/" element={<Launcher />} />
        <Route path="/owner/*" element={<OwnerApp />} />
        <Route path="*" element={<Launcher />} />
      </Routes>
    </ToastProvider>
  );
}
