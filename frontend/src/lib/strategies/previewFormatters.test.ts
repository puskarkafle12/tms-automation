import {
  formatCurrentRequired,
  formatEstimatePriceDisplay,
  formatNumericEstimatePrice,
  formatPriceBoundary,
  formatQuantityCell,
  type PreviewRow,
} from './previewFormatters';

describe('previewFormatters', () => {
  test('formats 52-week trigger as percentage boundary not raw price', () => {
    const row: PreviewRow = {
      trigger: {
        strategy_text: '52-week range position ≥ 95.00%',
        estimated_price: 392.5,
        estimated_price_display: 'Rs. 392.50 (est.)',
        estimated_price_available: true,
        is_exact_price: false,
        current_display: '81.80%',
        target_display: '95.00%',
      },
    };
    expect(formatPriceBoundary(row)).toBe('Rs. 392.50 (est.)');
    expect(formatPriceBoundary(row)).not.toMatch(/\(est\.\).*\(est\.\)/);
    expect(formatCurrentRequired(row)).toContain('81.80%');
    expect(formatCurrentRequired(row)).toContain('95.00%');
  });

  test('does not duplicate estimate suffix when backend already includes it', () => {
    expect(formatEstimatePriceDisplay('Rs. 195.80 (est.)')).toBe('Rs. 195.80 (est.)');
    expect(formatNumericEstimatePrice(195.8)).toBe('Rs. 195.80 (est.)');
  });

  test('shows unavailable quantity when holding missing', () => {
    const row: PreviewRow = {
      quantity: {
        mode: 'percent_of_holding',
        estimated_quantity_display: 'Unavailable',
        description: 'Sell 100% of current holding',
        note: 'Final quantity is recalculated immediately before execution.',
        warnings: [{ code: 'HOLDING_UNAVAILABLE', message: 'Current holding could not be retrieved.' }],
      },
    };
    expect(formatQuantityCell(row)).toContain('Unavailable');
    expect(formatQuantityCell(row)).toContain('recalculated');
  });
});
