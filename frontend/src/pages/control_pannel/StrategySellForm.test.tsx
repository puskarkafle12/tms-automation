import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StrategySellForm from './StrategySellForm';

describe('StrategySellForm', () => {
  test('Schedule Strategy Order click shows missing-field error for Profit Ladder Sell', async () => {
    const onSubmit = jest.fn();
    render(
      <StrategySellForm
        side="sell"
        currentLtp={100}
        availableQty={100}
        initialQty="10"
        initialPrice="100"
        onSubmit={onSubmit}
      />,
    );

    await act(async () => {
      userEvent.selectOptions(screen.getByLabelText('Strategy'), 'Profit Ladder Sell');
    });
    await act(async () => {
      userEvent.click(screen.getByRole('button', { name: 'Schedule Profit Ladder' }));
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Both target prices are required.');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test('Fixed Price Sell submits when required fields are present', async () => {
    const onSubmit = jest.fn();
    render(
      <StrategySellForm
        side="sell"
        currentLtp={100}
        availableQty={100}
        initialQty="10"
        initialPrice="100"
        onSubmit={onSubmit}
      />,
    );

    await act(async () => {
      userEvent.click(screen.getByRole('button', { name: 'Schedule Sell Order' }));
    });

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      strategy_type: 'Fixed Price Sell',
      qty: 10,
      price: 100,
    }));
  });

  test('Show details opens strategy guide modal', async () => {
    render(
      <StrategySellForm
        side="sell"
        currentLtp={100}
        availableQty={100}
        initialQty="10"
        initialPrice="100"
        onSubmit={jest.fn()}
      />,
    );

    await act(async () => {
      userEvent.click(screen.getByRole('button', { name: 'Strategy details' }));
    });

    expect(screen.getByRole('dialog')).toHaveTextContent('Fixed Price Sell');
    expect(screen.getByRole('dialog')).toHaveTextContent('Tested scenarios');
  });

  test('keeps typed strategy fields when market/client props refresh', async () => {
    const onSubmit = jest.fn();
    const { rerender } = render(
      <StrategySellForm
        side="sell"
        currentLtp={100}
        availableQty={100}
        initialQty="10"
        initialPrice="100"
        onSubmit={onSubmit}
      />,
    );

    await act(async () => {
      userEvent.clear(screen.getByLabelText('Quantity in kitta'));
      userEvent.type(screen.getByLabelText('Quantity in kitta'), '25');
    });

    rerender(
      <StrategySellForm
        side="sell"
        currentLtp={200}
        availableQty={300}
        initialQty="10"
        initialPrice="200"
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByLabelText('Quantity in kitta')).toHaveValue(25);
  });
});
