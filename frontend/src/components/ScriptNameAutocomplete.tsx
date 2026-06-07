import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import './ScriptNameAutocomplete.css';

export interface ScriptOption {
  symbol: string;
  ltp?: number;
  percentChange?: number;
}

interface ScriptNameAutocompleteProps {
  id?: string;
  value: string;
  options: ScriptOption[];
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  maxResults?: number;
  onChange: (value: string) => void;
  onSelect: (option: ScriptOption) => void;
}

const highlightMatch = (text: string, query: string) => {
  if (!query.trim()) {
    return text;
  }

  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index === -1) {
    return text;
  }

  const before = text.slice(0, index);
  const match = text.slice(index, index + query.length);
  const after = text.slice(index + query.length);

  return (
    <>
      {before}
      <mark>{match}</mark>
      {after}
    </>
  );
};

const ScriptNameAutocomplete: React.FC<ScriptNameAutocompleteProps> = ({
  id,
  value,
  options,
  placeholder = 'Search script...',
  disabled = false,
  required = false,
  maxResults = 10,
  onChange,
  onSelect,
}) => {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const filteredOptions = useMemo(() => {
    const query = value.trim().toLowerCase();
    const matches = query
      ? options.filter((option) => option.symbol.toLowerCase().includes(query))
      : options;

    return matches.slice(0, maxResults);
  }, [options, value, maxResults]);

  useEffect(() => {
    setActiveIndex(0);
  }, [value, filteredOptions.length]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectOption = (option: ScriptOption) => {
    onSelect(option);
    setIsOpen(false);
    inputRef.current?.blur();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      setIsOpen(true);
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((prev) => (prev + 1) % Math.max(filteredOptions.length, 1));
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((prev) =>
        prev === 0 ? Math.max(filteredOptions.length - 1, 0) : prev - 1,
      );
      return;
    }

    if (event.key === 'Enter' && isOpen && filteredOptions.length > 0) {
      event.preventDefault();
      selectOption(filteredOptions[activeIndex]);
      return;
    }

    if (event.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const showDropdown = isOpen && !disabled;

  return (
    <div className="script-autocomplete" ref={rootRef}>
      <div className="script-autocomplete-input-wrap">
        <input
          ref={inputRef}
          id={id}
          type="text"
          className="input script-autocomplete-input"
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          role="combobox"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          onChange={(e) => {
            onChange(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
        />
        <span className={`script-autocomplete-chevron ${showDropdown ? 'open' : ''}`} aria-hidden="true">
          ▾
        </span>
      </div>

      {showDropdown && (
        <div className="script-autocomplete-dropdown">
          {filteredOptions.length > 0 ? (
            <>
              <ul id={listId} className="script-autocomplete-list" role="listbox">
                {filteredOptions.map((option, index) => {
                  const isPositive = (option.percentChange ?? 0) >= 0;
                  return (
                    <li key={option.symbol} role="option" aria-selected={index === activeIndex}>
                      <button
                        type="button"
                        className={`script-autocomplete-option ${index === activeIndex ? 'active' : ''}`}
                        onMouseEnter={() => setActiveIndex(index)}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => selectOption(option)}
                      >
                        <div className="script-autocomplete-option-main">
                          <span className="script-autocomplete-symbol">
                            {highlightMatch(option.symbol, value)}
                          </span>
                          <span className="script-autocomplete-meta">NEPSE script</span>
                        </div>
                        {option.ltp !== undefined && (
                          <div className="script-autocomplete-price">
                            <span className="script-autocomplete-ltp">Rs. {option.ltp}</span>
                            {option.percentChange !== undefined && (
                              <span className={`script-autocomplete-change ${isPositive ? 'positive' : 'negative'}`}>
                                {isPositive ? '+' : ''}{option.percentChange}%
                              </span>
                            )}
                          </div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {options.length > maxResults && (
                <div className="script-autocomplete-footer">
                  Showing {filteredOptions.length} of {options.length} scripts — keep typing to narrow down
                </div>
              )}
            </>
          ) : (
            <div className="script-autocomplete-empty">
              {value.trim() ? `No scripts matching "${value}"` : 'No scripts available for this client'}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ScriptNameAutocomplete;
