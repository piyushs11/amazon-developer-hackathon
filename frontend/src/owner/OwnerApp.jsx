import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import useBodyClass from '../lib/useBodyClass.js';
import { OwnerProvider } from './ownerState.jsx';
import ConnectorList from './ConnectorList.jsx';
import ConnectorDetail from './ConnectorDetail.jsx';
import Wizard from './Wizard.jsx';
import './owner.css';

export default function OwnerApp() {
  useBodyClass('owner-page');
  useEffect(() => { document.title = 'MCP Bridge Owner Portal'; }, []);
  return (
    <OwnerProvider>
      <Routes>
        <Route index element={<ConnectorList />} />
        <Route path="demobistro" element={<Navigate to="/owner/demobistro/overview" replace />} />
        <Route path="demobistro/:tab" element={<ConnectorDetail />} />
        <Route path="submit/:step" element={<Wizard />} />
        <Route path="*" element={<Navigate to="/owner" replace />} />
      </Routes>
    </OwnerProvider>
  );
}
