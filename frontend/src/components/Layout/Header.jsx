import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Search, Bell, Menu, RefreshCw, Sun, Moon, X, FileText } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { fetchNotifications, markNotificationRead, markAllNotificationsRead } from '../../services/api';

const pageTitles = {
  '/': 'Dashboard',
  '/emails': 'Inbox',
  '/tasks': 'Task Board',
  '/calendar': 'Calendar',
  '/settings': 'Settings',
  '/actions': 'Action Center',
  '/digest': 'Daily Digest',
};

export default function Header({ onMenuClick }) {
  const location = useLocation();
  const { demoMode, emails, tasks, sync, syncing, theme, toggleTheme } = useApp();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationsList, setNotificationsList] = useState([]);
  const [realUnreadCount, setRealUnreadCount] = useState(0);

  const getTitle = () => {
    if (location.pathname.startsWith('/emails/')) return 'Email Detail';
    return pageTitles[location.pathname] || 'MailMind AI';
  };

  // Dynamic counts for header pills
  const pendingReviewCount = emails.filter(e => e.needsHumanReview || !e.read).length;
  const pendingTasksCount = tasks.filter(t => t.status !== 'completed').length;

  return (
    <header className="header">
      <div className="header-left">
        <button className="mobile-menu-btn" onClick={onMenuClick}>
          <Menu size={20} />
        </button>
        <div>
          <h1 className="header-title">{getTitle()}</h1>
          <span className="header-breadcrumb">
            {new Date().toLocaleDateString('en-US', {
              weekday: 'long',
              month: 'long',
              day: 'numeric',
              year: 'numeric',
            })}
            {demoMode && (
              <span className="demo-mode-badge" style={{ marginLeft: '8px', padding: '2px 6px', fontSize: '0.6875rem', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.15)', color: 'var(--color-warning)', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                Demo Mode
              </span>
            )}
          </span>
        </div>
      </div>

      <div className="header-search">
        <Search className="header-search-icon" />
        <input type="text" placeholder="Search emails, tasks, events..." />
      </div>

      <div className="header-right">
        {syncing && (
          <div className="header-stat-pill animate-fadeIn" style={{ borderColor: 'rgba(79, 227, 255, 0.4)', background: 'rgba(79, 227, 255, 0.08)', color: 'var(--color-accent)' }}>
            <span className="dot success bg-glow-pulse" style={{ background: 'var(--color-accent)', boxShadow: '0 0 8px var(--color-accent)' }} />
            Summarizing...
          </div>
        )}
        {pendingReviewCount > 0 && (
          <div className="header-stat-pill">
            <span className="dot warning" />
            {pendingReviewCount} Pending Review
          </div>
        )}
        {pendingTasksCount > 0 && (
          <div className="header-stat-pill">
            <span className="dot danger" />
            {pendingTasksCount} Tasks Due
          </div>
        )}

        <button 
          type="button"
          className={`header-icon-btn ${syncing ? 'syncing-spin' : ''}`} 
          onClick={(e) => { e.preventDefault(); sync(); }} 
          disabled={syncing}
          title="Sync Emails"
        >
          <RefreshCw style={{ animation: syncing ? 'spin 1s linear infinite' : 'none' }} />
        </button>

        <button 
          className="header-icon-btn" 
          onClick={toggleTheme} 
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
        </button>

        <a 
          href="/api/docs/readme/download" 
          className="header-icon-btn" 
          download="README.md"
          title="Download System README.md"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none' }}
        >
          <FileText size={18} />
        </a>

        <div style={{ position: 'relative' }}>
          <button 
            className="header-icon-btn" 
            title="Notifications"
            onClick={async () => {
              const next = !notificationsOpen;
              setNotificationsOpen(next);
              if (next) {
                try {
                  const res = await fetchNotifications({ page_size: 15 });
                  setNotificationsList(res?.items || []);
                  setRealUnreadCount(res?.unread_count || 0);
                } catch (e) {
                  console.error('Failed to load notifications:', e);
                }
              }
            }}
          >
            <Bell />
            {(realUnreadCount > 0 || pendingReviewCount > 0) && (
              <span className="header-notification-badge">{realUnreadCount || pendingReviewCount}</span>
            )}
          </button>
          
          {notificationsOpen && (
            <div 
              className="glass-card animate-scaleIn" 
              style={{ 
                position: 'absolute', 
                top: '45px', 
                right: '0', 
                width: '320px', 
                zIndex: 1000,
                padding: '16px',
                boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)',
                border: '1px solid var(--glass-border)',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--glass-border)', paddingBottom: '8px' }}>
                <span style={{ fontSize: '0.8125rem', fontWeight: '700', color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Notifications {realUnreadCount > 0 && `(${realUnreadCount})`}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {realUnreadCount > 0 && (
                    <button
                      onClick={async () => {
                        await markAllNotificationsRead();
                        setRealUnreadCount(0);
                        setNotificationsList(prev => prev.map(n => ({ ...n, read: true })));
                      }}
                      style={{ background: 'none', border: 'none', color: 'var(--color-indigo)', fontSize: '0.6875rem', cursor: 'pointer', padding: 0 }}
                    >
                      Mark all read
                    </button>
                  )}
                  <button 
                    onClick={() => setNotificationsOpen(false)}
                    style={{ background: 'none', border: 'none', color: 'var(--text-tertiary)', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '280px', overflowY: 'auto' }}>
                {notificationsList.length === 0 ? (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', textAlign: 'center', padding: '16px 0' }}>
                    🎉 All caught up! No notifications.
                  </div>
                ) : (
                  notificationsList.map((notif) => (
                    <div
                      key={notif.id}
                      style={{
                        display: 'flex',
                        alignItems: 'start',
                        gap: '8px',
                        fontSize: '0.78rem',
                        color: 'var(--text-primary)',
                        padding: '8px',
                        background: notif.read ? 'rgba(255, 255, 255, 0.02)' : 'rgba(99, 102, 241, 0.08)',
                        border: `1px solid ${notif.read ? 'var(--glass-border)' : 'rgba(99, 102, 241, 0.2)'}`,
                        borderRadius: 'var(--radius-sm)',
                        cursor: notif.read ? 'default' : 'pointer'
                      }}
                      onClick={async () => {
                        if (!notif.read) {
                          await markNotificationRead(notif.id);
                          setNotificationsList(prev => prev.map(n => n.id === notif.id ? { ...n, read: true } : n));
                          setRealUnreadCount(prev => Math.max(0, prev - 1));
                        }
                      }}
                    >
                      <span className={`dot ${notif.severity === 'urgent' ? 'danger' : (notif.severity === 'warning' ? 'warning' : 'info')}`} style={{ marginTop: '5px' }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: notif.read ? 500 : 700, color: 'var(--text-primary)' }}>{notif.title}</div>
                        <div style={{ color: 'var(--text-secondary)', marginTop: '2px', fontSize: '0.75rem' }}>{notif.message}</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

