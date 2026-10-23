import { useEffect } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { OverlayProvider } from '../components/Overlay.jsx';
import PortalGate from '../components/PortalGate.jsx';
import useBodyClass from '../lib/useBodyClass.js';
import { ReviewProvider } from './reviewState.jsx';
import Queue from './Queue.jsx';
import Catalog from './Catalog.jsx';
import ReviewDetail from './ReviewDetail.jsx';
import './review.css';

function ToSummary() {
  const { id } = useParams();
  return <Navigate to={`/review/${id}/summary`} replace />;
}

export default function ReviewApp() {
  useBodyClass('review-page');
  useEffect(() => { document.title = 'MCP Bridge Review Console'; }, []);
  return (
    <PortalGate role="reviewer" storageKey="mcpb.reviewer" title="Review Console"
      lede="Review connector submissions for the Alexa+ catalog. Choose a reviewer account.">
      <ReviewProvider>
        <OverlayProvider>
          <Routes>
            <Route index element={<Queue />} />
            <Route path="catalog" element={<Catalog />} />
            <Route path="submissions/:id" element={<ToSummary />} />
            <Route path=":id" element={<ToSummary />} />
            <Route path=":id/:tab" element={<ReviewDetail />} />
            <Route path="*" element={<Navigate to="/review" replace />} />
          </Routes>
        </OverlayProvider>
      </ReviewProvider>
    </PortalGate>
  );
}
