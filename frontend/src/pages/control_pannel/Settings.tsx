import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './Settings.css';
import {
  fetchPortalSettings,
  savePortalSettings,
  type PortalSettings,
  type PortalSettingsLimits,
} from '../../api/settings.api';
import {
  DEFAULT_UI_PORTAL_SETTINGS,
  MAX_MARKET_STATUS_POLL_SECONDS,
  MAX_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES,
  MAX_ORDER_LOGS_LIVE_REFRESH_SECONDS,
  MAX_VALIDATE_DEBOUNCE_MS,
  MIN_MARKET_STATUS_POLL_SECONDS,
  MIN_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES,
  MIN_ORDER_LOGS_LIVE_REFRESH_SECONDS,
  MIN_VALIDATE_DEBOUNCE_MS,
  normalizeUiPortalSettings,
  readUiPortalSettings,
  resetUiPortalSettings,
  writeUiPortalSettings,
  type UiPortalSettings,
} from '../../lib/uiPortalSettings';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

const SCAN_INTERVAL_SLIDER_MAX_SECONDS = 3600;

const clampSettingValue = (value: number, min: number, max: number) => {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.round(value)));
};

interface SettingFieldProps {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit: string;
  sliderMax?: number;
  showSlider?: boolean;
  inputHint?: string;
  onChange: (value: number) => void;
}

const SettingField: React.FC<SettingFieldProps> = ({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  unit,
  sliderMax,
  showSlider = true,
  inputHint,
  onChange,
}) => {
  const effectiveSliderMax = sliderMax ?? max;
  const sliderValue = clampSettingValue(value, min, effectiveSliderMax);

  return (
    <div className="settings-field">
      <div className="settings-field-head">
        <div>
          <label className="settings-field-label">{label}</label>
          <p className="settings-field-hint">{hint}</p>
        </div>
        <div className="settings-field-value">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(event) => onChange(clampSettingValue(Number(event.target.value), min, max))}
            className="settings-number-input"
          />
          <span>{unit}</span>
        </div>
      </div>
      {inputHint ? <p className="settings-field-input-hint">{inputHint}</p> : null}
      {showSlider ? (
        <div className="settings-field-slider-wrap">
          <input
            type="range"
            min={min}
            max={effectiveSliderMax}
            step={step}
            value={sliderValue}
            onChange={(event) => onChange(clampSettingValue(Number(event.target.value), min, effectiveSliderMax))}
            className="settings-range"
          />
          <span className="settings-range-label">
            Slider: {min}–{effectiveSliderMax} {unit}
          </span>
        </div>
      ) : null}
    </div>
  );
};

const Settings: React.FC = () => {
  const [serverSettings, setServerSettings] = useState<PortalSettings | null>(null);
  const [limits, setLimits] = useState<PortalSettingsLimits | null>(null);
  const [uiSettings, setUiSettings] = useState<UiPortalSettings>(() => readUiPortalSettings());
  const [useMaxDataAge, setUseMaxDataAge] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [errorMessage, setErrorMessage] = useState('');

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      const response = await fetchPortalSettings();
      setServerSettings(response.settings);
      setLimits(response.limits);
      setUseMaxDataAge(response.settings.default_max_data_age_seconds != null);
      setUiSettings(readUiPortalSettings());
    } catch {
      setErrorMessage('Could not load settings from the server.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const scanLimits = limits?.monitor_interval_seconds || { min: 3, max: 86400 };
  const maxAgeLimits = limits?.default_max_data_age_seconds || { min: 5, max: 3600 };
  const nepseLimits = limits?.nepse_alpha_interval_seconds || { min: 60, max: 3600 };
  const tickLimits = limits?.monitor_tick_seconds || { min: 1, max: 3600 };
  const concurrencyLimits = limits?.max_price_fetch_concurrency || { min: 1, max: 20 };

  const effectiveScanLabel = useMemo(() => {
    if (!serverSettings) {
      return '—';
    }
    const scansPerMinute = (60 / serverSettings.monitor_interval_seconds).toFixed(1);
    return `${serverSettings.monitor_interval_seconds}s · ~${scansPerMinute} scans/min`;
  }, [serverSettings]);

  const updateServer = (patch: Partial<PortalSettings>) => {
    setServerSettings((current) => (current ? { ...current, ...patch } : current));
  };

  const updateUi = (patch: Partial<UiPortalSettings>) => {
    setUiSettings((current) => normalizeUiPortalSettings({ ...current, ...patch }));
  };

  const handleSave = async () => {
    if (!serverSettings) {
      return;
    }
    setSaveState('saving');
    setErrorMessage('');
    try {
      const payload: Partial<PortalSettings> = {
        monitor_interval_seconds: serverSettings.monitor_interval_seconds,
        default_execution_mode: serverSettings.default_execution_mode,
        default_max_data_age_seconds: useMaxDataAge
          ? serverSettings.default_max_data_age_seconds ?? maxAgeLimits.min
          : null,
        enable_scan_staggering: serverSettings.enable_scan_staggering,
        nepse_alpha_interval_seconds: serverSettings.nepse_alpha_interval_seconds,
        monitor_tick_seconds: serverSettings.monitor_tick_seconds,
        max_price_fetch_concurrency: serverSettings.max_price_fetch_concurrency,
      };
      const response = await savePortalSettings(payload);
      setServerSettings(response.settings);
      setLimits(response.limits);
      writeUiPortalSettings(uiSettings);
      setSaveState('saved');
      window.setTimeout(() => setSaveState('idle'), 2500);
    } catch {
      setSaveState('error');
      setErrorMessage('Failed to save settings. Check that the backend is running.');
    }
  };

  const handleReset = async () => {
    setServerSettings({
      monitor_interval_seconds: 5,
      default_max_data_age_seconds: null,
      default_execution_mode: 'live',
      enable_scan_staggering: true,
      nepse_alpha_interval_seconds: 1800,
      monitor_tick_seconds: 5,
      max_price_fetch_concurrency: 5,
    });
    setUseMaxDataAge(false);
    setUiSettings({ ...DEFAULT_UI_PORTAL_SETTINGS });
    resetUiPortalSettings();
    setSaveState('idle');
    setErrorMessage('');
  };

  if (loading) {
    return (
      <div className="settings-page">
        <div className="settings-loading panel">Loading settings…</div>
      </div>
    );
  }

  if (!serverSettings) {
    return (
      <div className="settings-page">
        <div className="settings-loading panel settings-error">
          {errorMessage || 'Settings unavailable.'}
          <button type="button" className="btn btn-secondary" onClick={() => void loadSettings()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="settings-page">
      <header className="settings-hero panel">
        <div>
          <h2>Settings</h2>
          <p>Configure monitoring speed, defaults for new strategies, and how often the portal refreshes data.</p>
        </div>
        <div className="settings-hero-badge">
          <span className="settings-hero-badge-label">Current scan rate</span>
          <strong>{effectiveScanLabel}</strong>
        </div>
      </header>

      {errorMessage ? <div className="settings-banner error">{errorMessage}</div> : null}
      {saveState === 'saved' ? <div className="settings-banner success">Settings saved.</div> : null}

      <section className="settings-card panel">
        <div className="settings-card-head">
          <div>
            <h3>Order monitoring</h3>
            <p>Server-side scan loop for scheduled orders and live price checks.</p>
          </div>
          <span className="settings-chip server">Server</span>
        </div>

        <SettingField
          label="Scan interval"
          hint="How often each order is re-checked after its TMS quote fetch. Lower is faster but uses more TMS requests."
          value={serverSettings.monitor_interval_seconds}
          min={scanLimits.min}
          max={scanLimits.max}
          sliderMax={Math.min(SCAN_INTERVAL_SLIDER_MAX_SECONDS, scanLimits.max)}
          inputHint={`Type up to ${scanLimits.max} sec for slower schedules. Slider covers up to 1 hour.`}
          unit="sec"
          onChange={(value) => updateServer({ monitor_interval_seconds: value })}
        />

        <div className="settings-subsection">
          <h4>Scan orchestration</h4>
          <p className="settings-field-hint">
            Randomize each order's TMS refresh slot and fetch Nepse Alpha only when a strategy needs it.
          </p>
        </div>

        <div className="settings-toggle-row">
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={serverSettings.enable_scan_staggering}
              onChange={(event) => updateServer({ enable_scan_staggering: event.target.checked })}
            />
            <span>Enable scan staggering</span>
          </label>
          <p className="settings-field-hint">
            When on, each order gets a different random slot every interval so 100 orders at 20s do not all hit TMS at once.
            Off scans every due order together each interval.
          </p>
        </div>

        <SettingField
          label="Monitor loop tick"
          hint="How often the background loop wakes to see which orders are due for a TMS scan."
          value={serverSettings.monitor_tick_seconds}
          min={tickLimits.min}
          max={tickLimits.max}
          unit="sec"
          onChange={(value) => updateServer({ monitor_tick_seconds: value })}
        />

        <SettingField
          label="Nepse Alpha refresh interval"
          hint="Separate from TMS scans. Only orders whose rules use Nepse fields fetch on this cadence (cache still applies)."
          value={serverSettings.nepse_alpha_interval_seconds}
          min={nepseLimits.min}
          max={nepseLimits.max}
          unit="sec"
          onChange={(value) => updateServer({ nepse_alpha_interval_seconds: value })}
        />

        <SettingField
          label="Max concurrent TMS fetches"
          hint="Limits parallel TMS quote requests during each monitor tick."
          value={serverSettings.max_price_fetch_concurrency}
          min={concurrencyLimits.min}
          max={concurrencyLimits.max}
          unit="req"
          onChange={(value) => updateServer({ max_price_fetch_concurrency: value })}
        />

        <div className="settings-toggle-row">
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={useMaxDataAge}
              onChange={(event) => {
                setUseMaxDataAge(event.target.checked);
                if (event.target.checked && serverSettings.default_max_data_age_seconds == null) {
                  updateServer({ default_max_data_age_seconds: 60 });
                }
              }}
            />
            <span>Reject stale quotes by default</span>
          </label>
          <p className="settings-field-hint">
            When enabled, new custom-query orders skip evaluation if TMS quote data is older than the limit below.
          </p>
        </div>

        {useMaxDataAge ? (
          <SettingField
            label="Default max quote age"
            hint="Applies to new strategy plans unless overridden in the query."
            value={serverSettings.default_max_data_age_seconds ?? maxAgeLimits.min}
            min={maxAgeLimits.min}
            max={maxAgeLimits.max}
            unit="sec"
            onChange={(value) => updateServer({ default_max_data_age_seconds: value })}
          />
        ) : null}

        <div className="settings-field">
          <label className="settings-field-label">Default execution mode</label>
          <p className="settings-field-hint">Used as the baseline for new custom-query schedules.</p>
          <div className="settings-segmented">
            {(['live', 'paper'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={serverSettings.default_execution_mode === mode ? 'active' : ''}
                onClick={() => updateServer({ default_execution_mode: mode })}
              >
                {mode === 'live' ? 'Live trading' : 'Paper / dry-run'}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="settings-card panel">
        <div className="settings-card-head">
          <div>
            <h3>Order Logs page</h3>
            <p>Controls auto-refresh while you watch scheduled orders and logs.</p>
          </div>
          <span className="settings-chip browser">Browser</span>
        </div>

        <SettingField
          label="Live tab refresh"
          hint="How often Scheduled and Order Logs tabs poll the server while visible."
          value={uiSettings.orderLogsLiveRefreshSeconds}
          min={MIN_ORDER_LOGS_LIVE_REFRESH_SECONDS}
          max={MAX_ORDER_LOGS_LIVE_REFRESH_SECONDS}
          unit="sec"
          onChange={(value) => updateUi({ orderLogsLiveRefreshSeconds: value })}
        />

        <SettingField
          label="Background refresh"
          hint="Full cache refresh for trade book and history while Order Logs is open."
          value={uiSettings.orderLogsBackgroundRefreshMinutes}
          min={MIN_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES}
          max={MAX_ORDER_LOGS_BACKGROUND_REFRESH_MINUTES}
          unit="min"
          onChange={(value) => updateUi({ orderLogsBackgroundRefreshMinutes: value })}
        />
      </section>

      <section className="settings-card panel">
        <div className="settings-card-head">
          <div>
            <h3>Header &amp; editor</h3>
            <p>Clock sync and custom-query typing responsiveness.</p>
          </div>
          <span className="settings-chip browser">Browser</span>
        </div>

        <SettingField
          label="Market status sync"
          hint="How often the header re-checks market open/closed with the server. The clock still ticks every second."
          value={uiSettings.marketStatusPollSeconds}
          min={MIN_MARKET_STATUS_POLL_SECONDS}
          max={MAX_MARKET_STATUS_POLL_SECONDS}
          unit="sec"
          onChange={(value) => updateUi({ marketStatusPollSeconds: value })}
        />

        <SettingField
          label="Query validate debounce"
          hint="Delay after you stop typing before the custom query syntax check runs."
          value={uiSettings.customQueryValidateDebounceMs}
          min={MIN_VALIDATE_DEBOUNCE_MS}
          max={MAX_VALIDATE_DEBOUNCE_MS}
          step={100}
          unit="ms"
          onChange={(value) => updateUi({ customQueryValidateDebounceMs: value })}
        />
      </section>

      <div className="settings-actions panel">
        <button
          type="button"
          className="btn btn-primary"
          disabled={saveState === 'saving'}
          onClick={() => void handleSave()}
        >
          {saveState === 'saving' ? 'Saving…' : 'Save settings'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => void handleReset()}>
          Reset to defaults
        </button>
        <p className="settings-actions-note">
          Server settings persist across restarts. Browser settings stay on this device.
        </p>
      </div>
    </div>
  );
};

export default Settings;
