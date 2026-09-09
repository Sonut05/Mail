import { X, Keyboard } from 'lucide-react';

export default function ShortcutHelpModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  const shortcuts = [
    { key: 'Ctrl + K / ⌘ + K', desc: 'Open Command Palette' },
    { key: '?', desc: 'Show this Keyboard Shortcuts help' },
    { key: 'g i', desc: 'Go to Inbox' },
    { key: 'g d', desc: 'Go to Dashboard' },
    { key: 'g t', desc: 'Go to Tasks' },
    { key: 'g c', desc: 'Go to Calendar' },
    { key: 'g p', desc: 'Go to Contacts (People)' },
    { key: 'g s', desc: 'Go to Settings' },
    { key: 'Esc', desc: 'Close modals / active selection' },
  ];

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(8px)',
        zIndex: 10000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        animation: 'fadeIn 0.15s ease',
      }}
      onClick={onClose}
    >
      <div
        className="glass-card"
        style={{
          width: '100%',
          maxWidth: '480px',
          background: 'rgba(20, 20, 28, 0.95)',
          border: '1px solid var(--glass-border)',
          borderRadius: '14px',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)',
          padding: '20px',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--glass-border)', paddingBottom: '12px', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Keyboard size={18} style={{ color: 'var(--color-indigo)' }} />
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>Keyboard Shortcuts</h3>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-tertiary)', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {shortcuts.map((s) => (
            <div key={s.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', borderRadius: '6px', background: 'rgba(255, 255, 255, 0.02)' }}>
              <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{s.desc}</span>
              <kbd style={{ background: 'rgba(255, 255, 255, 0.1)', border: '1px solid rgba(255, 255, 255, 0.15)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {s.key}
              </kbd>
            </div>
          ))}
        </div>

        <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--glass-border)', textAlign: 'center', fontSize: '0.6875rem', color: 'var(--text-tertiary)' }}>
          Shortcuts are safely disabled while typing inside input fields or textareas.
        </div>
      </div>
    </div>
  );
}
