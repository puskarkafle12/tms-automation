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

const StockDetails: React.FC<StockDetailsProps> = ({ stock }) => {
  if (!stock) {
    return <p className="error-message">No stock details available</p>;
  }

  const formatDate = (dateArray: number[]) => {
    const [year, month, day, hour, minute, second] = dateArray;
    return `${day}-${month}-${year} ${hour}:${minute}:${second}`;
  };

  return (
    <div className="stock-details">
      <h3>Stock Details for {stock.symbol}</h3>
      <ul>
        <li><span className="data-name">Volume:</span> {stock.volume}</li>
        <li><span className="data-name">Last Traded Price (LTP):</span> {stock.ltp}</li>
        <li><span className="data-name">Percent Change:</span> {stock.percentChange}%</li>
        <li><span className="data-name">High:</span> {stock.high}</li>
        <li><span className="data-name">Low:</span> {stock.low}</li>
        <li><span className="data-name">Open:</span> {stock.open}</li>
        <li><span className="data-name">Last Traded Volume:</span> {stock.lastTradedVolume}</li>
        <li><span className="data-name">Last Traded Time:</span> {formatDate(stock.lastTradedTime)}</li>
        <li><span className="data-name">Change:</span> {stock.change}</li>
        <li><span className="data-name">Previous Close:</span> {stock.previousClose}</li>
      </ul>
    </div>
  );
};

export default StockDetails;
