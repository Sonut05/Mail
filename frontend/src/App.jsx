import { useState, useEffect, useRef } from 'react';
import { Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import Sidebar from './components/Layout/Sidebar';
import Header from './components/Layout/Header';
import Dashboard from './pages/Dashboard';
import Inbox from './pages/Inbox';
import TaskBoard from './pages/TaskBoard';
import CalendarView from './pages/CalendarView';
import Contacts from './pages/Contacts';
import Settings from './pages/Settings';
import ActionCenter from './pages/ActionCenter';
import Digest from './pages/Digest';
import Login from './pages/Login';
import CommandPalette from './components/CommandPalette';
import ShortcutHelpModal from './components/ShortcutHelpModal';
import { useApp } from './context/AppContext';

// Smooth fade and vertical slide route transition
const PageTransition = ({ children }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="w-full h-full"
    >
      {children}
    </motion.div>
  );
};

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, user, loading } = useApp();
  const pendingGRef = useRef(false);
  const gTimeoutRef = useRef(null);

  // Global Keyboard Shortcuts (Ctrl/Cmd+K, ?, g i, g d, g t, g c, g a)
  useEffect(() => {
    const handleKeyDown = (e) => {
      const activeEl = document.activeElement;
      const isInputActive = activeEl && (
        activeEl.tagName === 'INPUT' ||
        activeEl.tagName === 'TEXTAREA' ||
        activeEl.tagName === 'SELECT' ||
        activeEl.isContentEditable
      );

      // Ctrl + K or Cmd + K always works even if inside input
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(prev => !prev);
        return;
      }

      // If typing in an input field, do not hijack other single-key shortcuts
      if (isInputActive) return;

      // ? for Shortcut Help
      if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setHelpOpen(prev => !prev);
        return;
      }

      // Two-key chord: 'g' then another key
      if (e.key.toLowerCase() === 'g' && !pendingGRef.current && !e.ctrlKey && !e.metaKey) {
        pendingGRef.current = true;
        clearTimeout(gTimeoutRef.current);
        gTimeoutRef.current = setTimeout(() => {
          pendingGRef.current = false;
        }, 1200);
        return;
      }

      if (pendingGRef.current) {
        pendingGRef.current = false;
        clearTimeout(gTimeoutRef.current);
        const k = e.key.toLowerCase();
        if (k === 'i') {
          navigate('/emails');
        } else if (k === 'd') {
          navigate('/');
        } else if (k === 'a') {
          navigate('/actions');
        } else if (k === 't') {
          navigate('/tasks');
        } else if (k === 'c') {
          navigate('/calendar');
        } else if (k === 'p') {
          navigate('/contacts');
        } else if (k === 's') {
          navigate('/settings');
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      clearTimeout(gTimeoutRef.current);
    };
  }, [navigate]);

  const isLight = theme === 'light';

  if (loading) {
    return (
      <div 
        className="app-layout" 
        style={{ 
          background: '#0c0c0c', 
          height: '100vh', 
          display: 'flex', 
          flexDirection: 'column',
          alignItems: 'center', 
          justifyContent: 'center', 
          color: '#fff',
          fontFamily: 'system-ui, sans-serif'
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <div style={{ 
            width: '40px', 
            height: '40px', 
            border: '3px solid rgba(255,255,255,0.1)', 
            borderTopColor: '#3D81E3', 
            borderRadius: '50%',
            animation: 'spin 1s linear infinite'
          }} />
          <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.6)', fontWeight: 500, letterSpacing: '0.05em' }}>
            LOADING MAILMIND AI
          </span>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-layout" style={{ background: 'var(--bg-primary)' }}>
        <div style={{ 
          position: 'fixed', 
          inset: 0, 
          zIndex: 0, 
          pointerEvents: 'none', 
          opacity: isLight ? 0.25 : 0.65,
          filter: isLight ? 'invert(1) hue-rotate(180deg) brightness(1.15)' : 'none',
          transition: 'all 0.4s ease'
        }}>
          <video
            autoPlay
            loop
            muted
            playsInline
            preload="auto"
            style={{ width: '100%', height: '100%', objectFit: 'cover', pointerEvents: 'none' }}
            src="/background.mp4"
          />
        </div>
        <Login />
      </div>
    );
  }

  return (
    <div className="app-layout" style={{ background: 'var(--bg-primary)' }}>
      {/* Optimized local video element to load instantly and prevent remote loop stutters */}
      <div style={{ 
        position: 'fixed', 
        inset: 0, 
        zIndex: 0, 
        pointerEvents: 'none', 
        opacity: isLight ? 0.25 : 0.65,
        filter: isLight ? 'invert(1) hue-rotate(180deg) brightness(1.15)' : 'none',
        transition: 'all 0.4s ease'
      }}>
        <video
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          style={{ width: '100%', height: '100%', objectFit: 'cover', pointerEvents: 'none' }}
          src="/background.mp4"
        />
      </div>

      {/* Optional fixed vertical guide lines (desktop only) */}
      <div className="desktop-only-guide" style={{ pointerEvents: 'none', position: 'fixed', top: 0, bottom: 0, left: '50%', transform: 'translateX(calc(-50% - 36rem))', width: '1px', backgroundColor: 'rgba(255, 255, 255, 0.08)', zIndex: 5 }} />
      <div className="desktop-only-guide" style={{ pointerEvents: 'none', position: 'fixed', top: 0, bottom: 0, left: '50%', transform: 'translateX(calc(-50% + 36rem))', width: '1px', backgroundColor: 'rgba(255, 255, 255, 0.08)', zIndex: 5 }} />

      {/* Global SVG Noise Filter */}
      <svg width="0" height="0" style={{ position: 'absolute', pointerEvents: 'none' }}>
        <filter id="c3-noise">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.35 0" />
          <feComposite in2="SourceGraphic" operator="in" result="noise" />
          <feBlend in="SourceGraphic" in2="noise" mode="multiply" />
        </filter>
      </svg>

      <Sidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="main-wrapper">
        <Header onMenuClick={() => setSidebarOpen(!sidebarOpen)} />

        <main className="main-content">
          <AnimatePresence mode="wait">
            <Routes location={location} key={'/' + (location.pathname.split('/')[1] || '')}>
              <Route path="/" element={<PageTransition><Dashboard /></PageTransition>} />
              <Route path="/dashboard" element={<Navigate to="/" replace />} />
              <Route path="/actions" element={<PageTransition><ActionCenter /></PageTransition>} />
              <Route path="/digest" element={<PageTransition><Digest /></PageTransition>} />
              <Route path="/emails" element={<PageTransition><Inbox /></PageTransition>} />
              <Route path="/emails/:id" element={<PageTransition><Inbox /></PageTransition>} />
              <Route path="/inbox" element={<Navigate to="/emails" replace />} />
              <Route path="/inbox/:id" element={<Navigate to="/emails" replace />} />
              <Route path="/tasks" element={<PageTransition><TaskBoard /></PageTransition>} />
              <Route path="/calendar" element={<PageTransition><CalendarView /></PageTransition>} />
              <Route path="/contacts" element={<PageTransition><Contacts /></PageTransition>} />
              <Route path="/settings" element={<PageTransition><Settings /></PageTransition>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AnimatePresence>
        </main>
      </div>

      {/* Phase 8 Global Modals */}
      <CommandPalette isOpen={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <ShortcutHelpModal isOpen={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
  );
}
