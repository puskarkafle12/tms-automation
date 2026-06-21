import React, { useEffect, useMemo, useRef, useState } from 'react';
import './Dropdown.css';

export interface DropdownOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface DropdownProps {
  id?: string;
  label?: string;
  value: string;
  options: DropdownOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  hint?: string;
  className?: string;
}

const Dropdown: React.FC<DropdownProps> = ({
  id,
  label,
  value,
  options,
  onChange,
  placeholder = 'Select an option',
  disabled = false,
  hint,
  className = '',
}) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const selected = useMemo(
    () => options.find((option) => option.value === value) || null,
    [options, value],
  );

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, []);

  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  const handleSelect = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className={`custom-dropdown ${className}`.trim()}>
      {label ? <label className="custom-dropdown-label" htmlFor={id}>{label}</label> : null}
      <button
        id={id}
        type="button"
        className={`custom-dropdown-trigger${open ? ' open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={`custom-dropdown-value${selected ? '' : ' placeholder'}`}>
          {selected?.label || placeholder}
        </span>
        <span className="custom-dropdown-caret" aria-hidden="true" />
      </button>
      {hint ? <div className="custom-dropdown-hint">{hint}</div> : null}
      {open ? (
        <div className="custom-dropdown-menu" role="listbox" aria-label={label || placeholder}>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`custom-dropdown-option${option.value === value ? ' selected' : ''}`}
              role="option"
              aria-selected={option.value === value}
              disabled={option.disabled}
              onClick={() => handleSelect(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
};

export default Dropdown;
