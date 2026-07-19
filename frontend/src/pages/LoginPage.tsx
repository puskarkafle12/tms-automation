import React, { useEffect, useState } from 'react';
import { authService } from '../services/authService';
import './LoginPage.css';
import { useNavigate } from 'react-router-dom';
import ErrorMessage from '../components/ErrorMessage';
import { extractApiErrorMessage } from '../utils/apiError';

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [captcha, setCaptcha] = useState<{ captcha_id: string; image_data_url: string; prompt: string } | null>(null);
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  const loadCaptcha = async () => {
    try { setCaptcha(await authService.captcha()); setCaptchaAnswer(''); }
    catch (captchaError) { setError(extractApiErrorMessage(captchaError)); }
  };
  useEffect(() => { if (mode === 'signup') void loadCaptcha(); }, [mode]);
  useEffect(() => {
    if (!localStorage.getItem('accessToken')) return;
    let cancelled = false;
    void authService
      .me()
      .then(() => { if (!cancelled) navigate('/dashboard/order-logs', { replace: true }); })
      .catch(() => { /* keep the login form when the saved session is truly invalid */ });
    return () => { cancelled = true; };
  }, [navigate]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError(null);
      setSuccess(null);
      const cleanUsername = username.trim();
      if (!/^[a-zA-Z0-9_.-]{3,40}$/.test(cleanUsername)) throw new Error('Username must be 3–40 letters, numbers, dots, dashes, or underscores.');
      if (mode === 'signup') {
        if (password.length < 10 || !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password)) throw new Error('Password must have at least 10 characters, uppercase, lowercase, and a number.');
        if (password !== confirmPassword) throw new Error('Passwords do not match.');
        if (!captcha) throw new Error('Load a CAPTCHA challenge first.');
        if (captchaAnswer.trim().length !== 6) throw new Error('Enter all six CAPTCHA characters.');
        await authService.signup(username, password, captcha.captcha_id, captchaAnswer);
        setSuccess('Account created securely. Opening your private workspace…');
      } else {
        await authService.login(username, password);
        setSuccess('Welcome back. Opening your private workspace…');
      }
      await new Promise((resolve) => window.setTimeout(resolve, 650));
      navigate('/dashboard/order-logs');
    } catch (loginError) {
      setError(extractApiErrorMessage(loginError));
      if (mode === 'signup') void loadCaptcha();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-page-bg" />
      <div className="login-page-card panel">
        <div className="login-page-brand">
          <div className="login-page-logo">T</div>
          <div>
            <h1>TMS Automation</h1>
            <p>{mode === 'login' ? 'Sign in to your private trading workspace' : 'Create a local account—no email verification required'}</p>
          </div>
        </div>

        {error && <ErrorMessage message={error} variant="error" />}
        {success && <div className="login-success" role="status">✓ {success}</div>}
        <form onSubmit={handleSubmit} className="login-page-form">
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              autoComplete="username"
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <div className="login-password-field"><input
              type={showPassword ? 'text' : 'password'}
              id="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              required
            /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? 'Hide' : 'Show'}</button></div>
            {mode === 'signup' && <small className="login-field-hint">10+ characters · uppercase · lowercase · number</small>}
          </div>
          {mode === 'signup' && <>
            <div className="form-group"><label htmlFor="confirm-password">Confirm password</label><input type="password" id="confirm-password" className="input" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" required /></div>
            <div className="login-captcha"><div><span>Human check</span>{captcha ? <img src={captcha.image_data_url} alt="Distorted six-character CAPTCHA challenge" /> : <b>Loading challenge…</b>}</div><button type="button" onClick={() => void loadCaptcha()} disabled={busy}>New image</button></div>
            <div className="form-group"><label htmlFor="captcha-answer">{captcha?.prompt || 'CAPTCHA characters'}</label><input id="captcha-answer" className="input login-captcha-answer" value={captchaAnswer} onChange={(e) => setCaptchaAnswer(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6))} inputMode="text" autoComplete="off" spellCheck={false} maxLength={6} placeholder="6 characters" required /></div>
          </>}
          <button type="submit" disabled={busy} className="btn btn-primary login-page-submit">
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create account'}
          </button>
          <button type="button" className="login-mode-switch" onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setError(null); setSuccess(null); setPassword(''); setConfirmPassword(''); setCaptchaAnswer(''); }}>
            {mode === 'login' ? 'New here? Create an account' : 'Already registered? Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
