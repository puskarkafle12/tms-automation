import React, { useState } from 'react';
import CategoricalHeaderFilter, {
  isCategoricalColumn,
  uniqueCategoricalValues,
} from './CategoricalHeaderFilter';
import './Table.css';

interface TableRow {
  [key: string]: any;
  color?: string; // Optional color property for row coloring
  sortValues?: Record<string, string | number | null | undefined>;
}

interface CommonTableProps {
  data: TableRow[];
  onAction?: (row: TableRow, actionType: string) => void;
  columns?: string[];
  columnLabels?: Record<string, string>;
  emptyMessage?: string;
  columnLinks?: Record<string, (row: TableRow) => string | undefined>;
  selectable?: boolean;
  selectedRowIds?: Set<string | number>;
  rowIdKey?: string;
  onToggleRow?: (rowId: string | number, selected: boolean) => void;
  onToggleAll?: (selected: boolean, rowIds: Array<string | number>) => void;
}

const COLUMN_LABEL_OVERRIDES: Record<string, string> = {
  trigger_price: 'Est. Trigger',
  order_type: 'Side',
  created_at: 'Created',
  strategy_type: 'Strategy',
  averageBuyPrice: 'Buy Price',
  buyPrice: 'Buy Price',
  sellPrice: 'Sell Price',
  buyValue: 'Buy Value',
  valueAsOfLTP: 'Current Value',
  profitLoss: 'P/L',
  dailyGain: 'Daily Gain',
  totalProfit: 'Total Profit',
  percentChange: '%',
  holdingDays: 'Holding Days',
  dateRange: 'Buy - Sell',
};

const formatColumnLabel = (column: string, columnLabels?: Record<string, string>) =>
  columnLabels?.[column]
  || COLUMN_LABEL_OVERRIDES[column]
  || column
    .replace(/([A-Z])/g, ' $1')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();

const rowToneClass = (color?: string) => {
  const normalized = String(color || '').trim().toLowerCase();
  if (!normalized) return undefined;
  if (normalized.includes('green')) return 'common-table-row-profit';
  if (normalized.includes('red')) return 'common-table-row-loss';
  if (normalized.includes('yellow')) return 'common-table-row-flat';
  return undefined;
};

const normalizeSortValue = (value: unknown): string | number => {
  if (value == null || value === '') return '';
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (React.isValidElement(value)) return String((value.props as { children?: React.ReactNode })?.children ?? '');
  if (typeof value === 'object') return JSON.stringify(value);
  const text = String(value).trim();
  const numeric = Number(text.replace(/,/g, '').replace(/[^\d.-]/g, ''));
  return Number.isFinite(numeric) && text.match(/^-?[\d,]+(\.\d+)?$/) ? numeric : text.toLowerCase();
};

const CommonTable: React.FC<CommonTableProps> = ({
  data,
  onAction,
  columns,
  columnLabels,
  emptyMessage,
  columnLinks,
  selectable = false,
  selectedRowIds,
  rowIdKey = 'order_id',
  onToggleRow,
  onToggleAll,
}) => {
  const [sortConfig, setSortConfig] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null);
  const [categoricalFilters, setCategoricalFilters] = useState<Record<string, string>>({});

  const filteredData = React.useMemo(() => data.filter((row) => (
    Object.entries(categoricalFilters).every(([key, selected]) => (
      !selected || String(row[key] ?? '') === selected
    ))
  )), [categoricalFilters, data]);

  // Sort data based on the sort configuration
  const sortedData = React.useMemo(() => {
    if (!sortConfig) return filteredData;
    const sortedArray = [...filteredData].sort((a, b) => {
      const aValue = a.sortValues?.[sortConfig.key] ?? a[sortConfig.key];
      const bValue = b.sortValues?.[sortConfig.key] ?? b[sortConfig.key];
      const left = normalizeSortValue(aValue);
      const right = normalizeSortValue(bValue);
      if (left < right) return sortConfig.direction === 'asc' ? -1 : 1;
      if (left > right) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
    return sortedArray;
  }, [filteredData, sortConfig]);

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

  const visibleRowIds = React.useMemo(
    () => sortedData
      .map((row) => row[rowIdKey])
      .filter((value) => value != null && value !== '') as Array<string | number>,
    [rowIdKey, sortedData],
  );

  const allVisibleSelected = selectable
    && visibleRowIds.length > 0
    && visibleRowIds.every((id) => selectedRowIds?.has(id));

  const someVisibleSelected = selectable
    && visibleRowIds.some((id) => selectedRowIds?.has(id));

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
          <div className="table-action-group">
            {row.canEdit !== false && (
              <button type="button" className="table-action-btn table-action-edit" onClick={() => onAction(row, 'Edit')}>
                Edit
              </button>
            )}
            <button type="button" className="table-action-btn table-action-danger" onClick={() => onAction(row, 'Delete')}>
              Delete
            </button>
          </div>
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

  const renderCell = (row: TableRow, column: string) => {
    const value = row[column];
    const href = columnLinks?.[column]?.(row);
    if (href && value != null && value !== '') {
      return (
        <a className="common-table-link" href={href} target="_blank" rel="noopener noreferrer">
          {String(value)}
        </a>
      );
    }
    return formatValue(value);
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
              {selectable ? (
                <th className="common-table-select-col">
                  <input
                    type="checkbox"
                    aria-label="Select all rows"
                    checked={allVisibleSelected}
                    ref={(input) => {
                      if (input) {
                        input.indeterminate = !allVisibleSelected && someVisibleSelected;
                      }
                    }}
                    onChange={(event) => onToggleAll?.(event.target.checked, visibleRowIds)}
                  />
                </th>
              ) : null}
              {columnsToRender.map((column, index) => {
                const label = formatColumnLabel(column, columnLabels);
                const categorical = isCategoricalColumn(data, column);
                return (
                  <th key={index}>
                    {categorical ? (
                      <CategoricalHeaderFilter
                        label={label}
                        values={uniqueCategoricalValues(data, column)}
                        selectedValue={categoricalFilters[column]}
                        onChange={(value) => setCategoricalFilters((current) => ({ ...current, [column]: value }))}
                      />
                    ) : (
                      <button type="button" className="common-table-sort-trigger" onClick={() => handleSort(column)}>
                        {label}
                        {sortConfig && sortConfig.key === column ? (
                          <span className="common-table-sort">{sortConfig.direction === 'asc' ? ' ↑' : ' ↓'}</span>
                        ) : null}
                      </button>
                    )}
                  </th>
                );
              })}
              {onAction && <th>Action</th>}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row, rowIndex) => (
              <tr key={rowIndex} className={rowToneClass(row.color)}>
                {selectable ? (
                  <td className="common-table-select-col">
                    <input
                      type="checkbox"
                      aria-label={`Select row ${row[rowIdKey]}`}
                      checked={selectedRowIds?.has(row[rowIdKey]) ?? false}
                      onChange={(event) => onToggleRow?.(row[rowIdKey], event.target.checked)}
                    />
                  </td>
                ) : null}
                {columnsToRender.map((column, colIndex) => (
                  <td
                    key={colIndex}
                    className={column === 'status' && row.liveStatus ? 'table-status-live' : undefined}
                  >
                    {renderCell(row, column)}
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
