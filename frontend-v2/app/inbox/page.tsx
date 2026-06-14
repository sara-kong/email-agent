'use client'

import { useEffect, useState } from 'react'
import { shortName, initials, badgeColors, avatarColors, formatDate } from '@/lib/email'
import { apiFetch } from '@/lib/api'

const API = '/api'

type EmailRow = {
  id: number
  gmail_id: string
  thread_id: string
  sender: string
  subject: string
  snippet: string
  full_text: string
  category: string
  action: string
  importance: string
  summary: string
  created_at: string
  draft_status?: string
  draft_text?: string
}

type ThreadMessage = {
  gmail_id: string
  thread_id: string
  sender: string
  subject: string
  date: string
  full_body: string
}

const CATEGORIES = ['important', 'marketing', 'social', 'historical', 'unknown']

function StarIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
    </svg>
  )
}

function ArchiveIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <rect width="20" height="5" x="2" y="3" rx="1" />
      <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />
      <path d="M10 12h4" />
    </svg>
  )
}

function TagIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z" />
      <circle cx="7.5" cy="7.5" r=".5" fill="currentColor" />
    </svg>
  )
}

function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 2l1.5 4.5L18 8l-4.5 1.5L12 14l-1.5-4.5L6 8l4.5-1.5z" />
      <path d="M19 14l.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8z" />
    </svg>
  )
}

export default function InboxPage() {
  const [emails, setEmails] = useState<EmailRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')

  const [selected, setSelected] = useState<EmailRow | null>(null)
  const [thread, setThread] = useState<ThreadMessage[]>([])
  const [threadLoading, setThreadLoading] = useState(false)

  const [reply, setReply] = useState('')
  const [replyLoading, setReplyLoading] = useState(false)
  const [draftStatus, setDraftStatus] = useState<'idle' | 'creating' | 'created' | 'error'>('idle')
  const [sendStatus, setSendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  const [correctingId, setCorrectingId] = useState<string | null>(null)
  const [correctedFlash, setCorrectedFlash] = useState<string | null>(null)

  useEffect(() => {
    loadEmails(filter)
  }, [filter])

  async function loadEmails(category: string) {
    setLoading(true)
    const qs = category ? `&label=${category}` : ''
    const res = await apiFetch(`${API}/inbox/emails?limit=30${qs}`)
    const data = await res.json()
    setEmails(data.emails || [])
    setLoading(false)
  }

  async function openEmail(email: EmailRow) {
    setSelected(email)
    setReply(email.draft_status === 'ready' ? (email.draft_text || '') : '')
    setDraftStatus('idle')
    setSendStatus('idle')
    setThread([])
    setThreadLoading(true)
    try {
      const res = await apiFetch(`${API}/inbox/threads/${email.thread_id}`)
      const data = await res.json()
      setThread(data.messages || [])
    } catch {
      setThread([])
    } finally {
      setThreadLoading(false)
    }
  }

  async function correctEmail(email: EmailRow, category: string, action: string) {
    if (correctingId === email.gmail_id) return

    const previous = { category: email.category, action: email.action }

    // Optimistic update
    setEmails(list => list.map(em => em.gmail_id === email.gmail_id ? { ...em, category, action } : em))
    setSelected(s => (s && s.gmail_id === email.gmail_id ? { ...s, category, action } : s))
    setCorrectingId(email.gmail_id)

    try {
      const res = await apiFetch(`${API}/inbox/emails/${email.gmail_id}/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category, action }),
      })
      if (!res.ok) throw new Error('failed')
      setCorrectedFlash(email.gmail_id)
      setTimeout(() => setCorrectedFlash(f => (f === email.gmail_id ? null : f)), 1500)
    } catch {
      // revert on failure
      setEmails(list => list.map(em => em.gmail_id === email.gmail_id ? { ...em, ...previous } : em))
      setSelected(s => (s && s.gmail_id === email.gmail_id ? { ...s, ...previous } : s))
    } finally {
      setCorrectingId(null)
    }
  }

  async function generateReply() {
    if (!selected) return
    setReplyLoading(true)
    setDraftStatus('idle')
    try {
      const res = await apiFetch(`${API}/inbox/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gmail_id: selected.gmail_id,
          email_text: selected.full_text,
          thread_summary: selected.summary || '',
          auto_send: false,
        }),
      })
      const data = await res.json()
      setReply(data.reply || '')
    } catch {
      // leave reply box as-is
    } finally {
      setReplyLoading(false)
    }
  }

  async function createDraft() {
    if (!selected || !reply.trim()) return
    setDraftStatus('creating')
    try {
      const res = await apiFetch(`${API}/inbox/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gmail_id: selected.gmail_id,
          email_text: selected.full_text,
          thread_summary: selected.summary || '',
          auto_send: true,
          final_text: reply,
        }),
      })
      if (!res.ok) throw new Error('failed')
      setDraftStatus('created')
    } catch {
      setDraftStatus('error')
    }
  }

  async function sendDraft() {
    if (!selected || !reply.trim()) return
    if (!window.confirm('Send this email now? This will actually send via Gmail.')) return

    setSendStatus('sending')
    try {
      const res = await apiFetch(`${API}/inbox/emails/${selected.gmail_id}/draft/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_text: reply }),
      })
      if (!res.ok) throw new Error('failed')
      setSendStatus('sent')
      setEmails(list => list.map(em => em.gmail_id === selected.gmail_id ? { ...em, draft_status: 'sent' } : em))
      setSelected(s => (s && s.gmail_id === selected.gmail_id ? { ...s, draft_status: 'sent' } : s))
    } catch {
      setSendStatus('error')
    }
  }

  return (
    <div className="min-h-screen bg-stone-50 font-sans">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-medium text-stone-800">Inbox</h1>
            <p className="text-stone-400 text-sm mt-1">Browse threads and draft replies in your voice</p>
          </div>
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="text-xs text-stone-500 bg-white border border-stone-200 rounded-lg px-3 py-1.5 outline-none"
          >
            <option value="">All categories</option>
            {CATEGORIES.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 items-start">
          {/* Email list */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-stone-100 overflow-hidden">
            <div className="max-h-[75vh] overflow-y-auto divide-y divide-stone-50">
              {loading ? (
                <p className="text-sm text-stone-400 p-4">Loading inbox...</p>
              ) : emails.length === 0 ? (
                <p className="text-sm text-stone-400 p-4">No emails found.</p>
              ) : emails.map((e, i) => (
                <div
                  key={e.gmail_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => openEmail(e)}
                  onKeyDown={ev => { if (ev.key === 'Enter' || ev.key === ' ') openEmail(e) }}
                  className={`group w-full text-left flex items-start gap-3 p-3 cursor-pointer transition hover:bg-stone-50 ${
                    selected?.gmail_id === e.gmail_id ? 'bg-teal-50/60' : ''
                  }`}
                >
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0 ${avatarColors[i % avatarColors.length]}`}>
                    {initials(shortName(e.sender))}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-stone-700 truncate">{shortName(e.sender)}</p>
                      <span className="text-xs text-stone-300 flex-shrink-0">{formatDate(e.created_at)}</span>
                    </div>
                    <p className="text-sm text-stone-700 truncate">{e.subject}</p>
                    <p className="text-xs text-stone-400 truncate">{e.snippet}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1 flex-shrink-0">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${badgeColors[e.category] || badgeColors.unknown}`}>
                      {e.category}
                    </span>
                    {e.draft_status === 'ready' && (
                      <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-teal-50 text-teal-600">
                        <SparkleIcon className="w-3 h-3" />
                        draft ready
                      </span>
                    )}
                    <div className="h-4 flex items-center gap-0.5">
                      {correctedFlash === e.gmail_id ? (
                        <span className="text-xs text-teal-600">✓</span>
                      ) : (
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
                          <button
                            title="Mark important"
                            onClick={ev => { ev.stopPropagation(); correctEmail(e, 'important', 'reply') }}
                            className="p-1 rounded text-stone-400 hover:text-teal-600 hover:bg-teal-50"
                          >
                            <StarIcon className="w-3.5 h-3.5" />
                          </button>
                          <button
                            title="Not important"
                            onClick={ev => { ev.stopPropagation(); correctEmail(e, 'unknown', 'archive') }}
                            className="p-1 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100"
                          >
                            <ArchiveIcon className="w-3.5 h-3.5" />
                          </button>
                          <button
                            title="This is marketing"
                            onClick={ev => { ev.stopPropagation(); correctEmail(e, 'marketing', 'archive') }}
                            className="p-1 rounded text-stone-400 hover:text-amber-600 hover:bg-amber-50"
                          >
                            <TagIcon className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Thread + reply composer */}
          <div className="lg:col-span-3 bg-white rounded-xl border border-stone-100 p-4 flex flex-col min-h-[75vh]">
            {!selected ? (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-stone-400 text-sm">Select an email to view the thread</p>
              </div>
            ) : (
              <>
                <div className="pb-3 border-b border-stone-100 mb-3">
                  <p className="text-sm font-medium text-stone-800">{selected.subject}</p>
                  <p className="text-xs text-stone-400 mt-1">{shortName(selected.sender)}</p>
                </div>

                <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                  {threadLoading ? (
                    <p className="text-sm text-stone-400">Loading thread...</p>
                  ) : thread.length === 0 ? (
                    <p className="text-sm text-stone-500 whitespace-pre-wrap leading-relaxed">{selected.snippet}</p>
                  ) : thread.map(m => (
                    <div key={m.gmail_id} className="bg-stone-50 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-1 gap-2">
                        <p className="text-xs font-medium text-stone-700 truncate">{shortName(m.sender)}</p>
                        <p className="text-xs text-stone-300 flex-shrink-0">{m.date}</p>
                      </div>
                      <p className="text-sm text-stone-600 whitespace-pre-wrap leading-relaxed">{m.full_body}</p>
                    </div>
                  ))}
                </div>

                <div className="pt-4 border-t border-stone-100 mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm font-medium text-stone-700">Reply</p>
                    <button
                      onClick={generateReply}
                      disabled={replyLoading}
                      className="text-xs text-teal-600 font-medium hover:text-teal-700 disabled:text-stone-300"
                    >
                      {replyLoading ? 'generating...' : 'generate draft ✦'}
                    </button>
                  </div>
                  {selected.draft_status === 'ready' && (
                    <div className="flex items-center gap-1.5 text-xs text-teal-600 bg-teal-50 rounded-lg px-3 py-1.5 mb-2">
                      <SparkleIcon className="w-3 h-3" />
                      AI draft ready — review before sending
                    </div>
                  )}
                  {selected.draft_status === 'sent' && (
                    <div className="text-xs text-stone-400 bg-stone-50 rounded-lg px-3 py-1.5 mb-2">
                      Sent ✓
                    </div>
                  )}
                  <textarea
                    value={reply}
                    onChange={e => { setReply(e.target.value); setDraftStatus('idle'); setSendStatus('idle') }}
                    placeholder="Generate a draft in your voice, or write your own reply..."
                    className="w-full min-h-[160px] text-sm text-stone-600 bg-stone-50 rounded-lg p-3 outline-none resize-none placeholder-stone-300 leading-relaxed"
                  />
                  <div className="flex items-center justify-between mt-2">
                    <p className="text-xs text-stone-400">
                      {draftStatus === 'created' && 'Draft saved to Gmail ✓'}
                      {draftStatus === 'error' && 'Could not create draft — try again'}
                      {sendStatus === 'sent' && 'Sent ✓'}
                      {sendStatus === 'error' && 'Could not send — try again'}
                    </p>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={createDraft}
                        disabled={!reply.trim() || draftStatus === 'creating'}
                        className="text-xs bg-stone-100 text-stone-600 font-medium px-3 py-1.5 rounded-lg hover:bg-stone-200 disabled:bg-stone-100 disabled:text-stone-300 transition"
                      >
                        {draftStatus === 'creating' ? 'creating...' : 'create Gmail draft'}
                      </button>
                      <button
                        onClick={sendDraft}
                        disabled={!reply.trim() || sendStatus === 'sending' || sendStatus === 'sent'}
                        className="text-xs bg-teal-500 text-white font-medium px-3 py-1.5 rounded-lg hover:bg-teal-600 disabled:bg-stone-200 disabled:text-stone-400 transition"
                      >
                        {sendStatus === 'sending' ? 'sending...' : sendStatus === 'sent' ? 'sent ✓' : 'approve & send'}
                      </button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
