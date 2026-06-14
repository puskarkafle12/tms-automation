import { render, screen, within } from '@testing-library/react';
import StockDetails from './StockDetails';

const stock = {
  symbol: 'AAA',
  volume: 1000,
  ltp: 100,
  percentChange: 1,
  high: 110,
  low: 90,
  open: 95,
  lastTradedVolume: 10,
  lastTradedTime: [2026, 6, 14, 12, 0, 0],
  change: 1,
  previousClose: 99,
};

describe('StockDetails market depth', () => {
  test('shows Top Buy and Top Sell tables when market depth is available', () => {
    render(
      <StockDetails
        stock={stock}
        topBuy={[{ price: 99, quantity: 100, totalOrders: 2 }]}
        topSell={[{ price: 101, quantity: 200, totalOrders: 3 }]}
      />,
    );

    const topBuyCard = screen.getByText('Top Buy Orders').closest('.stock-depth-card');
    const topSellCard = screen.getByText('Top Sell Orders').closest('.stock-depth-card');
    expect(topBuyCard).toBeTruthy();
    expect(topSellCard).toBeTruthy();
    expect(within(topBuyCard as HTMLElement).getByText('99')).toBeInTheDocument();
    expect(within(topSellCard as HTMLElement).getByText('101')).toBeInTheDocument();
  });

  test('shows market depth unavailable instead of empty/null table rows', () => {
    render(<StockDetails stock={stock} topBuy={[]} topSell={[]} />);

    expect(screen.getAllByText('Market depth unavailable')).toHaveLength(2);
  });
});
