import { useEffect, useState } from 'react';
import { api } from './client';
import type { PublicConfig } from './types';

let cached: PublicConfig | null = null;
let pending: Promise<PublicConfig> | null = null;

export function loadPublicConfig(): Promise<PublicConfig> {
  if (cached) return Promise.resolve(cached);
  if (!pending) {
    pending = api<PublicConfig>('/config')
      .then((config) => {
        cached = config;
        return config;
      })
      .finally(() => {
        pending = null;
      });
  }
  return pending;
}

export function usePublicConfig() {
  const [config, setConfig] = useState<PublicConfig | null>(cached);
  useEffect(() => {
    if (!cached) {
      loadPublicConfig().then(setConfig).catch(() => undefined);
    }
  }, []);
  return config;
}
