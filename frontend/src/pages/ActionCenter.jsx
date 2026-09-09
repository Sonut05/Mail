import { useState, useEffect } from 'react';
import {
  Zap,
  Clock,
  CheckCircle2,
  XCircle,
  Calendar,
  AlertTriangle,
  ChevronDown,
  Filter,
  Sparkles,
  RefreshCw,
  ExternalLink,
} from 'lucide-react';
import { fetchActions, snoozeAction, dismissAction, completeAction } from '../services/api';

export default function ActionCenter() {
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState('ALL');
  const [filterPriority, setFilterPriority] = useState('ALL');
  const [snoozeMenuId, setSnoozeMenuId] = useState(null);

  const loadActions = async () => {
    try {
      setLoading(true);
      const params = {};
      if (filterType !== 'ALL') params.type = filterType;
      if (filterPriority !== 'ALL') params.priority = filterPriority;
      const res = await fetchActions(params);
      setActions(res?.items || []);
    } catch (err) {
      console.error('Failed to load actions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadActions();
  }, [filterType, filterPriority]);

  const handleSnooze = async (actionId, duration) => {
    setSnoozeMenuId(null);
    try {
      await snoozeAction(actionId, duration);
      setActions(prev => prev.filter(a => a.id !== actionId));
    } catch (err) {
      console.error('Failed to snooze action:', err);
    }
  };

  const handleDismiss = async (actionId) => {
    try {
      await dismissAction(actionId);
      setActions(prev => prev.filter(a => a.id !== actionId));
    } catch (err) {
      console.error('Failed to dismiss action:', err);
    }
  };

  const handleComplete = async (actionId) => {
    try {
      await completeAction(actionId);
      setActions(prev => prev.filter(a => a.id !== actionId));
    } catch (err) {
      console.error('Failed to complete action:', err);
    }
  };

  const getPriorityBadgeClass = (priority) => {
    switch (priority?.toLowerCase()) {
      case 'urgent': return 'badge-danger';
      case 'high': return 'badge-warning';
      case 'medium': return 'badge-primary';
      default: return 'badge-secondary';
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Header & Controls */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Zap size={24} style={{ color: 'var(--color-indigo)' }} />
            Action Center
          </h1>
          <p style={{ margin: '4px 0 0 0', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            Unified personal productivity actions, deadlines, follow-ups, and pending decisions.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="input-select"
            style={{ padding: '8px 12px', fontSize: '0.8125rem' }}
          >
            <option value="ALL">All Types</option>
            <option value="EMAIL_RESPONSE">Email Response</option>
            <option value="TASK_DUE">Task Due</option>
            <option value="FOLLOW_UP">Follow Up</option>
            <option value="DEADLINE">Deadline</option>
            <option value="MEETING_PROPOSAL">Meeting Proposal</option>
          </select>

          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value)}
            className="input-select"
            style={{ padding: '8px 12px', fontSize: '0.8125rem' }}
          >
            <option value="ALL">All Priorities</option>
            <option value="urgent">Urgent</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>

          <button onClick={loadActions} className="btn btn-secondary" style={{ padding: '8px 12px' }} title="Refresh">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Action Items List */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-secondary)' }}>
          <div className="spinner" style={{ margin: '0 auto 12px auto' }} />
          <span>Synchronizing Action Center...</span>
        </div>
      ) : actions.length === 0 ? (
        <div className="glass-card" style={{ padding: '48px', textAlign: 'center' }}>
          <CheckCircle2 size={48} style={{ color: 'var(--color-success)', margin: '0 auto 16px auto', opacity: 0.8 }} />
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1.125rem' }}>All Caught Up!</h3>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            You have no pending action items requiring attention right now.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {actions.map((item) => (
            <div
              key={item.id}
              className="glass-card animate-fadeIn"
              style={{
                padding: '16px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '16px',
                position: 'relative',
              }}
            >
              {/* Left: Score & Type & Content */}
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px', flex: 1 }}>
                <div
                  style={{
                    minWidth: '46px',
                    height: '46px',
                    borderRadius: '10px',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: item.score >= 80 ? 'rgba(239, 68, 68, 0.15)' : (item.score >= 60 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(99, 102, 241, 0.15)'),
                    border: `1px solid ${item.score >= 80 ? 'rgba(239, 68, 68, 0.3)' : (item.score >= 60 ? 'rgba(245, 158, 11, 0.3)' : 'rgba(99, 102, 241, 0.3)')}`,
                    color: item.score >= 80 ? 'var(--color-danger)' : (item.score >= 60 ? 'var(--color-warning)' : 'var(--color-indigo)'),
                  }}
                  title="Deterministic Action Score (0-100)"
                >
                  <span style={{ fontSize: '0.9375rem', fontWeight: 700, lineHeight: 1 }}>{item.score}</span>
                  <span style={{ fontSize: '0.5625rem', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.8 }}>Score</span>
                </div>

                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' }}>
                      {item.action_type?.replace(/_/g, ' ')}
                    </span>
                    <span className={`badge ${getPriorityBadgeClass(item.priority)}`} style={{ fontSize: '0.6875rem' }}>
                      {item.priority}
                    </span>
                    {item.due_at && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--color-warning)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock size={12} />
                        Due: {new Date(item.due_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
                    {item.title}
                  </div>

                  {item.description && (
                    <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: 1.4 }}>
                      {item.description}
                    </div>
                  )}

                  {/* Explainable Reasons */}
                  {Array.isArray(item.reasons) && item.reasons.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                      {item.reasons.map((r, i) => (
                        <span key={i} style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--glass-border)', padding: '2px 6px', borderRadius: '4px' }}>
                          • {r}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Right: Actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  onClick={() => handleComplete(item.id)}
                  className="btn btn-secondary"
                  style={{ padding: '6px 10px', fontSize: '0.75rem', color: 'var(--color-success)', display: 'flex', alignItems: 'center', gap: '4px' }}
                  title="Mark Complete"
                >
                  <CheckCircle2 size={14} />
                  <span>Done</span>
                </button>

                <div style={{ position: 'relative' }}>
                  <button
                    onClick={() => setSnoozeMenuId(snoozeMenuId === item.id ? null : item.id)}
                    className="btn btn-secondary"
                    style={{ padding: '6px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <Clock size={14} />
                    <span>Snooze</span>
                  </button>

                  {snoozeMenuId === item.id && (
                    <div
                      className="glass-card"
                      style={{
                        position: 'absolute',
                        top: '100%',
                        right: 0,
                        marginTop: '6px',
                        zIndex: 100,
                        width: '130px',
                        padding: '4px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '2px',
                        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                      }}
                    >
                      <button onClick={() => handleSnooze(item.id, '1h')} className="btn-dropdown-item">1 Hour</button>
                      <button onClick={() => handleSnooze(item.id, 'tomorrow')} className="btn-dropdown-item">Tomorrow</button>
                      <button onClick={() => handleSnooze(item.id, '3d')} className="btn-dropdown-item">3 Days</button>
                      <button onClick={() => handleSnooze(item.id, 'next_week')} className="btn-dropdown-item">Next Week</button>
                    </div>
                  )}
                </div>

                <button
                  onClick={() => handleDismiss(item.id)}
                  className="btn btn-secondary"
                  style={{ padding: '6px 8px', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}
                  title="Dismiss Recommendation"
                >
                  <XCircle size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
