import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Mail,
  Circle,
  Zap,
  Sparkles,
  Archive,
  CheckSquare,
  Calendar,
  Users,
  Settings,
  ChevronUp,
  UserPlus,
  LogOut,
  Check,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export default function Sidebar({ isOpen, onClose }) {
  const location = useLocation();
  const { user, demoMode, emails, tasks, sync, syncing, savedAccounts, switchAccount, addAccount, logout } = useApp();
  const [menuOpen, setMenuOpen] = useState(false);

  // Dynamic counts for sidebar badges
  const unreadEmailsCount = (emails || []).filter(e => e.needsHumanReview || !e.read).length;
  const pendingTasksCount = (tasks || []).filter(t => t.status !== 'completed').length;
  const priorityEmailsCount = (emails || []).filter(e => e.priority === 'high').length;

  const navItems = [
    {
      section: 'Overview',
      links: [
        { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
      ],
    },
    {
      section: 'Inbox Folders',
      links: [
        { to: '/emails?folder=all', icon: Mail, label: 'All Mail' },
        { 
          to: '/emails?folder=unread', 
          icon: Circle, 
          label: 'Unread', 
          badge: unreadEmailsCount > 0 ? String(unreadEmailsCount) : null, 
          badgeType: 'primary' 
        },
        { 
          to: '/emails?folder=priority', 
          icon: Zap, 
          label: 'Priority', 
          badge: priorityEmailsCount > 0 ? String(priorityEmailsCount) : null, 
          badgeType: 'warning' 
        },
        { to: '/emails?folder=summarized', icon: Sparkles, label: 'Summarized' },
        { to: '/emails?folder=archived', icon: Archive, label: 'Archived' },
      ],
    },
    {
      section: 'Workspace',
      links: [
        { to: '/actions', icon: Zap, label: 'Action Center' },
        { to: '/digest', icon: Sparkles, label: 'Daily Digest' },
        { 
          to: '/tasks', 
          icon: CheckSquare, 
          label: 'Task Board', 
          badge: pendingTasksCount > 0 ? String(pendingTasksCount) : null, 
          badgeType: 'danger' 
        },
        { to: '/calendar', icon: Calendar, label: 'Calendar' },
        { to: '/contacts', icon: Users, label: 'Contacts' },
      ],
    },
    {
      section: 'System',
      links: [
        { to: '/settings', icon: Settings, label: 'Settings' },
      ],
    },
  ];

  const getInitials = (email) => {
    if (!email) return 'DM';
    return email.slice(0, 2).toUpperCase();
  };

  return (
    <>
      <div
        className={`sidebar-overlay ${isOpen ? 'active' : ''}`}
        onClick={onClose}
      />
      <aside className={`sidebar ${isOpen ? 'open' : ''}`}>
        {/* Logo */}
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="sidebar-logo-icon">
              <Sparkles />
            </div>
            <div>
              <div className="sidebar-logo-text">MailMind AI</div>
              <div className="sidebar-logo-badge">Beta</div>
            </div>
          </div>
        </div>

        {/* New Summary Action */}
        <div style={{ padding: '16px 16px 0 16px' }}>
          <button 
            type="button"
            className="btn btn-primary" 
            style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '10px 14px', borderRadius: 'var(--radius-md)', fontWeight: '600' }}
            onClick={(e) => { e.preventDefault(); sync(); }}
            disabled={syncing}
          >
            <Sparkles size={16} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Summarizing...' : 'New Summary'}
          </button>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav">
          {navItems.map((section) => (
            <div key={section.section} className="sidebar-nav-section">
              <div className="sidebar-nav-label">{section.section}</div>
              {section.links.map((link) => {
                const Icon = link.icon;
                const queryParams = new URLSearchParams(location.search);
                const currentFolder = queryParams.get('folder') || (location.pathname.startsWith('/emails') ? 'all' : null);
                
                const isEmailsSection = location.pathname.startsWith('/emails');
                const linkParams = new URLSearchParams(link.to.includes('?') ? link.to.split('?')[1] : '');
                const linkFolder = linkParams.get('folder');

                const isActive =
                  link.to === '/'
                    ? location.pathname === '/'
                    : (isEmailsSection && link.to.startsWith('/emails') && linkFolder === currentFolder) ||
                      (location.pathname + location.search) === link.to;

                return (
                  <Link
                    key={link.to}
                    to={link.to}
                    className={`sidebar-nav-link ${isActive ? 'active' : ''}`}
                    onClick={onClose}
                  >
                    <Icon />
                    <span>{link.label}</span>
                    {link.badge && (
                      <span className={`sidebar-nav-badge ${link.badgeType}`}>
                        {link.badge}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* User section with Account Switcher Popover */}
        <div className="sidebar-footer" style={{ position: 'relative' }}>
          {menuOpen && (
            <div 
              style={{ 
                position: 'absolute', 
                bottom: '100%', 
                left: '12px', 
                right: '12px', 
                marginBottom: '8px', 
                background: 'rgba(18, 18, 24, 0.95)', 
                backdropFilter: 'blur(20px)', 
                border: '1px solid var(--glass-border)', 
                borderRadius: '12px', 
                padding: '12px', 
                boxShadow: '0 12px 32px rgba(0,0,0,0.5)',
                zIndex: 100 
              }}
            >
              <div style={{ fontSize: '0.6875rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', marginBottom: '8px', paddingLeft: '4px' }}>
                Switch Account
              </div>

              {/* Saved accounts list */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '10px', maxHeight: '160px', overflowY: 'auto' }}>
                {(Array.isArray(savedAccounts) ? savedAccounts : []).map((acc) => {
                  const isCurrent = user?.email === acc.email;
                  return (
                    <button
                      key={acc.email}
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        switchAccount(acc);
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '8px 10px',
                        borderRadius: '8px',
                        background: isCurrent ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                        border: isCurrent ? '1px solid rgba(99, 102, 241, 0.3)' : '1px solid transparent',
                        color: 'var(--text-primary)',
                        cursor: 'pointer',
                        textAlign: 'left',
                        width: '100%',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', overflow: 'hidden', background: 'rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: '700' }}>
                          {acc.picture ? <img src={acc.picture} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : acc.email.slice(0, 2).toUpperCase()}
                        </div>
                        <span style={{ fontSize: '0.75rem', fontWeight: isCurrent ? '600' : '400', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '130px' }}>
                          {acc.email}
                        </span>
                      </div>
                      {isCurrent && <Check size={14} style={{ color: 'var(--color-indigo)', flexShrink: 0 }} />}
                    </button>
                  );
                })}
              </div>

              <div style={{ borderTop: '1px solid var(--glass-border)', paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    addAccount();
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 10px',
                    borderRadius: '8px',
                    background: 'none',
                    border: 'none',
                    color: 'var(--color-indigo)',
                    fontSize: '0.75rem',
                    fontWeight: '600',
                    cursor: 'pointer',
                    width: '100%',
                    textAlign: 'left'
                  }}
                >
                  <UserPlus size={14} />
                  <span>+ Add Another Account</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 10px',
                    borderRadius: '8px',
                    background: 'none',
                    border: 'none',
                    color: 'var(--color-danger, #EF4444)',
                    fontSize: '0.75rem',
                    fontWeight: '500',
                    cursor: 'pointer',
                    width: '100%',
                    textAlign: 'left'
                  }}
                >
                  <LogOut size={14} />
                  <span>Sign Out</span>
                </button>
              </div>
            </div>
          )}

          <div 
            className="sidebar-user" 
            onClick={() => setMenuOpen(!menuOpen)} 
            style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', userSelect: 'none' }}
          >
            <div className="sidebar-avatar" style={{ position: 'relative', width: '36px', height: '36px', borderRadius: '50%', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.1)' }}>
              {user?.picture ? (
                <img src={user.picture} alt="Avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} referrerPolicy="no-referrer" />
              ) : (
                demoMode ? 'DM' : getInitials(user?.email)
              )}
              <span className={`sidebar-avatar-pulse ${demoMode ? 'demo' : 'live'}`} />
            </div>
            <div className="sidebar-user-info" style={{ overflow: 'hidden', flexGrow: 1 }}>
              <div className="sidebar-user-name" style={{ fontSize: '0.8125rem', fontWeight: '600', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '120px' }} title={user?.name || user?.email}>
                {user?.name || (demoMode ? 'Demo Workspace' : user?.email?.split('@')[0])}
              </div>
              <div className="sidebar-user-email" style={{ fontSize: '0.6875rem', color: 'var(--text-tertiary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '120px' }} title={user?.email}>
                {user?.email || 'Guest User'}
              </div>
            </div>
            <ChevronUp size={14} style={{ color: 'var(--text-tertiary)', transform: menuOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }} />
          </div>
        </div>
      </aside>
    </>
  );
}

