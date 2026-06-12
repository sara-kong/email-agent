export function shortName(sender: string) {
  const match = sender.match(/^([^<]+)/)
  return match ? match[1].trim().replace(/"/g, '') : sender
}

export function initials(name: string) {
  return name
    .replace(/<.*?>/, '')
    .trim()
    .split(' ')
    .slice(0, 2)
    .map((w: string) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

export const badgeColors: Record<string, string> = {
  important: 'bg-rose-50 text-rose-700',
  marketing: 'bg-amber-50 text-amber-700',
  social: 'bg-violet-50 text-violet-700',
  historical: 'bg-stone-100 text-stone-500',
  unknown: 'bg-stone-100 text-stone-500',
}

export const avatarColors = [
  'bg-teal-50 text-teal-700',
  'bg-rose-50 text-rose-700',
  'bg-violet-50 text-violet-700',
  'bg-blue-50 text-blue-700',
  'bg-amber-50 text-amber-700',
]

export const campaignStatusColors: Record<string, string> = {
  active: 'bg-teal-50 text-teal-700',
  paused: 'bg-amber-50 text-amber-700',
  completed: 'bg-stone-100 text-stone-500',
}

export const contactStatusColors: Record<string, string> = {
  pending: 'bg-stone-100 text-stone-500',
  sent: 'bg-blue-50 text-blue-700',
  replied: 'bg-teal-50 text-teal-700',
  bounced: 'bg-rose-50 text-rose-700',
  opted_out: 'bg-stone-100 text-stone-400',
}

export function formatDate(dateStr?: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr.replace(' ', 'T'))
  if (isNaN(d.getTime())) return dateStr
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}
