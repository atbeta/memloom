import { NavLink, Outlet } from 'react-router-dom'
import { clearKey } from '@/lib/api'

const links = [
  { to: '/', label: 'Overview', end: true },
  { to: '/explorer', label: 'Explorer' },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/settings', label: 'Settings' },
]

export function Shell() {
  return (
    <div className="mx-auto flex min-h-full max-w-7xl flex-col px-5 py-5 md:px-8 md:py-6">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
        <div className="space-y-1">
          <p className="font-mono text-[11px] tracking-[0.2em] text-accent uppercase">memloom</p>
          <h1 className="text-xl font-semibold tracking-tight md:text-[1.35rem]">Memory console</h1>
        </div>
        <nav className="flex flex-wrap items-center gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                [
                  'btn rounded-md px-3.5 py-1.5',
                  isActive ? 'btn-soft-active' : 'btn-ghost',
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
            className="btn btn-ghost ml-1"
          >
            Sign out
          </button>
        </nav>
      </header>
      <main className="flex-1 py-6 md:py-7">
        <Outlet />
      </main>
    </div>
  )
}
