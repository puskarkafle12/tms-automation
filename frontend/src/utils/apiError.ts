import axios from 'axios';

export const extractApiErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown; message?: unknown } | undefined;
    if (typeof data?.detail === 'string' && data.detail.trim()) {
      return data.detail;
    }
    if (data && Array.isArray(data.detail)) {
      return data.detail.map((item) => String(item)).join(', ');
    }
    if (typeof data?.message === 'string' && data.message.trim()) {
      return data.message;
    }
    if (error.message) {
      return error.message;
    }
  }

  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
};
