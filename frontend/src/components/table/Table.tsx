import React from 'react';
import './Table.css';

interface TableRow {
  [key: string]: any;
  color?: string; // Add optional color property to TableRow interface
}

interface CommonTableProps {
  data: TableRow[];
  onAction?: (row: TableRow, actionType: string) => void;
  columns?: string[]; // Optional prop for specifying columns to display
}

const CommonTable: React.FC<CommonTableProps> = ({ data, onAction, columns }) => {
  if (data.length === 0) {
    return <p>No data available</p>;
  }

  const columnsToRender = columns ? columns : Object.keys(data[0]);

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

  const formatValue = (value: any) => {
    if (typeof value === 'object' && value !== null) {
      return JSON.stringify(value);
    }
    return value;
  };

  return (
    <table className="common-table">
      <thead>
        <tr>
          {columnsToRender.map((column, index) => (
            <th key={index}>{column}</th>
          ))}
          {onAction && <th>Action</th>}
        </tr>
      </thead>
      <tbody>
        {data.map((row, rowIndex) => (
          <tr key={rowIndex} style={{ backgroundColor: row.color }}>
            {columnsToRender.map((column, colIndex) => (
              <td key={colIndex}>{formatValue(row[column])}</td>
            ))}
            {onAction && renderActions(row)}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

export default CommonTable;
