/** Mirrors `ChatRequest` in `src/alphadesk/api/routes.py`. Change both in the same commit. */

/** The body of `POST /chat`. */
export interface ChatRequest {
  message: string;
  /** Names the conversation. Letters, digits, "-" and "_" only. */
  thread_id: string;
}
