import { useState, useEffect } from 'react';
import {
  Sparkles,
  Clock,
  Zap,
  Calendar,
  Users,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ArrowRight,
} from 'lucide-react';
import { fetchDailyDigest } from '../services/api';
import { Link } from 'react-router-dom';

export default function Digest() {
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadDigest = async () => {
    try {
      setLoading(true);
      const res = await fetchDailyDigest();
      setDigest(res?.digest || null);
    } catch (err) {
      console.error('Failed to load daily digest:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDigest();
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
        <div className="spinner" style={{ margin: '0 auto 12px auto' }} />
        <span>Compiling your morning productivity digest...</span>
      </div>
    );
  }

  const counts = digest?.summary_counts || {};

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <Sparkles size={20} style={{ color: 'var(--color-indigo)' }} />
            <span style={{ fontSize: '0.8125rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-indigo)' }}>
              Daily Intelligence Briefing
            </span>
          </div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, margin: 0 }}>
            Good Day — Here's Your Focus
          </h1>
          <p style={{ margin: '4px 0 0 0', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {digest?.date} • Pure deterministic intelligence from your active communications
          </p>
        </div>

        <button onClick={loadDigest} className="btn btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Metric Cards Banner */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', marginBottom: '28px' }}>
        <div className="glass-card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-danger)' }}>
            <AlertCircle size={20} />
          </div>
          <div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{counts.action_count || 0}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Needs Action</div>
          </div>
        </div>

        <div className="glass-card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-warning)' }}>
            <Clock size={20} />
          </div>
          <div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{counts.deadlines_count || 0}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Deadlines Soon</div>
          </div>
        </div>

        <div className="glass-card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(99, 102, 241, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-indigo)' }}>
            <Zap size={20} />
          </div>
          <div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{counts.follow_ups_count || 0}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Follow-ups Due</div>
          </div>
        </div>

        <div className="glass-card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-success)' }}>
            <Calendar size={20} />
          </div>
          <div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{counts.meetings_count || 0}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Meetings Today</div>
          </div>
        </div>
      </div>

      {/* Grid Sections */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '20px' }}>
        {/* Needs Action */}
        <div className="glass-card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Zap size={16} style={{ color: 'var(--color-danger)' }} />
              Needs Your Response
            </h3>
            <Link to="/emails?folder=all&filter=needs_action" style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
              View all <ArrowRight size={12} />
            </Link>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(digest?.needs_action || []).length === 0 ? (
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', padding: '12px 0' }}>No emails currently require action.</div>
            ) : (
              digest.needs_action.map(item => (
                <div key={item.id} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>{item.subject}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>From: {item.sender}</div>
                  {item.next_action && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', marginTop: '4px' }}>→ {item.next_action}</div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Approaching Deadlines */}
        <div className="glass-card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Clock size={16} style={{ color: 'var(--color-warning)' }} />
              Approaching Deadlines
            </h3>
            <Link to="/tasks" style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
              Task Board <ArrowRight size={12} />
            </Link>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(digest?.deadlines || []).length === 0 ? (
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', padding: '12px 0' }}>No deadlines in the next 48 hours.</div>
            ) : (
              digest.deadlines.map(item => (
                <div key={item.id} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid var(--glass-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>{item.subject}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--color-warning)' }}>
                      Due: {item.deadline ? new Date(item.deadline).toLocaleString() : 'Soon'}
                    </div>
                  </div>
                  <span className="badge badge-warning">{item.priority}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Recommended Follow-ups */}
        <div className="glass-card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sparkles size={16} style={{ color: 'var(--color-indigo)' }} />
              Follow-up Recommendations
            </h3>
            <Link to="/actions" style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
              Action Center <ArrowRight size={12} />
            </Link>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(digest?.follow_ups || []).length === 0 ? (
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', padding: '12px 0' }}>All active threads have recent replies.</div>
            ) : (
              digest.follow_ups.map((fu, idx) => (
                <div key={idx} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>{fu.subject}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '2px 0' }}>
                    Awaiting reply from {fu.recipient} ({fu.days_waiting} days)
                  </div>
                  {fu.suggested_followup && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontStyle: 'italic', marginTop: '4px' }}>
                      "{fu.suggested_followup}"
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Today's Schedule */}
        <div className="glass-card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Calendar size={16} style={{ color: 'var(--color-success)' }} />
              Schedule & Meetings
            </h3>
            <Link to="/calendar" style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
              Calendar <ArrowRight size={12} />
            </Link>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {(digest?.meetings || []).length === 0 ? (
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', padding: '12px 0' }}>No scheduled events today.</div>
            ) : (
              digest.meetings.map(m => (
                <div key={m.id} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)' }}>{m.title}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--color-success)', marginTop: '2px' }}>
                    {new Date(m.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                  {m.meeting_link && (
                    <a href={m.meeting_link} target="_blank" rel="noopener noreferrer" style={{ fontSize: '0.75rem', color: 'var(--color-indigo)', display: 'inline-block', marginTop: '4px' }}>
                      Join Meeting ↗
                    </a>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
