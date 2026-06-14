'use client'

import { useEffect, useState } from 'react'
import { shortName, initials, badgeColors, avatarColors } from '@/lib/email'
import { apiFetch } from '@/lib/api'

const API = '/api'

export default function Dashboard() {
  const [analytics, setAnalytics] = useState<any>(null)
  const [emails, setEmails] = useState<any[]>([])
  const [contacts, setContacts] = useState<any[]>([])
  const [agentInput, setAgentInput] = useState('')
  const [agentResponse, setAgentResponse] = useState('')
  const [agentLoading, setAgentLoading] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      apiFetch(`${API}/analytics/overview`).then(r => r.json()),
      apiFetch(`${API}/inbox/emails?limit=8`).then(r => r.json()),
      apiFetch(`${API}/contacts?limit=6`).then(r => r.json()),
    ]).then(([a, e, c]) => {
      setAnalytics(a)
      setEmails(e.emails || [])
      setContacts(c.contacts || [])
      setLoading(false)
    })
  }, [])

  async function askAgent() {
    if (!agentInput.trim()) return
    setAgentLoading(true)
    setAgentResponse('')
    const res = await apiFetch(`${API}/agent/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: agentInput })
    })
    const data = await res.json()
    setAgentResponse(data.response)
    setAgentLoading(false)
  }

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-stone-50">
      <p className="text-stone-400 text-sm">Loading your inbox...</p>
    </div>
  )

  return (
    <div className="min-h-screen bg-stone-50 font-sans">
      <div className="max-w-4xl mx-auto px-6 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-medium text-stone-800">Good morning, Sara</h1>
          <p className="text-stone-400 text-sm mt-1">Here's what's happening across your inbox and relationships</p>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          {[
            { label: 'Emails indexed', value: analytics?.total_emails?.toLocaleString(), sub: `${analytics?.emails_by_category?.important || 0} important` },
            { label: 'Contacts', value: analytics?.total_contacts?.toLocaleString(), sub: 'relationship scored' },
            { label: 'Campaigns', value: '0', sub: 'none active yet' },
            { label: 'Open deals', value: '0', sub: 'pipeline empty' },
          ].map((m, i) => (
            <div key={i} className="bg-white rounded-xl border border-stone-100 p-4">
              <p className="text-xs text-stone-400 mb-1">{m.label}</p>
              <p className="text-2xl font-medium text-stone-800">{m.value}</p>
              <p className="text-xs text-stone-400 mt-1">{m.sub}</p>
            </div>
          ))}
        </div>
        <div className="bg-white rounded-xl border border-stone-100 p-4 mb-8">
          <div className="flex gap-3 items-center">
            <div className="w-8 h-8 rounded-full bg-teal-50 flex items-center justify-center text-teal-600 text-sm flex-shrink-0">✦</div>
            <input
              className="flex-1 text-sm text-stone-600 outline-none placeholder-stone-300 bg-transparent"
              placeholder="Ask anything about your inbox, contacts, or deals..."
              value={agentInput}
              onChange={e => setAgentInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && askAgent()}
            />
            <button onClick={askAgent} disabled={agentLoading} className="text-xs text-teal-600 font-medium hover:text-teal-700 disabled:text-stone-300">
              {agentLoading ? 'thinking...' : 'ask ↗'}
            </button>
          </div>
          {agentResponse && (
            <div className="mt-4 pt-4 border-t border-stone-100 text-sm text-stone-600 leading-relaxed whitespace-pre-wrap">
              {agentResponse}
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
          <div className="bg-white rounded-xl border border-stone-100 p-4">
            <p className="text-sm font-medium text-stone-700 mb-3">Recent inbox</p>
            <div className="space-y-3">
              {emails.slice(0, 6).map((e, i) => (
                <div key={e.gmail_id} className="flex items-start gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0 ${avatarColors[i % avatarColors.length]}`}>
                    {initials(shortName(e.sender))}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-stone-700 truncate">{shortName(e.sender)}</p>
                    <p className="text-xs text-stone-400 truncate">{e.subject}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${badgeColors[e.category] || badgeColors.unknown}`}>
                    {e.category}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="bg-white rounded-xl border border-stone-100 p-4">
            <p className="text-sm font-medium text-stone-700 mb-3">Top contacts</p>
            <div className="space-y-3">
              {contacts.slice(0, 6).map((c, i) => (
                <div key={c.id} className="flex items-center gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0 ${avatarColors[i % avatarColors.length]}`}>
                    {initials(shortName(c.name || c.email))}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-stone-700 truncate">{shortName(c.name || c.email)}</p>
                    <p className="text-xs text-stone-400">{c.contact_type}</p>
                  </div>
                  <div className="text-right w-12 flex-shrink-0">
                    <div className="h-1 bg-stone-100 rounded-full overflow-hidden">
                      <div className="h-full bg-teal-400 rounded-full" style={{ width: `${Math.min(c.relationship_score, 100)}%` }} />
                    </div>
                    <p className="text-xs text-stone-300 mt-1">{Math.round(c.relationship_score)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-stone-100 p-4">
          <p className="text-sm font-medium text-stone-700 mb-4">Inbox breakdown</p>
          <div className="space-y-3">
            {Object.entries(analytics?.emails_by_category || {}).map(([cat, count]: any) => (
              <div key={cat}>
                <div className="flex justify-between text-xs text-stone-400 mb-1">
                  <span>{cat}</span><span>{count}</span>
                </div>
                <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{
                    width: `${Math.round((count / analytics.total_emails) * 100)}%`,
                    background: cat === 'important' ? '#2dd4bf' : cat === 'marketing' ? '#f59e0b' : cat === 'social' ? '#8b5cf6' : '#d6d3d1'
                  }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
