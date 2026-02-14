import { useEffect, useMemo, useState } from 'react'
import { createDemoEmbedBurst, getJobs } from '../api/edgemesh'
import type { Job, JobStatus, TaskType } from '../types'

const STATUS_OPTIONS: Array<JobStatus | 'ALL'> = [
  'ALL',
  'QUEUED',
  'RUNNING',
  'COMPLETED',
  'FAILED',
  'CANCELLED',
]
const TASK_OPTIONS: Array<TaskType | 'ALL'> = [
  'ALL',
  'INFERENCE',
  'EMBEDDINGS',
  'INDEX',
  'TOKENIZE',
  'PREPROCESS',
]

function formatDuration(job: Job): string {
  const start = job.started_at ? Date.parse(job.started_at) : Number.NaN

  if (Number.isNaN(start)) {
    return '-'
  }

  const end = job.completed_at ? Date.parse(job.completed_at) : Date.now()
  if (Number.isNaN(end) || end < start) {
    return '-'
  }

  return `${Math.floor((end - start) / 1000)}s`
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleTimeString()
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<JobStatus | 'ALL'>('ALL')
  const [taskFilter, setTaskFilter] = useState<TaskType | 'ALL'>('ALL')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true

    const load = async () => {
      try {
        const payload = await getJobs({
          status: statusFilter,
          taskType: taskFilter,
        })
        if (!active) {
          return
        }
        setJobs(payload)
        setError(null)
      } catch (err) {
        if (!active) {
          return
        }
        setError(err instanceof Error ? err.message : 'Failed to load jobs')
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void load()
    const id = window.setInterval(() => {
      void load()
    }, 5000)

    return () => {
      active = false
      window.clearInterval(id)
    }
  }, [statusFilter, taskFilter])

  const sortedJobs = useMemo(
    () =>
      [...jobs].sort(
        (left, right) =>
          Date.parse(right.created_at) - Date.parse(left.created_at)
      ),
    [jobs]
  )

  const triggerDemoBurst = async () => {
    setBusy(true)
    try {
      await createDemoEmbedBurst(20)
      const payload = await getJobs({
        status: statusFilter,
        taskType: taskFilter,
      })
      setJobs(payload)
      setError(null)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to create demo jobs'
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="page">
      <header>
        <h1>Jobs</h1>
      </header>

      <section className="surface jobs-controls">
        <label>
          Task type{' '}
          <select
            value={taskFilter}
            onChange={(event) =>
              setTaskFilter(event.target.value as TaskType | 'ALL')
            }
          >
            {TASK_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label>
          Status{' '}
          <select
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as JobStatus | 'ALL')
            }
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => void triggerDemoBurst()}
          disabled={busy}
        >
          {busy ? 'Creating...' : 'Create Demo Embed Burst'}
        </button>
      </section>

      {loading && <p>Loading jobs...</p>}
      {error && <p>{error}</p>}

      <section className="surface table-wrap">
        <table>
          <thead>
            <tr>
              <th>job_id</th>
              <th>task_type</th>
              <th>status</th>
              <th>node</th>
              <th>created_at</th>
              <th>duration</th>
              <th>attempts</th>
              <th>error</th>
            </tr>
          </thead>
          <tbody>
            {sortedJobs.map((job) => (
              <tr key={job.id}>
                <td>{job.id}</td>
                <td>{job.type}</td>
                <td>{job.status}</td>
                <td>{job.assigned_node_id ?? '-'}</td>
                <td>{formatTimestamp(job.created_at)}</td>
                <td>{formatDuration(job)}</td>
                <td>{job.attempts}</td>
                <td>{job.error ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </section>
  )
}
