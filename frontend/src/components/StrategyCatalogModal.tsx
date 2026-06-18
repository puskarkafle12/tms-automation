import React from 'react';
import '../pages/control_pannel/OrderLogs.css';
import '../pages/control_pannel/StrategyDetails.css';
import { getStrategyCatalogEntry } from '../lib/strategies/catalog';
import { formatStrategyLabel } from '../lib/strategies';
import StrategyGuidePanel from './StrategyGuidePanel';

interface Props {
  strategyName: string;
  side?: 'buy' | 'sell';
  onClose: () => void;
}

const StrategyCatalogModal: React.FC<Props> = ({ strategyName, side = 'buy', onClose }) => {
  const label = formatStrategyLabel(strategyName, side);
  const entry = getStrategyCatalogEntry(label, side);

  return (
    <div className="strategy-details-backdrop" role="presentation" onClick={onClose}>
      <div
        className="strategy-details-modal strategy-catalog-modal strategy-guide-modal"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="strategy-details-header">
          <div>
            <h3>{entry?.name || 'Strategy guide'}</h3>
            <p>{entry?.purpose || label}</p>
          </div>
          <button type="button" className="strategy-details-close" onClick={onClose} aria-label="Close strategy details">
            ×
          </button>
        </div>

        {entry ? (
          <StrategyGuidePanel entry={entry} variant="flat" />
        ) : (
          <p>No guide found for this strategy.</p>
        )}
      </div>
    </div>
  );
};

export default StrategyCatalogModal;
