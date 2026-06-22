import { getApiUrl } from '../../utils/api';

export interface AiQuickScreen {
  id: string;
  prompt: string;
  summary: string;
  query: string;
}

export const fetchAiQuickScreens = async (): Promise<AiQuickScreen[]> => {
  const response = await fetch(`${getApiUrl()}/market_analysis/ai_quick_screens`);
  if (!response.ok) {
    throw new Error('Failed to load quick AI screens');
  }
  const data = await response.json();
  return Array.isArray(data?.quick_screens) ? data.quick_screens : [];
};

export const normalizeQuickPrompt = (text: string): string =>
  text.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[?.!]+$/, '');

export const findQuickScreenByPrompt = (
  screens: AiQuickScreen[],
  message: string,
): AiQuickScreen | undefined => {
  const normalized = normalizeQuickPrompt(message);
  return screens.find((screen) => normalizeQuickPrompt(screen.prompt) === normalized);
};
