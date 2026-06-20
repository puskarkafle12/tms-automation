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

  it('is much shorter than the full reference prompt', () => {
    const compact = buildChatGptScreenerPromptForCopy(SAMPLE_FIELDS);
    const full = buildChatGptScreenerPrompt(SAMPLE_FIELDS);
    expect(compact.length).toBeLessThan(full.length / 3);
  });
});
