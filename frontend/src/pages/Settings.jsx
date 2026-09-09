import { useState, useEffect } from 'react';
import {
  Mail,
  Shield,
  Bell,
  LogOut,
  RefreshCw,
  Sun,
  Briefcase,
  UploadCloud,
  CheckCircle,
  Plus,
  Trash2,
  Edit2,
  AlertTriangle,
  X,
  Check,
  FileText,
  Download,
} from 'lucide-react';
import { 
  fetchMailAccounts, 
  disconnectMailAccount, 
  getConnectGoogleUrl, 
  triggerMailSync, 
  triggerIncrementalMailSync, 
  fetchSyncStatus,
  fetchPreferences,
  updatePreferences,
  clearAIData
} from '../services/api';
import { useApp } from '../context/AppContext';


const autoReplyCategories = [
  { key: 'social', label: 'Social / Newsletters', desc: 'Auto-reply to social media notifications and newsletters', default: true },
  { key: 'promotions', label: 'Promotions', desc: 'Auto-archive promotional emails', default: true },
  { key: 'finance', label: 'Finance / Invoices', desc: 'Auto-categorize and create tasks for financial emails', default: false },
  { key: 'scheduling', label: 'Meeting Requests', desc: 'Auto-reply to meeting requests with availability', default: true },
  { key: 'support', label: 'Support / Tickets', desc: 'Auto-acknowledge support request emails', default: false },
];

const notificationPrefs = [
  { key: 'high_priority', label: 'High Priority Emails', desc: 'Get notified for high priority incoming emails', default: true },
  { key: 'auto_reply', label: 'Auto-Reply Confirmations', desc: 'Notify when an email is auto-replied', default: true },
  { key: 'task_due', label: 'Task Due Reminders', desc: 'Remind you when tasks are approaching their due date', default: true },
  { key: 'weekly_digest', label: 'Weekly Digest', desc: 'Receive a weekly summary of email activity', default: false },
];

function Toggle({ defaultChecked }) {
  const [checked, setChecked] = useState(defaultChecked);
  return (
    <label className="toggle-switch">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => setChecked(!checked)}
      />
      <span className="toggle-slider" />
    </label>
  );
}

export default function Settings() {
  const { 
    user, 
    demoMode, 
    login, 
    loginWithMock,
    logout, 
    sync, 
    syncing, 
    theme, 
    toggleTheme,
    updateResumeProfile,
    removeResumeProfile
  } = useApp();

  const profiles = user?.resume_profiles || [];

  const [editingProfileId, setEditingProfileId] = useState(null);
  const [isAdding, setIsAdding] = useState(false);
  const [role, setRole] = useState('');
  const [minSalary, setMinSalary] = useState('');
  const [maxSalary, setMaxSalary] = useState('');
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState('');

  // Phase 7: Personalization Preferences & Privacy
  const [prefs, setPrefs] = useState(null);
  const [loadingPrefs, setLoadingPrefs] = useState(true);
  const [prefsMsg, setPrefsMsg] = useState('');
  const [confirmClearOpen, setConfirmClearOpen] = useState(false);
  const [clearingData, setClearingData] = useState(false);
  const [clearResult, setClearResult] = useState(null);

  useEffect(() => {
    fetchPreferences()
      .then((res) => {
        if (res && res.preferences) setPrefs(res.preferences);
      })
      .catch((err) => console.error('Failed to load preferences:', err))
      .finally(() => setLoadingPrefs(false));
  }, []);

  const handleUpdatePref = async (updates) => {
    try {
      setPrefsMsg('Saving...');
      const res = await updatePreferences(updates);
      if (res && res.preferences) {
        setPrefs(res.preferences);
        setPrefsMsg('Saved!');
        setTimeout(() => setPrefsMsg(''), 2000);
      }
    } catch (err) {
      setPrefsMsg('Failed to update preferences.');
    }
  };

  const handleClearAIData = async () => {
    try {
      setClearingData(true);
      const res = await clearAIData();
      setClearResult(res);
      setConfirmClearOpen(false);
    } catch (err) {
      alert('Failed to clear AI data: ' + err.message);
    } finally {
      setClearingData(false);
    }
  };

  const startEdit = (p) => {
    setEditingProfileId(p.id);
    setIsAdding(false);
    setRole(p.target_role || '');
    setMinSalary(p.min_salary || '');
    setMaxSalary(p.max_salary || '');
    setFile(null);
    setFileError('');
  };

  const startAdd = () => {
    setEditingProfileId(null);
    setIsAdding(true);
    setRole('');
    setMinSalary('');
    setMaxSalary('');
    setFile(null);
    setFileError('');
  };

  const cancelEdit = () => {
    setEditingProfileId(null);
    setIsAdding(false);
    setRole('');
    setMinSalary('');
    setMaxSalary('');
    setFile(null);
    setFileError('');
  };

  const handleSave = async () => {
    if (!role.trim()) {
      setFileError('Target role is required.');
      return;
    }

    setSaving(true);
    setSaveStatus('Saving...');
    setFileError('');

    try {
      const payload = {
        id: editingProfileId,
        target_role: role,
        min_salary: minSalary ? parseInt(minSalary) : null,
        max_salary: maxSalary ? parseInt(maxSalary) : null,
      };

      const res = await updateResumeProfile(payload, file);
      if (res.success) {
        setSaveStatus('Saved!');
        setTimeout(() => {
          setSaveStatus('');
          cancelEdit();
        }, 1000);
      } else {
        setFileError(res.error || 'Failed to save profile.');
      }
    } catch (err) {
      setFileError('An unexpected error occurred.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (profileId) => {
    if (window.confirm('Are you sure you want to delete this recruitment profile?')) {
      await removeResumeProfile(profileId);
    }
  };

  const [connectedAccounts, setConnectedAccounts] = useState([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);
  const [syncingIds, setSyncingIds] = useState({});

  const loadAccounts = async () => {
    try {
      setLoadingAccounts(true);
      const res = await fetchMailAccounts();
      if (res && res.accounts) {
        setConnectedAccounts(res.accounts);
      } else {
        setConnectedAccounts([]);
      }
    } catch (err) {
      console.error('Failed to load connected mail accounts:', err);
    } finally {
      setLoadingAccounts(false);
    }
  };

  useEffect(() => {
    loadAccounts();
  }, []);

  const handleDisconnect = async (accountId) => {
    if (window.confirm('Are you sure you want to disconnect this Gmail account? MailMild will revoke and delete stored OAuth tokens.')) {
      setDisconnecting(true);
      try {
        await disconnectMailAccount(accountId);
        await loadAccounts();
      } catch (err) {
        console.error('Failed to disconnect account:', err);
      } finally {
        setDisconnecting(false);
      }
    }
  };

  const handleSyncAccount = async (accountId) => {
    setSyncingIds((prev) => ({ ...prev, [accountId]: true }));
    // Immediately show syncing status in UI
    setConnectedAccounts((prev) =>
      prev.map((a) => (a.id === accountId ? { ...a, sync_status: 'syncing', sync_progress: 'Starting full synchronization...' } : a))
    );

    try {
      await triggerMailSync(accountId);
      // Poll sync status and update live counts
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetchSyncStatus(accountId);
          if (statusRes) {
            setConnectedAccounts((prev) =>
              prev.map((a) =>
                a.id === accountId
                  ? {
                      ...a,
                      sync_status: statusRes.status,
                      messages_synced: statusRes.messages_synced !== undefined ? statusRes.messages_synced : a.messages_synced,
                      sync_progress: statusRes.progress || a.sync_progress,
                      last_sync_at: statusRes.last_sync_at || a.last_sync_at,
                      history_id: statusRes.history_id || a.history_id,
                    }
                  : a
              )
            );

            if (statusRes.status !== 'syncing') {
              clearInterval(pollInterval);
              setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
              loadAccounts();
            }
          }
        } catch (pollErr) {
          console.warn('Poll error:', pollErr);
          clearInterval(pollInterval);
          setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
          loadAccounts();
        }
      }, 1500);
    } catch (err) {
      console.error('Failed to trigger mailbox sync:', err);
      setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
      loadAccounts();
    }
  };

  const handleIncrementalSyncAccount = async (accountId) => {
    setSyncingIds((prev) => ({ ...prev, [accountId]: true }));
    // Immediately show syncing status in UI
    setConnectedAccounts((prev) =>
      prev.map((a) => (a.id === accountId ? { ...a, sync_status: 'syncing', sync_progress: 'Checking for new messages...' } : a))
    );

    try {
      await triggerIncrementalMailSync(accountId);
      // Poll sync status and update live counts
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await fetchSyncStatus(accountId);
          if (statusRes) {
            setConnectedAccounts((prev) =>
              prev.map((a) =>
                a.id === accountId
                  ? {
                      ...a,
                      sync_status: statusRes.status,
                      messages_synced: statusRes.messages_synced !== undefined ? statusRes.messages_synced : a.messages_synced,
                      sync_progress: statusRes.progress || a.sync_progress,
                      last_sync_at: statusRes.last_sync_at || a.last_sync_at,
                      history_id: statusRes.history_id || a.history_id,
                    }
                  : a
              )
            );

            if (statusRes.status !== 'syncing') {
              clearInterval(pollInterval);
              setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
              loadAccounts();
            }
          }
        } catch (pollErr) {
          console.warn('Incremental poll error:', pollErr);
          clearInterval(pollInterval);
          setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
          loadAccounts();
        }
      }, 1500);
    } catch (err) {
      console.error('Failed to trigger incremental mailbox sync:', err);
      setSyncingIds((prev) => ({ ...prev, [accountId]: false }));
      loadAccounts();
    }
  };

  return (
    <div className="settings-page page-enter">
      {/* Connected Accounts */}
      <div className="glass-card settings-section animate-fadeIn stagger-1">
        <h3 className="settings-section-title">
          <Mail size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
          Connected Email Accounts (Gmail)
        </h3>
        <p className="settings-section-desc">
          Connect your personal or work Gmail account using Google's official OAuth 2.0 system. MailMild never requests or stores your Gmail password.
        </p>

        {loadingAccounts ? (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            Loading connected accounts...
          </div>
        ) : connectedAccounts.length === 0 ? (
          <div className="connected-account-empty" style={{ padding: '28px 24px', textAlign: 'center', border: '1px dashed var(--glass-border)', borderRadius: 'var(--radius-md)', background: 'rgba(255,255,255,0.01)' }}>
            <Mail size={36} style={{ marginBottom: '12px', color: 'var(--text-tertiary)' }} />
            <div style={{ fontSize: '1rem', fontWeight: '600', marginBottom: '6px', color: 'var(--text-primary)' }}>
              No Gmail Account Connected
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', marginBottom: '20px', maxWidth: '420px', margin: '0 auto 20px auto', lineHeight: 1.5 }}>
              Connect your Gmail account via Google's official consent page to allow MailMild to read and monitor your incoming emails securely.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
              <button
                className="btn btn-primary"
                onClick={() => { window.location.href = getConnectGoogleUrl(); }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '10px 24px',
                  fontSize: '0.875rem',
                  fontWeight: '600',
                  borderRadius: '10px',
                }}
              >
                <svg style={{ width: '16px', height: '16px' }} viewBox="0 0 24 24" fill="currentColor">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#FFFFFF" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#FFFFFF" fillRule="evenodd" opacity="0.85" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FFFFFF" fillRule="evenodd" opacity="0.75" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#FFFFFF" opacity="0.9" />
                </svg>
                <span>Connect Gmail</span>
              </button>
              <span style={{ fontSize: '0.725rem', color: 'var(--text-tertiary)' }}>
                Direct Google OAuth 2.0 consent · Passwords never collected
              </span>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {connectedAccounts.map((acc) => {
              const isSyncing = Boolean(syncingIds[acc.id] || acc.sync_status === 'syncing');
              const effectiveStatus = isSyncing ? 'syncing' : acc.sync_status;
              const statusColor = effectiveStatus === 'completed' 
                ? '#22C55E' 
                : effectiveStatus === 'syncing' 
                ? '#EAB308' 
                : effectiveStatus === 'resync_required'
                ? '#F97316'
                : effectiveStatus === 'error' 
                ? '#EF4444' 
                : '#64748B';
              const statusLabel = effectiveStatus === 'completed' 
                ? 'Completed' 
                : effectiveStatus === 'syncing' 
                ? 'Syncing...' 
                : effectiveStatus === 'resync_required'
                ? 'Resync Required'
                : effectiveStatus === 'error' 
                ? 'Error' 
                : 'Not synced';

              return (
                <div key={acc.id} className="connected-account" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderRadius: '12px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', flexWrap: 'wrap', gap: '14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flex: 1, minWidth: '280px' }}>
                    <div className="connected-account-icon" style={{ width: '42px', height: '42px', borderRadius: '10px', background: 'rgba(99, 102, 241, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#818CF8', flexShrink: 0 }}>
                      <Mail size={22} />
                    </div>
                    <div className="connected-account-info" style={{ flex: 1 }}>
                      <div style={{ fontSize: '0.9375rem', fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span>{acc.email_address}</span>
                        <span style={{ 
                          fontSize: '0.6875rem', 
                          fontWeight: '600', 
                          padding: '2px 8px', 
                          borderRadius: '12px', 
                          background: `${statusColor}18`, 
                          color: statusColor, 
                          border: `1px solid ${statusColor}40` 
                        }}>
                          {statusLabel}
                        </span>
                      </div>
                      <div className="connected-account-status" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '8px', marginTop: '3px', flexWrap: 'wrap' }}>
                        <span>Messages Synced: <strong>{acc.messages_synced || 0}</strong></span>
                        {acc.last_sync_at && (
                          <span>· Last Synced: {new Date(acc.last_sync_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}, {new Date(acc.last_sync_at).toLocaleDateString()}</span>
                        )}
                        {effectiveStatus === 'completed' && (
                          <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>· Incremental Sync: Ready</span>
                        )}
                      </div>

                      {effectiveStatus === 'resync_required' && (
                        <div style={{ 
                          margin: '8px 0 4px 0', 
                          padding: '8px 12px', 
                          borderRadius: '8px', 
                          background: 'rgba(249, 115, 22, 0.1)', 
                          border: '1px solid rgba(249, 115, 22, 0.3)', 
                          color: '#F97316', 
                          fontSize: '0.75rem', 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: '8px' 
                        }}>
                          <AlertTriangle size={15} style={{ flexShrink: 0 }} />
                          <span>Gmail history cursor expired. A full sync is needed to re-synchronize your mailbox.</span>
                        </div>
                      )}

                      {acc.sync_progress && (
                        <div style={{ 
                          fontSize: '0.725rem', 
                          color: effectiveStatus === 'syncing' ? '#EAB308' : effectiveStatus === 'error' ? '#EF4444' : effectiveStatus === 'resync_required' ? '#F97316' : '#22C55E', 
                          marginTop: '3px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px'
                        }}>
                          {effectiveStatus === 'completed' && <span>✓</span>}
                          <span>{acc.sync_progress}</span>
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    {effectiveStatus === 'resync_required' ? (
                      <button
                        className="btn btn-primary"
                        onClick={() => handleSyncAccount(acc.id)}
                        disabled={isSyncing}
                        style={{ fontSize: '0.8125rem', padding: '8px 16px', borderRadius: '8px', gap: '6px', display: 'flex', alignItems: 'center', background: '#F97316', borderColor: '#F97316' }}
                      >
                        <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
                        <span>{isSyncing ? 'Syncing...' : 'Resync All'}</span>
                      </button>
                    ) : (
                      <>
                        <button
                          className="btn btn-primary"
                          onClick={() => handleIncrementalSyncAccount(acc.id)}
                          disabled={isSyncing}
                          title="Quickly fetch newly arrived messages using Gmail history cursor"
                          style={{ fontSize: '0.8125rem', padding: '8px 14px', borderRadius: '8px', gap: '6px', display: 'flex', alignItems: 'center' }}
                        >
                          <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
                          <span>{isSyncing ? 'Syncing...' : 'Sync New Mail'}</span>
                        </button>
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleSyncAccount(acc.id)}
                          disabled={isSyncing}
                          title="Run a complete mailbox synchronization"
                          style={{ fontSize: '0.8125rem', padding: '8px 12px', borderRadius: '8px', gap: '6px', display: 'flex', alignItems: 'center' }}
                        >
                          <span>Full Sync</span>
                        </button>
                      </>
                    )}
                    <button
                      className="btn btn-danger-ghost"
                      onClick={() => handleDisconnect(acc.id)}
                      disabled={disconnecting || isSyncing}
                      style={{ fontSize: '0.8125rem', padding: '8px 12px', borderRadius: '8px', gap: '6px', display: 'flex', alignItems: 'center' }}
                    >
                      <LogOut size={14} />
                      <span>{disconnecting ? 'Disconnecting...' : 'Disconnect'}</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Recruitment Autopilot (Multi-Resume) */}
      <div className="glass-card settings-section animate-fadeIn stagger-2">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h3 className="settings-section-title" style={{ marginBottom: 0 }}>
            <Briefcase size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
            Recruitment Autopilot (Multi-Resume)
          </h3>
          {!isAdding && !editingProfileId && (
            <button className="btn btn-ghost" onClick={startAdd} style={{ fontSize: '0.75rem', padding: '6px 12px', gap: '4px' }}>
              <Plus size={14} /> Add Role Profile
            </button>
          )}
        </div>
        <p className="settings-section-desc">
          Configure different target roles and upload custom tailored resumes for each. Autopilot will select the best-matching profile to auto-fill recruitment forms.
        </p>

        {/* Existing Profiles List */}
        {!isAdding && !editingProfileId && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {profiles.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', border: '1px dashed var(--glass-border)', borderRadius: 'var(--radius-md)', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
                <Briefcase size={24} style={{ marginBottom: '8px', opacity: 0.5 }} />
                <div>No role profiles added yet.</div>
                <p style={{ fontSize: '0.75rem', marginTop: '4px' }}>Add a target job role and upload a resume to enable auto-filling recruitment forms.</p>
              </div>
            ) : (
              profiles.map((p) => (
                <div key={p.id} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontSize: '0.9375rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '4px' }}>{p.target_role}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                      <span className="badge" style={{ fontSize: '0.6875rem', background: 'rgba(99, 102, 241, 0.1)', color: '#818CF8' }}>
                        {p.min_salary && p.max_salary ? `$${p.min_salary.toLocaleString()} - $${p.max_salary.toLocaleString()}` : p.min_salary ? `>= $${p.min_salary.toLocaleString()}` : 'No Target Salary'}
                      </span>
                      {p.resume_parsed_json ? (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--color-success)' }}>
                          <CheckCircle size={12} /> {p.resume_text || 'Tailored Resume'} loaded
                        </span>
                      ) : (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--color-warning)' }}>
                          <AlertTriangle size={12} /> No Resume Uploaded
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button className="btn btn-ghost" onClick={() => startEdit(p)} style={{ padding: '6px', height: 'auto' }}>
                      <Edit2 size={14} />
                    </button>
                    <button className="btn btn-ghost" onClick={() => handleDelete(p.id)} style={{ padding: '6px', height: 'auto', color: 'var(--color-danger)' }}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Add/Edit Form */}
        {(isAdding || editingProfileId) && (
          <div style={{ background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', padding: '20px', marginTop: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <h4 style={{ margin: 0, fontSize: '0.875rem', fontWeight: '700', textTransform: 'uppercase', color: 'var(--color-indigo)', letterSpacing: '0.05em' }}>
                {isAdding ? 'Add New Role Profile' : 'Edit Role Profile'}
              </h4>
              <button onClick={cancelEdit} style={{ background: 'none', border: 'none', color: 'var(--text-tertiary)', cursor: 'pointer' }}>
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '20px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '6px', textTransform: 'uppercase' }}>Target Role</label>
                <input 
                  type="text" 
                  placeholder="e.g. Software Engineer" 
                  value={role} 
                  onChange={(e) => setRole(e.target.value)}
                  style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', outline: 'none', fontSize: '0.875rem' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '6px', textTransform: 'uppercase' }}>Min Annual Salary ($)</label>
                <input 
                  type="number" 
                  placeholder="e.g. 80000" 
                  value={minSalary} 
                  onChange={(e) => setMinSalary(e.target.value)}
                  style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', outline: 'none', fontSize: '0.875rem' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '6px', textTransform: 'uppercase' }}>Max Annual Salary ($)</label>
                <input 
                  type="number" 
                  placeholder="e.g. 120000" 
                  value={maxSalary} 
                  onChange={(e) => setMaxSalary(e.target.value)}
                  style={{ width: '100%', padding: '10px 14px', background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', color: 'var(--text-primary)', outline: 'none', fontSize: '0.875rem' }}
                />
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '10px', textTransform: 'uppercase' }}>Resume File (.txt or .pdf)</label>
              <div 
                style={{ 
                  border: '2px dashed var(--glass-border)', 
                  borderRadius: 'var(--radius-lg)', 
                  padding: '30px 20px', 
                  textAlign: 'center', 
                  background: 'rgba(255,255,255,0.01)',
                  position: 'relative',
                  cursor: 'pointer',
                  transition: 'all 0.3s ease'
                }}
                onClick={() => document.getElementById('profile-file-input').click()}
              >
                <input 
                  id="profile-file-input"
                  type="file"
                  accept=".txt,.pdf"
                  style={{ display: 'none' }}
                  onChange={(e) => setFile(e.target.files[0])}
                />
                <UploadCloud size={32} style={{ color: 'var(--color-indigo)', marginBottom: '8px', opacity: 0.8 }} />
                <div style={{ fontSize: '0.875rem', fontWeight: '500', marginBottom: '4px' }}>
                  {file ? `Selected file: ${file.name}` : 'Click to tailer and upload Resume'}
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                  Supports plain text (.txt) or PDF. Tailors your credentials for the role.
                </p>
              </div>

              {fileError && <div style={{ color: 'var(--color-danger)', fontSize: '0.8125rem', marginTop: '8px' }}>{fileError}</div>}
            </div>

            <div style={{ display: 'flex', gap: '12px' }}>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving} style={{ fontSize: '0.8125rem' }}>
                {saveStatus ? saveStatus : 'Save Profile'}
              </button>
              <button className="btn btn-ghost" onClick={cancelEdit} style={{ fontSize: '0.8125rem' }}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Appearance Settings */}
      <div className="glass-card settings-section animate-fadeIn stagger-2">
        <h3 className="settings-section-title">
          <Sun size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
          Appearance Settings
        </h3>
        <p className="settings-section-desc">
          Customize the look and theme of the AI Mail Summarizer.
        </p>

        <div className="toggle-row">
          <div>
            <div className="toggle-label">Light Mode</div>
            <div className="toggle-desc">Switch the dashboard theme to light mode</div>
          </div>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={theme === 'light'}
              onChange={toggleTheme}
            />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      {/* Phase 7: Personalization & AI Privacy Controls */}
      <div className="glass-card settings-section animate-fadeIn stagger-2" style={{ position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <h3 className="settings-section-title" style={{ margin: 0 }}>
            <Shield size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
            Personalization & AI Privacy Controls
          </h3>
          {prefsMsg && (
            <span style={{ fontSize: '0.8rem', color: 'var(--color-success)', fontWeight: '600' }}>
              {prefsMsg}
            </span>
          )}
        </div>
        <p className="settings-section-desc">
          Manage AI analysis permissions, custom follow-up thresholds, inbox scoring behavior, and data retention.
        </p>

        {loadingPrefs ? (
          <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
            Loading preferences...
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '16px' }}>
            {/* AI Analysis Master Toggle */}
            <div className="toggle-row" style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--glass-border)' }}>
              <div>
                <div className="toggle-label" style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
                  Enable AI Background Analysis
                </div>
                <div className="toggle-desc">
                  When enabled, MailMind generates summaries, sentiment, urgency scores, and action items. Disabling stops background analysis for new emails.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={prefs?.ai_analysis_enabled ?? true}
                  onChange={(e) => handleUpdatePref({ ai_analysis_enabled: e.target.checked })}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            {/* Smart Inbox Toggle */}
            <div className="toggle-row" style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--glass-border)' }}>
              <div>
                <div className="toggle-label" style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
                  Smart Inbox Deterministic Ranking
                </div>
                <div className="toggle-desc">
                  Prioritizes unread emails, action requests, VIP interactions, and pending deadlines automatically.
                </div>
              </div>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={prefs?.smart_inbox_enabled ?? true}
                  onChange={(e) => handleUpdatePref({ smart_inbox_enabled: e.target.checked })}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            {/* Priority and Threshold Options Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
              <div style={{ padding: '14px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--glass-border)' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '6px' }}>
                  Preferred Priority Mode
                </label>
                <select
                  value={prefs?.preferred_priority_behavior || 'balanced'}
                  onChange={(e) => handleUpdatePref({ preferred_priority_behavior: e.target.value })}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--surface-primary)', color: 'var(--text-primary)', border: '1px solid var(--glass-border)', borderRadius: '6px', fontSize: '0.85rem' }}
                >
                  <option value="balanced">Balanced (Default)</option>
                  <option value="strict_action_required">Strict Action Required</option>
                  <option value="people_first">People & VIP First</option>
                  <option value="urgent_only">Urgent / Deadlines Only</option>
                </select>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  Adjusts score multipliers for action items and sender importance.
                </div>
              </div>

              <div style={{ padding: '14px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--glass-border)' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '6px' }}>
                  Follow-up Recommendation Threshold
                </label>
                <select
                  value={prefs?.follow_up_threshold_days ?? 3}
                  onChange={(e) => handleUpdatePref({ follow_up_threshold_days: parseInt(e.target.value, 10) })}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--surface-primary)', color: 'var(--text-primary)', border: '1px solid var(--glass-border)', borderRadius: '6px', fontSize: '0.85rem' }}
                >
                  <option value={1}>1 Day (Fast cadence)</option>
                  <option value={3}>3 Days (Standard)</option>
                  <option value={5}>5 Days (Relaxed)</option>
                  <option value={7}>7 Days (Weekly)</option>
                </select>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  Days after sent inquiry or pending reply before suggesting follow-up.
                </div>
              </div>

              <div style={{ padding: '14px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--glass-border)' }}>
                <label style={{ display: 'block', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '6px' }}>
                  Stale Conversation Threshold
                </label>
                <select
                  value={prefs?.stale_thread_threshold_days ?? 7}
                  onChange={(e) => handleUpdatePref({ stale_thread_threshold_days: parseInt(e.target.value, 10) })}
                  style={{ width: '100%', padding: '8px 12px', background: 'var(--surface-primary)', color: 'var(--text-primary)', border: '1px solid var(--glass-border)', borderRadius: '6px', fontSize: '0.85rem' }}
                >
                  <option value={3}>3 Days</option>
                  <option value={7}>7 Days (Default)</option>
                  <option value={14}>14 Days</option>
                  <option value={30}>30 Days</option>
                </select>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                  Inactivity threshold before a thread is marked as Stale.
                </div>
              </div>
            </div>

            {/* Clear AI Data Danger Section */}
            <div style={{ padding: '14px 16px', background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <div style={{ fontWeight: '600', color: '#EF4444', fontSize: '0.875rem' }}>
                  Clear Stored AI Analysis Data
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                  Removes all AI-generated summaries, key points, priority predictions, and pending analysis jobs. Raw emails and user-confirmed tasks/calendar events are kept intact.
                </div>
              </div>
              <button
                className="btn btn-danger"
                onClick={() => setConfirmClearOpen(true)}
                style={{ fontSize: '0.78rem', padding: '8px 14px', borderRadius: '6px' }}
              >
                Clear AI Data
              </button>
            </div>

            {clearResult && (
              <div style={{ padding: '10px 14px', background: 'rgba(34, 197, 94, 0.1)', border: '1px solid rgba(34, 197, 94, 0.3)', borderRadius: '6px', color: '#22C55E', fontSize: '0.8rem' }}>
                ✓ Stored AI data cleared successfully ({clearResult.emails_cleared || 0} emails reset, {clearResult.jobs_removed || 0} jobs removed).
              </div>
            )}
          </div>
        )}

        {/* Confirmation Modal */}
        {confirmClearOpen && (
          <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
            <div className="glass-card" style={{ maxWidth: '440px', width: '90%', padding: '24px', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.4)' }}>
              <h4 style={{ margin: '0 0 10px 0', color: '#EF4444', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertTriangle size={20} />
                Confirm AI Data Purge
              </h4>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, margin: '0 0 16px 0' }}>
                Are you sure you want to clear all stored AI analysis? This resets summaries, categories, priorities, and action items for all your emails. Your raw email messages and existing confirmed tasks will not be deleted.
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  className="btn btn-ghost"
                  onClick={() => setConfirmClearOpen(false)}
                  disabled={clearingData}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-danger"
                  onClick={handleClearAIData}
                  disabled={clearingData}
                >
                  {clearingData ? 'Clearing...' : 'Yes, Purge AI Data'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Auto-Reply Preferences */}
      <div className="glass-card settings-section animate-fadeIn stagger-2">
        <h3 className="settings-section-title">
          <Shield size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
          Auto-Reply Preferences
        </h3>
        <p className="settings-section-desc">
          Configure which email categories should be auto-replied by the AI assistant.
        </p>

        {autoReplyCategories.map((cat) => (
          <div key={cat.key} className="toggle-row">
            <div>
              <div className="toggle-label">{cat.label}</div>
              <div className="toggle-desc">{cat.desc}</div>
            </div>
            <Toggle defaultChecked={cat.default} />
          </div>
        ))}
      </div>

      {/* Notification Preferences */}
      <div className="glass-card settings-section animate-fadeIn stagger-3">
        <h3 className="settings-section-title">
          <Bell size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
          Notification Preferences
        </h3>
        <p className="settings-section-desc">
          Choose how and when you want to be notified about email activity.
        </p>

        {notificationPrefs.map((pref) => (
          <div key={pref.key} className="toggle-row">
            <div>
              <div className="toggle-label">{pref.label}</div>
              <div className="toggle-desc">{pref.desc}</div>
            </div>
            <Toggle defaultChecked={pref.default} />
          </div>
        ))}
      </div>

      {/* System Documentation & Architecture */}
      <div className="glass-card settings-section animate-fadeIn stagger-3">
        <h3 className="settings-section-title">
          <FileText size={18} style={{ verticalAlign: 'middle', marginRight: '8px', color: 'var(--color-indigo)' }} />
          System Documentation & Architecture
        </h3>
        <p className="settings-section-desc">
          Download the comprehensive MailMild system specifications, REST API reference, and Phase 1–5 feature documentation.
        </p>

        <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <a
            href="/api/docs/readme/download"
            className="btn btn-secondary"
            download="README.md"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', textDecoration: 'none' }}
          >
            <Download size={16} />
            Download README.md
          </a>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
            Markdown format • Complete architecture & API docs
          </span>
        </div>
      </div>
    </div>
  );
}
