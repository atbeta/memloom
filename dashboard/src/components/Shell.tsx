import { NavLink, Outlet } from 'react-router-dom'
import { clearKey } from '@/lib/api'

const links = [
  { to: '/', label: 'Overview', end: true },
  { to: '/explorer', label: 'Explorer' },
  { to: '/pipeline', label: 'Pipeline' },
]

export function Shell() {
  return (
    <div className="mx-auto flex min-h-full max-w-7xl flex-col px-4 py-4 md:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div>
          <p className="font-mono text-xs tracking-[0.18em] text-accent uppercase">memloom</p>
          <h1 className="text-xl font-semibold tracking-tight">Memory console</h1>
        </div>
        <nav className="flex flex-wrap items-center gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                [
                  'px-3 py-1.5 text-sm',
                  isActive
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-muted hover:bg-panel hover:text-ink',
                ].join(' ')
              }
            >
              {l.label}
            </NavLink>
          ))}
          <button
            type="button"
            onClick={() => {
              clearKey()
              window.location.reload()
            }}
            className="ml-2 px-3 py-1.5 text-sm text-muted hover:text-ink"
          >
            Sign out
          </button>
        </nav>
      </header>
      <main className="flex-1 py-5">
        <Outlet />
      </main>
    </div>
  )
}
