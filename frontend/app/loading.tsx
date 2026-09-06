function Shimmer({ className }: { className: string }) { return <div className={`animate-pulse rounded-xl bg-slate-200/75 ${className}`} />; }

export default function Loading() {
  return <main className="mx-auto max-w-7xl px-5 pb-16 pt-12 sm:px-8 sm:pt-20" aria-label="Loading dashboard" aria-busy="true">
    <section className="rounded-3xl border border-indigo-100 bg-white px-7 py-11 sm:px-12 sm:py-16"><Shimmer className="h-7 w-48" /><Shimmer className="mt-7 h-12 max-w-xl" /><Shimmer className="mt-4 h-5 max-w-2xl" /></section>
    <section className="mt-14"><Shimmer className="h-7 w-44" /><div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <div key={index} className="rounded-2xl border border-slate-200 bg-white p-5"><Shimmer className="h-4 w-24" /><Shimmer className="mt-8 h-9 w-16" /><Shimmer className="mt-3 h-4 w-32" /></div>)}</div></section>
  </main>;
}
