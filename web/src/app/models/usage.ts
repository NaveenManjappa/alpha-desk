/** Mirrors `RunUsage` in `src/alphadesk/domain/usage.py`. Change both in the same commit. */

/** What one run used. Every value is worked out by the API; the UI only formats them. */
export interface RunUsage {
  duration_seconds: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}
