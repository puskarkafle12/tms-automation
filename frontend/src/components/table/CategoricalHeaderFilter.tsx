import React, { useEffect, useMemo, useRef, useState } from 'react';
import './CategoricalHeaderFilter.css';

type Row = Record<string, any>;

const CATEGORICAL_KEY = /(symbol|status|signal|sector|strategy|preset|category|family|type|side|reason|result|name|market|source|state|action)/i;
const NUMERIC_KEY = /(price|ltp|volume|qty|quantity|amount|value|profit|loss|return|rate|pct|percent|score|trades|count|days|age|holding|drawdown|sharpe|ratio|capital|equity|fee|charge|tax|rank|id$)/i;
const DATE_VALUE = /^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/;
const NUMERIC_VALUE = /^-?[\d,]+(?:\.\d+)?%?$/;

const rawFilterValue = (value: unknown): string | null => {
  if (value == null || value === '' || typeof value === 'object') return null;
  return String(value).trim();
};

export const uniqueCategoricalValues = (rows: Row[], key: string): string[] => (
  Array.from(new Set(rows.map((row) => rawFilterValue(row[key])).filter(Boolean) as string[]))
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' }))
);

export const isCategoricalColumn = (rows: Row[], key: string): boolean => {
  if (CATEGORICAL_KEY.test(key)) return true;
  if (NUMERIC_KEY.test(key)) return false;
  const values = uniqueCategoricalValues(rows, key);
  if (!values.length || values.every((value) => DATE_VALUE.test(value))) return false;
  return !values.every((value) => NUMERIC_VALUE.test(value.replace(/\s/g, '')));
};

type Props = {
  label: string;
  values: string[];
  selectedValue?: string;
  onChange: (value: string) => void;
  disabled?: boolean;
};

const CategoricalHeaderFilter: React.FC<Props> = ({
  label,
  values,
  selectedValue = '',
  onChange,
  disabled = false,
}) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const filteredValues = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return needle ? values.filter((value) => value.toLowerCase().includes(needle)) : values;
  }, [search, values]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') setOpen(false);
        return;
      }
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);

  const choose = (value: string) => {
    onChange(value);
    setOpen(false);
    setSearch('');
  };

  return (
    <div className="categorical-header-filter" ref={rootRef}>
      <button
        type="button"
        className={`categorical-header-trigger${selectedValue ? ' active' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`Filter ${label} by an exact value`}
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((current) => !current);
        }}
      >
        <span>{label}</span>
        <i aria-hidden="true">▾</i>
      </button>
      {open && (
        <div className="categorical-header-menu" role="listbox" aria-label={`Filter ${label}`}>
          <header>
            <b>{label}</b>
            {selectedValue && <button type="button" onClick={() => choose('')}>Clear</button>}
          </header>
          {values.length > 7 && (
            <input
              autoFocus
              type="search"
              value={search}
              placeholder="Search values…"
              aria-label={`Search ${label} values`}
              onChange={(event) => setSearch(event.target.value)}
              onClick={(event) => event.stopPropagation()}
            />
          )}
          <div className="categorical-header-options">
            <button type="button" className={!selectedValue ? 'selected' : ''} onClick={() => choose('')}>
              <span>All</span><small>{values.length} values</small>
            </button>
            {filteredValues.map((value) => (
              <button
                type="button"
                key={value}
                className={selectedValue === value ? 'selected' : ''}
                role="option"
                aria-selected={selectedValue === value}
                onClick={() => choose(value)}
              >
                <span>{value.replaceAll('_', ' ')}</span>
                {selectedValue === value && <i aria-hidden="true">✓</i>}
              </button>
            ))}
            {!filteredValues.length && <p>No matching values</p>}
          </div>
        </div>
      )}
    </div>
  );
};

export default CategoricalHeaderFilter;
