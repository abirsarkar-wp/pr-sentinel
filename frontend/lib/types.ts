export interface RepoSummary {
  id: number;
  full_name: string;
  connected_at: string | null;
  last_indexed_at: string | null;
  review_count: number;
}

export interface LatestReview {
  id: number;
  status: string;
  summary: string;
  tokens_used: number | null;
  turns_taken: number | null;
}

export interface PullRequestSummary {
  id: number;
  github_pr_number: number;
  title: string;
  author: string;
  status: string;
  latest_review: LatestReview | null;
}

export interface Finding {
  id: number;
  file: string;
  line_start: number;
  line_end: number;
  category: string;
  severity: string;
  explanation: string;
  suggested_fix: string | null;
  confidence: number;
}

export interface ReviewDetail {
  id: number;
  status: string;
  summary: string;
  tokens_used: number | null;
  turns_taken: number | null;
  created_at: string | null;
  pull_request: {
    id: number;
    github_pr_number: number;
    title: string;
    author: string;
  };
  findings: Finding[];
}

export interface AgentTraceEntry {
  turn_number: number;
  role: string;
  content_json: unknown;
  latency_ms: number | null;
  created_at: string | null;
}
