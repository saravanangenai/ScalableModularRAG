function friendlyMessage(status: number, body: unknown): string {
  const detail =
    typeof body === "object" && body !== null && "detail" in body
      ? String((body as { detail: unknown }).detail)
      : undefined;

  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "You don't have permission to do that.";
    case 404:
      return "Not found.";
    case 429:
      return "You're doing that too much — please wait a moment and try again.";
    default:
      return detail ?? `Something went wrong (${status}).`;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(friendlyMessage(status, body));
  }
}

/** Thin typed fetch wrapper — attaches the bearer token, centralizes error handling.
 * specs/071-search-frontend/plan.md::api/client.ts. */
export async function apiFetch<T>(
  path: string,
  accessToken: string | undefined,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${import.meta.env.VITE_API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new Error("Network error — is the server reachable?");
  }

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
