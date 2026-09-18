export const ORIGIN: string;
export const PREFIX: string;
export const PASSWORD: string;
export const CODE: string;
export interface Receipt {
  events: { method: string; host: string; path: string }[];
  exchange_count: number; external_attempts: number; entered: boolean; status_entered: boolean;
  pointer: string | null; offset: number; private_input_leaks: number; exit?: number;
}
export class AuthHost {
  root: string;
  logs: string;
  process: { exitCode: number | null };
  start(offset?: number): Promise<void>;
  command(op: string, extra?: Record<string, unknown>): Promise<Receipt>;
  configure(values: Record<string, unknown>): Promise<Receipt>;
  stop(): Promise<void>;
  close(): Promise<void>;
}
export function attackServer(): Promise<() => Promise<void>>;
