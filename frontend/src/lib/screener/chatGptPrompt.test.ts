import {
  buildChatGptScreenerPrompt,
  buildChatGptScreenerPromptForCopy,
  ScreenerFieldRef,
} from './chatGptPrompt';

const SAMPLE_FIELDS: ScreenerFieldRef[] = [
  {
    key: 'alpha_annualized',
    label: 'Alpha (annualized)',
    category: 'risk',
    type: 'number',
    operators: ['gte', 'lte'],
  },
  {
    key: 'technical_macd',
    label: 'MACD',
    category: 'technical',
    type: 'text',
    operators: ['eq', 'in'],
  },
];

describe('buildChatGptScreenerPromptForCopy', () => {
  it('includes rules and compact field reference without JSON catalog', () => {
    const prompt = buildChatGptScreenerPromptForCopy(SAMPLE_FIELDS);
    expect(prompt).toContain('Rules:');
    expect(prompt).toContain('alpha_annualized (number)');
    expect(prompt).toContain('User request:');
    expect(prompt).not.toContain('MACHINE-READABLE CATALOG');
    expect(prompt).not.toContain('"filterable_field_count"');
  });

  it('prefers best-effort single-pass guidance', () => {
    const prompt = buildChatGptScreenerPromptForCopy(SAMPLE_FIELDS);
    expect(prompt).toContain('one shot');
    expect(prompt).toContain('Limitation:');
    expect(prompt).toContain('close, not exact');
  });

  it('does not include a hard error template in the copy prompt', () => {
    const prompt = buildChatGptScreenerPromptForCopy(SAMPLE_FIELDS);
    expect(prompt).toContain('Avoid STATUS: ERROR');
    expect(prompt).toContain('top 50 good stocks');
    expect(prompt).toContain('true market-wide discovery');
    expect(prompt).toContain('Do not output Strategy Query Language');
    expect(prompt).not.toContain('Response only when no valid query is possible');
    expect(prompt).not.toContain('This screener is not supported');
  });

  it('is much shorter than the full reference prompt', () => {
    const compact = buildChatGptScreenerPromptForCopy(SAMPLE_FIELDS);
    const full = buildChatGptScreenerPrompt(SAMPLE_FIELDS);
    expect(compact.length).toBeLessThan(full.length / 3);
  });
});
