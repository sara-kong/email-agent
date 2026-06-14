const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-stone-50 font-sans">
      <div className="bg-white rounded-xl border border-stone-100 p-8 max-w-sm w-full text-center">
        <h1 className="text-xl font-medium text-stone-800 mb-2">Email OS</h1>
        <p className="text-sm text-stone-400 mb-6">Sign in with Google to connect your inbox.</p>
        <a
          href={`${BACKEND_URL}/auth/google/login`}
          className="inline-block w-full text-sm font-medium text-white bg-teal-500 hover:bg-teal-600 rounded-lg px-4 py-2.5 transition"
        >
          Continue with Google
        </a>
      </div>
    </div>
  )
}
