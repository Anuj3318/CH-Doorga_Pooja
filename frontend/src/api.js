export const API_BASE = (
  import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'
).replace(/\/$/, '')

async function request(path, options = {}) {
  const token = sessionStorage.getItem('cdps_admin_token')

  const headers = {
    ...(options.body instanceof FormData
      ? {}
      : { 'Content-Type': 'application/json' }),
    ...options.headers
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  })

  const type = response.headers.get('content-type') || ''

  const payload = type.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    throw new Error(
      payload?.detail ||
      payload?.message ||
      'Something went wrong. Please try again.'
    )
  }

  return payload
}

export const api = {
  get: (path) => request(path),

  post: (path, data) =>
    request(path, {
      method: 'POST',
      body:
        data instanceof FormData
          ? data
          : JSON.stringify(data)
    }),

  put: (path, data) =>
    request(path, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  patch: (path, data = {}) =>
    request(path, {
      method: 'PATCH',
      body: JSON.stringify(data)
    }),

  remove: (path) =>
    request(path, {
      method: 'DELETE'
    }),

  qr: (data, download = false) =>
    `${API_BASE}/qr?data=${encodeURIComponent(data)}${
      download ? '&download=1' : ''
    }`,

  asset: (path) =>
    path?.startsWith('/')
      ? `${API_BASE.replace(/\/api$/, '')}${path}`
      : path
}

export const currency = (value) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(Number(value || 0))


// UPI PAYMENT LINK
export const toUPI = ({ upiId, amount, name, note }) => {
  const params = new URLSearchParams()

  // Receiver UPI ID
  params.set('pa', upiId)

  // Receiver name
  params.set('pn', 'Chhabinathpur Durga Pooja Samiti')

  // Currency
  params.set('cu', 'INR')

  // Donation amount
  if (amount && Number(amount) > 0) {
    params.set('am', Number(amount).toFixed(2))
  }

  // Transaction note
  if (note) {
    params.set('tn', note)
  } else if (name) {
    params.set('tn', `Donation by ${name}`)
  }

  return `upi://pay?${params.toString()}`
}
