import { getApiUrl } from '../utils/api';

const wait = (milliseconds: number, signal?: AbortSignal): Promise<void> => new Promise((resolve, reject) => {
  const timeoutId = window.setTimeout(resolve, milliseconds);
  signal?.addEventListener('abort', () => {
    window.clearTimeout(timeoutId);
    reject(new DOMException('The request was aborted.', 'AbortError'));
  }, { once: true });
});

export const fetchAiScreen = async (
  endpoint: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<Response> => {
  const response = await fetch(`${getApiUrl()}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, background: true }),
    signal,
  });

  if (response.status !== 202) {
    return response;
  }

  const accepted = await response.json() as { job_id?: string };
  if (!accepted.job_id) {
    throw new Error('Server accepted the AI screen but did not return a job ID.');
  }

  const statusUrl = `${getApiUrl()}/market_analysis/ai_screen/jobs/${encodeURIComponent(accepted.job_id)}`;
  while (true) {
    await wait(1000, signal);
    const statusResponse = await fetch(statusUrl, { signal });
    if (statusResponse.status !== 202) {
      return statusResponse;
    }
  }
};
