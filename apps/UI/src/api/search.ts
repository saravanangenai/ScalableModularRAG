import { apiFetch } from "./client";

export interface SearchResult {
  document_id: string;
  document_version_id: string;
  filename: string | null;
  content_type: "page_text_plus_ocr" | "table" | "image" | null;
  page_number: number | null;
  chunk_index: number | null;
  table_index: number | null;
  image_index: number | null;
  image_path: string | null;
  text: string | null;
  score: number;
}

export function search(
  accessToken: string | undefined,
  workspaceId: string,
  query: string,
  k = 8,
): Promise<{ results: SearchResult[] }> {
  return apiFetch<{ results: SearchResult[] }>(`/workspaces/${workspaceId}/search`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k }),
  });
}
