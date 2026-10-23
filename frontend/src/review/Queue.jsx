import { useNavigate } from 'react-router-dom';
import { Row2 } from '../components/ConsoleShell.jsx';
import { fmtDateTime } from '../lib/utils.js';
import ReviewShell, { TopNav } from './ReviewShell.jsx';
import { ChecksSummary, StatusLabel, isOpen, useReview } from './reviewState.jsx';

const FILTERS = [['open', 'Open'], ['pending', 'Pending review'], ['in_review', 'In review'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['all', 'All']];

export default function Queue() {
  const { subs, filter, setFilter, loading, error } = useReview();
  const navigate = useNavigate();

  const count = (st) => subs.filter((s) => s.status === st).length;
  const counts = {
    all: subs.length, open: subs.filter(isOpen).length,
    pending: count('pending'), in_review: count('in_review'), approved: count('approved'), rejected: count('rejected'),
  };
  const list = subs
    .filter((s) => filter === 'all' || (filter === 'open' ? isOpen(s) : s.status === filter))
    .sort((a, b) => b.submitted - a.submitted);

  return (
    <ReviewShell row2={<Row2 title="Queue" />} nav={<TopNav current="queue" />}>
      <div className="page-head"><div>
        <h1>Submissions</h1>
        <p className="lede">Connector submissions from website owners. Every one listed here passed the automated checks; your job is the part a machine can't do.</p>
      </div></div>

      {error && <div className="banner err" style={{ marginBottom: 16 }}><div>{error}</div></div>}
      <div className="queue-sum">
        <div className="tile"><span className="n tnum">{counts.pending}</span><span className="l">Waiting for a reviewer</span></div>
        <div className="tile"><span className="n tnum">{counts.in_review}</span><span className="l">In review</span></div>
        <div className="tile"><span className="n tnum">{counts.approved}</span><span className="l">Approved, in the catalog</span></div>
        <div className="tile"><span className="n tnum">{counts.rejected}</span><span className="l">Rejected with a reason</span></div>
      </div>

      <div className="filters" role="group" aria-label="Filter by status">
        {FILTERS.map(([key, label]) => (
          <button key={key} className="chip" aria-pressed={filter === key} onClick={() => setFilter(key)}>
            {label} <span className="n">{counts[key]}</span>
          </button>
        ))}
      </div>

      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Service</th><th>Domain</th><th>Category</th><th>Version</th><th>Submitted</th><th>Automated checks</th><th>Status</th></tr></thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => navigate(`/review/${s.id}/summary`)}>
                <td className="primary" data-l="Service">{s.service}</td>
                <td data-l="Domain">{s.domain}</td>
                <td data-l="Category">{s.category}</td>
                <td data-l="Version" className="tnum">{s.version}</td>
                <td data-l="Submitted">{fmtDateTime(s.submitted)}</td>
                <td data-l="Automated checks"><ChecksSummary checks={s.checks} /></td>
                <td data-l="Status"><div><StatusLabel status={s.status} />{s.assignee && <div className="small muted">{s.assignee}</div>}</div></td>
              </tr>
            ))}
            {!list.length && !loading && (
              <tr><td colSpan={7} className="muted" style={{ padding: '28px 16px', textAlign: 'center' }}>Nothing here.</td></tr>
            )}
          </tbody>
        </table>
      </div></div>
    </ReviewShell>
  );
}
