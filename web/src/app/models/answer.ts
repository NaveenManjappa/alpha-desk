/**
 * Mirrors `src/alphadesk/domain/answer.py`. Change both in the same commit.
 *
 * Field names stay in snake_case, exactly as they arrive in the JSON, so there is no
 * mapping step to keep in step as well.
 */

/** One number in the answer, with where it came from. */
export interface KeyFigure {
  label: string;
  value: number;
  unit: string;
  period: string;
  source_url: string;
}

/** The answer contract: what the research agent returns. */
export interface Answer {
  summary: string;
  key_figures: KeyFigure[];
  sources: string[];
  /** ISO 8601 date and time. The age of the oldest data behind the answer. */
  as_of: string;
  /** True if every figure passed the API's grounding check. */
  verified: boolean;
  disclaimer: string;
}
