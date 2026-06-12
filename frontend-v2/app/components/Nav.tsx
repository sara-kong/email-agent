'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const links = [
  { href: '/', label: 'Dashboard' },
  { href: '/inbox', label: 'Inbox' },
  { href: '/campaigns', label: 'Campaigns' },
]

export default function Nav() {
  const pathname = usePathname()

  return (
    <div className="border-b border-stone-100 bg-white">
      <div className="max-w-6xl mx-auto px-6 h-12 flex items-center gap-1">
        <span className="text-sm font-medium text-stone-800 mr-4">Email OS</span>
        {links.map(l => (
          <Link
            key={l.href}
            href={l.href}
            className={`text-sm px-3 py-1.5 rounded-lg transition ${
              pathname === l.href
                ? 'bg-teal-50 text-teal-700'
                : 'text-stone-400 hover:text-stone-600'
            }`}
          >
            {l.label}
          </Link>
        ))}
      </div>
    </div>
  )
}
