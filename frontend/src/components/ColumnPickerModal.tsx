import React, { useEffect, useState } from "react";
import "./ColumnPickerModal.css";

export type ColumnPickerItem = {
  key: string;
  label: string;
  locked?: boolean;
};

type Props = {
  open: boolean;
  title?: string;
  subtitle?: string;
  columns: ColumnPickerItem[];
  selectedKeys: string[];
  defaultKeys: string[];
  onClose: () => void;
  onChange: (keys: string[]) => void;
};

const normalizeOrder = (
  keys: string[],
  columns: ColumnPickerItem[],
  fallback: string[],
) => {
  const known = new Set(columns.map((column) => column.key));
  const locked = columns.filter((column) => column.locked).map((column) => column.key);
  const ordered = keys
    .map(String)
    .filter((key, index, all) => known.has(key) && all.indexOf(key) === index && !locked.includes(key));
  const next = [...locked, ...ordered];
  return next.length ? next : [...fallback];
};

const ColumnPickerModal: React.FC<Props> = ({
  open,
  title = "Table columns",
  subtitle = "Show, hide, and drag columns into the order you want.",
  columns,
  selectedKeys,
  defaultKeys,
  onClose,
  onChange,
}) => {
  const [draggingKey, setDraggingKey] = useState<string | null>(null);
  const [dropKey, setDropKey] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const selected = new Set(normalizeOrder(selectedKeys, columns, defaultKeys));
  const orderedColumns = (() => {
    const byKey = new Map(columns.map((column) => [column.key, column]));
    const chosen = normalizeOrder(selectedKeys, columns, defaultKeys)
      .map((key) => byKey.get(key))
      .filter(Boolean) as ColumnPickerItem[];
    const remaining = columns.filter((column) => !selected.has(column.key));
    return [...chosen, ...remaining];
  })();

  const setKeys = (keys: string[]) => onChange(normalizeOrder(keys, columns, defaultKeys));

  const toggle = (key: string) => {
    const column = columns.find((item) => item.key === key);
    if (!column || column.locked) return;
    if (selected.has(key)) {
      setKeys(selectedKeys.filter((item) => item !== key));
      return;
    }
    setKeys([...selectedKeys, key]);
  };

  const moveRelative = (fromKey: string, toKey: string) => {
    const fromColumn = columns.find((item) => item.key === fromKey);
    const toColumn = columns.find((item) => item.key === toKey);
    if (!fromColumn || !toColumn || fromColumn.locked || toColumn.locked || fromKey === toKey) return;
    const working = normalizeOrder(selectedKeys, columns, defaultKeys);
    if (!working.includes(fromKey)) working.push(fromKey);
    if (!working.includes(toKey) && selected.has(toKey)) working.push(toKey);
    const fromIndex = working.indexOf(fromKey);
    const toIndex = working.indexOf(toKey);
    if (fromIndex < 0 || toIndex < 0) return;
    working.splice(fromIndex, 1);
    working.splice(toIndex, 0, fromKey);
    setKeys(working);
  };

  const moveByOffset = (key: string, offset: number) => {
    const column = columns.find((item) => item.key === key);
    if (!column || column.locked) return;
    const working = normalizeOrder(selectedKeys, columns, defaultKeys);
    if (!working.includes(key)) return;
    const fromIndex = working.indexOf(key);
    const toIndex = fromIndex + offset;
    if (toIndex < 0 || toIndex >= working.length) return;
    const target = working[toIndex];
    const targetColumn = columns.find((item) => item.key === target);
    if (targetColumn?.locked) return;
    working.splice(fromIndex, 1);
    working.splice(toIndex, 0, key);
    setKeys(working);
  };

  return (
    <div
      className="column-picker-backdrop"
      role="presentation"
      onClick={onClose}
    >
      <section
        className="column-picker-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="column-picker-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>Customize table</span>
            <h2 id="column-picker-title">{title}</h2>
            <p>{subtitle}</p>
          </div>
          <button
            type="button"
            className="column-picker-close"
            aria-label="Close column picker"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="column-picker-toolbar">
          <span>
            <b>{selected.size}</b> of {columns.length} columns · drag the handle to reorder
          </span>
          <div>
            <button type="button" onClick={() => setKeys(defaultKeys)}>
              Reset default
            </button>
            <button
              type="button"
              onClick={() => setKeys(columns.map((column) => column.key))}
            >
              Show all
            </button>
          </div>
        </div>

        <div className="column-picker-list" role="list">
          {orderedColumns.map((column) => {
            const checked = selected.has(column.key);
            const isDragging = draggingKey === column.key;
            const isDropTarget = dropKey === column.key && draggingKey !== column.key;
            return (
              <div
                key={column.key}
                role="listitem"
                className={[
                  "column-picker-row",
                  checked ? "is-visible" : "is-hidden",
                  column.locked ? "is-locked" : "",
                  isDragging ? "is-dragging" : "",
                  isDropTarget ? "is-drop-target" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                draggable={!column.locked}
                onDragStart={(event) => {
                  if (column.locked) return;
                  setDraggingKey(column.key);
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", column.key);
                }}
                onDragOver={(event) => {
                  if (column.locked || !draggingKey || draggingKey === column.key) return;
                  event.preventDefault();
                  setDropKey(column.key);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  const fromKey = event.dataTransfer.getData("text/plain") || draggingKey;
                  if (fromKey) moveRelative(fromKey, column.key);
                  setDraggingKey(null);
                  setDropKey(null);
                }}
                onDragEnd={() => {
                  setDraggingKey(null);
                  setDropKey(null);
                }}
              >
                <span
                  className="column-picker-handle"
                  title={column.locked ? "Pinned column" : "Drag to reorder"}
                  aria-hidden="true"
                >
                  ⋮⋮
                </span>
                <label>
                  <input
                    type="checkbox"
                    checked={checked || Boolean(column.locked)}
                    disabled={Boolean(column.locked)}
                    onChange={() => toggle(column.key)}
                  />
                  <span>{column.label}</span>
                </label>
                <div className="column-picker-move">
                  <button
                    type="button"
                    aria-label={`Move ${column.label} up`}
                    disabled={Boolean(column.locked) || !checked}
                    onClick={() => moveByOffset(column.key, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label={`Move ${column.label} down`}
                    disabled={Boolean(column.locked) || !checked}
                    onClick={() => moveByOffset(column.key, 1)}
                  >
                    ↓
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <footer>
          <span>
            Press <kbd>Esc</kbd> or use × to close. Order is saved for this login.
          </span>
          <button type="button" onClick={onClose}>
            Done
          </button>
        </footer>
      </section>
    </div>
  );
};

export default ColumnPickerModal;
