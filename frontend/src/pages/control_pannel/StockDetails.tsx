import React from 'react';
import './StockDetails.css';

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
}

const formatDate = (dateArray: number[]) => {
  const [year, month, day, hour, minute, second] = dateArray;
  return `${day}-${month}-${year} ${hour}:${minute}:${second}`;
};

const StockDetails: React.FC<StockDetailsProps> = ({ stock }) => {
  if (!stock) {
    return <p className="stock-details-empty">No stock details available.</p>;
  }

  const isPositive = stock.percentChange >= 0;

  const fields = [
    { label: 'LTP', value: stock.ltp },
    { label: 'Open', value: stock.open },
    { label: 'High', value: stock.high },
    { label: 'Low', value: stock.low },
    { label: 'Volume', value: stock.volume },
    { label: 'Prev. Close', value: stock.previousClose },
    { label: 'Change', value: stock.change },
    { label: 'Last Traded Vol.', value: stock.lastTradedVolume },
    { label: 'Last Traded', value: formatDate(stock.lastTradedTime) },
  ];

  return (
    <div className="stock-details">
      <div className="stock-details-header">
        <h3 className="stock-details-title">{stock.symbol}</h3>
        <span className={`stock-details-change ${isPositive ? 'positive' : 'negative'}`}>
          {isPositive ? '+' : ''}{stock.percentChange}%
        </span>
      </div>
      <div className="stock-details-grid">
        {fields.map((field) => (
          <div key={field.label} className="stock-details-item">
            <span className="stock-details-label">{field.label}</span>
            <span className="stock-details-value">{field.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default StockDetails;
