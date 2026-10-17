import { useRef, useState } from 'react';
import { useOverlay } from '../components/Overlay.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { useReview } from './reviewState.jsx';

const REJECT_CATEGORIES = [
  "Test account doesn't work",
  "Tool behaviour doesn't match the description",
  'Confirmation or safety',
  'Metadata, privacy or terms',
  'Other',
];
const MIN_REASON = 20;

export function ApproveDialog({ s }) {
  const { approve } = useReview();
  const overlay = useOverlay();
  const toast = useToast();
  const [note, setNote] = useState('');

  const confirm = () => {
    approve(s.id, note.trim());
    overlay.close();
    toast(s.service + ' approved and added to the catalog', 'ok');
  };

  return (
    <>
      <h2>Approve {s.service} {s.version}?</h2>
      <p className="lede">This lists {s.service} in the Alexa+ catalog so customers can add it by searching for {s.domain}. Nothing is generated now: the tool bundle is built and activated on the gateway the first time a user publishes the service, and every later user shares it.</p>
      <div className="field">
        <label htmlFor="apNote">Note to the owner (optional)</label>
        <textarea className="textarea" id="apNote" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Anything they should know, for example phrases that worked especially well" />
      </div>
      <div className="actions">
        <button className="btn btn-ghost" onClick={overlay.close}>Cancel</button>
        <button className="btn btn-primary" onClick={confirm}><Icon name="check" />Approve</button>
      </div>
    </>
  );
}

export function RejectDialog({ s }) {
  const { reject } = useReview();
  const overlay = useOverlay();
  const toast = useToast();
  const [category, setCategory] = useState(REJECT_CATEGORIES[0]);
  const [reason, setReason] = useState('');
  const [showError, setShowError] = useState(false);
  const reasonRef = useRef(null);

  const confirm = () => {
    const text = reason.trim();
    if (text.length < MIN_REASON) {
      setShowError(true);
      reasonRef.current.focus();
      return;
    }
    reject(s.id, category + ': ' + text);
    overlay.close();
    toast(s.service + ' ' + s.version + ' rejected. The owner has been emailed.');
  };

  return (
    <>
      <h2>Reject {s.service} {s.version}</h2>
      <p className="lede">The owner sees this reason in their portal and by email, fixes it and submits a new version. Be specific about what to change.</p>
      <div className="stack">
        <div className="field">
          <label htmlFor="rjCat">Category</label>
          <select className="select" id="rjCat" value={category} onChange={(e) => setCategory(e.target.value)}>
            {REJECT_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rjReason">Reason</label>
          <textarea ref={reasonRef} className={'textarea' + (showError ? ' err' : '')} id="rjReason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What failed, where you saw it, and what the owner should change" />
          <div className="error" hidden={!showError}><Icon name="alert" cls="s" />Write at least {MIN_REASON} characters so the owner knows what to fix.</div>
        </div>
      </div>
      <div className="actions">
        <button className="btn btn-ghost" onClick={overlay.close}>Cancel</button>
        <button className="btn btn-danger" onClick={confirm}>Reject</button>
      </div>
    </>
  );
}
