import { useEffect } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import PortalGate from '../components/PortalGate.jsx';
import useBodyClass from '../lib/useBodyClass.js';
import { OwnerProvider } from './ownerState.jsx';
import ConnectorList from './ConnectorList.jsx';
import ConnectorDetail from './ConnectorDetail.jsx';
import Wizard from './Wizard.jsx';
import './owner.css';

function ToOverview() {
  const { uuid } = useParams();
  return <Navigate to={`/owner/${uuid}/overview`} replace />;
}

export default function OwnerApp() {
  useBodyClass('owner-page');
  useEffect(() => { document.title = 'MCP Bridge Owner Portal'; }, []);
  return (
    <PortalGate role="owner" storageKey="mcpb.owner" title="Owner Portal"
      lede="Submit your service's API to the Alexa+ catalog. Choose a business account.">
      <OwnerProvider>
        <Routes>
          <Route index element={<ConnectorList />} />
          <Route path="submit/:step" element={<Wizard />} />
          <Route path=":uuid" element={<ToOverview />} />
          <Route path=":uuid/:tab" element={<ConnectorDetail />} />
          <Route path="*" element={<Navigate to="/owner" replace />} />
        </Routes>
      </OwnerProvider>
    </PortalGate>
  );
}
