import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import CommonTable from '../../components/table/Table';
import { buildNepseAlphaChartUrl } from '../../lib/nepseAlpha';

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
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState(0);

  const apiUrl = localStorage.getItem('apiUrl') || '';
  const clientIds: string[] = JSON.parse(localStorage.getItem('client_ids') || '[]');

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        if (clientIds.length === 0) {
          if (!cancelled) {
            setStockData([]);
            setTotalCount(0);
          }
          return;
        }
        setLoading(true);
        const response = await axios.get(`${apiUrl}/get_script_details?client_id=${clientIds[0]}`);
        const payload = response.data;
        const rows = Array.isArray(payload)
          ? payload
          : Array.isArray(payload?.payload?.data)
            ? payload.payload.data
            : Array.isArray(payload?.data)
              ? payload.data
              : Array.isArray(payload?.result)
                ? payload.result
                : [];
        const data = rows.map((stock: StockData) => ({
          ...stock,
          color: stock.percentChange > 0 ? 'lightgreen' : stock.percentChange < 0 ? 'red' : 'lightyellow'
        }));
        if (!cancelled) {
          setStockData(data);
          setTotalCount(data.length);
        }
      } catch (error) {
        console.error('Error fetching stock data:', error);
        if (!cancelled) {
          setStockData([]);
          setTotalCount(0);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, clientIds]);

  const columns = useMemo(
    () => ['symbol', 'volume', 'ltp', 'percentChange', 'high', 'low', 'open', 'lastTradedVolume', 'lastTradedTime', 'previousClose'],
    [],
  );

  return (
    <div className="stock-table-container">
      <div className="stock-table-header">
        <h1>Live Market</h1>
        <span className="stock-table-count">{loading ? 'Loading…' : `${totalCount} stocks`}</span>
      </div>
      <CommonTable
        data={stockData}
        columns={columns}
        columnLinks={{
          symbol: (row) => buildNepseAlphaChartUrl(String(row.symbol || '')),
        }}
        emptyMessage={loading ? 'Loading live market data…' : 'No live market data available.'}
      />
    </div>
  );
};

export default StockTable;
