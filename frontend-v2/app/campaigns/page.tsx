'use client'

import { useEffect, useState } from 'react'
import { shortName, initials, avatarColors, campaignStatusColors, contactStatusColors, formatDate } from '@/lib/email'

const API = '/api'

type CampaignStats = {
  total: number
  sent: number
  replied: number
  bounced: number
  reply_rate: number
}

type Campaign = {
  id: number
  name: string
  goal: string
  status: string
  created_at: string
  updated_at: string
  stats: CampaignStats
}

type CampaignContact = {
  id: number
  campaign_id: number
  contact_email: string
  sequence_step: number
  status: string
  last_sent_at: string | null
  replied_at: string | null
  reply_gmail_id: string | null
  notes: string | null
}

type CampaignDetail = Campaign & {
  contacts: CampaignContact[]
}

type ContactResult = {
  email: string
  name: string
  company: string
  contact_type: string
  relationship_score: number
}

const STATUS_OPTIONS = ['active', 'paused', 'completed']

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<CampaignDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [showNewForm, setShowNewForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newGoal, setNewGoal] = useState('')
  const [creating, setCreating] = useState(false)

  const [campaignPrompt, setCampaignPrompt] = useState('')

  const [contactQuery, setContactQuery] = useState('')
  const [contactResults, setContactResults] = useState<ContactResult[]>([])
  const [searching, setSearching] = useState(false)
  const [addingEmail, setAddingEmail] = useState<string | null>(null)

  const [sendingFor, setSendingFor] = useState<string | null>(null)
  const [generated, setGenerated] = useState<Record<string, { email_body: string; draft_created: boolean }>>({})

  useEffect(() => {
    loadCampaigns()
  }, [])

  useEffect(() => {
    if (!contactQuery.trim()) {
      setContactResults([])
      return
    }
    setSearching(true)
    const timer = setTimeout(async () => {
      const res = await fetch(`${API}/contacts?q=${encodeURIComponent(contactQuery)}`)
      const data = await res.json()
      setContactResults(data.contacts || [])
      setSearching(false)
    }, 300)
    return () => clearTimeout(timer)
  }, [contactQuery])

  async function loadCampaigns() {
    setLoading(true)
    const res = await fetch(`${API}/campaigns`)
    const data = await res.json()
    setCampaigns(data.campaigns || [])
    setLoading(false)
  }

  async function selectCampaign(id: number) {
    setSelectedId(id)
    setContactQuery('')
    setContactResults([])
    setGenerated({})
    await loadDetail(id, true)
  }

  async function loadDetail(id: number, resetPrompt = false) {
    setDetailLoading(true)
    const res = await fetch(`${API}/campaigns/${id}`)
    const data = await res.json()
    setDetail(data)
    if (resetPrompt) setCampaignPrompt(data.goal || '')
    setDetailLoading(false)
  }

  async function createCampaign() {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const res = await fetch(`${API}/campaigns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName, goal: newGoal, contacts: [] }),
      })
      const data = await res.json()
      setNewName('')
      setNewGoal('')
      setShowNewForm(false)
      await loadCampaigns()
      if (data.campaign_id) selectCampaign(data.campaign_id)
    } finally {
      setCreating(false)
    }
  }

  async function updateStatus(status: string) {
    if (!detail) return
    await fetch(`${API}/campaigns/${detail.id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    await Promise.all([loadCampaigns(), loadDetail(detail.id)])
  }

  async function addContact(email: string) {
    if (!detail) return
    setAddingEmail(email)
    try {
      await fetch(`${API}/campaigns/${detail.id}/contacts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emails: [email] }),
      })
      setContactQuery('')
      setContactResults([])
      await Promise.all([loadDetail(detail.id), loadCampaigns()])
    } finally {
      setAddingEmail(null)
    }
  }

  async function sendToContact(contactEmail: string) {
    if (!detail || !campaignPrompt.trim()) return
    setSendingFor(contactEmail)
    try {
      const res = await fetch(`${API}/campaigns/${detail.id}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          campaign_id: detail.id,
          contact_email: contactEmail,
          campaign_prompt: campaignPrompt,
          send_as_draft: true,
        }),
      })
      const data = await res.json()
      setGenerated(prev => ({ ...prev, [contactEmail]: data }))
      await Promise.all([loadDetail(detail.id), loadCampaigns()])
    } finally {
      setSendingFor(null)
    }
  }

  const existingEmails = new Set((detail?.contacts || []).map(c => c.contact_email))

  return (
    <div className="min-h-screen bg-stone-50 font-sans">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-medium text-stone-800">Campaigns</h1>
            <p className="text-stone-400 text-sm mt-1">Create outreach, draft personalized emails, and track replies</p>
          </div>
          <button
            onClick={() => setShowNewForm(v => !v)}
            className="text-xs bg-teal-500 text-white font-medium px-3 py-1.5 rounded-lg hover:bg-teal-600 transition"
          >
            {showNewForm ? 'cancel' : '+ new campaign'}
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 items-start">
          {/* Campaign list */}
          <div className="lg:col-span-2 space-y-4">
            {showNewForm && (
              <div className="bg-white rounded-xl border border-stone-100 p-4 space-y-3">
                <p className="text-sm font-medium text-stone-700">New campaign</p>
                <input
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder="Campaign name"
                  className="w-full text-sm text-stone-600 bg-stone-50 rounded-lg px-3 py-2 outline-none placeholder-stone-300"
                />
                <textarea
                  value={newGoal}
                  onChange={e => setNewGoal(e.target.value)}
                  placeholder="Goal / outreach prompt — what is this campaign trying to achieve?"
                  className="w-full min-h-[80px] text-sm text-stone-600 bg-stone-50 rounded-lg px-3 py-2 outline-none resize-none placeholder-stone-300 leading-relaxed"
                />
                <button
                  onClick={createCampaign}
                  disabled={!newName.trim() || creating}
                  className="text-xs bg-teal-500 text-white font-medium px-3 py-1.5 rounded-lg hover:bg-teal-600 disabled:bg-stone-200 disabled:text-stone-400 transition"
                >
                  {creating ? 'creating...' : 'create campaign'}
                </button>
              </div>
            )}

            <div className="bg-white rounded-xl border border-stone-100 overflow-hidden">
              <div className="max-h-[70vh] overflow-y-auto divide-y divide-stone-50">
                {loading ? (
                  <p className="text-sm text-stone-400 p-4">Loading campaigns...</p>
                ) : campaigns.length === 0 ? (
                  <p className="text-sm text-stone-400 p-4">No campaigns yet — create one to get started.</p>
                ) : campaigns.map(c => (
                  <button
                    key={c.id}
                    onClick={() => selectCampaign(c.id)}
                    className={`w-full text-left p-3 transition hover:bg-stone-50 ${selectedId === c.id ? 'bg-teal-50/60' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-sm font-medium text-stone-800 truncate">{c.name}</p>
                      <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${campaignStatusColors[c.status] || campaignStatusColors.completed}`}>
                        {c.status}
                      </span>
                    </div>
                    {c.goal && <p className="text-xs text-stone-400 truncate mb-2">{c.goal}</p>}
                    <div className="flex items-center gap-3 text-xs text-stone-400">
                      <span>{c.stats?.total || 0} contacts</span>
                      <span>{c.stats?.sent || 0} sent</span>
                      <span>{c.stats?.replied || 0} replied</span>
                      <span className="text-teal-600 font-medium">{c.stats?.reply_rate || 0}% reply rate</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Campaign detail */}
          <div className="lg:col-span-3 bg-white rounded-xl border border-stone-100 p-4 min-h-[70vh]">
            {!detail ? (
              <div className="h-full flex items-center justify-center">
                <p className="text-stone-400 text-sm">Select a campaign to view details</p>
              </div>
            ) : detailLoading && !detail.contacts ? (
              <p className="text-sm text-stone-400">Loading...</p>
            ) : (
              <>
                <div className="flex items-start justify-between gap-3 pb-3 border-b border-stone-100 mb-4">
                  <div>
                    <p className="text-sm font-medium text-stone-800">{detail.name}</p>
                    {detail.goal && <p className="text-xs text-stone-400 mt-1">{detail.goal}</p>}
                  </div>
                  <select
                    value={detail.status}
                    onChange={e => updateStatus(e.target.value)}
                    className={`text-xs px-2 py-1 rounded-lg border-0 outline-none flex-shrink-0 ${campaignStatusColors[detail.status] || campaignStatusColors.completed}`}
                  >
                    {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

                <div className="grid grid-cols-4 gap-3 mb-4">
                  {[
                    { label: 'Contacts', value: detail.stats?.total || 0 },
                    { label: 'Sent', value: detail.stats?.sent || 0 },
                    { label: 'Replied', value: detail.stats?.replied || 0 },
                    { label: 'Reply rate', value: `${detail.stats?.reply_rate || 0}%` },
                  ].map((m, i) => (
                    <div key={i} className="bg-stone-50 rounded-lg p-3 text-center">
                      <p className="text-lg font-medium text-stone-800">{m.value}</p>
                      <p className="text-xs text-stone-400 mt-0.5">{m.label}</p>
                    </div>
                  ))}
                </div>

                <div className="mb-4">
                  <p className="text-sm font-medium text-stone-700 mb-2">Outreach prompt</p>
                  <textarea
                    value={campaignPrompt}
                    onChange={e => setCampaignPrompt(e.target.value)}
                    placeholder="Describe what each outreach email should say..."
                    className="w-full min-h-[70px] text-sm text-stone-600 bg-stone-50 rounded-lg p-3 outline-none resize-none placeholder-stone-300 leading-relaxed"
                  />
                </div>

                <div className="mb-4 relative">
                  <p className="text-sm font-medium text-stone-700 mb-2">Add contacts</p>
                  <input
                    value={contactQuery}
                    onChange={e => setContactQuery(e.target.value)}
                    placeholder="Search contacts by name, email, or company..."
                    className="w-full text-sm text-stone-600 bg-stone-50 rounded-lg px-3 py-2 outline-none placeholder-stone-300"
                  />
                  {contactQuery.trim() && (
                    <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-stone-100 rounded-lg shadow-sm max-h-56 overflow-y-auto">
                      {searching ? (
                        <p className="text-xs text-stone-400 p-3">Searching...</p>
                      ) : contactResults.filter(r => !existingEmails.has(r.email)).length === 0 ? (
                        <p className="text-xs text-stone-400 p-3">No matching contacts</p>
                      ) : contactResults.filter(r => !existingEmails.has(r.email)).map(r => (
                        <button
                          key={r.email}
                          onClick={() => addContact(r.email)}
                          disabled={addingEmail === r.email}
                          className="w-full text-left flex items-center justify-between gap-2 px-3 py-2 hover:bg-stone-50 transition disabled:opacity-50"
                        >
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-stone-700 truncate">{r.name || r.email}</p>
                            <p className="text-xs text-stone-400 truncate">{r.email}{r.company ? ` · ${r.company}` : ''}</p>
                          </div>
                          <span className="text-xs text-teal-600 flex-shrink-0">{addingEmail === r.email ? 'adding...' : '+ add'}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium text-stone-700 mb-2">Contacts</p>
                  {(!detail.contacts || detail.contacts.length === 0) ? (
                    <p className="text-sm text-stone-400">No contacts added yet — search above to add some.</p>
                  ) : detail.contacts.map((c, i) => (
                    <div key={c.id} className="bg-stone-50 rounded-lg p-3">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0 ${avatarColors[i % avatarColors.length]}`}>
                          {initials(shortName(c.contact_email))}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-stone-700 truncate">{c.contact_email}</p>
                          <p className="text-xs text-stone-400">
                            {c.status === 'sent' && c.last_sent_at && `sent ${formatDate(c.last_sent_at)}`}
                            {c.status === 'replied' && c.replied_at && `replied ${formatDate(c.replied_at)}`}
                            {c.status === 'pending' && 'not yet contacted'}
                            {c.status === 'bounced' && 'bounced'}
                          </p>
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${contactStatusColors[c.status] || contactStatusColors.pending}`}>
                          {c.status}
                        </span>
                        <button
                          onClick={() => sendToContact(c.contact_email)}
                          disabled={!campaignPrompt.trim() || sendingFor === c.contact_email}
                          className="text-xs bg-teal-500 text-white font-medium px-3 py-1.5 rounded-lg hover:bg-teal-600 disabled:bg-stone-200 disabled:text-stone-400 transition flex-shrink-0"
                        >
                          {sendingFor === c.contact_email ? 'generating...' : c.status === 'pending' ? 'generate & draft' : 're-draft'}
                        </button>
                      </div>
                      {generated[c.contact_email] && (
                        <div className="mt-3 pt-3 border-t border-stone-100">
                          <p className="text-xs text-stone-400 mb-1">
                            {generated[c.contact_email].draft_created ? 'Saved to Gmail drafts ✓' : 'Preview'}
                          </p>
                          <p className="text-sm text-stone-600 whitespace-pre-wrap leading-relaxed">{generated[c.contact_email].email_body}</p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
