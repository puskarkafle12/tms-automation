import React, { useState } from 'react';
import './Table.css';

interface TableRow {
  [key: string]: any;
  color?: string; // Optional color property for row coloring
}

interface CommonTableProps {
  data: TableRow[];
  onAction?: (row: TableRow, actionType: string) => void;
  columns?: string[]; // Optional prop for specifying columns to display
}

const CommonTable: React.FC<CommonTableProps> = ({ data, onAction, columns }) => {
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
          <button onClick={() => onAction(row, 'Cancel')}>Cancel</button>
        </td>
      )}
      {onAction && row.hasOwnProperty('order_id') && (
        <td>
          <button onClick={() => onAction(row, 'Delete')}>Delete</button>
        </td>
      )}
    </>
  );

  // Format value for display
  const formatValue = (value: any) => {
    if (typeof value === 'object' && value !== null) {
      return JSON.stringify(value);
    }
    return value;
  };

  return (
    <div>
      {data.length === 0 ? (
        <p>No data available</p>
      ) : (
        <table className="common-table">
          <thead>
            <tr>
              {columnsToRender.map((column, index) => (
                <th key={index} onClick={() => handleSort(column)}>
                  {column}
                  {sortConfig && sortConfig.key === column ? (
                    sortConfig.direction === 'asc' ? ' 🔼' : ' 🔽'
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
                  <td key={colIndex}>{formatValue(row[column])}</td>
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
