import React, { useState } from 'react';
import './Table.css';

interface TableRow {
  [key: string]: any;
  color?: string; // Optional color property for row coloring
}

interface CommonTableProps {
  data: TableRow[];
  onAction?: (row: TableRow, actionType: string) => void;
  columns?: string[];
  emptyMessage?: string;
}

const formatColumnLabel = (column: string) =>
  column
    .replace(/([A-Z])/g, ' $1')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();

const CommonTable: React.FC<CommonTableProps> = ({ data, onAction, columns, emptyMessage }) => {
  const [sortConfig, setSortConfig] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null);

  // Sort data based on the sort configuration
  const sortedData = React.useMemo(() => {
    if (!sortConfig) return data;
    const sortedArray = [...data].sort((a, b) => {
      if (a[sortConfig.key] < b[sortConfig.key]) return sortConfig.direction === 'asc' ? -1 : 1;
      if (a[sortConfig.key] > b[sortConfig.key]) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
    return sortedArray;
  }, [data, sortConfig]);

  // Function to handle header click for sorting
  const handleSort = (key: string) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig && sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  // Columns to render, defaulting to keys from the first data object
  const columnsToRender = columns ? columns : Object.keys(data[0] || {});

  // Render actions for each row
  const renderActions = (row: TableRow) => (
    <>
      {onAction && row.hasOwnProperty('exchangeOrderId') && (
        <td>
          <button type="button" className="table-action-btn table-action-danger" onClick={() => onAction(row, 'Cancel')}>
            Cancel
          </button>
        </td>
      )}
      {onAction && row.hasOwnProperty('order_id') && (
        <td>
          <button type="button" className="table-action-btn table-action-danger" onClick={() => onAction(row, 'Delete')}>
            Delete
          </button>
        </td>
      )}
    </>
  );

  // Format value for display
  const formatValue = (value: any) => {
    if (React.isValidElement(value)) {
      return value;
    }
    if (typeof value === 'object' && value !== null) {
      return JSON.stringify(value);
    }
    return value == null || value === '' ? '-' : value;
  };

  return (
    <div className="common-table-wrap">
      {data.length === 0 ? (
        <div className="common-table-empty">
          <span className="common-table-empty-icon">📭</span>
          <p>{emptyMessage || 'No data available'}</p>
        </div>
      ) : (
        <table className="common-table">
          <thead>
            <tr>
              {columnsToRender.map((column, index) => (
                <th key={index} onClick={() => handleSort(column)}>
                  {formatColumnLabel(column)}
                  {sortConfig && sortConfig.key === column ? (
                    <span className="common-table-sort">{sortConfig.direction === 'asc' ? ' ↑' : ' ↓'}</span>
                  ) : null}
                </th>
              ))}
              {onAction && <th>Action</th>}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row, rowIndex) => (
              <tr key={rowIndex} style={{ backgroundColor: row.color }}>
                {columnsToRender.map((column, colIndex) => (
                  <td
                    key={colIndex}
                    className={column === 'status' && row.liveStatus ? 'table-status-live' : undefined}
                  >
                    {formatValue(row[column])}
                  </td>
                ))}
                {onAction && renderActions(row)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default CommonTable;
