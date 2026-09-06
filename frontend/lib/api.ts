import type {
  RepoSummary,
  PullRequestSummary,
  ReviewDetail,
  AgentTraceEntry,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(
    `${API_URL}${path}`,
    { cache: "no-store" }
  );

  if (!res.ok) {
    throw new Error(
      `API request failed: ${res.status} ${res.statusText}`
    );
  }

  return res.json();
}

export function getRepos() {
  return apiFetch<RepoSummary[]>("/repos");
}

export function getRepoPulls(repoId: number) {
  return apiFetch<{
    repo: {
      id: number;
      full_name: string;
    };
    pulls: PullRequestSummary[];
  }>(`/repos/${repoId}/pulls`);
}

export function getReview(reviewId: number) {
  return apiFetch<ReviewDetail>(
    `/reviews/${reviewId}`
  );
}

export function getReviewTraces(reviewId: number) {
  return apiFetch<AgentTraceEntry[]>(
    `/reviews/${reviewId}/traces`
  );
}
