import { ScheduledOrder, TmsAccount, TmsAccountPayload } from '../api/tmsAccounts.api';

export type TmsExportType = 'users-only' | 'users-with-data';

export interface TmsExportUserWithData {
  user: TmsAccountPayload;
  scheduledOrders: ScheduledOrder[];
  metadata: Record<string, unknown>;
}

export interface TmsUsersOnlyExport {
  version: 1;
  type: 'users-only';
  exportedAt: string;
  users: TmsAccountPayload[];
}

export interface TmsUsersWithDataExport {
  version: 1;
  type: 'users-with-data';
  exportedAt: string;
  users: TmsExportUserWithData[];
}

export type TmsExportData = TmsUsersOnlyExport | TmsUsersWithDataExport;

export interface ImportPreview {
  uniqueUsers: number;
  scheduledOrders: number;
  duplicateUsers: number;
  duplicateScheduledOrders: number;
}

export interface ParsedImportData {
  users: Array<{
    user: TmsAccountPayload;
    scheduledOrders: ScheduledOrder[];
    metadata: Record<string, unknown>;
  }>;
  preview: ImportPreview;
  skippedScheduledOrders: number;
}

const accountKey = (account: Pick<TmsAccountPayload, 'broker_no' | 'client_id'>) =>
  `${String(account.broker_no || '').trim()}::${String(account.client_id || '').trim().toUpperCase()}`;

const scheduledOrderKey = (order: ScheduledOrder) => {
  if (order.order_id != null) {
    return `id::${order.order_id}`;
  }
  return [
    'fields',
    order.client_id,
    order.script_name,
    order.order_type,
    order.qty,
    order.price,
    order.status || 'pending',
  ]
    .map((value) => String(value ?? '').trim().toUpperCase())
    .join('::');
};

const toAccountPayload = (value: unknown): TmsAccountPayload | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const raw = value as Record<string, unknown>;
  const clientId = String(raw.client_id ?? '').trim();
  const brokerNo = String(raw.broker_no ?? '').trim();
  const password = String(raw.password ?? '').trim();
  if (!clientId || !brokerNo || !password) {
    return null;
  }
  return {
    client_id: clientId,
    broker_no: brokerNo,
    password,
    auto_login: typeof raw.auto_login === 'boolean' ? raw.auto_login : true,
  };
};

const toScheduledOrder = (value: unknown, fallbackClientId: string): ScheduledOrder | null => {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const raw = value as Record<string, unknown>;
  const clientId = String(raw.client_id ?? fallbackClientId).trim();
  const scriptName = String(raw.script_name ?? '').trim().toUpperCase();
  const orderType = String(raw.order_type ?? '').trim().toLowerCase();
  const price = Number(raw.price);
  const qty = Number(raw.qty);
  if (!clientId || !scriptName || !orderType || !Number.isFinite(price) || !Number.isFinite(qty)) {
    return null;
  }
  return {
    client_id: clientId,
    security_details:
      raw.security_details && typeof raw.security_details === 'object'
        ? (raw.security_details as Record<string, unknown>)
        : {},
    script_name: scriptName,
    price,
    qty,
    order_type: orderType,
    status: String(raw.status ?? 'pending').trim() || 'pending',
    order_id: typeof raw.order_id === 'number' ? raw.order_id : undefined,
    last_updated: typeof raw.last_updated === 'string' ? raw.last_updated : null,
  };
};

export const buildExportData = (
  type: TmsExportType,
  accounts: TmsAccount[],
  scheduledOrders: ScheduledOrder[],
): TmsExportData => {
  const exportedAt = new Date().toISOString();
  const accountPayloads = accounts
    .map(toAccountPayload)
    .filter((account): account is TmsAccountPayload => Boolean(account));

  if (type === 'users-only') {
    return {
      version: 1,
      type,
      exportedAt,
      users: accountPayloads,
    };
  }

  return {
    version: 1,
    type,
    exportedAt,
    users: accountPayloads.map((account) => ({
      user: account,
      scheduledOrders: scheduledOrders.filter((order) => order.client_id === account.client_id),
      metadata: {
        session_status: accounts.find((item) => item.client_id === account.client_id)?.session_status || 'logged_out',
      },
    })),
  };
};

export const exportTmsData = (
  type: TmsExportType,
  accounts: TmsAccount[],
  scheduledOrders: ScheduledOrder[],
) => JSON.stringify(buildExportData(type, accounts, scheduledOrders), null, 2);

export const validateImportData = (value: unknown, importType: TmsExportType): ParsedImportData => {
  if (!value || typeof value !== 'object') {
    throw new Error('No users found in this file');
  }
  const raw = value as Record<string, unknown>;
  const rawUsers = Array.isArray(raw.users)
    ? raw.users
    : Array.isArray(raw.accounts)
      ? raw.accounts
      : [];
  if (rawUsers.length === 0) {
    throw new Error('No users found in this file');
  }

  const byAccount = new Map<string, ParsedImportData['users'][number]>();
  let duplicateUsers = 0;
  let duplicateScheduledOrders = 0;
  let skippedScheduledOrders = 0;

  for (const item of rawUsers) {
    const container = item && typeof item === 'object' ? (item as Record<string, unknown>) : {};
    const userValue = container.user || container.account || item;
    const user = toAccountPayload(userValue);
    if (!user) {
      throw new Error('Some required user fields are missing');
    }

    const key = accountKey(user);
    const existing = byAccount.get(key);
    const target =
      existing ||
      {
        user,
        scheduledOrders: [],
        metadata:
          container.metadata && typeof container.metadata === 'object'
            ? (container.metadata as Record<string, unknown>)
            : {},
      };
    if (existing) {
      duplicateUsers += 1;
    }

    if (importType === 'users-with-data') {
      const incomingOrders = Array.isArray(container.scheduledOrders) ? container.scheduledOrders : [];
      const orderKeys = new Set(target.scheduledOrders.map(scheduledOrderKey));
      for (const orderValue of incomingOrders) {
        const order = toScheduledOrder(orderValue, user.client_id);
        if (!order) {
          skippedScheduledOrders += 1;
          continue;
        }
        order.client_id = user.client_id;
        const orderKey = scheduledOrderKey(order);
        if (orderKeys.has(orderKey)) {
          duplicateScheduledOrders += 1;
          continue;
        }
        orderKeys.add(orderKey);
        target.scheduledOrders.push(order);
      }
    }

    byAccount.set(key, target);
  }

  const users = Array.from(byAccount.values());
  const scheduledOrders = users.reduce((count, user) => count + user.scheduledOrders.length, 0);
  return {
    users,
    preview: {
      uniqueUsers: users.length,
      scheduledOrders,
      duplicateUsers,
      duplicateScheduledOrders,
    },
    skippedScheduledOrders,
  };
};

export const parseImportData = (jsonText: string, importType: TmsExportType): ParsedImportData => {
  try {
    return validateImportData(JSON.parse(jsonText), importType);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error('Invalid JSON format');
    }
    throw error;
  }
};

export const downloadJsonFile = (json: string, type: TmsExportType) => {
  const date = new Date().toISOString().slice(0, 10);
  const filename = type === 'users-only'
    ? `tms-users-export-${date}.json`
    : `tms-data-export-${date}.json`;
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

export const copyJsonToClipboard = (json: string) => navigator.clipboard.writeText(json);
