
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const API = 'http://127.0.0.1:8000'
const PAGE_SIZE = 25

type Overview = {
  source_customers: number
  unified_customers: number
  accounts: number
  orders: number
  total_order_value: number
  interactions: number
  quarantined_records: number
  uncertain_matches: number
  successful_runs: number
  failed_runs: number
}

type Customer = {
  canonical_customer_id: string
  customer_name: string
  email_normalized: string | null
  phone_normalized: string | null
  account_count: number
  active_account_count: number
  order_count: number
  lifetime_order_value: number
  interaction_count: number
  last_order_at: string | null
  latest_interaction_at: string | null
}

type PipelineRun = {
  run_id: string
  batch_id: string
  started_at: string
  ended_at: string | null
  status: string
  input_counts: Record<string, number>
  output_counts: Record<string, number>
  rejected_count: number
  error_message: string | null
}

type ReconciliationRow = {
  entity: string
  accepted_source_rows: number
  quarantined_rows: number
}

type QuarantineRow = {
  source_name: string
  reason_code: string
  record_count: number
}

type PageName = 'Overview' | 'Customers' | 'Data Quality' | 'Pipeline Runs'

const navigation: { name: PageName; icon: string; description: string }[] = [
  { name: 'Overview', icon: '◫', description: 'Your data at a glance' },
  { name: 'Customers', icon: '◎', description: 'Unified customer profiles' },
  { name: 'Data Quality', icon: '◇', description: 'Reconciliation and quarantine' },
  { name: 'Pipeline Runs', icon: '↻', description: 'Execution history' },
]

function formatNumber(value: number | null | undefined) {
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 2,
  }).format(value ?? 0)
}

function formatCurrency(value: number | null | undefined) {
  return new Intl.NumberFormat('en-IN', {
    style: 'decimal',
    maximumFractionDigits: 2,
  }).format(value ?? 0)
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleString('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function durationSeconds(start: string, end: string | null) {
  if (!end) return 'In progress'

  const seconds = (new Date(end).getTime() - new Date(start).getTime()) / 1000

  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  return `${seconds.toFixed(2)} sec`
}

function Panel({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-2xl border border-white/[0.09] bg-[#111620] p-5 shadow-lg shadow-black/10 ${className}`}
    >
      {children}
    </section>
  )
}

function SectionHeading({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="mb-5">
      <h2 className="text-lg font-semibold tracking-tight text-white">{title}</h2>
      <p className="mt-1 text-sm text-slate-400">{description}</p>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const success = status.toLowerCase() === 'succeeded'

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${
        success
          ? 'bg-emerald-400/10 text-emerald-300'
          : 'bg-rose-400/10 text-rose-300'
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          success ? 'bg-emerald-400' : 'bg-rose-400'
        }`}
      />
      {status}
    </span>
  )
}

function App() {
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [apiConnected, setApiConnected] = useState(false)

  const [activePage, setActivePage] = useState<PageName>('Overview')
  const [lastUpdated, setLastUpdated] = useState('')

  const [customersData, setCustomersData] = useState<Customer[]>([])
  const [runsData, setRunsData] = useState<PipelineRun[]>([])
  const [reconciliationData, setReconciliationData] = useState<ReconciliationRow[]>([])
  const [quarantineData, setQuarantineData] = useState<QuarantineRow[]>([])

  const [pageLoading, setPageLoading] = useState(false)
  const [pageError, setPageError] = useState('')
  const [customerSearch, setCustomerSearch] = useState('')
  const [customerOffset, setCustomerOffset] = useState(0)
  const [customerHasNext, setCustomerHasNext] = useState(false)

  const loadOverview = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      console.log('Calling overview API:', `${API}/api/overview`)

      const response = await fetch(`${API}/api/overview`)
      console.log('Overview response status:', response.status)

      if (!response.ok) {
        throw new Error(`Overview API returned HTTP ${response.status}`)
      }

      const result: Overview = await response.json()
      console.log('Overview data received:', result)

      setData(result)
      setApiConnected(true)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (err) {
      console.error('Overview API request failed:', err)
      setApiConnected(false)
      setError(
        err instanceof Error
          ? err.message
          : 'Unexpected error while loading overview metrics.',
      )
    } finally {
      setLoading(false)
    }
  }, [])

  const loadPageData = useCallback(async () => {
    if (activePage === 'Overview') return

    setPageLoading(true)
    setPageError('')

    try {
      if (activePage === 'Customers') {
        const response = await fetch(
          `${API}/api/customers?limit=${PAGE_SIZE + 1}&offset=${customerOffset}`,
        )

        if (!response.ok) {
          throw new Error(`Customers API returned HTTP ${response.status}`)
        }

        const result: Customer[] = await response.json()
        setCustomerHasNext(result.length > PAGE_SIZE)
        setCustomersData(result.slice(0, PAGE_SIZE))
      } else if (activePage === 'Data Quality') {
        const [reconciliationResponse, quarantineResponse] = await Promise.all([
          fetch(`${API}/api/reconciliation`),
          fetch(`${API}/api/quarantine`),
        ])

        if (!reconciliationResponse.ok) {
          throw new Error(`Reconciliation API returned HTTP ${reconciliationResponse.status}`)
        }

        if (!quarantineResponse.ok) {
          throw new Error(`Quarantine API returned HTTP ${quarantineResponse.status}`)
        }

        const reconciliation: ReconciliationRow[] =
          await reconciliationResponse.json()
        const quarantine: QuarantineRow[] = await quarantineResponse.json()

        setReconciliationData(reconciliation)
        setQuarantineData(quarantine)
      } else if (activePage === 'Pipeline Runs') {
        const response = await fetch(`${API}/api/runs?limit=25`)

        if (!response.ok) {
          throw new Error(`Pipeline runs API returned HTTP ${response.status}`)
        }

        const result: PipelineRun[] = await response.json()
        setRunsData(result)
      }

      setApiConnected(true)
    } catch (err) {
      console.error(`${activePage} request failed:`, err)
      setPageError(
        err instanceof Error ? err.message : 'An unexpected error occurred.',
      )
    } finally {
      setPageLoading(false)
    }
  }, [activePage, customerOffset])

  useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  useEffect(() => {
    void loadPageData()
  }, [loadPageData])

  const filteredCustomers = useMemo(() => {
    const term = customerSearch.trim().toLowerCase()

    if (!term) return customersData

    return customersData.filter((customer) =>
      [
        customer.customer_name,
        customer.canonical_customer_id,
        customer.email_normalized ?? '',
        customer.phone_normalized ?? '',
      ].some((value) => value.toLowerCase().includes(term)),
    )
  }, [customersData, customerSearch])

  const chartData = useMemo(() => {
    if (!data) return []

    return [
      { name: 'Customers', records: data.source_customers },
      { name: 'Accounts', records: data.accounts },
      { name: 'Orders', records: data.orders },
      { name: 'Interactions', records: data.interactions },
    ]
  }, [data])

  const metrics = data
    ? [
        {
          label: 'Source customers',
          value: formatNumber(data.source_customers),
          note: 'Customer records received',
          icon: '◎',
        },
        {
          label: 'Unified customers',
          value: formatNumber(data.unified_customers),
          note: 'Canonical customer profiles',
          icon: '◉',
        },
        {
          label: 'Total order value',
          value: formatCurrency(data.total_order_value),
          note: `${formatNumber(data.orders)} source orders`,
          icon: '↗',
        },
        {
          label: 'Quarantined records',
          value: formatNumber(data.quarantined_records),
          note: 'Records flagged for review',
          icon: '△',
        },
      ]
    : []

  const totalAccepted = reconciliationData.reduce(
    (sum, row) => sum + row.accepted_source_rows,
    0,
  )

  const totalQuarantined = reconciliationData.reduce(
    (sum, row) => sum + row.quarantined_rows,
    0,
  )

  return (
    <div className="min-h-screen bg-[#0b0e14] text-slate-100">
      <div className="flex min-h-screen">
        <aside className="hidden w-64 shrink-0 flex-col border-r border-white/[0.08] bg-[#0e121a] p-5 md:flex">
          <div className="flex items-center gap-3 px-2 py-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-500 text-lg font-black text-white shadow-lg shadow-violet-500/20">
              C
            </div>
            <div>
              <h1 className="font-bold tracking-tight text-white">Customer360</h1>
              <p className="mt-0.5 text-xs text-slate-500">Data platform</p>
            </div>
          </div>

          <div className="mt-10">
            <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
              Workspace
            </p>
            <nav className="space-y-1">
              {navigation.map((item) => {
                const active = activePage === item.name

                return (
                  <button
                    key={item.name}
                    onClick={() => setActivePage(item.name)}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition ${
                      active
                        ? 'bg-violet-500/15 text-violet-200 ring-1 ring-violet-400/20'
                        : 'text-slate-400 hover:bg-white/[0.04] hover:text-white'
                    }`}
                  >
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.04] text-lg">
                      {item.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{item.name}</span>
                      <span className="mt-0.5 block text-[10px] text-slate-500">
                        {item.description}
                      </span>
                    </span>
                  </button>
                )
              })}
            </nav>
          </div>

          <div className="mt-auto rounded-2xl border border-white/[0.08] bg-white/[0.025] p-4">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  apiConnected ? 'bg-emerald-400' : 'bg-rose-400'
                }`}
              />
              <span
                className={`text-xs font-medium ${
                  apiConnected ? 'text-emerald-300' : 'text-rose-300'
                }`}
              >
                {apiConnected ? 'API connected' : 'API not confirmed'}
              </span>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              PostgreSQL analytics powered by FastAPI.
            </p>
            <p className="mt-2 break-all font-mono text-[10px] text-slate-600">
              127.0.0.1:8000
            </p>
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          <header className="sticky top-0 z-10 border-b border-white/[0.08] bg-[#0b0e14]/90 px-5 py-4 backdrop-blur-xl sm:px-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-xs text-slate-500">Workspace / {activePage}</div>
                <h2 className="mt-1 text-xl font-semibold tracking-tight text-white">
                  {activePage}
                </h2>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <span className="hidden text-xs text-slate-500 sm:inline">
                  {lastUpdated ? `Updated ${lastUpdated}` : 'Connecting to database'}
                </span>
                <button
                  onClick={() => {
                    if (activePage === 'Overview') void loadOverview()
                    else void loadPageData()
                  }}
                  disabled={loading || pageLoading}
                  className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm font-medium transition hover:bg-white/[0.08] disabled:opacity-50"
                >
                  ↻ <span className="ml-1">Refresh</span>
                </button>
              </div>
            </div>

            <div className="mt-4 flex items-center gap-2 text-xs text-slate-400">
              <span
                className={`h-2 w-2 rounded-full ${
                  apiConnected ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              PostgreSQL · FastAPI · React
            </div>

            <nav className="mt-4 flex gap-2 overflow-x-auto md:hidden">
              {navigation.map((item) => (
                <button
                  key={item.name}
                  onClick={() => setActivePage(item.name)}
                  className={`shrink-0 rounded-lg px-3 py-2 text-xs ${
                    activePage === item.name
                      ? 'bg-violet-500/20 text-violet-200'
                      : 'bg-white/[0.04] text-slate-400'
                  }`}
                >
                  {item.name}
                </button>
              ))}
            </nav>
          </header>

          <div className="mx-auto max-w-[1600px] p-5 sm:p-8">
            {error && (
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-400/20 bg-rose-400/5 p-4 text-sm text-rose-300">
                <span>{error}</span>
                <button onClick={() => void loadOverview()} className="underline">
                  Try again
                </button>
              </div>
            )}

            {pageError && (
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-400/20 bg-rose-400/5 p-4 text-sm text-rose-300">
                <span>{pageError}</span>
                <button onClick={() => void loadPageData()} className="underline">
                  Try again
                </button>
              </div>
            )}

            {pageLoading && (
              <div className="mb-5 rounded-xl border border-white/10 bg-[#111620] p-4 text-sm text-slate-400">
                Loading {activePage.toLowerCase()} data…
              </div>
            )}

            {activePage === 'Overview' && (
              <>
                <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-sm text-violet-300">Your data, unified</p>
                    <h3 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
                      Customer intelligence overview
                    </h3>
                    <p className="mt-2 text-sm text-slate-400">
                      A live view of your customer data pipeline.
                    </p>
                  </div>
                  <span className="rounded-full border border-emerald-400/20 bg-emerald-400/5 px-3 py-1.5 text-xs text-emerald-300">
                    ● Live metrics
                  </span>
                </div>

                {loading && !data ? (
                  <Panel>
                    <p className="text-sm text-slate-400">Loading overview metrics…</p>
                  </Panel>
                ) : data ? (
                  <>
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                      {metrics.map((metric, index) => (
                        <Panel key={metric.label}>
                          <div className="flex items-center justify-between">
                            <span className="text-sm text-slate-400">{metric.label}</span>
                            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-400/10 text-lg text-violet-300">
                              {metric.icon}
                            </span>
                          </div>
                          <p className="mt-5 break-words text-2xl font-bold tracking-tight text-white">
                            {metric.value}
                          </p>
                          <p className="mt-2 text-xs text-slate-500">{metric.note}</p>
                          <div
                            className={`mt-5 h-1 rounded-full ${
                              index === 3 ? 'bg-amber-300/70' : 'bg-violet-400/70'
                            }`}
                          />
                        </Panel>
                      ))}
                    </div>

                    <div className="mt-5 grid gap-5 xl:grid-cols-[1.5fr_1fr]">
                      <Panel>
                        <SectionHeading
                          title="Data landscape"
                          description="Source records across pipeline entities"
                        />
                        <div className="h-72">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                              data={chartData}
                              margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                            >
                              <CartesianGrid stroke="#252c3a" strokeDasharray="4 4" vertical={false} />
                              <XAxis
                                dataKey="name"
                                tick={{ fill: '#94a3b8', fontSize: 12 }}
                                axisLine={{ stroke: '#303747' }}
                                tickLine={false}
                              />
                              <YAxis
                                tick={{ fill: '#94a3b8', fontSize: 11 }}
                                axisLine={false}
                                tickLine={false}
                              />
                              <Tooltip
                                contentStyle={{
                                  background: '#171d29',
                                  border: '1px solid #303747',
                                  borderRadius: 12,
                                  color: '#fff',
                                }}
                              />
                              <Bar
                                dataKey="records"
                                name="Source rows"
                                fill="#8b7cff"
                                radius={[7, 7, 0, 0]}
                                maxBarSize={58}
                              />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </Panel>

                      <Panel>
                        <SectionHeading
                          title="Pipeline health"
                          description="Current database summary"
                        />
                        <div className="space-y-3">
                          {[
                            { label: 'Successful runs', value: data.successful_runs, color: 'text-emerald-300' },
                            { label: 'Failed runs', value: data.failed_runs, color: 'text-rose-300' },
                            { label: 'Uncertain identity matches', value: data.uncertain_matches, color: 'text-amber-300' },
                            { label: 'Customer interactions', value: data.interactions, color: 'text-violet-300' },
                          ].map((item) => (
                            <div
                              key={item.label}
                              className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4"
                            >
                              <span className="text-sm text-slate-400">{item.label}</span>
                              <span className={`text-lg font-semibold ${item.color}`}>
                                {formatNumber(item.value)}
                              </span>
                            </div>
                          ))}
                        </div>

                        <button
                          onClick={() => setActivePage('Data Quality')}
                          className="mt-4 w-full rounded-xl border border-violet-400/20 bg-violet-400/[0.06] px-4 py-3 text-sm font-medium text-violet-200 transition hover:bg-violet-400/10"
                        >
                          Explore data quality →
                        </button>
                      </Panel>
                    </div>
                  </>
                ) : !loading ? (
                  <Panel>
                    <p className="text-sm text-slate-400">
                      Overview metrics are unavailable. Use Refresh to try again.
                    </p>
                  </Panel>
                ) : null}
              </>
            )}

            {activePage === 'Customers' && (
              <Panel>
                <SectionHeading
                  title="Unified customers"
                  description="Search customer profiles and explore account, order, and interaction metrics."
                />

                <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <input
                    value={customerSearch}
                    onChange={(event) => {
  setCustomerSearch(event.target.value)
  setCustomerOffset(0)
}}
                    placeholder="Search current page by name, email, phone or ID…"
                    className="w-full rounded-xl border border-white/10 bg-[#0b0e14] px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-violet-400/60 sm:max-w-md"
                  />
                  <span className="text-xs text-slate-500">
                    {filteredCustomers.length} visible records
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[850px] text-left text-sm">
                    <thead className="border-b border-white/10 text-xs uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="px-3 py-3 font-medium">Customer</th>
                        <th className="px-3 py-3 font-medium">Accounts</th>
                        <th className="px-3 py-3 font-medium">Orders</th>
                        <th className="px-3 py-3 font-medium">Interactions</th>
                        <th className="px-3 py-3 font-medium">Last order</th>
                        <th className="px-3 py-3 text-right font-medium">Lifetime value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.06]">
                      {filteredCustomers.map((customer) => (
                        <tr key={customer.canonical_customer_id} className="transition hover:bg-white/[0.025]">
                          <td className="px-3 py-4">
                            <p className="font-medium text-white">{customer.customer_name}</p>
                            <p className="mt-1 text-xs text-slate-400">
                              {customer.email_normalized || 'No email'}
                            </p>
                            <p className="mt-1 max-w-64 truncate font-mono text-[10px] text-slate-600">
                              {customer.canonical_customer_id}
                            </p>
                          </td>

<td className="px-3 py-4">
  <div className="flex flex-col items-start gap-1">
    <span className="font-semibold text-white">
      {formatNumber(customer.account_count)}{" "}
      {customer.account_count === 1 ? "account" : "accounts"}
    </span>

    {customer.account_count > 0 ? (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-400/10 px-2 py-1 text-xs text-emerald-300">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        {formatNumber(customer.active_account_count)} active
      </span>
    ) : (
      <span className="text-xs text-slate-400">
        No linked accounts
      </span>
    )}
  </div>
</td>

                          <td className="px-3 py-4">{formatNumber(customer.order_count)}</td>
                          <td className="px-3 py-4">{formatNumber(customer.interaction_count)}</td>
                          <td className="px-3 py-4 text-xs text-slate-400">
                            {formatDate(customer.last_order_at)}
                          </td>
                          <td className="px-3 py-4 text-right font-semibold text-emerald-300">
                            {formatCurrency(customer.lifetime_order_value)}
                          </td>
                        </tr>
                      ))}
                      {!pageLoading && filteredCustomers.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-3 py-12 text-center text-slate-500">
                            {customersData.length
                              ? 'No customers on this page match your search.'
                              : 'No customer records found.'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
                  <span className="text-xs text-slate-500">
                    Page {Math.floor(customerOffset / PAGE_SIZE) + 1} · {PAGE_SIZE} records per page
                  </span>
                  <div className="flex gap-2">
                    <button
                      disabled={customerOffset === 0 || pageLoading}
                      onClick={() => setCustomerOffset((offset) => Math.max(0, offset - PAGE_SIZE))}
                      className="rounded-lg border border-white/10 px-4 py-2 text-sm transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      ← Previous
                    </button>
                    <button
                      disabled={!customerHasNext || pageLoading}
                      onClick={() => setCustomerOffset((offset) => offset + PAGE_SIZE)}
                      className="rounded-lg border border-white/10 px-4 py-2 text-sm transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              </Panel>
            )}

            {activePage === 'Data Quality' && (
              <div className="space-y-5">
                <div className="grid gap-4 sm:grid-cols-3">
                  <Panel>
                    <p className="text-sm text-slate-400">Accepted source rows</p>
                    <p className="mt-3 text-3xl font-bold text-white">{formatNumber(totalAccepted)}</p>
                    <p className="mt-2 text-xs text-slate-500">Across the four entities</p>
                  </Panel>
                  <Panel>
                    <p className="text-sm text-slate-400">Quarantined source rows</p>
                    <p className="mt-3 text-3xl font-bold text-amber-300">{formatNumber(totalQuarantined)}</p>
                    <p className="mt-2 text-xs text-slate-500">Source-level reconciliation count</p>
                  </Panel>
                  <Panel>
                    <p className="text-sm text-slate-400">Uncertain matches</p>
                    <p className="mt-3 text-3xl font-bold text-violet-300">
                      {formatNumber(data?.uncertain_matches)}
                    </p>
                    <p className="mt-2 text-xs text-slate-500">Requires identity review</p>
                  </Panel>
                </div>

                <Panel>
                  <SectionHeading
                    title="Reconciliation by entity"
                    description="Compare accepted source rows with quarantined rows."
                  />
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[500px] text-left text-sm">
                      <thead className="border-b border-white/10 text-xs uppercase tracking-wider text-slate-500">
                        <tr>
                          <th className="px-3 py-3 font-medium">Entity</th>
                          <th className="px-3 py-3 font-medium">Accepted rows</th>
                          <th className="px-3 py-3 font-medium">Quarantined rows</th>
                          <th className="px-3 py-3 font-medium">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.06]">
                        {reconciliationData.map((row) => (
                          <tr key={row.entity}>
                            <td className="px-3 py-4 font-medium capitalize">{row.entity}</td>
                            <td className="px-3 py-4">{formatNumber(row.accepted_source_rows)}</td>
                            <td className="px-3 py-4">{formatNumber(row.quarantined_rows)}</td>
                            <td className="px-3 py-4">
                              <span className={`rounded-full px-3 py-1 text-xs ${
                                row.quarantined_rows
                                  ? 'bg-amber-400/10 text-amber-300'
                                  : 'bg-emerald-400/10 text-emerald-300'
                              }`}>
                                {row.quarantined_rows ? 'Review needed' : 'Clean'}
                              </span>
                            </td>
                          </tr>
                        ))}
                        {!pageLoading && reconciliationData.length === 0 && (
                          <tr>
                            <td colSpan={4} className="px-3 py-8 text-center text-slate-500">
                              No reconciliation data found.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Panel>

                <Panel>
                  <SectionHeading
                    title="Quarantine breakdown"
                    description="Understand which source records were rejected and why."
                  />
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[450px] text-left text-sm">
                      <thead className="border-b border-white/10 text-xs uppercase tracking-wider text-slate-500">
                        <tr>
                          <th className="px-3 py-3 font-medium">Source</th>
                          <th className="px-3 py-3 font-medium">Reason</th>
                          <th className="px-3 py-3 text-right font-medium">Records</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.06]">
                        {quarantineData.map((row) => (
                          <tr key={`${row.source_name}-${row.reason_code}`}>
                            <td className="px-3 py-4 capitalize">{row.source_name}</td>
                            <td className="px-3 py-4">{row.reason_code.replaceAll('_', ' ')}</td>
                            <td className="px-3 py-4 text-right">{formatNumber(row.record_count)}</td>
                          </tr>
                        ))}
                        {!pageLoading && quarantineData.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-3 py-8 text-center text-slate-500">
                              No quarantine records reported.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </div>
            )}

            {activePage === 'Pipeline Runs' && (
              <div>
                <div className="mb-5 grid gap-4 sm:grid-cols-3">
                  <Panel>
                    <p className="text-sm text-slate-400">Runs loaded</p>
                    <p className="mt-3 text-3xl font-bold">{formatNumber(runsData.length)}</p>
                  </Panel>
                  <Panel>
                    <p className="text-sm text-slate-400">Successful runs shown</p>
                    <p className="mt-3 text-3xl font-bold text-emerald-300">
                      {formatNumber(runsData.filter((run) => run.status.toLowerCase() === 'succeeded').length)}
                    </p>
                  </Panel>
                  <Panel>
                    <p className="text-sm text-slate-400">Failed runs shown</p>
                    <p className="mt-3 text-3xl font-bold text-rose-300">
                      {formatNumber(runsData.filter((run) => run.status.toLowerCase() === 'failed').length)}
                    </p>
                  </Panel>
                </div>

                <Panel>
                  <SectionHeading
                    title="Execution history"
                    description="Recent pipeline runs, their status, processing counts, and duration."
                  />

                  <div className="space-y-3">
                    {runsData.map((run) => {
                      const inputTotal = Object.values(run.input_counts ?? {}).reduce(
                        (sum, count) => sum + count,
                        0,
                      )
                      const outputTotal = Object.values(run.output_counts ?? {}).reduce(
                        (sum, count) => sum + count,
                        0,
                      )

                      return (
                        <article
                          key={run.run_id}
                          className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 transition hover:border-white/[0.13]"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="font-medium text-white">
                                Pipeline batch <span className="font-mono text-violet-300">{run.batch_id.slice(0, 12)}…</span>
                              </p>
                              <p className="mt-2 text-xs text-slate-500">
                                Started {formatDate(run.started_at)}
                              </p>
                            </div>
                            <StatusPill status={run.status} />
                          </div>

                          <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
                            <div>
                              <p className="text-xs text-slate-500">Input rows</p>
                              <p className="mt-1 text-lg font-semibold">{formatNumber(inputTotal)}</p>
                            </div>
                            <div>
                              <p className="text-xs text-slate-500">Output rows</p>
                              <p className="mt-1 text-lg font-semibold">{formatNumber(outputTotal)}</p>
                            </div>
                            <div>
                              <p className="text-xs text-slate-500">Rejected records</p>
                              <p className="mt-1 text-lg font-semibold text-amber-300">
                                {formatNumber(run.rejected_count)}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-slate-500">Duration</p>
                              <p className="mt-1 text-lg font-semibold">
                                {durationSeconds(run.started_at, run.ended_at)}
                              </p>
                            </div>
                          </div>

                          <details className="mt-4 border-t border-white/[0.06] pt-3">
                            <summary className="cursor-pointer text-xs text-violet-300 hover:text-violet-200">
                              View run details
                            </summary>
                            <div className="mt-3 grid gap-4 sm:grid-cols-2">
                              <div>
                                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                                  Input counts
                                </p>
                                <pre className="overflow-x-auto rounded-lg bg-black/20 p-3 text-xs text-slate-300">
                                  {JSON.stringify(run.input_counts, null, 2)}
                                </pre>
                              </div>
                              <div>
                                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                                  Output counts
                                </p>
                                <pre className="overflow-x-auto rounded-lg bg-black/20 p-3 text-xs text-slate-300">
                                  {JSON.stringify(run.output_counts, null, 2)}
                                </pre>
                              </div>
                            </div>
                            {run.error_message && (
                              <p className="mt-3 rounded-lg bg-rose-400/5 p-3 text-xs text-rose-300">
                                {run.error_message}
                              </p>
                            )}
                            <p className="mt-3 break-all font-mono text-[10px] text-slate-600">
                              Run ID: {run.run_id}
                            </p>
                          </details>
                        </article>
                      )
                    })}

                    {!pageLoading && runsData.length === 0 && (
                      <p className="py-10 text-center text-sm text-slate-500">
                        No pipeline runs found.
                      </p>
                    )}
                  </div>
                </Panel>
              </div>
            )}

            <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.07] py-5 text-xs text-slate-600">
              <span>Customer360 · Data engineering workspace</span>
              <span>React + FastAPI + PostgreSQL</span>
            </footer>
          </div>
        </main>
      </div>
    </div>
  )
}

export default App
