import { getApiUrl } from '../../utils/api';

export type ScreenerPresetCategory = 'INVESTOR' | 'TRADER';

export interface ScreenerPreset {
  id: string;
  title: string;
  subtitle: string;
  query: string;
  prompt?: string;
  category?: ScreenerPresetCategory;
  risk_level?: string;
  time_horizon?: string;
  preset_code?: string;
  display_order?: number;
}

export interface ScreenerPresetGroup {
  category: ScreenerPresetCategory;
  label: string;
}

export const SCREENER_PRESET_GROUPS: ScreenerPresetGroup[] = [
  { category: 'INVESTOR', label: 'Investor' },
  { category: 'TRADER', label: 'Trader' },
];

export const SCREENER_QUERY_GUIDE = `How to write screener SQL:
- Presets use v_nepse_stock_screen (equity universe with liquidity and rank columns)
- Full query: WITH ranked AS (...) SELECT ... FROM v_nepse_stock_screen ...
- Simple query: SELECT * FROM market_combined WHERE ... ORDER BY ... LIMIT ...
- Legacy WHERE-only fragments still work (server wraps them automatically)`;

export const DEFAULT_SIMPLE_QUERY = `SELECT * FROM market_combined
ORDER BY alpha_annualized DESC NULLS LAST
LIMIT 25`;

export const fetchMarketAnalysisPresets = async (): Promise<ScreenerPreset[]> => {
  const response = await fetch(`${getApiUrl()}/market_analysis/presets`);
  if (!response.ok) {
    throw new Error('Failed to load screener presets');
  }
  const data = await response.json();
  return Array.isArray(data?.presets) ? data.presets : [];
};

export const buildPresetCopyText = (preset: ScreenerPreset): string => {
  const meta = [
    preset.category ? `Category: ${preset.category}` : '',
    preset.risk_level ? `Risk: ${preset.risk_level}` : '',
    preset.time_horizon ? `Horizon: ${preset.time_horizon}` : '',
  ].filter(Boolean).join(' | ');
  return `${preset.title}\n${preset.subtitle}${meta ? `\n${meta}` : ''}\n\n--- Query ---\n${preset.query}`;
};

export const groupPresetsByCategory = (
  presets: ScreenerPreset[],
): Record<ScreenerPresetCategory, ScreenerPreset[]> => {
  const grouped: Record<ScreenerPresetCategory, ScreenerPreset[]> = {
    INVESTOR: [],
    TRADER: [],
  };
  presets.forEach((preset) => {
    const category = preset.category === 'TRADER' ? 'TRADER' : 'INVESTOR';
    grouped[category].push(preset);
  });
  return grouped;
};
