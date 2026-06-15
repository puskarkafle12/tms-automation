export interface ScripLotMetadata {
  symbol?: string | null;
  scrip?: string | null;
  symbolName?: string | null;
  securityName?: string | null;
  lotSize?: number | string | null;
  boardLot?: number | string | null;
  boardLotSize?: number | string | null;
  faceValue?: number | string | null;
  security?: ScripLotMetadata | null;
}

const DEFAULT_BOARD_LOT_SIZE = 10;

const positiveNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

export const getBoardLotSize = (scrip?: ScripLotMetadata | null): number => {
  const metadata = scrip || {};
  const nested = metadata.security || {};
  const configuredLot =
    positiveNumber(metadata.lotSize) ||
    positiveNumber(metadata.boardLot) ||
    positiveNumber(metadata.boardLotSize) ||
    positiveNumber(nested.lotSize) ||
    positiveNumber(nested.boardLot) ||
    positiveNumber(nested.boardLotSize);

  if (configuredLot) {
    return Math.max(1, Math.floor(configuredLot));
  }

  const faceValue = positiveNumber(metadata.faceValue) || positiveNumber(nested.faceValue);
  if (faceValue === 100) return 10;
  if (faceValue === 10) return 100;
  if (faceValue === 1000) return 1;
  return DEFAULT_BOARD_LOT_SIZE;
};

export const isOddLotQty = (qty: number, lotSize: number) => qty > 0 && qty < lotSize;

export const isRegularLotQty = (qty: number, lotSize: number) =>
  qty > 0 && qty % Math.max(1, lotSize) === 0;

export const roundDownToBoardLot = (qty: number, lotSize: number) => {
  const size = Math.max(1, lotSize);
  return Math.floor(Math.max(0, qty) / size) * size;
};

export const wouldLeaveOddRemainder = (holdingQty: number, sellQty: number, lotSize: number) => {
  const remaining = holdingQty - sellQty;
  return remaining > 0 && remaining < lotSize;
};

export interface NormalizedSellQty {
  qty: number;
  remaining: number;
  isSellAll: boolean;
  warning?: string;
  error?: string;
}

export const normalizeSellQty = (
  desiredQty: number,
  holdingQty: number,
  lotSize: number,
): NormalizedSellQty => {
  const size = Math.max(1, lotSize);
  const requested = Math.max(0, Math.floor(desiredQty));
  const holding = Math.max(0, Math.floor(holdingQty));

  if (requested >= holding) {
    return {
      qty: holding,
      remaining: 0,
      isSellAll: true,
      warning: isRegularLotQty(holding, size)
        ? undefined
        : 'Sell All may include odd-lot quantity because your holding is not a board-lot multiple.',
    };
  }

  let roundedQty = roundDownToBoardLot(requested, size);
  const initialRemaining = holding - roundedQty;
  if (initialRemaining > 0 && initialRemaining < size) {
    roundedQty -= size;
  }
  if (roundedQty <= 0) {
    return {
      qty: 0,
      remaining: holding,
      isSellAll: false,
      error: 'Partial sell would leave odd-lot shares. Use Sell All or adjust quantity.',
    };
  }

  const remaining = holding - roundedQty;
  return {
    qty: roundedQty,
    remaining,
    isSellAll: false,
    warning:
      roundedQty !== requested
        ? holding - requested > 0 && holding - requested < size
          ? `Selling ${requested} would leave ${holding - requested} kitta odd lot. Suggested safe quantity: ${roundedQty}.`
          : `Suggested board-lot safe quantity: ${roundedQty}.`
        : undefined,
  };
};

export const calculateBoardLotQuantityFromAmount = (
  investmentAmount: number,
  price: number,
  lotSize: number,
) => {
  if (investmentAmount <= 0 || price <= 0) {
    return { quantity: 0, estimatedAmount: 0, unusedAmount: Math.max(0, investmentAmount || 0) };
  }
  const rawQty = Math.floor(investmentAmount / price);
  const quantity = roundDownToBoardLot(rawQty, lotSize);
  const estimatedAmount = quantity * price;
  return {
    quantity,
    estimatedAmount,
    unusedAmount: Math.max(0, investmentAmount - estimatedAmount),
  };
};
