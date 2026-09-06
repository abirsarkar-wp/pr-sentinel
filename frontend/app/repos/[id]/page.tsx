import Link from "next/link";
import { getRepoPulls } from "@/lib/api";

const statusColor: Record<string, string> = {
  posted: "bg-green-100 text-green-700",
  completed: "bg-blue-100 text-blue-700",
  post_failed: "bg-red-100 text-red-700",
  pending: "bg-gray-100 text-gray-600",
};

export default async function RepoPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const repoId = Number(id);

  const { repo, pulls } = await getRepoPulls(repoId);

  return (
    <main className="max-w-3xl mx-auto py-12 px-4">
      <Link
        href="/"
        className="text-sm text-gray-500 hover:underline"
      >
        &larr; All repos
      </Link>

      <h1 className="text-2xl font-bold mt-2 mb-6">
        {repo.full_name}
      </h1>

      {pulls.length === 0 ? (
        <p className="text-gray-400">
          No pull requests found.
        </p>
      ) : (
        <ul className="space-y-3">
          {pulls.map((pr) => (
            <li
              key={pr.id}
              className="rounded-lg border border-gray-200 p-4"
            >
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-medium">
                    #{pr.github_pr_number} {pr.title}
                  </div>

                  <div className="text-xs text-gray-400">
                    by {pr.author}
                  </div>
                </div>

                {pr.latest_review && (
                  <span
                    className={`text-xs px-2 py-1 rounded-full ${
                      statusColor[pr.latest_review.status] ??
                      "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {pr.latest_review.status}
                  </span>
                )}
              </div>

              {pr.latest_review ? (
                <div className="mt-3">
                  <p className="text-sm text-gray-600">
                    {pr.latest_review.summary}
                  </p>

                  <Link
                    href={`/reviews/${pr.latest_review.id}`}
                    className="text-sm text-blue-600 hover:underline mt-2 inline-block"
                  >
                    View findings &amp; trace &rarr;
                  </Link>
                </div>
              ) : (
                <p className="text-sm text-gray-400 mt-2">
                  No review yet.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
