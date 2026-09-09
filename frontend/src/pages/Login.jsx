import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Sparkles, Mail, ShieldAlert, Lock, User as UserIcon, AlertCircle, ArrowRight } from 'lucide-react';
import { useApp } from '../context/AppContext';

export default function Login() {
  const { login, loginWithMock, enterDemoMode, loginWithEmail, registerWithEmail, theme } = useApp();
  const [authMode, setAuthMode] = useState('oauth'); // 'oauth' | 'email'
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isLight = theme === 'light';

  const cardStyle = {
    background: isLight ? 'rgba(255, 255, 255, 0.7)' : 'rgba(12, 12, 16, 0.7)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid var(--glass-border)',
    borderRadius: '20px',
    padding: '36px 32px',
    width: '100%',
    maxWidth: '420px',
    boxShadow: isLight ? '0 20px 40px rgba(0,0,0,0.06)' : '0 24px 48px rgba(0,0,0,0.5)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '20px',
    transition: 'all 0.3s ease',
  };

  const containerStyle = {
    display: 'flex',
    minHeight: '90vh',
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '20px',
    position: 'relative',
    zIndex: 10,
  };

  const logoContainerStyle = {
    width: '52px',
    height: '52px',
    borderRadius: '14px',
    background: 'linear-gradient(135deg, var(--color-indigo) 0%, var(--color-purple) 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 8px 20px rgba(99, 102, 241, 0.3)',
    marginBottom: '8px',
  };

  const textPrimaryColor = 'var(--text-primary)';
  const textSecondaryColor = 'var(--text-secondary)';

  const handleEmailSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('Please provide both email and password.');
      return;
    }

    if (isRegister && !name.trim()) {
      setError('Please provide your name.');
      return;
    }

    setSubmitting(true);
    try {
      if (isRegister) {
        const res = await registerWithEmail(email, password, name, '');
        if (!res.success) {
          setError(res.error || 'Registration failed.');
        }
      } else {
        const res = await loginWithEmail(email, password);
        if (!res.success) {
          setError(res.error || 'Invalid email or password.');
        }
      }
    } catch (err) {
      setError(err.message || 'An error occurred during authentication.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={containerStyle}>
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        style={cardStyle}
      >
        {/* Header Section */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
          <div style={logoContainerStyle}>
            <Sparkles className="text-white" size={26} />
          </div>
          <h2 style={{ fontSize: '1.625rem', fontWeight: '800', color: textPrimaryColor, letterSpacing: '-0.02em', margin: '0 0 4px 0' }}>
            MailMind AI
          </h2>
          <p style={{ fontSize: '0.875rem', color: textSecondaryColor, margin: 0, lineHeight: 1.4 }}>
            Intelligent Email Intelligence & Productivity Platform
          </p>
        </div>

        {/* Tab Selector */}
        <div style={{
          display: 'flex',
          width: '100%',
          background: 'rgba(255, 255, 255, 0.04)',
          border: '1px solid var(--glass-border)',
          borderRadius: '10px',
          padding: '3px',
          gap: '4px'
        }}>
          <button
            type="button"
            onClick={() => { setAuthMode('oauth'); setError(''); }}
            style={{
              flex: 1,
              padding: '8px',
              fontSize: '0.8125rem',
              fontWeight: 600,
              borderRadius: '7px',
              border: 'none',
              cursor: 'pointer',
              background: authMode === 'oauth' ? 'var(--color-indigo)' : 'transparent',
              color: authMode === 'oauth' ? '#fff' : textSecondaryColor,
              transition: 'all 0.2s ease'
            }}
          >
            Google & Demo
          </button>
          <button
            type="button"
            onClick={() => { setAuthMode('email'); setError(''); }}
            style={{
              flex: 1,
              padding: '8px',
              fontSize: '0.8125rem',
              fontWeight: 600,
              borderRadius: '7px',
              border: 'none',
              cursor: 'pointer',
              background: authMode === 'email' ? 'var(--color-indigo)' : 'transparent',
              color: authMode === 'email' ? '#fff' : textSecondaryColor,
              transition: 'all 0.2s ease'
            }}
          >
            Email Login
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div style={{
            width: '100%',
            background: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            borderRadius: '10px',
            padding: '10px 12px',
            color: 'var(--color-danger, #EF4444)',
            fontSize: '0.8125rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <AlertCircle size={16} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        <AnimatePresence mode="wait">
          {authMode === 'oauth' ? (
            <motion.div
              key="oauth"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.2 }}
              style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '14px' }}
            >
              {/* Secure Notice */}
              <div style={{ 
                background: 'rgba(99, 102, 241, 0.06)', 
                border: '1px solid rgba(99, 102, 241, 0.18)', 
                borderRadius: '12px', 
                padding: '12px 14px', 
                fontSize: '0.75rem', 
                lineHeight: '1.45',
                color: textSecondaryColor,
                textAlign: 'left'
              }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <ShieldAlert size={16} style={{ color: '#818CF8', flexShrink: 0, marginTop: '2px' }} />
                  <div>
                    <strong style={{ color: textPrimaryColor, display: 'block', marginBottom: '2px' }}>Least-Privilege Security</strong>
                    We use Google OAuth (read-only). We never ask for or store your Gmail password.
                  </div>
                </div>
              </div>

              {/* Continue with Google */}
              <button
                onClick={login}
                type="button"
                className="btn btn-primary"
                style={{ 
                  width: '100%', 
                  padding: '12px', 
                  fontSize: '0.875rem', 
                  fontWeight: '600', 
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '10px',
                  background: 'var(--color-indigo)',
                  border: 'none',
                  color: '#fff',
                  cursor: 'pointer',
                  boxShadow: '0 4px 14px rgba(99, 102, 241, 0.25)'
                }}
              >
                <svg style={{ width: '16px', height: '16px' }} viewBox="0 0 24 24" fill="currentColor">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#FFFFFF" />
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#FFFFFF" fillRule="evenodd" opacity="0.85" />
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FFFFFF" fillRule="evenodd" opacity="0.75" />
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#FFFFFF" opacity="0.9" />
                </svg>
                <span>Continue with Google</span>
              </button>

              <div style={{ display: 'flex', alignItems: 'center', width: '100%', padding: '2px 0' }}>
                <div style={{ flexGrow: 1, borderTop: '1px solid var(--glass-border)' }}></div>
                <span style={{ margin: '0 10px', fontSize: '0.6875rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: textSecondaryColor }}>
                  OR
                </span>
                <div style={{ flexGrow: 1, borderTop: '1px solid var(--glass-border)' }}></div>
              </div>

              {/* Instant Test Session (Mock OAuth Session) */}
              <button
                onClick={loginWithMock}
                type="button"
                className="btn btn-ghost"
                style={{ 
                  width: '100%', 
                  padding: '11px', 
                  fontSize: '0.875rem', 
                  fontWeight: '500', 
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  background: 'rgba(255, 255, 255, 0.04)',
                  border: '1px solid var(--glass-border)',
                  color: textPrimaryColor,
                  cursor: 'pointer',
                  transition: 'background 0.2s ease'
                }}
              >
                <Mail size={16} />
                <span>Sign In with Demo Session</span>
              </button>

              {/* Instant Client Demo Mode */}
              <button
                onClick={enterDemoMode}
                type="button"
                style={{
                  width: '100%',
                  padding: '8px',
                  fontSize: '0.75rem',
                  color: textSecondaryColor,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  textDecoration: 'underline'
                }}
              >
                Launch Offline Demo Mode
              </button>
            </motion.div>
          ) : (
            <motion.form
              key="email"
              onSubmit={handleEmailSubmit}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '12px' }}
            >
              {isRegister && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: textSecondaryColor, marginBottom: '4px' }}>
                    Full Name
                  </label>
                  <div style={{ position: 'relative' }}>
                    <UserIcon size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: textSecondaryColor }} />
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Alex Developer"
                      style={{
                        width: '100%',
                        padding: '10px 12px 10px 36px',
                        background: 'rgba(255, 255, 255, 0.04)',
                        border: '1px solid var(--glass-border)',
                        borderRadius: '8px',
                        color: textPrimaryColor,
                        fontSize: '0.875rem',
                        outline: 'none'
                      }}
                    />
                  </div>
                </div>
              )}

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: textSecondaryColor, marginBottom: '4px' }}>
                  Email Address
                </label>
                <div style={{ position: 'relative' }}>
                  <Mail size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: textSecondaryColor }} />
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    style={{
                      width: '100%',
                      padding: '10px 12px 10px 36px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      borderRadius: '8px',
                      color: textPrimaryColor,
                      fontSize: '0.875rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: textSecondaryColor, marginBottom: '4px' }}>
                  Password
                </label>
                <div style={{ position: 'relative' }}>
                  <Lock size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: textSecondaryColor }} />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    style={{
                      width: '100%',
                      padding: '10px 12px 10px 36px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid var(--glass-border)',
                      borderRadius: '8px',
                      color: textPrimaryColor,
                      fontSize: '0.875rem',
                      outline: 'none'
                    }}
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: '100%',
                  padding: '12px',
                  marginTop: '4px',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                  borderRadius: '10px',
                  background: 'var(--color-indigo)',
                  border: 'none',
                  color: '#fff',
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  opacity: submitting ? 0.7 : 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px'
                }}
              >
                <span>{submitting ? 'Please wait...' : isRegister ? 'Create Account' : 'Sign In'}</span>
                {!submitting && <ArrowRight size={16} />}
              </button>

              <div style={{ textAlign: 'center', marginTop: '6px' }}>
                <button
                  type="button"
                  onClick={() => { setIsRegister(!isRegister); setError(''); }}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--color-accent, #4FE3FF)',
                    fontSize: '0.75rem',
                    cursor: 'pointer'
                  }}
                >
                  {isRegister ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
                </button>
              </div>
            </motion.form>
          )}
        </AnimatePresence>

        {/* Footer info */}
        <div style={{ fontSize: '0.6875rem', color: textSecondaryColor, textAlign: 'center' }}>
          Secure sessions are encrypted and stored safely.
        </div>
      </motion.div>
    </div>
  );
}
