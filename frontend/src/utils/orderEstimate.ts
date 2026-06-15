import { roundDownToBoardLot } from '../pages/control_pannel/lotSize';

export type OrderSide = 'BUY' | 'SELL';

export interface NepseProfitResult {
  buyAmount: number;
  sellAmount: number;
  buyBroker: number;
  buySebon: number;
  sellBroker: number;
  sellSebon: number;
  dpCharge: number;
  grossProfit: number;
  tax: number;
  finalProfit: number;
  profitPercent: string;
  totalBuyCost: number;
  totalSellCost: number;
  moneyReceived: number;
}

export interface OrderEstimateInput {
  side: OrderSide;
  quantity: number;
  price: number;
  investmentAmount?: number;
  averageBuyPrice?: number | null;
  holdingDays?: number;
  lotSize: number;
  priceSource?: string;
}

export interface OrderEstimate {
  quantity: number;
  grossAmount: number;
  estimatedCost?: number;
  netReceivable?: number;
  profitResult?: NepseProfitResult | null;
  unusedAmount?: number;
  priceSource: string;
  netEstimateAvailable: boolean;
}

export const brokerCommission = (amount: number) => {
  const value = Number(amount) || 0;
  let rate: number;

  if (value <= 50000) {
    rate = 0.0036;
  } else if (value <= 500000) {
    rate = 0.0033;
  } else if (value <= 2000000) {
    rate = 0.0031;
  } else if (value <= 10000000) {
    rate = 0.0027;
  } else {
    rate = 0.0024;
  }

  return Math.max(value * rate, 10);
};

export const sebonFee = (amount: number) => (Number(amount) || 0) * 0.00015;

export const dpCharge = () => 25;

export const capitalGainTax = (profit: number, holdingDays = 400) => {
  if (profit <= 0) return 0;
  return holdingDays > 365 ? profit * 0.05 : profit * 0.075;
};

export const calculateNepseProfit = (
  buyPrice: number,
  sellPrice: number,
  quantity: number,
  holdingDays = 400,
): NepseProfitResult => {
  const qty = Number(quantity) || 0;
  const buyAmount = (Number(buyPrice) || 0) * qty;
  const sellAmount = (Number(sellPrice) || 0) * qty;
  const buyBroker = brokerCommission(buyAmount);
  const buySebon = sebonFee(buyAmount);
  const totalBuyCost = buyAmount + buyBroker + buySebon;
  const sellBroker = brokerCommission(sellAmount);
  const sellSebon = sebonFee(sellAmount);
  const totalSellCost = sellBroker + sellSebon + dpCharge();
  const moneyReceived = sellAmount - totalSellCost;
  const grossProfit = moneyReceived - totalBuyCost;
  const tax = capitalGainTax(grossProfit, holdingDays);
  const finalProfit = grossProfit - tax;

  return {
    buyAmount,
    sellAmount,
    buyBroker,
    buySebon,
    sellBroker,
    sellSebon,
    dpCharge: dpCharge(),
    grossProfit,
    tax,
    finalProfit,
    profitPercent: totalBuyCost > 0 ? ((finalProfit / totalBuyCost) * 100).toFixed(2) : '0.00',
    totalBuyCost,
    totalSellCost,
    moneyReceived,
  };
};

export const calculateQuantityFromAmount = (
  amount: number,
  price: number,
  lotSize: number,
) => {
  const value = Number(amount) || 0;
  const unitPrice = Number(price) || 0;
  if (!Number.isFinite(value) || !Number.isFinite(unitPrice) || unitPrice <= 0) {
    return { quantity: 0, estimatedAmount: 0, unusedAmount: Math.max(0, value) };
  }

  const rawQty = Math.floor(value / unitPrice);
  const quantity = roundDownToBoardLot(rawQty, lotSize);
  const estimatedAmount = quantity * unitPrice;
  return {
    quantity,
    estimatedAmount,
    unusedAmount: Math.max(0, value - estimatedAmount),
  };
};

export const getOrderEstimate = (input: OrderEstimateInput): OrderEstimate => {
  const quantity = Math.max(0, Number(input.quantity) || 0);
  const price = Math.max(0, Number(input.price) || 0);
  const grossAmount = quantity * price;
  const investmentAmount = Number(input.investmentAmount || 0);

  if (input.side === 'BUY') {
    const estimatedCost =
      grossAmount > 0 ? grossAmount + brokerCommission(grossAmount) + sebonFee(grossAmount) : 0;
    return {
      quantity,
      grossAmount,
      estimatedCost,
      unusedAmount: investmentAmount > 0 ? Math.max(0, investmentAmount - grossAmount) : 0,
      priceSource: input.priceSource || 'User price / selected buy price',
      netEstimateAvailable: false,
    };
  }

  const buyPrice = Number(input.averageBuyPrice || 0);
  if (buyPrice > 0 && price > 0 && quantity > 0) {
    const profitResult = calculateNepseProfit(
      buyPrice,
      price,
      quantity,
      Number(input.holdingDays || 400),
    );
    return {
      quantity,
      grossAmount,
      netReceivable: profitResult.moneyReceived - profitResult.tax,
      profitResult,
      unusedAmount: investmentAmount > 0 ? Math.max(0, investmentAmount - grossAmount) : 0,
      priceSource: input.priceSource || 'User sell price / selected sell price',
      netEstimateAvailable: true,
    };
  }

  return {
    quantity,
    grossAmount,
    netReceivable: undefined,
    profitResult: null,
    unusedAmount: investmentAmount > 0 ? Math.max(0, investmentAmount - grossAmount) : 0,
    priceSource: input.priceSource || 'User sell price / selected sell price',
    netEstimateAvailable: false,
  };
};
