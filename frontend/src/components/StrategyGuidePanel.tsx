import React from 'react';
import { StrategyCatalogEntry } from '../lib/strategies/catalog';
import '../pages/control_pannel/StrategyDetails.css';

interface Props {
  entry: StrategyCatalogEntry;
  open?: boolean;
  onToggle?: () => void;
  variant?: 'accordion' | 'flat';
}

const InnerToggle: React.FC<{ title: string; children: React.ReactNode; defaultOpen?: boolean }> = ({
  title,
  children,
  defaultOpen = false,
}) => (
  <details className="strategy-inner-toggle" open={defaultOpen}>
    <summary>
      <span className="strategy-inner-chevron" aria-hidden>›</span>
      <span>{title}</span>
    </summary>
    <div className="strategy-inner-body">{children}</div>
  </details>
);

const ScenarioTable: React.FC<{ scenarios: StrategyCatalogEntry['testScenarios'] }> = ({ scenarios }) => (
  <div className="strategy-scenario-table-wrap">
    <table className="strategy-scenario-table">
      <thead>
        <tr>
          <th>Scenario</th>
          <th>System action</th>
          <th>Order sent to TMS</th>
        </tr>
      </thead>
      <tbody>
        {scenarios.map((row) => (
          <tr key={`${row.situation}-${row.action}`}>
            <td>{row.situation}</td>
            <td><span className="strategy-action-chip">{row.action}</span></td>
            <td>{row.order}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const StrategyGuideContent: React.FC<{ entry: StrategyCatalogEntry }> = ({ entry }) => (
  <div className={`strategy-toggle-body ${entry.side}`}>
    <div className="strategy-detail-block strategy-detail-overview">
      <h4>Overview</h4>
      <p><strong>Best for:</strong> {entry.bestFor}</p>
      <p>{entry.purpose}</p>
    </div>

    <InnerToggle title="How it works" defaultOpen>
      <ol>
        {entry.howItWorks.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
    </InnerToggle>

    <InnerToggle title="Tested scenarios (unit tests)">
      <ScenarioTable scenarios={entry.testScenarios} />
    </InnerToggle>

    <InnerToggle title="When an order executes">
      <p className="strategy-on-execute">{entry.onExecute}</p>
      <ul className="strategy-behavior-list">
        {entry.expectedBehavior.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </InnerToggle>

    <InnerToggle title="Example walkthrough">
      <p>{entry.example}</p>
    </InnerToggle>

    <InnerToggle title="Required data">
      <p>{entry.requiredData.join(' · ')}</p>
    </InnerToggle>

    <p className="strategy-note">{entry.note}</p>
  </div>
);

const StrategyGuidePanel: React.FC<Props> = ({ entry, open = false, onToggle, variant = 'accordion' }) => {
  if (variant === 'flat') {
    return (
      <article className={`strategy-guide-flat ${entry.side}`}>
        <StrategyGuideContent entry={entry} />
      </article>
    );
  }

  return (
    <details className={`strategy-toggle ${entry.side}`} open={open}>
      <summary
        onClick={(event) => {
          event.preventDefault();
          onToggle?.();
        }}
      >
        <span className="strategy-toggle-chevron" aria-hidden>›</span>
        <div className="strategy-toggle-main">
          <strong>{entry.name}</strong>
          <span>{entry.purpose}</span>
        </div>
        <span className={`strategy-details-pill ${entry.side}`}>{entry.side.toUpperCase()}</span>
      </summary>
      {open && <StrategyGuideContent entry={entry} />}
    </details>
  );
};

export default StrategyGuidePanel;
