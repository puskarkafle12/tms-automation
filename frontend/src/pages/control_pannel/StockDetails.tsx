import React from 'react';
import './StockDetails.css';
import NepseAlphaSymbolLink from '../../components/NepseAlphaSymbolLink';

interface StockDetailsProps {
  stock: {
    symbol: string;
    volume: number;
    ltp: number;
    percentChange: number;
    high: number;
    low: number;
    open: number;
    lastTradedVolume: number;
    lastTradedTime: number[];
    change: number;
    previousClose: number;
  } | null;
  orderType?: 'buy' | 'sell';
  latestLtp?: number | null;
  quoteLoading?: boolean;
  quoteError?: string;
  topBuy?: QuoteLevel[];
  topSell?: QuoteLevel[];
  holdingQty?: number | null;
  holdingLabel?: string;
  holdingLoading?: boolean;
  holdingError?: string;
  onFillFromHolding?: () => void;
}

interface QuoteLevel {
  sequenceId?: number;
  quantity?: number;
  price?: number;
  totalOrders?: number;
}

const formatDate = (dateArray?: number[]) => {
  if (!Array.isArray(dateArray) || dateArray.length < 6) {
    return '-';
  }
  const [year, month, day, hour, minute, second] = dateArray;
  return `${day}-${month}-${year} ${hour}:${minute}:${second}`;
};

const formatNumber = (value?: number | null) =>
  Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-NP') : '-';

const StockDetails: React.FC<StockDetailsProps> = ({
  stock,
  orderType = 'buy',
  latestLtp = null,
  quoteLoading = false,
  quoteError = '',
  topBuy = [],
  topSell = [],
  holdingQty = null,
  holdingLabel = '',
  holdingLoading = false,
  holdingError = '',
  onFillFromHolding,
}) => {
  if (!stock) {
    return <p className="stock-details-empty">No stock details available.</p>;
  }

  const percentChange = Number(stock.percentChange || 0);
  const changeTone = percentChange > 0 ? 'positive' : percentChange < 0 ? 'negative' : 'neutral';
  const displayLtp = quoteLoading
    ? 'Loading...'
    : latestLtp && latestLtp > 0
      ? formatNumber(latestLtp)
      : stock.ltp
        ? formatNumber(stock.ltp)
        : '-';

  const fields = [
    { label: 'LTP', value: displayLtp },
    { label: 'Open', value: formatNumber(stock.open) },
    { label: 'High', value: formatNumber(stock.high) },
    { label: 'Low', value: formatNumber(stock.low) },
    { label: 'Volume', value: formatNumber(stock.volume) },
    { label: 'Prev. Close', value: formatNumber(stock.previousClose) },
    { label: 'Change', value: formatNumber(stock.change) },
    { label: 'Last Traded', value: formatDate(stock.lastTradedTime) },
  ];

  const holdingDisplay = holdingLoading
    ? 'Checking...'
    : holdingQty && holdingQty > 0
      ? formatNumber(holdingQty)
      : '-';

  return (
    <div className="stock-details">
      <div className="stock-details-header">
        <div>
          <span className="stock-details-eyebrow">Market Snapshot</span>
          <h3 className="stock-details-title">
            <NepseAlphaSymbolLink symbol={stock.symbol} />
          </h3>
        </div>
        <span className={`stock-details-change ${changeTone}`}>
          {percentChange > 0 ? '+' : ''}{percentChange}%
        </span>
      </div>
      <div className="stock-details-grid">
        {fields.map((field) => (
          <div key={field.label} className="stock-details-item">
            <span className="stock-details-label">{field.label}</span>
            <span className="stock-details-value">{field.value}</span>
          </div>
        ))}
        {orderType === 'sell' && (
          <div
            className={`stock-details-item stock-details-item-action ${
              holdingQty && holdingQty > 0 ? 'available' : 'missing'
            }`}
          >
            <span className="stock-details-label">Holding Qty</span>
            <div className="stock-details-holding-row">
              <span className="stock-details-value">{holdingDisplay}</span>
              <button
                type="button"
                className="stock-details-action-value"
                onClick={onFillFromHolding}
                disabled={!holdingQty || holdingQty <= 0 || holdingLoading}
                title={holdingQty ? 'Use full holding quantity' : 'No holding quantity available'}
              >
                Max
              </button>
            </div>
            {holdingLabel && <span className="stock-details-hint">{holdingLabel}</span>}
          </div>
        )}
      </div>
      {quoteError && <p className="stock-details-error">{quoteError}</p>}
      {orderType === 'sell' && holdingError && <p className="stock-details-error">{holdingError}</p>}
      <div className="stock-depth-grid">
        <MarketDepthTable title="Top Buy Orders" rows={topBuy} />
        <MarketDepthTable title="Top Sell Orders" rows={topSell} />
      </div>
    </div>
  );
};

const MarketDepthTable: React.FC<{ title: string; rows: QuoteLevel[] }> = ({ title, rows }) => {
  const activeRows = rows.filter((row) => Number(row.price || 0) > 0 || Number(row.quantity || 0) > 0);

  return (
    <div className="stock-depth-card">
      <h4>{title}</h4>
      {activeRows.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Price</th>
              <th>Qty</th>
              <th>Orders</th>
            </tr>
          </thead>
          <tbody>
            {activeRows.map((row, index) => (
              <tr key={`${title}-${row.sequenceId ?? index}`}>
                <td>{row.price ? formatNumber(Number(row.price)) : '-'}</td>
                <td>{row.quantity ? formatNumber(Number(row.quantity)) : '-'}</td>
                <td>{row.totalOrders ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>Market depth unavailable</p>
      )}
    </div>
  );
};

export default StockDetails;
