export interface Health {
  product: 'Visto';
  version: string;
  runtime_ready: boolean;
}

export type HealthState =
  | { kind: 'checking' }
  | { kind: 'connected'; health: Health; checkedAt: Date }
  | { kind: 'disconnected'; message: string };

type HealthFetch = (url: string, options: RequestInit) => Promise<Response>;

export async function loadHealth(
  fetcher: HealthFetch = fetch,
  signal?: AbortSignal,
): Promise<Health> {
  const response = await fetcher('/api/health', { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error('Invalid health response');
  }
  if (
    typeof data !== 'object' || data === null || Array.isArray(data) ||
    !('product' in data) || data.product !== 'Visto' ||
    !('version' in data) || typeof data.version !== 'string' || !data.version.trim() ||
    !('runtime_ready' in data) || typeof data.runtime_ready !== 'boolean'
  ) {
    throw new Error('Invalid health response');
  }
  return { product: data.product, version: data.version, runtime_ready: data.runtime_ready };
}

export function createHealthMonitor(
  publish: (state: HealthState) => void,
  fetcher: HealthFetch = fetch,
  timeoutMs = 5000,
) {
  let generation = 0;
  let active: AbortController | undefined;
  let disposed = false;

  return {
    async refresh(): Promise<void> {
      if (disposed) return;
      const request = ++generation;
      active?.abort();
      const controller = new AbortController();
      active = controller;
      publish({ kind: 'checking' });
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeoutMs);
      try {
        const health = await loadHealth(fetcher, controller.signal);
        if (request === generation && !disposed) {
          publish({ kind: 'connected', health, checkedAt: new Date() });
        }
      } catch {
        if (request === generation && !disposed) {
          publish({
            kind: 'disconnected',
            message: timedOut
              ? 'The local backend did not respond in time. Refresh to try again.'
              : 'Cannot reach the local backend. Check that it is running, then refresh.',
          });
        }
      } finally {
        clearTimeout(timer);
        if (request === generation) active = undefined;
      }
    },
    dispose(): void {
      disposed = true;
      generation += 1;
      active?.abort();
    },
  };
}
