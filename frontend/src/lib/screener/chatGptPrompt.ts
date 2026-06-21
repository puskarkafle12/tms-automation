export interface ScreenerFieldRef {
  key: string;
  label: string;
  category: string;
  type: 'number' | 'text';
  operators?: string[];
}

export interface ScreenerQuerySpec {
  allowed_filter_keys: string[];
  result_columns: string[];
  non_filterable_columns: string[];
  unsupported_user_terms: string[];
  numeric_operators: string[];
  text_operators: string[];
  field_aliases: Record<string, string[]>;
  alias_map: Record<string, string>;
  limit_default: number;
  limit_max: number;
  default_rank_by: string;
  default_rank_direction: 'asc' | 'desc';
}

const OPERATOR_QUERY_SYNTAX: Record<string, { label: string; example: (field: string) => string }> = {
  gt: { label: 'greater than', example: (f) => `${f} > 10` },
  gte: { label: 'greater than or equal', example: (f) => `${f} >= 10` },
  lt: { label: 'less than', example: (f) => `${f} < 10` },
  lte: { label: 'less than or equal', example: (f) => `${f} <= 10` },
  eq: { label: 'equals', example: (f) => `${f} = 10` },
  neq: { label: 'not equals', example: (f) => `${f} != 10` },
  between: { label: 'between (numbers only)', example: (f) => `${f} BETWEEN 30 AND 45` },
  contains: { label: 'contains text', example: (f) => `${f} CONTAINS 'Bullish'` },
  in: { label: 'in list', example: (f) => `${f} IN ('above', 'below')` },
};

const TEXT_FIELD_HINTS: Record<string, string> = {
  technical_macd: "Signal text from Nepse Alpha — commonly 'Bullish' or 'Bearish'",
  technical_sma_10: "Price vs SMA — use exactly 'above' or 'below'",
  technical_sma_20: "Price vs SMA — use exactly 'above' or 'below'",
  technical_sma_50: "Price vs SMA — use exactly 'above' or 'below'",
  technical_sma_200: "Price vs SMA — use exactly 'above' or 'below'",
  technical_volume_trend: "Trend label from Nepse Alpha (e.g. Up, Down)",
  technical_3m_price_tend: "Trend label from Nepse Alpha (e.g. Mean reverting, Trending)",
};

const pickField = (fields: ScreenerFieldRef[], key: string): ScreenerFieldRef | undefined =>
  fields.find((field) => field.key === key);

const buildDynamicExamples = (fields: ScreenerFieldRef[], spec: ScreenerQuerySpec): string[] => {
  if (fields.length === 0) {
    return [];
  }

  const examples: string[] = [];
  const rsi = pickField(fields, 'technical_rsi_14');
  const pe = pickField(fields, 'fundamental_pe_ttm');
  const macd = pickField(fields, 'technical_macd');
  const alpha = pickField(fields, 'alpha_annualized');
  const roe = pickField(fields, 'fundamental_roe_ttm');
  const debt = pickField(fields, 'fundamental_debt_to_equity');
  const sharpe = pickField(fields, 'sharpe_ratio_annualized');
  const rankBy = spec.default_rank_by;
  const limit = spec.limit_default;

  if (rsi && pe && macd && alpha) {
    examples.push(
      `WHERE ${rsi.key} BETWEEN 30 AND 45
  AND ${pe.key} <= 30
  AND ${macd.key} = 'Bullish'
ORDER BY ${alpha.key} DESC
LIMIT ${limit}`,
    );
  }

  if (roe && debt && sharpe) {
    examples.push(
      `WHERE ${roe.key} >= 15
  AND ${debt.key} <= 1
  AND ${sharpe.key} >= 1
ORDER BY ${sharpe.key} DESC
LIMIT ${limit}`,
    );
  }

  if (alpha) {
    examples.push(`ORDER BY ${rankBy} DESC\nLIMIT ${limit}`);
  }

  return examples;
};

const buildFieldDetailLines = (field: ScreenerFieldRef, aliases: string[]): string => {
  const ops = (field.operators || [])
    .map((op) => {
      const syntax = OPERATOR_QUERY_SYNTAX[op];
      return syntax ? `${op} (${syntax.label}) → e.g. \`${syntax.example(field.key)}\`` : op;
    })
    .join('\n      ');

  const hint = TEXT_FIELD_HINTS[field.key];
  const aliasLine = aliases.length > 0
    ? `\n    Accepted aliases (parser maps these to \`${field.key}\`): ${aliases.map((a) => `"${a}"`).join(', ')}`
    : '';
  const displayLine = `\n    UI label: "${field.label}" | Category: ${field.category} | Type: ${field.type}`;
  const hintLine = hint ? `\n    Value hint: ${hint}` : '';

  return `  • **${field.key}**${displayLine}${aliasLine}${hintLine}
    Allowed operators:
      ${ops}`;
};

const buildUnsupportedTermsBlock = (spec: ScreenerQuerySpec, allowedKeySet: Set<string>): string => {
  const terms = spec.unsupported_user_terms.filter((term) => !allowedKeySet.has(term));
  if (terms.length === 0) {
    return '(none listed)';
  }
  return terms.map((term) => `- "${term}"`).join('\n');
};

const buildAliasReference = (spec: ScreenerQuerySpec): string => {
  const lines: string[] = [];
  Object.entries(spec.field_aliases).forEach(([canonical, aliases]) => {
    if (aliases.length === 0) {
      return;
    }
    lines.push(`  - ${canonical} ← ${aliases.map((a) => `"${a}"`).join(', ')}`);
  });
  return lines.length > 0 ? lines.join('\n') : '  - (use exact keys only)';
};

const buildOperatorReference = (spec: ScreenerQuerySpec): string => {
  const numericLines = spec.numeric_operators
    .map((op) => {
      const entry = OPERATOR_QUERY_SYNTAX[op];
      return entry ? `- \`${entry.example('field_key')}\` — ${entry.label}` : `- ${op}`;
    })
    .join('\n');

  const textLines = spec.text_operators
    .map((op) => {
      const entry = OPERATOR_QUERY_SYNTAX[op];
      if (op === 'contains') {
        return `- \`field_key CONTAINS 'text'\` or \`field_key LIKE 'text'\` — ${entry?.label || 'contains'}`;
      }
      return entry ? `- \`${entry.example('field_key')}\` — ${entry.label}` : `- ${op}`;
    })
    .join('\n');

  return `### Numeric fields (${spec.numeric_operators.join(', ')})
${numericLines}

### Text fields (${spec.text_operators.join(', ')})
${textLines}`;
};

const buildMachineReadableCatalog = (fields: ScreenerFieldRef[], spec: ScreenerQuerySpec): string => {
  const payload = {
    source: 'GET /stock_screener/fields',
    filterable_field_count: fields.length,
    fields: fields.map((field) => ({
      key: field.key,
      label: field.label,
      category: field.category,
      type: field.type,
      operators: field.operators || [],
      aliases: spec.field_aliases[field.key] || [],
      filterable: true,
    })),
    non_filterable_result_columns: spec.non_filterable_columns,
    default_rank_by: spec.default_rank_by,
    limit_default: spec.limit_default,
    limit_max: spec.limit_max,
  };
  return JSON.stringify(payload, null, 2);
};

const defaultQuerySpec = (fields: ScreenerFieldRef[]): ScreenerQuerySpec => ({
  allowed_filter_keys: fields.map((f) => f.key),
  result_columns: ['rank', 'symbol', ...fields.map((f) => f.key)],
  non_filterable_columns: ['rank', 'symbol', 'cached', 'fetched_at'],
  unsupported_user_terms: [
    'market_cap', 'sector', 'eps', 'volume', 'company_name', 'name', 'ticker', 'symbol',
  ],
  numeric_operators: ['gt', 'gte', 'lt', 'lte', 'eq', 'neq', 'between'],
  text_operators: ['eq', 'neq', 'contains', 'in'],
  field_aliases: {},
  alias_map: {},
  limit_default: 25,
  limit_max: 500,
  default_rank_by: 'alpha_annualized',
  default_rank_direction: 'desc',
});

const resolveQuerySpec = (
  fields: ScreenerFieldRef[],
  querySpec?: ScreenerQuerySpec | null,
): ScreenerQuerySpec => querySpec || defaultQuerySpec(fields);

export const buildChatGptScreenerPromptForCopy = (
  fields: ScreenerFieldRef[],
  querySpec?: ScreenerQuerySpec | null,
): string => {
  const spec = resolveQuerySpec(fields, querySpec);
  const allowedKeys = [...spec.allowed_filter_keys].sort();
  const examples = buildDynamicExamples(fields, spec);
  const exampleBlock = examples[0]
    ? `\nExample query:\n\`\`\`\n${examples[0]}\n\`\`\`\n`
    : '';
  const aliasReference = buildAliasReference(spec);
  const unsupportedTerms = buildUnsupportedTermsBlock(spec, new Set(allowedKeys));

  return `You generate NEPSE stock screener queries for a TMS automation app. Output uses a mini-language (NOT full SQL).
Single-pass: give the best relevant query on the first reply.

Rules:
- Use ONLY the field keys listed below in WHERE and ORDER BY (copy snake_case keys exactly).
- Combine filters with AND only. No OR, no parentheses, no JOIN, no subqueries, no comparing two fields.
- Numeric fields: >, >=, <, <=, =, !=, BETWEEN low AND high
- Text fields: =, !=, IN ('a', 'b'), CONTAINS 'text' or LIKE 'text'
- Always include ORDER BY <field> ASC|DESC and LIMIT (default ${spec.limit_default}, max ${spec.limit_max}).
- symbol is returned in results but is NOT filterable.
- If the user asks for unsupported data, prefer STATUS: OK with the closest allowed query — omit or substitute, then note the gap in Summary.

Allowed field keys (${allowedKeys.length}):
${allowedKeys.join(', ')}

Field reference:
${fields.length > 0 ? buildCompactFieldReference(fields) : '(Load the screener page first to fetch live fields.)'}

Common aliases (output the canonical key in the query):
${aliasReference}

Unsupported terms (omit or substitute — do not put in query):
${unsupportedTerms}

Response when you can build a reasonable screen (default):
STATUS: OK
Summary:
- 2-3 bullets: what the screen finds
- Limitation: (only if needed) We don't have <X>; used <Y> instead — close, not exact.
Query:
\`\`\`
WHERE ...
ORDER BY ${spec.default_rank_by} DESC
LIMIT ${spec.limit_default}
\`\`\`

Response only when no valid query is possible:
STATUS: ERROR
Reason: ...
Do NOT include a Query block.
${exampleBlock}
User request:
[PASTE WHAT YOU WANT TO SCREEN FOR HERE]`;
};

export const buildChatGptScreenerPrompt = (
  fields: ScreenerFieldRef[],
  querySpec?: ScreenerQuerySpec | null,
): string => {
  const spec = resolveQuerySpec(fields, querySpec);

  const allowedKeys = [...spec.allowed_filter_keys].sort();
  const allowedKeySet = new Set(allowedKeys);
  const numericFields = fields.filter((f) => f.type === 'number');
  const textFields = fields.filter((f) => f.type === 'text');

  const grouped = new Map<string, ScreenerFieldRef[]>();
  fields.forEach((field) => {
    const list = grouped.get(field.category) || [];
    list.push(field);
    grouped.set(field.category, list);
  });

  const fieldSections = Array.from(grouped.entries())
    .map(([category, items]) => {
      const lines = items.map((field) => buildFieldDetailLines(field, spec.field_aliases[field.key] || []));
      return `## ${category} (${items.length} fields)\n${lines.join('\n\n')}`;
    })
    .join('\n\n');

  const examples = buildDynamicExamples(fields, spec);
  const exampleBlock = examples.length > 0
    ? examples.map((q, i) => `### Example ${i + 1} (uses only live API keys)\n\`\`\`\n${q}\n\`\`\``).join('\n\n')
    : '*(Load the screener UI first so field keys are available.)*';

  const filterableKeyList = allowedKeys.map((key) => `\`${key}\``).join(', ');
  const resultColumnList = spec.result_columns.map((col) => `\`${col}\``).join(', ');

  return `You are a strict query generator for a **NEPSE stock screener** powered by **Nepse Alpha** data.
Your output is pasted into a TMS automation app that parses a **custom mini-language** (NOT full SQL).

The field list below is loaded **live from the backend API** (\`GET /stock_screener/fields\`).
You must use **only** the exact column keys listed here. If a column is not listed, it does not exist — respond with STATUS: ERROR.

---

## 1. CRITICAL RULES (read before generating anything)

1. **Whitelist only** — Every token in \`WHERE\` and \`ORDER BY\` must be one of the ${allowedKeys.length} \`allowed_filter_keys\` below. Copy keys **character-for-character** (snake_case).
2. **No invented columns** — Never use shorthand like \`pe\`, \`rsi\`, \`roe\`, \`market_cap\`, \`volume\`, \`sector\`, \`eps\`, \`name\`, or \`symbol\` in the query unless the exact key appears in the whitelist. Map user language via the alias tables, then output the canonical key.
3. **If any part of the user request cannot be mapped** to allowed keys → \`STATUS: ERROR\` with **no** query block.
4. **This is NOT SQL** — No \`OR\`, no parentheses for logic, no \`JOIN\`, no subqueries, no \`SELECT\` column lists, no math, no comparing two fields.
5. **symbol** is returned in results but is **not filterable**. Reject \`WHERE symbol = ...\`.
6. **Type rules** — Numeric fields: \`>\`, \`>=\`, \`<\`, \`<=\`, \`=\`, \`!=\`, \`<>\`, \`BETWEEN\`. Text fields: \`=\`, \`!=\`, \`<>\`, \`IN (...)\`, \`CONTAINS\`, \`LIKE\`.
7. **Always include** \`ORDER BY <allowed_key> ASC|DESC\` and \`LIMIT <1-${spec.limit_max}>\` (default LIMIT ${spec.limit_default}).

---

## 2. LIVE API FIELD WHITELIST (${allowedKeys.length} filterable columns)

These are the **only** column keys the parser accepts in \`WHERE\` and \`ORDER BY\`:

${allowedKeys.map((key) => `- \`${key}\``).join('\n')}

**Comma-separated (for quick scanning):**
${filterableKeyList}

---

## 3. RESULT TABLE COLUMNS (what the user sees after screening)

The API returns rows with these columns (you do **not** choose columns — ranking returns all metrics):

${spec.result_columns.map((col) => `- \`${col}\``).join('\n')}

**Not filterable (display/metadata only):**
${spec.non_filterable_columns.map((col) => `- \`${col}\``).join('\n')}

---

## 4. NUMERIC vs TEXT FIELDS (from live API)

### Numeric (${numericFields.length} fields) — use numeric comparisons only
${numericFields.map((f) => `- \`${f.key}\` — ${f.label}`).join('\n') || '(none)'}

### Text (${textFields.length} fields) — use =, IN, CONTAINS/LIKE only
${textFields.map((f) => `- \`${f.key}\` — ${f.label}`).join('\n') || '(none)'}

---

## 5. OPERATOR SYNTAX (exact text the parser expects)

${buildOperatorReference(spec)}

Additional rules:
- Combine filters with **AND** only (never OR).
- \`BETWEEN\` format: \`field_key BETWEEN low AND high\` (both numbers).
- String literals use **single quotes**: \`'Bullish'\`, \`'above'\`.
- \`IN\` format: \`field_key IN ('a', 'b')\`.
- \`SELECT ...\` prefix is stripped/ignored — do not rely on it.

---

## 6. ALIAS MAP (user/AI terms → exact API key)

When the user says a label or shorthand, resolve to the canonical key below, then **output only the canonical key** in the query.

${buildAliasReference(spec)}

---

## 7. FULL FIELD CATALOG (live from API — key, label, type, operators, hints)

${fieldSections || '**ERROR: Field catalog not loaded.** Refuse to generate queries until the app provides field metadata.'}

---

## 8. TERMS THAT DO **NOT** EXIST (always STATUS: ERROR)

If the user asks to filter/sort by any of these, they are **not** in the Nepse Alpha screener API:

${buildUnsupportedTermsBlock(spec, allowedKeySet)}

Also reject: comparing two fields (\`ltp < fifty_two_week_low\`), math on fields, \`OR\` logic, nested parentheses.

---

## 9. PARSER ERRORS YOU MUST PREVENT

The backend rejects invalid queries with messages like:
- \`Unknown field: <name>\` — you used a key not in section 2
- \`Could not parse condition: ...\` — wrong operator/syntax for field type
- \`Query is empty\`
- \`LIMIT must be a number\`
- \`ORDER BY direction must be ASC or DESC\`

---

## 10. MACHINE-READABLE CATALOG (JSON from live API)

\`\`\`json
${buildMachineReadableCatalog(fields, spec)}
\`\`\`

---

## 11. RESPONSE FORMAT (MANDATORY)

### When the request CAN be satisfied:
\`\`\`
STATUS: OK

Summary:
- (2-4 bullets: what filters mean in plain English)

Field mapping used:
- user term "..." → \`exact_api_key\` (operator value)

Query:
\`\`\`
WHERE ...
ORDER BY ${spec.default_rank_by} DESC
LIMIT ${spec.limit_default}
\`\`\`
\`\`\`

Output **exactly one** fenced query block. Keys must match section 2 exactly.

### When the request CANNOT be satisfied:
\`\`\`
STATUS: ERROR

Reason:
- (which field/syntax is unsupported)

Invalid request detail:
- (what the user asked for)

Closest allowed API keys:
- (list from section 2, or "none")

Do NOT include a Query block when STATUS is ERROR.
\`\`\`

---

## 12. EXAMPLE VALID QUERIES (built from current API keys only)

${exampleBlock}

---

## 13. EXAMPLE ERROR RESPONSE

\`\`\`
STATUS: ERROR

Reason:
- "market_cap" is not a filterable column in the live Nepse Alpha screener API.

Invalid request detail:
- User asked to screen by market capitalization.

Closest allowed API keys:
- fundamental_ps_ttm
- ltp
- one_year_yield
\`\`\`

---

## 14. YOUR WORKFLOW

1. Read the user request below.
2. For each filter/sort/rank intent, find the matching key in **section 2** or **section 6** (aliases).
3. If any intent has no match → STATUS: ERROR.
4. Pick operators from **section 5** matching the field **type** in **section 4**.
5. If all intents map → STATUS: OK + one query using **only** canonical keys from section 2.
6. Double-check: every field name in your query appears in section 2.

---

## User request
[PASTE WHAT YOU WANT TO SCREEN FOR HERE]
`;
};

export const buildCompactFieldReference = (fields: ScreenerFieldRef[]): string => {
  return fields
    .map((f) => `${f.key} (${f.type}) — ${f.label} [${(f.operators || []).join(', ')}]`)
    .join('\n');
};
