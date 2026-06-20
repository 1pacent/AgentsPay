import service from './index'

export const listScenarios = () =>
  service.get('/api/eco/scenarios')

export const listPersonas = () =>
  service.get('/api/eco/personas')

export const startRun = (data) =>
  service.post('/api/eco/run', data)

export const getRun = (runId) =>
  service.get(`/api/eco/run/${runId}`)

export const listRuns = () =>
  service.get('/api/eco/runs')

export const getMetrics = (runId) =>
  service.get(`/api/eco/metrics/${runId}`)

export const getReport = (runId) =>
  service.get(`/api/eco/report/${runId}`)

export const compareRuns = (runIds) =>
  service.post('/api/eco/compare', { run_ids: runIds })

export const ecoHealth = () =>
  service.get('/api/eco/health')
