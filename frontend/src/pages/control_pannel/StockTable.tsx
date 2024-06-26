import React, { useEffect, useState } from 'react';
import axios from 'axios';
import CommonTable from '../../components/Table/Table';

interface StockData {
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
  color?: string;
}

const StockTable: React.FC = () => {
  const [stockData, setStockData] = useState<StockData[]>([]);
  const apiUrl = 'http://localhost:8000/get_script_details?client_id=PK479690';

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get(apiUrl);
        const data = response.data.payload.data.map((stock: StockData) => ({
          ...stock,
          color: stock.percentChange > 0 ? 'lightgreen' : stock.percentChange < 0 ? 'red' : 'lightyellow'
        }));
        setStockData(data);
      } catch (error) {
        console.error('Error fetching stock data:', error);
      }
    };
    fetchData();
  }, []);

  return (
    <div className="stock-table-container">
      <h1>Live Market:</h1>
      <CommonTable
        data={stockData}
        columns={['symbol', 'volume', 'ltp', 'percentChange', 'high', 'low', 'open', 'lastTradedVolume', 'lastTradedTime', 'change', 'previousClose']}
      />
    </div>
  );
};

export default StockTable;
