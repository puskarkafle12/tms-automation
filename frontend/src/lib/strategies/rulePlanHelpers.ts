import { RULE_BASED_STRATEGIES } from '../../pages/control_pannel/strategyValidation';

export const DEFAULT_RULE_PLANNED_QTY = 10;

export function isRuleBasedStrategy(strategy: string): boolean {
  return RULE_BASED_STRATEGIES.has(strategy);
}

export function isCustomQueryStrategy(strategy: string): boolean {
  return strategy === 'Custom Query' || strategy === 'Custom Query Buy' || strategy === 'Custom Query Sell';
}

export function extractPlanSide(compiledPlan?: Record<string, unknown>): 'buy' | 'sell' | null {
  const side = String(compiledPlan?.side || '').trim().toUpperCase();
  if (side === 'BUY') return 'buy';
  if (side === 'SELL') return 'sell';
  return null;
}

export function customQueryStrategyForSide(side: 'buy' | 'sell'): 'Custom Query Buy' | 'Custom Query Sell' {
  return side === 'buy' ? 'Custom Query Buy' : 'Custom Query Sell';
}

export function holdingsMapFromRows(
  rows: Array<{ scrip?: string; symbolName?: string; symbol?: string; currentBalance?: number | string }>,
): Record<string, number> {
  const holdings: Record<string, number> = {};
  for (const row of rows) {
    const qty = Number(row.currentBalance || 0);
    const symbols = [row.scrip, row.symbolName, row.symbol]
      .map((value) => String(value || '').trim().toUpperCase())
      .filter(Boolean);
    for (const symbol of symbols) {
      holdings[symbol] = Math.max(holdings[symbol] || 0, qty);
    }
  }
  return holdings;
}

export function extractSymbolsFromCompiledPlan(compiledPlan?: Record<string, unknown>): string[] {
  const rules = (compiledPlan?.rules as Array<{ symbols?: string[] }> | undefined) || [];
  const seen = new Set<string>();
  const symbols: string[] = [];
  for (const rule of rules) {
    for (const symbol of rule.symbols || []) {
      const normalized = String(symbol).trim().toUpperCase();
      if (normalized && !seen.has(normalized)) {
        seen.add(normalized);
        symbols.push(normalized);
      }
    }
  }
  return symbols;
}

type CompiledRule = {
  symbols?: string[];
  order?: { mode?: string; value?: number };
};

const HOLDING_DEPENDENT_MODES = new Set(['percent_of_holding', 'all_available', 'sell_up_to']);

export function isHoldingDependentOrderMode(mode?: string): boolean {
  return HOLDING_DEPENDENT_MODES.has(String(mode || '').toLowerCase());
}

export function extractOrderQuantityLabel(
  compiledPlan?: Record<string, unknown>,
  symbol?: string,
): string | null {
  const rules = (compiledPlan?.rules as CompiledRule[] | undefined) || [];
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();
  for (const rule of rules) {
    const ruleSymbols = (rule.symbols || [])
      .map((item) => String(item).trim().toUpperCase())
      .filter(Boolean);
    if (normalizedSymbol && ruleSymbols.length > 0 && !ruleSymbols.includes(normalizedSymbol)) {
      continue;
    }
    const order = rule.order;
    const mode = String(order?.mode || '').toLowerCase();
    const value = Number(order?.value);
    if (mode === 'percent_of_holding' && Number.isFinite(value) && value > 0) {
      return `${value}% of available holding (final quantity calculated immediately before execution)`;
    }
    if (mode === 'all_available') {
      return 'All available holding (final quantity calculated immediately before execution)';
    }
    if (mode === 'sell_up_to' && Number.isFinite(value) && value > 0) {
      return `Sell up to ${Math.floor(value)} (final quantity calculated immediately before execution)`;
    }
  }
  return null;
}

export function formatOrderQuantityDisplay(order: {
  qty?: number | string | null;
  script_name?: string;
  strategy_type?: string;
  strategy_config?: Record<string, unknown>;
}): string {
  const config = (order.strategy_config || {}) as Record<string, unknown>;
  const audit = config.execution_quantity_audit as
    | { resolved_execution_quantity?: number }
    | undefined;
  if (audit?.resolved_execution_quantity && audit.resolved_execution_quantity > 0) {
    return String(audit.resolved_execution_quantity);
  }
  const dynamicLabel = extractOrderQuantityLabel(
    config.compiled_plan as Record<string, unknown> | undefined,
    order.script_name,
  );
  if (dynamicLabel) {
    return dynamicLabel;
  }
  return String(getDisplayQtyForOrder(order));
}

export function extractPlannedQtyFromCompiledPlan(
  compiledPlan?: Record<string, unknown>,
  symbol?: string,
): number | null {
  const rules = (compiledPlan?.rules as CompiledRule[] | undefined) || [];
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();
  for (const rule of rules) {
    const ruleSymbols = (rule.symbols || [])
      .map((item) => String(item).trim().toUpperCase())
      .filter(Boolean);
    if (normalizedSymbol && ruleSymbols.length > 0 && !ruleSymbols.includes(normalizedSymbol)) {
      continue;
    }
    const order = rule.order;
    const mode = String(order?.mode || '').toLowerCase();
    const value = Number(order?.value);
    if (isHoldingDependentOrderMode(mode)) {
      return null;
    }
    if (mode === 'quantity') {
      if (Number.isFinite(value) && value > 0) {
        return Math.floor(value);
      }
      return DEFAULT_RULE_PLANNED_QTY;
    }
  }
  return null;
}

export function getDisplayQtyForOrder(order: {
  qty?: number | string | null;
  script_name?: string;
  strategy_type?: string;
  strategy_config?: Record<string, unknown>;
}): number {
  const config = (order.strategy_config || {}) as Record<string, unknown>;
  if (isRuleBasedStrategy(String(order.strategy_type || ''))) {
    const configured = Number(config.rule_planned_qty);
    if (Number.isFinite(configured) && configured > 0) {
      return configured;
    }
    const fromPlan = extractPlannedQtyFromCompiledPlan(
      config.compiled_plan as Record<string, unknown> | undefined,
      order.script_name,
    );
    if (fromPlan && fromPlan > 0) {
      return fromPlan;
    }
  }
  return Number(order.qty || 0);
}

function nodeUsesReference(node: unknown): boolean {
  if (!node || typeof node !== 'object') {
    return false;
  }
  const record = node as Record<string, unknown>;
  if (record.type === 'function' && String(record.name || '').toUpperCase() === 'REFERENCE') {
    return true;
  }
  for (const value of Object.values(record)) {
    if (Array.isArray(value)) {
      if (value.some((item) => nodeUsesReference(item))) {
        return true;
      }
    } else if (nodeUsesReference(value)) {
      return true;
    }
  }
  return false;
}

export interface PlanValidationSnapshot {
  valid?: boolean;
  status?: string;
  errors?: Array<{ code?: string; message?: string }>;
  warnings?: Array<{ code?: string; message?: string }>;
}

const BLOCKING_VALIDATION_CODES = new Set([
  'SELL_SYMBOL_NOT_HELD',
  'SELL_QTY_EXCEEDS_HOLDING',
  'INVALID_SYMBOL',
  'NEPSE_ALPHA_UNAVAILABLE',
  'NEPSE_ALPHA_FIELD_MISSING',
  'CLIENT_NOT_LOGGED_IN',
  'USER_NOT_FOUND',
]);

export function findBlockingValidationIssue(
  validation: PlanValidationSnapshot | null | undefined,
): { code?: string; message?: string } | null {
  if (!validation) {
    return null;
  }
  for (const issue of validation.errors || []) {
    if (issue.message) {
      return issue;
    }
  }
  for (const issue of validation.warnings || []) {
    if (issue.code && BLOCKING_VALIDATION_CODES.has(issue.code) && issue.message) {
      return issue;
    }
  }
  return null;
}

export function isSchedulePreflightReady(
  schedulePreflight?: { ready?: boolean } | null,
): boolean {
  return Boolean(schedulePreflight?.ready);
}

export function isQueryValidationReady(
  validation: PlanValidationSnapshot | null | undefined,
  compiledPlan?: Record<string, unknown>,
): boolean {
  if (!validation?.valid || !compiledPlan) {
    return false;
  }
  if (validation.status === 'unsupported_data') {
    return false;
  }
  if ((validation.errors || []).length > 0) {
    return false;
  }
  return !findBlockingValidationIssue(validation);
}

export function validatePlanSymbolsForSchedule(
  compiledPlan: Record<string, unknown> | undefined,
  side: 'buy' | 'sell',
  options: {
    knownBuySymbols?: Set<string>;
    holdingsBySymbol?: Record<string, number>;
    scriptListLoading?: boolean;
    holdingsLoading?: boolean;
  } = {},
): string | null {
  const symbols = extractSymbolsFromCompiledPlan(compiledPlan);
  if (!symbols.length) {
    return 'Rule plan must include at least one symbol.';
  }

  if (side === 'buy') {
    if (options.scriptListLoading) {
      return 'Loading stock list for this client…';
    }
    const known = options.knownBuySymbols;
    if (!known || known.size === 0) {
      return 'Stock list is not loaded yet. Wait for scripts to load or refresh.';
    }
    for (const symbol of symbols) {
      if (!known.has(symbol)) {
        return `${symbol} is not a valid listed scrip for this client.`;
      }
    }
    return null;
  }

  if (options.holdingsLoading) {
    return 'Verifying DP holdings for this client…';
  }
  const holdings = options.holdingsBySymbol || {};
  for (const symbol of symbols) {
    if ((holdings[symbol] ?? 0) <= 0) {
      return `${symbol} is not available in DP holdings.`;
    }
  }
  return null;
}

export function planUsesReference(
  compiledPlan?: Record<string, unknown>,
  queryText?: string,
): boolean {
  if (queryText && /REFERENCE\s*\(/i.test(queryText)) {
    return true;
  }
  if (!compiledPlan) {
    return false;
  }
  const rules = (compiledPlan.rules as unknown[] | undefined) || [];
  return rules.some((rule) => nodeUsesReference(rule));
}
