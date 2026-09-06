import Link from "next/link";
import { getReview, getReviewTraces } from "@/lib/api";
import TraceViewer from "@/components/TraceViewer";

const severityColor: Record<string, string> = {
  low: "bg-blue-100 text-blue-700",
  medium: "bg-yellow-100 text-yellow-700",
  high: "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
};

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const reviewId = Number(id);

  const [review, traces] = await Promise.all([
    getReview(reviewId),
    getReviewTraces(reviewId),
  ]);

  return (
    <main className="max-w-3xl mx-auto py-12 px-4">
      <Link
        href="/"
        className="text-sm text-gray-500 hover:underline"
      >
        &larr; Back
      </Link>

      <h1 className="text-2xl font-bold mt-2">
        #{review.pull_request.github_pr_number}{" "}
        {review.pull_request.title}
      </h1>

      <p className="text-sm text-gray-400 mb-2">
        by {review.pull_request.author}
      </p>

      <p className="text-sm text-gray-500 mb-6">
        {review.tokens_used} tokens &middot;{" "}
        {review.turns_taken} turns &middot; status:{" "}
        {review.status}
      </p>

      <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 mb-8">
        <h2 className="font-semibold mb-2">
          Summary
        </h2>

        <p className="text-sm text-gray-700 whitespace-pre-wrap">
          {review.summary}
        </p>
      </div>

      <h2 className="font-semibold mb-3">
        Findings ({review.findings.length})
      </h2>

      <ul className="space-y-3 mb-10">
        {review.findings.map((finding) => (
          <li
            key={finding.id}
            className="rounded-lg border border-gray-200 p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`text-xs px-2 py-1 rounded-full ${
                  severityColor[finding.severity] ?? ""
                }`}
              >
                {finding.severity}
              </span>

              <span className="text-xs text-gray-500">
                {finding.category}
              </span>

              <span className="text-xs text-gray-400 ml-auto">
                confidence{" "}
                {(finding.confidence * 100).toFixed(0)}%
              </span>
            </div>

            <div className="text-sm font-mono text-gray-600 mb-1">
              {finding.file}:{finding.line_start}-
              {finding.line_end}
            </div>

            <p className="text-sm text-gray-800">
              {finding.explanation}
            </p>

            {finding.suggested_fix && (
              <p className="text-sm text-gray-500 mt-2">
                <span className="font-medium">
                  Suggested fix:
                </span>{" "}
                {finding.suggested_fix}
              </p>
            )}
          </li>
        ))}
      </ul>

      <h2 className="font-semibold mb-3">
        Agent trace
      </h2>

      <TraceViewer traces={traces} />
    </main>
  );
}