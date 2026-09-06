import Link from "next/link";
import { getRepos } from "@/lib/api";

export default async function HomePage() {
  const repos = await getRepos();

  return (
    <main className="max-w-3xl mx-auto py-12 px-4">
      <h1 className="text-2xl font-bold mb-6">
        PR Sentinel
      </h1>

      <p className="text-gray-500 mb-8">
        Connected repositories and their review activity.
      </p>

      {repos.length === 0 && (
        <p className="text-gray-400">
          No repos connected yet. Install the GitHub App on a
          repo to get started.
        </p>
      )}

      <ul className="space-y-3">
        {repos.map((repo) => (
          <li key={repo.id}>
            <Link
              href={`/repos/${repo.id}`}
              className="block rounded-lg border border-gray-200 p-4 hover:border-gray-400 transition-colors"
            >
              <div className="flex justify-between items-center">
                <span className="font-medium">
                  {repo.full_name}
                </span>

                <span className="text-sm text-gray-500">
                  {repo.review_count} review(s)
                </span>
              </div>

              <div className="text-xs text-gray-400 mt-1">
                Last indexed:{" "}
                {repo.last_indexed_at ?? "never"}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}