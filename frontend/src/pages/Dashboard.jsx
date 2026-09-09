import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Mail,
  Send,
  AlertCircle,
  CheckSquare,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Clock,
  ArrowRight,
  CalendarClock,
  Zap,
  CheckCircle2,
  CalendarDays,
  AlertTriangle,
  Sparkles,
  Activity,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import ThreeCore from '../components/Layout/ThreeCore';
import { fetchProductivityAnalytics } from '../services/api';

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
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState(false);
  const [analyticsPeriod, setAnalyticsPeriod] = useState('7d');
  const [analyticsData, setAnalyticsData] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const { stats, emails, tasks, calendarEvents, loading, syncing } = useApp();

  const recentEmails = emails.slice(0, 5);
  const upcomingEvents = calendarEvents.slice(0, 4);

  useEffect(() => {
    const timer = setTimeout(() => setLoaded(true), 100);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    let active = true;
    setAnalyticsLoading(true);
    fetchProductivityAnalytics(analyticsPeriod)
      .then((data) => {
        if (active) setAnalyticsData(data);
      })
      .catch((err) => console.error('Failed to fetch productivity analytics:', err))
      .finally(() => {
        if (active) setAnalyticsLoading(false);
      });
    return () => { active = false; };
  }, [analyticsPeriod]);

  // Productivity metrics
  const pendingTasks = tasks.filter((t) => t.status === 'pending');
  const inProgressTasks = tasks.filter((t) => t.status === 'in_progress');
  const completedTasks = tasks.filter((t) => t.status === 'completed');
  const overdueTasks = tasks.filter(
    (t) => t.is_overdue || (t.status !== 'completed' && t.due_date && new Date(t.due_date) < new Date())
  );
  const dueTodayTasks = tasks.filter((t) => {
    if (!t.due_date || t.status === 'completed') return false;
    const d = new Date(t.due_date);
    const now = new Date();
    return d.toDateString() === now.toDateString();
  });

  const upcomingDeadlines = tasks
    .filter((t) => t.due_date && t.status !== 'completed')
    .sort((a, b) => new Date(a.due_date) - new Date(b.due_date))
    .slice(0, 5);

  const analyzedCount = emails.filter((e) => e.aiStatus === 'completed').length;
  const pendingAnalysisCount = emails.filter((e) => e.aiStatus === 'pending').length;
  const actionRequiredCount = emails.filter((e) => e.aiActionRequired).length;
  const waitingForCount = emails.filter((e) => Boolean(e.aiWaitingFor)).length;
  const priorityDist = stats?.priority_distribution || {
    urgent: emails.filter((e) => (e.aiImportanceScore !== null && e.aiImportanceScore > 80) || (e.priority || '').toLowerCase() === 'urgent').length,
    high: emails.filter((e) => (e.aiImportanceScore !== null && e.aiImportanceScore > 60 && e.aiImportanceScore <= 80) || (e.priority || '').toLowerCase() === 'high').length,
    medium: emails.filter((e) => (e.aiImportanceScore !== null && e.aiImportanceScore > 30 && e.aiImportanceScore <= 60) || (e.priority || '').toLowerCase() === 'medium').length,
    low: emails.filter((e) => (e.aiImportanceScore !== null && e.aiImportanceScore <= 30) || (e.priority || '').toLowerCase() === 'low').length,
  };

  const smartReminders = stats?.smart_reminders || [];

  const statCards = [
    {
      label: 'Emails Summarized',
      value: emails.length,
      trend: stats?.trends?.totalEmails || '+12%',
      trendDir: 'up',
      icon: Mail,
      color: 'indigo',
    },
    {
      label: 'Tasks & Deadlines',
      value: tasks.length,
      trend: `${overdueTasks.length} overdue`,
      trendDir: overdueTasks.length > 0 ? 'down' : 'up',
      icon: CheckSquare,
      color: overdueTasks.length > 0 ? 'danger' : 'success',
    },
    {
      label: 'Priority Pending',
      value: emails.filter((e) => e.priority === 'high' && (e.needsHumanReview || !e.read)).length,
      trend: `${actionRequiredCount} need action`,
      trendDir: 'down',
      icon: AlertCircle,
      color: 'warning',
    },
    {
      label: 'Waiting For',
      value: waitingForCount,
      trend: `${waitingForCount} awaiting response`,
      trendDir: waitingForCount > 0 ? 'down' : 'up',
      icon: Clock,
      color: 'purple',
    },
    {
      label: 'AI Core Status',
      value: syncing ? 'Active' : 'Standby',
      trend: `${analyzedCount} analyzed`,
      trendDir: syncing ? 'up' : 'down',
      icon: Zap,
      color: 'accent',
    },
  ];

  return (
    <div className={`dashboard-page page-enter ${loaded ? '' : ''}`}>
      {/* Stats Row */}
      <div className="stats-grid">
        {statCards.map((card, i) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className={`glass-card stat-card ${card.color} animate-fadeIn stagger-${i + 1}`}
            >
              <div className="stat-card-header">
                <div className={`stat-card-icon ${card.color}`}>
                  <Icon />
                </div>
                <div className={`stat-card-trend ${card.trendDir}`}>
                  {card.trendDir === 'up' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  {card.trend}
                </div>
              </div>
              <div className="stat-card-value">{card.value.toLocaleString()}</div>
              <div className="stat-card-label">{card.label}</div>
            </div>
          );
        })}
      </div>

      {/* Dashboard 2.0 — Inbox Health Strip */}
      <div className="glass-card animate-fadeIn stagger-1" style={{ padding: '16px 20px', marginBottom: '20px', background: 'rgba(255, 255, 255, 0.02)', border: '1px solid var(--glass-border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Inbox Health & Triage
          </span>
          <button
            onClick={() => navigate('/emails')}
            style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'var(--color-accent)', fontSize: '0.75rem', fontWeight: 500 }}
          >
            Open Smart Inbox &rarr;
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px' }}>
          <div style={{ padding: '8px 12px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: '8px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)' }}>Unread Items</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
              {stats?.inbox_health?.total_unread ?? emails.filter(e => !e.read).length}
            </div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.04)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.15)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--color-danger)' }}>Needs Action</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-danger)', marginTop: '2px' }}>
              {stats?.inbox_health?.needs_action ?? emails.filter(e => e.aiActionRequired).length}
            </div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(245, 158, 11, 0.04)', borderRadius: '8px', border: '1px solid rgba(245, 158, 11, 0.15)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--color-warning)' }}>Waiting on Reply</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-warning)', marginTop: '2px' }}>
              {stats?.inbox_health?.waiting_for_reply ?? 0}
            </div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(99, 102, 241, 0.04)', borderRadius: '8px', border: '1px solid rgba(99, 102, 241, 0.15)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--color-indigo)' }}>High Priority</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-indigo)', marginTop: '2px' }}>
              {stats?.inbox_health?.high_priority ?? priorityDist.urgent + priorityDist.high}
            </div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: '8px', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)' }}>Stale Threads</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-secondary)', marginTop: '2px' }}>
              {stats?.inbox_health?.stale_threads ?? 0}
            </div>
          </div>
          <div style={{ padding: '8px 12px', background: 'rgba(16, 185, 129, 0.04)', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.15)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--color-success)' }}>Upcoming Deadlines</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--color-success)', marginTop: '2px' }}>
              {stats?.inbox_health?.upcoming_deadlines ?? upcomingDeadlines.length}
            </div>
          </div>
        </div>
      </div>

      {/* Task & AI Productivity Strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        {/* Task Overview */}
        <div className="glass-card animate-fadeIn stagger-2" style={{ padding: '20px' }}>
          <div className="section-header" style={{ marginBottom: '14px' }}>
            <h3 className="section-title" style={{ fontSize: '0.9375rem' }}>
              <CheckSquare size={16} /> Task Productivity
            </h3>
            <button
              className="section-link"
              onClick={() => navigate('/tasks')}
              style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit' }}
            >
              Task Board <ArrowRight size={14} style={{ verticalAlign: 'middle' }} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', textAlign: 'center' }}>
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '10px 6px', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--text-primary)' }}>{pendingTasks.length}</div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>Pending</div>
            </div>
            <div style={{ background: 'rgba(99, 102, 241, 0.06)', padding: '10px 6px', borderRadius: '8px', border: '1px solid rgba(99, 102, 241, 0.2)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--color-indigo)' }}>{inProgressTasks.length}</div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>In Progress</div>
            </div>
            <div style={{ background: 'rgba(16, 185, 129, 0.06)', padding: '10px 6px', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.2)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--color-success)' }}>{completedTasks.length}</div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>Completed</div>
            </div>
            <div style={{ background: overdueTasks.length > 0 ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255, 255, 255, 0.02)', padding: '10px 6px', borderRadius: '8px', border: overdueTasks.length > 0 ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid var(--glass-border)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: overdueTasks.length > 0 ? 'var(--color-danger)' : 'var(--text-primary)' }}>{overdueTasks.length}</div>
              <div style={{ fontSize: '0.6875rem', color: overdueTasks.length > 0 ? 'var(--color-danger)' : 'var(--text-tertiary)', marginTop: '2px' }}>Overdue</div>
            </div>
          </div>
        </div>

        {/* AI Productivity Status */}
        <div className="glass-card animate-fadeIn stagger-2" style={{ padding: '20px' }}>
          <div className="section-header" style={{ marginBottom: '14px' }}>
            <h3 className="section-title" style={{ fontSize: '0.9375rem' }}>
              <Sparkles size={16} /> AI Email Intelligence
            </h3>
            <button
              className="section-link"
              onClick={() => navigate('/emails')}
              style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit' }}
            >
              Open Inbox <ArrowRight size={14} style={{ verticalAlign: 'middle' }} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', textAlign: 'center' }}>
            <div style={{ background: 'rgba(79, 227, 255, 0.06)', padding: '10px 6px', borderRadius: '8px', border: '1px solid rgba(79, 227, 255, 0.2)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--color-accent)' }}>{analyzedCount}</div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>Analyzed</div>
            </div>
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '10px 6px', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: 'var(--text-primary)' }}>{pendingAnalysisCount}</div>
              <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginTop: '2px' }}>Pending</div>
            </div>
            <div style={{ background: actionRequiredCount > 0 ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255, 255, 255, 0.02)', padding: '10px 6px', borderRadius: '8px', border: actionRequiredCount > 0 ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid var(--glass-border)' }}>
              <div style={{ fontSize: '1.25rem', fontWeight: '700', color: actionRequiredCount > 0 ? 'var(--color-danger)' : 'var(--text-primary)' }}>{actionRequiredCount}</div>
              <div style={{ fontSize: '0.6875rem', color: actionRequiredCount > 0 ? 'var(--color-danger)' : 'var(--text-tertiary)', marginTop: '2px' }}>Action Needed</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <div className="dashboard-grid">
        {/* Left Column */}
        <div>
          {/* Upcoming Deadlines Widget */}
          <div className="glass-card animate-fadeIn stagger-2" style={{ padding: '20px', marginBottom: '16px' }}>
            <div className="section-header" style={{ marginBottom: '12px' }}>
              <h3 className="section-title">
                <Clock size={16} /> Upcoming Deadlines
              </h3>
              <button
                className="section-link"
                onClick={() => navigate('/tasks')}
                style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit' }}
              >
                View All
              </button>
            </div>

            {upcomingDeadlines.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {upcomingDeadlines.map((t) => {
                  const d = new Date(t.due_date);
                  const isToday = d.toDateString() === new Date().toDateString();
                  const isPast = d < new Date();
                  return (
                    <div
                      key={t.id}
                      onClick={() => navigate('/tasks')}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '8px 12px',
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid var(--glass-border)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                    >
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: '10px' }}>
                        <span style={{ fontSize: '0.8125rem', fontWeight: '600', color: 'var(--text-primary)' }}>{t.title}</span>
                      </div>
                      <span
                        className={`badge ${isPast ? 'danger' : isToday ? 'warning' : 'neutral'}`}
                        style={{ fontSize: '0.6875rem', padding: '2px 6px', flexShrink: 0 }}
                      >
                        {isPast ? 'Overdue' : isToday ? 'Today' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
                No upcoming deadlines. You're all caught up!
              </div>
            )}
          </div>

          {/* Productivity Trends (Phase 8) */}
          <div className="glass-card animate-fadeIn stagger-2" style={{ marginBottom: '16px' }}>
            <div className="section-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h3 className="section-title">
                <Activity size={18} /> Productivity Trends
              </h3>
              <div style={{ display: 'flex', gap: '4px', background: 'rgba(255, 255, 255, 0.05)', borderRadius: '8px', padding: '2px' }}>
                {['7d', '30d', '90d'].map((p) => (
                  <button
                    key={p}
                    onClick={() => setAnalyticsPeriod(p)}
                    style={{
                      padding: '4px 10px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      borderRadius: '6px',
                      border: 'none',
                      cursor: 'pointer',
                      background: analyticsPeriod === p ? 'var(--accent-primary, #3D81E3)' : 'transparent',
                      color: analyticsPeriod === p ? '#fff' : 'var(--text-tertiary)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {p.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {analyticsData && (
              <div style={{ marginTop: '12px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '14px' }}>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginBottom: '4px' }}>Received</div>
                    <div style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--text-primary)' }}>{analyticsData.summary?.emails_received || 0}</div>
                  </div>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginBottom: '4px' }}>Sent</div>
                    <div style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--text-primary)' }}>{analyticsData.summary?.emails_sent || 0}</div>
                  </div>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginBottom: '4px' }}>Completed</div>
                    <div style={{ fontSize: '1.125rem', fontWeight: 700, color: '#10B981' }}>{analyticsData.summary?.tasks_completed || 0}</div>
                  </div>
                  <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '10px', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', marginBottom: '4px' }}>Completion Rate</div>
                    <div style={{ fontSize: '1.125rem', fontWeight: 700, color: '#3D81E3' }}>{analyticsData.summary?.completion_rate_pct || 0}%</div>
                  </div>
                </div>

                {/* Mini trend visualization */}
                {analyticsData.trends && analyticsData.trends.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: '3px', height: '60px', padding: '4px 0', borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    {analyticsData.trends.slice(-14).map((tr, idx) => {
                      const totalVol = (tr.emails_received || 0) + (tr.emails_sent || 0);
                      const maxVol = Math.max(...analyticsData.trends.slice(-14).map(t => (t.emails_received || 0) + (t.emails_sent || 0)), 5);
                      const barH = Math.max(8, Math.round((totalVol / maxVol) * 52));
                      return (
                        <div
                          key={idx}
                          title={`${tr.date}: ${totalVol} emails, ${tr.tasks_completed || 0} tasks done`}
                          style={{
                            flex: 1,
                            height: `${barH}px`,
                            background: tr.tasks_completed > 0 ? 'linear-gradient(180deg, #10B981, #3D81E3)' : 'rgba(255, 255, 255, 0.15)',
                            borderRadius: '2px',
                            transition: 'height 0.3s ease',
                          }}
                        />
                      );
                    })}
                  </div>
                )}

                <div style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
                  <button
                    onClick={() => navigate('/actions')}
                    style={{
                      flex: 1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      padding: '8px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      borderRadius: '8px',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      background: 'rgba(245, 158, 11, 0.08)',
                      color: '#F59E0B',
                      cursor: 'pointer',
                    }}
                  >
                    <Zap size={14} /> Open Action Center
                  </button>
                  <button
                    onClick={() => navigate('/digest')}
                    style={{
                      flex: 1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      padding: '8px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      borderRadius: '8px',
                      border: '1px solid rgba(139, 92, 246, 0.3)',
                      background: 'rgba(139, 92, 246, 0.08)',
                      color: '#A78BFA',
                      cursor: 'pointer',
                    }}
                  >
                    <Sparkles size={14} /> View Daily Digest
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Category Distribution */}
          <div className="glass-card category-chart animate-fadeIn stagger-2">
            <div className="section-header">
              <h3 className="section-title">
                <BarChart3 /> Category Distribution
              </h3>
              <span className="section-link">All time</span>
            </div>
            {stats?.categoryDistribution?.map((cat) => (
              <div key={cat.name} className="category-bar-item">
                <div className="category-bar-label">
                  <span className="category-bar-name">{cat.name}</span>
                  <span className="category-bar-value">{cat.count}</span>
                </div>
                <div className="category-bar-track">
                  <div
                    className={`category-bar-fill ${cat.color}`}
                    style={{ width: loaded ? `${cat.percentage}%` : '0%' }}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Recent Emails */}
          <div className="glass-card recent-emails animate-fadeIn stagger-3" style={{ marginTop: '16px' }}>
            <div className="section-header">
              <h3 className="section-title">
                <Mail /> Recent Emails
              </h3>
              <button
                className="section-link"
                onClick={() => navigate('/emails')}
                style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit' }}
              >
                View All <ArrowRight size={14} style={{ verticalAlign: 'middle' }} />
              </button>
            </div>
            {recentEmails.length > 0 ? (
              recentEmails.map((email) => (
                <div
                  key={email.id}
                  className="recent-email-item"
                  onClick={() => navigate(`/emails/${email.id}`)}
                  style={{ cursor: 'pointer' }}
                >
                  <div
                    className="recent-email-avatar"
                    style={{ background: getAvatarColor(email.sender) }}
                  >
                    {getInitials(email.sender)}
                  </div>
                  <div className="recent-email-content">
                    <div className="recent-email-subject">{email.subject}</div>
                    <div className="recent-email-sender">{email.sender}</div>
                  </div>
                  <div className="recent-email-meta">
                    <span className="recent-email-time">{email.timeAgo}</span>
                    <span className={`badge ${
                      email.category === 'Business' || email.category === 'Sales' || email.category === 'Client' || email.category === 'Recruitment' || email.category === 'HR' || email.category === 'Internship' ? 'indigo' :
                      email.category === 'Finance' || email.category === 'Billing' || email.category === 'Invoice' || email.category === 'Subscription' ? 'success' :
                      email.category === 'Urgent' || email.category === 'Refund' || email.category === 'Complaint' || email.category === 'Security Alert' || email.category === 'Legal' ? 'danger' :
                      email.category === 'Social' || email.category === 'Meeting' || email.category === 'Interview' || email.category === 'Event' || email.category === 'Travel' || email.category === 'Promotion' ? 'purple' :
                      email.category === 'Personal' || email.category === 'Feedback' || email.category === 'Appreciation' || email.category === 'University' ? 'warning' :
                      email.category === 'Technical' || email.category === 'Support' || email.category === 'Project' || email.category === 'Assignment' ? 'accent' : 'neutral'
                    }`}>
                      {email.category}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
                No emails found in this mailbox yet. Click Sync or connect your account in Settings.
              </div>
            )}
          </div>
        </div>

        {/* Right Column */}
        <div>
          {/* AI Core Panel */}
          <div className="glass-card animate-fadeIn stagger-2" style={{ padding: '24px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '320px', position: 'relative', overflow: 'hidden', marginBottom: '16px' }}>
            <div className="section-header" style={{ width: '100%', position: 'absolute', top: '20px', left: '20px' }}>
              <h3 className="section-title">
                <Zap /> AI Core Activity
              </h3>
            </div>
            <div style={{ width: '220px', height: '220px', marginTop: '20px' }}>
              <ThreeCore syncing={syncing} />
            </div>
            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '8px', zIndex: 10, textAlign: 'center' }}>
              {syncing ? 'Analyzing and Summarizing Inbound Mail...' : 'System Idle · Monitoring Inbox'}
            </div>
          </div>

          {/* Priority Distribution */}
          <div className="glass-card priority-pills animate-fadeIn stagger-2">
            <div className="section-header" style={{ padding: '0 0 4px 0' }}>
              <h3 className="section-title">
                <Zap /> Priority Distribution
              </h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
              {[
                { level: 'urgent', label: 'Urgent (81–100)', count: priorityDist.urgent, color: 'danger' },
                { level: 'high', label: 'High (61–80)', count: priorityDist.high, color: 'warning' },
                { level: 'medium', label: 'Medium (31–60)', count: priorityDist.medium, color: 'indigo' },
                { level: 'low', label: 'Low (0–30)', count: priorityDist.low, color: 'neutral' },
              ].map((p) => (
                <div key={p.level} className="priority-pill">
                  <span className={`priority-dot ${p.level}`} />
                  <span className="priority-label">{p.label}</span>
                  <span className={`badge ${p.color}`} style={{ fontSize: '0.75rem', fontWeight: '600' }}>
                    {p.count}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Smart Reminders (Derived on-the-fly) */}
          <div className="glass-card reminders-section animate-fadeIn stagger-2" style={{ marginTop: '16px' }}>
            <div className="section-header">
              <h3 className="section-title">
                <Sparkles /> Smart Reminders
              </h3>
              <span className="section-link">AI Derived</span>
            </div>
            {smartReminders.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {smartReminders.map((rem, idx) => (
                  <div
                    key={idx}
                    className="reminder-item"
                    onClick={() => {
                      if (rem.email_id) navigate(`/emails/${rem.email_id}`);
                      else if (rem.task_id) navigate('/tasks');
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className={`reminder-icon ${rem.type === 'overdue_task' ? 'danger' : 'warning'}`}>
                      {rem.type === 'overdue_task' ? <AlertTriangle /> : <Clock />}
                    </div>
                    <div className="reminder-content" style={{ flex: 1, minWidth: 0 }}>
                      <div className="reminder-title" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {rem.title}
                      </div>
                      <div className="reminder-date">
                        {rem.deadline ? `Due: ${new Date(rem.deadline).toLocaleDateString()}` : rem.sender ? `From: ${rem.sender}` : 'Action Required'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '16px', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
                No active smart reminders. All caught up!
              </div>
            )}
          </div>

          {/* Upcoming Events */}
          <div className="glass-card reminders-section animate-fadeIn stagger-3" style={{ marginTop: '16px' }}>
            <div className="section-header">
              <h3 className="section-title">
                <CalendarClock /> Upcoming Events
              </h3>
              <button
                className="section-link"
                onClick={() => navigate('/calendar')}
                style={{ cursor: 'pointer', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit' }}
              >
                View All
              </button>
            </div>
            {upcomingEvents.length > 0 ? (
              upcomingEvents.map((event) => (
                <div
                  key={event.id}
                  className="reminder-item"
                  onClick={() => navigate('/calendar')}
                  style={{ cursor: 'pointer' }}
                >
                  <div className={`reminder-icon ${
                    event.priority === 'high' ? 'danger' :
                    event.priority === 'medium' ? 'warning' : 'accent'
                  }`}>
                    <Clock />
                  </div>
                  <div className="reminder-content">
                    <div className="reminder-title">{event.title}</div>
                    <div className="reminder-date">
                      {event.date || 'Scheduled'} · {event.time}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: '16px', color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>
                No upcoming calendar events.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
