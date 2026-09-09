import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Mail, Lock, User, Eye, EyeOff, Sparkles, AlertCircle, RotateCw } from 'lucide-react';
import { motion } from 'motion/react';
import { useApp } from '../context/AppContext';
import { registerWithEmail } from '../services/api';

export default function Register() {
  const { login, theme } = useApp();
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const isLight = theme === 'light';

  // Tailwind classes that adapt to our theme variables
  const bgClass = isLight ? 'bg-white' : 'bg-[#14141B]';
  const textPrimary = isLight ? 'text-gray-900' : 'text-white';
  const textSecondary = isLight ? 'text-gray-500' : 'text-gray-400';
  const borderClass = isLight ? 'border-gray-200' : 'border-white/10';
  const inputBg = isLight ? 'bg-gray-50' : 'bg-white/[0.02]';

  const validateEmail = (email) => {
    return String(email)
      .toLowerCase()
      .match(
        /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|.(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
      );
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!name || !email || !password || !confirmPassword) {
      setError('Please fill in all fields.');
      return;
    }

    if (!validateEmail(email)) {
      setError('Please enter a valid email address.');
      return;
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    if (!agreedToTerms) {
      setError('You must agree to the Terms & Conditions.');
      return;
    }

    setLoading(true);
    try {
      // Pass null for contactNo since it's optional in the new UI requirements
      const res = await registerWithEmail(email, password, name, null);
      if (res.success) {
        // Redirect to login on success
        navigate('/login');
      } else {
        setError(res.error || 'Failed to register account.');
      }
    } catch (err) {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-[92vh] items-center justify-center px-4 relative z-10 font-sans py-8">
      <motion.div
        initial={{ opacity: 0, y: 30, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1], delay: 0.05 }}
        className={`w-full max-w-[440px] rounded-2xl border ${borderClass} ${bgClass} p-8 shadow-2xl transition-all duration-300`}
      >
        {/* Header Section */}
        <div className="flex flex-col items-center mb-8 text-center">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/30 mb-4">
            <Sparkles className="text-white" size={24} />
          </div>
          <h2 className={`text-2xl font-bold tracking-tight ${textPrimary}`}>
            Create an Account
          </h2>
          <p className={`text-sm mt-2 ${textSecondary}`}>
            Join MailMind AI and supercharge your inbox
          </p>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-6 p-3 rounded-xl border border-red-200 bg-red-50 text-red-600 text-sm flex items-start gap-2">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          
          {/* Name Field */}
          <div className="space-y-1.5">
            <label className={`block text-sm font-medium ${textPrimary}`}>
              Full Name
            </label>
            <div className="relative">
              <span className={`absolute inset-y-0 left-0 pl-3.5 flex items-center ${textSecondary} pointer-events-none`}>
                <User size={16} />
              </span>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="John Doe"
                className={`w-full pl-10 pr-4 py-2.5 rounded-xl border ${borderClass} ${inputBg} ${textPrimary} focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all text-sm`}
              />
            </div>
          </div>

          {/* Email Field */}
          <div className="space-y-1.5">
            <label className={`block text-sm font-medium ${textPrimary}`}>
              Email Address
            </label>
            <div className="relative">
              <span className={`absolute inset-y-0 left-0 pl-3.5 flex items-center ${textSecondary} pointer-events-none`}>
                <Mail size={16} />
              </span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                className={`w-full pl-10 pr-4 py-2.5 rounded-xl border ${borderClass} ${inputBg} ${textPrimary} focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all text-sm`}
              />
            </div>
          </div>

          {/* Passwords Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Password Field */}
            <div className="space-y-1.5">
              <label className={`block text-sm font-medium ${textPrimary}`}>
                Password
              </label>
              <div className="relative">
                <span className={`absolute inset-y-0 left-0 pl-3.5 flex items-center ${textSecondary} pointer-events-none`}>
                  <Lock size={16} />
                </span>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className={`w-full pl-10 pr-10 py-2.5 rounded-xl border ${borderClass} ${inputBg} ${textPrimary} focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all text-sm`}
                />
              </div>
            </div>

            {/* Confirm Password Field */}
            <div className="space-y-1.5">
              <label className={`block text-sm font-medium ${textPrimary}`}>
                Confirm
              </label>
              <div className="relative">
                <span className={`absolute inset-y-0 left-0 pl-3.5 flex items-center ${textSecondary} pointer-events-none`}>
                  <Lock size={16} />
                </span>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  className={`w-full pl-10 pr-10 py-2.5 rounded-xl border ${borderClass} ${inputBg} ${textPrimary} focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all text-sm`}
                />
              </div>
            </div>
          </div>

          {/* Show Password Toggle */}
          <div className="flex items-center justify-end">
             <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className={`text-xs flex items-center gap-1.5 font-medium ${textSecondary} hover:text-blue-500 transition-colors`}
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                <span>{showPassword ? 'Hide Passwords' : 'Show Passwords'}</span>
              </button>
          </div>

          {/* Terms & Conditions */}
          <div className="flex items-start gap-2 pt-2">
            <label className="flex items-center cursor-pointer group mt-0.5">
              <div className="relative flex items-center justify-center">
                <input
                  type="checkbox"
                  checked={agreedToTerms}
                  onChange={(e) => setAgreedToTerms(e.target.checked)}
                  className="peer sr-only"
                />
                <div className={`w-4 h-4 rounded border ${borderClass} peer-checked:bg-blue-600 peer-checked:border-blue-600 transition-all flex items-center justify-center`}>
                  {agreedToTerms && <CheckIcon />}
                </div>
              </div>
            </label>
            <p className={`text-xs ${textSecondary} leading-relaxed`}>
              I agree to the <a href="#" className="text-blue-600 hover:underline">Terms of Service</a> and <a href="#" className="text-blue-600 hover:underline">Privacy Policy</a>.
            </p>
          </div>

          {/* Register Button */}
          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition-all flex items-center justify-center gap-2 active:scale-[0.98] disabled:opacity-70 disabled:cursor-not-allowed shadow-md shadow-blue-500/20"
          >
            {loading ? (
              <>
                <RotateCw className="w-4 h-4 animate-spin" />
                <span>Creating Account...</span>
              </>
            ) : (
              <span>Create Account</span>
            )}
          </button>
        </form>

        {/* Divider */}
        <div className="relative flex items-center my-6">
          <div className={`flex-grow border-t ${borderClass}`}></div>
          <span className={`mx-4 text-xs font-medium uppercase tracking-wider ${textSecondary}`}>
            Or register with
          </span>
          <div className={`flex-grow border-t ${borderClass}`}></div>
        </div>

        {/* Social Login */}
        <button
          onClick={login}
          type="button"
          className={`w-full py-2.5 rounded-xl border ${borderClass} ${inputBg} hover:bg-gray-100 dark:hover:bg-white/5 ${textPrimary} font-medium text-sm transition-all flex items-center justify-center gap-3 active:scale-[0.98]`}
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" fillRule="evenodd" />
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" fillRule="evenodd" />
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
          </svg>
          <span>Sign up with Google</span>
        </button>

        {/* Login Link */}
        <div className={`mt-8 text-center text-sm ${textSecondary}`}>
          Already have an account?{' '}
          <Link to="/login" className="text-blue-600 hover:text-blue-700 font-semibold hover:underline">
            Log in
          </Link>
        </div>
      </motion.div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="10" height="8" viewBox="0 0 10 8" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
