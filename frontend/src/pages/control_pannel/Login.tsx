import React, { useCallback, useEffect, useState } from 'react';
import './Login.css';
import ErrorMessage from '../../components/ErrorMessage';
import { extractApiErrorMessage } from '../../utils/apiError';
import {
  TmsAccount,
  createTmsAccount,
  deleteTmsAccount,
  listTmsAccounts,
  loginTmsAccount,
  updateTmsAccount,
} from '../../api/tmsAccounts.api';

type FormMode = 'create' | 'edit' | null;

const emptyForm = {
  client_id: '',
  broker_no: '',
  password: '',
  auto_login: true,
};

const formatSessionStatus = (status: string) => status.replace(/_/g, ' ');

const Login: React.FC = () => {
  const [accounts, setAccounts] = useState<TmsAccount[]>([]);
  const [loggedInCount, setLoggedInCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [form, setForm] = useState(emptyForm);
  const [editingClientId, setEditingClientId] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [loadWarning, setLoadWarning] = useState('');

  const loadAccounts = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
    }
    setLoadWarning('');
    try {
      const data = await listTmsAccounts();
      setAccounts(data.accounts);
      setLoggedInCount(data.logged_in_count);
      setLoadWarning(data.notice || '');
    } catch (error) {
      setAccounts([]);
      setLoggedInCount(0);
      setErrorMessage(extractApiErrorMessage(error));
    } finally {
      if (!options?.silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  const resetMessages = () => {
    setSuccessMessage('');
    setErrorMessage('');
  };

  const openCreateForm = () => {
    resetMessages();
    setFormMode('create');
    setEditingClientId(null);
    setForm(emptyForm);
    setShowPassword(false);
  };

  const openEditForm = (account: TmsAccount) => {
    resetMessages();
    setFormMode('edit');
    setEditingClientId(account.client_id);
    setForm({
      client_id: account.client_id,
      broker_no: account.broker_no,
      password: '',
      auto_login: account.auto_login,
    });
    setShowPassword(false);
  };

  const closeForm = () => {
    setFormMode(null);
    setEditingClientId(null);
    setForm(emptyForm);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    resetMessages();
    setActionLoading('save');
    try {
      if (formMode === 'create') {
        if (!form.password.trim()) {
          setErrorMessage('Password is required for a new account.');
          return;
        }
        await createTmsAccount({
          client_id: form.client_id.trim(),
          broker_no: form.broker_no.trim(),
          password: form.password,
          auto_login: form.auto_login,
        });
        setSuccessMessage(`Account ${form.client_id.trim()} created.`);
      } else if (formMode === 'edit' && editingClientId) {
        await updateTmsAccount(editingClientId, {
          broker_no: form.broker_no.trim(),
          auto_login: form.auto_login,
          ...(form.password.trim() ? { password: form.password } : {}),
        });
        setSuccessMessage(`Account ${editingClientId} updated.`);
      }
      closeForm();
      await loadAccounts();
    } catch (error) {
      setErrorMessage(extractApiErrorMessage(error));
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (account: TmsAccount) => {
    if (!window.confirm(`Delete TMS account ${account.client_id}?`)) {
      return;
    }
    resetMessages();
    setActionLoading(`delete-${account.client_id}`);
    try {
      await deleteTmsAccount(account.client_id);
      setSuccessMessage(`Account ${account.client_id} deleted.`);
      if (editingClientId === account.client_id) {
        closeForm();
      }
      await loadAccounts();
    } catch (error) {
      setErrorMessage(extractApiErrorMessage(error));
    } finally {
      setActionLoading(null);
    }
  };

  const formatLoginResponse = (response: { message?: Record<string, string> }) => {
    const payload = response?.message || {};
    const loginMessage = payload.message || 'TMS login successful';
    const expiryNote = payload.password_expiry ? ` Expiry: ${payload.password_expiry}.` : '';
    const rotationNote = payload.new_password_plain
      ? ` New password saved: ${payload.new_password_plain}`
      : '';
    return `${loginMessage}${expiryNote}${rotationNote}`;
  };

  const handleLoginStored = async (account: TmsAccount) => {
    resetMessages();
    setActionLoading(`login-${account.client_id}`);
    try {
      const response = await loginTmsAccount(account.client_id);
      setSuccessMessage(formatLoginResponse(response));
      await loadAccounts({ silent: true });
    } catch (error) {
      setErrorMessage(extractApiErrorMessage(error));
      await loadAccounts({ silent: true });
    } finally {
      setActionLoading(null);
    }
  };

  const loggedInAccounts = accounts.filter((a) => a.session_status === 'logged_in');

  return (
    <div className="tms-login-page">
      <div className="tms-login-hero panel">
        <div className="tms-login-hero-content">
          <div className="tms-login-hero-icon" aria-hidden="true">
            🔐
          </div>
          <div>
            <h2 className="tms-login-hero-title">TMS Login</h2>
            <p className="tms-login-hero-subtitle">
              Connect broker accounts, manage sessions, and view who is logged in to NEPSE TMS.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-secondary tms-refresh-btn"
          onClick={() => { void loadAccounts(); }}
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {successMessage && <ErrorMessage message={successMessage} variant="success" />}
      {errorMessage && <ErrorMessage message={errorMessage} variant="error" persistent />}
      {loadWarning && <ErrorMessage message={loadWarning} variant="info" persistent />}

      <div className="tms-login-stats">
        <div className="tms-stat-card">
          <span className="tms-stat-label">Total Accounts</span>
          <span className="tms-stat-value">{accounts.length}</span>
        </div>
        <div className="tms-stat-card tms-stat-card-active">
          <span className="tms-stat-label">Logged In</span>
          <span className="tms-stat-value">{loggedInCount}</span>
        </div>
      </div>

      <div className="tms-logged-in-panel panel">
        <h3 className="tms-section-title">Active Sessions</h3>
        {loading ? (
          <p className="tms-muted">Loading sessions...</p>
        ) : loggedInAccounts.length === 0 ? (
          <p className="tms-muted">No clients are logged in right now. Add an account below and press Login.</p>
        ) : (
          <div className="tms-logged-in-list">
            {loggedInAccounts.map((account) => (
              <div key={account.client_id} className="tms-logged-in-chip">
                <span className="tms-online-dot" aria-hidden="true" />
                <strong>{account.client_id}</strong>
                <span>Broker {account.broker_no}</span>
                {account.last_updated && (
                  <span className="tms-session-time">
                    Updated {new Date(account.last_updated).toLocaleString()}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className={`tms-login-layout${formMode ? ' has-sidebar' : ''}`}>
        <div className="tms-accounts-table-wrap panel">
          <div className="tms-panel-header">
            <div>
              <h3 className="tms-section-title">All Accounts</h3>
              <p className="panel-subtitle">Saved broker credentials and session status.</p>
            </div>
            <button type="button" className="btn btn-primary" onClick={openCreateForm}>
              + Add Account
            </button>
          </div>

          {loading ? (
            <div className="tms-loading-state">
              <span className="tms-spinner" aria-hidden="true" />
              <p className="tms-muted">Loading accounts...</p>
            </div>
          ) : accounts.length === 0 ? (
            <div className="tms-empty-state">
              <p>No TMS accounts yet.</p>
              <button type="button" className="btn btn-primary btn-sm" onClick={openCreateForm}>
                Add your first account
              </button>
            </div>
          ) : (
            <table className="tms-accounts-table">
              <thead>
                <tr>
                  <th>Client ID</th>
                  <th>Broker</th>
                  <th>Auto Login</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.client_id}>
                    <td className="tms-client-id">{account.client_id}</td>
                    <td>{account.broker_no}</td>
                    <td>{account.auto_login ? 'Yes' : 'No'}</td>
                    <td>
                      <div className="tms-status-cell">
                        <span className={`tms-status tms-status-${account.session_status}`}>
                          {formatSessionStatus(account.session_status)}
                        </span>
                        {account.session_message && account.session_status !== 'logged_in' && (
                          <span className="tms-session-error" title={account.session_message}>
                            {account.session_message}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="tms-actions">
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={actionLoading === `login-${account.client_id}`}
                        onClick={() => handleLoginStored(account)}
                      >
                        {actionLoading === `login-${account.client_id}` ? 'Logging in...' : 'Login'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => openEditForm(account)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm tms-delete-btn"
                        disabled={actionLoading === `delete-${account.client_id}`}
                        onClick={() => handleDelete(account)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {formMode && (
          <div className="tms-side-column">
            <div className="tms-form-panel panel">
              <div className="tms-form-header">
                <h3 className="tms-section-title">
                  {formMode === 'create' ? 'Add TMS Account' : `Edit ${editingClientId}`}
                </h3>
                <button type="button" className="btn btn-secondary btn-sm" onClick={closeForm}>
                  Cancel
                </button>
              </div>
              <form onSubmit={handleSave} className="tms-login-form">
                <div className="tms-login-grid">
                  <div className="form-group">
                    <label htmlFor="clientId">Client ID</label>
                    <input
                      type="text"
                      id="clientId"
                      className="input"
                      value={form.client_id}
                      onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                      placeholder="Your TMS client ID"
                      disabled={formMode === 'edit'}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="brokerNo">Broker Number</label>
                    <input
                      type="text"
                      id="brokerNo"
                      className="input"
                      value={form.broker_no}
                      onChange={(e) => setForm({ ...form, broker_no: e.target.value })}
                      placeholder="e.g. 35"
                      required
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label htmlFor="password">
                    Password {formMode === 'edit' && '(leave blank to keep current)'}
                  </label>
                  <div className="tms-password-row">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      id="password"
                      className="input"
                      value={form.password}
                      onChange={(e) => setForm({ ...form, password: e.target.value })}
                      placeholder="Plain TMS password"
                      required={formMode === 'create'}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setShowPassword((v) => !v)}
                    >
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>
                <label className="tms-checkbox">
                  <input
                    type="checkbox"
                    checked={form.auto_login}
                    onChange={(e) => setForm({ ...form, auto_login: e.target.checked })}
                  />
                  Enable auto login
                </label>
                <button
                  type="submit"
                  className="btn btn-primary tms-login-btn"
                  disabled={actionLoading === 'save'}
                >
                  {actionLoading === 'save' ? 'Saving...' : formMode === 'create' ? 'Create Account' : 'Save Changes'}
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Login;
