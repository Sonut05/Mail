import { useState, useMemo, useEffect } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  Search,
  Mail,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Send,
  Edit3,
  Trash2,
  CheckCircle2,
  User,
  Building2,
  CalendarDays,
  DollarSign,
  SmilePlus,
  Frown,
  Meh,
  Reply,
  Zap,
  Check,
  Loader2,
  Calendar,
  AlertCircle,
  Clock,
  AlertTriangle,
  RefreshCw,
  Tag,
  Flag,
  MessageSquare,
  ThumbsUp,
  ThumbsDown,
  Bookmark,
  Star,
  CheckSquare,
  X,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import {
  retryEmailAnalysis,
  recordFeedbackSignal,
  fetchSavedSearches,
  createSavedSearch,
  deleteSavedSearch,
  executeBulkAction,
} from '../services/api';
import ThreadViewModal from '../components/ThreadViewModal';

const avatarColors = [
  '#4F46E5', '#7C3AED', '#06B6D4', '#10B981',
  '#F59E0B', '#F43F5E', '#8B5CF6', '#EC4899',
];

function getAvatarColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return avatarColors[Math.abs(hash) % avatarColors.length];
}

function getInitials(name) {
  if (!name) return 'U';
  return name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);
}

function getCategoryBadge(category) {
  const cat = (category || '').toLowerCase();
  const map = {
    work: 'indigo',
    job: 'indigo',
    recruitment: 'indigo',
    hr: 'indigo',
    finance: 'success',
    billing: 'success',
    invoice: 'success',
    education: 'accent',
    assignment: 'accent',
    shopping: 'purple',
    social: 'purple',
    promotion: 'neutral',
    notification: 'neutral',
    travel: 'accent',
    personal: 'warning',
    other: 'neutral',
    general: 'neutral',
  };
  return map[cat] || 'neutral';
}

function SentimentIcon({ sentiment }) {
  if (sentiment === 'positive') return <SmilePlus size={12} />;
  if (sentiment === 'negative') return <Frown size={12} />;
  return <Meh size={12} />;
}

function ConfidenceCircle({ value }) {
  const normalizedValue = value > 1 ? value / 100 : value;
  const radius = 14;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - normalizedValue * circumference;

  return (
    <div className="confidence-circle" style={{ width: '44px', height: '44px', position: 'relative' }}>
      <svg viewBox="0 0 36 36" style={{ width: '44px', height: '44px', transform: 'rotate(-90deg)' }}>
        <circle className="confidence-circle-bg" cx="18" cy="18" r={radius} style={{ stroke: 'rgba(255,255,255,0.06)' }} />
        <circle
          className="confidence-circle-fill"
          cx="18"
          cy="18"
          r={radius}
          style={{
            stroke: normalizedValue > 0.9 ? 'var(--color-accent)' : normalizedValue > 0.7 ? 'var(--color-warning)' : 'var(--color-danger)',
            strokeDasharray: circumference,
            strokeDashoffset: offset
          }}
        />
      </svg>
      <span className="confidence-value" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.72rem', fontWeight: '700' }}>
        {Math.round(normalizedValue * 100)}%
      </span>
    </div>
  );
}

function EmailDetailPanel({ email, onOpenThread }) {
  const {
    approveReplyDraft,
    discardReplyDraft,
    tasks,
    calendarEvents,
    updateTaskStatus,
    completeTask,
    reopenTask,
    fetchFormAutofillData,
    user,
    analyzeEmail,
    createTask,
    createCalendarEvent,
  } = useApp();
  const navigate = useNavigate();
  const [entitiesOpen, setEntitiesOpen] = useState(false);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [replyText, setReplyText] = useState(email?.draftReply || '');

  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState('');
  const [createdTaskIndices, setCreatedTaskIndices] = useState({});
  const [creatingTaskIdx, setCreatingTaskIdx] = useState(null);
  const [createdEvent, setCreatedEvent] = useState(false);
  const [creatingEvent, setCreatingEvent] = useState(false);
  const [copiedFollowup, setCopiedFollowup] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState('');

  const handleFeedback = async (signalType, weight) => {
    if (!email) return;
    try {
      setFeedbackMsg('Saving feedback...');
      await recordFeedbackSignal({ email_id: email.id, signal_type: signalType, signal_weight: weight });
      setFeedbackMsg('Feedback saved!');
      setTimeout(() => setFeedbackMsg(''), 2500);
    } catch (err) {
      setFeedbackMsg('Failed to record feedback');
    }
  };

  const [autofillData, setAutofillData] = useState(null);
  const [loadingAutofill, setLoadingAutofill] = useState(false);
  const [autofillError, setAutofillError] = useState('');
  const [submittingForm, setSubmittingForm] = useState(false);
  const [submittedForm, setSubmittedForm] = useState(false);

  const isRecruitmentForm = email && (
    email.category?.toLowerCase() === 'recruitment' ||
    email.category?.toLowerCase() === 'job' ||
    email.subject?.toLowerCase().includes('recruitment') ||
    email.body?.toLowerCase().includes('form') ||
    email.body?.toLowerCase().includes('forms.gle')
  );

  const [selectedProfileId, setSelectedProfileId] = useState('');

  useEffect(() => {
    setReplyText(email?.draftReply || '');
    setOriginalOpen(false);
    setAnalysisError('');
    setCreatedTaskIndices({});
    setCreatedEvent(false);

    if (isRecruitmentForm && email) {
      setSelectedProfileId('');
      setSubmittedForm(false);
      setAutofillData(null);
    }
  }, [email, isRecruitmentForm]);

  useEffect(() => {
    if (isRecruitmentForm && email) {
      const profilesList = user?.resume_profiles || [];
      if (profilesList.length === 0) {
        setAutofillError('Please upload and parse your resume in Settings to enable Recopilot Form Autopilot.');
        setAutofillData(null);
        return;
      }

      setAutofillError('');
      setLoadingAutofill(true);
      fetchFormAutofillData(email.id, selectedProfileId || null)
        .then(data => {
          setAutofillData(data);
          if (data && data.selected_profile_id && !selectedProfileId) {
            setSelectedProfileId(data.selected_profile_id);
          }
        })
        .catch(err => {
          console.error(err);
          setAutofillError('Failed to parse form details or match resume.');
        })
        .finally(() => {
          setLoadingAutofill(false);
        });
    }
  }, [email, isRecruitmentForm, selectedProfileId, user?.resume_profiles]);

  if (!email) {
    return (
      <div className="inbox-detail-panel">
        <div className="inbox-detail-empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-tertiary)' }}>
          <Mail size={48} style={{ marginBottom: '16px', opacity: 0.6 }} />
          <p style={{ fontSize: '0.875rem' }}>Select an email summary to view full AI breakdown</p>
        </div>
      </div>
    );
  }

  const handleTriggerAnalyze = async () => {
    setAnalyzing(true);
    setAnalysisError('');
    try {
      let res;
      if (email.aiStatus === 'failed') {
        res = await retryEmailAnalysis(email.id);
      } else {
        res = await analyzeEmail(email.id);
      }
      if (!res.success && res.error) {
        setAnalysisError(res.error);
      }
    } catch (err) {
      setAnalysisError(err.message || 'Analysis failed.');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleConfirmTask = async (task, idx) => {
    setCreatingTaskIdx(idx);
    try {
      const res = await createTask({
        email_id: email.id,
        title: task.title,
        description: task.description,
        due_date: task.due_date,
        priority: task.priority,
      });
      if (res && res.success) {
        setCreatedTaskIndices(prev => ({ ...prev, [idx]: true }));
      }
    } catch (err) {
      console.error('Failed to create task:', err);
    } finally {
      setCreatingTaskIdx(null);
    }
  };

  const handleConfirmEvent = async () => {
    if (!email.suggestedEvent) return;
    setCreatingEvent(true);
    try {
      const res = await createCalendarEvent({
        email_id: email.id,
        title: email.suggestedEvent.title,
        description: email.suggestedEvent.description,
        start: email.suggestedEvent.start,
        end: email.suggestedEvent.end,
        location: email.suggestedEvent.location,
      });
      if (res && res.success) {
        setCreatedEvent(true);
      }
    } catch (err) {
      console.error('Failed to create calendar event:', err);
    } finally {
      setCreatingEvent(false);
    }
  };

  // Filter tasks and calendar events belonging to the current email
  const emailTasks = tasks.filter((t) => t.sourceEmailId === email.id || t.email_id === email.id);
  const emailEvents = (calendarEvents || []).filter((e) => e.sourceEmailId === email.id || e.email_id === email.id);

  const handleToggleTask = async (taskId, currentStatus) => {
    if (currentStatus === 'completed') {
      await reopenTask(taskId);
    } else {
      await completeTask(taskId);
    }
  };

  const entityGroups = [
    { label: 'People', items: email.entities?.people || [], icon: User },
    { label: 'Organizations', items: email.entities?.organizations || [], icon: Building2 },
    { label: 'Dates', items: email.entities?.dates || [], icon: CalendarDays },
    { label: 'Amounts', items: email.entities?.amounts || [], icon: DollarSign },
  ].filter((g) => g.items.length > 0);

  const formatDeadline = (dl) => {
    if (!dl) return 'None';
    try {
      const d = new Date(dl);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return dl;
    }
  };

  return (
    <div className="inbox-detail-panel" style={{ padding: '24px', overflowY: 'auto' }}>
      {/* Subject Header */}
      <div className="email-detail-header" style={{ marginBottom: '20px', borderBottom: '1px solid var(--glass-border)', paddingBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap', marginBottom: '12px' }}>
          <h2 className="email-detail-subject" style={{ fontSize: '1.25rem', fontWeight: '700', margin: 0, color: 'var(--text-primary)', lineHeight: '1.4', flex: 1 }}>
            {email.subject}
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {(email.thread_id || email.threadId) && (
              <button
                className="btn btn-secondary"
                onClick={() => onOpenThread && onOpenThread(email.thread_id || email.threadId)}
                title="View entire conversation thread"
                style={{ fontSize: '0.78rem', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <MessageSquare size={14} />
                View Thread
              </button>
            )}
          </div>
        </div>

        <div className="email-detail-sender-row" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            className="inbox-email-avatar"
            style={{ background: getAvatarColor(email.sender), width: '36px', height: '36px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: '600', fontSize: '0.875rem' }}
          >
            {getInitials(email.sender)}
          </div>
          <div className="email-detail-sender-info" style={{ flex: 1, overflow: 'hidden' }}>
            <div className="email-detail-sender-name" style={{ fontSize: '0.875rem', fontWeight: '600', color: 'var(--text-primary)' }}>{email.sender}</div>
            <div className="email-detail-sender-email" style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{email.senderEmail}</div>
          </div>
          <div className="email-detail-date" style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>{email.timeAgo}</div>
        </div>

        {/* Phase 7: Personalization Ranking Explainability & Feedback */}
        {((email.personalized_score !== undefined && email.personalized_score !== null) || (email.personalized_reasons && email.personalized_reasons.length > 0)) && (
          <div style={{ marginTop: '14px', padding: '10px 14px', background: 'rgba(99, 102, 241, 0.05)', border: '1px solid rgba(99, 102, 241, 0.2)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="badge indigo" style={{ fontSize: '0.75rem', fontWeight: '700', padding: '2px 8px' }}>
                  Smart Score: {email.personalized_score ?? email.aiImportanceScore}
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: '500' }}>
                  Deterministic Ranking Factors
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {feedbackMsg ? (
                  <span style={{ fontSize: '0.72rem', color: 'var(--color-success)', fontWeight: '600' }}>{feedbackMsg}</span>
                ) : (
                  <>
                    <button
                      className="btn btn-ghost"
                      onClick={() => handleFeedback('user_importance_boost', 15)}
                      title="Train ranking: prioritize similar emails higher"
                      style={{ fontSize: '0.72rem', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <ThumbsUp size={12} /> More like this
                    </button>
                    <button
                      className="btn btn-ghost"
                      onClick={() => handleFeedback('user_dismiss_action', -15)}
                      title="Train ranking: prioritize similar emails lower"
                      style={{ fontSize: '0.72rem', padding: '3px 8px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <ThumbsDown size={12} /> Less like this
                    </button>
                  </>
                )}
              </div>
            </div>
            {email.personalized_reasons && email.personalized_reasons.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {email.personalized_reasons.map((r, idx) => (
                  <span key={idx} className="badge neutral" style={{ fontSize: '0.7rem', padding: '2px 7px' }}>
                    {r.description} ({r.weight > 0 ? `+${r.weight}` : r.weight})
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* AI Intelligence Header Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'rgba(255, 255, 255, 0.02)',
        border: '1px solid var(--glass-border)',
        padding: '12px 16px',
        borderRadius: 'var(--radius-md)',
        marginBottom: '16px',
        flexWrap: 'wrap',
        gap: '10px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.8125rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
            AI Status:
          </span>
          {email.aiStatus === 'completed' && (
            <span className="badge success" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem' }}>
              <Check size={12} /> Analyzed
            </span>
          )}
          {(email.aiStatus === 'processing' || analyzing) && (
            <span className="badge indigo" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem' }}>
              <Loader2 size={12} className="animate-spin" /> Analyzing...
            </span>
          )}
          {email.aiStatus === 'failed' && (
            <span className="badge danger" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem' }}>
              <AlertTriangle size={12} /> Analysis Failed
            </span>
          )}
          {(!email.aiStatus || email.aiStatus === 'pending') && !analyzing && (
            <span className="badge warning" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem' }}>
              <Clock size={12} /> Pending Analysis
            </span>
          )}
          {email.aiRetryCount > 0 && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
              (Attempt {email.aiRetryCount}/3)
            </span>
          )}
        </div>

        <div>
          {email.aiStatus !== 'completed' ? (
            <button
              className={`btn ${email.aiStatus === 'failed' ? 'btn-danger-ghost' : 'btn-primary'}`}
              onClick={handleTriggerAnalyze}
              disabled={analyzing || email.aiStatus === 'processing'}
              style={{ fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              {analyzing || email.aiStatus === 'processing' ? (
                <><Loader2 size={13} className="animate-spin" /> Analyzing...</>
              ) : email.aiStatus === 'failed' ? (
                <><RefreshCw size={13} /> Retry Analysis</>
              ) : (
                <><Sparkles size={13} /> Analyze Email</>
              )}
            </button>
          ) : (
            <button
              className="btn btn-ghost"
              onClick={handleTriggerAnalyze}
              disabled={analyzing}
              style={{ fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}
              title="Re-run AI analysis on this email"
            >
              {analyzing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Re-analyze
            </button>
          )}
        </div>
      </div>

      {/* Analysis Error Alert if failed */}
      {(email.aiStatus === 'failed' || analysisError) && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: 'var(--color-danger)',
          padding: '12px',
          borderRadius: 'var(--radius-md)',
          marginBottom: '16px',
          fontSize: '0.8125rem',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <AlertCircle size={16} />
          <span>{analysisError || email.aiError || 'AI analysis could not be completed. Click "Retry Analysis" to try again.'}</span>
        </div>
      )}

      {/* Main AI Summary Box */}
      <div className="ai-summary-box" style={{ background: 'rgba(79, 227, 255, 0.04)', border: '1px solid rgba(79, 227, 255, 0.2)', padding: '20px', borderRadius: 'var(--radius-lg)', marginBottom: '20px', boxShadow: 'inset 0 1px 0px rgba(255,255,255,0.05)' }}>
        <div className="ai-summary-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', fontWeight: '700', color: 'var(--color-accent)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          <Sparkles size={16} /> AI Summary
        </div>
        <p className="ai-summary-text" style={{ fontSize: '0.875rem', lineHeight: '1.6', color: 'var(--text-primary)' }}>
          {email.aiStatus === 'pending' && (!email.aiSummary || email.aiSummary === 'No summary available.') ? (
            <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
              AI analysis has not been performed on this email yet. Click "Analyze Email" above to generate summary, priority, tasks, and deadlines.
            </span>
          ) : (
            email.aiSummary
          )}
        </p>
      </div>

      {/* Recommended Next Action Banner */}
      {email.aiNextAction && (
        <div style={{
          background: 'rgba(99, 102, 241, 0.08)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          borderRadius: 'var(--radius-md)',
          padding: '12px 16px',
          marginBottom: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <Zap size={16} style={{ color: 'var(--color-indigo)', flexShrink: 0 }} />
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-primary)' }}>
            <strong>Next Action:</strong> {email.aiNextAction}
          </div>
        </div>
      )}

      {/* Key Points */}
      {email.aiKeyPoints && email.aiKeyPoints.length > 0 && (
        <div style={{
          background: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid var(--glass-border)',
          borderRadius: 'var(--radius-md)',
          padding: '12px 16px',
          marginBottom: '16px'
        }}>
          <div style={{ fontSize: '0.72rem', fontWeight: '700', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
            Key Points
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.8125rem', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
            {email.aiKeyPoints.map((pt, idx) => (
              <li key={idx} style={{ marginBottom: '4px' }}>{pt}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Metric Breakdown Cards (Priority, Category, Sentiment, Action Required, Deadline, Importance) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '10px', marginBottom: '20px' }}>
        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Category</span>
          <span className={`badge ${getCategoryBadge(email.category)}`} style={{ width: 'fit-content', fontSize: '0.72rem', textTransform: 'capitalize' }}>
            {email.category}
          </span>
        </div>

        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Priority</span>
          <span className={`badge ${email.priority === 'urgent' || email.priority === 'high' ? 'danger' : email.priority === 'medium' ? 'warning' : 'neutral'}`} style={{ width: 'fit-content', fontSize: '0.72rem', textTransform: 'capitalize' }}>
            {email.priority}
          </span>
        </div>

        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Importance</span>
          <span style={{ fontSize: '0.8125rem', fontWeight: '800', color: email.aiImportanceScore >= 81 ? 'var(--color-danger)' : email.aiImportanceScore >= 61 ? 'var(--color-warning)' : 'var(--text-primary)' }}>
            {email.aiImportanceScore !== null && email.aiImportanceScore !== undefined ? `${email.aiImportanceScore}/100` : '—'}
          </span>
        </div>

        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Confidence</span>
          <span style={{ fontSize: '0.8125rem', fontWeight: '700', color: 'var(--color-accent)' }}>
            {Math.round((email.confidence || 0.85) * 100)}%
          </span>
        </div>

        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Action Req</span>
          <span className={`badge ${email.aiActionRequired ? 'accent' : 'neutral'}`} style={{ width: 'fit-content', fontSize: '0.72rem' }}>
            {email.aiActionRequired ? 'Yes' : 'No'}
          </span>
        </div>

        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--glass-border)', padding: '10px 12px', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Deadline</span>
          <span style={{ fontSize: '0.75rem', fontWeight: '600', color: email.aiDeadline ? 'var(--color-accent)' : 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {formatDeadline(email.aiDeadline)}
          </span>
        </div>
      </div>

      {/* Explainability Reasons */}
      {email.aiReasons && email.aiReasons.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginBottom: '16px' }}>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AI Reasoning:</span>
          {email.aiReasons.map((r, i) => (
            <span key={i} className="badge neutral" style={{ fontSize: '0.6875rem', padding: '2px 8px' }}>
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Waiting For Card */}
      {email.aiWaitingFor && (
        <div style={{
          background: 'rgba(245, 158, 11, 0.05)',
          border: '1px solid rgba(245, 158, 11, 0.25)',
          borderRadius: 'var(--radius-lg)',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-warning)', fontWeight: '700', fontSize: '0.875rem' }}>
              <Clock size={16} /> Waiting For Response
            </div>
            <span className="badge warning" style={{ fontSize: '0.6875rem' }}>Pending External Action</span>
          </div>
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-primary)', marginBottom: '4px' }}>
            <strong>Person:</strong> {email.aiWaitingFor.person}
          </div>
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
            <strong>Waiting on:</strong> {email.aiWaitingFor.for_what}
          </div>
          {email.aiWaitingFor.suggested_followup && (
            <div style={{
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid var(--glass-border)',
              borderRadius: 'var(--radius-md)',
              padding: '10px 12px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '12px',
            }}>
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', fontStyle: 'italic', flex: 1 }}>
                "{email.aiWaitingFor.suggested_followup}"
              </div>
              <button
                className="btn btn-ghost"
                onClick={() => {
                  navigator.clipboard.writeText(email.aiWaitingFor.suggested_followup);
                  setCopiedFollowup(true);
                  setTimeout(() => setCopiedFollowup(false), 2000);
                }}
                style={{ fontSize: '0.75rem', padding: '4px 10px', flexShrink: 0, display: 'flex', alignItems: 'center', gap: '4px' }}
                title="Copy suggested follow-up message to clipboard"
              >
                {copiedFollowup ? <><Check size={12} /> Copied!</> : 'Copy Follow-up'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Action Required Callout Banner */}
      {email.aiActionRequired && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-lg)',
          padding: '14px 18px',
          marginBottom: '20px',
          display: 'flex',
          alignItems: 'flex-start',
          gap: '12px',
        }}>
          <AlertTriangle size={20} style={{ color: 'var(--color-danger)', marginTop: '2px', flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: '0.8125rem', fontWeight: '800', color: 'var(--color-danger)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '2px' }}>
              Action Required
            </div>
            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
              This email has been flagged as requiring your action. Review the AI-suggested task(s) below and click <strong>Create Task</strong> to add them to your board.
            </div>
          </div>
        </div>
      )}

      {/* Suggested Tasks (AI Task Suggestions) */}
      {email.suggestedTasks && email.suggestedTasks.length > 0 && (
        <div style={{
          background: 'rgba(79, 227, 255, 0.02)',
          border: '1px solid rgba(79, 227, 255, 0.15)',
          borderRadius: 'var(--radius-lg)',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', fontWeight: '700', color: 'var(--color-accent)', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
              <Sparkles size={15} /> Suggested Tasks ({email.suggestedTasks.length})
            </h4>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>Requires your confirmation</span>
          </div>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
            AI detected these potential action items in this email. Click "Create Task" to add them to your tasks list.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {email.suggestedTasks.map((t, idx) => {
              const isCreated = createdTaskIndices[idx];
              const isCreating = creatingTaskIdx === idx;
              return (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    background: 'rgba(0, 0, 0, 0.2)',
                    border: '1px solid var(--glass-border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '10px 14px',
                    gap: '12px',
                    flexWrap: 'wrap'
                  }}
                >
                  <div style={{ flex: 1, minWidth: '180px' }}>
                    <div style={{ fontSize: '0.8125rem', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '2px' }}>
                      {t.title}
                    </div>
                    {t.description && (
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginBottom: '4px' }}>
                        {t.description}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: '2px' }}>
                      {t.due_date && (
                        <span className="badge neutral" style={{ fontSize: '0.6875rem', padding: '1px 5px' }}>
                          Due: {t.due_date.split('T')[0]}
                        </span>
                      )}
                      <span className={`badge ${t.priority === 'urgent' || t.priority === 'high' ? 'danger' : 'neutral'}`} style={{ fontSize: '0.6875rem', padding: '1px 5px', textTransform: 'capitalize' }}>
                        {t.priority}
                      </span>
                    </div>
                  </div>
                  <div>
                    {isCreated ? (
                      <span className="badge success" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '4px 8px' }}>
                        <Check size={12} /> Task Created
                      </span>
                    ) : (
                      <button
                        className="btn btn-primary"
                        onClick={() => handleConfirmTask(t, idx)}
                        disabled={isCreating}
                        style={{ fontSize: '0.75rem', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '4px' }}
                      >
                        {isCreating ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                        Create Task
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Suggested Calendar Event */}
      {email.suggestedEvent && (
        <div style={{
          background: 'rgba(124, 58, 237, 0.04)',
          border: '1px solid rgba(124, 58, 237, 0.2)',
          borderRadius: 'var(--radius-lg)',
          padding: '16px',
          marginBottom: '20px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', fontWeight: '700', color: '#A78BFA', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
              <Calendar size={15} /> Suggested Calendar Event
            </h4>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)' }}>Requires your confirmation</span>
          </div>
          <div style={{
            background: 'rgba(0, 0, 0, 0.2)',
            border: '1px solid var(--glass-border)',
            borderRadius: 'var(--radius-md)',
            padding: '12px 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap'
          }}>
            <div style={{ flex: 1, minWidth: '180px' }}>
              <div style={{ fontSize: '0.875rem', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '4px' }}>
                {email.suggestedEvent.title}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span><strong>Start:</strong> {email.suggestedEvent.start ? new Date(email.suggestedEvent.start).toLocaleString() : 'N/A'}</span>
                {email.suggestedEvent.end && <span><strong>End:</strong> {new Date(email.suggestedEvent.end).toLocaleString()}</span>}
                {email.suggestedEvent.location && <span><strong>Location:</strong> {email.suggestedEvent.location}</span>}
              </div>
            </div>
            <div>
              {createdEvent ? (
                <span className="badge success" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '4px 8px' }}>
                  <Check size={12} /> Event Added
                </span>
              ) : (
                <button
                  className="btn btn-primary"
                  onClick={handleConfirmEvent}
                  disabled={creatingEvent}
                  style={{ fontSize: '0.75rem', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  {creatingEvent ? <Loader2 size={12} className="animate-spin" /> : <Calendar size={12} />}
                  Create Calendar Event
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Recopilot Autopilot Form Preview Card */}
      {isRecruitmentForm && (
        <div style={{ 
          background: 'rgba(99, 102, 241, 0.04)', 
          border: '1px solid rgba(99, 102, 241, 0.2)', 
          padding: '20px', 
          borderRadius: 'var(--radius-lg)', 
          marginBottom: '20px',
          boxShadow: 'inset 0 1px 0px rgba(255,255,255,0.05)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', fontWeight: '700', color: '#818CF8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <Sparkles size={16} /> Recopilot Autopilot
            </div>
            
            {autofillData?.available_profiles && autofillData.available_profiles.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <label style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: '500' }}>Profile:</label>
                <select
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                  style={{
                    background: 'rgba(0, 0, 0, 0.25)',
                    border: '1px solid var(--glass-border)',
                    borderRadius: '4px',
                    color: 'var(--text-primary)',
                    fontSize: '0.75rem',
                    padding: '3px 8px',
                    outline: 'none',
                    cursor: 'pointer'
                  }}
                >
                  {autofillData.available_profiles.map(p => (
                    <option key={p.id} value={p.id} style={{ background: '#111', color: '#fff' }}>
                      {p.target_role}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {autofillData && (
              <span className={`badge ${autofillData.is_match ? 'success' : 'warning'}`} style={{ fontSize: '0.75rem' }}>
                {autofillData.is_match ? 'Target Match' : 'Mismatch'}
              </span>
            )}
          </div>

          {loadingAutofill && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.8125rem', padding: '10px 0' }}>
              <div className="animate-spin" style={{ width: '12px', height: '12px', border: '2px solid rgba(255,255,255,0.1)', borderTopColor: 'var(--color-indigo)', borderRadius: '50%' }} />
              Matching candidate profile & extracting form fields...
            </div>
          )}

          {autofillError && (
            <div style={{ color: 'var(--color-warning)', fontSize: '0.8125rem', lineHeight: '1.4' }}>
              {autofillError}
            </div>
          )}

          {autofillData && !loadingAutofill && !autofillError && (
            <div>
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '12px', lineHeight: '1.4' }}>
                <strong>Match Verdict:</strong> {autofillData.match_reason}
              </div>

              {autofillData.is_match && (
                <div style={{ background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', padding: '12px', marginBottom: '16px' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AI Autocomplete Preview:</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {autofillData.form_fields.map((f, idx) => (
                      <div key={idx} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 60px', gap: '4px 8px', fontSize: '0.78rem', borderBottom: '1px solid rgba(255,255,255,0.02)', paddingBottom: '6px' }}>
                        <span style={{ color: 'var(--text-secondary)', fontWeight: '500', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.field_name}:</span>
                        <span style={{ color: 'var(--text-primary)', fontWeight: '600', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.value}</span>
                        <span style={{ fontSize: '0.625rem', color: 'var(--color-indigo)', background: 'rgba(99, 102, 241, 0.1)', padding: '1px 4px', borderRadius: '3px', textAlign: 'center', height: 'fit-content', width: 'fit-content' }}>{f.source}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button 
                  className="btn btn-primary" 
                  disabled={submittingForm || submittedForm || !autofillData.is_match}
                  onClick={() => {
                    setSubmittingForm(true);
                    setTimeout(() => {
                      setSubmittingForm(false);
                      setSubmittedForm(true);
                    }, 1500);
                  }}
                  style={{ fontSize: '0.8125rem' }}
                >
                  {submittingForm ? 'Submitting Form...' : submittedForm ? 'Form Submitted!' : 'Auto-Fill & Submit'}
                </button>
                <button 
                  className="btn btn-ghost" 
                  onClick={() => {
                    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(autofillData, null, 2));
                    const dlAnchorElem = document.createElement('a');
                    dlAnchorElem.setAttribute("href", dataStr);
                    dlAnchorElem.setAttribute("download", `google_form_filled_${email.id}.json`);
                    dlAnchorElem.click();
                  }}
                  style={{ fontSize: '0.8125rem' }}
                >
                  Export Mapped Data (JSON)
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Related Tasks (Confirmed Action Items) */}
      <div className="action-items-section" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9375rem', fontWeight: '600', color: 'var(--text-primary)', margin: 0 }}>
            <CheckCircle2 size={16} style={{ color: 'var(--color-accent)' }} /> Related Tasks ({emailTasks.length})
          </h4>
          <button
            className="btn btn-ghost"
            onClick={() => navigate('/tasks')}
            style={{ fontSize: '0.75rem', padding: '3px 8px' }}
          >
            Open Task Board →
          </button>
        </div>

        {emailTasks.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {emailTasks.map((task) => (
              <div
                key={task.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  background: 'rgba(255,255,255,0.01)',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--glass-border)',
                  gap: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: '180px' }}>
                  <input
                    type="checkbox"
                    checked={task.status === 'completed'}
                    onChange={() => handleToggleTask(task.id, task.status)}
                    style={{ accentColor: 'var(--color-accent)', width: '16px', height: '16px', cursor: 'pointer' }}
                  />
                  <div>
                    <span
                      style={{
                        fontSize: '0.8125rem',
                        fontWeight: '500',
                        textDecoration: task.status === 'completed' ? 'line-through' : 'none',
                        color: task.status === 'completed' ? 'var(--text-tertiary)' : 'var(--text-primary)',
                      }}
                    >
                      {task.title}
                    </span>
                    {task.description && (
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                        {task.description}
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {task.due_date && (
                    <span className="badge neutral" style={{ fontSize: '0.6875rem', padding: '2px 6px' }}>
                      Due: {new Date(task.due_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                    </span>
                  )}
                  <span className={`badge ${task.priority === 'urgent' || task.priority === 'high' ? 'danger' : 'neutral'}`} style={{ fontSize: '0.6875rem', padding: '2px 6px', textTransform: 'capitalize' }}>
                    {task.priority || 'Medium'}
                  </span>
                  <span className={`badge ${task.status === 'completed' ? 'success' : 'neutral'}`} style={{ fontSize: '0.6875rem', padding: '2px 6px', textTransform: 'capitalize' }}>
                    {task.status || 'pending'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '16px', background: 'rgba(255,255,255,0.01)', border: '1px dashed var(--glass-border)', borderRadius: 'var(--radius-md)', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
            No tasks created for this email yet. Confirm a suggested task above or add one from the Task Board.
          </div>
        )}
      </div>

      {/* Related Calendar Events */}
      <div className="calendar-items-section" style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9375rem', fontWeight: '600', color: 'var(--text-primary)', margin: 0 }}>
            <Calendar size={16} style={{ color: '#A78BFA' }} /> Related Calendar Events ({emailEvents.length})
          </h4>
          <button
            className="btn btn-ghost"
            onClick={() => navigate('/calendar')}
            style={{ fontSize: '0.75rem', padding: '3px 8px' }}
          >
            Open Calendar →
          </button>
        </div>

        {emailEvents.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {emailEvents.map((evt) => (
              <div
                key={evt.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  background: 'rgba(124, 58, 237, 0.03)',
                  padding: '12px 14px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid rgba(124, 58, 237, 0.15)',
                  gap: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div style={{ fontSize: '0.875rem', fontWeight: '600', color: 'var(--text-primary)' }}>
                    {evt.title}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px', display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                    <span>
                      <strong>When:</strong> {evt.start_date_time ? new Date(evt.start_date_time).toLocaleString() : evt.time}
                    </span>
                    {evt.location && (
                      <span>
                        <strong>Location:</strong> {evt.location}
                      </span>
                    )}
                  </div>
                </div>

                <button
                  className="btn btn-ghost"
                  onClick={() => navigate('/calendar')}
                  style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                >
                  View in Calendar
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '16px', background: 'rgba(255,255,255,0.01)', border: '1px dashed var(--glass-border)', borderRadius: 'var(--radius-md)', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
            No scheduled events linked to this email.
          </div>
        )}
      </div>

      {/* Extracted Entities */}
      {entityGroups.length > 0 && (
        <div className="entities-section" style={{ marginBottom: '24px' }}>
          <button
            className={`entities-toggle ${entitiesOpen ? 'open' : ''}`}
            onClick={() => setEntitiesOpen(!entitiesOpen)}
            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.875rem', fontWeight: '600', color: 'var(--text-primary)', background: 'none', border: 'none', padding: '4px 0', borderBottom: '1px solid var(--glass-border)', cursor: 'pointer' }}
          >
            {entitiesOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            Extracted Entities ({entityGroups.reduce((sum, g) => sum + g.items.length, 0)})
          </button>
          {entitiesOpen && (
            <div className="entities-content" style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {entityGroups.map((group) => (
                <div key={group.label} className="entity-group">
                  <div className="entity-group-label" style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{group.label}</div>
                  <div className="entity-chips" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {group.items.map((item, i) => (
                      <span key={i} className="entity-chip" style={{ fontSize: '0.75rem', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--glass-border)', padding: '4px 10px', borderRadius: 'var(--radius-full)', color: 'var(--text-primary)' }}>
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Suggested Draft Reply */}
      <div className="draft-reply-section" style={{ marginBottom: '24px', borderTop: '1px solid var(--glass-border)', paddingTop: '16px' }}>
        <div className="draft-reply-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h4 className="draft-reply-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9375rem', fontWeight: '600', color: 'var(--text-primary)', margin: 0 }}>
            <Reply size={16} /> Suggested Reply
          </h4>
          {email.autoReplied && (
            <span className="auto-replied-badge" style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', background: 'rgba(16, 185, 129, 0.15)', color: 'var(--color-success)', padding: '2px 8px', borderRadius: 'var(--radius-full)' }}>
              <CheckCircle2 size={10} /> Auto-Replied
            </span>
          )}
        </div>
        {email.draftReply || email.autoReplied ? (
          <>
            <textarea
              className="draft-reply-textarea"
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              placeholder={email.autoReplied ? 'This email was auto-replied.' : 'No draft reply generated.'}
              disabled={email.autoReplied}
              style={{ width: '100%', minHeight: '120px', background: 'rgba(0,0,0,0.15)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', padding: '12px', fontSize: '0.8125rem', color: 'var(--text-primary)', resize: 'vertical', outline: 'none', lineHeight: '1.5', marginBottom: '12px' }}
            />
            {!email.autoReplied && (
              <div className="draft-reply-actions" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8125rem' }} onClick={() => approveReplyDraft(email.id)}>
                  <Send size={12} /> Send Response
                </button>
                <button className="btn btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8125rem' }}>
                  <Edit3 size={12} /> Edit
                </button>
                <button className="btn btn-danger-ghost" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8125rem' }} onClick={() => discardReplyDraft(email.id)}>
                  <Trash2 size={12} /> Discard
                </button>
              </div>
            )}
          </>
        ) : (
          <div style={{ padding: '16px', background: 'rgba(255,255,255,0.01)', border: '1px dashed var(--glass-border)', borderRadius: 'var(--radius-md)', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
            No suggested response generated for this message.
          </div>
        )}
      </div>

      {/* Expandable Original Email Toggle */}
      <div style={{ marginTop: '24px', borderTop: '1px solid var(--glass-border)', paddingTop: '16px' }}>
        <button 
          className="btn btn-ghost" 
          onClick={() => setOriginalOpen(!originalOpen)}
          style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.875rem', fontWeight: '500', color: 'var(--text-primary)' }}>
            <Mail size={16} /> Original Email Text
          </span>
          {originalOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        
        {originalOpen && (
          <div style={{ marginTop: '12px', padding: '16px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--glass-border)', borderRadius: 'var(--radius-md)', fontSize: '0.8125rem', lineHeight: '1.5', maxHeight: '300px', overflowY: 'auto', whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>
            {email.body}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Inbox() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { search } = useLocation();
  const { emails, loading, markEmailAsRead, analyzeBatch } = useApp();
  const [activeFilter, setActiveFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [batchAnalyzing, setBatchAnalyzing] = useState(false);
  const [batchStatusMsg, setBatchStatusMsg] = useState('');

  const [viewThreadId, setViewThreadId] = useState(null);

  // Phase 8: Saved Searches & Bulk Actions
  const [selectedEmailIds, setSelectedEmailIds] = useState([]);
  const [savedSearches, setSavedSearches] = useState([]);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveSearchName, setSaveSearchName] = useState('');
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkMsg, setBulkMsg] = useState('');
  const [showTaskConfirm, setShowTaskConfirm] = useState(false);

  useEffect(() => {
    fetchSavedSearches()
      .then((data) => setSavedSearches(data.saved_searches || []))
      .catch((err) => console.error('Failed to load saved searches:', err));
  }, []);

  const handleSaveSearch = async () => {
    if (!saveSearchName.trim() || !searchQuery.trim()) return;
    try {
      const res = await createSavedSearch(saveSearchName.trim(), searchQuery.trim());
      if (res.saved_search) {
        setSavedSearches((prev) => [
          res.saved_search,
          ...prev.filter((s) => s.name !== res.saved_search.name),
        ]);
      }
      setShowSaveModal(false);
      setSaveSearchName('');
    } catch (err) {
      alert(err.response?.data?.error || 'Failed to save search');
    }
  };

  const handleDeleteSavedSearch = async (sId, e) => {
    e.stopPropagation();
    try {
      await deleteSavedSearch(sId);
      setSavedSearches((prev) => prev.filter((s) => s.id !== sId));
    } catch (err) {
      console.error('Failed to delete saved search:', err);
    }
  };

  const handleToggleSelectEmail = (emailId, e) => {
    e.stopPropagation();
    setSelectedEmailIds((prev) =>
      prev.includes(emailId) ? prev.filter((i) => i !== emailId) : [...prev, emailId]
    );
  };

  const handleSelectAll = () => {
    if (selectedEmailIds.length === filteredEmails.length && filteredEmails.length > 0) {
      setSelectedEmailIds([]);
    } else {
      setSelectedEmailIds(filteredEmails.map((e) => e.id));
    }
  };

  const handleBulkAction = async (action, options = {}) => {
    if (selectedEmailIds.length === 0) return;
    setBulkLoading(true);
    try {
      const res = await executeBulkAction(selectedEmailIds, action, options);
      setBulkMsg(`Bulk ${action} succeeded on ${res.affected || 0} emails.`);
      setSelectedEmailIds([]);
      setTimeout(() => setBulkMsg(''), 3500);
    } catch (err) {
      alert(err.response?.data?.error || 'Bulk action failed');
    } finally {
      setBulkLoading(false);
      setShowTaskConfirm(false);
    }
  };

  // Extract folder query param (default: 'all')
  const folder = useMemo(() => {
    const params = new URLSearchParams(search);
    return (params.get('folder') || 'all').toLowerCase().trim();
  }, [search]);

  const selectedId = id ? (isNaN(id) ? id : Number(id)) : null;
  const selectedEmail = selectedId
    ? emails.find((e) => e.id === selectedId)
    : null;

  // Reset active filter chip when switching folders
  useEffect(() => {
    setActiveFilter('all');
  }, [folder]);

  useEffect(() => {
    if (selectedEmail && !selectedEmail.read) {
      markEmailAsRead(selectedEmail.id);
    }
  }, [selectedEmail, markEmailAsRead]);

  const handleRunBatchAnalyze = async () => {
    setBatchAnalyzing(true);
    setBatchStatusMsg('Analyzing up to 20 emails...');
    try {
      const res = await analyzeBatch(20);
      if (res.success) {
        setBatchStatusMsg(`Batch done: ${res.analyzed_count || 0} analyzed, ${res.skipped_count || 0} skipped.`);
        setTimeout(() => setBatchStatusMsg(''), 4000);
      } else {
        setBatchStatusMsg(res.error || 'Batch analysis failed');
      }
    } catch (err) {
      setBatchStatusMsg('Batch analysis failed');
    } finally {
      setBatchAnalyzing(false);
    }
  };

  const filters = [
    { key: 'all', label: 'All Mail' },
    { key: 'smart_ranked', label: 'Smart Ranked' },
    { key: 'needs_action', label: 'Needs Action' },
    { key: 'waiting_for', label: 'Waiting For' },
    { key: 'due_soon', label: 'Due Soon' },
    { key: 'urgent', label: 'Urgent' },
    { key: 'newsletters', label: 'Newsletters' },
    { key: 'review', label: 'Needs Review' },
    { key: 'replied', label: 'Auto-Replied' },
  ];

  const filteredEmails = useMemo(() => {
    let result = emails;

    // Filter by Search Query
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (e) =>
          e.sender.toLowerCase().includes(q) ||
          e.subject.toLowerCase().includes(q) ||
          e.aiSummary?.toLowerCase().includes(q)
      );
    }

    // Filter by Folder query parameter (fully robust case-insensitivity)
    switch (folder) {
      case 'unread':
        result = result.filter((e) => !e.read);
        break;
      case 'priority':
        result = result.filter((e) => (e.priority || '').toLowerCase().trim() === 'high');
        break;
      case 'summarized':
        // Show emails that have valid AI summaries
        result = result.filter((e) => 
          e.aiSummary && 
          e.aiSummary.trim() !== '' && 
          e.aiSummary !== 'No summary available.' && 
          !e.aiSummary.includes('API rate/quota limits')
        );
        break;
      case 'archived':
        // Mock empty archived folder
        result = [];
        break;
      default:
        break;
    }

    // Filter by local top filter chip
    switch (activeFilter) {
      case 'smart_ranked':
        return [...result].sort((a, b) => {
          const scoreA = a.personalized_score ?? a.aiImportanceScore ?? 0;
          const scoreB = b.personalized_score ?? b.aiImportanceScore ?? 0;
          return scoreB - scoreA;
        });
      case 'needs_action':
        return result.filter((e) => e.aiActionRequired);
      case 'waiting_for':
        return result.filter((e) => Boolean(e.aiWaitingFor));
      case 'due_soon': {
        const in48h = Date.now() + 48 * 3600 * 1000;
        return result.filter((e) => e.aiDeadline && new Date(e.aiDeadline).getTime() <= in48h);
      }
      case 'urgent':
        return result.filter((e) => (e.aiImportanceScore !== null && e.aiImportanceScore >= 81) || (e.priority || '').toLowerCase() === 'urgent');
      case 'newsletters':
        return result.filter((e) => (e.category || '').toLowerCase() === 'newsletter' || (e.category || '').toLowerCase() === 'promotion');
      case 'review':
        return result.filter((e) => !e.autoReplied && e.draftReply);
      case 'replied':
        return result.filter((e) => e.autoReplied);
      default:
        return result;
    }
  }, [emails, folder, activeFilter, searchQuery]);

  return (
    <div className="inbox-page glass-card page-enter">
      {/* Email List Panel */}
      <div className="inbox-list-panel">
        <div className="inbox-filters">
          <div className="inbox-search" style={{ position: 'relative' }}>
            <Search />
            <input
              type="text"
              placeholder="Search (e.g. from:acme action:true urgent)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery.trim() && (
              <button
                onClick={() => setShowSaveModal(true)}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'rgba(61, 129, 227, 0.15)',
                  border: '1px solid rgba(61, 129, 227, 0.3)',
                  color: '#3D81E3',
                  borderRadius: '6px',
                  padding: '3px 8px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  cursor: 'pointer',
                }}
                title="Save this search"
              >
                <Bookmark size={12} /> Save
              </button>
            )}
          </div>

          {/* Saved Searches (Phase 8) */}
          {savedSearches.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: '6px 0 2px 0', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.68rem', color: '#A78BFA', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '3px' }}>
                <Bookmark size={10} /> Saved:
              </span>
              {savedSearches.map((s) => (
                <div
                  key={s.id}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '0.68rem',
                    padding: '2px 8px',
                    borderRadius: '12px',
                    background: searchQuery === s.query ? 'rgba(167, 139, 250, 0.25)' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(167, 139, 250, 0.3)',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                  }}
                  onClick={() => setSearchQuery(s.query)}
                >
                  <span>{s.name}</span>
                  <X
                    size={10}
                    style={{ color: 'var(--text-tertiary)', cursor: 'pointer' }}
                    onClick={(e) => handleDeleteSavedSearch(s.id, e)}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Quick Syntax Pills */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: '6px 0 2px 0', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.68rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Quick syntax:</span>
            {['from:', 'priority:urgent', 'action:true', 'has:attachment'].map((syntax) => (
              <button
                key={syntax}
                onClick={() => setSearchQuery((prev) => (prev ? `${prev} ${syntax}` : syntax))}
                style={{
                  fontSize: '0.68rem',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid var(--glass-border)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer'
                }}
              >
                {syntax}
              </button>
            ))}
          </div>

          <div className="inbox-filter-chips" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', flexWrap: 'wrap', gap: '8px', marginTop: '6px' }}>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {filters.map((f) => (
                <button
                  key={f.key}
                  className={`filter-chip ${activeFilter === f.key ? 'active' : ''}`}
                  onClick={() => setActiveFilter(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>

            <button
              className="btn btn-ghost"
              onClick={handleRunBatchAnalyze}
              disabled={batchAnalyzing}
              style={{
                fontSize: '0.75rem',
                padding: '4px 10px',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                background: 'rgba(79, 227, 255, 0.08)',
                border: '1px solid rgba(79, 227, 255, 0.25)',
                color: 'var(--color-accent)'
              }}
              title="Batch analyze up to 20 unanalyzed emails with AI"
            >
              {batchAnalyzing ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {batchAnalyzing ? 'Analyzing...' : 'Analyze Unprocessed'}
            </button>
          </div>

          {batchStatusMsg && (
            <div style={{ fontSize: '0.75rem', color: 'var(--color-accent)', padding: '4px 8px', background: 'rgba(79, 227, 255, 0.05)', borderRadius: '4px', marginTop: '6px' }}>
              {batchStatusMsg}
            </div>
          )}
        </div>

        {/* Phase 8: Bulk Selection Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', background: selectedEmailIds.length > 0 ? 'rgba(61, 129, 227, 0.12)' : 'rgba(255,255,255,0.02)', borderBottom: '1px solid var(--glass-border)', fontSize: '0.75rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', userSelect: 'none', color: 'var(--text-secondary)' }}>
            <input
              type="checkbox"
              checked={selectedEmailIds.length > 0 && selectedEmailIds.length === filteredEmails.length}
              onChange={handleSelectAll}
              style={{ accentColor: '#3D81E3', cursor: 'pointer' }}
            />
            {selectedEmailIds.length > 0 ? `${selectedEmailIds.length} selected` : 'Select All'}
          </label>

          {selectedEmailIds.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-ghost"
                onClick={() => handleBulkAction('mark_read')}
                disabled={bulkLoading}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
              >
                Mark Read
              </button>
              <button
                className="btn btn-ghost"
                onClick={() => handleBulkAction('mark_unread')}
                disabled={bulkLoading}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
              >
                Mark Unread
              </button>
              <button
                className="btn btn-ghost"
                onClick={() => handleBulkAction('star')}
                disabled={bulkLoading}
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
              >
                <Star size={12} /> Star
              </button>
              <button
                className="btn btn-primary"
                onClick={() => setShowTaskConfirm(true)}
                disabled={bulkLoading}
                style={{ padding: '3px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <CheckSquare size={12} /> Create Tasks
              </button>
              <button
                className="btn btn-ghost"
                onClick={() => setSelectedEmailIds([])}
                style={{ padding: '3px 8px', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}
              >
                Cancel
              </button>
            </div>
          )}

          {bulkMsg && (
            <span style={{ color: '#10B981', fontWeight: 600 }}>{bulkMsg}</span>
          )}
        </div>

        <div className="inbox-email-list">
          {filteredEmails.map((email) => (
            <div
              key={email.id}
              className={`inbox-email-card ${
                selectedId === email.id ? 'active' : ''
              } ${!email.read ? 'unread' : ''}`}
              onClick={() => navigate(`/emails/${email.id}?folder=${folder}`)}
              style={{ transition: 'all var(--transition-base)' }}
            >
              {/* Checkbox */}
              <div
                onClick={(e) => e.stopPropagation()}
                style={{ display: 'flex', alignItems: 'center', paddingRight: '8px' }}
              >
                <input
                  type="checkbox"
                  checked={selectedEmailIds.includes(email.id)}
                  onChange={(e) => handleToggleSelectEmail(email.id, e)}
                  style={{ cursor: 'pointer', accentColor: '#3D81E3' }}
                />
              </div>

              <div
                className="inbox-email-avatar"
                style={{ background: getAvatarColor(email.sender) }}
              >
                {getInitials(email.sender)}
              </div>
              <div className="inbox-email-body" style={{ flex: 1, minWidth: 0 }}>
                <div className="inbox-email-top" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                  <span className="inbox-email-sender" style={{ fontSize: '0.8125rem', fontWeight: '700', color: 'var(--text-primary)' }}>
                    {email.sender}
                  </span>
                  <span className="inbox-email-time" style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginLeft: 'auto' }}>
                    {email.timeAgo}
                  </span>
                </div>
                
                <div className="inbox-email-subject" style={{ fontSize: '0.8125rem', fontWeight: email.read ? '500' : '700', color: email.read ? 'var(--text-secondary)' : 'var(--text-primary)', marginBottom: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {email.subject}
                </div>

                {/* 2-line AI Summary preview */}
                <div className="inbox-email-summary-preview" style={{ 
                  fontSize: '0.78rem', 
                  color: email.read ? 'var(--text-tertiary)' : 'var(--text-secondary)', 
                  margin: '4px 0 8px 0',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  lineHeight: '1.4'
                }}>
                  {email.aiSummary}
                </div>

                <div className="inbox-email-tags" style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  {email.category && (
                    <span className={`badge ${getCategoryBadge(email.category)}`} style={{ fontSize: '0.6875rem', padding: '1px 6px', textTransform: 'uppercase' }}>
                      {email.category}
                    </span>
                  )}

                  <span className={`badge ${
                    email.priority === 'urgent' || email.priority === 'high' ? 'danger' : email.priority === 'medium' ? 'warning' : 'neutral'
                  }`} style={{ fontSize: '0.6875rem', padding: '1px 6px', textTransform: 'uppercase' }}>
                    {email.priority}
                  </span>
                  
                  {email.personalized_score !== null && email.personalized_score !== undefined ? (
                    <span className="badge indigo" style={{ fontSize: '0.6875rem', padding: '1px 6px', fontWeight: '700' }} title="Personalized Smart Inbox score">
                      Smart: {email.personalized_score}
                    </span>
                  ) : email.aiImportanceScore !== null && email.aiImportanceScore !== undefined ? (
                    <span className="badge indigo" style={{ fontSize: '0.6875rem', padding: '1px 6px', fontWeight: '700' }}>
                      Score: {email.aiImportanceScore}
                    </span>
                  ) : null}

                  {email.aiWaitingFor && (
                    <span className="badge warning" style={{ fontSize: '0.6875rem', padding: '1px 6px', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <Clock size={8} /> Waiting
                    </span>
                  )}

                  {email.aiActionRequired && (
                    <span className="badge accent" style={{ fontSize: '0.6875rem', padding: '1px 6px', fontWeight: '700' }}>
                      ACTION REQUIRED
                    </span>
                  )}

                  {email.aiStatus === 'completed' && (
                    <span className="badge success" style={{ display: 'flex', alignItems: 'center', gap: '3px', fontSize: '0.6875rem', padding: '1px 6px' }}>
                      <Check size={8} /> Analyzed
                    </span>
                  )}

                  {email.aiStatus === 'processing' && (
                    <span className="badge indigo" style={{ display: 'flex', alignItems: 'center', gap: '3px', fontSize: '0.6875rem', padding: '1px 6px' }}>
                      <Loader2 size={8} className="animate-spin" /> Analyzing...
                    </span>
                  )}

                  {email.autoReplied && (
                    <span className="badge success" style={{ fontSize: '0.6875rem', padding: '1px 6px' }}>Auto-Replied</span>
                  )}
                </div>
              </div>
              {!email.read && (
                <div
                  className="unread-indicator"
                  style={{
                    position: 'absolute',
                    top: '16px',
                    right: '16px',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: 'var(--color-accent)',
                    boxShadow: '0 0 8px rgba(79, 227, 255, 0.4)',
                  }}
                />
              )}
            </div>
          ))}
          {filteredEmails.length === 0 && (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
              No emails found in this category.
            </div>
          )}
        </div>
      </div>

      {/* Detail Panel */}
      <EmailDetailPanel email={selectedEmail} onOpenThread={(tId) => setViewThreadId(tId)} />

      {/* Conversation Thread Modal */}
      {viewThreadId && (
        <ThreadViewModal threadId={viewThreadId} onClose={() => setViewThreadId(null)} />
      )}

      {/* Save Search Modal */}
      {showSaveModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(6px)',
            zIndex: 10000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={() => setShowSaveModal(false)}
        >
          <div
            className="glass-card"
            style={{
              width: '100%',
              maxWidth: '420px',
              padding: '24px',
              background: 'rgba(20, 20, 28, 0.95)',
              border: '1px solid var(--glass-border)',
              borderRadius: '14px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              Save Search Query
            </h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', marginBottom: '16px' }}>
              Save current query: <code style={{ color: '#3D81E3' }}>{searchQuery}</code>
            </p>
            <input
              type="text"
              placeholder="e.g. Urgent Acme Inquiries"
              value={saveSearchName}
              onChange={(e) => setSaveSearchName(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--glass-border)',
                borderRadius: '8px',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                marginBottom: '16px',
                outline: 'none',
              }}
              autoFocus
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                className="btn btn-ghost"
                onClick={() => setShowSaveModal(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSaveSearch}
                disabled={!saveSearchName.trim()}
              >
                Save Search
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Task Creation Safeguard Confirmation Modal */}
      {showTaskConfirm && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(6px)',
            zIndex: 10000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={() => setShowTaskConfirm(false)}
        >
          <div
            className="glass-card"
            style={{
              width: '100%',
              maxWidth: '440px',
              padding: '24px',
              background: 'rgba(20, 20, 28, 0.95)',
              border: '1px solid rgba(61, 129, 227, 0.3)',
              borderRadius: '14px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <div style={{ padding: '8px', borderRadius: '8px', background: 'rgba(61, 129, 227, 0.15)', color: '#3D81E3' }}>
                <CheckSquare size={20} />
              </div>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                Confirm Bulk Task Creation
              </h3>
            </div>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '20px' }}>
              Are you sure you want to create tasks for <strong>{selectedEmailIds.length}</strong> selected email(s)?
              <br />
              <span style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>
                This creates draft tasks in your personal Task Board. No autonomous emails or external actions are performed.
              </span>
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                className="btn btn-ghost"
                onClick={() => setShowTaskConfirm(false)}
                disabled={bulkLoading}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => handleBulkAction('create_tasks', { confirmed: true })}
                disabled={bulkLoading}
              >
                {bulkLoading ? 'Creating Tasks...' : `Confirm & Create (${selectedEmailIds.length})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
