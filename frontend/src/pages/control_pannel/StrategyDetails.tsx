import React, { useState } from 'react';
import './StrategyDetails.css';
import { STRATEGY_CATALOG } from '../../lib/strategies/catalog';
import { STRATEGY_DISCLAIMER } from '../../lib/strategies';
import StrategyGuidePanel from '../../components/StrategyGuidePanel';

const StrategyDetails: React.FC = () => {
  const buyStrategies = STRATEGY_CATALOG.filter((item) => item.side === 'buy');
  const sellStrategies = STRATEGY_CATALOG.filter((item) => item.side === 'sell');
  const [openName, setOpenName] = useState<string | null>(null);

  const toggle = (name: string) => {
    setOpenName((current) => (current === name ? null : name));
  };

  const renderSection = (
    title: string,
    subtitle: string,
    items: typeof STRATEGY_CATALOG,
    side: 'buy' | 'sell',
  ) => (
    <section className="strategy-details-section">
      <div className="strategy-details-section-header">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <span className={`strategy-details-pill ${side}`}>{items.length} strategies</span>
      </div>
      <div className="strategy-toggle-list">
        {items.map((entry) => (
          <StrategyGuidePanel
            key={entry.name}
            entry={entry}
            open={openName === entry.name}
            onToggle={() => toggle(entry.name)}
          />
        ))}
      </div>
    </section>
  );

  return (
    <div className="strategy-details-page">
      <header className="strategy-details-hero">
        <h2>Strategy guide</h2>
        <p>
          Expand one strategy at a time. Each section below is collapsible — tested scenarios show exactly
          what the system does and what order (if any) is sent to TMS.
        </p>
        <p className="strategy-details-disclaimer">{STRATEGY_DISCLAIMER}</p>
      </header>

      {renderSection('Buy strategies', 'Entry rules verified by unit tests', buyStrategies, 'buy')}
      {renderSection('Sell strategies', 'Exit rules verified by unit tests', sellStrategies, 'sell')}
    </div>
  );
};

export default StrategyDetails;
