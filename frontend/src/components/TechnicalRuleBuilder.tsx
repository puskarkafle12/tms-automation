import React, { useMemo, useState } from 'react';
import './CustomQueryEditor.css';

export interface TechnicalCondition {
  field: string;
  operator: string;
  value: string;
}

export interface TechnicalStockRule {
  id: string;
  name: string;
  targetType: 'single' | 'multiple';
  symbols: string;
  orderMode: string;
  orderValue: string;
  confirmScans: string;
  logic: 'AND' | 'OR';
  conditions: TechnicalCondition[];
}

interface Props {
  side: 'buy' | 'sell';
  formSymbol?: string;
  onQueryChange: (queryText: string) => void;
}

const FIELD_OPTIONS = [
  { value: 'technical_rsi_14', label: 'RSI 14' },
  { value: 'technical_macd', label: 'MACD' },
  { value: 'ltp', label: 'LTP' },
  { value: 'fundamental_pbv', label: 'PBV' },
  { value: 'technical_volume_trend', label: 'Volume Trend' },
];

const OPERATOR_OPTIONS = [
  { value: '<', label: 'Less Than' },
  { value: '>', label: 'Greater Than' },
  { value: '=', label: 'Equals' },
  { value: 'CONSECUTIVE_DROPS', label: 'Consecutive Drops' },
  { value: 'CONSECUTIVE_RISES', label: 'Consecutive Rises' },
  { value: 'CROSSES_ABOVE', label: 'Crosses Above' },
  { value: 'CROSSES_BELOW', label: 'Crosses Below' },
  { value: 'REMAINS_ABOVE', label: 'Remains Above' },
  { value: 'REMAINS_BELOW', label: 'Remains Below' },
];

const makeRule = (side: 'buy' | 'sell', formSymbol?: string): TechnicalStockRule => ({
  id: `${Date.now()}-${Math.random()}`,
  name: `${formSymbol || 'CZBIL'} Rule`,
  targetType: 'single',
  symbols: formSymbol || 'CZBIL',
  orderMode: side === 'buy' ? 'QUANTITY' : 'PERCENT_OF_HOLDING',
  orderValue: '100',
  confirmScans: '2',
  logic: 'AND',
  conditions: [{ field: 'technical_rsi_14', operator: '<', value: '70' }],
});

const buildQuery = (side: 'buy' | 'sell', rules: TechnicalStockRule[]) => {
  const lines = [
    'STRATEGY_VERSION 1',
    `SIDE ${side.toUpperCase()}`,
    '',
  ];
  for (const rule of rules) {
    const symbols = rule.symbols.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean);
    const target = symbols.length > 1
      ? `FOR SYMBOL IN (${symbols.map((symbol) => `"${symbol}"`).join(', ')})`
      : `FOR SYMBOL "${symbols[0] || 'CZBIL'}"`;
    lines.push(`RULE "${rule.name}" ${target} {`);
    lines.push('    WHEN');
    const rendered = rule.conditions.map((condition, index) => {
      const prefix = index === 0 ? '         ' : `         ${rule.logic} `;
      if (condition.operator === 'CONSECUTIVE_DROPS') {
        return `${prefix}CONSECUTIVE_DROPS(${condition.field}, count=${condition.value || '2'})`;
      }
      if (condition.operator === 'CONSECUTIVE_RISES') {
        return `${prefix}CONSECUTIVE_RISES(${condition.field}, count=${condition.value || '2'})`;
      }
      if (condition.operator === 'CROSSES_ABOVE') {
        return `${prefix}CROSSES_ABOVE(${condition.field}, ${condition.value || '0'})`;
      }
      if (condition.operator === 'CROSSES_BELOW') {
        return `${prefix}CROSSES_BELOW(${condition.field}, ${condition.value || '0'})`;
      }
      if (condition.operator === 'REMAINS_ABOVE') {
        const [threshold = '0', scans = '2'] = condition.value.split(',');
        return `${prefix}REMAINS_ABOVE(${condition.field}, value=${threshold.trim()}, scans=${scans.trim()})`;
      }
      if (condition.operator === 'REMAINS_BELOW') {
        const [threshold = '0', scans = '2'] = condition.value.split(',');
        return `${prefix}REMAINS_BELOW(${condition.field}, value=${threshold.trim()}, scans=${scans.trim()})`;
      }
      const rhs = condition.field === 'technical_macd' ? `"${condition.value}"` : condition.value;
      return `${prefix}${condition.field} ${condition.operator} ${rhs}`;
    });
    lines.push(...rendered);
    lines.push('');
    lines.push(`    ORDER ${rule.orderMode} ${rule.orderValue}`);
    lines.push('    MAX_SLIPPAGE_PCT 1');
    if (Number(rule.confirmScans) > 0) {
      lines.push(`    CONFIRM TRUE_FOR ${Number(rule.confirmScans)} SCANS`);
    }
    lines.push('    TRIGGER ON_CROSS');
    lines.push('    EXECUTE ONCE PER SYMBOL');
    lines.push('}');
    lines.push('');
  }
  return `${lines.join('\n').trim()}\n`;
};

const TechnicalRuleBuilder: React.FC<Props> = ({ side, formSymbol, onQueryChange }) => {
  const [rules, setRules] = useState<TechnicalStockRule[]>([makeRule(side, formSymbol)]);

  const queryText = useMemo(() => buildQuery(side, rules), [side, rules]);

  React.useEffect(() => {
    onQueryChange(queryText);
  }, [queryText, onQueryChange]);

  const updateRule = (id: string, patch: Partial<TechnicalStockRule>) => {
    setRules((current) => current.map((rule) => (rule.id === id ? { ...rule, ...patch } : rule)));
  };

  const addRule = () => setRules((current) => [...current, makeRule(side, formSymbol)]);
  const duplicateRule = (rule: TechnicalStockRule) => setRules((current) => [...current, { ...rule, id: `${Date.now()}-${Math.random()}`, name: `${rule.name} Copy` }]);
  const removeRule = (id: string) => setRules((current) => current.filter((rule) => rule.id !== id));

  return (
    <div className="technical-rule-builder">
      {rules.map((rule, index) => (
        <div key={rule.id} className="technical-rule-card">
          <h4>Stock Rule {index + 1}</h4>
          <div className="technical-rule-grid">
            <label>
              Rule name
              <input value={rule.name} onChange={(event) => updateRule(rule.id, { name: event.target.value })} />
            </label>
            <label>
              Target type
              <select value={rule.targetType} onChange={(event) => updateRule(rule.id, { targetType: event.target.value as 'single' | 'multiple' })}>
                <option value="single">Single stock</option>
                <option value="multiple">Multiple selected stocks</option>
              </select>
            </label>
            <label>
              Symbols
              <input value={rule.symbols} onChange={(event) => updateRule(rule.id, { symbols: event.target.value.toUpperCase() })} />
            </label>
            <label>
              Order mode
              <select value={rule.orderMode} onChange={(event) => updateRule(rule.id, { orderMode: event.target.value })}>
                <option value="QUANTITY">Quantity</option>
                <option value="AMOUNT">Amount</option>
                <option value="PERCENT_OF_HOLDING">Percent of Holding</option>
              </select>
            </label>
            <label>
              Order value
              <input value={rule.orderValue} onChange={(event) => updateRule(rule.id, { orderValue: event.target.value })} />
            </label>
            <label>
              Confirm scans
              <input value={rule.confirmScans} onChange={(event) => updateRule(rule.id, { confirmScans: event.target.value })} />
            </label>
            <label>
              Match
              <select value={rule.logic} onChange={(event) => updateRule(rule.id, { logic: event.target.value as 'AND' | 'OR' })}>
                <option value="AND">ALL</option>
                <option value="OR">ANY</option>
              </select>
            </label>
          </div>
          <div className="technical-condition-list">
            {rule.conditions.map((condition, conditionIndex) => (
              <div key={`${rule.id}-${conditionIndex}`} className="technical-condition-row">
                <select
                  value={condition.field}
                  onChange={(event) => {
                    const next = [...rule.conditions];
                    next[conditionIndex] = { ...condition, field: event.target.value };
                    updateRule(rule.id, { conditions: next });
                  }}
                >
                  {FIELD_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <select
                  value={condition.operator}
                  onChange={(event) => {
                    const next = [...rule.conditions];
                    next[conditionIndex] = { ...condition, operator: event.target.value };
                    updateRule(rule.id, { conditions: next });
                  }}
                >
                  {OPERATOR_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <input
                  value={condition.value}
                  onChange={(event) => {
                    const next = [...rule.conditions];
                    next[conditionIndex] = { ...condition, value: event.target.value };
                    updateRule(rule.id, { conditions: next });
                  }}
                />
              </div>
            ))}
          </div>
          <div className="technical-rule-actions">
            <button
              type="button"
              onClick={() => updateRule(rule.id, { conditions: [...rule.conditions, { field: 'technical_rsi_14', operator: '<', value: '70' }] })}
            >
              + Add Condition
            </button>
            <button type="button" onClick={() => duplicateRule(rule)}>Duplicate Rule</button>
            <button type="button" disabled={rules.length <= 1} onClick={() => removeRule(rule.id)}>Remove Rule</button>
          </div>
        </div>
      ))}
      <button type="button" onClick={addRule}>+ Add Stock Rule</button>
    </div>
  );
};

export default TechnicalRuleBuilder;
