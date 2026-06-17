export interface ScreenerFieldRef {
  key: string;
  label: string;
  category: string;
  type: 'number' | 'text';
  operators?: string[];
}

const OPERATOR_DOCS: Record<string, string> = {
  gt: '>',
  gte: '>=',
  lt: '<',
  lte: '<=',
  eq: '=',
  neq: '!= or <>',
  between: 'BETWEEN low AND high',
  contains: "CONTAINS 'text' or LIKE 'text'",
  in: "IN ('a', 'b', 'c')",
};

const TEXT_FIELD_HINTS: Record<string, string> = {
  technical_macd: "Usually 'Bullish', 'Bearish', or similar signal text from Nepse Alpha",
  technical_sma_10: "Use 'above' or 'below' (price vs moving average)",
  technical_sma_20: "Use 'above' or 'below'",
  technical_sma_50: "Use 'above' or 'below'",
  technical_sma_200: "Use 'above' or 'below'",
  technical_volume_trend: "Text trend label from Nepse Alpha, e.g. Up, Down",
  technical_3m_price_tend: "Text trend label, e.g. Mean reverting, Trending",
};

const EXAMPLE_QUERIES = [
  `WHERE technical_rsi_14 BETWEEN 30 AND 45
  AND fundamental_pe_ttm <= 30
  AND technical_macd = 'Bullish'
ORDER BY alpha_annualized DESC
LIMIT 25`,
  `WHERE fundamental_roe_ttm >= 15
  AND fundamental_debt_to_equity <= 1
  AND sharpe_ratio_annualized >= 1
ORDER BY sharpe_ratio_annualized DESC
LIMIT 25`,
  `ORDER BY alpha_annualized DESC
LIMIT 25`,
];

export const buildChatGptScreenerPrompt = (fields: ScreenerFieldRef[]): string => {
  const grouped = new Map<string, ScreenerFieldRef[]>();
  fields.forEach((field) => {
    const list = grouped.get(field.category) || [];
    list.push(field);
    grouped.set(field.category, list);
  });

  const fieldSections = Array.from(grouped.entries())
    .map(([category, items]) => {
      const lines = items.map((field) => {
        const ops = (field.operators || [])
          .map((op) => OPERATOR_DOCS[op] || op)
          .join(', ');
        const hint = TEXT_FIELD_HINTS[field.key];
        const typeLine = field.type === 'number'
          ? `type: number | operators: ${ops}`
          : `type: text | operators: ${ops}${hint ? ` | hint: ${hint}` : ''}`;
        return `  - ${field.key} — ${field.label} (${typeLine})`;
      });
      return `### ${category}\n${lines.join('\n')}`;
    })
    .join('\n\n');

  return `You are helping a user write stock screener queries for a NEPSE (Nepal Stock Exchange) app.

## Important context
- This is NOT real SQL and NOT a database query.
- Queries are parsed by a custom Python parser (SQL-like syntax only).
- Data source: Nepse Alpha signals per stock symbol (statistical, fundamental, technical).
- The app scans all TMS-listed symbols for a logged-in broker client, filters each stock's Nepse Alpha data, ranks matches, and returns top N results (default 50, max 500).
- Nepse Alpha data is cached 5 minutes per symbol.
- symbol is returned in results but is NOT a filter field in the query.

## Query grammar (what you may output)
\`\`\`
[WHERE <condition> [AND <condition> ...]]
[ORDER BY <field_key> [ASC|DESC]]
[LIMIT <number>]
\`\`\`

- WHERE is optional (omit to rank all stocks).
- Only AND is supported between conditions (no OR, no parentheses).
- SELECT is ignored if present.
- One condition per AND segment.

## Operators

### Numeric fields
- \`field > value\`
- \`field >= value\`
- \`field < value\`
- \`field <= value\`
- \`field = value\`
- \`field != value\` or \`field <> value\`
- \`field BETWEEN low AND high\`

### Text fields
- \`field = 'value'\`
- \`field != 'value'\`
- \`field IN ('a', 'b')\`
- \`field CONTAINS 'text'\` or \`field LIKE 'text'\`

## Sorting and limit
- \`ORDER BY <field_key> DESC\` — highest first (default if omitted: alpha_annualized DESC)
- \`ORDER BY <field_key> ASC\` — lowest first
- \`LIMIT 25\` — return top 25 (max 500)

## All filterable field keys (use exact keys)

${fieldSections || '(Field catalog not loaded — use standard keys like alpha_annualized, fundamental_pe_ttm, technical_rsi_14.)'}

## Not supported (do not use)
- OR conditions
- Nested parentheses logic
- Math between fields (e.g. ltp / pe)
- Comparing two fields to each other
- JOIN, GROUP BY, HAVING, subqueries
- Sector high/low as separate filter keys (not in catalog yet)

## Example valid queries

${EXAMPLE_QUERIES.map((q, i) => `Example ${i + 1}:\n\`\`\`\n${q}\n\`\`\``).join('\n\n')}

## Your task
When the user describes what stocks they want, respond with:
1. A short explanation of the screen logic (2-4 bullets).
2. One valid query block only (no extra SQL features).
3. Optional tweaks (e.g. stricter thresholds).

Always use exact field keys from the catalog above. Always end with LIMIT (recommend 25 unless user asks otherwise).

User request:
[PASTE WHAT YOU WANT TO SCREEN FOR HERE]
`;
};

export const buildCompactFieldReference = (fields: ScreenerFieldRef[]): string => {
  return fields
    .map((f) => `${f.key} (${f.type}) — ${f.label}`)
    .join('\n');
};
